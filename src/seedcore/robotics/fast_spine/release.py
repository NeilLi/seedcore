"""Prepare a local firmware review packet. This never qualifies or flashes firmware."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile


def _snapshot(root: Path, name: str, limit: int = 16 * 1024 * 1024) -> bytes:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("build inputs must use contained relative paths")
    path = root / relative
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("symlinked build inputs are not accepted")
    if not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError("missing, empty or oversized build input")
    data = path.read_bytes()
    if len(data) > limit:
        raise ValueError("build input grew beyond its size bound")
    return data


def prepare_release(
    build_dir: Path,
    output: Path,
    *,
    merged_image: str,
    expected_sha256: str,
    source_revision: str,
    version: str,
):
    """Snapshot a real build into a new, unpublished review directory.

    Hashes and metadata establish packet integrity, not firmware correctness.
    ESP-IDF v4+ needs an independently prepared/patched merged image for Web Tools.
    No synthetic image, flashing command or signing key is created here.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", source_revision):
        raise ValueError("a full source revision is required")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("an independently supplied merged-image SHA-256 is required")
    if not re.fullmatch(r"[0-9][0-9A-Za-z.+-]{0,63}", version):
        raise ValueError("invalid release candidate version")
    if output.exists() or output.is_symlink():
        raise ValueError("output must be a new review directory")
    if any(
        p.is_symlink()
        for p in (build_dir, *build_dir.parents, output.parent, *output.parent.parents)
    ):
        raise ValueError("symlinked build/output paths are not accepted")
    root = build_dir.resolve(strict=True)
    description_bytes = _snapshot(root, "project_description.json", 2 * 1024 * 1024)
    args_bytes = _snapshot(root, "flasher_args.json", 2 * 1024 * 1024)
    description, args = json.loads(description_bytes), json.loads(args_bytes)
    if (
        description.get("target") != "esp32s3"
        or args.get("extra_esptool_args", {}).get("chip") != "esp32s3"
    ):
        raise ValueError("both build metadata files must identify esp32s3")
    if not description.get("idf_ver") or not description.get("project_name"):
        raise ValueError("missing build provenance")
    files = args.get("flash_files")
    if not isinstance(files, dict) or not 2 <= len(files) <= 8:
        raise ValueError("expected a bounded bootloader/partition/application build")
    snapshots, parts, last_end = {}, [], 0
    try:
        ordered = sorted((int(offset, 0), name) for offset, name in files.items())
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid flash offset map") from exc
    for index, (offset, name) in enumerate(ordered):
        data = _snapshot(root, name)
        if offset < last_end or offset % 4096 or offset + len(data) > 16 * 1024 * 1024:
            raise ValueError("overlapping, unaligned or oversized flash layout")
        last_end = offset + len(data)
        destination = f"part-{index}.bin"
        snapshots[destination] = data
        parts.append(
            {
                "path": destination,
                "offset": offset,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    merged = _snapshot(root, merged_image)
    if hashlib.sha256(merged).hexdigest() != expected_sha256 or len(merged) < last_end:
        raise ValueError("merged image digest/coverage mismatch")
    # Image format, flash settings, secure boot and enrollment require separate review.
    snapshots["merged-firmware.bin"] = merged
    manifest = {
        "name": "SeedCore Fast Spine review candidate",
        "version": version,
        "new_install_prompt_erase": True,
        "builds": [
            {
                "chipFamily": "ESP32-S3",
                "improv": False,
                "parts": [{"path": "merged-firmware.bin", "offset": 0}],
            }
        ],
    }
    report = {
        "schema_version": "seedcore.fast-spine.release-review.v1",
        "release_ready": False,
        "published": False,
        "hardware_tested": False,
        "declared_source_revision": source_revision,
        "version": version,
        "build_metadata_sha256": {
            "project_description.json": hashlib.sha256(description_bytes).hexdigest(),
            "flasher_args.json": hashlib.sha256(args_bytes).hexdigest(),
        },
        "merged_image_sha256": expected_sha256,
        "parts": parts,
        "open_gates": [
            "source/build reproducibility and dependency licenses",
            "merged image format, flash settings and board partition review",
            "device identity enrollment and all motor ingress isolation",
            "single-servo then three-servo watchdog/stop/fault measurements",
            "secure boot/update/rollback and interrupted-flash recovery",
            "named board/browser/managed-host acceptance and release review",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".spine-review-", dir=output.parent))
    try:
        for name, data in snapshots.items():
            (temporary / name).write_bytes(data)
        (temporary / "candidate-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
        (temporary / "review.json").write_text(json.dumps(report, indent=2) + "\n")
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return report
