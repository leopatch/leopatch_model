/*
 * LeoPatch on-chip test: AD8232 breakout -> nRF54LM20B -> median-beat model on the Axon NPU.
 *
 * The model is chosen at build time (MODEL_DIR in CMakeLists.txt, or the dashboard in
 * dashboard/), so any median-beat model exported for the Axon NPU can be flashed.
 *
 * Press Button 0 (or send 'r' on the serial port) to record RECORD_SECONDS at 500 Hz. The chip
 * removes mains hum and finds the heartbeats. With RUN_MODEL set it also builds the 800-sample
 * median beat, runs the stem on the CPU and the rest of the model on the NPU, and shows the answer
 * on the LEDs:
 *   LED0 = MODEL_POS_LABEL, LED1 = MODEL_NEG_LABEL, LED2 = running (recording or thinking),
 *   LED3 = error
 * With RUN_MODEL off, the recording is only sent (Button 1) and the model runs on the laptop
 * (tools/ble_receive.py); all LEDs are off when the recording is done.
 * Errors: an electrode off, fewer than 2 full heartbeats, ADC or NPU failure. At start-up the
 * NPU is checked against the Python reference on 4 built-in median beats; a mismatch is an error.
 *
 * Press Button 1 (or send 'u') to send the last result and recording over Bluetooth (see
 * upload.h); LED2 blinks while the board waits for a receiver and sends. The radio is off at all
 * other times, so it never runs during an inference.
 *
 * Serial commands (one character, no Enter needed): r = record, u = Bluetooth upload,
 * t = rerun the NPU self-test, i = print the model info line.
 *
 * Serial output (debugger's second port) is compatible with
 * firmware/ecg_breakout_test/tools/plot_ecg.py: one "raw_mv,filtered_mv,lead_off" line per
 * sample, status lines start with '#'.
 */
#include <assert.h> /* static_assert, used by the generated model header */
#include <math.h>

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/sys/printk.h>

#include <axon/nrf_axon_platform.h>
#include <drivers/axon/nrf_axon_driver.h>
#include <drivers/axon/nrf_axon_nn_infer.h>

#include "beats.h"
#include "frontend.h"
#include "notch.h"
#include "recording.h"
#include "upload.h"
#include MODEL_HEADER  /* nrf_axon_model_<name>_.h from MODEL_DIR */
#include "test_beats.h" /* from MODEL_DIR */

/* MODEL, MODEL_NAME_STR, MODEL_OUTPUT_SIZE, MODEL_POS_LABEL, MODEL_NEG_LABEL and RUN_MODEL
 * come from CMakeLists.txt.
 * RUN_MODEL 0: record and send only; the lead I model runs on the laptop.
 * RUN_MODEL 1: run the model on the chip (2-5 s recordings are enough, see RECORD_SECONDS). */

/* Mains hum in the US: 60 Hz plus harmonics below the 250 Hz Nyquist limit. */
#define MAINS_HZ       60
#define N_NOTCHES      3
#define NOTCH_Q        30.0f
#define SETTLE_SAMPLES (SAMPLE_RATE_HZ / 2) /* filter warm-up, not recorded */

/* A recording is rejected if an electrode is off in more than this share of samples. */
#define MAX_LEAD_OFF_PERCENT 5

/* Allowed logit difference to the Python int8 reference (front end float rounding). */
#define LOGIT_TOLERANCE 0.25f

/* How long Button 1 advertises for a phone or laptop before giving up. */
#define UPLOAD_WAIT K_SECONDS(60)

enum event { EVENT_MEASURE, EVENT_UPLOAD, EVENT_SELF_TEST, EVENT_INFO };

static const struct adc_dt_spec ecg = ADC_DT_SPEC_GET_BY_IDX(DT_PATH(zephyr_user), 0);
static const struct gpio_dt_spec lo_plus = GPIO_DT_SPEC_GET(DT_PATH(zephyr_user), lo_plus_gpios);
static const struct gpio_dt_spec lo_minus = GPIO_DT_SPEC_GET(DT_PATH(zephyr_user), lo_minus_gpios);
/* Active low: "active" means shut down. */
static const struct gpio_dt_spec sdn = GPIO_DT_SPEC_GET(DT_PATH(zephyr_user), sdn_gpios);
static const struct gpio_dt_spec button = GPIO_DT_SPEC_GET(DT_ALIAS(sw0), gpios);
static const struct gpio_dt_spec button_upload = GPIO_DT_SPEC_GET(DT_ALIAS(sw1), gpios);
static const struct gpio_dt_spec led_pos = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
static const struct gpio_dt_spec led_neg = GPIO_DT_SPEC_GET(DT_ALIAS(led1), gpios);
static const struct gpio_dt_spec led_running = GPIO_DT_SPEC_GET(DT_ALIAS(led2), gpios);
static const struct gpio_dt_spec led_error = GPIO_DT_SPEC_GET(DT_ALIAS(led3), gpios);
static const struct device *const console = DEVICE_DT_GET(DT_CHOSEN(zephyr_console));

K_MSGQ_DEFINE(events, sizeof(enum event), 1, 4);
static struct gpio_callback button_cb;
static struct gpio_callback button_upload_cb;

/* Last successful result, sent by Button 1 together with recording[]. */
static char last_result[128];
static bool have_result;

static float recording[RECORDING_LEN];
static float beat[BEAT_LEN];
static int8_t npu_input[FRONTEND_OUT_CH * FRONTEND_OUT_LEN];
static int8_t npu_output[MODEL_OUTPUT_SIZE] __aligned(4);

static void button_pressed(const struct device *dev, struct gpio_callback *cb, uint32_t pins)
{
	enum event e = cb == &button_upload_cb ? EVENT_UPLOAD : EVENT_MEASURE;

	k_msgq_put(&events, &e, K_NO_WAIT); /* dropped if a job is already waiting */
}

/* Serial commands from the dashboard: same events as the buttons, plus self-test and info. */
static void serial_commands(void *a, void *b, void *c)
{
	while (true) {
		unsigned char ch;
		enum event e;

		if (uart_poll_in(console, &ch) != 0) {
			k_msleep(20);
			continue;
		}
		switch (ch) {
		case 'r':
			e = EVENT_MEASURE;
			break;
		case 'u':
			e = EVENT_UPLOAD;
			break;
		case 't':
			e = EVENT_SELF_TEST;
			break;
		case 'i':
			e = EVENT_INFO;
			break;
		default:
			continue;
		}
		if (k_msgq_put(&events, &e, K_NO_WAIT)) {
			printk("# busy: command '%c' ignored\n", ch);
		}
	}
}

K_THREAD_DEFINE(serial_cmd_tid, 1024, serial_commands, NULL, NULL, NULL, 7, 0, 0);

static void blink(struct k_timer *t)
{
	gpio_pin_toggle_dt(&led_running);
}

static K_TIMER_DEFINE(blinker, blink, NULL);

static void show(const struct gpio_dt_spec *on)
{
	const struct gpio_dt_spec *leds[] = {&led_pos, &led_neg, &led_running, &led_error};

	for (int i = 0; i < ARRAY_SIZE(leds); i++) {
		gpio_pin_set_dt(leds[i], leds[i] == on);
	}
}

/* One machine-readable line describing the firmware; the dashboard reads it. */
static void print_info(void)
{
	printk("# model: name=%s,pos=%s,neg=%s,threshold=%.3f,stem_channels=%d,run_model=%d,"
	       "record_s=%d,fs=%d\n",
	       MODEL_NAME_STR, MODEL_POS_LABEL, MODEL_NEG_LABEL, (double)MODEL_THRESHOLD,
	       FRONTEND_OUT_CH, RUN_MODEL, RECORD_SECONDS, SAMPLE_RATE_HZ);
}

static float dequantize(int8_t q, const nrf_axon_compiled_model_output_s *out)
{
	return (float)(q - out->dequant_zp) * ldexpf((float)out->dequant_mult, -out->dequant_round);
}

/* Median beat -> logit: stem on the CPU, the rest on the NPU. Returns false on an NPU error. */
static bool run_model(const float *median_beat, float *logit)
{
	const nrf_axon_nn_compiled_model_input_s *in = &MODEL.inputs[0];

	frontend_run(median_beat, npu_input, ldexpf((float)in->quant_mult, -in->quant_round),
		     in->quant_zp);
	if (nrf_axon_nn_model_infer_sync(&MODEL, npu_input, npu_output) != NRF_AXON_RESULT_SUCCESS) {
		return false;
	}
	*logit = dequantize(npu_output[0], &MODEL.outputs[0]);
	return true;
}

static int setup(void)
{
	const nrf_axon_nn_model_layer_dimensions_s *dims = &MODEL.inputs[0].dimensions;
	const struct gpio_dt_spec *leds[] = {&led_pos, &led_neg, &led_running, &led_error};
	int err = adc_channel_setup_dt(&ecg);

	err = err ?: gpio_pin_configure_dt(&lo_plus, GPIO_INPUT);
	err = err ?: gpio_pin_configure_dt(&lo_minus, GPIO_INPUT);
	err = err ?: gpio_pin_configure_dt(&sdn, GPIO_OUTPUT_INACTIVE);
	for (int i = 0; i < ARRAY_SIZE(leds); i++) {
		err = err ?: gpio_pin_configure_dt(leds[i], GPIO_OUTPUT_INACTIVE);
	}
	err = err ?: gpio_pin_configure_dt(&button, GPIO_INPUT);
	err = err ?: gpio_pin_interrupt_configure_dt(&button, GPIO_INT_EDGE_TO_ACTIVE);
	err = err ?: gpio_pin_configure_dt(&button_upload, GPIO_INPUT);
	err = err ?: gpio_pin_interrupt_configure_dt(&button_upload, GPIO_INT_EDGE_TO_ACTIVE);
	if (err) {
		printk("# error: GPIO/ADC setup failed (%d)\n", err);
		return err;
	}
	gpio_init_callback(&button_cb, button_pressed, BIT(button.pin));
	gpio_init_callback(&button_upload_cb, button_pressed, BIT(button_upload.pin));
	err = gpio_add_callback_dt(&button, &button_cb);
	err = err ?: gpio_add_callback_dt(&button_upload, &button_upload_cb);
	if (err || upload_init()) {
		printk("# error: button or Bluetooth setup failed\n");
		return err ?: -EIO;
	}

	if (dims->height * dims->width * dims->channel_cnt != sizeof(npu_input) ||
	    dims->byte_width != 1 || MODEL.outputs[0].dimensions.byte_width != 1) {
		printk("# error: model input/output does not match the front end\n");
		return -EINVAL;
	}
	if (nrf_axon_platform_init() != NRF_AXON_RESULT_SUCCESS || nrf_axon_nn_model_init_vars(&MODEL) ||
	    nrf_axon_nn_model_validate(&MODEL) != NRF_AXON_RESULT_SUCCESS) {
		printk("# error: NPU initialization failed\n");
		return -EIO;
	}
	return err;
}

/* Run the built-in median beats and compare with the Python int8 reference. */
static bool self_test(void)
{
	int passed = 0;

	for (int i = 0; i < TEST_BEAT_COUNT; i++) {
		float logit;
		const uint32_t t0 = k_cycle_get_32();

		if (!run_model(test_beat[i], &logit)) {
			printk("# self-test beat %d: NPU error\n", i);
			continue;
		}
		const uint32_t ms = k_cyc_to_ms_near32(k_cycle_get_32() - t0);
		const bool ok = fabsf(logit - test_beat_logit_int8[i]) <= LOGIT_TOLERANCE;

		passed += ok;
		printk("# self-test beat %d: logit %.3f, Python int8 %.3f, float %.3f, %u ms %s\n", i,
		       (double)logit, (double)test_beat_logit_int8[i], (double)test_beat_logit_float[i],
		       ms, ok ? "OK" : "MISMATCH");
	}
	printk("# self-test: %d/%d beats match the Python reference\n", passed, TEST_BEAT_COUNT);
	return passed == TEST_BEAT_COUNT;
}

/* Record RECORDING_LEN hum-filtered samples. Returns the number of lead-off samples, or -1. */
static int record(int *clipped)
{
	int16_t raw;
	struct adc_sequence seq = {.buffer = &raw, .buffer_size = sizeof(raw)};
	struct notch notches[N_NOTCHES];
	struct k_timer tick;
	int off = 0;

	*clipped = 0;
	adc_sequence_init_dt(&ecg, &seq);
	printk("# start\n");

	k_timer_init(&tick, NULL, NULL);
	k_timer_start(&tick, K_USEC(1000000 / SAMPLE_RATE_HZ), K_USEC(1000000 / SAMPLE_RATE_HZ));
	/* Negative i: the filters settle on the first 0.5 s, which isn't recorded. */
	for (int i = -SETTLE_SAMPLES; i < RECORDING_LEN; i++) {
		k_timer_status_sync(&tick);
		if (adc_read_dt(&ecg, &seq)) {
			k_timer_stop(&tick);
			return -1;
		}
		int32_t mv = raw;
		int plus = gpio_pin_get_dt(&lo_plus);
		int minus = gpio_pin_get_dt(&lo_minus);

		adc_raw_to_millivolts_dt(&ecg, &mv);
		if (i == -SETTLE_SAMPLES) {
			for (int k = 0; k < N_NOTCHES; k++) {
				notch_init(&notches[k], MAINS_HZ * (k + 1), SAMPLE_RATE_HZ, NOTCH_Q, (float)mv);
			}
		}
		float filtered = (float)mv;

		for (int k = 0; k < N_NOTCHES; k++) {
			filtered = notch_step(&notches[k], filtered);
		}
		if (i < 0) {
			continue;
		}
		recording[i] = filtered;
		*clipped += mv < 150 || mv > 3150;
		off += plus || minus;
		printk("%d,%d,%d\n", mv, (int)lroundf(filtered), plus | (minus << 1));
	}
	k_timer_stop(&tick);
	return off;
}

static int beats_per_minute(const int *peaks, int n_peaks)
{
	return n_peaks > 1 ? 60 * SAMPLE_RATE_HZ * (n_peaks - 1) / (peaks[n_peaks - 1] - peaks[0]) : 0;
}

static void measure(void)
{
	int peaks[PEAKS_MAX];
	int clipped;
	float logit;

	show(&led_running);
	have_result = false; /* recording[] is about to be overwritten */
	const int off = record(&clipped);

	if (off < 0) {
		printk("# result: error, ADC read failed\n# done\n");
		show(&led_error);
		return;
	}
	if (off * 100 > RECORDING_LEN * MAX_LEAD_OFF_PERCENT) {
		printk("# result: error, an electrode was off in %d%% of samples\n# done\n",
		       off * 100 / RECORDING_LEN);
		show(&led_error);
		return;
	}

	const uint32_t t0 = k_cycle_get_32();
	const int n_peaks = beats_find_r_peaks(recording, RECORDING_LEN, peaks, PEAKS_MAX);
	const int bpm = beats_per_minute(peaks, n_peaks);

	if (!RUN_MODEL) {
		printk("# result: recorded %d s, %d beats, %d bpm, %d clipped samples\n",
		       RECORD_SECONDS, n_peaks, bpm, clipped);
		show(NULL);
		snprintk(last_result, sizeof(last_result), "RECORDED,seconds=%d,beats=%d,bpm=%d,clipped=%d",
			 RECORD_SECONDS, n_peaks, bpm, clipped);
		printk("# result-data: %s\n# done\n", last_result);
		have_result = true;
		return;
	}
	const int n_beats = beats_median(recording, RECORDING_LEN, peaks, n_peaks, beat);

	if (n_beats < 2) {
		printk("# result: error, only %d full heartbeats (found %d peaks)\n# done\n", n_beats,
		       n_peaks);
		show(&led_error);
		return;
	}
	if (!run_model(beat, &logit)) {
		printk("# result: error, NPU inference failed\n# done\n");
		show(&led_error);
		return;
	}
	const uint32_t ms = k_cyc_to_ms_near32(k_cycle_get_32() - t0);
	const float p = 1.0f / (1.0f + expf(-logit));
	const bool positive = p >= MODEL_THRESHOLD;
	const char *label = positive ? MODEL_POS_LABEL : MODEL_NEG_LABEL;

	printk("# result: %s (P(%s) %.2f, threshold %.2f) from %d beats, %d bpm, %d clipped samples,"
	       " %u ms on chip\n",
	       label, MODEL_POS_LABEL, (double)p, (double)MODEL_THRESHOLD, n_beats, bpm, clipped, ms);
	show(positive ? &led_pos : &led_neg);
	snprintk(last_result, sizeof(last_result),
		 "%s,p=%.3f,logit=%.3f,threshold=%.3f,beats=%d,bpm=%d,clipped=%d,ms=%u", label,
		 (double)p, (double)logit, (double)MODEL_THRESHOLD, n_beats, bpm, clipped, ms);
	printk("# result-data: %s\n# done\n", last_result);
	have_result = true;
}

static void upload(void)
{
	if (!have_result) {
		printk("# bluetooth: nothing to send yet, press Button 0 to record first\n");
		return;
	}
	k_timer_start(&blinker, K_MSEC(250), K_MSEC(250));
	const int err = upload_send(last_result, recording, RECORDING_LEN, UPLOAD_WAIT);

	k_timer_stop(&blinker);
	gpio_pin_set_dt(&led_running, 0);
	if (err == -ETIMEDOUT) {
		printk("# bluetooth: no receiver connected within 60 s, stopped\n");
	} else if (err) {
		printk("# bluetooth: upload failed (%d)\n", err);
	} else {
		printk("# bluetooth: sent result and %d samples\n", RECORDING_LEN);
	}
}

int main(void)
{
	print_info();
	if (setup()) {
		show(&led_error);
		return 0;
	}
	/* Keep the AD8232 running so its output is settled when a recording starts. */
	gpio_pin_set_dt(&sdn, 0);
	if (!self_test()) {
		show(&led_error);
		printk("# error: NPU self-test failed\n");
		return 0;
	}
	printk("# ready: press Button 0 to record %d s, Button 1 to send it over Bluetooth\n",
	       RECORD_SECONDS);
	while (true) {
		enum event e;

		k_msgq_get(&events, &e, K_FOREVER);
		switch (e) {
		case EVENT_MEASURE:
			measure();
			break;
		case EVENT_UPLOAD:
			upload();
			break;
		case EVENT_SELF_TEST:
			show(self_test() ? NULL : &led_error);
			break;
		case EVENT_INFO:
			print_info();
			break;
		}
		k_msgq_purge(&events); /* ignore presses during the job */
		printk("# ready\n");
	}
}
