#!/usr/bin/env python3
"""Train a narrower copy of the median-beat model so it fits the nRF54LM20B with room to spare.

Same layers as ECGSexClassifier, but every channel count is multiplied by --width
(0.5 -> 32/64/128 channels, about 4x fewer weights). Input: 800-sample median beats from
deploy/prepare_beats.py.

  Sex model on PTB-XL adults (stand-in task), copying the full model's answers (distillation):
    python deploy/train_halfwidth.py sex ptbxl_beats.npz --lead V3 \
        --teacher models/2026.10.28/best_leadv3_median_beat_w800_sweep.pth --out models/2026.11.10/sex_v3_half
  Congenital heart disease model on the pediatric data:
    python deploy/train_halfwidth.py chd pediatric_beats.npz --lead I --out models/2026.11.10/chd_lead1_half

Writes <out>.pth (weights) and <out>.json (settings, split, AUCs, threshold).
Patients never appear in more than one of train / validation / test.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import GroupShuffleSplit


class ResBlock1D(nn.Module):
    def __init__(self, channels, dropout_rate=0.2):
        super().__init__()
        self.conv1 = nn.Conv1d(channels, channels, 7, padding=3)
        self.bn1 = nn.BatchNorm1d(channels)
        self.drop = nn.Dropout1d(dropout_rate)
        self.conv2 = nn.Conv1d(channels, channels, 7, padding=3)
        self.bn2 = nn.BatchNorm1d(channels)

    def forward(self, x):
        out = self.drop(torch.relu(self.bn1(self.conv1(x))))
        return torch.relu(self.bn2(self.conv2(out)) + x)


class ECGNet(nn.Module):
    """ECGSexClassifier with the channel counts scaled by `width` (1.0 = the original)."""

    def __init__(self, width=1.0):
        super().__init__()
        c1, c2, c3, f = (max(8, int(round(c * width))) for c in (64, 128, 256, 64))
        self.stem = nn.Sequential(nn.Conv1d(1, c1, 15, stride=2, padding=7), nn.BatchNorm1d(c1), nn.ReLU(),
                                  nn.MaxPool1d(3, stride=2, padding=1))
        self.layer1 = nn.Sequential(nn.Conv1d(c1, c2, 7, stride=2, padding=3), nn.BatchNorm1d(c2), nn.ReLU())
        self.res1 = ResBlock1D(c2)
        self.layer2 = nn.Sequential(nn.Conv1d(c2, c3, 7, stride=2, padding=3), nn.BatchNorm1d(c3), nn.ReLU())
        self.res2 = ResBlock1D(c3)
        self.fc = nn.Sequential(nn.Dropout(0.5), nn.Linear(c3, f), nn.ReLU(), nn.Linear(f, 1))

    def forward(self, x):
        x = self.res1(self.layer1(self.stem(x)))
        x = self.res2(self.layer2(x))
        return self.fc(x.mean(-1))


def predict(model, x):
    model.eval()
    with torch.no_grad():
        return torch.cat([model(x[i:i + 512]) for i in range(0, len(x), 512)])[:, 0]


def augment(x):
    """Small random gain, time shift and noise, so the model can't memorise exact beats."""
    shift = np.random.randint(-10, 11)
    x = torch.roll(x, shift, dims=-1)
    x = x * (1 + 0.1 * torch.randn(len(x), 1, 1))
    return x + 0.03 * torch.randn_like(x)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task", choices=["sex", "chd"])
    ap.add_argument("data", type=Path, help=".npz from prepare_beats.py")
    ap.add_argument("--lead", default="V3", choices=["I", "V3"])
    ap.add_argument("--width", type=float, default=0.5)
    ap.add_argument("--teacher", type=Path, help="full-width checkpoint to copy (sex task)")
    ap.add_argument("--init", type=Path, help="start from these weights (same width)")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    torch.manual_seed(0); np.random.seed(0)
    torch.set_num_threads(8)

    d = np.load(args.data, allow_pickle=True)
    ok = d[f"ok_{args.lead}"]
    x = torch.from_numpy(d[f"beat_{args.lead}"][ok])[:, None]
    y = torch.from_numpy((d["male"] if args.task == "sex" else d["chd"])[ok].astype(np.float32))
    patient, age = d["patient"][ok], d["age_days"][ok]

    if "fold" in d.files:      # PTB-XL's own patient-wise folds: 1-8 train, 9 validation, 10 test
        fold = d["fold"][ok]
        tr, va, te = np.where(fold <= 8)[0], np.where(fold == 9)[0], np.where(fold == 10)[0]
    else:                      # 70 / 15 / 15 by patient
        idx = np.arange(len(y))
        trva, te = next(GroupShuffleSplit(1, test_size=0.15, random_state=42).split(idx, groups=patient))
        a, b = next(GroupShuffleSplit(1, test_size=0.1765, random_state=42).split(trva, groups=patient[trva]))
        tr, va = trva[a], trva[b]
    print(f"{args.task} / lead {args.lead}: train {len(tr)}, val {len(va)}, test {len(te)}; positives {y.mean():.1%}")

    teacher_logit = None
    if args.teacher:
        teacher = ECGNet(1.0)
        teacher.load_state_dict(torch.load(args.teacher, map_location="cpu", weights_only=True))
        teacher_logit = predict(teacher, x)
        print(f"teacher (full width): val AUC {roc_auc_score(y[va], teacher_logit[va]):.4f}, "
              f"test AUC {roc_auc_score(y[te], teacher_logit[te]):.4f}")

    model = ECGNet(args.width)
    if args.init:
        model.load_state_dict(torch.load(args.init, map_location="cpu", weights_only=True))
    n_params = sum(p.numel() for n, p in model.named_parameters())
    print(f"width {args.width}: {n_params:,} weights")
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-2)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=args.epochs * (len(tr) // 128 + 1))
    pos_weight = (1 - y[tr].mean()) / y[tr].mean()
    bce = nn.BCEWithLogitsLoss(pos_weight=pos_weight if args.task == "chd" else None)
    soft = nn.BCEWithLogitsLoss()

    best_auc, best_state, best_epoch = 0, None, 0
    for epoch in range(1, args.epochs + 1):
        model.train()
        perm = np.random.permutation(tr)
        total = 0.0
        for i in range(0, len(perm), 128):
            b = perm[i:i + 128]
            logit = model(augment(x[b]))[:, 0]
            loss = bce(logit, y[b])
            if teacher_logit is not None:   # half the loss: match the full model's probability
                loss = 0.5 * loss + 0.5 * soft(logit, torch.sigmoid(teacher_logit[b]))
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
            total += loss.item() * len(b)
        auc = roc_auc_score(y[va], predict(model, x[va]))
        flag = ""
        if auc > best_auc:
            best_auc, best_epoch, flag = auc, epoch, "  <- best"
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        print(f"epoch {epoch:2d}: train loss {total / len(tr):.4f}, val AUC {auc:.4f}{flag}", flush=True)

    model.load_state_dict(best_state)
    p_va, p_te = torch.sigmoid(predict(model, x[va])).numpy(), torch.sigmoid(predict(model, x[te])).numpy()
    fpr, tpr, thr = roc_curve(y[va], p_va)
    threshold = float(thr[np.argmax(tpr - fpr)])
    result = {"task": args.task, "lead": args.lead, "width": args.width, "weights": n_params, "data": args.data.name,
              "best_epoch": best_epoch, "val_auc": float(best_auc), "test_auc": float(roc_auc_score(y[te], p_te)),
              "val_threshold": threshold, "n_train": len(tr), "n_val": len(va), "n_test": len(te)}
    if teacher_logit is not None:
        result["teacher_test_auc"] = float(roc_auc_score(y[te], teacher_logit[te]))
    print(f"test AUC {result['test_auc']:.4f} (val {best_auc:.4f}, epoch {best_epoch}), threshold {threshold:.3f}")
    if args.task == "chd":      # how it does per age group, on the test patients only
        yt, at = y[te].numpy(), age[te]
        result["test_by_age"] = {}
        for lo, hi, name in [(0, 28, "0-28 days"), (28, 365, "1-12 months"), (365, 2190, "1-6 years"), (2190, 99999, "6+ years")]:
            s = (at >= lo) & (at < hi)
            if s.sum() and 0 < yt[s].sum() < s.sum():
                sens = float(np.mean(p_te[s][yt[s] == 1] >= threshold)); spec = float(np.mean(p_te[s][yt[s] == 0] < threshold))
                result["test_by_age"][name] = {"n": int(s.sum()), "chd": int(yt[s].sum()), "auc": float(roc_auc_score(yt[s], p_te[s])),
                                               "sensitivity": sens, "specificity": spec}
                print(f"  {name:12s} n={s.sum():4d} CHD={int(yt[s].sum()):3d} AUC={result['test_by_age'][name]['auc']:.3f} "
                      f"sensitivity {sens:.0%} specificity {spec:.0%}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_state, args.out.with_suffix(".pth"))
    args.out.with_suffix(".json").write_text(json.dumps(result, indent=2))
    np.savez(args.out.with_suffix(".npz"), y_test_true=y[te].numpy(), y_test_probs=p_te, val_threshold=threshold)
    print("saved", args.out.with_suffix(".pth"))


if __name__ == "__main__":
    main()
