// USB descriptors: UAC2 headset function (speaker + microphone) and a CDC-ACM
// control port, composed with IADs. Numbers live in usb_descriptors.h.
#include <stdio.h>
#include <string.h>
#include "esp_mac.h"
#include "tusb.h"
#include "usb_descriptors.h"

TU_VERIFY_STATIC(AUDIO_EP_SIZE == TUD_AUDIO_EP_SIZE(AUDIO_SAMPLE_RATE, AUDIO_BYTES_PER_SAMPLE, AUDIO_CHANNELS),
                 "audio endpoint size");
TU_VERIFY_STATIC(AUDIO_EP_SIZE <= CFG_TUD_AUDIO_FUNC_1_EP_IN_SZ_MAX, "audio IN endpoint size");
TU_VERIFY_STATIC(AUDIO_FIFO_BYTES % AUDIO_FRAME_BYTES == 0, "FIFO holds whole frames");

static const tusb_desc_device_t desc_device = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0200,
    // Composite device built from interface association descriptors.
    .bDeviceClass = TUSB_CLASS_MISC,
    .bDeviceSubClass = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor = USB_VID,
    .idProduct = USB_PID,
    .bcdDevice = USB_BCD_DEVICE,
    .iManufacturer = STRID_MANUFACTURER,
    .iProduct = STRID_PRODUCT,
    .iSerialNumber = STRID_SERIAL,
    .bNumConfigurations = 1,
};

uint8_t const *tud_descriptor_device_cb(void)
{
    return (uint8_t const *)&desc_device;
}

#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_AUDIO_BRIDGE_DESC_LEN + TUD_CDC_DESC_LEN)
#define STEREO           (AUDIO_CHANNEL_CONFIG_FRONT_LEFT | AUDIO_CHANNEL_CONFIG_FRONT_RIGHT)
#define ISO_DATA_ASYNC   ((uint8_t)(TUSB_XFER_ISOCHRONOUS | TUSB_ISO_EP_ATT_ASYNCHRONOUS | TUSB_ISO_EP_ATT_DATA))
#define CLOCK_CONTROLS   ((AUDIO_CTRL_R << AUDIO_CLOCK_SOURCE_CTRL_CLK_FRQ_POS) | \
                          (AUDIO_CTRL_R << AUDIO_CLOCK_SOURCE_CTRL_CLK_VAL_POS))
#define FU_MUTE          (AUDIO_CTRL_RW << AUDIO_FEATURE_UNIT_CTRL_MUTE_POS)
#define FU_MUTE_VOLUME   (FU_MUTE | (AUDIO_CTRL_RW << AUDIO_FEATURE_UNIT_CTRL_VOLUME_POS))

static const uint8_t desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 500),

    // ---- Audio function: interfaces 0 (control), 1 (speaker), 2 (microphone)
    TUD_AUDIO_DESC_IAD(ITF_NUM_AUDIO_CONTROL, 3, 0x00),
    TUD_AUDIO_DESC_STD_AC(ITF_NUM_AUDIO_CONTROL, 0, STRID_AUDIO),
    TUD_AUDIO_DESC_CS_AC(0x0200, AUDIO_FUNC_HEADSET, UAC2_AC_BODY_LEN, 0x00),
    // The XIAO is the I2S master, so the rate is fixed by its own clock tree.
    TUD_AUDIO_DESC_CLK_SRC(UAC2_ENTITY_CLOCK, AUDIO_CLOCK_SOURCE_ATT_INT_FIX_CLK, CLOCK_CONTROLS, 0x00, 0x00),
    // Speaker path: USB streaming -> feature unit (master mute + volume) -> speaker.
    TUD_AUDIO_DESC_INPUT_TERM(UAC2_ENTITY_SPK_INPUT_TERM, AUDIO_TERM_TYPE_USB_STREAMING, 0x00,
                              UAC2_ENTITY_CLOCK, AUDIO_CHANNELS, STEREO, 0x00, 0x0000, 0x00),
    TUD_AUDIO_DESC_FEATURE_UNIT_TWO_CHANNEL(UAC2_ENTITY_SPK_FEATURE_UNIT, UAC2_ENTITY_SPK_INPUT_TERM,
                                            FU_MUTE_VOLUME, 0, 0, 0x00),
    TUD_AUDIO_DESC_OUTPUT_TERM(UAC2_ENTITY_SPK_OUTPUT_TERM, AUDIO_TERM_TYPE_OUT_GENERIC_SPEAKER, 0x00,
                               UAC2_ENTITY_SPK_FEATURE_UNIT, UAC2_ENTITY_CLOCK, 0x0000, 0x00),
    // Microphone path: XVF3800 output -> feature unit (master mute) -> USB streaming.
    TUD_AUDIO_DESC_INPUT_TERM(UAC2_ENTITY_MIC_INPUT_TERM, AUDIO_TERM_TYPE_IN_GENERIC_MIC, 0x00,
                              UAC2_ENTITY_CLOCK, AUDIO_CHANNELS, STEREO, 0x00, 0x0000, 0x00),
    TUD_AUDIO_DESC_FEATURE_UNIT_TWO_CHANNEL(UAC2_ENTITY_MIC_FEATURE_UNIT, UAC2_ENTITY_MIC_INPUT_TERM,
                                            FU_MUTE, 0, 0, 0x00),
    TUD_AUDIO_DESC_OUTPUT_TERM(UAC2_ENTITY_MIC_OUTPUT_TERM, AUDIO_TERM_TYPE_USB_STREAMING, 0x00,
                               UAC2_ENTITY_MIC_FEATURE_UNIT, UAC2_ENTITY_CLOCK, 0x0000, 0x00),

    // Speaker streaming: alt 0 = zero bandwidth, alt 1 = ISO OUT + explicit feedback.
    TUD_AUDIO_DESC_STD_AS_INT(ITF_NUM_AUDIO_STREAMING_SPK, 0, 0, STRID_SPEAKER),
    TUD_AUDIO_DESC_STD_AS_INT(ITF_NUM_AUDIO_STREAMING_SPK, 1, 2, STRID_SPEAKER),
    TUD_AUDIO_DESC_CS_AS_INT(UAC2_ENTITY_SPK_INPUT_TERM, AUDIO_CTRL_NONE, AUDIO_FORMAT_TYPE_I,
                             AUDIO_DATA_FORMAT_TYPE_I_PCM, AUDIO_CHANNELS, STEREO, 0x00),
    TUD_AUDIO_DESC_TYPE_I_FORMAT(AUDIO_BYTES_PER_SAMPLE, AUDIO_BITS_PER_SAMPLE),
    TUD_AUDIO_DESC_STD_AS_ISO_EP(EPNUM_AUDIO_OUT, ISO_DATA_ASYNC, AUDIO_EP_SIZE, 1),
    TUD_AUDIO_DESC_CS_AS_ISO_EP(AUDIO_CS_AS_ISO_DATA_EP_ATT_NON_MAX_PACKETS_OK, AUDIO_CTRL_NONE,
                                AUDIO_CS_AS_ISO_DATA_EP_LOCK_DELAY_UNIT_MILLISEC, 1),
    TUD_AUDIO_DESC_STD_AS_ISO_FB_EP(EPNUM_AUDIO_FB, AUDIO_FEEDBACK_EP_SIZE, 1),

    // Microphone streaming: alt 0 = zero bandwidth, alt 1 = ISO IN.
    TUD_AUDIO_DESC_STD_AS_INT(ITF_NUM_AUDIO_STREAMING_MIC, 0, 0, STRID_MIC),
    TUD_AUDIO_DESC_STD_AS_INT(ITF_NUM_AUDIO_STREAMING_MIC, 1, 1, STRID_MIC),
    TUD_AUDIO_DESC_CS_AS_INT(UAC2_ENTITY_MIC_OUTPUT_TERM, AUDIO_CTRL_NONE, AUDIO_FORMAT_TYPE_I,
                             AUDIO_DATA_FORMAT_TYPE_I_PCM, AUDIO_CHANNELS, STEREO, 0x00),
    TUD_AUDIO_DESC_TYPE_I_FORMAT(AUDIO_BYTES_PER_SAMPLE, AUDIO_BITS_PER_SAMPLE),
    TUD_AUDIO_DESC_STD_AS_ISO_EP(EPNUM_AUDIO_IN, ISO_DATA_ASYNC, AUDIO_EP_SIZE, 1),
    TUD_AUDIO_DESC_CS_AS_ISO_EP(AUDIO_CS_AS_ISO_DATA_EP_ATT_NON_MAX_PACKETS_OK, AUDIO_CTRL_NONE,
                                AUDIO_CS_AS_ISO_DATA_EP_LOCK_DELAY_UNIT_UNDEFINED, 0),

    // ---- CDC-ACM control port: interfaces 3 (notification) and 4 (data)
    TUD_CDC_DESCRIPTOR(ITF_NUM_CDC, STRID_CDC, EPNUM_CDC_NOTIF, 8, EPNUM_CDC_OUT, EPNUM_CDC_IN,
                       CFG_TUD_CDC_EP_BUFSIZE),
};

TU_VERIFY_STATIC(sizeof(desc_configuration) == CONFIG_TOTAL_LEN, "configuration descriptor length");

uint8_t const *tud_descriptor_configuration_cb(uint8_t index)
{
    (void)index;
    return desc_configuration;
}

static const char *const string_desc[] = {
    [STRID_MANUFACTURER] = "Reactor prototype",
    [STRID_PRODUCT] = "XIAO ReSpeaker Audio",
    [STRID_AUDIO] = "XIAO ReSpeaker Audio",
    [STRID_SPEAKER] = "XIAO ReSpeaker Speaker",
    [STRID_MIC] = "XIAO ReSpeaker Microphone",
    [STRID_CDC] = "XIAO ReSpeaker Control",
};

static uint16_t desc_str[32 + 1];

uint16_t const *tud_descriptor_string_cb(uint8_t index, uint16_t langid)
{
    (void)langid;
    char serial[13];
    const char *str;
    if (index == STRID_LANGID) {
        desc_str[1] = 0x0409; // English (United States)
        desc_str[0] = (uint16_t)((TUSB_DESC_STRING << 8) | 4);
        return desc_str;
    }
    if (index == STRID_SERIAL) {
        // The factory MAC identifies the board, same as esptool read_mac.
        uint8_t mac[6] = {0};
        esp_efuse_mac_get_default(mac);
        snprintf(serial, sizeof(serial), "%02X%02X%02X%02X%02X%02X",
                 mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
        str = serial;
    } else if (index < TU_ARRAY_SIZE(string_desc) && string_desc[index]) {
        str = string_desc[index];
    } else {
        return NULL;
    }
    size_t count = strlen(str);
    if (count > TU_ARRAY_SIZE(desc_str) - 1) count = TU_ARRAY_SIZE(desc_str) - 1;
    for (size_t i = 0; i < count; ++i) desc_str[1 + i] = (uint8_t)str[i];
    desc_str[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2 * count + 2));
    return desc_str;
}
