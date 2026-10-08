# XIAO audio bridge

ESP32-S3 firmware for the XIAO on the ReSpeaker XVF3800 board.
UAC2 provides 16 kHz, stereo, signed 16-bit capture/playback; CDC provides
configuration, status and voice-activity events. The four microphones feed the
XVF3800 DSP; this bridge carries two processed channels, not four raw channels.

Use **ESP-IDF 5.5.1**, ESP32-S3, 8 MB flash and the pinned TinyUSB dependency.
The matching XMOS image is **I2S slave 1.0.8 / 16 kHz**. XIAO drives I2S clocks.

| Signal | XIAO GPIO |
| --- | --- |
| BCLK / LRCLK | 8 / 7 |
| Data out / in | 44 / 43 |
| I2C SDA / SCL | 5 / 6 |

The XMOS I2C address is `0x2c`. UART console output is disabled because
GPIO43/44 carry audio. An external-clock check prevents automatic conflicting
I2S clock drive.

With the ESP-IDF environment activated:

```sh
cd donald-microduck/firmware
idf.py set-target esp32s3
idf.py build
idf.py -p YOUR_XIAO_SERIAL_PORT flash
```

Select the actual XIAO port and verify the flash size before flashing.
Connect the Radxa USB host to the **XIAO USB port** for this firmware.
The separate XMOS USB port is used for its DFU recovery/update.

`fetch_xmos.py` downloads only the pinned official XMOS image and verifies its
SHA-256; it does not flash a device:

```sh
python3 fetch_xmos.py --output build/xmos-i2s-slave-16k.bin
```

Basic CDC commands: `ping`, `status`, `log`, `vad 0|1`,
`vad_silence <milliseconds>`, `mic_mute 0|1`, `speaker_mute 0|1`.
`help` lists low-level controls. Voice activity is an energy/firmware event,
not keyword recognition. USB identifiers are development-prototype values.

The source has been built locally. The cleaned release has not been flashed
or tested on hardware; runtime testing uses the software twin.
