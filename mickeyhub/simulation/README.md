# Simulation and analysis scope

`mux_dc_sensitivity/` contains 18 ngspice input decks (`.cir`) and their saved
numerical results (`.txt`). They sweep three supply voltages (4.75, 5 and
5.25 V), three pulldown resistance values (1, 10 and 100 kΩ), and two contact
states. These are limited DC sensitivity cases for the MUX circuit.

## Case names

Names describe the simulation conditions, not design or software versions:

`4.75V_100kOhm_contact-open.cir`

| Part | Meaning |
| --- | --- |
| `4.75V` | Supply voltage |
| `100kOhm` | Value of each of the two identical pulldown resistors |
| `contact-open` / `contact-closed` | Contact state in the DC model |
| `.cir` / `.txt` | Editable input deck / saved numerical result |

The 18 cases cover all 3 × 3 × 2 parameter combinations. Each input writes to
the `.txt` file with the same name. Execution logs are retained in the local
archive.

## Scope and reproduction

The earlier automatic SPICE extractor executed **zero cases**. Its empty
finding list does not establish a whole-system pass. Those automatic review
reports and historical PCB snapshots are held in the local archive. This
directory retains the actual executed DC decks and their numerical results.

Mechanical topology/contact and movement checks live in `../mechanical/validation/`; firmware tests/build logs live in `../firmware/validation/`. Their scope is separate from analog simulation.

The input decks are editable. Re-running them requires ngspice. Run from a
scratch directory: each deck writes its named result to the current directory.
Saved results remain tied to the original assumptions and component models;
no complete-system transient model is supplied or claimed.
