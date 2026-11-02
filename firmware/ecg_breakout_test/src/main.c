/*
 * AD8232 breakout test on the nRF54LM20 DK. Press Button 0 to record 5 s at 500 Hz; LED 0 is on
 * while recording. Each sample is printed as "mv,lead_off" on the debugger's serial port, ready
 * for tools/plot_ecg.py. Lines starting with '#' are status messages.
 */
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>

#define SAMPLE_RATE_HZ 500
#define RECORD_SECONDS 5

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
	int clipped = 0, off = 0;

	adc_sequence_init_dt(&ecg, &seq);
	gpio_pin_set_dt(&led, 1);
	printk("# start\n");

	k_timer_init(&tick, NULL, NULL);
	k_timer_start(&tick, K_USEC(1000000 / SAMPLE_RATE_HZ), K_USEC(1000000 / SAMPLE_RATE_HZ));
	for (int i = 0; i < SAMPLE_RATE_HZ * RECORD_SECONDS; i++) {
		k_timer_status_sync(&tick);
		if (adc_read_dt(&ecg, &seq)) {
			printk("# adc error\n");
			break;
		}
		int32_t mv = raw;
		int lead_off = gpio_pin_get_dt(&lo_plus) || gpio_pin_get_dt(&lo_minus);

		adc_raw_to_millivolts_dt(&ecg, &mv);
		clipped += mv < 150 || mv > 3150;
		off += lead_off;
		printk("%d,%d\n", mv, lead_off);
	}
	k_timer_stop(&tick);

	gpio_pin_set_dt(&led, 0);
	printk("# done: %d samples near the rails (clipping), %d with a lead off\n", clipped, off);
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
