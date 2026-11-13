#include <stdbool.h>

#include <zephyr/sys/util.h>

#include "beats.h"
#include "recording.h"

#define FS           500
#define DERIV_HALF   2              /* derivative x[n + 2] - x[n - 2] */
#define INTEG        40             /* 80 ms moving sum of the squared derivative */
#define REFRACTORY   (FS * 3 / 10)  /* 300 ms: at most 200 bpm */
#define SEARCH_BACK  40
#define SEARCH_FWD   60
#define THRESH_FRAC  0.3f

/* Squared-derivative energy, one value per recorded sample. */
static float energy[RECORDING_LEN];

static void compute_energy(const float *x, int n)
{
	float sum = 0.0f;
	float sq[INTEG] = {0};

	for (int i = 0; i < n; i++) {
		float d = (i >= DERIV_HALF && i < n - DERIV_HALF) ? x[i + DERIV_HALF] - x[i - DERIV_HALF]
								   : 0.0f;

		/* causal moving sum over the last INTEG squared derivatives */
		sum += d * d - sq[i % INTEG];
		sq[i % INTEG] = d * d;
		energy[i] = sum;
	}
}

int beats_find_r_peaks(const float *x, int n, int *peaks, int max_peaks)
{
	int lo_cand[PEAKS_MAX];
	int hi_cand[PEAKS_MAX];
	int n_cand = 0;
	float thr = 0.0f;

	if (n > RECORDING_LEN || n <= 2 * INTEG + SEARCH_FWD) {
		return 0;
	}
	compute_energy(x, n);
	for (int i = INTEG; i < n - INTEG; i++) {
		thr = MAX(thr, energy[i]);
	}
	thr *= THRESH_FRAC;

	/* candidate QRS regions: energy above threshold, then skip the refractory period */
	for (int i = INTEG; i < n - SEARCH_FWD && n_cand < PEAKS_MAX;) {
		if (energy[i] <= thr) {
			i++;
			continue;
		}
		int lo = MAX(i - SEARCH_BACK - INTEG, 0);

		lo_cand[n_cand] = lo;
		hi_cand[n_cand] = MIN(i + SEARCH_FWD, n);
		n_cand++;
		i = (lo + REFRACTORY + INTEG > i) ? lo + REFRACTORY + INTEG : i + REFRACTORY;
		while (i < n && energy[i] > thr) {
			i++;
		}
	}
	if (n_cand == 0) {
		return 0;
	}

	/* one polarity for the whole recording: whichever extreme is bigger across the beats */
	float mean = 0.0f;
	float up = 0.0f;
	float down = 0.0f;

	for (int i = 0; i < n; i++) {
		mean += x[i];
	}
	mean /= n;
	for (int c = 0; c < n_cand; c++) {
		float mx = x[lo_cand[c]];
		float mn = mx;

		for (int i = lo_cand[c]; i < hi_cand[c]; i++) {
			mx = MAX(mx, x[i]);
			mn = MIN(mn, x[i]);
		}
		up += mx - mean;
		down += mean - mn;
	}
	const float pol = up >= down ? 1.0f : -1.0f;

	/* R peak = extreme in each region; drop peaks closer than the refractory period */
	int count = 0;

	for (int c = 0; c < n_cand; c++) {
		int p = lo_cand[c];

		for (int i = lo_cand[c]; i < hi_cand[c]; i++) {
			if (pol * x[i] > pol * x[p]) {
				p = i;
			}
		}
		if (count > 0 && p - peaks[count - 1] < REFRACTORY) {
			if (pol * x[p] > pol * x[peaks[count - 1]]) {
				peaks[count - 1] = p;
			}
			continue;
		}
		if (count < max_peaks) {
			peaks[count++] = p;
		}
	}
	return count;
}

int beats_median(const float *x, int n, const int *peaks, int n_peaks, float *beat)
{
	int start[BEAT_MAX];
	int k = 0;

	for (int i = 0; i < n_peaks && k < BEAT_MAX; i++) {
		int s = peaks[i] - BEAT_R_OFFSET;

		if (s >= 0 && s + BEAT_LEN <= n) {
			start[k++] = s;
		}
	}
	if (k < 2) {
		return k;
	}

	for (int t = 0; t < BEAT_LEN; t++) {
		float v[BEAT_MAX];

		/* insertion sort of the k values at this time point */
		for (int i = 0; i < k; i++) {
			float val = x[start[i] + t];
			int j = i;

			while (j > 0 && v[j - 1] > val) {
				v[j] = v[j - 1];
				j--;
			}
			v[j] = val;
		}
		beat[t] = (k & 1) ? v[k / 2] : 0.5f * (v[k / 2 - 1] + v[k / 2]);
	}
	return k;
}
