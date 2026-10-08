# Sources and licensing

Mickey Hub's [license scope](LICENSE) applies CC BY-NC 4.0 to first-party
designs and content, and PolyForm Noncommercial 1.0.0 to first-party firmware
and software tools. Commercial production requires separate prior written
authorization from the relevant rights holders.
See [the repository license scope](../LICENSING.md).
It does not relicense third-party material or the separate
Donald Microduck project.

The complete assembly combines original enclosure design with purchased-part
reference geometry. Seeed ReSpeaker/XIAO, Radxa, ST ToF and other manufacturer
or distributor references retain their own notices and terms. Simplified
module envelopes are visualization and fit references.

`components/references/`, `components/datasheets/`, local KiCad libraries and
firmware dependency declarations preserve their source information. Repository
URLs, filenames and source notes identify origins where recorded. No blanket
Mickey Hub license is asserted over manufacturer documents or CAD.

The ST driver under [firmware/zero/tof/vendor/](firmware/zero/tof/vendor/)
retains its [original license](firmware/zero/tof/vendor/LICENSE.md).
The [Pico SDK license](LICENSES/Pico-SDK-BSD-3-Clause.txt) and
[Apache-2.0 text for dependencies such as ESP-IDF](LICENSES/Apache-2.0.txt)
are retained separately. Other installed dependencies retain their respective licenses. Their notices must accompany redistribution where required.

[release_manifest.json](release_manifest.json) records the delivered files
and hashes. Original import ledgers and workstation history are archived
locally. For the other project's official terms, see
[Microduck's upstream licenses](../donald-microduck/UPSTREAM_LICENSES.md).
