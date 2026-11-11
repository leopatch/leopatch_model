/*
 * LEO PATCH -- 1-lead ECG sex model on the nRF54LM20B DK, running on the AXON NPU.
 *
 * Same job and the same wire protocol as board_fw/ (the Cortex-M33 + TensorFlow Lite Micro version), so
 * `board_runner.py run --engine axon ...` talks to either firmware.
 *
 * The host streams one int8 ECG window (1000 samples = 10 s at 100 Hz, already quantized with the model's
 * input scale / zero point) over the console UART (the DK's USB virtual COM port); this firmware runs the
 * model on Axon and answers with the int8 logit and how long the inference took.
 *
 * Protocol (host -> board, binary)            Board -> host (ASCII lines, plus the single byte 'K')
 *   A5 5A 'I'                                  INFO engine=axon model=.. model_bytes=.. model_crc32=..
 *                                                   arena_size=.. arena_used=.. in_bytes=.. in_zp=.. out_zp=..
 *                                                   status=..
 *   A5 5A 'W' len_lo len_hi                    (then after every 250 payload bytes: 'K')
 *   <len payload bytes, int8>
 *   crc16_lo crc16_hi   (CRC-16/CCITT-FALSE    RES q=<int8 logit> ms=<ms> us=<microseconds>   or   ERR <reason>
 *                        of the payload)
 *
 * Written against Nordic's hello_axon sample (sdk-edge-ai/samples/axon/hello_axon); NOT yet built or run on
 * hardware -- see README.md.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/fatal.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/reboot.h>

#include <axon/nrf_axon_platform.h>
#include <drivers/axon/nrf_axon_driver.h>
#include <drivers/axon/nrf_axon_nn_infer.h>

/* The compiled model (made by Nordic's Axon compiler from the _axon_int8.tflite files in export_out/axon). */
#if defined(CONFIG_ECG_MODEL_W25)
#include "generated/nrf_axon_model_ecg_sex_w25_.h"
#define MODEL model_ecg_sex_w25
#else
#include "generated/nrf_axon_model_ecg_sex_w50_b10_.h"
#define MODEL model_ecg_sex_w50_b10
#endif

#define SYNC0 0xA5
#define SYNC1 0x5A
#define CHUNK 250u
#define MAX_IN 1024u            /* Axon tensor-size limit; the model input is 1000 samples */
#define MAX_OUT 8u

/* The UART that is the DK's first virtual COM port (devicetree "zephyr,console"). */
static const struct device *const uart = DEVICE_DT_GET(DT_CHOSEN(zephyr_console));

static int8_t in_buf[MAX_IN];
static int8_t out_buf[MAX_OUT] __aligned(4);
static const char *model_status = "init";
static uint32_t model_crc;
static uint32_t model_bytes;
static uint32_t in_len;

static uint16_t crc16_ccitt_false(const uint8_t *d, size_t n)
{
	uint16_t c = 0xFFFF;

	while (n--) {
		c ^= (uint16_t)(*d++) << 8;
		for (int i = 0; i < 8; i++) {
			c = (c & 0x8000) ? (uint16_t)((c << 1) ^ 0x1021) : (uint16_t)(c << 1);
		}
	}
	return c;
}

static uint32_t crc32_ieee(const uint8_t *d, size_t n)
{
	uint32_t c = 0xFFFFFFFFu;

	while (n--) {
		c ^= *d++;
		for (int i = 0; i < 8; i++) {
			c = (c & 1u) ? (c >> 1) ^ 0xEDB88320u : (c >> 1);
		}
	}
	return ~c;
}

/* Poll one byte. timeout_ms < 0 waits forever. Busy-polls on purpose: sleeping would drop bytes. */
static bool rx_byte(uint8_t *b, int32_t timeout_ms)
{
	const int64_t deadline = (timeout_ms < 0) ? INT64_MAX : k_uptime_get() + timeout_ms;

	while (uart_poll_in(uart, b) != 0) {
		if (k_uptime_get() > deadline) {
			return false;
		}
	}
	return true;
}

static void tx(const char *s)
{
	for (; *s; ++s) {
		uart_poll_out(uart, (unsigned char)*s);
	}
}

static bool setup_model(void)
{
	nrf_axon_result_e r;

	if (MODEL.inputs[0].dimensions.byte_width != 1 || MODEL.outputs[0].dimensions.byte_width != 1) {
		model_status = "not_int8_io";
		return false;
	}
	in_len = (uint32_t)MODEL.inputs[0].dimensions.height * MODEL.inputs[0].dimensions.width *
		 MODEL.inputs[0].dimensions.channel_cnt;
	/* the window is sent as one contiguous row, so the Axon row stride must equal the width */
	if (in_len == 0 || in_len > MAX_IN || MODEL.inputs[0].stride != MODEL.inputs[0].dimensions.width) {
		model_status = "bad_input_tensor";
		return false;
	}
	if (MODEL.outputs[0].packed_size > MAX_OUT) {
		model_status = "bad_output_tensor";
		return false;
	}
	r = nrf_axon_platform_init();
	if (r != NRF_AXON_RESULT_SUCCESS) {
		model_status = "axon_init_fail";
		return false;
	}
	if (nrf_axon_nn_model_init_vars(&MODEL) != 0) {
		model_status = "init_vars_fail";
		return false;
	}
	r = nrf_axon_nn_model_validate(&MODEL);
	if (r != NRF_AXON_RESULT_SUCCESS) {
		model_status = "model_validate_fail";
		return false;
	}
	model_status = "ok";
	return true;
}

static void send_info(void)
{
	char buf[240];

	snprintf(buf, sizeof(buf),
		 "INFO engine=axon model=%s model_bytes=%u model_crc32=%08x arena_size=%u arena_used=%u "
		 "in_bytes=%u in_zp=%d out_zp=%d status=%s\n",
		 MODEL.model_name, (unsigned)model_bytes, (unsigned)model_crc,
		 (unsigned)CONFIG_NRF_AXON_INTERLAYER_BUFFER_SIZE, (unsigned)MODEL.interlayer_buffer_needed,
		 (unsigned)in_len, (int)MODEL.inputs[0].quant_zp, (int)MODEL.outputs[0].dequant_zp,
		 model_status);
	tx(buf);
}

static void handle_window(void)
{
	uint8_t lb[2];

	if (!rx_byte(&lb[0], 1000) || !rx_byte(&lb[1], 1000)) {
		tx("ERR timeout\n");
		return;
	}
	if (strcmp(model_status, "ok") != 0) {
		tx("ERR model\n");
		return;
	}
	const size_t len = (size_t)lb[0] | ((size_t)lb[1] << 8);

	if (len != in_len) {
		tx("ERR len\n");
		return;
	}

	uint8_t *dst = (uint8_t *)in_buf;

	for (size_t off = 0; off < len; off += CHUNK) {
		const size_t n = (len - off < CHUNK) ? (len - off) : CHUNK;

		for (size_t i = 0; i < n; i++) {
			if (!rx_byte(&dst[off + i], 2000)) {
				tx("ERR timeout\n");
				return;
			}
		}
		uart_poll_out(uart, 'K');
	}

	uint8_t cb[2];

	if (!rx_byte(&cb[0], 2000) || !rx_byte(&cb[1], 2000)) {
		tx("ERR timeout\n");
		return;
	}
	const uint16_t want = (uint16_t)cb[0] | (uint16_t)((uint16_t)cb[1] << 8);

	if (crc16_ccitt_false(dst, len) != want) {
		tx("ERR crc\n");
		return;
	}

	/* The bytes are already int8 in the model's input quantization (the host used the same scale / zero
	 * point as the .tflite); the window is one row of 1000 samples, so no re-layout is needed. */
	memset(out_buf, 0, sizeof(out_buf));
	const uint32_t c0 = k_cycle_get_32();
	const nrf_axon_result_e r = nrf_axon_nn_model_infer_sync(&MODEL, in_buf, out_buf);
	const uint32_t us = k_cyc_to_us_near32(k_cycle_get_32() - c0);

	if (r != NRF_AXON_RESULT_SUCCESS) {
		char eb[40];

		snprintf(eb, sizeof(eb), "ERR invoke %d\n", (int)r);
		tx(eb);
		return;
	}

	char buf[64];

	snprintf(buf, sizeof(buf), "RES q=%d ms=%u us=%u\n", (int)out_buf[0], (unsigned)((us + 500u) / 1000u),
		 (unsigned)us);
	tx(buf);
}

/* On a CPU fault, say why over the same UART, then reboot (the host prints this line).
 * Hand-rolled hex so nothing heavy runs on the small exception stack. */
static void hex8(char *o, uint32_t v)
{
	for (int i = 7; i >= 0; i--, v >>= 4) {
		o[i] = "0123456789abcdef"[v & 15];
	}
	o[8] = 0;
}

void k_sys_fatal_error_handler(unsigned int reason, const struct arch_esf *esf)
{
	char h[9];
	const uint32_t cfsr = *(volatile uint32_t *)0xE000ED28u;
	const uint32_t hfsr = *(volatile uint32_t *)0xE000ED2Cu;
	const uint32_t bfar = *(volatile uint32_t *)0xE000ED38u;

	tx("\nFAULT reason=");
	hex8(h, reason); tx(h);
	if (esf != NULL) {
		tx(" pc="); hex8(h, esf->basic.pc); tx(h);
		tx(" lr="); hex8(h, esf->basic.lr); tx(h);
	}
	tx(" cfsr="); hex8(h, cfsr); tx(h);
	tx(" hfsr="); hex8(h, hfsr); tx(h);
	tx(" bfar="); hex8(h, bfar); tx(h);
	tx("\n");
	k_msleep(50);
	sys_reboot(SYS_REBOOT_COLD);
	for (;;) {
	}
}

int main(void)
{
	if (!device_is_ready(uart)) {
		return 0;
	}

	model_crc = crc32_ieee((const uint8_t *)MODEL.model_const_ptr, MODEL.model_const_size);
	model_bytes = (uint32_t)MODEL.model_const_size +
		      (uint32_t)MODEL.cmd_buffer_len * (uint32_t)sizeof(NRF_AXON_PLATFORM_BITWIDTH_UNSIGNED_TYPE);
	setup_model();
	tx("READY\n");

	for (;;) {
		uint8_t b;

		if (!rx_byte(&b, -1) || b != SYNC0) {
			continue;
		}
		if (!rx_byte(&b, 1000) || b != SYNC1) {
			continue;
		}
		if (!rx_byte(&b, 1000)) {
			continue;
		}
		if (b == 'I') {
			send_info();
		} else if (b == 'W') {
			handle_window();
		}
	}
	return 0;
}
