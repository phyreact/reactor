# BOX R2.1R control firmware

This directory contains the XIAO ESP32S3 Plus, XIAO RP2350 and Radxa ZERO 3W
control sources used by Mickey Hub: candidate power sequencing, shutdown
coordination, legacy radar forwarding, ToF acquisition and fan control.
ReSpeaker USB audio firmware and complete perception applications are separate.

**The power actuator remains unresolved.** UPS P2/J51 carries battery current;
the TL2230OAF140 low-current button must not directly switch it. The candidate
startup/sense arrangement requires suitably rated hardware and a complete
shutdown interlock. Software tests do not qualify that hardware. See the
[current power contract](../docs/current_contract/) and
[engineering status](../docs/CURRENT_STATUS.md).

## Files and recorded checks

| Directory | Contents |
| --- | --- |
| `common/` | Power state machine, pin assignments and protocol. |
| `rp/` | RP2350 controller source and CMake project. |
| `s3/` | ESP-IDF project and saved defaults. |
| `zero/` | Linux service, shutdown hook, preflight, device tree and ToF library. |
| `tests/` | Native C tests and 20 Python tests. |
| `verified_builds/` | Recorded RP UF2, S3 application binary, overlay and AArch64 ToF library. |
| `validation/` | Source/build hashes and recorded results. |

The S3 binary is an application artifact, not a complete flash bundle. Build
the matching ESP-IDF project for its bootloader, partition table and flash
arguments. Historical commissioning archives and build caches are not included.

## Current behavior

RP initially asserts M16 hold; M1, M2 and M17 default off. A startup press must
remain held for approximately 1 second after RP startup before HOST is enabled.
That initial hold cannot become a shutdown press. After release, a new 2.5-second
hold requests normal Linux shutdown. Short presses no longer toggle HOST.

S3 and RP exchange 64-byte messages over I2C1, with RP address `0x2D`, CRC16,
sequence numbers and session identifiers. Both sides must confirm radar TX
release before M2 changes state. Communication failure releases TX and reports
a fault while retaining MAIN/HOST power. Recovery requires a fresh radar-off
handshake; stale messages cannot restore TX.

Adjacent relay transitions have a 250 ms minimum interval. ToF enable also
requires ZERO READY and at least 500 ms of M1 on-time. Reported relay state is
a command, not a contact or voltage measurement.

Linux requests normal `systemctl poweroff`. The final acknowledgement comes
from the systemd shutdown hook, which checks shutdown ancestry, read-only
persistent filesystems and disabled swap. This indicates quiescent storage,
not completed CPU halt. RP waits at least 1 second, requires fresh radar-off
confirmation and a ToF-off command held for 50 ms before releasing M1.
Releasing M16 additionally requires button release/debounce and at least
250 ms. Communication failure cancels the MAIN release timer. The 120-second
shutdown timeout reports a fault and does not force power removal.

The radar transport still targets **four LD2450** devices at 256000/8N1:
three on S3 and one on RP UART1. RP UART0 forwards sensor-tagged, 30-byte reports
to ZERO at 115200/8N1. The assembly now contains **three Rd-03E** radars; their
protocol and application migration remains incomplete.

Fan control uses a configurable 25 kHz candidate PWM frequency, with M42 PHASE
duty inverted relative to requested fan duty. Startup uses full speed for
1 second; missing FG or lost events latch full speed. Unknown pulses per
revolution produce Hz, not inferred RPM. The purchased fan is 5 V with black
GND, yellow supply, green FG and blue PWM. Electrical FG/PWM qualification is
still required; `electrical_qualified` defaults to `false`.

ToF uses the pinned ST ULD through Linux `I2C_RDWR`, with 8 × 8, 10 Hz raw
distance, target-count and status output. Stopping acquisition enters software
sleep without switching M17. The candidate J37 route is SCL, SDA, ZERO 3V3 and
GND on pins 1–4; J16 is unused for this device. The actual nine-pin carrier
requires qualification; `carrier_3v3_qualified` defaults to `false`.

The overlay provides UART9_M1 for RP, UART5_M1 for the displays, I2C4_M0 for
ToF, PWM14_M0 and GPIO1_A0/A1 software I2C for the HAT. `preflight.py` discovers
actual device mappings rather than assuming Linux bus numbers.

## Build and test

From this directory:

```sh
python3 tests/run_tests.py

# Build on the Linux ZERO, or use an AArch64 Linux cross-toolchain.
make -C zero/tof

# Pico SDK 2.3.1; Arm GNU 14.3.rel1; seeed_xiao_rp2350.
cmake -S rp -B rp/build \
  -DPICO_SDK_PATH=/path/to/pico-sdk-2.3.1 \
  -DPICO_TOOLCHAIN_PATH=/path/to/arm-gnu-toolchain
cmake --build rp/build -j

# ESP-IDF 5.5.1, ESP32S3, 16 MB flash.
(cd s3 && idf.py -DIDF_TARGET=esp32s3 build)

dtc -@ -I dts -O dtb -o zero/box-r21r.dtbo zero/box-r21r.dts
```

Native C tests use AddressSanitizer and UndefinedBehaviorSanitizer. They cover
state transitions, communication loss/restart, stale messages, shutdown
acknowledgement/timeouts, counter rollover, button timing and relay intervals.
ToF tests cover 512-byte chunking, partial-transfer failure, register bounds and
byte order. Python tests cover protocol handling, shutdown-hook guards, PWM
inversion, fan fail-safe behavior, qualification gates and ToF shutdown errors.

No target flashing or powered-device acceptance test is recorded. PSRAM is
disabled; RP USB/UART standard output is disabled. Later USB flashing requires
removal of the XIAO boards from the carrier because USB/carrier power
arbitration is not provided.

## Target integration

The target kernel DTB has not been supplied or merged with this overlay.
Before deployment, validate against that exact DTB and run
`sudo python3 zero/preflight.py` on the target. GPIO-I2C, I2C character-device,
Rockchip PWM and UART drivers must be available without conflicting pin use.

| File | Intended target path |
| --- | --- |
| `zero/box_host.py`, `zero/box_peripherals.py` | `/usr/libexec/box-controller/` |
| AArch64 `libbox_tof.so` | `/usr/libexec/box-controller/tof/libbox_tof.so` |
| `zero/box-controller.service` | `/etc/systemd/system/box-controller.service` |
| Complete executable copy of `zero/box_host.py` | `/usr/lib/systemd/system-shutdown/99-box-controller` |
| `zero/box-controller.example.json` | `/etc/box-controller.json` |

The shutdown hook requires Python 3 and its standard library late in shutdown.
FG support also needs libgpiod 2.x Python bindings and verified GPIO paths.
Configure the UART and exported PWM paths discovered on the target. Keep
`poweroff_enabled: false` until hardware, timing and the late shutdown hook
have been validated. This mode records requests without enabling power removal.

The service uses a local root socket with `status`, `radar-on`, `tof-on`,
`fan --duty 75` and `all-off` commands. It has no network listener or application
command for final shutdown acknowledgement. Stopping the service does not
acknowledge shutdown.

OLED presentation, IMU processing, the display protocol, ToF perception and
audio applications remain outside this firmware's scope. No servo is included
in the current load or acceptance budget. Startup current, relay life, thermal
behavior, reset faults and back-powering require physical verification.

Implementation references include Seeed XIAO pin/flash documentation, Pico SDK
2.3.1 commit `079c6f39023649b154152db30f1d781e884879bc`, Radxa ZERO 3 pin
documentation, Linux Rockchip pinctrl and `i2c-gpio` bindings, and systemd's
shutdown manual/source. Pinned ToF sources and their license are retained under
`zero/tof/`.
