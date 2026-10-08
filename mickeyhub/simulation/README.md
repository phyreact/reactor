# Simulation and analysis scope

`mux_dc_sensitivity/` contains 18 ngspice input decks (`.cir`) and their saved logs/data. They sweep three supply values (4.75, 5.0 and 5.25 V), three load values (1 kΩ, 10 kΩ and 100 kΩ), and two switch states. These are limited DC sensitivity cases for the MUX circuit.

The earlier automatic SPICE extractor executed **zero cases**. Its empty
finding list does not establish a whole-system pass. Those automatic review
reports and historical PCB snapshots are held in the local archive. This
directory retains the actual executed DC decks and their numerical results.

Mechanical topology/contact and movement checks live in `../mechanical/validation/`; firmware tests/build logs live in `../firmware/validation/`. Their scope is separate from analog simulation.

The input decks are editable. Re-running them requires ngspice. Run from a
scratch directory: each deck writes its named result to the current directory.
Saved results remain tied to the original assumptions and component models;
no complete-system transient model is supplied or claimed.
