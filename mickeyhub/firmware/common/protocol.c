#include "protocol.h"
#include <string.h>

uint16_t box_crc16(const uint8_t *data, size_t size) {
    uint16_t crc = 0xffff;
    for (size_t i = 0; i < size; ++i) {
        crc ^= (uint16_t)data[i] << 8;
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (uint16_t)((crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1);
    }
    return crc;
}
void box_put32(uint8_t *p, uint32_t v) {
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (8 * i));
}
uint32_t box_get32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
bool box_sequence_newer(uint16_t next, uint16_t previous) {
    uint16_t difference = (uint16_t)(next - previous);
    return difference != 0 && difference < 0x8000;
}
void box_encode(const box_packet *p, uint8_t out[BOX_FRAME_SIZE]) {
    memset(out, 0, BOX_FRAME_SIZE);
    out[0] = 0xa5; out[1] = 0x5a; out[2] = 1; out[3] = p->type;
    out[4] = (uint8_t)p->sequence; out[5] = (uint8_t)(p->sequence >> 8);
    out[6] = p->length <= BOX_PAYLOAD_SIZE ? p->length : 0;
    box_put32(out + 8, p->boot);
    memcpy(out + 12, p->payload, out[6]);
    uint16_t crc = box_crc16(out, 62);
    out[62] = (uint8_t)crc; out[63] = (uint8_t)(crc >> 8);
}
bool box_decode(const uint8_t in[BOX_FRAME_SIZE], box_packet *p) {
    if (in[0] != 0xa5 || in[1] != 0x5a || in[2] != 1 ||
        in[3] < BOX_RP_LINK || in[3] > BOX_RADAR_SAMPLE ||
        in[6] > BOX_PAYLOAD_SIZE || in[7] != 0 ||
        box_crc16(in, 62) != ((uint16_t)in[62] | (uint16_t)in[63] << 8)) return false;
    memset(p, 0, sizeof(*p));
    p->type = in[3]; p->sequence = (uint16_t)in[4] | (uint16_t)in[5] << 8;
    p->length = in[6]; p->boot = box_get32(in + 8);
    memcpy(p->payload, in + 12, p->length);
    return true;
}
bool box_stream_byte(box_stream *s, uint8_t byte, box_packet *p) {
    if (!s->used && byte != 0xa5) return false;
    s->bytes[s->used++] = byte;
    if (s->used == 2 && s->bytes[1] != 0x5a) {
        s->used = byte == 0xa5 ? 1 : 0;
        s->bytes[0] = byte;
    }
    if (s->used != BOX_FRAME_SIZE) return false;
    if (box_decode(s->bytes, p)) { s->used = 0; return true; }
    memmove(s->bytes, s->bytes + 1, --s->used);
    while (s->used && s->bytes[0] != 0xa5)
        memmove(s->bytes, s->bytes + 1, --s->used);
    return false;
}
bool box_radar_byte(box_radar_parser *s, uint8_t byte, uint8_t sample[30]) {
    static const uint8_t header[] = {0xaa, 0xff, 0x03, 0x00};
    if (s->used < 4 && byte != header[s->used]) {
        s->used = byte == 0xaa ? 1 : 0; s->bytes[0] = byte;
        return false;
    }
    s->bytes[s->used++] = byte;
    if (s->used != 30) return false;
    if (s->bytes[28] == 0x55 && s->bytes[29] == 0xcc) {
        memcpy(sample, s->bytes, 30); s->used = 0; return true;
    }
    /* Recover a complete nested header after a damaged/truncated frame. */
    for (size_t i = 1; i <= 26; ++i) {
        if (!memcmp(s->bytes + i, header, 4)) {
            memmove(s->bytes, s->bytes + i, 30 - i); s->used = 30 - i;
            return false;
        }
    }
    s->used = byte == 0xaa ? 1 : 0; s->bytes[0] = byte;
    return false;
}
