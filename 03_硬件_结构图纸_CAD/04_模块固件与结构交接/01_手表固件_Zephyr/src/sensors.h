#ifndef SENSEMIND_SENSORS_H
#define SENSEMIND_SENSORS_H
#include <stdbool.h>
#include <stdint.h>
int sm_sensors_init(void);
bool sm_imu_present(void);
bool sm_ppg_present(void);
void sm_bringup_scan(void);
int sm_mpu6050_read(int16_t values[6]);
int sm_max30102_read(uint32_t *red, uint32_t *ir);
int sm_st7789v_init(void); /* Intentionally unsupported: SPI/display disabled. */
#endif
