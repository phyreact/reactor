#include "../zero/tof/vendor/platform.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static unsigned calls, fail_at;
static uint16_t seen_reg[4], seen_size[4];
static int32_t write_mock(uint16_t address, uint16_t reg, uint8_t *data, uint16_t size) {
    assert(address == 0x52 && data && size <= 512);
    seen_reg[calls] = reg; seen_size[calls] = size;
    ++calls;
    return calls == fail_at ? -1 : 0;
}
static int32_t read_mock(uint16_t address, uint16_t reg, uint8_t *data, uint16_t size) {
    int32_t result = write_mock(address, reg, data, size);
    if (!result) memset(data, (int)calls, size);
    return result;
}
int main(void) {
    VL53L8CX_Platform platform = {.address = 0x52, .Write = write_mock, .Read = read_mock};
    uint8_t bytes[1025] = {0};
    assert(!VL53L8CX_WrMulti(&platform, 0x1000, bytes, sizeof(bytes)));
    assert(calls == 3 && seen_reg[0] == 0x1000 && seen_reg[1] == 0x1200 &&
           seen_reg[2] == 0x1400 && seen_size[0] == 512 &&
           seen_size[1] == 512 && seen_size[2] == 1);
    calls = 0; fail_at = 2;
    assert(VL53L8CX_RdMulti(&platform, 0, bytes, sizeof(bytes)));
    assert(calls == 2 && bytes[0] == 1 && bytes[511] == 1 && bytes[512] == 0);
    calls = fail_at = 0;
    assert(VL53L8CX_WrMulti(&platform, 0xffff, bytes, 2));
    assert(calls == 0);
    assert(!VL53L8CX_WrByte(&platform, 0xffff, 5));
    assert(calls == 1 && seen_reg[0] == 0xffff && seen_size[0] == 1);
    uint8_t endian[] = {0, 1, 2, 3, 4, 5, 6, 7, 8};
    VL53L8CX_SwapBuffer(endian, sizeof(endian));
    const uint8_t expected[] = {3, 2, 1, 0, 7, 6, 5, 4, 8};
    assert(!memcmp(endian, expected, sizeof(endian)));
    puts("PASS: ToF I2C chunking, partial-transfer failure, register bounds, byte order");
}
