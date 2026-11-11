#!/usr/bin/env python3
"""
eval_host.py  --  script 1 of 2.  Host-side evaluation of the LEO PATCH 1-lead sex model.

What it does (everything runs on your computer, no GPU and no PyTorch needed):
  1. Rebuilds Sara's exact patient-wise split (seed 42, 20k subjects, 70/15/15) from
     "Dataset for ECG/mimic_iv_ecg_clean_metadata.csv" and checks it against the labels saved in
     models/*/..._epoch_outputs_*.npz.
  2. Runs the fp32 checkpoint (pure numpy) on the test ECGs and reports AUC, accuracy at the
     validation-chosen threshold, sensitivity / specificity, with 95% CIs that resample PATIENTS.
  3. Optionally (--tflite) runs the int8 .tflite on the same ECGs and reports the accuracy lost to
     quantization, with a paired patient-bootstrap CI on the AUC difference.
  4. Reports the cost: parameters, MACs, flash (weights) and RAM (peak activations), compared with the DK.
  5. Optionally writes helper files for the next steps:
       --dump-calib N     N real VALIDATION windows for int8 calibration (export_to_tflite.py --calib-npy)
       --dump-boardset N  N balanced TEST windows + fp32 logits, fed to the board by board_runner.py

Usage (from this folder):
  python eval_host.py --n 1000                       # quick look
  python eval_host.py                                # full test set (about 10 min)
  python eval_host.py --dump-calib 200 --dump-boardset 60 --n 500
  python eval_host.py --tflite export_out/ecg_sex_leadv3_int8.tflite     # also evaluates int8

Needs: numpy, pandas, h5py.   Optional (only for --tflite / RAM estimate): tensorflow or ai-edge-litert.
"""
import argparse
import collections
import glob
import json
import math
import os
import pickle
import sys
import time
import zipfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DEFAULT_CKPT = HERE.parent / "models" / "2026.10.08" / "2_best_ecg_sex_leadv3_finetuned_15epochs.pth"
DEFAULT_DATA = HERE / "Dataset for ECG"
LEAD_IDX = {"leadv1": 6, "leadv3": 8}          # index into the 12 stored leads (I,II,III,aVR,aVF,aVL,V1..V6)
SEQ_LEN = 5000                                  # 10 s at 500 Hz
# Zephyr board doc, target nrf54lm20dk/nrf54lm20a/cpuapp ("523168 B of RAM, 2036 KiB of Flash").
BOARD = {"name": "nRF54LM20 DK, cpuapp image", "ram": 523168, "flash": 2036 * 1024}


# ======================================================================================
# 1. Checkpoint loader + numpy forward pass (no torch). The unpickler only allows tensor
#    rebuild + OrderedDict, so a hostile .pth cannot run code.
# ======================================================================================
_DT = {"FloatStorage": np.float32, "LongStorage": np.int64, "HalfStorage": np.float16, "DoubleStorage": np.float64}


def load_pth(path):
    z = zipfile.ZipFile(path)
    pkl = [n for n in z.namelist() if n.endswith("data.pkl")][0]
    prefix = pkl[: -len("data.pkl")]

    def rebuild(flat, offset, size, stride, *rest):
        n = int(np.prod(size)) if len(size) else 1
        return np.array(flat[offset: offset + n]).reshape(tuple(size))

    class U(pickle.Unpickler):
        def find_class(self, module, name):
            if name == "_rebuild_tensor_v2":
                return rebuild
            if name == "OrderedDict":
                return collections.OrderedDict
            if name in _DT:
                return name
            raise pickle.UnpicklingError(f"blocked global {module}.{name}")

        def persistent_load(self, pid):
            _, stype, key, _loc, _numel = pid
            return np.frombuffer(z.read(f"{prefix}data/{key}"), dtype=_DT[stype])

    return U(z.open(pkl)).load()


def _fold(sd, conv, bn, eps=1e-5):
    w, b = sd[f"{conv}.weight"].astype(np.float64), sd[f"{conv}.bias"].astype(np.float64)
    s = sd[f"{bn}.weight"] / np.sqrt(sd[f"{bn}.running_var"] + eps)
    return (w * s[:, None, None]).astype(np.float32), ((b - sd[f"{bn}.running_mean"]) * s + sd[f"{bn}.bias"]).astype(np.float32)


def prepare_weights(sd):
    P = {"stem": _fold(sd, "stem.0", "stem.1"), "l1": _fold(sd, "layer1.0", "layer1.1"),
         "r1a": _fold(sd, "res1.conv1", "res1.bn1"), "r1b": _fold(sd, "res1.conv2", "res1.bn2"),
         "l2": _fold(sd, "layer2.0", "layer2.1"),
         "r2a": _fold(sd, "res2.conv1", "res2.bn1"), "r2b": _fold(sd, "res2.conv2", "res2.bn2")}
    P["fc1"] = (sd["fc.1.weight"].astype(np.float32), sd["fc.1.bias"].astype(np.float32))
    P["fc2"] = (sd["fc.3.weight"].astype(np.float32), sd["fc.3.bias"].astype(np.float32))
    return P


def _conv(x, wb, stride, pad):
    from numpy.lib.stride_tricks import sliding_window_view
    w, b = wb
    xp = np.pad(x, ((0, 0), (pad, pad)))
    win = sliding_window_view(xp, w.shape[2], axis=1)[:, ::stride, :]
    cols = np.ascontiguousarray(win.transpose(1, 0, 2)).reshape(win.shape[1], -1)
    return (cols @ w.reshape(w.shape[0], -1).T + b).T


def forward(P, x):
    """x: (5000,) z-scored single-lead window -> logit."""
    from numpy.lib.stride_tricks import sliding_window_view
    r = lambda a: np.maximum(a, 0)
    h = r(_conv(x[None, :].astype(np.float32), P["stem"], 2, 7))
    hp = np.pad(h, ((0, 0), (1, 1)), constant_values=-np.inf)
    h = sliding_window_view(hp, 3, axis=1)[:, ::2, :].max(-1)
    h = r(_conv(h, P["l1"], 2, 3))
    h = r(_conv(r(_conv(h, P["r1a"], 1, 3)), P["r1b"], 1, 3) + h)
    h = r(_conv(h, P["l2"], 2, 3))
    h = r(_conv(r(_conv(h, P["r2a"], 1, 3)), P["r2b"], 1, 3) + h)
    g = r(P["fc1"][0] @ h.mean(-1) + P["fc1"][1])
    return float((P["fc2"][0] @ g + P["fc2"][1])[0])


# ======================================================================================
# 2. Data: Sara's split, reproduced with plain numpy (identical to sklearn GroupShuffleSplit)
# ======================================================================================
def _group_shuffle(groups, test_size, seed):
    classes, inv = np.unique(groups, return_inverse=True)
    n = len(classes)
    n_test = math.ceil(test_size * n)
    perm = np.random.RandomState(seed).permutation(n)
    return np.flatnonzero(np.isin(inv, perm[n_test:])), np.flatnonzero(np.isin(inv, perm[:n_test]))


def make_splits(df, samples_count=20_000):
    np.random.seed(42)
    subjects = df["subject_id"].unique()
    sampled = np.random.choice(subjects, size=min(samples_count, len(subjects)), replace=False)
    d = df[df["subject_id"].isin(sampled)].reset_index(drop=True)
    tv, te = _group_shuffle(d["subject_id"].values, 0.15, 42)
    tvdf, test = d.iloc[tv].reset_index(drop=True), d.iloc[te].reset_index(drop=True)
    tr, va = _group_shuffle(tvdf["subject_id"].values, 0.1765, 42)
    return tvdf.iloc[tr].reset_index(drop=True), tvdf.iloc[va].reset_index(drop=True), test


def read_lead(sig, h5_idx, lead):
    """Read one lead for many records. Sorted by file position for speed, returned in the order asked."""
    order = np.argsort(h5_idx, kind="stable")
    out = np.empty((len(h5_idx), SEQ_LEN), np.float16)
    t0 = time.time()
    for k, j in enumerate(order):
        out[j] = sig[int(h5_idx[j]), lead, :]
        if (k + 1) % 2000 == 0:
            print(f"    read {k + 1:,}/{len(h5_idx):,} records ({time.time() - t0:.0f}s)", flush=True)
    return out


def zscore_rows(raw):
    """Same per-window normalisation as the training notebook (computed in float32)."""
    x = np.nan_to_num(raw.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    m, s = x.mean(1, keepdims=True), x.std(1, keepdims=True)
    return ((x - m) / np.where(s < 1e-6, 1.0, s)).astype(np.float32)


# ======================================================================================
# 3. Metrics
# ======================================================================================
def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.asarray(z, dtype=np.float64)))


def auc_score(y, s):
    """Mann-Whitney AUC with tie handling (no sklearn needed)."""
    y = np.asarray(y).astype(bool)
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    _, inv, cnt = np.unique(s, return_inverse=True, return_counts=True)
    avg_rank = np.cumsum(cnt) - (cnt - 1) / 2.0
    ranks = avg_rank[inv]
    return float((ranks[y].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def point_metrics(y, logit, thr):
    y = np.asarray(y).astype(bool)
    pred = sigmoid(logit) >= thr
    return {"auc": auc_score(y, logit), "acc": float((pred == y).mean()),
            "sens": float(pred[y].mean()) if y.any() else float("nan"),
            "spec": float((~pred[~y]).mean()) if (~y).any() else float("nan")}


def patient_bootstrap(groups, y, scores, thr, n_boot, seed=0):
    """Resample PATIENTS (not ECGs): ECGs of one patient are correlated, so this gives honest CIs."""
    uniq, inv = np.unique(groups, return_inverse=True)
    order = np.argsort(inv, kind="stable")
    starts = np.searchsorted(inv[order], np.arange(len(uniq)))
    ends = np.append(starts[1:], len(inv))
    lists = [order[a:b] for a, b in zip(starts, ends)]
    rng = np.random.default_rng(seed)
    y = np.asarray(y).astype(bool)
    res = {k: {"auc": [], "acc": []} for k in scores}
    for _ in range(n_boot):
        idx = np.concatenate([lists[p] for p in rng.integers(0, len(uniq), len(uniq))])
        for k, s in scores.items():
            res[k]["auc"].append(auc_score(y[idx], s[idx]))
            res[k]["acc"].append(float(((sigmoid(s[idx]) >= thr) == y[idx]).mean()))
    return {k: {m: np.array(v) for m, v in d.items()} for k, d in res.items()}


def ci(a):
    lo, hi = np.percentile(a, [2.5, 97.5])
    return float(lo), float(hi)


# ======================================================================================
# 4. Cost: parameters, MACs, flash, RAM
# ======================================================================================
def _co(l, k, s, p):
    return (l + 2 * p - k) // s + 1


def analytic_cost(sd, length=SEQ_LEN):
    """Parameters (BatchNorm folded into the convs) and multiply-accumulates for one inference."""
    params = sum(int(v.size) for k, v in sd.items() if k.endswith(".weight") and v.ndim >= 2)
    params += sum(int(sd[k].size) for k in sd if k.endswith(".bias") and sd[k[:-5] + ".weight"].ndim >= 2)
    macs, l = 0, length
    l = _co(l, 15, 2, 7); macs += 1 * 64 * 15 * l
    l = _co(l, 3, 2, 1)
    l = _co(l, 7, 2, 3); macs += 64 * 128 * 7 * l
    macs += 2 * 128 * 128 * 7 * l
    l = _co(l, 7, 2, 3); macs += 128 * 256 * 7 * l
    macs += 2 * 256 * 256 * 7 * l
    macs += 256 * 64 + 64
    return params, macs


def make_interpreter(path):
    """Prefer the standalone LiteRT package, fall back to TensorFlow. No default delegates, so every op is visible."""
    try:
        from ai_edge_litert.interpreter import Interpreter, OpResolverType
        it = Interpreter(model_path=str(path),
                         experimental_op_resolver_type=OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    except Exception:
        try:
            import tensorflow as tf
        except ImportError:
            raise ImportError("reading a .tflite needs `pip install tensorflow` or `pip install ai-edge-litert`")
        it = tf.lite.Interpreter(
            model_path=str(path),
            experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    it.allocate_tensors()
    return it


def tflite_memory_report(path):
    """Lower/upper estimates of the activation RAM a micro-interpreter needs, from tensor lifetimes.
    peak_copy : every tensor gets its own buffer (what TFLM does unless it aliases RESHAPE outputs)
    peak_alias: RESHAPE outputs share their input's buffer (best case)
    The board prints the real number (arena_used) -- trust that one."""
    it = make_interpreter(path)
    ops = it._get_ops_details()
    td = {int(t["index"]): t for t in it.get_tensor_details()}
    g_in = [int(d["index"]) for d in it.get_input_details()]
    g_out = [int(d["index"]) for d in it.get_output_details()]
    produced = {int(o) for op in ops for o in op["outputs"]}
    acts = {i for i in td if (i in produced or i in g_in) and td[i]["name"]}      # drop weights + interpreter scratch

    def nbytes(i):
        return int(np.prod(td[i]["shape"])) * np.dtype(td[i]["dtype"]).itemsize

    def peak(alias):
        root = {i: i for i in acts}
        if alias:
            for op in ops:
                if op["op_name"] == "RESHAPE":
                    s, d = int(op["inputs"][0]), int(op["outputs"][0])
                    if s in root and d in root:
                        root[d] = root[s]
        first, last, size = {}, {}, {}

        def touch(t, i):
            r = root[t]
            first[r] = min(first.get(r, i), i)
            last[r] = max(last.get(r, i), i)
            size[r] = max(size.get(r, 0), nbytes(t))
        for t in g_in:
            touch(t, 0)
        for i, op in enumerate(ops):
            for t in op["inputs"]:
                if int(t) in acts:
                    touch(int(t), i)
            for t in op["outputs"]:
                touch(int(t), i)
        for t in g_out:
            touch(t, len(ops) - 1)
        return max(sum(size[r] for r in first if first[r] <= i <= last[r]) for i in range(len(ops)))

    names = collections.Counter(op["op_name"] for op in ops)
    return {"model_bytes": os.path.getsize(path), "ops": dict(names),
            "peak_copy": peak(False), "peak_alias": peak(True)}


def eval_tflite(path, X):
    """Run the int8 model on z-scored float windows. Returns dequantised logits and the raw int8 outputs."""
    it = make_interpreter(path)
    i_d, o_d = it.get_input_details()[0], it.get_output_details()[0]
    (i_s, i_zp), (o_s, o_zp) = i_d["quantization"], o_d["quantization"]
    q = np.clip(np.round(X / i_s + i_zp), -128, 127).astype(np.int8)
    qo = np.empty(len(X), np.int8)
    t0 = time.time()
    for k in range(len(X)):
        it.set_tensor(i_d["index"], q[k].reshape(i_d["shape"]))
        it.invoke()
        qo[k] = it.get_tensor(o_d["index"]).reshape(-1)[0]
        if (k + 1) % 2000 == 0:
            print(f"    int8 {k + 1:,}/{len(X):,} ({time.time() - t0:.0f}s)", flush=True)
    return (qo.astype(np.float32) - o_zp) * o_s, qo


def run_fp32(P, X, label="fp32"):
    out = np.empty(len(X), np.float32)
    t0 = time.time()
    for i in range(len(X)):
        out[i] = forward(P, X[i])
        if (i + 1) % 1000 == 0:
            el = time.time() - t0
            print(f"    {label} {i + 1:,}/{len(X):,}  ({el:.0f}s, ~{el / (i + 1) * (len(X) - i - 1):.0f}s left)", flush=True)
    return out


# ======================================================================================
# 5. Main
# ======================================================================================
def fmt_ci(v, lo_hi, pct=False):
    s = f"{v * 100:.1f}%" if pct else f"{v:.4f}"
    lo, hi = lo_hi
    return s + (f"  [{lo * 100:.1f}, {hi * 100:.1f}]" if pct else f"  [{lo:.4f}, {hi:.4f}]")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checkpoint", default=str(DEFAULT_CKPT))
    ap.add_argument("--lead", type=int, default=None, help="lead index (default: from checkpoint name; V1=6, V3=8)")
    ap.add_argument("--dataset-dir", default=str(DEFAULT_DATA))
    ap.add_argument("--out-dir", default=str(HERE / "export_out"))
    ap.add_argument("--n", type=int, default=0, help="evaluate a random subset of N test ECGs (0 = all)")
    ap.add_argument("--tflite", default=None, help="int8 .tflite to evaluate on the same ECGs")
    ap.add_argument("--threshold", type=float, default=None, help="probability threshold (default: val_threshold from the npz)")
    ap.add_argument("--bootstrap", type=int, default=500, help="patient-bootstrap resamples")
    ap.add_argument("--dump-calib", type=int, default=0, help="write N validation windows for int8 calibration")
    ap.add_argument("--dump-boardset", type=int, default=0, help="write N balanced test windows + fp32 logits for the board")
    args = ap.parse_args()

    import h5py
    import pandas as pd

    ckpt = Path(args.checkpoint)
    tag = ckpt.stem.replace("2_best_ecg_sex_", "").replace("_finetuned_15epochs", "")
    lead = args.lead if args.lead is not None else LEAD_IDX.get(tag)
    if lead is None:
        sys.exit(f"cannot infer the lead from '{ckpt.name}'; pass --lead")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path(args.dataset_dir)

    print(f"== model {tag} (lead index {lead}) ==")
    sd = load_pth(ckpt)
    P = prepare_weights(sd)

    print("== data ==")
    df = pd.read_csv(data_dir / "mimic_iv_ecg_clean_metadata.csv")
    train, val, test = make_splits(df)
    print(f"  split: train {len(train):,} | val {len(val):,} | test {len(test):,} ECGs "
          f"({test.subject_id.nunique():,} test patients)")
    thr, saved_probs, thr_src = args.threshold, None, "--threshold"
    npzs = glob.glob(str(ckpt.parent / "*epoch_outputs*.npz"))
    if len(npzs) == 1:
        d = np.load(npzs[0], allow_pickle=False)
        same = len(d["y_test_true"]) == len(test) and bool((d["y_test_true"] == test.label.values).all())
        print(f"  Sara's saved test labels vs rebuilt split: {'IDENTICAL' if same else 'MISMATCH (data differs from her run!)'}")
        saved_probs = d["y_test_probs"] if same else None
        if thr is None:
            thr, thr_src = float(d["val_threshold"]), "validation set (Youden J), from the npz"
    if thr is None:
        thr, thr_src = 0.5, "default 0.5 (no npz found)"

    # ---- choose the test ECGs to evaluate
    rng = np.random.default_rng(0)
    sel = np.sort(rng.choice(len(test), size=args.n, replace=False)) if 0 < args.n < len(test) else np.arange(len(test))
    sig = h5py.File(data_dir / "mimic_iv_ecg_full.h5", "r")["signals"]
    cache = out_dir / "cache" / f"test_lead{lead}_raw_f16.npy"
    if len(sel) == len(test) and cache.exists():
        print(f"  using cache {cache.name}")
        raw = np.load(cache)
    else:
        print(f"  reading {len(sel):,} test ECGs from the HDF5 (lead {lead}) ...")
        raw = read_lead(sig, test.h5_idx.values[sel], lead)
        if len(sel) == len(test):
            cache.parent.mkdir(exist_ok=True)
            np.save(cache, raw)
    X = zscore_rows(raw)
    y = test.label.values[sel].astype(int)
    patients = test.subject_id.values[sel]

    print(f"== fp32 inference on {len(X):,} ECGs ==")
    t0 = time.time()
    fp32 = run_fp32(P, X)
    print(f"  done in {time.time() - t0:.0f}s")
    if saved_probs is not None:
        diff = np.abs(sigmoid(fp32) - saved_probs[sel])
        print(f"  vs Sara's saved probabilities: max|diff| {diff.max():.4f}  mean|diff| {diff.mean():.5f}")

    scores = {"fp32": fp32}
    int8 = None
    if args.tflite:
        print(f"== int8 inference ({Path(args.tflite).name}) ==")
        int8, _ = eval_tflite(args.tflite, X)
        scores["int8"] = int8

    # ---- metrics
    print(f"== bootstrap over {len(np.unique(patients)):,} patients x {args.bootstrap} ==")
    boot = patient_bootstrap(patients, y, scores, thr, args.bootstrap)
    m = {k: point_metrics(y, s, thr) for k, s in scores.items()}

    print("\n" + "=" * 78)
    print(f" RESULTS  {tag}  | {len(X):,} test ECGs, {len(np.unique(patients)):,} patients | 95% CI resamples patients")
    print("=" * 78)
    print(f" decision threshold on probability: {thr:.4f}  ({thr_src})")
    for k in scores:
        print(f" {k:5s} AUC  {fmt_ci(m[k]['auc'], ci(boot[k]['auc']))}")
        print(f" {k:5s} Acc  {fmt_ci(m[k]['acc'], ci(boot[k]['acc']), pct=True)}")
        print(f" {k:5s} Sens {m[k]['sens']:.3f}   Spec {m[k]['spec']:.3f}   (positive class = male)")
    if int8 is not None:
        dauc = boot["int8"]["auc"] - boot["fp32"]["auc"]
        print(f" int8 - fp32 AUC: {m['int8']['auc'] - m['fp32']['auc']:+.4f}  95% CI [{ci(dauc)[0]:+.4f}, {ci(dauc)[1]:+.4f}]")
        agree = float(((sigmoid(int8) >= thr) == (sigmoid(fp32) >= thr)).mean())
        print(f" int8 vs fp32 logits: mean|diff| {np.abs(int8 - fp32).mean():.3f}, decisions agree on {agree:.1%} of ECGs")

    # ---- cost
    params, macs = analytic_cost(sd)
    print("\n" + "-" * 78)
    print(" COST  (what the model needs on the board)")
    print("-" * 78)
    print(f" parameters (BN folded): {params:,}   MACs per inference: {macs / 1e6:.1f} M")
    mem = None
    if args.tflite:
        try:
            mem = tflite_memory_report(args.tflite)
        except ImportError as e:
            print(f" (RAM estimate skipped: {e})")
    flash = mem["model_bytes"] if mem else params
    print(f" FLASH  model weights: {flash / 1024:,.0f} KiB = {flash / BOARD['flash']:.0%} of the DK's {BOARD['flash'] // 1024} KiB "
          f"(firmware + TFLite Micro need more on top)")
    if mem:
        print(f" RAM    activations: {mem['peak_alias'] / 1024:,.0f} - {mem['peak_copy'] / 1024:,.0f} KiB "
              f"= {mem['peak_alias'] / BOARD['ram']:.0%} - {mem['peak_copy'] / BOARD['ram']:.0%} of the DK's {BOARD['ram'] // 1024} KiB RAM")
        print(f"        (low = RESHAPE shares buffers, high = separate buffers; the board's arena_used is the real value)")
        print(f" ops in the .tflite: {mem['ops']}")
    else:
        print(" RAM    activations: pass --tflite (and install tensorflow or ai-edge-litert) for an estimate")
    print(" Which matters: FLASH decides whether the model fits at all; RAM decides whether it can run next to the rest")
    print(" of the firmware; MACs set the latency and the battery cost per ECG.")

    # ---- helper files
    stamp = {"tag": tag, "lead": lead, "threshold": thr}
    if args.dump_calib:
        r = np.random.default_rng(1).choice(len(val), size=min(args.dump_calib, len(val)), replace=False)
        cal = zscore_rows(read_lead(sig, val.h5_idx.values[r], lead))
        p = out_dir / f"calib_windows_{tag}.npy"
        np.save(p, cal)
        print(f"\n wrote {p}  ({len(cal)} real VALIDATION windows) -> python export_to_tflite.py --calib-npy {p}")
    if args.dump_boardset:
        nb = args.dump_boardset
        r2 = np.random.default_rng(2)
        pos, neg = np.flatnonzero(test.label.values == 1), np.flatnonzero(test.label.values == 0)
        pick = np.concatenate([r2.choice(pos, nb // 2, replace=False), r2.choice(neg, nb - nb // 2, replace=False)])
        r2.shuffle(pick)
        Xb = zscore_rows(read_lead(sig, test.h5_idx.values[pick], lead))
        lb = run_fp32(P, Xb, "boardset fp32")
        p = out_dir / f"boardset_{tag}.npz"
        np.savez(p, x=Xb, y=test.label.values[pick].astype(np.int8), test_row=pick, fp32_logit=lb,
                 patient=test.subject_id.values[pick], threshold=thr)
        print(f" wrote {p}  ({nb} balanced test windows + fp32 logits) -> used by board_runner.py")

    report = {**stamp, "n_test_ecgs": int(len(X)), "n_patients": int(len(np.unique(patients))),
              "metrics": m, "params": params, "macs": macs, "flash_bytes": int(flash),
              "ram_peak_copy": int(mem["peak_copy"]) if mem else None,
              "ram_peak_alias": int(mem["peak_alias"]) if mem else None,
              "ci95": {k: {"auc": ci(boot[k]["auc"]), "acc": ci(boot[k]["acc"])} for k in scores}}
    (out_dir / f"host_report_{tag}.json").write_text(json.dumps(report, indent=2))
    print(f"\n report saved: {out_dir / f'host_report_{tag}.json'}")


if __name__ == "__main__":
    main()
