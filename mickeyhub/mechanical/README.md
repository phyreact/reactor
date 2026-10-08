# Mechanical design

Use [../mickeyhub.blend](../mickeyhub.blend) for the complete wired assembly and
current graphite appearance. It is the project's only included Blender file.

- `stl/`: 15 printable parts in millimetres. Filenames retain `DRAFT` because physical fit and material strength are not qualified.
- `fit_samples/`: four mating-seam samples for process/tolerance trials.
- `parameters/`: saved dimensions and revision parameters.
- `validation/`: topology, contact-area, service-sweep and export reports.
- `images/`: structural inspection views.

The reinforced halo seat increases effective bearing contact by 18.77% and the conservative roof connection area by about 20.14×. The inner and outer root bands are approximately 2 mm wide, with no breaks at 360 sampled angles. The ring remains flush with the roof.

Print exports are geometry only. Use a uniform dark graphite exterior finish except for the translucent LED ring. Historical colour fields in source export manifests do not encode STL colour and do not override the current finish.

The 15 exported meshes passed closed-surface, single-component and winding checks recorded against their hashes. CAD service sweeps are geometric checks, not proof of resin strength or a qualified assembly process. Choose orientation/supports through the actual printer/material workflow and test the supplied fit samples.

## File scope

STL files retain their original validated bytes. Separate structural Blender
projects, construction inputs, component GLBs, STEP references and the associated
modeling/export tools are stored in `memory_backups/3d_sources/` at the repository
root and are excluded from the published package.

The validation directory retains recorded geometry and export evidence.
Source-model hashes in those reports identify the models used for the checks;
intermediate models are archived. The current verifier checks the included
STLs, final integrated assembly, electronics and GIF without requiring the archive.
