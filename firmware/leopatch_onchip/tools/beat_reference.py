"""Python mirror of the firmware's beat finder and median beat (src/beats.c).

Used to check the on-chip algorithm against neurokit before trusting it on the board.
"""
import numpy as np

FS = 500
WIN = 800                  # median beat length (1.6 s)
R_OFFSET = 250             # R peak position inside the window
DERIV_HALF = 2             # derivative x[n + 2] - x[n - 2]
INTEG = 40                 # 80 ms moving sum of the squared derivative
REFRACTORY = FS * 3 // 10  # 300 ms: at most 200 bpm
SEARCH_BACK, SEARCH_FWD = 40, 60
THRESH_FRAC = 0.3
MAX_BEATS = 8


def find_r_peaks(x):
    n = len(x)
    d = np.zeros(n)
    d[DERIV_HALF:n - DERIV_HALF] = x[2 * DERIV_HALF:] - x[:n - 2 * DERIV_HALF]
    e = np.convolve(d * d, np.ones(INTEG), "full")[:n]     # causal moving sum
    thr = THRESH_FRAC * e[INTEG:n - INTEG].max()
    cands = []
    n_i = INTEG
    while n_i < n - SEARCH_FWD:
        if e[n_i] > thr:
            lo, hi = max(n_i - SEARCH_BACK - INTEG, 0), min(n_i + SEARCH_FWD, n)
            cands.append((lo, hi))
            n_i = lo + REFRACTORY + INTEG if lo + REFRACTORY + INTEG > n_i else n_i + REFRACTORY
            while n_i < n and e[n_i] > thr:
                n_i += 1
        else:
            n_i += 1
    if not cands:
        return np.array([], int)
    # one polarity for the whole recording: whichever extreme is bigger across the beats
    mean = x.mean()
    up = sum(x[lo:hi].max() - mean for lo, hi in cands)
    down = sum(mean - x[lo:hi].min() for lo, hi in cands)
    pol = 1.0 if up >= down else -1.0
    peaks = [lo + int(np.argmax(pol * x[lo:hi])) for lo, hi in cands]
    # drop peaks closer than the refractory period (keep the bigger one)
    out = []
    for p in peaks:
        if out and p - out[-1] < REFRACTORY:
            if pol * x[p] > pol * x[out[-1]]:
                out[-1] = p
            continue
        out.append(p)
    return np.array(out, int)


def median_beat(x):
    """Median of up to MAX_BEATS 800-sample windows (R at 250), z-scored. None if < 2 beats."""
    peaks = find_r_peaks(x)
    wins = [x[r - R_OFFSET:r - R_OFFSET + WIN] for r in peaks
            if r - R_OFFSET >= 0 and r - R_OFFSET + WIN <= len(x)][:MAX_BEATS]
    if len(wins) < 2:
        return None, peaks
    m = np.median(np.stack(wins), axis=0)
    s = m.std()
    return (m - m.mean()) / (s if s > 1e-6 else 1.0), peaks
