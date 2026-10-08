# Component catalog

Open [index.html](index.html) for 46 assembly units, English purposes and
millimetre dimensions. [catalog.json](catalog.json) records source-object names,
dimensions and original assembly centres; [catalog.csv](catalog.csv) provides
a tabular version.

Inspect the geometry in [mickeyhub.blend](../mickeyhub.blend), the final integrated
assembly. Individual component GLB exports are archived locally. Printable
parts are supplied as [STL files](../mechanical/stl/).

Some purchased parts are reference geometry or simplified envelopes; they are
not certified manufacturer production CAD. Soldered small parts remain grouped
with their parent module. For circuit-level parts, use the KiCad symbols,
footprints and engineering BOM.

- `selections/`: retained component selection records.
- `device_review.json` and `.csv`: current device review.
- `datasheets/`: manufacturer reference documents.
- `references/`: supporting technical documents and electronics reference designs.
- [KiCad datasheets](../electronics/kicad/datasheets/): canonical carrier-project datasheets.
- [reference_aliases.json](reference_aliases.json): locations and hashes of consolidated documents.

Only the S3 Plus and RP2350 source footprints are retained from the broader
XIAO library. Current carrier and adapter libraries remain with their KiCad
projects. Separate STEP, VRML and DXF reference files, component GLBs and
intermediate models are held in `memory_backups/3d_sources/` at the repository
root and are excluded from the published package.

Presence in `references/` is not a selection or wiring approval. In particular,
the TL2230 low-current direct battery-switch proposal is rejected; the rear
power mechanism remains provisional. See
[CURRENT_STATUS.md](../docs/CURRENT_STATUS.md).
