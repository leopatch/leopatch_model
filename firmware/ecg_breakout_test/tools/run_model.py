"""Run the 800-sample median-beat model on recordings from the ecg_breakout_test firmware.

For each CSV: find the heartbeats, cut an 800-sample window around each one (R peak 250 samples
in), take the median beat, z-score it like the training data, and run the model. Also saves a
picture of the median beat next to each CSV.

The median-beat steps are a reconstruction (the training script for this model isn't in the repo).
On PTB-XL lead V3 they give AUC 0.80, close to the reported 0.84 on MIMIC.

usage: python run_model.py <model.pth> <recording.csv> [more.csv ...]
"""
import sys
from pathlib import Path

import matplotlib
import neurokit2 as nk
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from scipy import signal

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

FS, WIN, R_OFFSET = 500, 800, 250


class ResBlock1D(nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.conv1 = nn.Conv1d(channels, channels, 7, padding=3)
        self.bn1 = nn.BatchNorm1d(channels)
        self.conv2 = nn.Conv1d(channels, channels, 7, padding=3)
        self.bn2 = nn.BatchNorm1d(channels)

    def forward(self, x):
        out = torch.relu(self.bn1(self.conv1(x)))
        return torch.relu(self.bn2(self.conv2(out)) + x)


class ECGSexClassifier(nn.Module):
    """Same layers as finetune_12lead_for_1lead_script.ipynb (eval only)."""

    def __init__(self):
        super().__init__()
        self.stem = nn.Sequential(nn.Conv1d(1, 64, 15, stride=2, padding=7), nn.BatchNorm1d(64), nn.ReLU(),
                                  nn.MaxPool1d(3, stride=2, padding=1))
        self.layer1 = nn.Sequential(nn.Conv1d(64, 128, 7, stride=2, padding=3), nn.BatchNorm1d(128), nn.ReLU())
        self.res1 = ResBlock1D(128)
        self.layer2 = nn.Sequential(nn.Conv1d(128, 256, 7, stride=2, padding=3), nn.BatchNorm1d(256), nn.ReLU())
        self.res2 = ResBlock1D(256)
        self.fc = nn.Sequential(nn.Dropout(0.5), nn.Linear(256, 64), nn.ReLU(), nn.Linear(64, 1))

    def forward(self, x):
        x = self.res1(self.layer1(self.stem(x)))
        x = self.res2(self.layer2(x))
        return self.fc(x.mean(-1))


def load_ecg(path):
    """The board's filtered signal, or the raw one with hum removed for older recordings."""
    df = pd.read_csv(path)
    if "filtered_mv" in df:
        return df["filtered_mv"].to_numpy(float), df["lead_off"].to_numpy(int)
    sig = df.iloc[:, 0].to_numpy(float)
    for f0 in (60, 120, 180):
        b, a = signal.iirnotch(f0, 30, FS)
        sig = signal.filtfilt(b, a, sig)
    return sig, df.iloc[:, 1].to_numpy(int)


def median_beat(sig):
    peaks = nk.ecg_peaks(nk.ecg_clean(sig, sampling_rate=FS), sampling_rate=FS)[1]["ECG_R_Peaks"]
    beats = [sig[r - R_OFFSET:r - R_OFFSET + WIN] for r in peaks
             if r - R_OFFSET >= 0 and r - R_OFFSET + WIN <= len(sig)]
    if len(beats) < 2:
        return None, len(peaks), len(beats)
    med = np.median(np.stack(beats), axis=0)
    return (med - med.mean()) / max(med.std(), 1e-6), len(peaks), len(beats)


def main():
    model = ECGSexClassifier()
    model.load_state_dict(torch.load(sys.argv[1], map_location="cpu", weights_only=True))
    model.eval()
    for path in map(Path, sys.argv[2:]):
        sig, lead_off = load_ecg(path)
        if lead_off.any():
            print(f"{path.name}: skipped, an electrode was off in {np.mean(lead_off > 0):.0%} of samples")
            continue
        beat, n_peaks, n_used = median_beat(sig)
        if beat is None:
            print(f"{path.name}: skipped, only {n_used} full beats (found {n_peaks} peaks)")
            continue
        with torch.no_grad():
            p = torch.sigmoid(model(torch.from_numpy(beat.astype(np.float32))[None, None])).item()
        bpm = 60 * FS / np.median(np.diff(nk.ecg_peaks(nk.ecg_clean(sig, sampling_rate=FS),
                                                       sampling_rate=FS)[1]["ECG_R_Peaks"]))
        print(f"{path.name}: {n_used} beats in the median, {bpm:.0f} bpm -> "
              f"P(male) = {p:.2f}, P(female) = {1 - p:.2f}")

        fig, ax = plt.subplots(figsize=(6, 3))
        ax.plot(np.arange(WIN) / FS, beat)
        ax.set(xlabel="time (s)", ylabel="z-score", title=f"median beat ({n_used} beats): P(male) {p:.2f}")
        fig.tight_layout()
        fig.savefig(path.with_suffix(".beat.png"), dpi=100)
        plt.close(fig)


if __name__ == "__main__":
    main()
