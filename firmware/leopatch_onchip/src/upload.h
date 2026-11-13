/*
 * Bluetooth upload of the last result and recording over the Nordic UART Service (NUS).
 * The radio is only used during an upload: advertise as "LeoPatch", wait for a phone or laptop to
 * connect and subscribe, send, disconnect, stop advertising.
 */
#pragma once

#include <zephyr/kernel.h>

/* Turn on the Bluetooth stack (the radio stays off until upload_send). */
int upload_init(void);

/**
 * Send one result line, then the recording as one "filtered_mv" line per sample, then "# end".
 *
 * @param result  Result text without newline, e.g. "WOMAN,0.74,5,65".
 * @param samples Recording in mV.
 * @param n       Number of samples.
 * @param wait    How long to advertise for a receiver before giving up.
 * @return 0 when everything was sent, -ETIMEDOUT if nobody connected, other negative on error.
 */
int upload_send(const char *result, const float *samples, int n, k_timeout_t wait);
