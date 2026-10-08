# Sources and licensing

Reactor's project scopes and commercial-authorization policy are defined in
[LICENSE](LICENSE) and [LICENSING.md](LICENSING.md).
Donald Microduck preserves its official upstream terms; Mickey Hub's first-party
work uses noncommercial public licenses with separate written authorization
for commercial production. Third-party material keeps its original terms.

| Source | Included use | Terms |
| --- | --- | --- |
| [Pollen Robotics Microduck RL](https://github.com/pollen-robotics/microduck_rl) | Original robot meshes/MJCF; derived head, print files and Blender assembly | Software: Apache-2.0. Models: the official upstream README states Creative Commons BY-SA-NC; see the preserved upstream notice. |
| [Pollen Robotics Microduck](https://github.com/pollen-robotics/microduck) | Runtime reference; not vendored | Apache-2.0 |
| [Seeed ReSpeaker XVF3800](https://github.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY) | Microphone-board geometry within the final assembly and XMOS image download link; separate STEP references are archived | Upstream/manufacturer terms; no blanket Apache license is asserted for these assets or firmware |
| [Radxa Zero 3W](https://docs.radxa.com/en/zero/zero3) | Main-computer geometry reference within the assembly | Manufacturer reference; no blanket Apache license is asserted |
| [ESP-IDF](https://github.com/espressif/esp-idf/tree/v5.5.1) and [TinyUSB](https://github.com/hathach/tinyusb) | Firmware build dependencies, fetched by ESP-IDF | Preserve their supplied licenses; not vendored |
| NumPy and MuJoCo | Simulation dependencies | Installed separately; see each distribution's license |

The upstream Microduck hardware notice does not identify a Creative Commons
version. It includes a non-commercial restriction; this repository does not
relicense the derived models as unrestricted hardware. The original notice and its source revision are recorded in
[UPSTREAM_LICENSES.md](donald-microduck/UPSTREAM_LICENSES.md).

Reactor modifications include the four-microphone enclosure, the final
reinforcement/contact-land edits, XIAO bridge, host tools and acoustic simulation.
The assembly also contains simplified purchased-part envelopes.

The Donald Microduck mechanical basis is the 2026-10-02 design delivery.
Local checksum lists and historical import ledgers are excluded from commits.
The Mickey Hub release manifest records its delivered files and hashes.
No source repository history, private recordings or device backups are included.

Mickey Hub uses CC BY-NC 4.0 for first-party designs/content and PolyForm
Noncommercial 1.0.0 for first-party software. Commercial production requires
separate prior written authorization from the relevant rights holders.
See [the license scope](LICENSING.md)
and [third-party exclusions](mickeyhub/THIRD_PARTY.md). These terms do not override
Microduck's official licenses or third-party manufacturer terms.
