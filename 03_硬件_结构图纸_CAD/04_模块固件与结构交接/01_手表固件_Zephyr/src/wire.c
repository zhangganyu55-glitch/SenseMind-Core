#include "wire.h"
#include <string.h>
static void put16(uint8_t *p,uint16_t v){p[0]=v;p[1]=v>>8;}
static void put32(uint8_t *p,uint32_t v){put16(p,v);put16(p+2,v>>16);}
uint16_t sm_crc16(const uint8_t *p,size_t n){
 uint16_t crc=0xffff;
 while(n--){crc^=(uint16_t)(*p++)<<8;for(unsigned i=0;i<8;i++)crc=(crc&0x8000)?(uint16_t)((crc<<1)^0x1021):(uint16_t)(crc<<1);}
 return crc;
}
size_t sm_fragment(const uint8_t *m,uint16_t length,uint16_t crc,uint32_t id,uint16_t index,uint16_t payload,uint8_t *out,size_t capacity){
 if(!length||length>4096||!payload||capacity<16)return 0;
 unsigned count=(length+payload-1)/payload;if(count>1024||index>=count)return 0;
 unsigned first=index*payload,n=length-first;if(n>payload)n=payload;if(capacity<16+n)return 0;
 out[0]='S';out[1]='M';out[2]=1;out[3]=0;put32(out+4,id);put16(out+8,index);put16(out+10,count);put16(out+12,length);put16(out+14,crc);
 memcpy(out+16,m+first,n);return n+16;
}
