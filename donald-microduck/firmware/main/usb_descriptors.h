// Shared numbers for the USB descriptors, tusb_config.h and the I2S bridge.
// Included from tusb_config.h, so only macros and enums here (no tusb.h).
#pragma once

// Audio format on USB: 16 kHz, stereo, signed 16-bit little endian.
#define AUDIO_SAMPLE_RATE       16000
#define AUDIO_CHANNELS          2
#define AUDIO_BYTES_PER_SAMPLE  2
#define AUDIO_BITS_PER_SAMPLE   16
#define AUDIO_FRAME_BYTES       (AUDIO_CHANNELS * AUDIO_BYTES_PER_SAMPLE)
// Full speed, 1 ms interval: nominal 16 frames plus one frame of rate slack.
#define AUDIO_EP_SIZE           ((AUDIO_SAMPLE_RATE / 1000 + 1) * AUDIO_FRAME_BYTES)
// Per-direction software FIFO: 256 frames = 16 ms. Feedback (speaker) and
// IN flow control (microphone) both steer the level towards half full.
#define AUDIO_FIFO_BYTES        1024
// Full-speed feedback: 10.14 format in a 3-byte endpoint (TinyUSB's own table:
// the only combination macOS accepts; Linux takes anything; Windows would need
// 16.16/4 and is not a target). Pairs with FEEDBACK_FORMAT_CORRECTION=1.
#define AUDIO_FEEDBACK_EP_SIZE  3

#define USB_VID                 0x303A
#define USB_PID                 0x8001
#define USB_BCD_DEVICE          0x0100

enum {
    ITF_NUM_AUDIO_CONTROL = 0,
    ITF_NUM_AUDIO_STREAMING_SPK,
    ITF_NUM_AUDIO_STREAMING_MIC,
    ITF_NUM_CDC,
    ITF_NUM_CDC_DATA,
    ITF_NUM_TOTAL
};

// UAC2 entity IDs. One internal fixed clock drives both directions.
#define UAC2_ENTITY_CLOCK             0x04
#define UAC2_ENTITY_SPK_INPUT_TERM    0x01
#define UAC2_ENTITY_SPK_FEATURE_UNIT  0x02
#define UAC2_ENTITY_SPK_OUTPUT_TERM   0x03
#define UAC2_ENTITY_MIC_INPUT_TERM    0x11
#define UAC2_ENTITY_MIC_FEATURE_UNIT  0x12
#define UAC2_ENTITY_MIC_OUTPUT_TERM   0x13

#define EPNUM_AUDIO_OUT   0x01
#define EPNUM_AUDIO_FB    0x81
#define EPNUM_AUDIO_IN    0x82
#define EPNUM_CDC_NOTIF   0x83
#define EPNUM_CDC_OUT     0x04
#define EPNUM_CDC_IN      0x84

enum {
    STRID_LANGID = 0,
    STRID_MANUFACTURER,
    STRID_PRODUCT,
    STRID_SERIAL,
    STRID_AUDIO,
    STRID_SPEAKER,
    STRID_MIC,
    STRID_CDC,
};

// Class-specific AC body: clock + speaker IT/FU/OT + microphone IT/FU/OT.
#define UAC2_AC_BODY_LEN (TUD_AUDIO_DESC_CLK_SRC_LEN \
    + TUD_AUDIO_DESC_INPUT_TERM_LEN + TUD_AUDIO_DESC_FEATURE_UNIT_TWO_CHANNEL_LEN + TUD_AUDIO_DESC_OUTPUT_TERM_LEN \
    + TUD_AUDIO_DESC_INPUT_TERM_LEN + TUD_AUDIO_DESC_FEATURE_UNIT_TWO_CHANNEL_LEN + TUD_AUDIO_DESC_OUTPUT_TERM_LEN)

// Whole audio function, IAD included; TinyUSB walks exactly this many bytes.
#define TUD_AUDIO_BRIDGE_DESC_LEN (TUD_AUDIO_DESC_IAD_LEN \
    + TUD_AUDIO_DESC_STD_AC_LEN + TUD_AUDIO_DESC_CS_AC_LEN + UAC2_AC_BODY_LEN \
    /* speaker AS: alt 0, alt 1 with data EP and feedback EP */ \
    + TUD_AUDIO_DESC_STD_AS_INT_LEN \
    + TUD_AUDIO_DESC_STD_AS_INT_LEN + TUD_AUDIO_DESC_CS_AS_INT_LEN + TUD_AUDIO_DESC_TYPE_I_FORMAT_LEN \
    + TUD_AUDIO_DESC_STD_AS_ISO_EP_LEN + TUD_AUDIO_DESC_CS_AS_ISO_EP_LEN + TUD_AUDIO_DESC_STD_AS_ISO_FB_EP_LEN \
    /* microphone AS: alt 0, alt 1 with data EP */ \
    + TUD_AUDIO_DESC_STD_AS_INT_LEN \
    + TUD_AUDIO_DESC_STD_AS_INT_LEN + TUD_AUDIO_DESC_CS_AS_INT_LEN + TUD_AUDIO_DESC_TYPE_I_FORMAT_LEN \
    + TUD_AUDIO_DESC_STD_AS_ISO_EP_LEN + TUD_AUDIO_DESC_CS_AS_ISO_EP_LEN)
