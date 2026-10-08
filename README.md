# Reactor

**A world that can be seen, heard, and sensed.**

Someone calls from across the room. A hand moves beside the camera. The surface
under a device shifts. Each moment carries a cue about what is happening nearby.

We want to build machines that can notice those cues and respond in ways people
understand. Reactor explores that idea through two devices: an expressive robot
and a compact sensing hub. They share a Radxa ZERO 3W host and four-microphone
audio, with different bodies and ways to interact.

[![Donald Microduck and Mickey Hub in the Reactor studio](assets/reactor-family.jpg)](assets/reactor-family.jpg)

## Meet the projects

| Donald Microduck | Mickey Hub |
| :--- | :--- |
| <img src="donald-microduck/media/duck-decompose.gif" width="400" alt="Donald Microduck rotating and separating into labeled modules"> | <img src="mickeyhub/media/mickeyhub-preview.gif" width="400" alt="Mickey Hub rotating and separating into labeled assemblies"> |
| **Give listening a body.** A small robot with four microphones, a camera, a speaker and 15 smart servos. | **Bring perception together.** Four microphones, three radars, a camera, depth sensing, motion sensors and dual displays. |
| [**Explore Donald Microduck →**](donald-microduck/) | [**Explore Mickey Hub →**](mickeyhub/) |

Each project has its own guide, animated previews, STL parts, one final assembled
Blender model, firmware and build instructions. The GIFs above show the devices rotating, separating
into modules and coming back together, with English explanations.

## What you can explore

| Area | Donald Microduck | Mickey Hub |
| --- | --- | --- |
| Hearing | Four-microphone ReSpeaker hardware; current firmware provides 16 kHz stereo processed audio. | Four-microphone ReSpeaker hardware and a speaker for audio experiments. |
| Perception | Camera and motion sensing in a moving robot. | Ultra-wide camera, 8 × 8 ToF depth sensing, three radar modules, six-axis IMU and compass. |
| Interaction | Speaker, expressive pose and 15 smart servos. | Glasses-like dual displays, speaker, light ring, controls and additional I/O. |
| Design files | One final assembled Blender model and 37 printable STL parts. | One final assembled Blender model, 15 printable STL parts, four fit samples and native KiCad projects. |
| Development | [Firmware](donald-microduck/firmware/) · [Host tools](donald-microduck/software/) · [Simulation](donald-microduck/sim/) | [Firmware](mickeyhub/firmware/) · [Electronics](mickeyhub/electronics/) · [Simulation](mickeyhub/simulation/) |

These are evolving hardware projects. Sound-source localization, sensor fusion
and autonomous responses are development goals. Each project guide distinguishes
the supplied files and recorded checks from work that still needs assembled
hardware testing.

## Start exploring

1. **Choose a project above.** Its README introduces the device and points to the relevant files.
2. **Retrieve the large models with Git LFS.** Run these commands inside your checkout:

   ```sh
   git lfs install --local
   git lfs pull
   ```

3. **Open an editable assembly.** Start with
   [Donald Microduck](donald-microduck/mechanical/duck.blend) or
   [Mickey Hub](mickeyhub/mickeyhub.blend), then follow the project's build guide.

The repository includes firmware and application sources, native electronics,
manufacturing files, STL exports, one final assembled Blender file per project,
GIF previews and captions. Component GLBs, STEP references, intermediate design
files, separate animation scenes and full MP4 renders stay in the local
`memory_backups/` directory, alongside render caches and conversation history.
They are excluded from commits and source archives.

## Contribute

Work on mechanical fit, audio processing, perception, firmware, host applications
and interaction design is welcome. Identify the affected project, explain the
change and include the checks needed to reproduce your result.

## Licenses

| Project | Terms |
| --- | --- |
| **Donald Microduck** | Preserves the official upstream Apache-2.0 software license and the upstream noncommercial, share-alike model notice. [Upstream terms](donald-microduck/UPSTREAM_LICENSES.md). |
| **Mickey Hub** | First-party designs, models, documentation and media: **CC BY-NC 4.0**. First-party firmware and tools: **PolyForm Noncommercial 1.0.0**. [License scope](mickeyhub/LICENSE). |

Third-party material retains its own terms. [LICENSE](LICENSE) defines the
repository's directory scopes; [THIRD_PARTY.md](THIRD_PARTY.md) records upstream sources.
