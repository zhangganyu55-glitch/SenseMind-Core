/*
 * Two physical buttons on the SenseMind H1-02 prototype.
 *
 * KEY_A = P1.04 (board pad 104), KEY_B = P1.06 (board pad 106).
 * Both are wired GPIO -> button -> GND and use the internal pull-up.
 *
 * The GPIO edge interrupt only wakes the button thread.  Debounce, short/long
 * classification and event queuing happen in that thread, never in the ISR.
 */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>

#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/printk.h>

#include "buttons.h"

#define DEBOUNCE_MS 30
#define SHORT_MIN_MS 40
#define SHORT_MAX_MS 600
#define LONG_MS 800

static const struct gpio_dt_spec button_spec[2] = {
	[BTN_A] = GPIO_DT_SPEC_GET(DT_NODELABEL(button_a), gpios),
	[BTN_B] = GPIO_DT_SPEC_GET(DT_NODELABEL(button_b), gpios),
};

struct button_state {
	bool raw_last;
	bool stable;
	int64_t change_at;
	int64_t press_at;
	bool long_sent;
};

static struct button_state state[2];
static struct k_sem button_sem;
static struct gpio_callback button_cb;
static atomic_t dropped_events;

K_MSGQ_DEFINE(button_msgq, sizeof(struct button_event), 8, 4);

static void button_isr(const struct device *port, struct gpio_callback *cb,
		       uint32_t pins)
{
	ARG_UNUSED(port);
	ARG_UNUSED(cb);
	ARG_UNUSED(pins);

	k_sem_give(&button_sem);
}

static void post_event(enum button_id id, enum button_event_type type)
{
	struct button_event ev = {
		.id = (uint8_t)id,
		.type = (uint8_t)type,
	};

	if (k_msgq_put(&button_msgq, &ev, K_NO_WAIT) != 0) {
		atomic_inc(&dropped_events);
	}

#if IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG)
	printk("SM BTN %c %s\n", id == BTN_A ? 'A' : 'B',
	       type == BTN_SHORT ? "SHORT" : "LONG");
#endif
}

static int buttons_init(void)
{
	k_sem_init(&button_sem, 0, 1);

	for (int i = 0; i < 2; i++) {
		if (!gpio_is_ready_dt(&button_spec[i])) {
			printk("SM BTN %c GPIO not ready\n", i == BTN_A ? 'A' : 'B');
			return -ENODEV;
		}

		int rc = gpio_pin_configure_dt(&button_spec[i], GPIO_INPUT);

		if (rc != 0) {
			printk("SM BTN %c configure rc=%d\n", i == BTN_A ? 'A' : 'B', rc);
			return rc;
		}

		rc = gpio_pin_interrupt_configure_dt(&button_spec[i],
						     GPIO_INT_EDGE_BOTH);
		if (rc != 0) {
			/* Polling fallback: the thread still samples every 10 ms. */
			printk("SM BTN %c irq rc=%d (poll fallback)\n",
			       i == BTN_A ? 'A' : 'B', rc);
		}
	}

	/* Both buttons are on GPIO1 on this board. */
	if (button_spec[BTN_A].port != button_spec[BTN_B].port) {
		printk("SM BTN ports differ; irq grouping disabled\n");
		return 0;
	}

	gpio_init_callback(&button_cb, button_isr,
			   BIT(button_spec[BTN_A].pin) |
			   BIT(button_spec[BTN_B].pin));
	int rc = gpio_add_callback(button_spec[BTN_A].port, &button_cb);

	if (rc != 0) {
		printk("SM BTN callback rc=%d (poll fallback)\n", rc);
	}

	for (int i = 0; i < 2; i++) {
		state[i].raw_last = gpio_pin_get_dt(&button_spec[i]) != 0;
		state[i].stable = state[i].raw_last;
		state[i].change_at = k_uptime_get();
		state[i].press_at = state[i].change_at;
		state[i].long_sent = false;
	}

#if IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG)
	printk("SM BTN ready A=P1.04 B=P1.06\n");
#endif

	return 0;
}

static void button_thread(void *a, void *b, void *c)
{
	ARG_UNUSED(a);
	ARG_UNUSED(b);
	ARG_UNUSED(c);

	if (buttons_init() != 0) {
		printk("SM BTN init failed\n");
		return;
	}

	while (1) {
		/* A 10 ms timeout also provides the polling fallback if the
		 * GPIO interrupt is unavailable. */
		(void)k_sem_take(&button_sem, K_MSEC(10));

		int64_t now = k_uptime_get();

		for (int i = 0; i < 2; i++) {
			bool raw = gpio_pin_get_dt(&button_spec[i]) != 0;
			struct button_state *st = &state[i];

			if (raw != st->raw_last) {
				st->raw_last = raw;
				st->change_at = now;
			}

			if (now - st->change_at >= DEBOUNCE_MS &&
			    st->stable != st->raw_last) {
				st->stable = st->raw_last;

				if (st->stable) {
					st->press_at = now;
					st->long_sent = false;
				} else {
					int64_t held = now - st->press_at;

					if (!st->long_sent &&
					    held >= SHORT_MIN_MS &&
					    held <= SHORT_MAX_MS) {
						post_event((enum button_id)i,
							   BTN_SHORT);
					}
				}
			}

			if (st->stable && !st->long_sent &&
			    now - st->press_at >= LONG_MS) {
				post_event((enum button_id)i, BTN_LONG);
				st->long_sent = true;
			}
		}
	}
}

K_THREAD_DEFINE(sm_button_thread_id, 2048, button_thread,
		NULL, NULL, NULL, 6, 0, 0);

int buttons_get_event(struct button_event *ev, k_timeout_t timeout)
{
	return k_msgq_get(&button_msgq, ev, timeout);
}

uint32_t buttons_dropped_events(void)
{
	return (uint32_t)atomic_get(&dropped_events);
}
