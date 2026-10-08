#define _POSIX_C_SOURCE 200809L
#include "vendor/platform.h"
#include <errno.h>
#include <time.h>

/* Keep vendor files unchanged. I2C transfers stay below adapter message limits;
 * register indexes are big endian. A failed partial transfer is never retried. */
static uint8_t transfer(VL53L8CX_Platform *p, uint16_t reg, uint8_t *data,
                        uint32_t size, int write) {
    if (!p || !data || size > 65536u - reg) return 255;
    while (size) {
        uint16_t n = size > 512 ? 512 : (uint16_t)size;
        int32_t rc = write ? p->Write(p->address, reg, data, n)
                           : p->Read(p->address, reg, data, n);
        if (rc) return 255;
        size -= n; data += n; reg = (uint16_t)(reg + n);
    }
    return 0;
}
uint8_t VL53L8CX_RdMulti(VL53L8CX_Platform *p, uint16_t r, uint8_t *d, uint32_t n) {
    return transfer(p, r, d, n, 0);
}
uint8_t VL53L8CX_WrMulti(VL53L8CX_Platform *p, uint16_t r, uint8_t *d, uint32_t n) {
    return transfer(p, r, d, n, 1);
}
uint8_t VL53L8CX_RdByte(VL53L8CX_Platform *p, uint16_t r, uint8_t *d) {
    return transfer(p, r, d, 1, 0);
}
uint8_t VL53L8CX_WrByte(VL53L8CX_Platform *p, uint16_t r, uint8_t d) {
    return transfer(p, r, &d, 1, 1);
}
void VL53L8CX_SwapBuffer(uint8_t *b, uint16_t n) {
    for (uint32_t i = 0; i + 3 < n; i += 4) {
        uint8_t a = b[i], c = b[i+1];
        b[i] = b[i+3]; b[i+1] = b[i+2]; b[i+2] = c; b[i+3] = a;
    }
}
uint8_t VL53L8CX_WaitMs(VL53L8CX_Platform *p, uint32_t ms) {
    (void)p;
    struct timespec delay = {ms / 1000u, (long)(ms % 1000u) * 1000000L};
    while (nanosleep(&delay, &delay) && errno == EINTR) {}
    return 0;
}
