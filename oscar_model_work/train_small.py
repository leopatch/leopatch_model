#!/usr/bin/env python3
"""
train_small.py -- OVERNIGHT run: train several small 100 Hz versions of the 1-lead ECG sex model, compare each
one with the current model (Sara's, 500 Hz) on the FULL test set, and write a results table.

What it does
  1. Rebuilds Sara's patient split (train 70,406 / val 14,471 / test 14,653 ECGs) and reads lead V3 from the HDF5
     (first run only, ~15-30 min; cached in export_out/cache so reruns skip it).
  2. Resamples every ECG 500 Hz -> 100 Hz (1000 samples, anti-aliased) and re-z-scores it.
  3. Runs the current model (the "teacher") on all ECGs once -> its logits are used for knowledge distillation and
     as the baseline in the final table.
  4. Trains each variant in small_ecg.VARIANTS under a time budget (cosine LR, light augmentation, distillation),
     keeps the epoch with the best validation AUC, picks the threshold on validation (Youden J, like Sara),
     evaluates on the whole test set with patient-level bootstrap CIs and a paired AUC difference vs the teacher.
  5. If tensorflow is installed: folds BatchNorm, int8-quantizes with real validation windows, writes the .tflite,
     re-evaluates int8 and reports flash / RAM. Otherwise run `python small_ecg.py export ...` later.
  6. Writes export_out/small/RESULTS_small.md and results_small.json after EVERY variant, so a partial run is useful.

Usage (from this folder, in the python that has torch):
  python train_small.py --quick                      # 5-minute smoke test on a few thousand ECGs. DO THIS FIRST.
  caffeinate -i python train_small.py --budget-min 220 2>&1 | tee train_small.log        # the overnight run

Needs: torch, numpy, pandas, h5py, scipy.  Optional: tensorflow (for the int8 export inside this script).
"""
import argparse
import copy
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402

import eval_host as eh  # noqa: E402
import small_ecg as S  # noqa: E402

FS_FACTOR = 5                      # 500 Hz -> 100 Hz
WEIGHT = {"w100": 1.6}             # relative share of the time budget (bigger model needs more epochs)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def jsonable(o):
    if isinstance(o, dict):
        return {k: jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    return o


def pick_device(arg):
    if arg != "auto":
        return torch.device(arg)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


# ======================================================================================
# Teacher = Sara's model in torch (weights from eval_host's numpy loader)
# ======================================================================================
class Teacher:
    def __init__(self, P, dev):
        t = lambda a: torch.tensor(np.asarray(a), dtype=torch.float32, device=dev)  # noqa: E731
        self.w = {k: (t(v[0]), t(v[1])) for k, v in P.items()}
        self.dev = dev

    @torch.no_grad()
    def __call__(self, x):                                   # (B, 5000) -> (B,)
        c = lambda h, k, s, p: F.conv1d(h, self.w[k][0], self.w[k][1], stride=s, padding=p)  # noqa: E731
        h = F.relu(c(x[:, None, :], "stem", 2, 7))
        h = F.max_pool1d(h, 3, 2, 1)
        h = F.relu(c(h, "l1", 2, 3))
        h = F.relu(c(F.relu(c(h, "r1a", 1, 3)), "r1b", 1, 3) + h)
        h = F.relu(c(h, "l2", 2, 3))
        h = F.relu(c(F.relu(c(h, "r2a", 1, 3)), "r2b", 1, 3) + h)
        g = F.relu(F.linear(h.mean(-1), *self.w["fc1"]))
        return F.linear(g, *self.w["fc2"]).squeeze(-1)


def teacher_logits(teacher, raw, bs=256):
    out = np.empty(len(raw), np.float32)
    t0 = time.time()
    for i in range(0, len(raw), bs):
        x = torch.from_numpy(eh.zscore_rows(np.asarray(raw[i:i + bs]))).to(teacher.dev)
        out[i:i + bs] = teacher(x).float().cpu().numpy()
        if (i // bs) % 40 == 0 and i:
            log(f"    teacher {i:,}/{len(raw):,}  ({time.time() - t0:.0f}s)")
    return out


# ======================================================================================
# Data
# ======================================================================================
def read_sorted(sig, h5_idx, lead, tag):
    order = np.argsort(h5_idx, kind="stable")
    out = np.empty((len(h5_idx), eh.SEQ_LEN), np.float16)
    t0 = time.time()
    for k, j in enumerate(order):
        out[j] = sig[int(h5_idx[j]), lead, :]
        if (k + 1) % 5000 == 0:
            el = time.time() - t0
            log(f"    reading {tag}: {k + 1:,}/{len(h5_idx):,}  ({el:.0f}s, ~{el / (k + 1) * (len(h5_idx) - k - 1) / 60:.0f} min left)")
    return out


def to_100hz(raw, chunk=2048):
    from scipy.signal import resample_poly
    out = np.empty((len(raw), eh.SEQ_LEN // FS_FACTOR), np.float32)
    for i in range(0, len(raw), chunk):
        x = np.nan_to_num(np.asarray(raw[i:i + chunk]).astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        y = resample_poly(x, 1, FS_FACTOR, axis=1).astype(np.float32)
        out[i:i + chunk] = eh.zscore_rows(y)
    return out


def synth_split(n, rng, n_pat):
    y = rng.integers(0, 2, n)
    t = np.arange(eh.SEQ_LEN) / 500.0
    hr = rng.uniform(1.0, 1.8, n)[:, None]
    ph = (t[None, :] * hr) % 1.0 - 0.5
    width = (0.03 + 0.02 * y)[:, None]
    sig = np.exp(-(ph / width) ** 2) + 0.35 * rng.standard_normal((n, eh.SEQ_LEN))
    pat = rng.integers(0, n_pat, n)
    return sig.astype(np.float16), y.astype(np.int8), pat


def load_data(args, dev, out_dir):
    lead = args.lead
    data, raws = {}, {}
    if args.synthetic:
        rng = np.random.default_rng(0)
        for name, n in (("train", 3000), ("val", 800), ("test", 800)):
            raws[name], data[name + "_y"], data[name + "_pat"] = synth_split(n, rng, n // 2)
        thr_prob_sara = 0.5
        teacher_P = None
    else:
        import h5py
        import pandas as pd
        ddir = Path(args.data_dir)
        df = pd.read_csv(ddir / "mimic_iv_ecg_clean_metadata.csv")
        train, val, test = eh.make_splits(df)
        log(f"split: train {len(train):,} | val {len(val):,} | test {len(test):,} ECGs ({test.subject_id.nunique():,} test patients)")
        if args.quick:
            rng = np.random.default_rng(0)
            train = train.iloc[np.sort(rng.choice(len(train), 4000, replace=False))].reset_index(drop=True)
            val = val.iloc[np.sort(rng.choice(len(val), 1500, replace=False))].reset_index(drop=True)
            test = test.iloc[np.sort(rng.choice(len(test), 1500, replace=False))].reset_index(drop=True)
        cache = (out_dir / "cache_quick") if args.quick else (HERE / "export_out" / "cache")
        cache.mkdir(parents=True, exist_ok=True)
        sig = None
        for name, d in (("test", test), ("val", val), ("train", train)):
            path = cache / f"{name}_lead{lead}_raw_f16.npy"
            if path.exists() and np.load(path, mmap_mode="r").shape[0] == len(d):
                log(f"using cache {path.name}")
                raws[name] = np.load(path, mmap_mode="r")
            else:
                if sig is None:
                    f = h5py.File(ddir / "mimic_iv_ecg_full.h5", "r", rdcc_nbytes=256 * 1024 * 1024, rdcc_nslots=100003)
                    sig = f["signals"]
                log(f"reading {len(d):,} {name} ECGs (lead {lead}) from the HDF5 ... (first run only)")
                raw = read_sorted(sig, d.h5_idx.values, lead, name)
                np.save(path, raw)
                raws[name] = raw
            data[name + "_y"] = d.label.values.astype(np.int8)
            data[name + "_pat"] = d.subject_id.values
        data["test_row"] = np.arange(len(test))
        teacher_P = eh.prepare_weights(eh.load_pth(Path(args.teacher_ckpt)))

    log("resampling 500 Hz -> 100 Hz ...")
    for name in ("train", "val", "test"):
        data[name + "_x"] = to_100hz(raws[name])
    data["raws"] = raws
    data["teacher_P"] = teacher_P
    return data


def compute_teacher(data, dev, out_dir, args):
    P = data["teacher_P"]
    if P is None:                                        # synthetic: random teacher just to exercise the code path
        rng = np.random.default_rng(1)
        P = {k: (rng.standard_normal(s).astype(np.float32) * 0.1, np.zeros(s[0], np.float32))
             for k, s in (("stem", (8, 1, 15)), ("l1", (8, 8, 7)), ("r1a", (8, 8, 7)), ("r1b", (8, 8, 7)),
                          ("l2", (8, 8, 7)), ("r2a", (8, 8, 7)), ("r2b", (8, 8, 7)), ("fc1", (4, 8)), ("fc2", (1, 4)))}
    teacher = Teacher(P, dev)
    xt = eh.zscore_rows(np.asarray(data["raws"]["test"][:4]))
    ref = np.array([eh.forward(P, x) for x in xt])
    got = teacher(torch.from_numpy(xt).to(dev)).float().cpu().numpy()
    log(f"teacher torch vs numpy check: max|diff| = {np.abs(ref - got).max():.2e}  (expect < 1e-3)")
    cache = out_dir / ("cache_quick" if args.quick else "cache")
    cache = HERE / "export_out" / "cache" if (not args.quick and not args.synthetic) else out_dir / "cache_quick"
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / f"teacher_logits_lead{args.lead}.npz"
    sizes = {k: len(data[k + "_y"]) for k in ("train", "val", "test")}
    if f.exists() and not args.synthetic:
        z = np.load(f)
        if all(len(z[k]) == sizes[k] for k in sizes):
            log("using cached teacher logits")
            return {k: z[k] for k in sizes}, P
    res = {}
    for k in ("test", "val", "train"):
        log(f"teacher on {k} ({sizes[k]:,} ECGs, 500 Hz) ...")
        res[k] = teacher_logits(teacher, data["raws"][k])
    if not args.synthetic:
        np.savez(f, **res)
    return res, P


# ======================================================================================
# Metrics
# ======================================================================================
def youden_logit_threshold(y, s):
    order = np.argsort(-s)
    ys = np.asarray(y)[order].astype(np.float64)
    tpr = np.cumsum(ys) / max(ys.sum(), 1)
    fpr = np.cumsum(1 - ys) / max((1 - ys).sum(), 1)
    i = int(np.argmax(tpr - fpr))
    return float(s[order][i])


def evaluate_scores(y_val, s_val, y_te, s_te, pat_te, s_ref=None, thr_ref=None, n_boot=500):
    thr_logit = youden_logit_threshold(y_val, s_val)
    thr = float(eh.sigmoid(thr_logit))
    m = eh.point_metrics(y_te, s_te, thr)
    boot = eh.patient_bootstrap(pat_te, y_te, {"s": s_te}, thr, n_boot)
    out = {"thr_prob": thr, **m, "auc_ci": eh.ci(boot["s"]["auc"]), "acc_ci": eh.ci(boot["s"]["acc"])}
    if s_ref is not None:
        b2 = eh.patient_bootstrap(pat_te, y_te, {"s": s_ref}, thr_ref, n_boot)
        d = boot["s"]["auc"] - b2["s"]["auc"]
        out["dauc"] = float(m["auc"] - eh.auc_score(y_te, s_ref))
        out["dauc_ci"] = eh.ci(d)
    return out


# ======================================================================================
# Training
# ======================================================================================
def augment(x, fs=100):
    b, l = x.shape
    dev = x.device
    shift = torch.randint(-50, 51, (b, 1), device=dev)
    idx = (torch.arange(l, device=dev)[None, :] + shift) % l
    x = x.gather(1, idx)
    t = torch.arange(l, device=dev)[None, :] / fs
    amp = torch.rand(b, 1, device=dev) * 0.15
    f = 0.1 + 0.4 * torch.rand(b, 1, device=dev)
    ph = torch.rand(b, 1, device=dev) * 2 * math.pi
    return x + 0.03 * torch.randn_like(x) + amp * torch.sin(2 * math.pi * f * t + ph)


@torch.no_grad()
def predict(model, X, bs=1024):
    model.eval()
    return np.concatenate([model(X[i:i + bs]).float().cpu().numpy() for i in range(0, len(X), bs)])


def score_split(model, X, dev):
    """Score a whole split on the accelerator (CPU only as a fallback; depthwise convs are slow on CPU)."""
    for d in ([dev] if dev.type == "cpu" else [dev, torch.device("cpu")]):
        try:
            model.to(d).eval()
            return predict(model, torch.from_numpy(X).to(d))
        except Exception as e:                                               # noqa: BLE001
            log(f"  scoring on {d} failed: {e!r}")
    raise RuntimeError("scoring failed")


def train_variant(name, cfg, data, teach, dev, args, slice_sec):
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    model = S.SmallECG(cfg)
    params, macs = S.cost(model)
    model.to(dev)
    use_kd = (name not in S.NO_KD) and args.kd_alpha > 0
    Xtr = torch.from_numpy(data["train_x"]).to(dev)
    ytr = torch.from_numpy(data["train_y"].astype(np.float32)).to(dev)
    ttr = torch.from_numpy(np.clip(teach["train"], -12, 12)).to(dev)
    Xva = torch.from_numpy(data["val_x"]).to(dev)
    yva = data["val_y"]
    n, bsz = len(Xtr), args.batch
    spe = max(1, n // bsz)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.wd)
    total_epochs, step, ep = None, 0, 0
    best_auc, best_state, best_ep = -1.0, None, -1
    hist = []
    t_start = time.time()
    log(f"  [{name}] {params:,} params, {macs / 1e6:.1f} M MACs, distillation={'on' if use_kd else 'off'}, "
        f"time slice {slice_sec / 60:.0f} min, device {dev}")
    while True:
        t_ep = time.time()
        model.train()
        perm = torch.randperm(n, device=dev)
        acc = torch.zeros((), device=dev)
        for bi in range(spe):
            if total_epochs is None:
                lr = args.lr * min(1.0, (step + 1) / min(200, spe))
            else:
                prog = min(1.0, ((ep - 1) * spe + bi) / max(1, (total_epochs - 1) * spe))
                lr = args.lr * (0.01 + 0.99 * 0.5 * (1 + math.cos(math.pi * prog)))
            for g in opt.param_groups:
                g["lr"] = lr
            idx = perm[bi * bsz:(bi + 1) * bsz]
            xb, yb, tb = Xtr[idx], ytr[idx], ttr[idx]
            if not args.no_aug:
                xb = augment(xb)
            z = model(xb)
            loss = F.binary_cross_entropy_with_logits(z, yb)
            if use_kd:
                T = args.kd_T
                soft = F.binary_cross_entropy_with_logits(z / T, torch.sigmoid(tb / T))
                loss = (1 - args.kd_alpha) * loss + args.kd_alpha * T * T * soft
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            acc += loss.detach()
            step += 1
        val_logit = predict(model, Xva)
        vauc = eh.auc_score(yva, val_logit)
        hist.append({"epoch": ep + 1, "loss": float(acc.item() / spe), "val_auc": float(vauc), "sec": time.time() - t_ep})
        if vauc > best_auc:
            best_auc, best_ep = vauc, ep + 1
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        if total_epochs is None:
            per = (time.time() - t_ep) * 1.06
            total_epochs = int(min(args.max_epochs, max(args.min_epochs, slice_sec // per)))
            if args.quick:
                total_epochs = args.max_epochs
            log(f"  [{name}] epoch took {per:.0f}s -> will run {total_epochs} epochs")
        log(f"  [{name}] epoch {ep + 1}/{total_epochs}  loss {hist[-1]['loss']:.4f}  val AUC {vauc:.4f}  "
            f"(best {best_auc:.4f} @ {best_ep})  {time.time() - t_ep:.0f}s")
        ep += 1
        if ep >= total_epochs or (time.time() - t_start) > slice_sec * 1.3:
            break
    model.load_state_dict(best_state)
    model.cpu()
    return model, {"params": params, "macs": macs, "epochs_run": ep, "best_epoch": best_ep, "best_val_auc": best_auc,
                   "train_seconds": time.time() - t_start, "kd": use_kd, "history": hist}


# ======================================================================================
# Export + int8 evaluation
# ======================================================================================
def export_and_eval(name, model, cfg, data, teach, out_dir, thr_prob, y_sub, s_sub, sub_idx, pat_sub):
    """int8 export + evaluation in a SEPARATE python process (tensorflow and torch crash each other in one process)."""
    import importlib.util
    import subprocess
    ckpt = out_dir / f"small_{name}.pt"
    if importlib.util.find_spec("tensorflow") is None:
        return {"status": "skipped (tensorflow not installed): run  python small_ecg.py export --ckpt "
                          f"{ckpt} --calib {out_dir / 'calib_windows_small.npy'}"}
    path = out_dir / f"ecg_small_{name}_int8.tflite"
    xs_path, lg_path, rep_path = out_dir / "_eval_x.npy", out_dir / "_eval_int8.npy", out_dir / "_export_report.json"
    np.save(xs_path, data["test_x"][sub_idx])
    cmd = [sys.executable, str(HERE / "small_ecg.py"), "export", "--ckpt", str(ckpt),
           "--calib", str(out_dir / "calib_windows_small.npy"), "--out", str(path),
           "--eval-x", str(xs_path), "--eval-out", str(lg_path), "--report", str(rep_path)]
    pr = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if pr.returncode != 0:
        return {"status": f"export failed (exit {pr.returncode}): " + (pr.stderr or pr.stdout)[-600:]}
    info = json.loads(rep_path.read_text())
    lg8 = np.load(lg_path)
    m8 = eh.point_metrics(y_sub, lg8, thr_prob)
    m32 = eh.point_metrics(y_sub, s_sub, thr_prob)
    boot = eh.patient_bootstrap(pat_sub, y_sub, {"i8": lg8, "f32": s_sub}, thr_prob, 300)
    d = boot["i8"]["auc"] - boot["f32"]["auc"]
    for f in (xs_path, lg_path, rep_path):
        f.unlink(missing_ok=True)
    return {"status": "ok", "tflite": path.name, "tflite_kib": info["tflite_bytes"] / 1024,
            "keras_vs_torch_max_abs": info.get("keras_vs_torch_max_abs"),
            "n_eval": int(len(sub_idx)), "auc_int8": m8["auc"], "auc_fp32_same_subset": m32["auc"],
            "acc_int8": m8["acc"], "dauc_int8_vs_fp32": float(m8["auc"] - m32["auc"]), "dauc_int8_ci": eh.ci(d),
            "agree_decisions": float(((eh.sigmoid(lg8) >= thr_prob) == (eh.sigmoid(s_sub) >= thr_prob)).mean()),
            "ram_kib_low": info["peak_alias"] / 1024, "ram_kib_high": info["peak_copy"] / 1024, "ops": info["ops"]}


def write_boardset(name, model, data, thr_prob, out_dir, n=200):
    r = np.random.default_rng(3)
    y = data["test_y"]
    pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    pick = np.concatenate([r.choice(pos, min(n // 2, len(pos)), replace=False), r.choice(neg, min(n // 2, len(neg)), replace=False)])
    r.shuffle(pick)
    x = data["test_x"][pick]
    with torch.no_grad():
        lg = model.eval()(torch.from_numpy(x)).numpy()
    np.savez(out_dir / f"boardset_small_{name}.npz", x=x, y=y[pick].astype(np.int8), test_row=pick,
             fp32_logit=lg.astype(np.float32), patient=data["test_pat"][pick], threshold=thr_prob)


# ======================================================================================
# Report
# ======================================================================================
def write_report(out_dir, teacher_row, rows, meta):
    (out_dir / "results_small.json").write_text(json.dumps(jsonable({"meta": meta, "teacher": teacher_row, "variants": rows}), indent=2))
    L = ["# Small ECG sex models: overnight results", "",
         f"Test set: {meta['n_test']:,} ECGs, {meta['n_test_patients']:,} patients. 95% intervals resample PATIENTS. "
         f"Threshold for each model = Youden J on the validation set. Device: {meta['device']}.", "",
         "| model | MACs | x fewer | params | int8 weights | act. RAM (est.) | test AUC [95% CI] | dAUC vs current [95% CI] | accuracy | sens / spec | int8 AUC | epochs | train min |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    t = teacher_row
    L.append(f"| **current (500 Hz)** | {t['macs'] / 1e6:.0f} M | 1x | {t['params'] / 1e6:.2f} M | {t['params'] / 1024:.0f} KiB | ~320 KiB | "
             f"{t['auc']:.4f} [{t['auc_ci'][0]:.3f}, {t['auc_ci'][1]:.3f}] | - | {t['acc'] * 100:.1f}% | {t['sens'] * 100:.0f} / {t['spec'] * 100:.0f} | - | - | - |")
    for n, r in rows.items():
        if "error" in r:
            L.append(f"| {n} | FAILED: {r['error'][:80]} |")
            continue
        e = r.get("export", {})
        i8 = f"{e['auc_int8']:.4f}" if e.get("status") == "ok" else "n/a"
        L.append(f"| {n} | {r['macs'] / 1e6:.1f} M | {t['macs'] / r['macs']:.0f}x | {r['params'] / 1e3:.0f} K | {r['params'] / 1024:.0f} KiB | "
                 f"{r['act_kib']:.0f} KiB | {r['auc']:.4f} [{r['auc_ci'][0]:.3f}, {r['auc_ci'][1]:.3f}] | "
                 f"{r['dauc']:+.4f} [{r['dauc_ci'][0]:+.3f}, {r['dauc_ci'][1]:+.3f}] | {r['acc'] * 100:.1f}% | "
                 f"{r['sens'] * 100:.0f} / {r['spec'] * 100:.0f} | {i8} | {r['epochs_run']} | {r['train_seconds'] / 60:.0f} |")
    ok = {n: r for n, r in rows.items() if "error" not in r}
    if ok:
        good = {n: r for n, r in ok.items() if r["dauc"] >= -0.01}
        L += ["", "## Reading it", ""]
        if good:
            b = min(good, key=lambda n: good[n]["macs"])
            L.append(f"* Cheapest model within 0.01 AUC of the current one: **{b}** "
                     f"({good[b]['macs'] / 1e6:.1f} M MACs = {t['macs'] / good[b]['macs']:.0f}x fewer, AUC {good[b]['auc']:.4f} vs {t['auc']:.4f}).")
        else:
            b2 = max(ok, key=lambda n: ok[n]["auc"])
            L.append(f"* No variant stayed within 0.01 AUC. Best was **{b2}** (AUC {ok[b2]['auc']:.4f}, dAUC {ok[b2]['dauc']:+.4f}).")
        L.append("* A difference smaller than its confidence interval is not a real difference. The dAUC interval is the thing to trust.")
        L.append("* 'act. RAM (est.)' is a rough int8 estimate; the board reports the real TFLM arena.")
        for n, r in ok.items():
            e = r.get("export", {})
            if e.get("status") == "ok":
                L.append(f"* {n}: int8 AUC {e['auc_int8']:.4f} (change vs its fp32: {e['dauc_int8_vs_fp32']:+.4f}, on {e['n_eval']:,} test ECGs); "
                         f"TFLite {e['tflite_kib']:.0f} KiB; RAM {e['ram_kib_low']:.0f}-{e['ram_kib_high']:.0f} KiB; ops {e['ops']}")
            elif e:
                L.append(f"* {n}: {e.get('status')}")
    (out_dir / "RESULTS_small.md").write_text("\n".join(L) + "\n")


# ======================================================================================
# Main
# ======================================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=str(eh.DEFAULT_DATA))
    ap.add_argument("--teacher-ckpt", default=str(eh.DEFAULT_CKPT))
    ap.add_argument("--lead", type=int, default=8)
    ap.add_argument("--out-dir", default=str(HERE / "export_out" / "small"))
    ap.add_argument("--variants", default="w50,w50_sep,w25,w100,w50_nokd,w50_b10,w75_sep")
    ap.add_argument("--budget-min", type=float, default=220, help="total wall-clock budget, minutes (incl. data prep)")
    ap.add_argument("--max-epochs", type=int, default=60)
    ap.add_argument("--min-epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--wd", type=float, default=1e-2)
    ap.add_argument("--kd-alpha", type=float, default=0.5)
    ap.add_argument("--kd-T", type=float, default=2.0)
    ap.add_argument("--no-aug", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--quick", action="store_true", help="smoke test on a few thousand ECGs, 2 variants, 2 epochs")
    ap.add_argument("--synthetic", action="store_true", help="(developer) fake data, no HDF5")
    args = ap.parse_args()

    t_global = time.time()
    if args.quick:
        args.out_dir = str(HERE / "export_out" / "small_quick")
        args.variants = "w50,w50_sep"
        args.max_epochs, args.min_epochs = 2, 2
        args.budget_min = 20
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dev = pick_device(args.device)
    import importlib.util
    tfv = "found (export runs in a separate process)" if importlib.util.find_spec("tensorflow") else \
        "not installed (int8 export will be skipped; do it later with small_ecg.py export)"
    log(f"torch {torch.__version__} | device {dev} | tensorflow {tfv} | budget {args.budget_min:.0f} min | out {out_dir}")

    data = load_data(args, dev, out_dir)
    teach, P = compute_teacher(data, dev, out_dir, args)
    yv, yt, pt = data["val_y"], data["test_y"], data["test_pat"]
    t_thr = float(eh.sigmoid(youden_logit_threshold(yv, teach["val"])))
    teacher_row = evaluate_scores(yv, teach["val"], yt, teach["test"], pt)
    tp, tm = eh.analytic_cost(eh.load_pth(Path(args.teacher_ckpt))) if not args.synthetic else (1452289, 540589888)
    teacher_row.update(params=tp, macs=tm)
    log(f"CURRENT MODEL on this test set: AUC {teacher_row['auc']:.4f} [{teacher_row['auc_ci'][0]:.3f}, {teacher_row['auc_ci'][1]:.3f}]  "
        f"acc {teacher_row['acc'] * 100:.1f}%  (threshold p>={teacher_row['thr_prob']:.3f})")
    if not args.synthetic and teacher_row["auc"] < 0.75:
        log("  WARNING: the current model scores much lower than the ~0.85 seen before -- check the data / lead index!")

    rng = np.random.default_rng(5)
    data["calib"] = data["val_x"][rng.choice(len(data["val_x"]), min(300, len(data["val_x"])), replace=False)]
    np.save(out_dir / "calib_windows_small.npy", data["calib"])
    n_sub = min(len(yt), 4000)
    sub_idx = np.sort(rng.choice(len(yt), n_sub, replace=False))

    names = [v.strip() for v in args.variants.split(",") if v.strip()]
    rows = {}
    meta = {"n_test": int(len(yt)), "n_test_patients": int(len(np.unique(pt))), "device": str(dev),
            "args": vars(args), "prep_minutes": (time.time() - t_global) / 60}
    log(f"data + teacher ready after {(time.time() - t_global) / 60:.1f} min; training {names}")
    budget = args.budget_min * 60
    for i, name in enumerate(names):
        remaining = budget - (time.time() - t_global)
        w_left = sum(WEIGHT.get(n, 1.0) for n in names[i:])
        slice_sec = remaining * WEIGHT.get(name, 1.0) / w_left - 120          # keep ~2 min for eval/export
        if slice_sec < 90 and not args.quick:
            log(f"[{name}] skipped: only {remaining / 60:.0f} min of budget left")
            continue
        try:
            cfg = S.VARIANTS[name]
            tried = [dev] + ([torch.device("cpu")] if dev.type != "cpu" else [])
            model = info = None
            for d in tried:
                try:
                    model, info = train_variant(name, cfg, data, teach, d, args, slice_sec if d is dev else slice_sec / 2)
                    break
                except Exception as e:                                       # noqa: BLE001
                    log(f"[{name}] training on {d} failed: {e!r}")
                    traceback.print_exc()
            if model is None:
                raise RuntimeError("training failed on every device (see log above)")
            val_l, te_l = score_split(model, data["val_x"], dev), score_split(model, data["test_x"], dev)
            model.cpu().eval()
            m = evaluate_scores(yv, val_l, yt, te_l, pt, s_ref=teach["test"], thr_ref=t_thr)
            r = {**info, **m, "act_kib": S.activation_bytes(cfg) / 1024, "cfg": cfg}
            torch.save({"cfg": cfg, "state": model.state_dict(), "name": name, "thr_prob": m["thr_prob"]}, out_dir / f"small_{name}.pt")
            write_boardset(name, model, data, m["thr_prob"], out_dir)
            log(f"[{name}] TEST AUC {m['auc']:.4f} [{m['auc_ci'][0]:.3f}, {m['auc_ci'][1]:.3f}]  dAUC vs current {m['dauc']:+.4f} "
                f"[{m['dauc_ci'][0]:+.3f}, {m['dauc_ci'][1]:+.3f}]  acc {m['acc'] * 100:.1f}%  ({info['macs'] / 1e6:.1f} M MACs)")
            try:
                r["export"] = export_and_eval(name, model, cfg, data, teach, out_dir, m["thr_prob"], yt[sub_idx], te_l[sub_idx], sub_idx, pt[sub_idx])
                if r["export"].get("status") == "ok":
                    e = r["export"]
                    log(f"[{name}] int8: AUC {e['auc_int8']:.4f} ({e['dauc_int8_vs_fp32']:+.4f} vs fp32), {e['tflite_kib']:.0f} KiB, "
                        f"RAM {e['ram_kib_low']:.0f}-{e['ram_kib_high']:.0f} KiB, ops {e['ops']}")
            except Exception as e:                                           # noqa: BLE001
                traceback.print_exc()
                r["export"] = {"status": f"export failed: {e!r}"}
            rows[name] = r
        except Exception as e:                                               # noqa: BLE001
            traceback.print_exc()
            rows[name] = {"error": repr(e)}
        meta["total_minutes"] = (time.time() - t_global) / 60
        write_report(out_dir, teacher_row, rows, meta)
        log(f"report updated: {out_dir / 'RESULTS_small.md'}")
    meta["total_minutes"] = (time.time() - t_global) / 60
    write_report(out_dir, teacher_row, rows, meta)
    log(f"DONE in {meta['total_minutes']:.0f} min. Read {out_dir / 'RESULTS_small.md'}")


if __name__ == "__main__":
    main()
