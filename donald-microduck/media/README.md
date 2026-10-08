# Donald Microduck media

Selected palette: **A / Classic Sailor Blue**.

![Rotating decomposition with English module explanations](duck-decompose.gif)

| Preview | Description |
| --- | --- |
| [Module explainer GIF](duck-decompose.gif) | 45-second, 960 × 540 silent summary with explanations and close-ups. |
| [Assembly GIF](duck-turntable.gif) | Eight-second turntable in the selected palette. |
| [Palette comparison](palette-comparison.png) | Three color options; A is selected. |

The explainer rotates continuously, separates each module and reassembles Duck.
It covers the lid, shell, four-microphone board, XIAO bridge, Radxa host, Robot
HAT and IMU, camera, speaker, beak, battery, servos, frame and software.

[decompose.json](decompose.json) contains the English script and labels;
[duck-decompose.srt](duck-decompose.srt) supplies subtitles, and
[duck-narration.m4a](duck-narration.m4a) contains the narration.
The selected and alternative colors are recorded in [palettes/](palettes/).

<p align="center">
  <img src="duck-turntable.gif" width="280" alt="Donald Microduck assembled turntable">
</p>

The previews were rendered from the final robot geometry. The display pose
adds a slight head tilt, staggered feet and an open jaw. Exploded spacing
illustrates the structure; physical balance, actuator feasibility and a
collision-free removal sequence have not been established.

The [final integrated Blender assembly](../mechanical/duck.blend) remains in
the repository. Separate display and animation scenes, along with their
rendering tools, are archived under `memory_backups/3d_sources/` at the
repository root. The narrated 2:08 MP4 and turntable MP4 remain under
`memory_backups/videos/donald-microduck/`. These archived files are excluded
from commits and are not needed to view the included GIFs.
