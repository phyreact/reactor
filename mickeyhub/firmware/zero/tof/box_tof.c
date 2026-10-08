#define _POSIX_C_SOURCE 200809L
#include "vendor/vl53l8cx_api.h"
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <string.h>
#include <sys/file.h>
#include <unistd.h>
#ifdef __linux__
#include <linux/i2c.h>
#include <linux/i2c-dev.h>
#include <sys/ioctl.h>
#endif

/* One sensor per process. Python supervisor serializes all calls. The advisory
 * exclusive lock also prevents two BOX processes uploading firmware together. */
static VL53L8CX_Configuration sensor;
static int bus = -1, initialized, ranging;

static int32_t write_reg(uint16_t address8, uint16_t reg, uint8_t *data, uint16_t n) {
    if (n > 512 || (address8 & 1) || address8 > 254) return -EINVAL;
#ifdef __linux__
    uint8_t bytes[514] = {(uint8_t)(reg >> 8), (uint8_t)reg};
    memcpy(bytes + 2, data, n);
    struct i2c_msg msg = {.addr = address8 >> 1, .flags = 0, .len = n + 2, .buf = bytes};
    struct i2c_rdwr_ioctl_data request = {.msgs = &msg, .nmsgs = 1};
    return ioctl(bus, I2C_RDWR, &request) == 1 ? 0 : -EIO;
#else
    (void)reg; (void)data;
    return -ENOTSUP;
#endif
}
static int32_t read_reg(uint16_t address8, uint16_t reg, uint8_t *data, uint16_t n) {
    if (n > 512 || (address8 & 1) || address8 > 254) return -EINVAL;
#ifdef __linux__
    uint8_t bytes[2] = {(uint8_t)(reg >> 8), (uint8_t)reg};
    struct i2c_msg msgs[2] = {
        {.addr = address8 >> 1, .flags = 0, .len = 2, .buf = bytes},
        {.addr = address8 >> 1, .flags = I2C_M_RD, .len = n, .buf = data}};
    struct i2c_rdwr_ioctl_data request = {.msgs = msgs, .nmsgs = 2};
    return ioctl(bus, I2C_RDWR, &request) == 2 ? 0 : -EIO;
#else
    (void)reg; (void)data;
    return -ENOTSUP;
#endif
}
int box_tof_close(void) {
    int result = 0;
    if (initialized) {
        if (ranging) result = vl53l8cx_stop_ranging(&sensor);
        if (!result) result = vl53l8cx_set_power_mode(&sensor, VL53L8CX_POWER_MODE_SLEEP);
    }
    if (bus >= 0) close(bus);
    bus = -1; initialized = ranging = 0;
    return result;
}
int box_tof_open(const char *device) {
    if (bus >= 0) return -EBUSY;
#ifndef __linux__
    (void)device;
    return -ENOTSUP;
#else
    bus = open(device, O_RDWR | O_CLOEXEC);
    if (bus < 0) return -errno;
    if (flock(bus, LOCK_EX | LOCK_NB)) { int e = errno; close(bus); bus = -1; return -e; }
    unsigned long capabilities = 0;
    if (ioctl(bus, I2C_FUNCS, &capabilities) || !(capabilities & I2C_FUNC_I2C)) {
        box_tof_close(); return -ENOTSUP;
    }
    memset(&sensor, 0, sizeof(sensor));
    sensor.platform.address = 0x52; /* ULD 8-bit address; Linux ioctl uses 0x29. */
    sensor.platform.Read = read_reg; sensor.platform.Write = write_reg;
    uint8_t alive = 0;
    int result = vl53l8cx_is_alive(&sensor, &alive);
    if (!result && !alive) result = -ENODEV;
    if (!result) result = vl53l8cx_init(&sensor);
    if (result) { box_tof_close(); return result; }
    initialized = 1;
    result = vl53l8cx_set_resolution(&sensor, VL53L8CX_RESOLUTION_8X8);
    if (!result) result = vl53l8cx_set_ranging_frequency_hz(&sensor, 10);
    if (!result) result = vl53l8cx_set_power_mode(&sensor, VL53L8CX_POWER_MODE_SLEEP);
    if (result) box_tof_close();
    return result;
#endif
}
int box_tof_start(void) {
    if (!initialized) return -ENODEV;
    if (ranging) return 0;
    int result = vl53l8cx_set_power_mode(&sensor, VL53L8CX_POWER_MODE_WAKEUP);
    if (!result) result = vl53l8cx_start_ranging(&sensor);
    if (!result) ranging = 1;
    return result;
}
int box_tof_stop(void) {
    if (!initialized) return -ENODEV;
    int result = ranging ? vl53l8cx_stop_ranging(&sensor) : 0;
    if (!result) {
        ranging = 0;
        result = vl53l8cx_set_power_mode(&sensor, VL53L8CX_POWER_MODE_SLEEP);
    }
    return result;
}
/* 1=new sample, 0=not ready, negative=failure. Preserve raw target status;
 * applications must not turn invalid zones into false zero-distance objects. */
int box_tof_read(int16_t *distance, uint8_t *status, uint8_t *targets) {
    if (!initialized || !ranging) return -ENODEV;
    uint8_t ready = 0;
    int result = vl53l8cx_check_data_ready(&sensor, &ready);
    if (result) return -result;
    if (!ready) return 0;
    VL53L8CX_ResultsData data;
    result = vl53l8cx_get_ranging_data(&sensor, &data);
    if (result) return -result;
    memcpy(distance, data.distance_mm, 64 * sizeof(int16_t));
    memcpy(status, data.target_status, 64);
    memcpy(targets, data.nb_target_detected, 64);
    return 1;
}
