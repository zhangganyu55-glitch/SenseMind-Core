/* Raw register interfaces only: no invented HR or medical quality. */
#include "sensors.h"
#include <errno.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/printk.h>
static const struct device *bus;
static bool imu_ok,ppg_ok;
bool sm_imu_present(void) { return imu_ok; }
bool sm_ppg_present(void) { return ppg_ok; }
int sm_sensors_init(void) {
 bus=DEVICE_DT_GET(DT_NODELABEL(i2c1));
 if(!device_is_ready(bus)) {
   if(IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG))printk("SM I2C1 not ready\n");
   return -ENODEV;
 }
 if(IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG)) {
   printk("SM I2C scan:");
   for(uint8_t a=0x08;a<0x78;a++){uint8_t v;if(!i2c_reg_read_byte(bus,a,0x00,&v))printk(" 0x%02x",a);}
   printk("\n");
 }
 uint8_t id=0;
 int rc_imu_id=i2c_reg_read_byte(bus,0x68,0x75,&id);
 /* MPU6050/6000 report 0x68; many MPU6500/9250 clones report 0x70/0x71. */
 bool imu_id_ok=(id==0x68||id==0x69||id==0x70||id==0x71);
 if(!rc_imu_id && imu_id_ok &&
    !i2c_reg_write_byte(bus,0x68,0x6b,0x00) &&
    !i2c_reg_write_byte(bus,0x68,0x1b,0x00) && !i2c_reg_write_byte(bus,0x68,0x1c,0x00))imu_ok=true;
 if(IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG))
   printk("SM MPU6050 who_am_i rc=%d id=0x%02x ready=%d\n",rc_imu_id,id,imu_ok);
 /* MAX30102: verify PART_ID, reset, FIFO and 50 Hz red+IR acquisition. */
 int rc_ppg_id=i2c_reg_read_byte(bus,0x57,0xff,&id);
 if(!rc_ppg_id && id==0x15) {
   if(!i2c_reg_write_byte(bus,0x57,0x09,0x40)) {
     k_msleep(20);
     ppg_ok=!i2c_reg_write_byte(bus,0x57,0x04,0) && !i2c_reg_write_byte(bus,0x57,0x05,0) &&
       !i2c_reg_write_byte(bus,0x57,0x06,0) && !i2c_reg_write_byte(bus,0x57,0x08,0) &&
       !i2c_reg_write_byte(bus,0x57,0x0a,0x23) && /* 4096 nA / 50 Hz / 411us */
       !i2c_reg_write_byte(bus,0x57,0x0c,0x1f) && !i2c_reg_write_byte(bus,0x57,0x0d,0x1f) &&
       !i2c_reg_write_byte(bus,0x57,0x09,0x03);
   }
 }
 if(IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG))
   printk("SM MAX30102 part_id rc=%d id=0x%02x ready=%d\n",rc_ppg_id,id,ppg_ok);
 return (imu_ok||ppg_ok)?0:-ENODEV;
}
void sm_bringup_scan(void) {
 if(!bus)bus=DEVICE_DT_GET(DT_NODELABEL(i2c1));
 if(!device_is_ready(bus)){printk("SM I2C not ready\n");return;}
 printk("SM I2C scan:");
 for(uint8_t a=0x08;a<0x78;a++){uint8_t v;if(!i2c_reg_read_byte(bus,a,0x00,&v))printk(" 0x%02x",a);}
 uint8_t id=0;int rc=i2c_reg_read_byte(bus,0x68,0x75,&id);
 printk("\nSM MPU who_am_i rc=%d id=0x%02x",rc,id);
 id=0;rc=i2c_reg_read_byte(bus,0x57,0xff,&id);
 printk(" | MAX part_id rc=%d id=0x%02x\n",rc,id);
}
int sm_mpu6050_read(int16_t values[6]) {
 if(!imu_ok)return -ENODEV;
 uint8_t b[14];int rc=i2c_burst_read(bus,0x68,0x3b,b,sizeof(b));
 if(rc)return rc;
 values[0]=(int16_t)sys_get_be16(b);values[1]=(int16_t)sys_get_be16(b+2);values[2]=(int16_t)sys_get_be16(b+4);
 values[3]=(int16_t)sys_get_be16(b+8);values[4]=(int16_t)sys_get_be16(b+10);values[5]=(int16_t)sys_get_be16(b+12);return 0;
}
int sm_max30102_read(uint32_t *red,uint32_t *ir) {
 if(!ppg_ok)return -ENODEV;
 uint8_t wr,rd,overflow,b[6];
 if(i2c_reg_read_byte(bus,0x57,0x04,&wr)||i2c_reg_read_byte(bus,0x57,0x06,&rd)||i2c_reg_read_byte(bus,0x57,0x05,&overflow))return -EIO;
 if(overflow) { i2c_reg_write_byte(bus,0x57,0x05,0);i2c_reg_write_byte(bus,0x57,0x06,wr&31);return -EOVERFLOW; }
 if((wr&31)==(rd&31))return -EAGAIN;
 if(i2c_burst_read(bus,0x57,0x07,b,6))return -EIO;
 *red=(((uint32_t)b[0]<<16)|((uint32_t)b[1]<<8)|b[2])&0x3ffff;
 *ir=(((uint32_t)b[3]<<16)|((uint32_t)b[4]<<8)|b[5])&0x3ffff;return 0;
}
int sm_st7789v_init(void) { return -ENOTSUP; }
