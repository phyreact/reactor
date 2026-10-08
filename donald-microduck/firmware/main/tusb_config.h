// TinyUSB configuration for the XIAO ESP32-S3 UAC2 + CDC bridge.
// Injected into the espressif/tinyusb component by main/CMakeLists.txt.
#pragma once

#include "usb_descriptors.h"

#ifdef __cplusplus
extern "C" {
#endif

#define CFG_TUSB_OS                 OPT_OS_FREERTOS
#define CFG_TUSB_DEBUG              0
#define CFG_TUD_ENABLED             1
#define CFG_TUD_MAX_SPEED           OPT_MODE_FULL_SPEED
#define CFG_TUD_ENDPOINT0_SIZE      64

#define CFG_TUD_CDC                 1
#define CFG_TUD_MSC                 0
#define CFG_TUD_HID                 0
#define CFG_TUD_MIDI                0
#define CFG_TUD_AUDIO               1
#define CFG_TUD_VENDOR              0

// CDC control port: short text commands in, JSON lines out.
#define CFG_TUD_CDC_RX_BUFSIZE      256
#define CFG_TUD_CDC_TX_BUFSIZE      1024
#define CFG_TUD_CDC_EP_BUFSIZE      64

// UAC2: one function, speaker (OUT + feedback) and microphone (IN).
#define CFG_TUD_AUDIO_FUNC_1_DESC_LEN        TUD_AUDIO_BRIDGE_DESC_LEN
#define CFG_TUD_AUDIO_FUNC_1_CTRL_BUF_SZ     64

#define CFG_TUD_AUDIO_ENABLE_EP_IN           1
#define CFG_TUD_AUDIO_FUNC_1_EP_IN_SZ_MAX    AUDIO_EP_SIZE
#define CFG_TUD_AUDIO_FUNC_1_EP_IN_SW_BUF_SZ AUDIO_FIFO_BYTES
#define CFG_TUD_AUDIO_EP_IN_FLOW_CONTROL     1

#define CFG_TUD_AUDIO_ENABLE_EP_OUT           1
#define CFG_TUD_AUDIO_FUNC_1_EP_OUT_SZ_MAX    AUDIO_EP_SIZE
#define CFG_TUD_AUDIO_FUNC_1_EP_OUT_SW_BUF_SZ AUDIO_FIFO_BYTES

// Asynchronous speaker: FIFO-level feedback. On full speed TinyUSB converts the
// internal 16.16 value to 10.14 in 3 bytes, which macOS requires and Linux
// accepts (v0.2 sent 16.16/4: macOS stopped the stream after ~60 packets).
// Windows would need 16.16/4 and is not a target host.
#define CFG_TUD_AUDIO_ENABLE_FEEDBACK_EP                1
#define CFG_TUD_AUDIO_ENABLE_FEEDBACK_FORMAT_CORRECTION 1
#define CFG_TUD_AUDIO_ENABLE_INTERRUPT_EP               0

#ifdef __cplusplus
}
#endif
