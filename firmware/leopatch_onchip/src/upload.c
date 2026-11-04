#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/sys/printk.h>
#include <zephyr/sys/util.h>
#include <bluetooth/services/nus.h>

#include "upload.h"

#define SENT_TIMEOUT K_SECONDS(2)

static struct bt_conn *current;
static K_SEM_DEFINE(subscribed, 0, 1);
static K_SEM_DEFINE(sent, 0, 1);
static K_SEM_DEFINE(gone, 0, 1);

static const struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME, sizeof(CONFIG_BT_DEVICE_NAME) - 1),
};
static const struct bt_data sd[] = {
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, BT_UUID_NUS_VAL),
};

static void connected(struct bt_conn *conn, uint8_t err)
{
	if (err) {
		return;
	}
	current = bt_conn_ref(conn);
	printk("# bluetooth: connected\n");
}

static void disconnected(struct bt_conn *conn, uint8_t reason)
{
	if (current == conn) {
		bt_conn_unref(current);
		current = NULL;
	}
	printk("# bluetooth: disconnected (reason %u)\n", reason);
	k_sem_give(&gone);
}

BT_CONN_CB_DEFINE(conn_callbacks) = {
	.connected = connected,
	.disconnected = disconnected,
};

static void send_enabled(enum bt_nus_send_status status)
{
	if (status == BT_NUS_SEND_STATUS_ENABLED) {
		k_sem_give(&subscribed);
	}
}

static void on_sent(struct bt_conn *conn)
{
	k_sem_give(&sent);
}

static struct bt_nus_cb nus_cb = {
	.send_enabled = send_enabled,
	.sent = on_sent,
};

int upload_init(void)
{
	int err = bt_enable(NULL);

	return err ?: bt_nus_init(&nus_cb);
}

/* Send one notification and wait until the stack has sent it. */
static int send_chunk(const char *buf, int len)
{
	k_sem_reset(&sent);
	int err = bt_nus_send(current, buf, len);

	if (err) {
		return err;
	}
	return k_sem_take(&sent, SENT_TIMEOUT) ? -EIO : 0;
}

int upload_send(const char *result, const float *samples, int n, k_timeout_t wait)
{
	char chunk[244]; /* fits the largest NUS payload with a 247-byte MTU */
	int err;

	k_sem_reset(&subscribed);
	k_sem_reset(&gone);
	err = bt_le_adv_start(BT_LE_ADV_CONN_FAST_1, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
	if (err) {
		return err;
	}
	printk("# bluetooth: advertising as \"%s\"\n", CONFIG_BT_DEVICE_NAME);
	if (k_sem_take(&subscribed, wait)) {
		bt_le_adv_stop();
		if (current) {
			bt_conn_disconnect(current, BT_HCI_ERR_REMOTE_USER_TERM_CONN);
		}
		return -ETIMEDOUT;
	}
	bt_le_adv_stop();

	/* The receiver negotiates the packet size (phones and macOS ask for a large one). */
	const int max = MIN((int)bt_nus_get_mtu(current), (int)sizeof(chunk));

	printk("# bluetooth: receiver subscribed, %d bytes per packet\n", max);
	int len = snprintf(chunk, sizeof(chunk), "# result: %s\n", result);

	err = send_chunk(chunk, MIN(len, max));
	/* pack as many whole sample lines into each notification as fit */
	len = 0;
	for (int i = 0; i < n && !err; i++) {
		char line[12];
		int l = snprintf(line, sizeof(line), "%d\n", (int)lroundf(samples[i]));

		if (len + l > max) {
			err = send_chunk(chunk, len);
			len = 0;
		}
		memcpy(&chunk[len], line, l);
		len += l;
	}
	if (!err && len) {
		err = send_chunk(chunk, len);
	}
	if (!err) {
		err = send_chunk("# end\n", 6);
	}

	if (current) {
		bt_conn_disconnect(current, BT_HCI_ERR_REMOTE_USER_TERM_CONN);
		k_sem_take(&gone, K_SECONDS(2));
	}
	return err;
}
