#ifndef SENSEMIND_WIRE_H
#define SENSEMIND_WIRE_H
#include <stdint.h>
#include <stddef.h>
uint16_t sm_crc16(const uint8_t *data,size_t length);
size_t sm_fragment(const uint8_t *message,uint16_t length,uint16_t crc,uint32_t id,uint16_t index,uint16_t payload,uint8_t *out,size_t capacity);
#endif
