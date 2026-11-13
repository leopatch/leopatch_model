#!/usr/bin/env python3
"""Turn WFDB ECG records into 800-sample median beats, the input of the median-beat model.

Same steps as firmware/ecg_breakout_test/tools/run_model.py: find the R peaks, cut 800 samples
around each (R peak 250 samples in), take the median, z-score. Works on 500 Hz records.

  pediatric (ZZU pECG, figshare 27078763):
    python deploy/prepare_beats.py pediatric <folder with AttributesDictionary.csv> <Child_ecg folder> out.npz
  PTB-XL (adults, only the records already downloaded are used):
    python deploy/prepare_beats.py ptbxl <folder with ptbxl_database.csv> out.npz

Add --highpass=0.5 at the end to first pass every lead through a causal 2-pole 0.5 Hz high-pass, the way the
AD8232 front end does on the board (hospital recordings go down to about 0.05 Hz).

The .npz holds, per record: beat_I and beat_V3 (N, 800), ok_I / ok_V3 (a median beat was found),
male (1 = male), age_days, patient, hr (beats per minute), n_beats, and for pediatric chd / ccode.
"""
import csv
import re
import sys
import warnings
from multiprocessing import Pool
from pathlib import Path

import numpy as np

FS, WIN, R_OFFSET = 500, 800, 250
LEADS = ("I", "V3")
HIGHPASS = next((float(a.split("=")[1]) for a in sys.argv if a.startswith("--highpass=")), None)
sys.argv = [a for a in sys.argv if not a.startswith("--highpass=")]


def median_beat(sig):
    import neurokit2 as nk
    sig = np.nan_to_num(np.asarray(sig, float))
    if HIGHPASS:
        from scipy.signal import butter, lfilter
        b, a = butter(2, HIGHPASS / (FS / 2), "highpass")
        sig = lfilter(b, a, sig - sig[0])       # forward only: same phase distortion as the analog filter
    peaks = nk.ecg_peaks(nk.ecg_clean(sig, sampling_rate=FS), sampling_rate=FS)[1]["ECG_R_Peaks"]
    beats = [sig[r - R_OFFSET:r - R_OFFSET + WIN] for r in peaks
             if r - R_OFFSET >= 0 and r - R_OFFSET + WIN <= len(sig)]
    if len(beats) < 2:
        return None, 0.0, len(beats)
    med = np.median(np.stack(beats), axis=0)
    hr = 60 * FS / np.median(np.diff(peaks))
    return ((med - med.mean()) / max(med.std(), 1e-6)).astype(np.float32), hr, len(beats)


def one(path):
    import wfdb
    out = {}
    warnings.filterwarnings("ignore")
    try:
        rec = wfdb.rdrecord(str(path))
        names = [n.upper() for n in rec.sig_name]
        for lead in LEADS:
            if lead in names:
                # at most 30 s: enough beats for a median, and keeps long records fast
                out[lead] = median_beat(rec.p_signal[:30 * FS, names.index(lead)])
    except Exception:
        pass
    return out


def main():
    kind = sys.argv[1]
    if kind == "pediatric":
        meta_dir, rec_dir, out_path = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
        rows = list(csv.DictReader(open(meta_dir / "AttributesDictionary.csv")))
        paths = [rec_dir / r["Filename"] for r in rows]
        male = [int("Female" not in r["Gender"]) for r in rows]
        age = [int(re.match(r"(\d+)d", r["Age"]).group(1)) for r in rows]
        patient = [r["Patient_ID"] for r in rows]
        # congenital heart disease: any Q20-Q26 code (structural heart and great-vessel defects)
        extra = {"chd": [int(bool(re.search(r"Q2[0-6]", r["ICD-10 code"]))) for r in rows],
                 "icd": [r["ICD-10 code"] for r in rows]}
    else:
        meta_dir, out_path = Path(sys.argv[2]), sys.argv[3]
        rows = [r for r in csv.DictReader(open(meta_dir / "ptbxl_database.csv"))
                if (meta_dir / (r["filename_hr"] + ".dat")).exists() and (meta_dir / (r["filename_hr"] + ".hea")).exists()]
        paths = [meta_dir / r["filename_hr"] for r in rows]
        male = [int(r["sex"] == "0") for r in rows]          # PTB-XL: 0 = male, 1 = female
        age = [int(float(r["age"]) * 365) if r["age"] else -1 for r in rows]
        patient = [r["patient_id"] for r in rows]
        extra = {"fold": [int(r["strat_fold"]) for r in rows]}

    with Pool(7) as pool:
        res = pool.map(one, paths, chunksize=32)
    n = len(rows)
    data = {"male": np.array(male), "age_days": np.array(age), "patient": np.array(patient),
            **{k: np.array(v) for k, v in extra.items()}}
    for lead in LEADS:
        beat = np.zeros((n, WIN), np.float32); ok = np.zeros(n, bool); hr = np.zeros(n); nb = np.zeros(n, int)
        for i, r in enumerate(res):
            if lead in r and r[lead][0] is not None:
                beat[i], hr[i], nb[i] = r[lead]; ok[i] = True
        data.update({f"beat_{lead}": beat, f"ok_{lead}": ok, f"hr_{lead}": hr, f"n_beats_{lead}": nb})
        print(f"lead {lead}: {ok.sum()} of {n} records gave a median beat")
    np.savez_compressed(out_path, **data)
    print("saved", out_path)


if __name__ == "__main__":
    main()
