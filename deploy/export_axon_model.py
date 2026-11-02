#!/usr/bin/env python3
# Export the 1-lead ECG sex classifier (ECGSexClassifier) for the nRF54LM20B Axon NPU.
#
# The Axon NPU caps every tensor dimension at 1024, but this model takes a 5000-sample
# input (stem output 2500, max-pool output 1250). So the model is split in two:
#   front end (Cortex-M33 CPU, float): stem conv + BN + ReLU + max-pool -> 64 x 1250,
#       stored as 2 interleaved phases -> 128 channels x 625 (channel = phase * 64 + c)
#   NPU part (int8 TFLite -> Axon compiler): everything after the max-pool. The stride-2
#       layer1 conv over 1250 samples is rewritten as an equivalent stride-1 conv over the
#       2 phases, so every tensor fits the NPU limits. The math is identical to PyTorch.
#
# Usage (from the repo root, inside the axon venv):
#   python deploy/export_axon_model.py                       # synthetic ECGs for calibration
#   python deploy/export_axon_model.py --calib-npy v3.npy    # real (N, 5000) lead-V3 ECGs
#   python deploy/export_axon_model.py --calib-npy v3.npy --labels-npy v3_labels.npy

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import yaml

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import tensorflow as tf  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SIG_LEN = 5000
STEM_OUT = 2500
POOL_OUT = 1250
NPU_W = POOL_OUT // 2      # 625
NPU_C = 128                # 2 phases x 64 stem channels


# Same architecture as finetune_12lead_for_1lead_script.ipynb
# -------------------------------------------------------------------------
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
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=3, stride=2, padding=1)
        )
        self.layer1 = nn.Sequential(
            nn.Conv1d(64, 128, kernel_size=7, stride=2, padding=3),
            nn.BatchNorm1d(128),
            nn.ReLU()
        )
        self.res1 = ResBlock1D(128)
        self.layer2 = nn.Sequential(
            nn.Conv1d(128, 256, kernel_size=7, stride=2, padding=3),
            nn.BatchNorm1d(256),
            nn.ReLU()
        )
        self.res2 = ResBlock1D(256)
        self.global_pool = nn.AdaptiveAvgPool1d(1)
        self.fc = nn.Sequential(
            nn.Dropout(0.5),
            nn.Linear(256, 64),
            nn.ReLU(),
            nn.Linear(64, 1)
        )

    def forward(self, x):
        x = self.stem(x)
        x = self.res1(self.layer1(x))
        x = self.res2(self.layer2(x))
        x = self.global_pool(x).squeeze(-1)
        return self.fc(x)


# Data
# -------------------------------------------------------------------------
def preprocess(sig):
    """Per-ECG z-score, identical to MIMICECGSingleLeadDataset.__getitem__."""
    sig = np.nan_to_num(np.asarray(sig, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    mean = sig.mean(axis=1, keepdims=True)
    std = sig.std(axis=1, keepdims=True)
    std = np.where(std < 1e-6, 1.0, std)
    return ((sig - mean) / std).astype(np.float32)


def synthetic_ecgs(n, seed):
    """Synthetic 10 s / 500 Hz ECGs. Only a stand-in until real lead-V3 data is available."""
    import neurokit2 as nk
    rng = np.random.default_rng(seed)
    out = np.empty((n, SIG_LEN), np.float32)
    t = np.arange(SIG_LEN) / 500.0
    for i in range(n):
        ecg = nk.ecg_simulate(duration=10, sampling_rate=500, method="ecgsyn",
                              heart_rate=rng.uniform(50, 110), heart_rate_std=rng.uniform(0.5, 5),
                              noise=rng.uniform(0.0, 0.05), random_state=int(rng.integers(2**31)))
        wander = rng.uniform(0, 0.2) * np.sin(2 * np.pi * rng.uniform(0.1, 0.5) * t + rng.uniform(0, 6.3))
        out[i] = (np.asarray(ecg)[:SIG_LEN] + wander) * rng.choice([-1.0, 1.0]) * rng.uniform(0.5, 2.0)
    return out


# Weights
# -------------------------------------------------------------------------
def fold_bn(conv, bn):
    w = conv.weight.detach().double().numpy()
    b = conv.bias.detach().double().numpy()
    scale = (bn.weight.detach().double() / torch.sqrt(bn.running_var.double() + bn.eps)).numpy()
    w = w * scale[:, None, None]
    b = (b - bn.running_mean.detach().double().numpy()) * scale + bn.bias.detach().double().numpy()
    return w.astype(np.float32), b.astype(np.float32)


def tf_kernel(w):
    """PyTorch Conv1d weight (out, in, k) -> TF conv2d kernel (1, k, in, out)."""
    return np.ascontiguousarray(w.transpose(2, 1, 0)[None])


def build_params(model):
    stem_w, stem_b = fold_bn(model.stem[0], model.stem[1])

    # layer1: y[n] = sum_k w[k] p[2n + k - 3] over the 1250-long pooled signal p.
    # With phases P[e*64 + c][m] = p[c][2m + e], tap j of a stride-1, k=5, SAME conv reads
    # P[:, n + j - 2] = p[2n + 2j - 4 + e], so it carries original tap k = 2j + e - 1.
    w1, b1 = fold_bn(model.layer1[0], model.layer1[1])
    k1 = np.zeros((1, 5, NPU_C, 128), np.float32)
    for j in range(5):
        for e in range(2):
            k = 2 * j + e - 1
            if 0 <= k < 7:
                k1[0, j, e * 64:(e + 1) * 64, :] = w1[:, :, k].T

    p = {"layer1_w": k1, "layer1_b": b1}
    for name, conv, bn in [
        ("res1_c1", model.res1.conv1, model.res1.bn1),
        ("res1_c2", model.res1.conv2, model.res1.bn2),
        ("layer2", model.layer2[0], model.layer2[1]),
        ("res2_c1", model.res2.conv1, model.res2.bn1),
        ("res2_c2", model.res2.conv2, model.res2.bn2),
    ]:
        w, b = fold_bn(conv, bn)
        p[name + "_w"], p[name + "_b"] = tf_kernel(w), b
    for name, lin in [("fc1", model.fc[1]), ("fc2", model.fc[3])]:
        p[name + "_w"] = np.ascontiguousarray(lin.weight.detach().numpy().T)
        p[name + "_b"] = lin.bias.detach().numpy().copy()
    return stem_w[:, 0, :], stem_b, p


# Front end (mirrored in firmware/ecg_sex_axon/src/frontend.c)
# -------------------------------------------------------------------------
def frontend(x, stem_w, stem_b, batch=64):
    """Normalized ECGs (N, 5000) -> NPU input (N, 128, 625): stem + max-pool + 2 phases."""
    idx = 2 * np.arange(STEM_OUT)[:, None] + np.arange(15)[None, :]
    out = np.empty((len(x), NPU_C, NPU_W), np.float32)
    for s in range(0, len(x), batch):
        xp = np.pad(x[s:s + batch], ((0, 0), (7, 7)))
        z = np.einsum("ntk,ck->nct", xp[:, idx], stem_w) + stem_b[None, :, None]
        # ReLU output is >= 0, so zero padding is equivalent to MaxPool1d's -inf padding
        zp = np.pad(np.maximum(z, 0), ((0, 0), (0, 0), (1, 1)))
        pooled = np.maximum(np.maximum(zp[:, :, 0:2 * POOL_OUT:2], zp[:, :, 1:2 * POOL_OUT + 1:2]),
                            zp[:, :, 2:2 * POOL_OUT + 2:2])
        out[s:s + batch] = np.concatenate([pooled[:, :, 0::2], pooled[:, :, 1::2]], axis=1)
    return out


def to_nhwc(P):
    return np.ascontiguousarray(P.transpose(0, 2, 1)[:, None, :, :])


# NPU part
# -------------------------------------------------------------------------
class NpuPart(tf.Module):
    def __init__(self, params):
        super().__init__()
        self.p = {k: tf.constant(v) for k, v in params.items()}

    def forward(self, x):
        p = self.p

        def conv(x, name, stride=1):
            y = tf.nn.conv2d(x, p[name + "_w"], strides=[1, 1, stride, 1], padding="SAME")
            return tf.nn.bias_add(y, p[name + "_b"])

        x = tf.nn.relu(conv(x, "layer1"))
        y = conv(tf.nn.relu(conv(x, "res1_c1")), "res1_c2")
        x = tf.nn.relu(y + x)
        x = tf.nn.relu(conv(x, "layer2", stride=2))
        y = conv(tf.nn.relu(conv(x, "res2_c1")), "res2_c2")
        x = tf.nn.relu(y + x)
        # Global average pool over 313 samples. Axon's MEAN stores its window in a uint8, so
        # first sum 31-sample windows (SAME padding adds zeros, each sample lands in exactly one
        # window) with a depthwise conv, then MEAN the 11 window sums.
        width, win = x.shape[2], 31
        n_win = -(-width // win)
        x = tf.nn.depthwise_conv2d(x, tf.fill([1, win, x.shape[3], 1], n_win / width),
                                   strides=[1, win, win, 1], padding="SAME")
        x = tf.reduce_mean(x, axis=[1, 2])
        x = tf.nn.relu(tf.matmul(x, p["fc1_w"]) + p["fc1_b"])
        return tf.matmul(x, p["fc2_w"]) + p["fc2_b"]

    @tf.function(input_signature=[tf.TensorSpec([1, 1, NPU_W, NPU_C], tf.float32)])
    def single(self, x):
        return self.forward(x)

    @tf.function(input_signature=[tf.TensorSpec([None, 1, NPU_W, NPU_C], tf.float32)])
    def batched(self, x):
        return self.forward(x)


def convert_int8(npu, calib_nhwc):
    def representative():
        for s in calib_nhwc:
            yield [s[None]]

    conv = tf.lite.TFLiteConverter.from_concrete_functions([npu.single.get_concrete_function()], npu)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = representative
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.int8
    conv.inference_output_type = tf.int8
    return conv.convert()


class Int8Runner:
    def __init__(self, tflite_bytes):
        self.it = tf.lite.Interpreter(model_content=tflite_bytes)
        self.it.allocate_tensors()
        self.inp = self.it.get_input_details()[0]
        self.out = self.it.get_output_details()[0]
        self.in_scale, self.in_zp = self.inp["quantization"]
        self.out_scale, self.out_zp = self.out["quantization"]

    def quantize(self, x):
        return np.clip(np.round(x / self.in_scale) + self.in_zp, -128, 127).astype(np.int8)

    def __call__(self, x_q):
        self.it.set_tensor(self.inp["index"], x_q[None])
        self.it.invoke()
        q = int(self.it.get_tensor(self.out["index"]).reshape(-1)[0])
        return (q - self.out_zp) * self.out_scale


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


# C headers for the firmware
# -------------------------------------------------------------------------
def c_floats(a, per_line=8):
    a = np.asarray(a, np.float32).reshape(-1)
    lines = [", ".join(f"{v:.9g}f" for v in a[i:i + per_line]) for i in range(0, len(a), per_line)]
    return "\t" + ",\n\t".join(lines)


def write_frontend_header(path, stem_w, stem_b):
    rows = ",\n".join("\t{" + c_floats(r, 15).strip() + "}" for r in stem_w)
    path.write_text(
        "/* Generated by deploy/export_axon_model.py: stem conv with BatchNorm folded in. */\n"
        "#pragma once\n\n"
        "#define FRONTEND_STEM_CHANNELS 64\n#define FRONTEND_STEM_KERNEL 15\n\n"
        f"static const float frontend_stem_w[64][15] = {{\n{rows}\n}};\n\n"
        f"static const float frontend_stem_b[64] = {{\n{c_floats(stem_b)}\n}};\n")


def write_test_ecg_header(path, raw, ref_float, ref_int8, threshold, source):
    body = ",\n".join("{\n" + c_floats(r, 10) + "\n}" for r in raw)
    path.write_text(
        f"/* Generated by deploy/export_axon_model.py: {len(raw)} {source} test ECGs (raw, 500 Hz). */\n"
        "#pragma once\n\n"
        f"#define TEST_ECG_COUNT {len(raw)}\n#define TEST_ECG_LEN {SIG_LEN}\n\n"
        "/* Decision threshold on sigmoid(logit), chosen on the validation set during training. */\n"
        f"#define MODEL_VAL_THRESHOLD {threshold:.6f}f\n\n"
        f"static const float test_ecg[TEST_ECG_COUNT][TEST_ECG_LEN] = {{\n{body}\n}};\n\n"
        "/* Expected logits: PyTorch float model and int8 TFLite reference. */\n"
        f"static const float test_ecg_logit_float[TEST_ECG_COUNT] = {{\n{c_floats(ref_float)}\n}};\n"
        f"static const float test_ecg_logit_int8[TEST_ECG_COUNT] = {{\n{c_floats(ref_int8)}\n}};\n")


# Axon compiler
# -------------------------------------------------------------------------
def run_axon_compiler(addon_dir, out_dir, model_name, tflite_path, test_q_path, il_buffer):
    compiler_dir = addon_dir / "tools/axon/compiler"
    template = yaml.safe_load((compiler_dir / "scripts/compiler_input_yaml_template.yaml").read_text())
    cfg = {k: None for k in next(iter(template.values()))}
    cfg.update(model_name=model_name, tflite_model=str(tflite_path), test_data=str(test_q_path),
               test_vectors="all", header_file_test_vector_cnt=2,
               interlayer_buffer_size=il_buffer, log_level="info")
    yaml_path = out_dir / f"compile_{model_name}.yaml"
    yaml_path.write_text(yaml.safe_dump({model_name: cfg}, sort_keys=False))
    print(f"\nRunning Axon compiler on {yaml_path} ...")
    res = subprocess.run([sys.executable, "scripts/axons_ml_nn_compiler_executor.py", str(yaml_path)],
                         cwd=compiler_dir)
    return res.returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", type=Path,
                    default=REPO / "models/2026.10.08/2_best_ecg_sex_leadv3_finetuned_15epochs.pth")
    ap.add_argument("--outputs-npz", type=Path,
                    default=REPO / "models/2026.10.08/2_best_epoch_outputs_leadv3_finetuned_15epochs.npz",
                    help="training outputs .npz holding val_threshold")
    ap.add_argument("--calib-npy", type=Path, help="(N, 5000) raw single-lead ECGs; synthetic if omitted")
    ap.add_argument("--labels-npy", type=Path, help="(N,) labels for --calib-npy, to report AUC")
    ap.add_argument("--n-synthetic", type=int, default=320)
    ap.add_argument("--n-eval", type=int, default=64, help="ECGs held out from calibration for evaluation")
    ap.add_argument("--n-firmware", type=int, default=4, help="test ECGs embedded in the firmware")
    ap.add_argument("--model-name", default="ecg_sex_v3")
    ap.add_argument("--out-dir", type=Path, default=REPO / "deploy/out")
    ap.add_argument("--firmware-dir", type=Path, default=REPO / "firmware/ecg_sex_axon/src/generated")
    ap.add_argument("--addon-dir", type=Path,
                    default=Path(os.environ.get("EDGE_AI_ADDON_DIR", "/opt/nordic/ncs/sdk-edge-ai")))
    ap.add_argument("--il-buffer", type=int, default=400000, help="Axon interlayer buffer upper bound")
    ap.add_argument("--skip-compile", action="store_true")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.firmware_dir.mkdir(parents=True, exist_ok=True)

    model = ECGSexClassifier(in_channels=1)
    model.load_state_dict(torch.load(args.checkpoint, map_location="cpu", weights_only=True))
    model.eval()
    threshold = float(np.load(args.outputs_npz)["val_threshold"]) if args.outputs_npz.exists() else 0.5
    print(f"Loaded {args.checkpoint.name} (val threshold {threshold:.4f})")

    if args.calib_npy:
        raw = np.load(args.calib_npy).astype(np.float32)
        source = "real"
    else:
        print(f"No --calib-npy given: generating {args.n_synthetic} synthetic ECGs for calibration")
        raw = synthetic_ecgs(args.n_synthetic, seed=0)
        source = "synthetic"
    assert raw.ndim == 2 and raw.shape[1] == SIG_LEN, f"expected (N, {SIG_LEN}), got {raw.shape}"
    labels = np.load(args.labels_npy) if args.labels_npy else None
    x = preprocess(raw)
    n_eval = min(args.n_eval, len(x) // 4)
    eval_idx = np.arange(len(x) - n_eval, len(x))
    calib_idx = np.arange(len(x) - n_eval)

    # 1) reference outputs from the PyTorch model
    with torch.no_grad():
        xt = torch.from_numpy(x[:, None, :])
        torch_pool = torch.cat([model.stem(xt[i:i + 64]) for i in range(0, len(x), 64)]).numpy()
        torch_logit = torch.cat([model(xt[i:i + 64]) for i in range(0, len(x), 64)]).numpy()[:, 0]

    # 2) split model, check the float rewrite matches PyTorch
    stem_w, stem_b, params = build_params(model)
    P = frontend(x, stem_w, stem_b)
    pool_back = np.empty_like(torch_pool)
    pool_back[:, :, 0::2], pool_back[:, :, 1::2] = P[:, :64], P[:, 64:]
    npu = NpuPart(params)
    P_nhwc = to_nhwc(P)
    split_logit = np.concatenate([npu.batched(P_nhwc[i:i + 32]).numpy()[:, 0] for i in range(0, len(x), 32)])
    err_pool = np.abs(pool_back - torch_pool).max()
    err_logit = np.abs(split_logit - torch_logit).max()
    print(f"Float split model vs PyTorch: front end max err {err_pool:.2e}, logit max err {err_logit:.2e}")
    if err_logit > 1e-3:
        sys.exit("Split model does not match PyTorch, aborting.")

    # 3) int8 quantization, calibrated on the non-eval ECGs
    tfl = convert_int8(npu, P_nhwc[calib_idx])
    tflite_path = args.out_dir / f"{args.model_name}_npu_int8.tflite"
    tflite_path.write_bytes(tfl)
    runner = Int8Runner(tfl)
    P_q = runner.quantize(P_nhwc)
    int8_logit = np.array([runner(P_q[i]) for i in eval_idx])
    ref = torch_logit[eval_idx]
    p_f, p_q = sigmoid(ref), sigmoid(int8_logit)
    print(f"int8 TFLite ({len(tfl) / 1024:.0f} KB) vs PyTorch on {n_eval} held-out {source} ECGs:")
    print(f"  logit  max err {np.abs(int8_logit - ref).max():.3f}, corr {np.corrcoef(int8_logit, ref)[0, 1]:.4f}")
    print(f"  prob   max err {np.abs(p_q - p_f).max():.3f}, mean err {np.abs(p_q - p_f).mean():.3f}")
    print(f"  same decision at threshold {threshold:.3f}: {np.mean((p_q >= threshold) == (p_f >= threshold)):.1%}")
    if labels is not None:
        from sklearn.metrics import roc_auc_score
        y = labels[eval_idx]
        print(f"  AUC float {roc_auc_score(y, p_f):.4f} | int8 {roc_auc_score(y, p_q):.4f}")

    # 4) artifacts: compiler test vectors, firmware headers
    test_q_path = args.out_dir / f"{args.model_name}_test_q.npy"
    np.save(test_q_path, P_q[eval_idx[:8]])
    fw_idx = eval_idx[:args.n_firmware]
    write_frontend_header(args.firmware_dir / "frontend_params.h", stem_w, stem_b)
    write_test_ecg_header(args.firmware_dir / "test_ecgs.h", raw[fw_idx], torch_logit[fw_idx],
                          [runner(P_q[i]) for i in fw_idx], threshold, source)
    print(f"Wrote {tflite_path.relative_to(REPO)} and firmware headers in {args.firmware_dir.relative_to(REPO)}")

    if args.skip_compile:
        return
    if not (args.addon_dir / "tools/axon/compiler").is_dir():
        sys.exit(f"Edge AI Add-on not found at {args.addon_dir}; set --addon-dir or EDGE_AI_ADDON_DIR")
    rc = run_axon_compiler(args.addon_dir, args.out_dir, args.model_name, tflite_path, test_q_path, args.il_buffer)
    header = args.out_dir / "outputs" / f"nrf_axon_model_{args.model_name}_.h"
    if rc == 0 and header.exists():
        shutil.copy(header, args.firmware_dir / header.name)
        print(f"Copied {header.name} to {args.firmware_dir.relative_to(REPO)}; set "
              "CONFIG_NRF_AXON_INTERLAYER_BUFFER_SIZE in prj.conf to at least its MAX_IL_BUFFER_USED")
    sys.exit(rc)


if __name__ == "__main__":
    main()
