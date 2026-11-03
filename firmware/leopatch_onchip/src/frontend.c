#include <math.h>

#include <zephyr/sys/util.h>

#include "frontend.h"
#include "generated/frontend_params.h"

#define PAD      ((FRONTEND_STEM_KERNEL - 1) / 2) /* stem conv padding (7) */
#define STEM_LEN (FRONTEND_IN_LEN / 2)            /* stride-2 stem output (400) */

BUILD_ASSERT(STEM_LEN == 2 * FRONTEND_OUT_LEN);
BUILD_ASSERT(FRONTEND_OUT_CH == FRONTEND_STEM_CHANNELS);

/* Normalized beat with PAD zeros on each side, so the stem conv needs no bounds checks. */
static float x_pad[FRONTEND_IN_LEN + 2 * PAD];

/* Per-beat z-score, as in the training data. */
static void normalize(const float *beat)
{
	float *x = &x_pad[PAD];
	double sum = 0.0;
	double var = 0.0;

	for (int i = 0; i < FRONTEND_IN_LEN; i++) {
		x[i] = isfinite(beat[i]) ? beat[i] : 0.0f;
		sum += (double)x[i];
	}

	const float mean = (float)(sum / FRONTEND_IN_LEN);

	for (int i = 0; i < FRONTEND_IN_LEN; i++) {
		const float d = x[i] - mean;

		var += (double)(d * d);
	}

	float std = (float)sqrt(var / FRONTEND_IN_LEN);

	if (std < 1e-6f) {
		std = 1.0f;
	}
	for (int i = 0; i < FRONTEND_IN_LEN; i++) {
		x[i] = (x[i] - mean) / std;
	}
}

/* ReLU(BN(conv)) of all stem channels at stem output sample n. */
static void stem(int n, float *z)
{
	const float *xs = &x_pad[2 * n];

	for (int c = 0; c < FRONTEND_STEM_CHANNELS; c++) {
		float acc = frontend_stem_b[c];

		for (int k = 0; k < FRONTEND_STEM_KERNEL; k++) {
			acc += frontend_stem_w[c][k] * xs[k];
		}
		z[c] = acc > 0.0f ? acc : 0.0f;
	}
}

void frontend_run(const float *beat, int8_t *out, float inv_scale, int8_t zero_point)
{
	/* stem outputs 2m - 1, 2m and 2m + 1. Stem output -1 is padding: 0 is safe after ReLU. */
	float prev[FRONTEND_STEM_CHANNELS] = {0};
	float z0[FRONTEND_STEM_CHANNELS];
	float z1[FRONTEND_STEM_CHANNELS];

	normalize(beat);

	for (int m = 0; m < FRONTEND_OUT_LEN; m++) {
		stem(2 * m, z0);
		stem(2 * m + 1, z1);

		for (int c = 0; c < FRONTEND_STEM_CHANNELS; c++) {
			const float pooled = fmaxf(prev[c], fmaxf(z0[c], z1[c]));
			const int32_t q = (int32_t)lrintf(pooled * inv_scale) + zero_point;

			out[c * FRONTEND_OUT_LEN + m] = (int8_t)CLAMP(q, INT8_MIN, INT8_MAX);
			prev[c] = z1[c];
		}
	}
}
