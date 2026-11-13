/*
 * Heartbeat (R peak) finder and median beat. Mirrors tools/beat_reference.py.
 */
#pragma once

#define BEAT_LEN      800 /* median beat window: 1.6 s at 500 Hz */
#define BEAT_R_OFFSET 250 /* R peak position inside the window */
#define BEAT_MAX      8   /* beats used for the median */
#define PEAKS_MAX     32

/**
 * Find R peaks in a hum-filtered ECG sampled at 500 Hz.
 *
 * @return number of peaks written to @p peaks (sample indices, increasing).
 */
int beats_find_r_peaks(const float *x, int n, int *peaks, int max_peaks);

/**
 * Median of up to BEAT_MAX windows of BEAT_LEN samples around the R peaks (not normalized).
 *
 * @return number of beats used; less than 2 means no usable median beat.
 */
int beats_median(const float *x, int n, const int *peaks, int n_peaks, float *beat);
