"""Run the 10 s lead I sex model on recordings (wrist pads: red right wrist, yellow left wrist).

Prepares the signal like the training notebook: the whole 10 s z-scored, nothing else.

Cutoff: 0.85, set by hand between two people's wrist recordings on the AD8232 breakout (woman
0.67-0.73, man 0.97-0.98, 2026-11-04). Our board scores everyone higher than PTB-XL lead I does,
where 0.57 balances men and women (AUC 0.78). Re-pick it once more people are recorded; the
teammate's own cutoff isn't known (no .npz for this model).

usage: python score_lead1.py <recording.csv> [more.csv ...]
Reads ecg_*.csv (from plot_ecg.py) and ble_*.csv (from ble_receive.py).
"""
import sys
from pathlib import Path

import numpy as np
import torch

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "firmware/ecg_breakout_test/tools"))
from run_model import ECGSexClassifier  # noqa: E402  (same layers as the 10 s model)

CHECKPOINT = REPO / "models/2026.10.08/2_best_ecg_sex_lead1_finetuned_15epochs.pth"
CUTOFF = 0.85
FS = 500

_model = None


def p_male(mv):
    """P(male) for one recording in mV (any length; the model was trained on 10 s)."""
    global _model
    if _model is None:
        _model = ECGSexClassifier()
        _model.load_state_dict(torch.load(CHECKPOINT, map_location="cpu", weights_only=True))
        _model.eval()
    x = np.asarray(mv, np.float32)
    x = (x - x.mean()) / max(float(x.std()), 1e-6)
    with torch.no_grad():
        return torch.sigmoid(_model(torch.from_numpy(x)[None, None])).item()


def verdict(p):
    return f"{'MAN' if p >= CUTOFF else 'WOMAN'} (lead I model, P(male) {p:.2f}, cutoff {CUTOFF})"


def load_mv(path):
    """Filtered mV column of an ecg_*.csv or ble_*.csv recording."""
    lines = [l for l in Path(path).read_text().splitlines() if l and not l.startswith("#")]
    header = lines[0].split(",")
    col = header.index("filtered_mv")
    return np.array([float(l.split(",")[col]) for l in lines[1:]])


def main():
    for path in sys.argv[1:]:
        mv = load_mv(path)
        note = "" if len(mv) >= 10 * FS else f"  [only {len(mv) / FS:.0f} s, trained on 10 s]"
        print(f"{Path(path).name}: {verdict(p_male(mv))}{note}")


if __name__ == "__main__":
    main()
