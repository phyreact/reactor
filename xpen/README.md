# XPen

XPen is a compact handheld sensing-enclosure prototype. Its mechanical design
packages a camera, a display and audio hardware, and provides space for battery
mounting, cables and airflow.

## V55 design files

- [Integrated assembly](cad/xpen-v55-assembly.blend): inspect the camera, enclosure and internal layout.
- [Editable shell source](cad/xpen-v55-editable-shell.blend): edit the shell geometry and camera supports.
- [Upper shell STL](parts/xpen-v55-upper-shell.stl) and [lower shell STL](parts/xpen-v55-lower-shell.stl): prototype meshes in millimetres.

After cloning, run `git lfs pull` to download the Blender and STL files.
V55 adds continuous supports above and below the camera PCB. The upper support
has a rear cable relief; the lower support has rear component clearance.
The nominal spacing is 23.70 mm; measure the actual camera PCB before printing.

## Design renders

- [V49 assembled exterior](media/xpen-v49-assembly.png) — design render used in the Reactor gallery. This revision corrected the display-board orientation.
- [V55 camera support cutaway](media/xpen-v55-camera-cutaway.png) — later design detail showing the continuous supports above and below the camera.

These images document different design revisions. The V55 files are for
prototype fit checks; they do not establish electrical, acoustic or thermal
performance. This is not a production release.
