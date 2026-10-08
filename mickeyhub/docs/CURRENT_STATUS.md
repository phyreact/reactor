# mickeyhub — current engineering state

This file describes the 2026-10-08 local design candidate. Historical reports are preserved as evidence and do not override this status.

| Area | Completed evidence | Remaining work |
| --- | --- | --- |
| Presentation | Uniform graphite finish, complete wired Blender model, 46 English-labelled assembly units, rotating exploded animation. | The exploded motion communicates structure; it is not a qualified removal sequence. |
| Structure | Wide-bearing halo v7b. Inner and outer roots approximately 2 mm; continuous at 360 sampled angles. Fifteen closed single-solid STL exports. | Material strength, print support strategy, shrinkage, tolerances and real assembly require samples. |
| Electrical CAD | Relocated KiCad project passes native DRC and ERC, with zero unconnected or schematic parity issues. | Checks do not qualify purchased modules, wiring, power sequencing or production hardware. |
| Power | M16 remains in the candidate shutdown design. Linux shutdown acknowledgement and button release are included in candidate firmware. | Choose a suitably rated power executor and finalize its interlock. UPS P2/J51 carries battery current; neither pin is ground. TL2230 direct switching is rejected. |
| Fan | Purchased fan confirmed 5 V. Black GND, yellow +5 V, green FG, blue PWM. | Verify FG/PWM electrical interface, frequency, pulses/revolution, startup/stall current. |
| ToF | Four-wire candidate route: J37.1 SCL, J37.2 SDA, J37.3 +3V3_ZERO, J37.4 GND. J16 empty; M17 unused. | Qualify the actual nine-pin carrier VIN/I/O levels. Bare VL53L8CX specifications do not establish carrier compatibility. |
| Harness | Current connection tables, 54-wire model and original audit included. | Audit records 45 overlaps, including 21 between harnesses. H05 short leads and H16 length/plug/bend allowances remain unresolved. |
| Firmware | Recorded 20 Python tests; C power-state and ToF-chunking tests with ASan/UBSan; RP/S3 builds; device-tree source and ARM64 ToF library builds. | No device flash, target DTB merge, energized validation or full radar protocol/application migration. |
| Simulation | Eighteen MUX DC sensitivity cases and saved output. | Automatic SPICE report ran zero cases. No full-system transient, switching, EMC chamber, thermal FEM or physical qualification. |

The current power contract and rejection evidence are in [current_contract](current_contract/). The firmware's safe-enable defaults and qualification gates must be preserved until the corresponding hardware is verified.

The recorded shutdown behavior uses a 1 s startup press and a 2.5 s shutdown press, then waits for Linux acknowledgement and a 250 ms released-button interval before opening M16. It assumes the missing rated power executor is correctly implemented; software timing does not resolve that hardware gap.

Original manufacturing records relate to the frozen carrier board. They do not certify the complete enclosure, module choices or current system power proposal. Current local packaging is authorized; manufacturing/series qualification and remote publication are not claimed.
