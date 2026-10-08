# Mickey Hub

**Bring perception together.**

[Reactor](../) · [Design files](mechanical/) · [Electronics](electronics/) · [Firmware](firmware/)

Mickey Hub explores how a compact device can notice activity around it and
respond through a familiar face, light and sound. It shares Donald Microduck's
Radxa ZERO 3W host and four-microphone audio platform, with more sensors and I/O
inside a rounded graphite enclosure.

## Explore every module

![Mickey Hub rotating and decomposing with English explanations](media/mickeyhub-preview.gif)

The animation keeps rotating as **20 chapters introduce 46 labeled assemblies**,
from sensing and computation to power, wiring and the enclosure. This silent
GIF plays the full sequence at twice its original speed, with English labels
and detail views. [Captions](media/mickeyhub-animation.srt),
[the storyboard](media/mickeyhub-animation.json) and the
[media guide](media/) are included.

## A compact sensing platform

| System | Hardware and intended role |
| --- | --- |
| Hearing | Four-microphone ReSpeaker array and speaker for listening and audio feedback. |
| Surrounding activity | Three millimeter-wave radar modules facing left, right and rear. |
| Vision and depth | Ultra-wide front camera and an 8 × 8 ToF depth-sensing module. |
| Motion and heading | Six-axis IMU and compass for orientation and mobile-support experiments. |
| Interaction | Glasses-like dual displays, light ring, speaker and physical controls. |
| Computation and expansion | Radxa ZERO 3W host, RP/S3 controllers, carrier board and additional interfaces. |

These inputs provide a platform for perception experiments. Complete sensor
fusion and reliable autonomous responses remain development goals.

## Hardware at a glance

[![Mickey Hub complete hardware functional diagram](docs/images/hardware-overview.png)](docs/images/hardware-overview.png)

The Linux host brings together audio, camera and depth input. RP2350 handles
power coordination; ESP32S3 connects the radar and shared I²C peripherals.
The figure also shows displays, cooling, expansion, the UPS and user input.

[Open the large figure](docs/images/hardware-overview.png) ·
[Editable SVG](docs/images/hardware-overview.svg) ·
[Hardware map and source notes](docs/HARDWARE_OVERVIEW.md)

## Open the design

| I want to… | Start here |
| --- | --- |
| Inspect the complete device | [Assembled Blender model](mickeyhub.blend) |
| Understand the hardware functions | [Hardware overview](docs/HARDWARE_OVERVIEW.md) — complete system block diagram |
| View the rotating explainer | [Media guide](media/) — GIF, storyboard and captions |
| Work on the enclosure | [Mechanical guide](mechanical/) — 15 print STLs and four fit samples |
| Inspect individual assemblies | [Component catalog](components/) — 46 descriptions, dimensions and source-object names |
| Edit the circuit and PCB | [Electronics guide](electronics/) — KiCad projects, local libraries, schematic PDF and BOM |
| Review the fabrication outputs | [Manufacturing guide](manufacturing/) — Gerbers, drills, placement and reference views |
| Build device software | [Firmware guide](firmware/) — RP, S3 and Linux sources |
| Explore the circuit checks | [Simulation guide](simulation/) — 18 executed MUX DC cases |
| Rebuild or review current constraints | [Build instructions](docs/BUILD.md) · [Engineering status](docs/CURRENT_STATUS.md) |

Large models use Git LFS. From your checkout:

```sh
git lfs install --local
git lfs pull
```

Open `mickeyhub.blend` in Blender for the complete assembly. It is the project's
only included Blender file. Printable geometry is supplied as STL.
Component GLBs, STEP references, structural construction baselines and separate
animation projects are retained in the local archive.

## PCB and assembled electronics

[![Carrier PCB front and back](electronics/images/pcb-carrier.jpg)](electronics/images/pcb-carrier.jpg)

The carrier is shown from both sides, with its native copper, connector lands,
mounting holes and silkscreen. These previews are rendered from the included
KiCad PCB.

[![Main carrier with the host and board-mounted modules installed](electronics/images/pcb-assembled.jpg)](electronics/images/pcb-assembled.jpg)

The assembled view shows the host, controllers, interface modules, connectors
and HAT in their positions from the final Blender model. The enclosure and
remote modules are hidden to expose the electronics.

[Explore the electronics](electronics/) for the editable PCB sources and
fabrication references.

The carrier uses a monochrome icon traced from the enclosure and the marking
**MicheyHub V0.0**. [Editable SVG](electronics/branding/mickeyhub-mark.svg),
native PCB graphics and current Gerbers are included. The electrical design
retains its **BOX R2.1R** revision.

## Development status

The carrier and both adapter projects pass the recorded native DRC/ERC checks.
Print exports have recorded geometry checks, and the simulation guide describes
the executed DC cases. Complete powered-device qualification remains open.

Power-actuator selection, fan/ToF electrical compatibility and harness fit need
further work. Read [CURRENT_STATUS.md](docs/CURRENT_STATUS.md) and the
[current electrical contract](docs/current_contract/) before assembling hardware.

From this project directory, verify the committed assets with:

```sh
python3 tools/verify_release.py
```

The check uses the included GIF, models and design evidence. Full MP4 renders
stay locally under `memory_backups/videos/mickeyhub/` at the repository root;
they are excluded from commits and are not required to verify a fresh checkout.
[Build instructions](docs/BUILD.md) describe the supplied files and checks.

## License

Copyright 2026 Mickey Hub contributors.

Mickey Hub's first-party work is source-available under these public licenses,
with a separate limited commercial permission:

- Designs, original models, documentation and media: **CC BY-NC 4.0**.
- Firmware and software tools: **PolyForm Noncommercial 1.0.0**.

Noncommercial development, sharing, personal builds and prototypes are
permitted under the applicable license terms.

The [additional commercial permission](COMMERCIAL_USE.md) allows the same
individual or legal entity to sell **up to and including 100 covered devices
or one-device kits per calendar year**, without a license fee or an individual
permission request. Sales across the entity's brands, stores, channels and
product variants count together.

**Before selling the 101st unit in that year**, obtain a separate written
commercial license. A calendar year runs from January 1 through December 31;
the complete grant defines the permitted activities and counting rules.

See [LICENSE](LICENSE) for the complete terms and contact information,
[Reactor's license scope](../LICENSING.md) for the project boundaries, and
[THIRD_PARTY.md](THIRD_PARTY.md) for exclusions. Third-party code, documents and
CAD retain their own terms. Donald Microduck's upstream licenses remain separate.

---

<sub>For questions or commercial licensing, contact [phyreact@gmail.com](mailto:phyreact@gmail.com).</sub>
