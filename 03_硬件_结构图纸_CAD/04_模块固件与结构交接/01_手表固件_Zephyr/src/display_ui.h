#ifndef SENSEMIND_DISPLAY_UI_H
#define SENSEMIND_DISPLAY_UI_H

#include <stdbool.h>
#include <stdint.h>

/* Called from the H1 main loop / BLE callbacks.  All functions are safe to
 * call from any thread; they only update a small shared snapshot. */
void sm_ui_set_ble(bool connected, bool subscribed);
void sm_ui_set_sensors(bool imu_ok, bool ppg_ok);
void sm_ui_set_imu(const int16_t raw[6]);
void sm_ui_push_ppg(uint32_t red, uint32_t ir);
void sm_ui_set_counters(uint32_t seq, uint32_t overruns);
void sm_ui_set_ids(const char *device_id, const char *boot_id, const char *fw);

#endif /* SENSEMIND_DISPLAY_UI_H */
