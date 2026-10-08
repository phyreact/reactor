#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define BOX_FRAME_SIZE 64u
#define BOX_PAYLOAD_SIZE 50u
#define BOX_I2C_ADDRESS 0x2du
#define BOX_LINK_TIMEOUT_MS 500u
#define BOX_RADAR_ON_SETTLE_MS 300u
#define BOX_RADAR_OFF_SETTLE_MS 50u
#define BOX_FINAL_CUT_DELAY_MS 1000u
#define BOX_RELAY_MIN_DWELL_MS 250u
#define BOX_HOST_ON_SETTLE_MS 500u
#define BOX_MAIN_RELEASE_DELAY_MS 250u
/* Timing values are engineering defaults; they require on-device qualification. */
enum box_message { BOX_RP_LINK = 1, BOX_S3_LINK, BOX_HOST_COMMAND,
                   BOX_HOST_STATUS, BOX_RADAR_SAMPLE };
enum box_command { BOX_READY = 1, BOX_HOST_ON, BOX_HOST_OFF, BOX_ALL_OFF,
                   BOX_RADAR_SET, BOX_TOF_SET, BOX_SAFE_TO_CUT, BOX_GET_STATUS };
typedef struct {
    uint8_t type, length;
    uint16_t sequence;
    uint32_t boot;
    uint8_t payload[BOX_PAYLOAD_SIZE];
} box_packet;
typedef struct { uint8_t bytes[BOX_FRAME_SIZE]; size_t used; } box_stream;
typedef struct { uint8_t bytes[30]; size_t used; } box_radar_parser;
uint16_t box_crc16(const uint8_t *data, size_t size);
void box_put32(uint8_t *p, uint32_t value);
uint32_t box_get32(const uint8_t *p);
bool box_sequence_newer(uint16_t next, uint16_t previous);
void box_encode(const box_packet *packet, uint8_t out[BOX_FRAME_SIZE]);
bool box_decode(const uint8_t in[BOX_FRAME_SIZE], box_packet *packet);
bool box_stream_byte(box_stream *stream, uint8_t byte, box_packet *packet);
bool box_radar_byte(box_radar_parser *parser, uint8_t byte, uint8_t sample[30]);
