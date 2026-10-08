# Open the assembly, print parts and verify files

Run the commands below from the `mickeyhub/` project root.

## Get the models

```sh
git lfs install --local
git lfs pull
```

Open [mickeyhub.blend](../mickeyhub.blend) in Blender to inspect the complete
wired assembly and graphite appearance. Blender 5.1.2 was used for this
assembly. It is the project's only included Blender file.

The [mechanical guide](../mechanical/README.md) describes 15 printable STL
parts and four seam fit samples. Import them into a slicer in millimetres at
100% scale. Test fit and choose supports for the actual printer and material;
the supplied checks do not establish physical qualification.

Component descriptions, dimensions and Blender object names are in the
[component catalog](../components/). Individual GLB exports, separate STEP/VRML
references, intermediate construction models and their associated modeling
tools are retained in the local archive and are not required for these files.

## Electronics and manufacturing

Open `electronics/kicad/box_carrier_modules_r2.kicad_pro` in KiCad to edit the
electrical design. Local symbols, footprints and schematic sources remain
included. Separate 3D preview models are archived; their optional references
remain in the unchanged PCB and footprint files.

Native DRC/ERC records are under `electronics/validation/`. To regenerate the
carrier fabrication package, including the enclosure icon and **MicheyHub V0.0**
marking:

```sh
python3 tools/export_manufacturing.py
```

Set `KICAD_CLI` if the executable is outside `PATH`. The exporter writes to
`build/manufacturing/` for review. See the
[fabrication guide](../manufacturing/README.md) and the
[firmware guide](../firmware/) for the corresponding workflows.

## Verify the public package

```sh
python3 tools/verify_release.py
shasum -a 256 -c checksums.sha256
```

The verifier checks the final assembly, STL hashes, component descriptions,
PCB and manufacturing integrity, firmware evidence and the included GIF.
It generates `checksums.sha256` locally; checksum lists are ignored by Git
and excluded from source archives.
It does not require archived models or rendering scenes. Historical model
hashes in geometry and animation reports record which sources produced those
checks; they do not imply those intermediate files are included.

The [media guide](../media/) introduces the GIF, storyboard and captions.
Full MP4s remain under `memory_backups/videos/` at the repository root;
separate animation scenes and rendering tools remain under
`memory_backups/3d_sources/`. To also verify the local MP4, when available:

```sh
python3 tools/verify_release.py --check-local-videos
```
