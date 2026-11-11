#!/usr/bin/env python3
"""
export_to_tflite.py  --  LEO PATCH 1-lead sex model: PyTorch -> int8 TFLite (for the Axon NPU compiler)

What it does
  1. Loads a fine-tuned checkpoint (ECGSexClassifier, architecture copied from
     finetune_12lead_for_1lead_script.ipynb) with weights_only=True.
  2. Rebuilds the same network in Keras (channels-last), folding every BatchNorm into
     the preceding conv and using explicit symmetric padding so it matches PyTorch
     (TF "same" padding is asymmetric for stride 2, which would silently change results).
  3. Quantizes to full-integer int8 with TFLite (int8 input, int8 output), calibrated on
     either DUMMY synthetic ECG windows (default) or your real windows (--calib-npy).
  4. Checks parity:  PyTorch fp32  vs  Keras fp32  vs  TFLite int8,
     lists the TFLite ops used (compare against Axon's supported-op list), and saves
     the int8 test vectors for the later on-device comparison.

NOTE: with the default dummy data the *conversion*, shapes, ops and memory numbers are
meaningful, but the accuracy-after-quantization numbers are NOT. Re-run with --calib-npy
pointing at real 1-lead windows before trusting any accuracy conclusion.

Requirements:  pip install torch tensorflow numpy
Usage (from this folder):
  python export_to_tflite.py
  python export_to_tflite.py --checkpoint models/2026.10.09/2_best_ecg_sex_leadv1_finetuned_15epochs.pth
  python export_to_tflite.py --calib-npy my_windows.npy      # float array, shape (N, 5000), raw 1-lead ECG
"""
import argparse
import collections
import glob
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np

HERE = Path(__file__).resolve().parent
DEFAULT_CKPT = HERE.parent / "models" / "2026.10.08" / "2_best_ecg_sex_leadv3_finetuned_15epochs.pth"
SEQ_LEN = 5000  # 10 s at 500 Hz (MIMIC-IV-ECG)
BN_EPS = 1e-5   # PyTorch BatchNorm default


# --------------------------------------------------------------------------------------
# Data helpers
# --------------------------------------------------------------------------------------
def zscore(sig):
    """Same per-window normalisation as the training notebook (z-score, std floor)."""
    sig = np.nan_to_num(sig.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    mean = sig.mean(axis=-1, keepdims=True)
    std = sig.std(axis=-1, keepdims=True)
    std = np.where(std < 1e-6, 1.0, std)
    return ((sig - mean) / std).astype(np.float32)


def make_dummy_ecg(n, length=SEQ_LEN, fs=500, seed=0):
    """Synthetic single-lead ECG-like windows (P-QRS-T gaussians + baseline wander + noise).
    Only for exercising the toolchain. NOT physiologically validated, NOT real data."""
    rng = np.random.default_rng(seed)
    t = np.arange(length) / fs
    out = np.zeros((n, length), dtype=np.float32)
    # (offset s, amplitude, sigma s) relative to the R peak
    waves = [(-0.20, 0.15, 0.025), (-0.04, -0.10, 0.010), (0.0, 1.00, 0.012),
             (0.03, -0.25, 0.012), (0.25, 0.30, 0.045)]
    for i in range(n):
        bpm = rng.uniform(55, 110)
        rr = 60.0 / bpm
        beat = rng.uniform(0.2, 0.8)
        sig = np.zeros(length)
        amp_scale = rng.uniform(0.6, 1.6)
        while beat < t[-1] + 0.5:
            for off, amp, sd in waves:
                sig += amp_scale * amp * np.exp(-0.5 * ((t - (beat + off)) / sd) ** 2)
            beat += rr * rng.uniform(0.95, 1.05)
        sig += rng.uniform(0.05, 0.3) * np.sin(2 * np.pi * rng.uniform(0.15, 0.4) * t + rng.uniform(0, 6.28))
        sig += rng.uniform(0.0, 0.05) * np.sin(2 * np.pi * 60 * t)
        sig += rng.normal(0, rng.uniform(0.01, 0.05), length)
        out[i] = sig
    return zscore(out)


# --------------------------------------------------------------------------------------
# PyTorch reference model (copied from the notebook, same state_dict keys)
# --------------------------------------------------------------------------------------
def build_torch_model():
    import torch.nn as nn

    class ResBlock1D(nn.Module):
        def __init__(self, channels, dropout_rate=0.2):
            super().__init__()
            self.conv1 = nn.Conv1d(channels, channels, kernel_size=7, padding=3)
            self.bn1 = nn.BatchNorm1d(channels)
            self.relu = nn.ReLU()
            self.drop = nn.Dropout1d(dropout_rate)
            self.conv2 = nn.Conv1d(channels, channels, kernel_size=7, padding=3)
            self.bn2 = nn.BatchNorm1d(channels)

        def forward(self, x):
            residual = x
            out = self.relu(self.bn1(self.conv1(x)))
            out = self.drop(out)
            out = self.bn2(self.conv2(out))
            out += residual
            return self.relu(out)

    class ECGSexClassifier(nn.Module):
        def __init__(self, in_channels=1):
            super().__init__()
            self.stem = nn.Sequential(
                nn.Conv1d(in_channels, 64, kernel_size=15, stride=2, padding=7),
                nn.BatchNorm1d(64), nn.ReLU(),
                nn.MaxPool1d(kernel_size=3, stride=2, padding=1))
            self.layer1 = nn.Sequential(
                nn.Conv1d(64, 128, kernel_size=7, stride=2, padding=3),
                nn.BatchNorm1d(128), nn.ReLU())
            self.res1 = ResBlock1D(128)
            self.layer2 = nn.Sequential(
                nn.Conv1d(128, 256, kernel_size=7, stride=2, padding=3),
                nn.BatchNorm1d(256), nn.ReLU())
            self.res2 = ResBlock1D(256)
            self.global_pool = nn.AdaptiveAvgPool1d(1)
            self.fc = nn.Sequential(nn.Dropout(0.5), nn.Linear(256, 64), nn.ReLU(), nn.Linear(64, 1))

        def forward(self, x):
            x = self.stem(x)
            x = self.res1(self.layer1(x))
            x = self.res2(self.layer2(x))
            x = self.global_pool(x).squeeze(-1)
            return self.fc(x)

    return ECGSexClassifier(in_channels=1)


# --------------------------------------------------------------------------------------
# Keras twin + BatchNorm folding
# --------------------------------------------------------------------------------------
def fold_bn(sd, conv_key, bn_key):
    """Fold BatchNorm into the preceding conv. Returns Keras kernel (k, in, out) and bias (out,)."""
    w = sd[f"{conv_key}.weight"].numpy().astype(np.float64)   # (out, in, k)
    b = sd[f"{conv_key}.bias"].numpy().astype(np.float64)
    gamma = sd[f"{bn_key}.weight"].numpy().astype(np.float64)
    beta = sd[f"{bn_key}.bias"].numpy().astype(np.float64)
    mean = sd[f"{bn_key}.running_mean"].numpy().astype(np.float64)
    var = sd[f"{bn_key}.running_var"].numpy().astype(np.float64)
    scale = gamma / np.sqrt(var + BN_EPS)
    w_f = w * scale[:, None, None]
    b_f = (b - mean) * scale + beta
    return w_f.transpose(2, 1, 0).astype(np.float32), b_f.astype(np.float32)


def build_keras(length, sd):
    import tensorflow as tf
    L = tf.keras.layers

    def conv(x, name, ch, k, stride, pad):
        if stride == 1:
            return L.Conv1D(ch, k, padding="same", name=name)(x)  # odd k, stride 1 => symmetric
        x = L.ZeroPadding1D(pad, name=name + "_pad")(x)
        return L.Conv1D(ch, k, strides=stride, padding="valid", name=name)(x)

    inp = tf.keras.Input(shape=(length, 1), batch_size=1, name="ecg")
    x = conv(inp, "stem_conv", 64, 15, 2, 7)
    x = L.ReLU(name="stem_relu")(x)
    # PyTorch MaxPool pads with -inf; input is post-ReLU (>=0) so zero padding is equivalent.
    x = L.ZeroPadding1D(1, name="stem_pool_pad")(x)
    x = L.MaxPooling1D(3, strides=2, padding="valid", name="stem_pool")(x)
    x = conv(x, "layer1_conv", 128, 7, 2, 3)
    x = L.ReLU(name="layer1_relu")(x)
    for blk, ch in (("res1", 128), ("res2", 256)):
        if blk == "res2":
            x = conv(x, "layer2_conv", 256, 7, 2, 3)
            x = L.ReLU(name="layer2_relu")(x)
        r = x
        y = conv(x, f"{blk}_conv1", ch, 7, 1, 3)
        y = L.ReLU(name=f"{blk}_relu1")(y)
        y = conv(y, f"{blk}_conv2", ch, 7, 1, 3)
        x = L.ReLU(name=f"{blk}_out")(L.Add(name=f"{blk}_add")([y, r]))
    x = L.GlobalAveragePooling1D(name="gap")(x)
    x = L.Dense(64, activation="relu", name="fc1")(x)
    out = L.Dense(1, name="fc2")(x)
    model = tf.keras.Model(inp, out, name="ecg_sex_int8")

    # relu after the first stem/layer convs is a separate layer for clarity; TFLite fuses it.
    pairs = {"stem_conv": ("stem.0", "stem.1"), "layer1_conv": ("layer1.0", "layer1.1"),
             "res1_conv1": ("res1.conv1", "res1.bn1"), "res1_conv2": ("res1.conv2", "res1.bn2"),
             "layer2_conv": ("layer2.0", "layer2.1"),
             "res2_conv1": ("res2.conv1", "res2.bn1"), "res2_conv2": ("res2.conv2", "res2.bn2")}
    for name, (c, b) in pairs.items():
        model.get_layer(name).set_weights(list(fold_bn(sd, c, b)))
    model.get_layer("fc1").set_weights([sd["fc.1.weight"].numpy().T, sd["fc.1.bias"].numpy()])
    model.get_layer("fc2").set_weights([sd["fc.3.weight"].numpy().T, sd["fc.3.bias"].numpy()])
    return model


# --------------------------------------------------------------------------------------
# Quantize + run TFLite
# --------------------------------------------------------------------------------------
def quantize(model, calib, per_tensor):
    import tensorflow as tf

    def rep():
        for w in calib:
            yield [w.reshape(1, -1, 1).astype(np.float32)]

    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = rep
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.int8
    conv.inference_output_type = tf.int8
    if per_tensor:
        conv._experimental_disable_per_channel = True  # private flag; try if Axon rejects per-channel weights
    return conv.convert()


def run_tflite(tflite_bytes, windows):
    import tensorflow as tf
    try:  # newer LiteRT package if installed, else the (deprecated) TF interpreter
        from ai_edge_litert.interpreter import Interpreter, OpResolverType
        it = Interpreter(model_content=tflite_bytes,
                         experimental_op_resolver_type=OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    except Exception:
        # no XNNPACK delegate, so every op shows up individually in the op list
        it = tf.lite.Interpreter(
            model_content=tflite_bytes,
            experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    it.allocate_tensors()
    i_d, o_d = it.get_input_details()[0], it.get_output_details()[0]
    i_s, i_zp = i_d["quantization"]
    o_s, o_zp = o_d["quantization"]
    q_in = np.clip(np.round(windows / i_s + i_zp), -128, 127).astype(np.int8)
    q_out = np.zeros(len(windows), dtype=np.int8)
    for k in range(len(windows)):
        it.set_tensor(i_d["index"], q_in[k].reshape(1, -1, 1))
        it.invoke()
        q_out[k] = it.get_tensor(o_d["index"]).reshape(-1)[0]
    logits = (q_out.astype(np.float32) - o_zp) * o_s
    return logits, q_in, q_out, it, (i_s, i_zp, o_s, o_zp)


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


def find_threshold(ckpt, user_thr):
    if user_thr is not None:
        return user_thr, "--threshold"
    hits = glob.glob(str(Path(ckpt).parent / "*epoch_outputs*.npz"))
    if len(hits) == 1:
        d = np.load(hits[0], allow_pickle=False)
        return float(d["val_threshold"]), os.path.basename(hits[0])
    return 0.5, "default 0.5"


# --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checkpoint", default=str(DEFAULT_CKPT))
    ap.add_argument("--out-dir", default=str(HERE / "export_out"))
    ap.add_argument("--calib-npy", help="float32 .npy of REAL windows, shape (N, 5000); z-scored here")
    ap.add_argument("--n-calib", type=int, default=200)
    ap.add_argument("--n-test", type=int, default=64)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--threshold", type=float, default=None, help="decision threshold on probability")
    ap.add_argument("--per-tensor", action="store_true", help="disable per-channel conv weight quantization")
    args = ap.parse_args()

    import torch
    import tensorflow as tf

    ckpt = Path(args.checkpoint)
    tag = ckpt.stem.replace("2_best_ecg_sex_", "").replace("_finetuned_15epochs", "")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) data
    if args.calib_npy:
        real = np.load(args.calib_npy, allow_pickle=False)
        assert real.ndim == 2 and real.shape[1] == SEQ_LEN, f"expected (N, {SEQ_LEN}), got {real.shape}"
        real = zscore(real)
        n_test = min(args.n_test, len(real) // 4)               # held-out windows for the parity check
        test = real[len(real) - n_test:]
        calib = real[: len(real) - n_test][: args.n_calib]      # never overlaps the held-out windows
        data_kind = f"REAL windows from {args.calib_npy} ({len(real)})"
    else:
        calib = make_dummy_ecg(args.n_calib, seed=args.seed)
        test = make_dummy_ecg(args.n_test, seed=args.seed + 1)
        data_kind = "DUMMY synthetic ECG (toolchain test only)"
    print(f"[data] calibration={len(calib)} test={len(test)}  source: {data_kind}")

    # 2) PyTorch reference
    sd = torch.load(ckpt, map_location="cpu", weights_only=True)
    tmodel = build_torch_model()
    tmodel.load_state_dict(sd)
    tmodel.eval()
    with torch.no_grad():
        ref = tmodel(torch.from_numpy(test).unsqueeze(1)).squeeze(-1).numpy()
    print(f"[torch] logits on test windows: mean={ref.mean():.3f} std={ref.std():.3f} "
          f"min={ref.min():.3f} max={ref.max():.3f}")

    # 3) Keras twin (checks BN folding + padding)
    km = build_keras(SEQ_LEN, sd)
    kout = np.concatenate([km(test[i:i + 1].reshape(1, -1, 1), training=False).numpy().reshape(-1)
                           for i in range(len(test))])
    k_err = np.abs(kout - ref).max()
    print(f"[keras fp32 vs torch] max|diff| = {k_err:.2e}   (expect ~1e-4 or smaller)")
    if k_err > 1e-2:
        sys.exit("Keras twin does not match PyTorch -- stop and fix before quantizing.")

    # 4) Quantize
    tfl = quantize(km, calib, args.per_tensor)
    tfl_path = out_dir / f"ecg_sex_{tag}_int8.tflite"
    tfl_path.write_bytes(tfl)
    print(f"[tflite] wrote {tfl_path}  ({len(tfl) / 1024:.0f} KiB)")

    # 5) Parity
    qlog, q_in, q_out, it, (i_s, i_zp, o_s, o_zp) = run_tflite(tfl, test)
    err = np.abs(qlog - ref)
    corr = float(np.corrcoef(qlog, ref)[0, 1]) if ref.std() > 0 and qlog.std() > 0 else float("nan")
    thr, thr_src = find_threshold(ckpt, args.threshold)
    agree = float(((sigmoid(qlog) >= thr) == (sigmoid(ref) >= thr)).mean())
    print(f"[int8 vs torch fp32] mean|err|={err.mean():.3f}  max|err|={err.max():.3f}  corr={corr:.4f}  "
          f"decision agreement@{thr:.3f} ({thr_src}) = {agree:.1%}")
    print(f"[quant] input scale={i_s:.5f} zp={i_zp}   output scale={o_s:.5f} zp={o_zp}")

    # 6) Ops + biggest tensors
    try:
        ops = collections.Counter(d["op_name"] for d in it._get_ops_details())
    except Exception:
        ops = {}
    print("[ops] " + (", ".join(f"{k} x{v}" for k, v in sorted(ops.items())) or "(unavailable)"))
    # activation tensors have batch dim 1; weight tensors start with the output-channel count
    sizes = sorted(((int(np.prod(t["shape"])), t["name"], [int(s) for s in t["shape"]])
                    for t in it.get_tensor_details() if t["dtype"] == np.int8 and t["shape"][0] == 1
                    and len(t["shape"]) >= 3 and t["name"]), reverse=True)[:4]  # unnamed = interpreter scratch
    for n, name, shape in sizes:
        print(f"[act] {n / 1024:7.1f} KiB int8  {shape}  {name[-45:]}")
    print("[act] (peak RAM is roughly the largest in+out pair, plus the residual copy; "
          "the Axon compiler reports the real number)")

    # 7) Artifacts for the later on-device check
    np.savez(out_dir / f"parity_vectors_{tag}.npz", inputs_int8=q_in[:16], outputs_int8=q_out[:16],
             torch_logits=ref[:16], input_scale=i_s, input_zp=i_zp, output_scale=o_s, output_zp=o_zp)
    report = dict(checkpoint=str(ckpt), data=data_kind, tflite_kib=round(len(tfl) / 1024, 1),
                  keras_vs_torch_max_abs=float(k_err), int8_mean_abs_err=float(err.mean()),
                  int8_max_abs_err=float(err.max()), int8_corr=corr, decision_agreement=agree,
                  threshold=thr, ops=dict(ops), tf_version=tf.__version__, torch_version=torch.__version__)
    (out_dir / f"export_report_{tag}.json").write_text(json.dumps(report, indent=2))
    print(f"[done] outputs in {out_dir}")


if __name__ == "__main__":
    main()
