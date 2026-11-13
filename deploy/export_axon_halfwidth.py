#!/usr/bin/env python3
"""Export a width-scaled median-beat model (deploy/train_halfwidth.py) for the Axon NPU.

Same split as deploy/export_axon_median_beat.py (needs that file and export_axon_model.py next
to it, they are on the Emma branch): the stem runs on the CPU in float, the rest is int8 on the NPU.
Only the channel counts differ, so the firmware front end needs FRONTEND_STEM_CHANNELS from the
generated frontend_params.h (32 for width 0.5) instead of a fixed 64.

Usage (axon venv):
  python deploy/export_axon_halfwidth.py models/2026.11.10/sex_v3_half.pth beats.npz --lead V3 \
      --label male --model-name ecg_sex_half
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import torch

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import tensorflow as tf  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_axon_median_beat as base  # noqa: E402
from export_axon_model import Int8Runner, c_floats, convert_int8, run_axon_compiler, sigmoid  # noqa: E402
from train_halfwidth import ECGNet  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def npu_part(params, channels):
    class Part(base.NpuPart):
        @tf.function(input_signature=[tf.TensorSpec([1, 1, base.POOL_OUT, channels], tf.float32)])
        def single(self, x):
            return self.forward(x)

        @tf.function(input_signature=[tf.TensorSpec([None, 1, base.POOL_OUT, channels], tf.float32)])
        def batched(self, x):
            return self.forward(x)
    return Part(params)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("checkpoint", type=Path, help=".pth from train_halfwidth.py (its .json is read too)")
    ap.add_argument("beats", type=Path, help=".npz from prepare_beats.py")
    ap.add_argument("--lead", default="V3")
    ap.add_argument("--label", default="male", choices=["male", "chd"])
    ap.add_argument("--model-name", required=True)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--n-calib", type=int, default=400)
    ap.add_argument("--n-eval", type=int, default=2000)
    ap.add_argument("--addon-dir", type=Path,
                    default=Path(os.environ.get("EDGE_AI_ADDON_DIR", "/opt/nordic/ncs/sdk-edge-ai")))
    ap.add_argument("--il-buffer", type=int, default=200000)
    ap.add_argument("--skip-compile", action="store_true")
    args = ap.parse_args()
    out = args.out_dir or REPO / f"deploy/out_{args.model_name}"
    fw = out / "firmware_generated"
    fw.mkdir(parents=True, exist_ok=True)

    meta = json.loads(args.checkpoint.with_suffix(".json").read_text())
    model = ECGNet(meta["width"])
    model.load_state_dict(torch.load(args.checkpoint, map_location="cpu", weights_only=True))
    model.eval()
    d = np.load(args.beats, allow_pickle=True)
    ok = d[f"ok_{args.lead}"]
    x, y = d[f"beat_{args.lead}"][ok], d[args.label][ok]
    # Calibration from training records, evaluation from the held-out test fold when there is one.
    # Without folds (pediatric data) the evaluation beats are a random half and include training
    # records: the AUCs printed below then only show that int8 matches float, not real accuracy.
    rng = np.random.default_rng(0)
    if "fold" in d.files:
        fold = d["fold"][ok]
        ci, ei = np.where(fold <= 8)[0], np.where(fold == 10)[0]
    else:
        perm = rng.permutation(len(x)); ci, ei = perm[:len(x) // 2], perm[len(x) // 2:]
    calib = x[rng.choice(ci, args.n_calib, replace=False)]
    ei = rng.choice(ei, min(args.n_eval, len(ei)), replace=False)
    ev, y = x[ei], y[ei]

    stem_w, stem_b, params = base.build_params(model)
    channels = stem_w.shape[0]
    npu = npu_part(params, channels)
    with torch.no_grad():
        torch_logit = model(torch.from_numpy(ev[:, None, :])).numpy()[:, 0]
    P_ev = base.to_nhwc(base.frontend(ev, stem_w, stem_b))
    split_logit = np.concatenate([npu.batched(P_ev[i:i + 64]).numpy()[:, 0] for i in range(0, len(ev), 64)])
    err = np.abs(split_logit - torch_logit).max()
    print(f"Float split model vs PyTorch: logit max err {err:.2e}")
    if err > 1e-3:
        sys.exit("Split model does not match PyTorch, aborting.")

    tfl = convert_int8(npu, base.to_nhwc(base.frontend(calib, stem_w, stem_b)))
    tflite_path = out / f"{args.model_name}_npu_int8.tflite"
    tflite_path.write_bytes(tfl)
    runner = Int8Runner(tfl)
    P_q = runner.quantize(P_ev)
    int8_logit = np.array([runner(q) for q in P_q])
    thr = meta["val_threshold"]
    p_f, p_q = sigmoid(torch_logit), sigmoid(int8_logit)
    from sklearn.metrics import roc_auc_score
    report = {"tflite_kb": len(tfl) / 1024, "n_eval": len(ev),
              "logit_corr": float(np.corrcoef(int8_logit, torch_logit)[0, 1]),
              "same_decision": float(np.mean((p_q >= thr) == (p_f >= thr))),
              "auc_float": float(roc_auc_score(y, p_f)), "auc_int8": float(roc_auc_score(y, p_q))}
    print(f"int8 TFLite ({report['tflite_kb']:.0f} KB) vs PyTorch on {len(ev)} beats: corr {report['logit_corr']:.4f}, "
          f"same decision {report['same_decision']:.1%}, AUC float {report['auc_float']:.4f} | int8 {report['auc_int8']:.4f}")
    (out / "int8_report.json").write_text(json.dumps(report, indent=2))

    test_q_path = out / f"{args.model_name}_test_q.npy"
    np.save(test_q_path, P_q[:8])
    rows = ",\n".join("\t{" + c_floats(r, 15).strip() + "}" for r in stem_w)
    (fw / "frontend_params.h").write_text(
        "/* Generated by deploy/export_axon_halfwidth.py: stem conv with BatchNorm folded in. */\n#pragma once\n\n"
        f"#define FRONTEND_STEM_CHANNELS {channels}\n#define FRONTEND_STEM_KERNEL 15\n\n"
        f"static const float frontend_stem_w[{channels}][15] = {{\n{rows}\n}};\n\n"
        f"static const float frontend_stem_b[{channels}] = {{\n{c_floats(stem_b)}\n}};\n")
    base.write_test_header(fw / "test_beats.h", ev[:4], torch_logit[:4], int8_logit[:4], thr)
    if args.skip_compile:
        return
    rc = run_axon_compiler(args.addon_dir, out, args.model_name, tflite_path, test_q_path, args.il_buffer)
    header = out / "outputs" / f"nrf_axon_model_{args.model_name}_.h"
    if rc == 0 and header.exists():
        shutil.copy(header, fw / header.name)
    sys.exit(rc)


if __name__ == "__main__":
    main()
