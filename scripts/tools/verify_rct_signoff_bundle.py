#!/usr/bin/env python3
"""Verify the pinned RCT Slice 1 live sign-off bundle matches manifest.json sha256 entries."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE_ROOT = REPO_ROOT / "tests" / "fixtures" / "demo" / "rct_signoff_v1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_bundle(*, bundle_root: Path) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    manifest_path = bundle_root / "manifest.json"
    if not manifest_path.is_file():
        return [f"missing_manifest:{manifest_path}"], {}
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("manifest_missing_artifacts")
        return errors, manifest

    for entry in artifacts:
        if not isinstance(entry, dict):
            errors.append(f"invalid_artifact_entry:{entry!r}")
            continue
        rel = str(entry.get("path") or "").strip()
        expected = str(entry.get("sha256") or "").strip().lower()
        if not rel or not expected:
            errors.append(f"artifact_missing_path_or_sha:{entry!r}")
            continue
        target = bundle_root / rel
        if not target.is_file():
            errors.append(f"missing_file:{rel}")
            continue
        actual = _sha256_file(target).lower()
        if actual != expected:
            errors.append(f"sha256_mismatch:{rel} expected={expected} actual={actual}")

    return errors, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle-root",
        type=Path,
        default=DEFAULT_BUNDLE_ROOT,
        help=f"Directory containing manifest.json and artifact paths (default: {DEFAULT_BUNDLE_ROOT})",
    )
    args = parser.parse_args()
    bundle_root = args.bundle_root.resolve()
    errors, manifest = verify_bundle(bundle_root=bundle_root)
    if errors:
        print("FAIL rct sign-off bundle verification")
        for line in errors:
            print(f"  - {line}")
        return 1
    version = manifest.get("bundle_version", "?")
    capture = manifest.get("source_capture", "?")
    print(f"PASS rct sign-off bundle verification (bundle_version={version} source_capture={capture})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
