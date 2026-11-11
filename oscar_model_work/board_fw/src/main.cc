/*
 * LEO PATCH -- 1-lead ECG sex model on the nRF54LM20 DK, running on the Cortex-M33 CPU with
 * TensorFlow Lite Micro (NOT the Axon NPU).
 *
 * The host (board_runner.py) streams one int8 ECG window at a time over the console UART
 * (the DK's USB virtual COM port); this firmware runs the model and answers with the int8 logit
 * and how long inference took.
 *
 * Protocol (host -> board, binary)            Board -> host (ASCII lines, plus the single byte 'K')
 *   A5 5A 'I'                                  INFO model_bytes=.. model_crc32=.. arena_size=.. arena_used=..
 *                                                   in_bytes=.. in_zp=.. out_zp=.. status=..
 *   A5 5A 'W' len_lo len_hi                    (then after every 250 payload bytes: 'K')
 *   <len payload bytes, int8>
 *   crc16_lo crc16_hi   (CRC-16/CCITT-FALSE    RES q=<int8 logit> ms=<inference ms>   or   ERR <reason>
 *                        of the payload)
 *
 * Written against the Zephyr tflite-micro sample; not yet compiled on hardware -- see README.md.
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

#include <tensorflow/lite/micro/micro_interpreter.h>
#include <tensorflow/lite/micro/micro_mutable_op_resolver.h>
#include <tensorflow/lite/schema/schema_generated.h>

#include "model_config.h"

namespace {

constexpr uint8_t kSync0 = 0xA5;
constexpr uint8_t kSync1 = 0x5A;
constexpr size_t kChunk = 250;

/* The UART that is the DK's first virtual COM port (devicetree "zephyr,console"). */
const struct device *const uart = DEVICE_DT_GET(DT_CHOSEN(zephyr_console));

alignas(16) uint8_t tensor_arena[MODEL_ARENA_BYTES];
tflite::MicroInterpreter *interp = nullptr;
TfLiteTensor *input = nullptr;
TfLiteTensor *output = nullptr;
const char *model_status = "init";
uint32_t model_crc = 0;

uint16_t crc16_ccitt_false(const uint8_t *d, size_t n)
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

uint32_t crc32_ieee(const uint8_t *d, size_t n)
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
bool rx_byte(uint8_t *b, int32_t timeout_ms)
{
	const int64_t deadline = (timeout_ms < 0) ? INT64_MAX : k_uptime_get() + timeout_ms;

	while (uart_poll_in(uart, b) != 0) {
		if (k_uptime_get() > deadline) {
			return false;
		}
	}
	return true;
}

void tx(const char *s)
{
	for (; *s; ++s) {
		uart_poll_out(uart, (unsigned char)*s);
	}
}

bool setup_model()
{
	const tflite::Model *model = tflite::GetModel(g_model_data);

	if (model->version() != TFLITE_SCHEMA_VERSION) {
		model_status = "schema_version";
		return false;
	}

	static tflite::MicroMutableOpResolver<7> resolver;

	if (resolver.AddPad() != kTfLiteOk || resolver.AddConv2D() != kTfLiteOk ||
	    resolver.AddMaxPool2D() != kTfLiteOk || resolver.AddAdd() != kTfLiteOk ||
	    resolver.AddMean() != kTfLiteOk || resolver.AddFullyConnected() != kTfLiteOk ||
	    resolver.AddReshape() != kTfLiteOk) {
		model_status = "op_resolver";
		return false;
	}

	static tflite::MicroInterpreter static_interp(model, resolver, tensor_arena,
						      MODEL_ARENA_BYTES);

	interp = &static_interp;
	if (interp->AllocateTensors() != kTfLiteOk) {
		model_status = "alloc_fail_raise_arena";
		return false;
	}
	input = interp->input(0);
	output = interp->output(0);
	if (input->type != kTfLiteInt8 || input->bytes != MODEL_INPUT_BYTES) {
		model_status = "bad_input_tensor";
		return false;
	}
	model_status = "ok";
	return true;
}

void send_info()
{
	char buf[200];

	snprintf(buf, sizeof(buf),
		 "INFO model_bytes=%u model_crc32=%08x arena_size=%u arena_used=%u in_bytes=%u "
		 "in_zp=%d out_zp=%d status=%s\n",
		 (unsigned)g_model_len, (unsigned)model_crc, (unsigned)MODEL_ARENA_BYTES,
		 (unsigned)(interp ? interp->arena_used_bytes() : 0u),
		 (unsigned)(input ? input->bytes : 0u), input ? (int)input->params.zero_point : 0,
		 output ? (int)output->params.zero_point : 0, model_status);
	tx(buf);
}

void handle_window()
{
	uint8_t lb[2];

	if (!rx_byte(&lb[0], 1000) || !rx_byte(&lb[1], 1000)) {
		tx("ERR timeout\n");
		return;
	}
	if (input == nullptr) {
		tx("ERR model\n");
		return;
	}
	const size_t len = (size_t)lb[0] | ((size_t)lb[1] << 8);

	if (len != input->bytes) {
		tx("ERR len\n");
		return;
	}

	uint8_t *dst = reinterpret_cast<uint8_t *>(input->data.int8);

	for (size_t off = 0; off < len; off += kChunk) {
		const size_t n = (len - off < kChunk) ? (len - off) : kChunk;

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

	const int64_t t0 = k_uptime_get();
	const TfLiteStatus st = interp->Invoke();
	const int64_t ms = k_uptime_get() - t0;

	if (st != kTfLiteOk) {
		tx("ERR invoke\n");
		return;
	}

	char buf[48];

	snprintf(buf, sizeof(buf), "RES q=%d ms=%u\n", (int)output->data.int8[0], (unsigned)ms);
	tx(buf);
}

} /* namespace */

/* On a CPU fault, say why over the same UART, then reboot (the host prints this line).
 * Hand-rolled hex so nothing heavy runs on the small exception stack. */
static void hex8(char *o, uint32_t v)
{
	for (int i = 7; i >= 0; i--, v >>= 4) {
		o[i] = "0123456789abcdef"[v & 15];
	}
	o[8] = 0;
}

extern "C" void k_sys_fatal_error_handler(unsigned int reason, const struct arch_esf *esf)
{
	char h[9];
	const uint32_t cfsr = *(volatile uint32_t *)0xE000ED28u;
	const uint32_t hfsr = *(volatile uint32_t *)0xE000ED2Cu;
	const uint32_t mmfar = *(volatile uint32_t *)0xE000ED34u;
	const uint32_t bfar = *(volatile uint32_t *)0xE000ED38u;

	tx("\nFAULT reason=");
	hex8(h, reason); tx(h);
	if (esf != nullptr) {
		tx(" pc="); hex8(h, esf->basic.pc); tx(h);
		tx(" lr="); hex8(h, esf->basic.lr); tx(h);
	}
	tx(" cfsr="); hex8(h, cfsr); tx(h);
	tx(" hfsr="); hex8(h, hfsr); tx(h);
	tx(" mmfar="); hex8(h, mmfar); tx(h);
	tx(" bfar="); hex8(h, bfar); tx(h);
	/* poor man's backtrace: odd (Thumb) code addresses found on the thread stack (PSP) at the time of the abort */
	uint32_t psp;

	__asm volatile("mrs %0, psp" : "=r"(psp));
	tx(" esf="); hex8(h, (uint32_t)(uintptr_t)esf); tx(h);
	tx(" psp="); hex8(h, psp); tx(h);
	if (psp >= 0x20000000u && psp < 0x20100000u) {
		const uint32_t *sp = (const uint32_t *)psp;
		int found = 0;

		tx(" bt=");
		for (int i = 0; i < 400 && found < 16; i++) {
			const uint32_t v = sp[i];

			if ((v & 1u) && v > 0x100u && v < 0x1A0000u) {
				hex8(h, v); tx(h); tx(",");
				found++;
			}
		}
	}
	tx("\n");
	k_msleep(50);
	sys_reboot(SYS_REBOOT_COLD);
	for (;;) {
	}
}

/* Linked with -Wl,--wrap=abort: every abort() in the firmware (TFLM's internal checks, asserts) lands here, so the
 * board can say WHO called it. Look the printed address up with arm-zephyr-eabi-addr2line. */
extern "C" __attribute__((noreturn)) void __wrap_abort(void)
{
	char h[9];

	hex8(h, (uint32_t)__builtin_return_address(0));
	tx("\nABORT caller=");
	tx(h);
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

	model_crc = crc32_ieee(g_model_data, g_model_len);
	setup_model();
	tx("READY\n");

	for (;;) {
		uint8_t b;

		if (!rx_byte(&b, -1) || b != kSync0) {
			continue;
		}
		if (!rx_byte(&b, 1000) || b != kSync1) {
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
