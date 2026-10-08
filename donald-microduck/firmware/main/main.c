// USB UAC2 (speaker + microphone) and CDC-ACM control bridge for the XIAO
// ESP32-S3 soldered onto the ReSpeaker XVF3800 board.
//
// USB side : 16 kHz / 2 ch / S16_LE both ways, asynchronous with explicit
//            feedback (speaker) and packet-size flow control (microphone).
// I2S side : XIAO is master, Philips, 32-bit slots, stereo, 16 kHz.
//            Pair ONLY with the XMOS "I2S slave 16k" firmware.
// Control  : CDC-ACM text commands, JSON replies (see command_help).
//
// Prototype firmware. See README.md for build and hardware test scope.
#include <inttypes.h>
#include <math.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "driver/i2s_std.h"
#include "driver/pulse_cnt.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_private/periph_ctrl.h"
#include "esp_private/usb_phy.h"
#include "hal/usb_serial_jtag_ll.h"
#include "soc/rtc_cntl_reg.h"
#include "esp32s3/rom/rtc.h"
#include "tusb.h"
#include "device/dcd.h"
#include "usb_descriptors.h"

#define FW_VERSION        "xiao-uac2-cdc-0.2"
#define CHUNK_FRAMES      32          // 2 ms of audio per I2S transfer
#define CHUNK_SAMPLES     (CHUNK_FRAMES * AUDIO_CHANNELS)
#define I2S_DMA_FRAMES    32
#define I2S_DMA_DESCS     4
#define XMOS_I2C_ADDR     0x2c
#define VOLUME_MIN_Q8     (-50 * 256) // UAC volume unit is 1/256 dB
#define VOLUME_DEFAULT_Q8 (-20 * 256) // until the host sets one
#define LOG_RING_SIZE     2048

#define PIN_BCLK GPIO_NUM_8
#define PIN_WS   GPIO_NUM_7
#define PIN_DOUT GPIO_NUM_44   // XIAO -> XMOS
#define PIN_DIN  GPIO_NUM_43   // XMOS -> XIAO (also U0TXD: ROM boot log lands here)
#define I2S_PINS ((1ULL << PIN_BCLK) | (1ULL << PIN_WS) | (1ULL << PIN_DOUT) | (1ULL << PIN_DIN))

static const char *TAG = "bridge";

static i2s_chan_handle_t tx_chan, rx_chan;
static i2c_master_bus_handle_t i2c_bus;
static i2c_master_dev_handle_t xmos_dev;
static usb_phy_handle_t usb_phy;
static TaskHandle_t usb_task_handle;
static bool xmos_present;

// I2S master is only driven when nothing else clocks the bus: the XMOS on its
// USB firmware is itself I2S master, and two masters short their drivers.
static atomic_bool i2s_running;
static bool i2s_ext_clock_at_boot;
static uint32_t i2s_probe_bclk_hz;

// XMOS control bus: one mutex serialises the VAD poller and the CDC i2c_* commands.
static SemaphoreHandle_t xmos_lock;

// Voice activity from the XVF3800 (DOA_VALUE speech flag), debounced into
// "wake" / "silence" events that the CDC control task prints as JSON lines.
#define VAD_POLL_MS   100
#define VAD_ON_POLLS  3          // 300 ms of continuous speech before "wake"
static atomic_bool vad_enabled = true;
static atomic_int vad_silence_ms = 30000;
static atomic_bool vad_speech, vad_active;
static atomic_int vad_doa = -1;
static atomic_uint vad_polls, vad_errors, vad_wakes, vad_last_wake_ms;
static atomic_bool evt_wake_pending, evt_silence_pending;
static atomic_int evt_wake_doa;

// Raw 32-bit I2S word statistics over the last full second, for the CDC
// "i2s_peek" command: which bits ever toggle (alignment) and true level.
typedef struct { int32_t min, max; uint32_t or_bits; uint64_t sumsq; } word_stat_t;
static word_stat_t peek_acc[2], peek_last[2];
static uint32_t peek_frames, peek_last_frames;
static int32_t peek_words[16];
static atomic_uint peek_seq;

// Streaming state from the host's alternate-setting changes.
static atomic_bool spk_streaming, mic_streaming;
// Mute is host mute OR CDC mute; volume comes from the host only.
static atomic_bool spk_host_mute, mic_host_mute, spk_cdc_mute, mic_cdc_mute;
static atomic_int spk_volume_q8 = VOLUME_DEFAULT_Q8;
static atomic_int spk_gain_q15;
// Counters for the status command.
static atomic_uint spk_frames, spk_underruns, spk_discarded, spk_fifo_avg, i2s_write_errors;
static atomic_uint mic_frames, mic_drops, i2s_read_errors;
static atomic_uint usb_mounts;

// ---------------------------------------------------------------------------
// Log ring: there is no console (GPIO43/44 belong to I2S), so ESP_LOG goes to
// RAM and is read back with the CDC "log" command.
static char log_ring[LOG_RING_SIZE];
static size_t log_total;
static portMUX_TYPE log_lock = portMUX_INITIALIZER_UNLOCKED;

static int log_to_ring(const char *fmt, va_list ap)
{
    char buf[192];
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    if (n <= 0) return 0;
    if ((size_t)n > sizeof(buf) - 1) n = sizeof(buf) - 1;
    portENTER_CRITICAL(&log_lock);
    for (int i = 0; i < n; ++i) log_ring[(log_total + i) % LOG_RING_SIZE] = buf[i];
    log_total += n;
    portEXIT_CRITICAL(&log_lock);
    return n;
}

static size_t log_snapshot(char *out, size_t cap)
{
    portENTER_CRITICAL(&log_lock);
    size_t have = log_total < LOG_RING_SIZE ? log_total : LOG_RING_SIZE;
    if (have > cap) have = cap;
    size_t start = log_total - have;
    for (size_t i = 0; i < have; ++i) out[i] = log_ring[(start + i) % LOG_RING_SIZE];
    portEXIT_CRITICAL(&log_lock);
    return have;
}

// ---------------------------------------------------------------------------
// Audio path

static void set_speaker_volume(int q8)
{
    if (q8 < VOLUME_MIN_Q8) q8 = VOLUME_MIN_Q8;
    if (q8 > 0) q8 = 0;
    atomic_store(&spk_volume_q8, q8);
    atomic_store(&spk_gain_q15, (int)lroundf(32768.0f * powf(10.0f, (float)q8 / 256.0f / 20.0f)));
}

// Core 1. Drains the USB OUT FIFO into I2S; the blocking I2S write paces the
// loop, the USB feedback endpoint keeps the FIFO near half full.
static void speaker_task(void *arg)
{
    static int16_t pcm[CHUNK_SAMPLES];
    static int32_t raw[CHUNK_SAMPLES];
    bool primed = false;
    for (;;) {
        if (!atomic_load(&spk_streaming)) {
            primed = false;
            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }
        uint16_t avail = tud_audio_available();
        if (!primed) {
            if (avail < AUDIO_FIFO_BYTES / 2) { vTaskDelay(1); continue; }
            primed = true;
        }
        if (avail < sizeof(pcm)) {
            if (avail == 0) { atomic_fetch_add(&spk_underruns, 1); primed = false; }
            vTaskDelay(1);
            continue;
        }
        size_t samples = tud_audio_read(pcm, sizeof(pcm)) / sizeof(int16_t);
        if (!atomic_load(&i2s_running)) {
            // Keep the USB side flowing (feedback stays sane), drop the audio.
            atomic_fetch_add(&spk_discarded, samples / AUDIO_CHANNELS);
            vTaskDelay(1);
            continue;
        }
        bool muted = atomic_load(&spk_host_mute) || atomic_load(&spk_cdc_mute);
        int32_t gain = muted ? 0 : atomic_load(&spk_gain_q15);
        for (size_t i = 0; i < samples; ++i) {
            // Q15 gain leaves a 31-bit result; one more doubling fills the 32-bit slot.
            raw[i] = (pcm[i] * gain) * 2;
        }
        size_t written = 0;
        if (i2s_channel_write(tx_chan, raw, samples * sizeof(int32_t), &written, 100) != ESP_OK) {
            atomic_fetch_add(&i2s_write_errors, 1);
        }
        atomic_fetch_add(&spk_frames, samples / AUDIO_CHANNELS);
    }
}

static void peek_accumulate(const int32_t *raw, size_t samples)
{
    if (peek_frames == 0) {
        for (int ch = 0; ch < 2; ++ch) peek_acc[ch] = (word_stat_t){.min = INT32_MAX, .max = INT32_MIN};
    }
    for (size_t i = 0; i + 1 < samples; i += 2) {
        for (int ch = 0; ch < 2; ++ch) {
            int32_t v = raw[i + ch];
            word_stat_t *st = &peek_acc[ch];
            if (v < st->min) st->min = v;
            if (v > st->max) st->max = v;
            st->or_bits |= (uint32_t)v;
            int64_t q = v >> 8; // keep the sum of squares inside 64 bits over one second
            st->sumsq += (uint64_t)(q * q);
        }
    }
    peek_frames += samples / 2;
    if (peek_frames >= AUDIO_SAMPLE_RATE) {
        atomic_fetch_add(&peek_seq, 1); // odd: writer busy
        peek_last[0] = peek_acc[0];
        peek_last[1] = peek_acc[1];
        peek_last_frames = peek_frames;
        memcpy(peek_words, raw, sizeof(peek_words));
        atomic_fetch_add(&peek_seq, 1); // even: consistent
        peek_frames = 0;
    }
}

// Core 1. Always drains I2S RX so the DMA never overruns; forwards to USB only
// while the host has the microphone interface open and the FIFO has room.
static void mic_task(void *arg)
{
    static int32_t raw[CHUNK_SAMPLES];
    static int16_t pcm[CHUNK_SAMPLES];
    for (;;) {
        size_t samples;
        if (!atomic_load(&i2s_running)) {
            // No I2S: pace 2 ms of silence so an open capture stream keeps running.
            vTaskDelay(pdMS_TO_TICKS(2));
            if (!atomic_load(&mic_streaming)) continue;
            samples = CHUNK_SAMPLES;
            memset(pcm, 0, sizeof(pcm));
        } else {
            size_t got = 0;
            if (i2s_channel_read(rx_chan, raw, sizeof(raw), &got, 100) != ESP_OK) {
                atomic_fetch_add(&i2s_read_errors, 1);
                continue;
            }
            samples = got / sizeof(int32_t);
            bool muted = atomic_load(&mic_host_mute) || atomic_load(&mic_cdc_mute);
            for (size_t i = 0; i < samples; ++i) pcm[i] = muted ? 0 : (int16_t)(raw[i] >> 16);
            atomic_fetch_add(&mic_frames, samples / AUDIO_CHANNELS);
            peek_accumulate(raw, samples);
            if (!atomic_load(&mic_streaming)) continue;
        }
        tu_fifo_t *ff = tud_audio_get_ep_in_ff();
        uint16_t bytes = samples * sizeof(int16_t);
        if (ff && tu_fifo_remaining(ff) >= bytes) tud_audio_write(pcm, bytes);
        else atomic_fetch_add(&mic_drops, 1);
    }
}

// Leave all four I2S pins as plain inputs so nothing on the bus is driven.
static void i2s_release_pins(void)
{
    gpio_config_t in = {.pin_bit_mask = I2S_PINS, .mode = GPIO_MODE_INPUT};
    gpio_config(&in);
}

// Measure BCLK with the pulse counter for 2 ms (rising edges * 500 = Hz), weak
// pull-down on the line so a floating bus reads 0 Hz.  Any I2S master gives
// hundreds of kHz; the first build polled GPIO in software and under-counted
// a real clock (960 "edges" in 20 ms), which is why hardware counting.
static uint32_t measure_bclk_hz(void)
{
    pcnt_unit_config_t ucfg = {.low_limit = -1, .high_limit = 32767};
    pcnt_unit_handle_t unit = NULL;
    pcnt_channel_handle_t chan = NULL;
    uint32_t hz = 0;
    if (pcnt_new_unit(&ucfg, &unit) != ESP_OK) return 0;
    pcnt_chan_config_t ccfg = {.edge_gpio_num = PIN_BCLK, .level_gpio_num = -1};
    if (pcnt_new_channel(unit, &ccfg, &chan) == ESP_OK) {
        pcnt_channel_set_edge_action(chan, PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_HOLD);
        pcnt_channel_set_level_action(chan, PCNT_CHANNEL_LEVEL_ACTION_KEEP, PCNT_CHANNEL_LEVEL_ACTION_KEEP);
        gpio_pullup_dis(PIN_BCLK);
        gpio_pulldown_en(PIN_BCLK);
        pcnt_unit_enable(unit);
        pcnt_unit_clear_count(unit);
        esp_rom_delay_us(200);
        pcnt_unit_start(unit);
        esp_rom_delay_us(2000);
        pcnt_unit_stop(unit);
        int count = 0;
        pcnt_unit_get_count(unit, &count);
        hz = (uint32_t)count * 500;
        pcnt_unit_disable(unit);
        pcnt_del_channel(chan);
    }
    pcnt_del_unit(unit);
    i2s_release_pins();
    return hz;
}

static bool external_i2s_clock_present(void)
{
    i2s_probe_bclk_hz = measure_bclk_hz();
    return i2s_probe_bclk_hz > 50000;
}

static bool i2s_start(void)
{
    if (atomic_load(&i2s_running)) return true;
    i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan.dma_desc_num = I2S_DMA_DESCS;
    chan.dma_frame_num = I2S_DMA_FRAMES;
    chan.auto_clear = true; // zeros on underrun instead of repeating stale data
    i2s_std_config_t std = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(AUDIO_SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED, .bclk = PIN_BCLK, .ws = PIN_WS, .dout = PIN_DOUT, .din = PIN_DIN,
        },
    };
    esp_err_t err = i2s_new_channel(&chan, &tx_chan, &rx_chan);
    if (err == ESP_OK) err = i2s_channel_init_std_mode(tx_chan, &std);
    if (err == ESP_OK) err = i2s_channel_init_std_mode(rx_chan, &std);
    if (err == ESP_OK) err = i2s_channel_enable(tx_chan);
    if (err == ESP_OK) err = i2s_channel_enable(rx_chan);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s start failed: %s", esp_err_to_name(err));
        if (tx_chan) { i2s_del_channel(tx_chan); tx_chan = NULL; }
        if (rx_chan) { i2s_del_channel(rx_chan); rx_chan = NULL; }
        i2s_release_pins();
        return false;
    }
    atomic_store(&i2s_running, true);
    ESP_LOGI(TAG, "i2s master running");
    return true;
}

static void i2s_stop(void)
{
    if (!atomic_load(&i2s_running)) { i2s_release_pins(); return; }
    atomic_store(&i2s_running, false);
    vTaskDelay(pdMS_TO_TICKS(250)); // let in-flight 100 ms reads/writes return
    i2s_channel_disable(tx_chan);
    i2s_channel_disable(rx_chan);
    i2s_del_channel(tx_chan);
    i2s_del_channel(rx_chan);
    tx_chan = rx_chan = NULL;
    i2s_release_pins();
    ESP_LOGI(TAG, "i2s stopped, pins released");
}

// ---------------------------------------------------------------------------
// XMOS control protocol over I2C

// Read: header [resid, cmd|0x80, len+1], then re-read (separate transactions)
// until the status byte stops saying RETRY (64). Returns the status byte
// (0 = OK), -1 on bus error; payload (len bytes) goes to out. Caller holds xmos_lock.
static int xmos_read_locked(uint8_t resid, uint8_t cmd, uint8_t len, uint8_t *out)
{
    uint8_t hdr[3] = {resid, (uint8_t)(cmd | 0x80), (uint8_t)(len + 1)};
    uint8_t rx[65];
    if (len > 64 || !xmos_dev || i2c_master_transmit(xmos_dev, hdr, 3, 50) != ESP_OK) return -1;
    for (int tries = 0; tries < 20; ++tries) {
        vTaskDelay(pdMS_TO_TICKS(2));
        if (i2c_master_receive(xmos_dev, rx, len + 1, 50) != ESP_OK) return -1;
        if (rx[0] != 64) {
            memcpy(out, rx + 1, len);
            return rx[0];
        }
    }
    return 64;
}

// Core 0. Polls DOA_VALUE (resid 20, cmd 18: uint16 doa, uint16 speech) at 10 Hz.
static void vad_task(void *arg)
{
    (void)arg;
    int speech_run = 0;
    int64_t last_speech_us = 0;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(VAD_POLL_MS));
        if (!xmos_dev || !atomic_load(&vad_enabled)) continue;
        uint8_t p[4];
        xSemaphoreTake(xmos_lock, portMAX_DELAY);
        int st = xmos_read_locked(20, 18, 4, p);
        xSemaphoreGive(xmos_lock);
        atomic_fetch_add(&vad_polls, 1);
        if (st != 0) { atomic_fetch_add(&vad_errors, 1); continue; }
        int doa = p[0] | (p[1] << 8);
        bool speech = (p[2] | (p[3] << 8)) != 0;
        atomic_store(&vad_speech, speech);
        if (speech) atomic_store(&vad_doa, doa);
        int64_t now = esp_timer_get_time();
        if (speech) {
            last_speech_us = now;
            if (++speech_run >= VAD_ON_POLLS && !atomic_load(&vad_active)) {
                atomic_store(&vad_active, true);
                atomic_store(&evt_wake_doa, doa);
                atomic_store(&evt_wake_pending, true);
                atomic_fetch_add(&vad_wakes, 1);
                atomic_store(&vad_last_wake_ms, (unsigned)(now / 1000));
            }
        } else {
            speech_run = 0;
            if (atomic_load(&vad_active) && now - last_speech_us > (int64_t)atomic_load(&vad_silence_ms) * 1000) {
                atomic_store(&vad_active, false);
                atomic_store(&evt_silence_pending, true);
            }
        }
    }
}

// ---------------------------------------------------------------------------
// TinyUSB callbacks (run inside tud_task on core 0, except the *_isr ones)

void tud_mount_cb(void)
{
    // A fresh configuration starts with both streaming interfaces at alt 0.
    atomic_store(&spk_streaming, false);
    atomic_store(&mic_streaming, false);
    atomic_fetch_add(&usb_mounts, 1);
    ESP_LOGI(TAG, "usb mounted");
}

void tud_umount_cb(void)
{
    atomic_store(&spk_streaming, false);
    atomic_store(&mic_streaming, false);
    ESP_LOGI(TAG, "usb unmounted");
}

bool tud_audio_set_itf_cb(uint8_t rhport, tusb_control_request_t const *req)
{
    (void)rhport;
    uint8_t itf = tu_u16_low(req->wIndex), alt = tu_u16_low(req->wValue);
    if (itf == ITF_NUM_AUDIO_STREAMING_SPK) atomic_store(&spk_streaming, alt != 0);
    if (itf == ITF_NUM_AUDIO_STREAMING_MIC) atomic_store(&mic_streaming, alt != 0);
    ESP_LOGI(TAG, "set itf %u alt %u", itf, alt);
    return true;
}

bool tud_audio_set_itf_close_ep_cb(uint8_t rhport, tusb_control_request_t const *req)
{
    (void)rhport;
    uint8_t itf = tu_u16_low(req->wIndex);
    if (itf == ITF_NUM_AUDIO_STREAMING_SPK) atomic_store(&spk_streaming, false);
    if (itf == ITF_NUM_AUDIO_STREAMING_MIC) atomic_store(&mic_streaming, false);
    return true;
}

void tud_audio_feedback_params_cb(uint8_t func_id, uint8_t alt_itf, audio_feedback_params_t *p)
{
    (void)func_id; (void)alt_itf;
    p->method = AUDIO_FEEDBACK_METHOD_FIFO_COUNT;
    p->sample_freq = AUDIO_SAMPLE_RATE;
}

bool tud_audio_rx_done_isr(uint8_t rhport, uint16_t n_bytes_received, uint8_t func_id,
                           uint8_t ep_out, uint8_t cur_alt_setting)
{
    (void)rhport; (void)n_bytes_received; (void)func_id; (void)ep_out; (void)cur_alt_setting;
    // Smoothed OUT FIFO level, status only.
    unsigned avg = atomic_load(&spk_fifo_avg);
    atomic_store(&spk_fifo_avg, (avg * 15 + tud_audio_available()) / 16);
    return true;
}

#define CONTROL_REPLY(rhport, req, value) \
    tud_audio_buffer_and_schedule_control_xfer(rhport, (tusb_control_request_t const *)(req), &(value), sizeof(value))

// Clock 0x04: fixed 16 kHz, frequency read-only, always valid.
static bool clock_get(uint8_t rhport, audio_control_request_t const *req)
{
    if (req->bControlSelector == AUDIO_CS_CTRL_SAM_FREQ) {
        if (req->bRequest == AUDIO_CS_REQ_CUR) {
            audio_control_cur_4_t cur = {.bCur = AUDIO_SAMPLE_RATE};
            return CONTROL_REPLY(rhport, req, cur);
        }
        if (req->bRequest == AUDIO_CS_REQ_RANGE) {
            audio_control_range_4_n_t(1) range = {
                .wNumSubRanges = 1,
                .subrange[0] = {.bMin = AUDIO_SAMPLE_RATE, .bMax = AUDIO_SAMPLE_RATE, .bRes = 0},
            };
            return CONTROL_REPLY(rhport, req, range);
        }
    } else if (req->bControlSelector == AUDIO_CS_CTRL_CLK_VALID && req->bRequest == AUDIO_CS_REQ_CUR) {
        audio_control_cur_1_t cur = {.bCur = 1};
        return CONTROL_REPLY(rhport, req, cur);
    }
    return false;
}

static bool mute_get(uint8_t rhport, audio_control_request_t const *req, atomic_bool *mute)
{
    if (req->bControlSelector != AUDIO_FU_CTRL_MUTE || req->bRequest != AUDIO_CS_REQ_CUR) return false;
    audio_control_cur_1_t cur = {.bCur = atomic_load(mute)};
    return CONTROL_REPLY(rhport, req, cur);
}

static bool speaker_fu_get(uint8_t rhport, audio_control_request_t const *req)
{
    if (req->bControlSelector == AUDIO_FU_CTRL_MUTE) return mute_get(rhport, req, &spk_host_mute);
    if (req->bControlSelector != AUDIO_FU_CTRL_VOLUME) return false;
    if (req->bRequest == AUDIO_CS_REQ_CUR) {
        audio_control_cur_2_t cur = {.bCur = (int16_t)atomic_load(&spk_volume_q8)};
        return CONTROL_REPLY(rhport, req, cur);
    }
    if (req->bRequest == AUDIO_CS_REQ_RANGE) {
        audio_control_range_2_n_t(1) range = {
            .wNumSubRanges = 1,
            .subrange[0] = {.bMin = VOLUME_MIN_Q8, .bMax = 0, .bRes = 256},
        };
        return CONTROL_REPLY(rhport, req, range);
    }
    return false;
}

bool tud_audio_get_req_entity_cb(uint8_t rhport, tusb_control_request_t const *p_request)
{
    audio_control_request_t const *req = (audio_control_request_t const *)p_request;
    switch (req->bEntityID) {
    case UAC2_ENTITY_CLOCK:            return clock_get(rhport, req);
    case UAC2_ENTITY_SPK_FEATURE_UNIT: return speaker_fu_get(rhport, req);
    case UAC2_ENTITY_MIC_FEATURE_UNIT: return mute_get(rhport, req, &mic_host_mute);
    default:                           return false; // stall
    }
}

// Called after the data stage; buf holds wLength bytes from the host.
bool tud_audio_set_req_entity_cb(uint8_t rhport, tusb_control_request_t const *p_request, uint8_t *buf)
{
    (void)rhport;
    audio_control_request_t const *req = (audio_control_request_t const *)p_request;
    if (req->bRequest != AUDIO_CS_REQ_CUR) return false;
    switch (req->bEntityID) {
    case UAC2_ENTITY_CLOCK:
        // The only rate is 16 kHz; anything else is refused with a stall.
        return req->bControlSelector == AUDIO_CS_CTRL_SAM_FREQ && req->wLength == 4 &&
               tu_unaligned_read32(buf) == AUDIO_SAMPLE_RATE;
    case UAC2_ENTITY_SPK_FEATURE_UNIT:
        if (req->bControlSelector == AUDIO_FU_CTRL_MUTE && req->wLength == 1) {
            atomic_store(&spk_host_mute, buf[0] != 0);
            return true;
        }
        if (req->bControlSelector == AUDIO_FU_CTRL_VOLUME && req->wLength == 2) {
            set_speaker_volume((int16_t)tu_unaligned_read16(buf));
            return true;
        }
        return false;
    case UAC2_ENTITY_MIC_FEATURE_UNIT:
        if (req->bControlSelector == AUDIO_FU_CTRL_MUTE && req->wLength == 1) {
            atomic_store(&mic_host_mute, buf[0] != 0);
            return true;
        }
        return false;
    default:
        return false;
    }
}

// Core 0. Owns the USB PHY and the TinyUSB device stack.
static void usb_task(void *arg)
{
    (void)arg;
    usb_phy_config_t phy_cfg = {
        .controller = USB_PHY_CTRL_OTG,
        .target = USB_PHY_TARGET_INT,
        .otg_mode = USB_OTG_MODE_DEVICE,
        .otg_speed = USB_PHY_SPEED_FULL,
    };
    ESP_ERROR_CHECK(usb_new_phy(&phy_cfg, &usb_phy));
    tusb_rhport_init_t dev_init = {.role = TUSB_ROLE_DEVICE, .speed = TUSB_SPEED_FULL};
    if (!tusb_init(0, &dev_init)) {
        ESP_LOGE(TAG, "tusb_init failed");
        vTaskDelete(NULL);
    }
    ESP_LOGI(TAG, "usb started");
    for (;;) tud_task();
}

// ---------------------------------------------------------------------------
// CDC control port

static void reply(const char *text)
{
    // Only this task uses CDC TX; drop a reply if the host is not reading.
    size_t len = strlen(text);
    if (tud_cdc_connected() && tud_cdc_write_available() >= len) {
        tud_cdc_write(text, len);
        tud_cdc_write_flush();
    }
}

// For payloads larger than the CDC TX buffer; gives up after ~1 s of no drain.
static void reply_chunked(const char *data, size_t len)
{
    int idle = 0;
    while (len && tud_cdc_connected() && idle < 200) {
        uint32_t room = tud_cdc_write_available();
        if (!room) { vTaskDelay(pdMS_TO_TICKS(5)); ++idle; continue; }
        uint32_t n = room < len ? room : len;
        tud_cdc_write(data, n);
        tud_cdc_write_flush();
        data += n; len -= n; idle = 0;
    }
}

static void detach_usb(void)
{
    tud_disconnect();
    vTaskDelay(pdMS_TO_TICKS(100));
    vTaskSuspend(usb_task_handle);
    dcd_int_disable(0);
}

static void command_reboot(void)
{
    reply("{\"ok\":true,\"action\":\"reboot\"}\n");
    vTaskDelay(pdMS_TO_TICKS(50));
    detach_usb();
    // Keep the ROM's boot log off GPIO43 (it is XMOS I2S data in this design).
    rtc_suppress_rom_log();
    esp_restart();
}

static void command_bootloader(void)
{
    reply("{\"ok\":true,\"action\":\"bootloader\",\"hint\":\"esptool over USB-Serial-JTAG; BOOT+RESET if this fails\"}\n");
    vTaskDelay(pdMS_TO_TICKS(50));
    detach_usb();
    usb_del_phy(usb_phy);
    // ROM download mode speaks USB-Serial-JTAG: hand the internal PHY back to it.
    PERIPH_RCC_ATOMIC() {
        usb_serial_jtag_ll_enable_bus_clock(true);
    }
    usb_serial_jtag_ll_phy_enable_external(false);
    usb_serial_jtag_ll_phy_enable_pad(true);
    // Same flag esp_restart() honours for "idf.py monitor" style reboots into download mode.
    REG_WRITE(RTC_CNTL_OPTION1_REG, RTC_CNTL_FORCE_DOWNLOAD_BOOT);
    esp_restart();
}

static void command_status(void)
{
    char out[960];
    snprintf(out, sizeof(out),
             "{\"firmware\":\"%s\",\"rate\":%d,\"channels\":%d,\"uptime_ms\":%" PRId64 ","
             "\"usb\":{\"mounted\":%s,\"suspended\":%s,\"mounts\":%u,\"cdc_connected\":%s},"
             "\"speaker\":{\"streaming\":%s,\"host_mute\":%s,\"cdc_mute\":%s,\"volume_q8\":%d,"
             "\"gain_q15\":%d,\"fifo_avg\":%u,\"fifo_depth\":%d,\"underruns\":%u,\"frames\":%u,\"discarded\":%u,\"i2s_errors\":%u},"
             "\"mic\":{\"streaming\":%s,\"host_mute\":%s,\"cdc_mute\":%s,\"drops\":%u,\"frames\":%u,\"i2s_errors\":%u},"
             "\"i2s\":{\"running\":%s,\"ext_clock_at_boot\":%s,\"probe_bclk_hz\":%" PRIu32 "},"
             "\"vad\":{\"enabled\":%s,\"active\":%s,\"speech\":%s,\"doa\":%d,\"wakes\":%u,\"last_wake_ms\":%u,"
             "\"polls\":%u,\"errors\":%u,\"silence_ms\":%d},"
             "\"xmos_i2c\":%s}\n",
             FW_VERSION, AUDIO_SAMPLE_RATE, AUDIO_CHANNELS, esp_timer_get_time() / 1000,
             tud_mounted() ? "true" : "false", tud_suspended() ? "true" : "false",
             atomic_load(&usb_mounts), tud_cdc_connected() ? "true" : "false",
             atomic_load(&spk_streaming) ? "true" : "false", atomic_load(&spk_host_mute) ? "true" : "false",
             atomic_load(&spk_cdc_mute) ? "true" : "false", atomic_load(&spk_volume_q8),
             atomic_load(&spk_gain_q15), atomic_load(&spk_fifo_avg), AUDIO_FIFO_BYTES,
             atomic_load(&spk_underruns), atomic_load(&spk_frames), atomic_load(&spk_discarded),
             atomic_load(&i2s_write_errors),
             atomic_load(&mic_streaming) ? "true" : "false", atomic_load(&mic_host_mute) ? "true" : "false",
             atomic_load(&mic_cdc_mute) ? "true" : "false", atomic_load(&mic_drops),
             atomic_load(&mic_frames), atomic_load(&i2s_read_errors),
             atomic_load(&i2s_running) ? "true" : "false", i2s_ext_clock_at_boot ? "true" : "false", i2s_probe_bclk_hz,
             atomic_load(&vad_enabled) ? "true" : "false", atomic_load(&vad_active) ? "true" : "false",
             atomic_load(&vad_speech) ? "true" : "false", atomic_load(&vad_doa), atomic_load(&vad_wakes),
             atomic_load(&vad_last_wake_ms), atomic_load(&vad_polls), atomic_load(&vad_errors), atomic_load(&vad_silence_ms),
             xmos_present ? "true" : "false");
    reply(out);
}

static void command_log(void)
{
    static char snap[LOG_RING_SIZE];
    size_t n = log_snapshot(snap, sizeof(snap));
    reply_chunked(snap, n);
    reply("\n{\"ok\":true,\"log_end\":true}\n");
}

static int hex_nibble(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

// Parses "<hex bytes> [decimal]" into tx/ntx and nrx; returns false on bad input.
static bool parse_hex_args(const char *args, uint8_t *tx, size_t cap, size_t *ntx, long *nrx)
{
    *ntx = 0;
    while (*args && *args != ' ') {
        int hi = hex_nibble(args[0]), lo = args[1] ? hex_nibble(args[1]) : -1;
        if (hi < 0 || lo < 0 || *ntx == cap) return false;
        tx[(*ntx)++] = (uint8_t)(hi << 4 | lo);
        args += 2;
    }
    *nrx = *args ? strtol(args, NULL, 10) : 0;
    return *ntx > 0 && *nrx >= 0 && *nrx <= 64;
}

static void reply_hex(const char *prefix, const uint8_t *rx, long nrx, const char *suffix)
{
    char out[240];
    size_t pos = snprintf(out, sizeof(out), "%s", prefix);
    for (long i = 0; i < nrx && pos + 4 < sizeof(out); ++i) pos += snprintf(out + pos, sizeof(out) - pos, "%02x", rx[i]);
    snprintf(out + pos, sizeof(out) - pos, "%s", suffix);
    reply(out);
}

// i2c_txrx <hex bytes to write> [bytes to read]: raw passthrough to the XMOS at
// 0x2c, write then read in one transaction. Nothing here is interpreted.
static void command_i2c_txrx(const char *args)
{
    uint8_t tx[32], rx[64];
    char out[120];
    size_t ntx; long nrx;
    if (!xmos_dev) { reply("{\"error\":\"xmos not present on i2c\"}\n"); return; }
    if (!parse_hex_args(args, tx, sizeof(tx), &ntx, &nrx)) { reply("{\"error\":\"usage: i2c_txrx <hex> [nread<=64]\"}\n"); return; }
    xSemaphoreTake(xmos_lock, portMAX_DELAY);
    esp_err_t err = nrx ? i2c_master_transmit_receive(xmos_dev, tx, ntx, rx, nrx, 100)
                        : i2c_master_transmit(xmos_dev, tx, ntx, 100);
    xSemaphoreGive(xmos_lock);
    if (err != ESP_OK) {
        snprintf(out, sizeof(out), "{\"error\":\"i2c %s\"}\n", esp_err_to_name(err));
        reply(out);
        return;
    }
    reply_hex("{\"ok\":true,\"rx\":\"", rx, nrx, "\"}\n");
}

// i2c_read <hex header> <nread>: XMOS control-protocol read. Header is
// [resid, cmdid|0x80, len+1]; the device answers [status, payload...] and says
// RETRY (64) until the value is ready, so the read is repeated (separate
// transactions) until the status changes.
static void command_i2c_read(const char *args)
{
    uint8_t tx[8], rx[64];
    char out[120];
    size_t ntx; long nrx;
    if (!xmos_dev) { reply("{\"error\":\"xmos not present on i2c\"}\n"); return; }
    if (!parse_hex_args(args, tx, sizeof(tx), &ntx, &nrx) || nrx < 1) { reply("{\"error\":\"usage: i2c_read <hex header> <nread 1..64>\"}\n"); return; }
    xSemaphoreTake(xmos_lock, portMAX_DELAY);
    esp_err_t err = i2c_master_transmit(xmos_dev, tx, ntx, 100);
    int tries = 0;
    while (err == ESP_OK && tries < 50) {
        vTaskDelay(pdMS_TO_TICKS(2));
        err = i2c_master_receive(xmos_dev, rx, nrx, 100);
        ++tries;
        if (err == ESP_OK && rx[0] != 64) break;
    }
    xSemaphoreGive(xmos_lock);
    if (err != ESP_OK) {
        snprintf(out, sizeof(out), "{\"error\":\"i2c %s\",\"tries\":%d}\n", esp_err_to_name(err), tries);
        reply(out);
        return;
    }
    snprintf(out, sizeof(out), "{\"ok\":%s,\"status\":%u,\"tries\":%d,\"rx\":\"", rx[0] == 0 ? "true" : "false", rx[0], tries);
    reply_hex(out, rx, nrx, "\"}\n");
}

static void command_help(void)
{
    reply("{\"commands\":[\"ping\",\"status\",\"mic_mute 0|1\",\"speaker_mute 0|1\",\"i2s_on\",\"i2s_off\",\"i2s_peek\","
          "\"vad 0|1\",\"vad_silence <ms>\",\"log\",\"i2c_txrx <hex> [nread]\",\"i2c_read <hex header> <nread>\","
          "\"reboot\",\"bootloader\",\"help\"],\"events\":[\"{\\\"event\\\":\\\"wake\\\",\\\"doa\\\":N}\",\"{\\\"event\\\":\\\"silence\\\"}\"]}\n");
}

// i2s_on forces the master on even if a clock was seen at boot: only for when
// the operator knows the XMOS runs the I2S slave firmware.
static void command_i2s(bool on)
{
    if (on) {
        bool ext = external_i2s_clock_present();
        if (ext) ESP_LOGW(TAG, "i2s_on forced with an external clock present (%" PRIu32 " Hz)", i2s_probe_bclk_hz);
        bool ok = i2s_start();
        char out[160];
        snprintf(out, sizeof(out), "{\"ok\":%s,\"i2s_running\":%s,\"external_clock_seen\":%s,\"probe_bclk_hz\":%" PRIu32 "}\n",
                 ok ? "true" : "false", atomic_load(&i2s_running) ? "true" : "false", ext ? "true" : "false", i2s_probe_bclk_hz);
        reply(out);
    } else {
        i2s_stop();
        reply("{\"ok\":true,\"i2s_running\":false}\n");
    }
}

// Statistics of the raw 32-bit I2S words over the last second, plus the first
// 8 frames of the newest chunk.  "or" shows which bits ever carry data.
static void command_i2s_peek(void)
{
    word_stat_t st[2];
    int32_t words[16];
    uint32_t frames, seq;
    do {
        seq = atomic_load(&peek_seq);
        st[0] = peek_last[0]; st[1] = peek_last[1];
        frames = peek_last_frames;
        memcpy(words, peek_words, sizeof(words));
    } while ((seq & 1) || seq != atomic_load(&peek_seq));
    if (!frames) { reply("{\"error\":\"no I2S data yet\"}\n"); return; }
    char out[640];
    size_t pos = snprintf(out, sizeof(out), "{\"frames\":%" PRIu32 ",\"i2s_running\":%s",
                          frames, atomic_load(&i2s_running) ? "true" : "false");
    for (int ch = 0; ch < 2; ++ch) {
        double rms32 = sqrt((double)st[ch].sumsq / frames) * 256.0;
        pos += snprintf(out + pos, sizeof(out) - pos,
                        ",\"%s\":{\"min\":%" PRId32 ",\"max\":%" PRId32 ",\"or\":\"0x%08" PRIx32 "\",\"rms32\":%.0f,\"rms_dbfs\":%.1f}",
                        ch ? "R" : "L", st[ch].min, st[ch].max, st[ch].or_bits, rms32,
                        rms32 > 0 ? 20.0 * log10(rms32 / 2147483648.0) : -999.0);
    }
    pos += snprintf(out + pos, sizeof(out) - pos, ",\"words\":[");
    for (int i = 0; i < 16 && pos + 14 < sizeof(out); ++i)
        pos += snprintf(out + pos, sizeof(out) - pos, "%s\"0x%08" PRIx32 "\"", i ? "," : "", (uint32_t)words[i]);
    snprintf(out + pos, sizeof(out) - pos, "]}\n");
    reply(out);
}

static void command(const char *line)
{
    if (!strcmp(line, "ping")) reply("{\"ok\":true,\"reply\":\"pong\"}\n");
    else if (!strcmp(line, "status")) command_status();
    else if (!strcmp(line, "i2s_peek")) command_i2s_peek();
    else if (!strcmp(line, "log")) command_log();
    else if (!strcmp(line, "help")) command_help();
    else if (!strcmp(line, "i2s_on")) command_i2s(true);
    else if (!strcmp(line, "i2s_off")) command_i2s(false);
    else if (!strcmp(line, "reboot")) command_reboot();
    else if (!strcmp(line, "bootloader")) command_bootloader();
    else if (!strncmp(line, "i2c_txrx ", 9)) command_i2c_txrx(line + 9);
    else if (!strncmp(line, "i2c_read ", 9)) command_i2c_read(line + 9);
    else if (!strcmp(line, "vad 1") || !strcmp(line, "vad 0")) {
        atomic_store(&vad_enabled, line[4] == '1');
        if (line[4] == '0') atomic_store(&vad_active, false);
        reply("{\"ok\":true}\n");
    } else if (!strncmp(line, "vad_silence ", 12)) {
        long ms = strtol(line + 12, NULL, 10);
        if (ms < 1000 || ms > 600000) reply("{\"error\":\"vad_silence 1000..600000 ms\"}\n");
        else { atomic_store(&vad_silence_ms, (int)ms); reply("{\"ok\":true}\n"); }
    }
    else if (!strcmp(line, "mic_mute 1") || !strcmp(line, "mic_mute 0")) {
        atomic_store(&mic_cdc_mute, line[9] == '1');
        reply("{\"ok\":true}\n");
    } else if (!strcmp(line, "speaker_mute 1") || !strcmp(line, "speaker_mute 0")) {
        atomic_store(&spk_cdc_mute, line[13] == '1');
        reply("{\"ok\":true}\n");
    } else reply("{\"error\":\"unknown command; try help\"}\n");
}

static void init_i2c(void)
{
    i2c_master_bus_config_t bus = {
        .i2c_port = I2C_NUM_0, .sda_io_num = GPIO_NUM_5, .scl_io_num = GPIO_NUM_6,
        .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus, &i2c_bus));
    // XMOS boots its own codec over this bus; we only look for its control address.
    for (int i = 0; i < 20 && !xmos_present; ++i) {
        if (i2c_master_probe(i2c_bus, XMOS_I2C_ADDR, 50) == ESP_OK) xmos_present = true;
        else vTaskDelay(pdMS_TO_TICKS(100));
    }
    if (xmos_present) {
        i2c_device_config_t dev = {
            .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = XMOS_I2C_ADDR, .scl_speed_hz = 100000,
        };
        ESP_ERROR_CHECK(i2c_master_bus_add_device(i2c_bus, &dev, &xmos_dev));
    }
    ESP_LOGI(TAG, "xmos on i2c 0x%02x: %s", XMOS_I2C_ADDR, xmos_present ? "yes" : "no");
}

// Core 0. Probes I2C once, then serves line-oriented CDC commands.
static void control_task(void *arg)
{
    (void)arg;
    init_i2c();
    char line[128];
    size_t count = 0;
    bool overflow = false;
    for (;;) {
        if (!tud_cdc_connected()) { count = 0; overflow = false; }
        while (tud_cdc_connected() && tud_cdc_available()) {
            char c;
            if (tud_cdc_read(&c, 1) != 1) break;
            if (c == '\n') {
                line[count] = 0;
                if (overflow) reply("{\"error\":\"line too long\"}\n");
                else if (count) command(line);
                count = 0; overflow = false;
            } else if (c != '\r') {
                if (count + 1 < sizeof(line)) line[count++] = c;
                else overflow = true;
            }
        }
        // Unsolicited events from the VAD poller (single CDC writer stays this task).
        if (atomic_exchange(&evt_wake_pending, false)) {
            char ev[96];
            snprintf(ev, sizeof(ev), "{\"event\":\"wake\",\"doa\":%d,\"uptime_ms\":%" PRId64 "}\n",
                     atomic_load(&evt_wake_doa), esp_timer_get_time() / 1000);
            reply(ev);
        }
        if (atomic_exchange(&evt_silence_pending, false)) {
            char ev[64];
            snprintf(ev, sizeof(ev), "{\"event\":\"silence\",\"uptime_ms\":%" PRId64 "}\n", esp_timer_get_time() / 1000);
            reply(ev);
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}

void app_main(void)
{
    esp_log_set_vprintf(log_to_ring);
    ESP_LOGI(TAG, "%s, reset reason %d", FW_VERSION, (int)esp_reset_reason());
    set_speaker_volume(VOLUME_DEFAULT_Q8);
    xmos_lock = xSemaphoreCreateMutex();
    ESP_ERROR_CHECK(xmos_lock ? ESP_OK : ESP_ERR_NO_MEM);
    i2s_ext_clock_at_boot = external_i2s_clock_present();
    if (i2s_ext_clock_at_boot) {
        ESP_LOGW(TAG, "BCLK already clocked at %" PRIu32 " Hz: another I2S master is on the bus "
                      "(XMOS on USB firmware?), I2S stays off; use i2s_on to override", i2s_probe_bclk_hz);
    } else {
        i2s_start();
    }
    ESP_ERROR_CHECK(xTaskCreatePinnedToCore(usb_task, "usb", 4096, NULL, 5, &usb_task_handle, 0) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(xTaskCreatePinnedToCore(speaker_task, "spk", 4096, NULL, 6, NULL, 1) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(xTaskCreatePinnedToCore(mic_task, "mic", 4096, NULL, 6, NULL, 1) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(xTaskCreatePinnedToCore(control_task, "cdc", 6144, NULL, 3, NULL, 0) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(xTaskCreatePinnedToCore(vad_task, "vad", 3072, NULL, 2, NULL, 0) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM);
}
