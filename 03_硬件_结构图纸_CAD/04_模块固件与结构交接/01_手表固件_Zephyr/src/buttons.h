#ifndef SENSEMIND_BUTTONS_H
#define SENSEMIND_BUTTONS_H

#include <stdint.h>
#include <zephyr/kernel.h>

enum button_id {
	BTN_A = 0,
	BTN_B = 1,
};

enum button_event_type {
	BTN_SHORT = 0,
	BTN_LONG = 1,
};

struct button_event {
	uint8_t id;
	uint8_t type;
};

/* Wait for a debounced short/long event.  Returns 0 on success, -EAGAIN on
 * timeout, or another negative errno. */
int buttons_get_event(struct button_event *ev, k_timeout_t timeout);

/* Number of events dropped because the queue was full (diagnostics). */
uint32_t buttons_dropped_events(void);

#endif /* SENSEMIND_BUTTONS_H */
