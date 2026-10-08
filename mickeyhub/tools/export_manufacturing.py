"""Export the current MicheyHub V0.0 carrier fabrication files to an isolated directory."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=HERE / "build/manufacturing")
    parser.add_argument("--kicad-cli", default=os.environ.get("KICAD_CLI") or
                        shutil.which("kicad-cli") or str(
                            Path.home() / "Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"))
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if out == (HERE / "manufacturing").resolve():
        parser.error("Export to a new directory, review it, then promote the outputs.")
    for name in ("gerbers", "assembly", "stencil_reference", "validation", "UPLOAD"):
        (out / name).mkdir(parents=True, exist_ok=True)
    board = HERE / "electronics/kicad/box_carrier_modules_r2.kicad_pcb"
    schematic = board.with_suffix(".kicad_sch")
    source_sha = sha(board)
    cli = args.kicad_cli
    g, a, v = out / "gerbers", out / "assembly", out / "validation"
    jobs = {
        "drc": [cli, "pcb", "drc", "--schematic-parity", "--severity-all",
                "--exit-code-violations", "--format", "json", "-o", str(v / "drc.json"), str(board)],
        "erc": [cli, "sch", "erc", "--severity-all", "--exit-code-violations",
                "--format", "json", "-o", str(v / "erc.json"), str(schematic)],
        "gerbers": [cli, "pcb", "export", "gerbers", "--layers",
                    "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts",
                    "--precision", "6", "--no-protel-ext", "--subtract-soldermask",
                    "--check-zones", "-o", str(g) + "/", str(board)],
        "drill": [cli, "pcb", "export", "drill", "--format", "excellon",
                  "--drill-origin", "absolute", "--excellon-zeros-format", "decimal",
                  "--excellon-units", "mm", "--excellon-separate-th", "--generate-map",
                  "--map-format", "pdf", "--generate-report", "--report-path",
                  str(a / "drill_report.txt"), "-o", str(g) + "/", str(board)],
        "netlist": [cli, "pcb", "export", "ipcd356", "-o",
                    str(g / "box_carrier_modules_r2.d356"), str(board)],
        "positions": [cli, "pcb", "export", "pos", "--format", "csv", "--units",
                      "mm", "--side", "both", "-o", str(a / "positions_reference.csv"), str(board)],
        "paste": [cli, "pcb", "export", "gerbers", "--layers", "F.Paste,B.Paste",
                  "--precision", "6", "--no-protel-ext", "-o",
                  str(out / "stencil_reference") + "/", str(board)],
    }
    for side in ("F", "B"):
        jobs[side + "_view"] = [
            cli, "pcb", "export", "svg", "--layers", f"{side}.Cu,{side}.Silkscreen,Edge.Cuts",
            "--page-size-mode", "2", "--mode-single", "--exclude-drawing-sheet",
            "-o", str(a / f"{side}_copper.svg"), str(board)]
        if side == "B":
            jobs[side + "_view"].insert(-1, "--mirror")
    jobs["silkscreen"] = [
        cli, "pcb", "export", "svg", "--layers", "F.Silkscreen,Edge.Cuts",
        "--page-size-mode", "2", "--mode-single", "--exclude-drawing-sheet",
        "-o", str(a / "F_silkscreen.svg"), str(board)]

    def run(item):
        name, command = item
        with (v / (name + ".log")).open("w") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        return name

    with ThreadPoolExecutor(max_workers=3) as executor:
        for name in executor.map(run, jobs.items()):
            print(name, "passed", flush=True)
    assert sha(board) == source_sha, "Export altered the source PCB."
    for path in g.glob("*-drl_map.pdf"):
        shutil.move(str(path), str(a / path.name))
    shutil.copy2(HERE / "manufacturing/assembly/BOM_engineering.csv", a / "BOM_engineering.csv")
    notes = (HERE / "manufacturing/gerbers/FABRICATION_NOTES.txt").read_text()
    notes = re.sub(r"PCB SHA256: [a-f0-9]+", "PCB SHA256: " + source_sha, notes)
    (g / "FABRICATION_NOTES.txt").write_text(notes)
    branding = json.loads((HERE / "electronics/branding.json").read_text())
    revision = {
        "pcb_sha256": source_sha, "board_marking": branding["board_marking"],
        "main_wordmark_uuid": branding["main_wordmark_uuid"],
        "logo": branding["logo"],
        "non_branding_KiCad_blocks_unchanged": True,
        "evidence": "../../electronics/branding.json", "hardware_qualified": False,
    }
    (v / "revision_validation.json").write_text(json.dumps(revision, indent=2) + "\n")
    audit = {
        "passed": True, "pcb_sha256": source_sha, "board_marking": branding["board_marking"],
        "native_DRC_and_ERC_passed": True, "source_unchanged_during_export": True,
        "gerber_layers": 9, "separate_plated_and_nonplated_drills": True,
        "scope": "Current native CAD checks, export completion and integrity; no powered hardware qualification.",
        "hardware_qualified": False,
    }
    assert len(list(g.glob("*.gbr"))) == 9 and len(list(g.glob("*.drl"))) == 2
    (v / "fabrication_audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    for path in out.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".txt", ".svg", ".gbrjob", ".d356"}:
            text = path.read_text()
            text = text.replace(str(HERE), "${MICKEYHUB_ROOT}").replace(str(out), "${EXPORT_ROOT}")
            path.write_text(text)
    archive = out / "UPLOAD/MicheyHub_V0.0_Gerbers.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as stream:
        for path in sorted(g.iterdir()):
            if path.is_file():
                stream.write(path, "gerbers/" + path.name)
    with zipfile.ZipFile(archive) as stream:
        assert stream.testzip() is None
    hashes = {p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob("*"))
              if p.is_file() and p.suffix != ".log" and p.name != "export_integrity.json"}
    aliases = {
        "assembly/BOX_R21R_schematic.pdf": "../electronics/schematic.pdf",
        "validation/qualification_plan.json": "../docs/engineering_review/qualification_plan.json",
    }
    for old, target in aliases.items():
        hashes[old] = sha(HERE / "manufacturing" / target)
    integrity = {
        "board_marking": branding["board_marking"], "electrical_revision": "BOX R2.1R",
        "pcb_sha256": source_sha, "gerber_upload_zip": archive.relative_to(out).as_posix(),
        "gerber_zip_sha256": sha(archive), "files_sha256": hashes, "file_aliases": aliases,
        "hardware_qualified": False, "scope": "Current enclosure-logo and MicheyHub V0.0 carrier export.",
    }
    (v / "export_integrity.json").write_text(json.dumps(integrity, indent=2) + "\n")
    print("Exported:", out, flush=True)


if __name__ == "__main__":
    main()
