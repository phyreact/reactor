# Carrier-board fabrication files

These files are exported from the included native KiCad carrier PCB. The front
silkscreen uses the actual enclosure's monochrome silhouette and **MicheyHub V0.0**.
The electrical design retains its BOX R2.1R revision.

| Path | Purpose |
| --- | --- |
| `UPLOAD/MicheyHub_V0.0_Gerbers.zip` | Current Gerber, drill and netlist upload archive. |
| `gerbers/` | Four copper layers, two masks, two silkscreens, outline, separate PTH/NPTH drills and fabrication notes. |
| `stencil_reference/` | Paste/stencil reference outputs. |
| `assembly/` | Engineering BOM, component positions, drill maps, copper views and front silkscreen SVG. |
| `validation/` | Native CAD checks, source/output hashes and export integrity record. |

[export_integrity.json](validation/export_integrity.json) records the exact
source PCB hash, every delivered output hash and the upload archive hash.
[branding.json](../electronics/branding.json) records the graphic changes and
checks that unrelated native CAD blocks are unchanged. The front
[silkscreen view](assembly/F_silkscreen.svg) provides a direct inspection of
the board markings.

To regenerate in an isolated directory:

```sh
python3 tools/export_manufacturing.py
```

Run this from `mickeyhub/`, with `kicad-cli` installed. Set `KICAD_CLI` if it is
outside `PATH`. Outputs go to `build/manufacturing/`; inspect them before
replacing this package. The exporter runs native DRC/ERC and generates the
Gerbers, drills, IPC-D356 netlist, reference views and integrity record from
the same source PCB.

The [schematic PDF](../electronics/schematic.pdf) and
[qualification plan](../docs/engineering_review/qualification_plan.json) each
each have one canonical copy. The integrity record resolves their former
package paths to those copies.

This is a bare prototype design package. CAD rule checks and consistent
exports do not establish complete-system hardware qualification. The current
power, interface and harness work is described in
[CURRENT_STATUS.md](../docs/CURRENT_STATUS.md). No fabrication order has been placed.
