"""Malformed build inputs cannot silently become a web-flashing review packet."""

import hashlib
import json

import pytest

from seedcore.robotics.fast_spine.release import prepare_release


@pytest.fixture
def build(tmp_path):
    root = tmp_path / "build"
    root.mkdir()
    (root / "project_description.json").write_text(
        json.dumps(
            {"target": "esp32s3", "idf_ver": "fixture-only", "project_name": "fixture"}
        )
    )
    (root / "flasher_args.json").write_text(
        json.dumps(
            {
                "extra_esptool_args": {"chip": "esp32s3"},
                "flash_files": {"0x0": "boot.bin", "0x1000": "app.bin"},
            }
        )
    )
    (root / "boot.bin").write_bytes(b"not firmware")
    (root / "app.bin").write_bytes(b"test fixture only")
    merged = b"synthetic test fixture" * 256
    (root / "merged.bin").write_bytes(merged)
    return {
        "build_dir": root,
        "output": tmp_path / "review",
        "merged_image": "merged.bin",
        "expected_sha256": hashlib.sha256(merged).hexdigest(),
        "source_revision": "a" * 40,
        "version": "0.0.0-test",
    }


def test_review_output_never_claims_release_qualification(build):
    report = prepare_release(**build)
    assert not report["release_ready"] and not report["hardware_tested"]
    manifest = json.loads((build["output"] / "candidate-manifest.json").read_text())
    assert manifest["builds"][0]["chipFamily"] == "ESP32-S3"
    assert "build_dir" not in str(report)
    with pytest.raises(ValueError, match="new review"):
        prepare_release(**build)


@pytest.mark.parametrize(
    "fault", ["wrong_target", "wrong_digest", "escape", "symlink", "overlap", "missing"]
)
def test_reject_invalid_builds_atomically(build, fault):
    root = build["build_dir"]
    if fault == "wrong_target":
        (root / "project_description.json").write_text('{"target":"esp32"}')
    elif fault == "wrong_digest":
        build["expected_sha256"] = "0" * 64
    elif fault == "escape":
        build["merged_image"] = "../outside.bin"
    elif fault == "symlink":
        (root / "merged.bin").unlink()
        (root / "merged.bin").symlink_to(root / "app.bin")
    elif fault == "overlap":
        (root / "boot.bin").write_bytes(b"x" * 5000)
    else:
        (root / "app.bin").unlink()
    with pytest.raises(ValueError):
        prepare_release(**build)
    assert not build["output"].exists()
