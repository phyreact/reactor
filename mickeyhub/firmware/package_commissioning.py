#!/usr/bin/env python3
"""Package tested controller builds, without generating a PCB manufacturing release."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

W = Path(__file__).resolve().parent
R = W.parents[1]
P = R / "hardware/box_carrier_modules_r2"
selected = json.loads((P / "current_design.json").read_text())
pcb = Path(selected["active_pcb"])
F = pcb.parent.parent
B = F / "analysis/release_closure"
D = W / "dist"
D.mkdir(exist_ok=True)

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

for source, target in {
        "rp/build/box_r21r_rp.uf2": "rp/box_r21r_rp.uf2",
        "rp/build/box_r21r_rp.elf": "rp/box_r21r_rp.elf",
        "s3/build/box_r21r_s3.bin": "s3/box_r21r_s3.bin",
        "s3/build/bootloader/bootloader.bin": "s3/bootloader/bootloader.bin",
        "s3/build/partition_table/partition-table.bin": "s3/partition_table/partition-table.bin",
        "s3/build/flash_args": "s3/flash_args",
        "s3/build/flasher_args.json": "s3/flasher_args.json",
        "s3/sdkconfig": "s3/sdkconfig",
        "README.md": "README.md"}.items():
    destination = D / target
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(W / source, destination)
for p in (W / "zero").iterdir():
    if p.is_file():
        destination = D / "zero" / p.name
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(p, destination)

sources = {str(p.relative_to(W)): sha(p) for p in W.rglob("*") if p.is_file()
           and not any(x in p.relative_to(W).parts for x in ("build", "dist", "__pycache__"))
           and p.suffix != ".log" and p.name not in ("sdkconfig", "sdkconfig.old")}
artifacts = {str(p.relative_to(D)): sha(p) for p in D.rglob("*")
             if p.is_file() and p.name != "manifest.json"}
manifest = {
    "purpose": "Engineering commissioning firmware, not production-qualified",
    "pcb_sha256": sha(pcb), "relay_polarity": "All four original modules LOW-active",
    "M15": "SparkFun BOB-12009, same GPIO and net map",
    "S3": {"target": "Seeed XIAO ESP32S3 Plus, ESP-IDF 5.5.1, 16MB Flash",
           "build_complete": True, "flashed": False},
    "RP": {"target": "Seeed XIAO RP2350, Pico SDK 2.3.1, Arm GNU 14.3.rel1",
           "build_complete": True, "flashed": False,
           "pico_sdk_commit": "079c6f39023649b154152db30f1d781e884879bc"},
    "ZERO": {"python_tests_pass": True, "dtc_compile_pass": True,
             "target_dtb_merge_tested": False, "systemd_hook_executed_on_target": False},
    "test_log": str(B / "firmware_tests.log"),
    "hardware_qualified": False, "production_release": False,
    "sources_sha256": sources, "artifacts_sha256": artifacts,
}
(D / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
archive = F / "control/BOX_R21R_firmware_commissioning.zip"
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
    for p in D.rglob("*"):
        if p.is_file():
            z.write(p, "firmware/" + str(p.relative_to(D)))
    for name in sources:
        z.write(W / name, "source/" + name)
    for name in ("firmware_tests.log", "device_tree.log", "native_audit.json"):
        z.write(B / name, "validation/" + name)
print(json.dumps({"archive": str(archive), "sha256": sha(archive),
                  "files": len(artifacts), "source_files": len(sources),
                  "pcb_sha256": sha(pcb)}, indent=2))
