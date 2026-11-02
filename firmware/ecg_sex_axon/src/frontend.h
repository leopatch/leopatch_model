/*
 * CPU front end of the ECG sex classifier: z-score normalization, stem conv + BN + ReLU and
 * max-pool. Mirrors frontend() in deploy/export_axon_model.py.
 */
#pragma once

#include <stdint.h>

#define FRONTEND_IN_LEN  5000 /* 10 s at 500 Hz */
#define FRONTEND_OUT_CH  128  /* 2 phases x 64 stem channels */
#define FRONTEND_OUT_LEN 625  /* 1250 pooled samples / 2 phases */

/**
 * Run the front end on one raw single-lead ECG and quantize the result for the NPU.
 *
 * @param raw        FRONTEND_IN_LEN raw samples (non-finite values are treated as 0).
 * @param out        int8 NPU input, packed channel-first: out[ch * FRONTEND_OUT_LEN + m] holds
 *                   pooled sample 2 * m + phase of stem channel c, where ch = phase * 64 + c.
 * @param inv_scale  1 / input scale of the compiled model.
 * @param zero_point Input zero point of the compiled model.
 */
void frontend_run(const float *raw, int8_t *out, float inv_scale, int8_t zero_point);
