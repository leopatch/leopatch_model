/*
 * AD8232 breakout test on the nRF54LM20 DK. Press Button 0 to record 5 s at 500 Hz; LED 0 is on
 * while recording. Each sample is printed as "raw_mv,filtered_mv,lead_off" on the debugger's
 * serial port, ready for tools/plot_ecg.py. filtered_mv has mains hum (60 Hz and its 120/180 Hz
 * harmonics) removed by notch filters. lead_off is 0 (both on), 1 (LO+ off), 2 (LO- off) or
 * 3 (both off). Lines starting with '#' are status messages.
 */
#include <math.h>

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

#define SAMPLE_RATE_HZ 500
#define RECORD_SECONDS 5

/* Mains hum in the US: 60 Hz plus harmonics below the 250 Hz Nyquist limit. */
#define MAINS_HZ   60
#define N_NOTCHES  3
/* Notch sharpness: bandwidth = frequency / Q, so 2 Hz wide at 60 Hz. */
#define NOTCH_Q    30.0f
/* Filter warm-up before the recording starts. */
#define SETTLE_SAMPLES (SAMPLE_RATE_HZ / 2)

/* One second-order notch filter (RBJ audio EQ cookbook), direct form I. */
struct notch {
	float b0, b1, b2, a1, a2;
	float x1, x2, y1, y2;
};

static void notch_init(struct notch *n, float f0, float start)
{
	float w0 = 2.0f * 3.14159265f * f0 / SAMPLE_RATE_HZ;
	float alpha = sinf(w0) / (2.0f * NOTCH_Q);
	float a0 = 1.0f + alpha;

	n->b0 = 1.0f / a0;
	n->b1 = -2.0f * cosf(w0) / a0;
	n->b2 = 1.0f / a0;
	n->a1 = n->b1;
	n->a2 = (1.0f - alpha) / a0;
	/* Start settled at the first sample (the notch passes DC unchanged), so there's no jump. */
	n->x1 = n->x2 = n->y1 = n->y2 = start;
}

static float notch_step(struct notch *n, float x)
{
	float y = n->b0 * x + n->b1 * n->x1 + n->b2 * n->x2 - n->a1 * n->y1 - n->a2 * n->y2;

	n->x2 = n->x1;
	n->x1 = x;
	n->y2 = n->y1;
	n->y1 = y;
	return y;
}

static const struct adc_dt_spec ecg = ADC_DT_SPEC_GET_BY_IDX(DT_PATH(zephyr_user), 0);
static const struct gpio_dt_spec lo_plus = GPIO_DT_SPEC_GET(DT_PATH(zephyr_user), lo_plus_gpios);
static const struct gpio_dt_spec lo_minus = GPIO_DT_SPEC_GET(DT_PATH(zephyr_user), lo_minus_gpios);
/* Active low: "active" means shut down. */
static const struct gpio_dt_spec sdn = GPIO_DT_SPEC_GET(DT_PATH(zephyr_user), sdn_gpios);
static const struct gpio_dt_spec button = GPIO_DT_SPEC_GET(DT_ALIAS(sw0), gpios);
static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);

static K_SEM_DEFINE(start, 0, 1);
static struct gpio_callback button_cb;

static void button_pressed(const struct device *dev, struct gpio_callback *cb, uint32_t pins)
{
	k_sem_give(&start);
}

static int setup(void)
{
	int err = adc_channel_setup_dt(&ecg);

	err = err ?: gpio_pin_configure_dt(&lo_plus, GPIO_INPUT);
	err = err ?: gpio_pin_configure_dt(&lo_minus, GPIO_INPUT);
	err = err ?: gpio_pin_configure_dt(&sdn, GPIO_OUTPUT_INACTIVE);
	err = err ?: gpio_pin_configure_dt(&led, GPIO_OUTPUT_INACTIVE);
	err = err ?: gpio_pin_configure_dt(&button, GPIO_INPUT);
	err = err ?: gpio_pin_interrupt_configure_dt(&button, GPIO_INT_EDGE_TO_ACTIVE);
	if (err) {
		return err;
	}
	gpio_init_callback(&button_cb, button_pressed, BIT(button.pin));
	return gpio_add_callback_dt(&button, &button_cb);
}

static void record(void)
{
	int16_t raw;
	struct adc_sequence seq = {.buffer = &raw, .buffer_size = sizeof(raw)};
	struct k_timer tick;
	int clipped = 0, off_plus = 0, off_minus = 0;
	struct notch notches[N_NOTCHES];

	adc_sequence_init_dt(&ecg, &seq);
	gpio_pin_set_dt(&led, 1);
	printk("# start\n");

	k_timer_init(&tick, NULL, NULL);
	k_timer_start(&tick, K_USEC(1000000 / SAMPLE_RATE_HZ), K_USEC(1000000 / SAMPLE_RATE_HZ));
	/* Negative i: the filters settle on the first 0.5 s, which isn't sent. */
	for (int i = -SETTLE_SAMPLES; i < SAMPLE_RATE_HZ * RECORD_SECONDS; i++) {
		k_timer_status_sync(&tick);
		if (adc_read_dt(&ecg, &seq)) {
			printk("# adc error\n");
			break;
		}
		int32_t mv = raw;
		int plus = gpio_pin_get_dt(&lo_plus);
		int minus = gpio_pin_get_dt(&lo_minus);

		adc_raw_to_millivolts_dt(&ecg, &mv);
		if (i == -SETTLE_SAMPLES) {
			for (int k = 0; k < N_NOTCHES; k++) {
				notch_init(&notches[k], MAINS_HZ * (k + 1), (float)mv);
			}
		}
		float filtered = (float)mv;

		for (int k = 0; k < N_NOTCHES; k++) {
			filtered = notch_step(&notches[k], filtered);
		}
		if (i < 0) {
			continue;
		}
		clipped += mv < 150 || mv > 3150;
		off_plus += plus;
		off_minus += minus;
		printk("%d,%d,%d\n", mv, (int)lroundf(filtered), plus | (minus << 1));
	}
	k_timer_stop(&tick);

	gpio_pin_set_dt(&led, 0);
	printk("# done: %d samples near the rails (clipping), LO+ off %d, LO- off %d (of %d)\n",
	       clipped, off_plus, off_minus, SAMPLE_RATE_HZ * RECORD_SECONDS);
}

int main(void)
{
	if (setup()) {
		printk("# setup failed: check the overlay and wiring\n");
		return 0;
	}
	/* Keep the AD8232 running between recordings so its pins can be checked with a multimeter. */
	gpio_pin_set_dt(&sdn, 0);
	printk("# ready: press Button 0 to record %d s\n", RECORD_SECONDS);
	while (true) {
		k_sem_take(&start, K_FOREVER);
		record();
		k_sem_reset(&start); /* ignore presses during the recording */
		printk("# ready\n");
	}
}
