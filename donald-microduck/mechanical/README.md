# Donald Microduck mechanical files

Open [duck.blend](duck.blend) for the **complete assembled robot**.
Its 80 robot parts, electronics and fastener references are separate editable
mesh objects, stored locally in the Blender file.

- [Print files](print/): 37 STL files, 31 designs. Print each file once at **100%, millimetres**.
- [Print manifest](print/manifest.json): quantities, SHA-256 and mesh checks.
- [MuJoCo model](mjcf/): the earlier simulation robot and its complete mesh dependencies.
- [Animated previews](../media/): assembled and rotating decomposition GIFs.

The head/lid print files preserve the 2026-10-02 delivery bytes and assembly
coordinates. Move them onto the build plate in the slicer. The flexible pads are
separate from rigid parts; electronics, motors and fasteners are reference parts.

The head retains the lower-shell mating geometry, continuous internal ribs,
an internal M2 anti-rotation screw and camera-panel retention. The lid has four
acoustic contact lands. Nominal hardware: M2×6 screw and an M2 insert,
4 mm long × 3.2 mm outer diameter. Fit must be checked with actual parts.

These are trial-fit models: physical fit, resin deformation, strength and
acoustic sealing have not been validated. The original lower locating lip is
still thin. The static Blender assembly does not establish walking stability.

## File scope

The 3D package contains STL meshes and one final integrated Blender assembly.
The separate head/lid project, compressed design baselines, STEP references,
construction scripts and presentation scenes are retained in the local
`memory_backups/3d_sources/` archive, outside the published package.
The included assembly still contains separate mesh objects for inspection
and editing; it is not a complete parametric CAD feature tree.

The MuJoCo model predates the final enclosure. Its simulation microphone frame
is set explicitly in `sim/acoustics/audio_world.py`; it is not a physical
calibration of the assembled duck.
