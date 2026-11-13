/*
 * CPU front end of the median-beat ECG sex classifier: z-score normalization, stem conv + BN +
 * ReLU and max-pool. Mirrors frontend() in deploy/export_axon_median_beat.py.
 */
#pragma once

#include <stdint.h>

#define FRONTEND_IN_LEN  800 /* one median beat */
#define FRONTEND_OUT_CH  MODEL_STEM_CHANNELS /* stem channels, from frontend_params.h via CMake */
#define FRONTEND_OUT_LEN 200 /* 800 -> stride-2 stem 400 -> stride-2 max-pool 200 */

/**
 * Run the front end on one median beat and quantize the result for the NPU.
 *
 * @param beat       FRONTEND_IN_LEN samples (non-finite values are treated as 0).
 * @param out        int8 NPU input, channel-first: out[c * FRONTEND_OUT_LEN + m].
 * @param inv_scale  1 / input scale of the compiled model.
 * @param zero_point Input zero point of the compiled model.
 */
void frontend_run(const float *beat, int8_t *out, float inv_scale, int8_t zero_point);
