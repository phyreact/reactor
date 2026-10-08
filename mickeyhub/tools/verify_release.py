"""Verify delivered evidence, update the manifest and write local checksums."""
from pathlib import Path
from urllib.parse import unquote, urlsplit
import argparse
import csv
import hashlib
import json
import re
import struct
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent.parent


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    return json.loads((HERE / path).read_text())


def unchanged_blocks_sha256(text, excluded_ids, excluded_kinds):
    """Hash raw top-level KiCad blocks outside the declared branding edits."""
    depth, quoted, escaped, start = 0, False, False, None
    kept = []
    for index, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "(":
            depth += 1
            if depth == 2:
                start = index
        elif char == ")":
            if depth == 2:
                block = text[start:index + 1]
                kind = block[1:].split(None, 1)[0].rstrip(")")
                if kind not in excluded_kinds and not any(f'"{key}"' in block for key in excluded_ids):
                    kept.append(block)
            depth -= 1
    assert depth == 0
    return hashlib.sha256("\0".join(kept).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-local-videos", action="store_true",
                        help="Also verify the optional MP4 in the ignored local backup.")
    args = parser.parse_args()
    errors = []
    portable = HERE / "electronics/kicad/box_carrier_modules_r2.kicad_pcb"
    relocation = read("electronics/library_relocation.json")
    branding = read("electronics/branding.json")
    branded = {row["file"]: row for row in branding["files"]}
    assert branding["board_marking"] == "MicheyHub V0.0"
    assert sha(HERE / branding["logo"]["source"]) == branding["logo"]["source_sha256"]
    assert sha(HERE / branding["logo"]["reference"]) == branding["logo"]["reference_sha256"]
    board_text = portable.read_text()
    assert f'(gr_text "{branding["board_marking"]}"' in board_text
    assert '611217c5-445b-4966-8e69-1b4f2b47572e' not in board_text
    for identifier in branding["logo"]["graphic_uuids"]:
        assert board_text.count(f'"{identifier}"') == 1
    for row in branding["files"]:
        path = HERE / row["file"]
        assert sha(path) == row["output_sha256"]
        assert unchanged_blocks_sha256(
            path.read_text(), row["excluded_graphic_uuids"], row["excluded_metadata_blocks"]
        ) == row["unchanged_blocks_sha256"], row["file"]
    for row in relocation["changes"]:
        if row["file"] in branded:
            assert branded[row["file"]]["input_sha256"] == row["output_sha256"]
        else:
            assert sha(HERE / row["file"]) == row["output_sha256"]
    optional_3d_references = []
    for path in re.findall(r'\(model\s+"([^"]+)"', portable.read_text()):
        resolved = path.replace("${KIPRJMOD}", str(portable.parent))
        if "${" in resolved or not Path(resolved).is_file():
            optional_3d_references.append(path)

    drc, erc = read("electronics/validation/drc.json"), read("electronics/validation/erc.json")
    for key in ["violations", "unconnected_items", "schematic_parity"]:
        if drc.get(key):
            errors.append("DRC: " + key)
    if any(sheet.get("violations") for sheet in erc.get("sheets", [])):
        errors.append("ERC violations")
    adapters = read("electronics/daughterboards/manifest.json")
    for row in adapters["files"]:
        assert sha(HERE / "electronics" / row["file"]) == row["sha256"], row["file"]
    adapter_checks = read("electronics/validation/adapters.json")
    assert adapter_checks["passed"]
    for row in adapter_checks["checks"]:
        assert sha(HERE / row["source_file"]) == row["source_sha256"]
        assert row["violations"] == 0, row["source_file"]

    stl = read("mechanical/validation/stl_export_checks.json")
    assert stl["passed"] and len(stl["files"]) == 15
    for row in stl["files"]:
        assert row["passed"] and sha(HERE / "mechanical/stl" / row["file"]) == row["sha256"]
    for row in read("mechanical/fit_samples/stl_export_checks.json")["files"]:
        assert row["passed"] and sha(HERE / "mechanical/fit_samples" / row["file"]) == row["sha256"]

    manufacturing = read("manufacturing/validation/export_integrity.json")
    assert manufacturing["pcb_sha256"] == sha(portable)
    assert manufacturing["board_marking"] == branding["board_marking"]
    gerber_zip = HERE / "manufacturing" / manufacturing["gerber_upload_zip"]
    assert sha(gerber_zip) == manufacturing["gerber_zip_sha256"]
    with zipfile.ZipFile(gerber_zip) as archive:
        assert archive.testzip() is None
    manufacturing_matches = 0
    for path, digest in manufacturing["files_sha256"].items():
        target = manufacturing.get("file_aliases", {}).get(path, path)
        file = HERE / "manufacturing" / target
        assert file.is_file() and sha(file) == digest, path
        manufacturing_matches += 1
    references = read("components/reference_aliases.json")
    for original, target in references["aliases"].items():
        assert sha(HERE / target) == references["sha256"][original], target

    firmware = read("firmware/validation/firmware_validation.json")
    for path, digest in firmware["source_hashes"].items():
        assert sha(HERE / "firmware" / path) == digest, path
    for row in firmware["builds"]:
        assert sha(HERE / "firmware/verified_builds" / Path(row["file"]).name) == row["sha256"]
    assert (HERE / "firmware/s3/sdkconfig.defaults").is_file()
    metadata_cleanup = read("validation/metadata_cleanup.json")
    assert metadata_cleanup["passed"]
    assert metadata_cleanup["geometry_animation_pixels_and_executable_code_unchanged"]
    for row in metadata_cleanup["files"]:
        assert sha(HERE / row["file"]) == row["output_sha256"], row["file"]

    appearance = read("validation/appearance.json")
    animation = read("validation/animation_checks.json")
    video = read("validation/video.json")
    preview = read("validation/preview.json")
    components = read("components/catalog.json")
    assert all(d["passed"] for d in [appearance, animation, video])
    source_sha = sha(HERE / "mickeyhub.blend")
    animation_sha = animation["animation_sha256"]
    assert source_sha == appearance["model_sha256"] == animation["source_sha256"] == video["source_model_sha256"] == components["source_model_sha256"]
    assert animation_sha == video["animation_model_sha256"]
    assert not animation["animation_model_in_repository"]
    assert not video["animation_model_in_repository"]
    assert video["storage"] == "local_backup" and not video["included_in_repository"]
    assert preview["passed"] and not preview["source_movie_in_repository"]
    gif = HERE / preview["file"]
    assert sha(gif) == preview["sha256"]
    with gif.open("rb") as stream:
        header = stream.read(10)
    assert header[:6] in (b"GIF87a", b"GIF89a")
    assert struct.unpack("<HH", header[6:10]) == (preview["width"], preview["height"])
    assert preview["source_movie_sha256"] == video["movie_sha256"]
    if args.check_local_videos:
        movie = HERE.parent / "memory_backups/videos/mickeyhub/mickeyhub-animation.mp4"
        if not movie.is_file():
            parser.error("The optional local MP4 is absent; omit --check-local-videos for a public checkout.")
        assert sha(movie) == video["movie_sha256"]
    assert components["count"] == len(components["components"]) == 46
    storyboard = read("media/mickeyhub-animation.json")["modules"]
    assert set(storyboard) == {row["id"] for row in components["components"]}
    for row in components["components"]:
        assert row["source_objects"] == storyboard[row["id"]]["objects"]
        assert row["name"] == storyboard[row["id"]]["name"]
        assert row["description"] == storyboard[row["id"]]["description"]
        assert len(row["dimensions_mm"]) == 3 and all(value >= 0 for value in row["dimensions_mm"])
        assert not any(key in row for key in ("file", "sha256", "bytes"))

    primary_docs = [
        "README.md", "THIRD_PARTY.md", "media/README.md", "docs/CURRENT_STATUS.md", "docs/BUILD.md",
        "mechanical/README.md", "electronics/README.md", "manufacturing/README.md",
        "simulation/README.md", "components/README.md",
    ]
    future_files = {"release_manifest.json", "checksums.sha256"}
    for name in primary_docs:
        file = HERE / name
        text = file.read_text()
        assert "micmouse" not in text.lower()
        for link in re.findall(r'\]\(([^)]+)\)', text):
            if urlsplit(link).scheme or link.startswith("#"):
                continue
            target = unquote(urlsplit(link).path)
            if target in future_files:
                continue
            if not (file.parent / target).exists():
                errors.append(f"Broken link in {name}: {link}")
    with (HERE / "electronics/bom/mickeyhub-board-bom.csv").open(newline="") as stream:
        bom_lines = len(list(csv.DictReader(stream)))
    assert bom_lines == 57
    assert not errors, errors

    report = dict(
        passed=True, product="mickeyhub",
        labelled_assemblies=46, included_component_GLB_files=0,
        included_integrated_Blender_files=1, printable_STL_files=15, BOM_lines=bom_lines,
        pcb_non_branding_blocks_preserved=True,
        pcb_marking=branding["board_marking"], pcb_logo_verified=True,
        adapter_native_checks_verified=len(adapter_checks["checks"]),
        metadata_sanitized_files_verified=len(metadata_cleanup["files"]),
        current_manufacturing_files_verified=manufacturing_matches,
        canonical_reference_files_verified=len(references["aliases"]),
        firmware_sources_verified=len(firmware["source_hashes"]), firmware_builds_verified=len(firmware["builds"]),
        drc_violations=0, erc_violations=0, unconnected_items=0, schematic_parity_issues=0,
        pcb_3d_reference_models_included=False,
        optional_pcb_3d_references_not_bundled=sorted(set(optional_3d_references)),
        primary_document_links_resolved=True,
        complete_model_sha256=source_sha, archived_animation_model_sha256=animation_sha,
        public_gif_preview=preview, archived_video_evidence=video,
        hardware_qualified=False, remote_release_published=False,
    )
    (HERE / "validation/release_checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    files = []
    candidates = subprocess.check_output(
        ["git", "-C", str(HERE), "ls-files", "--cached", "--others",
         "--exclude-standard", "-z"]).decode().strip("\0").split("\0")
    for name in sorted(set(candidates) - {""}):
        file = HERE / name
        if not file.is_file() or file.name in future_files:
            continue
        assert file.suffix.lower() not in {
            ".glb", ".step", ".stp", ".wrl", ".dxf", ".obj", ".fbx", ".ply", ".3mf"
        }, name
        assert file.suffix.lower() != ".blend" or name == "mickeyhub.blend", name
        files.append(dict(path=name, bytes=file.stat().st_size, sha256=sha(file)))
    manifest = dict(
        product="mickeyhub", revision="2026-10-08-design-candidate",
        status="complete_local_design_delivery_hardware_unqualified",
        geometry_revision="wide_bearing_halo_v7b", electrical_revision="BOX R2.1R",
        appearance="Uniform dark graphite enclosure except unchanged LED ring",
        file_count=len(files), total_bytes=sum(row["bytes"] for row in files), files=files,
        excluded=["MP4 renders", "component GLBs and separate CAD reference models",
                  "intermediate Blender projects and modeling tools", "Git-ignored files",
                  "local memory_backups", "local checksums.sha256 lists",
                  "superseded scripts and duplicate sources"],
        verification="validation/release_checks.json",
        open_engineering_items="docs/CURRENT_STATUS.md",
        remote_release_published=False, hardware_qualified=False,
        note="Manifest lists delivered files excluding itself; checksums.sha256 is generated locally and is not committed.",
    )
    manifest_file = HERE / "release_manifest.json"
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    lines = [f"{row['sha256']}  {row['path']}" for row in files]
    lines.append(f"{sha(manifest_file)}  release_manifest.json")
    (HERE / "checksums.sha256").write_text("\n".join(lines) + "\n")
    print(json.dumps(dict(passed=True, files=len(files), megabytes=round(manifest["total_bytes"]/1e6, 1),
                          integrated_Blender_files=1, labelled_assemblies=46, STL=15, BOM=bom_lines,
                          gif_seconds=preview["duration_seconds"],
                          local_video_checked=args.check_local_videos)))


if __name__ == "__main__":
    main()
