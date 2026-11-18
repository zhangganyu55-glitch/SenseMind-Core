/* SenseMind raw telemetry v1. Never flashes, updates UICR, estimates HR, or enables display. */
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/random/random.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/printk.h>
#include <zephyr/sys/reboot.h>
#include <zephyr/drivers/uart.h>
#include <hal/nrf_ficr.h>
#include <hal/nrf_power.h>
#include "sensors.h"
#include "wire.h"
#include "display_ui.h"
BUILD_ASSERT(DT_REG_ADDR(DT_CHOSEN(zephyr_code_partition))==0x26000,"unsafe UF2 start");
BUILD_ASSERT(DT_REG_SIZE(DT_CHOSEN(zephyr_code_partition))==0x87000,"unsafe UF2 limit");
BUILD_ASSERT(!DT_PROP_OR(DT_NODELABEL(uicr),nfct_pins_as_gpios,0),"UICR NFC write prohibited");
BUILD_ASSERT(!DT_PROP_OR(DT_NODELABEL(uicr),gpio_as_nreset,0),"UICR reset write prohibited");
#define VERSION "v0.7.0"
#define MAX_JSON 4096
#define QUEUE_N 4
#define BATCH_N 64
#define UUID(v) BT_UUID_128_ENCODE(v,0x1d2a,0x4f6e,0x9a7b,0x1c2d3e4f5a60)
static struct bt_uuid_128 service_uuid=BT_UUID_INIT_128(UUID(0x5f9b3c10));
static struct bt_uuid_128 data_uuid=BT_UUID_INIT_128(UUID(0x5f9b3c11));
static struct bt_uuid_128 ack_uuid=BT_UUID_INIT_128(UUID(0x5f9b3c12));
struct message { uint32_t id;uint16_t len,crc;char json[MAX_JSON]; };
static struct message queue[QUEUE_N];static unsigned head,used;
static uint32_t next_id,overruns;static uint16_t fragment;
static int64_t retry_at;
static struct bt_conn *connection;static bool subscribed;
K_MUTEX_DEFINE(lock);
struct batch { int32_t value[6][BATCH_N];unsigned count;uint64_t first_us;int last_error;uint32_t sequence; };
static struct batch imu,ppg;
static char device_id[40],boot_id[40],json_buffer[MAX_JSON];
static void enqueue(const char *json,size_t len) {
 k_mutex_lock(&lock,K_FOREVER);
 if(used==QUEUE_N||len>=MAX_JSON) { overruns++;k_mutex_unlock(&lock);return; }
 struct message *m=&queue[(head+used)%QUEUE_N];m->id=++next_id;m->len=len;
 memcpy(m->json,json,len);m->crc=sm_crc16((const uint8_t *)json,len);used++;
 k_mutex_unlock(&lock);
}
static ssize_t read_data(struct bt_conn *c,const struct bt_gatt_attr *a,void *b,uint16_t len,uint16_t offset) {
 /* READ exposes the transport state, not an ambiguous truncated JSON packet. */
 uint8_t status[8];k_mutex_lock(&lock,K_FOREVER);sys_put_le32(used,status);sys_put_le32(overruns,status+4);k_mutex_unlock(&lock);
 return bt_gatt_attr_read(c,a,b,len,offset,status,sizeof(status));
}
static void ccc(const struct bt_gatt_attr *a,uint16_t value) { ARG_UNUSED(a);subscribed=value==BT_GATT_CCC_NOTIFY;sm_ui_set_ble(connection!=NULL,subscribed); }
static ssize_t write_ack(struct bt_conn *c,const struct bt_gatt_attr *a,const void *buf,uint16_t len,uint16_t offset,uint8_t flags) {
 ARG_UNUSED(c);ARG_UNUSED(a);ARG_UNUSED(flags);const uint8_t *p=buf;
 if(offset||len!=8||p[0]!='S'||p[1]!='A'||p[2]!=1||p[3]>1)return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
 k_mutex_lock(&lock,K_FOREVER);
 if(used&&sys_get_le32(p+4)==queue[head].id) {
   if(p[3]==0){head=(head+1)%QUEUE_N;used--;}
   fragment=0;retry_at=0;
 }
 k_mutex_unlock(&lock);return len;
}
BT_GATT_SERVICE_DEFINE(sm_service,
 BT_GATT_PRIMARY_SERVICE(&service_uuid),
 BT_GATT_CHARACTERISTIC(&data_uuid.uuid,BT_GATT_CHRC_READ|BT_GATT_CHRC_NOTIFY,BT_GATT_PERM_READ,read_data,NULL,NULL),
 BT_GATT_CCC(ccc,BT_GATT_PERM_READ|BT_GATT_PERM_WRITE),
 BT_GATT_CHARACTERISTIC(&ack_uuid.uuid,BT_GATT_CHRC_WRITE,BT_GATT_PERM_WRITE,NULL,write_ack,NULL));
static const struct bt_data ad[]={BT_DATA_BYTES(BT_DATA_FLAGS,(BT_LE_AD_GENERAL|BT_LE_AD_NO_BREDR)),BT_DATA(BT_DATA_NAME_COMPLETE,CONFIG_BT_DEVICE_NAME,sizeof(CONFIG_BT_DEVICE_NAME)-1)};
static const struct bt_data sd[]={BT_DATA_BYTES(BT_DATA_UUID128_ALL,UUID(0x5f9b3c10))};
static void advertise(struct k_work *work);
K_WORK_DELAYABLE_DEFINE(adv_work,advertise);
static void advertise(struct k_work *work) { ARG_UNUSED(work);int rc=bt_le_adv_start(BT_LE_ADV_CONN_FAST_2,ad,ARRAY_SIZE(ad),sd,ARRAY_SIZE(sd));if(rc&&rc!=-EALREADY){printk("SM ADV retry error=%d\n",rc);k_work_reschedule(&adv_work,K_SECONDS(2));} }
static void mtu_exchanged(struct bt_conn *c,uint8_t error,struct bt_gatt_exchange_params *params) {
 ARG_UNUSED(c);ARG_UNUSED(error);ARG_UNUSED(params);
}
static struct bt_gatt_exchange_params mtu_params={.func=mtu_exchanged};
static void connected(struct bt_conn *c,uint8_t error) {
 if(error){k_work_reschedule(&adv_work,K_SECONDS(1));return;}
 k_mutex_lock(&lock,K_FOREVER);connection=bt_conn_ref(c);fragment=0;retry_at=0;k_mutex_unlock(&lock);
 sm_ui_set_ble(true,false);
 (void)bt_gatt_exchange_mtu(c,&mtu_params);
}
static void disconnected(struct bt_conn *c,uint8_t reason) {
 ARG_UNUSED(c);ARG_UNUSED(reason);k_mutex_lock(&lock,K_FOREVER);
 if(connection){bt_conn_unref(connection);connection=NULL;}subscribed=false;fragment=0;retry_at=0;k_mutex_unlock(&lock);
 sm_ui_set_ble(false,false);
 k_work_reschedule(&adv_work,K_SECONDS(1));
}
BT_CONN_CB_DEFINE(callbacks)={.connected=connected,.disconnected=disconnected};
static void transmit(void) {
 uint8_t frame[244];k_mutex_lock(&lock,K_FOREVER);
 if(!connection||!subscribed||!used){k_mutex_unlock(&lock);return;}
 struct message *m=&queue[head];uint16_t mtu=bt_gatt_get_mtu(connection);
 unsigned payload=MIN(sizeof(frame)-16,(unsigned)(mtu>19?mtu-19:0));
 if(!payload){k_mutex_unlock(&lock);return;}
 unsigned count=DIV_ROUND_UP(m->len,payload);
 if(fragment>=count) {
   if(k_uptime_get()<retry_at){k_mutex_unlock(&lock);return;}
   fragment=0;
 }
 size_t size=sm_fragment((const uint8_t *)m->json,m->len,m->crc,m->id,fragment,payload,frame,sizeof(frame));
 int rc=size?bt_gatt_notify(connection,&sm_service.attrs[2],frame,size):-EINVAL;
 if(!rc){fragment++;if(fragment==count)retry_at=k_uptime_get()+5000;}
 k_mutex_unlock(&lock);
}
static int append(char **p,size_t *left,const char *fmt,...) {
 va_list ap;va_start(ap,fmt);int n=vsnprintf(*p,*left,fmt,ap);va_end(ap);
 if(n<0||(size_t)n>=*left)return -ENOSPC;
 *p+=n;*left-=n;return 0;
}
static void packet(struct batch *b,bool optical) {
 char *p=json_buffer;size_t left=sizeof(json_buffer);bool has=b->count>0;
 const char *names[6]={"ax_raw","ay_raw","az_raw","gx_raw","gy_raw","gz_raw"};
 const char *source=IS_ENABLED(CONFIG_SENSEMIND_TEST_DATA)?"test":"hardware";
 const char *sensor=optical?"max30102":"mpu6050";const char *stream=optical?"ppg":"imu";
 int rc=append(&p,&left,"{\"protocol_version\":\"1.0\",\"device_id\":\"%s\",\"device_type\":\"wearable_nrf52840\",\"source_type\":\"%s\",\"timestamp\":null,\"boot_id\":\"%s\",\"stream_id\":\"%s\",\"sequence_number\":%u,\"sensor_type\":\"%s\",\"sampling_rate\":%s,\"measurements\":{",device_id,source,boot_id,stream,b->sequence++,sensor,has?(optical?"50":"10"):"null");
 for(unsigned ch=0;has&&ch<(optical?2:6)&&!rc;ch++) {
   rc=append(&p,&left,"%s\"%s\":{\"unit\":\"count\",\"samples\":[",ch?",":"",optical?(ch?"ir":"red"):names[ch]);
   for(unsigned i=0;i<b->count&&!rc;i++)rc=append(&p,&left,"%s%d",i?",":"",b->value[ch][i]);
   if(!rc)rc=append(&p,&left,"],\"validity\":[");
   for(unsigned i=0;i<b->count&&!rc;i++)rc=append(&p,&left,"%strue",i?",":"");
   if(!rc)rc=append(&p,&left,"]}");
 }
 bool present=has||b->last_error!=-ENODEV;
 if(!rc)rc=append(&p,&left,"},\"signal_quality\":\"%s\",\"device_status\":{\"connected\":%s,\"sampling\":%s,\"sensor_present\":%s,\"error_codes\":[%s],\"buffer_overruns\":%u,\"heartbeat_interval_seconds\":1,\"firmware_version\":\"%s\"},\"device_time_us\":%llu,\"time_sync\":{\"status\":\"unsynced\"},\"packet_kind\":\"%s\"}",has?"unknown":"invalid",connection?"true":"false",has?"true":"false",present?"true":"false",b->last_error?"\"SENSOR_READ_OR_FIFO_ERROR\"":"",overruns,VERSION,(unsigned long long)(has?b->first_us:k_uptime_get()*1000),has?"samples":"status");
 if(!rc)enqueue(json_buffer,p-json_buffer);else overruns++;
 b->count=0;
}
static void collect(struct batch *b,const int32_t *v,unsigned channels) {
 if(b->count==BATCH_N){overruns++;return;}
 if(!b->count)b->first_us=k_uptime_get()*1000;
 for(unsigned i=0;i<channels;i++){b->value[i][b->count]=v[i];}
 b->count++;
}
#if CONFIG_SENSEMIND_BOOTLOADER_CMD
static void enter_bootloader(void) {
 printk("SM reboot to UF2 bootloader\n");
 k_msleep(20);
 NRF_POWER->GPREGRET=0x57; /* DFU_MAGIC_UF2_RESET: Adafruit/nice!nano UF2 bootloader */
 sys_reboot(SYS_REBOOT_COLD);
}
static void poll_boot_command(void) {
 static char boot_cmd[8];static unsigned boot_len;
 static const struct device *console=DEVICE_DT_GET(DT_CHOSEN(zephyr_console));
 unsigned char c;
 if(!device_is_ready(console))return;
 while(uart_poll_in(console,&c)==0) {
   if(c=='\r'||c=='\n') {
     boot_cmd[boot_len]=0;
     if(!strcmp(boot_cmd,"boot")||!strcmp(boot_cmd,"dfu"))enter_bootloader();
     boot_len=0;
   } else if(boot_len<sizeof(boot_cmd)-1)boot_cmd[boot_len++]=(char)c;
 }
}
#endif
int main(void) {
 snprintf(device_id,sizeof(device_id),"band-%08x%08x",NRF_FICR->DEVICEID[0],NRF_FICR->DEVICEID[1]);
 snprintf(boot_id,sizeof(boot_id),"%08x%08x",sys_rand32_get(),sys_rand32_get());
 sm_ui_set_ids(device_id,boot_id,VERSION);
 if(IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG))printk("SM BOOT %s device=%s\n",VERSION,device_id);
 if(!IS_ENABLED(CONFIG_SENSEMIND_TEST_DATA)) {
   int sensor_rc=sm_sensors_init();
   if(IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG))printk("SM sensors init rc=%d\n",sensor_rc);
 }
 sm_ui_set_sensors(sm_imu_present(),sm_ppg_present());
 int rc=bt_enable(NULL);if(rc){printk("SM BLE unavailable %d\n",rc);return rc;}
 k_work_reschedule(&adv_work,K_NO_WAIT);
 sm_ui_set_ble(false,false);
 int64_t sensor_at=0,imu_at=0,packet_at=1000,log_at=1000,scan_at=2000;
 int32_t last_imu[6]={0};uint32_t last_red=0,last_ir=0;bool have_imu=false,have_ppg=false;
 while(1) {
   int64_t now=k_uptime_get();
   if(now>=sensor_at) {
     sensor_at=now+20;uint32_t red,ir;
     if(IS_ENABLED(CONFIG_SENSEMIND_TEST_DATA)){red=100000+(now%100);ir=120000+(now%100);rc=0;}
     else rc=sm_max30102_read(&red,&ir);
     ppg.last_error=(rc==-EAGAIN)?0:rc;
     if(!rc){
       int32_t v[2]={red,ir};collect(&ppg,v,2);sm_ui_push_ppg(red,ir);
       last_red=red;last_ir=ir;have_ppg=true;
       if(!IS_ENABLED(CONFIG_SENSEMIND_TEST_DATA)) {
         /* Drain bounded backlog so scheduler jitter cannot silently lower FIFO rate. */
         for(unsigned n=1;n<4;n++) {
           int more=sm_max30102_read(&red,&ir);
           if(more){if(more!=-EAGAIN)ppg.last_error=more;break;}
           v[0]=red;v[1]=ir;collect(&ppg,v,2);sm_ui_push_ppg(red,ir);
           last_red=red;last_ir=ir;
         }
       }
     }
     if(ppg.last_error==-EOVERFLOW){overruns++;ppg.count=0;}
   }
   if(now>=imu_at) {
     imu_at=now+100;int16_t raw[6];
     if(IS_ENABLED(CONFIG_SENSEMIND_TEST_DATA)){memset(raw,0,sizeof(raw));raw[2]=16384;rc=0;}else rc=sm_mpu6050_read(raw);
     imu.last_error=rc;
     if(!rc){int32_t v[6];for(unsigned i=0;i<6;i++){v[i]=raw[i];last_imu[i]=raw[i];}collect(&imu,v,6);sm_ui_set_imu(raw);have_imu=true;}
   }
   if(now>=packet_at){
     packet_at=now+1000;packet(&imu,false);packet(&ppg,true);
     sm_ui_set_counters(imu.sequence,overruns);
     sm_ui_set_sensors(imu.last_error==0,ppg.last_error==0);
   }
   if(IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG)&&now>=log_at) {
     log_at=now+1000;
     printk("SM BRINGUP imu_err=%d ppg_err=%d imu=%d ppg=%d",imu.last_error,ppg.last_error,have_imu,have_ppg);
     if(have_imu)printk(" ax=%d ay=%d az=%d gx=%d gy=%d gz=%d",last_imu[0],last_imu[1],last_imu[2],last_imu[3],last_imu[4],last_imu[5]);
     if(have_ppg)printk(" red=%u ir=%u",last_red,last_ir);
     printk("\n");
   }
   if(IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG)&&now>=scan_at&&(!have_imu||!have_ppg)) {
     scan_at=now+5000;
     sm_bringup_scan();
   }
#if CONFIG_SENSEMIND_BOOTLOADER_CMD
   poll_boot_command();
#endif
   transmit();k_msleep(10);
 }
 return 0;
}
