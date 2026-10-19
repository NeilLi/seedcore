#!/usr/bin/env python3
"""Recheck existing M0 candidates locally; never fetch, upgrade or qualify hardware."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PROFILE = "packages/robotics-profiles/microduck-sim-v1.json"


def review(runtime: Path, rl: Path):
    manifest = json.loads((ROOT / PROFILE).read_text())
    register = json.loads((ROOT / "packages/robotics-profiles/reviews/2026-10-19-m0-cw-d01.json").read_text())
    reviewed_inputs = []
    for pin in register["pin_inputs"]:
        artifact = ROOT / pin["path"]
        actual = hashlib.sha256(artifact.read_bytes()).hexdigest() if artifact.is_file() else None
        reviewed_inputs.append({"path": pin["path"], "expected_sha256": pin["sha256"], "actual_sha256": actual, "status": "match" if actual == pin["sha256"] else "missing_or_changed"})
    checks = []
    for key, repo in [("runtime", runtime), ("rl", rl)]:
        for filename, expected in manifest[key]["files"].items():
            result = subprocess.run(["git", "-C", str(repo), "show", f'{manifest[key]["revision"]}:{filename}'], capture_output=True)
            actual = hashlib.sha256(result.stdout).hexdigest() if result.returncode == 0 else None
            checks.append({"kind": key, "revision": manifest[key]["revision"], "path": filename, "expected_sha256": expected, "actual_sha256": actual, "status": "match" if actual == expected else "missing" if actual is None else "mismatch"})
    for key, path, expected in [
        ("body", manifest["body_manifest"], manifest["body_manifest_sha256"]),
        ("policy", manifest["policy"]["local_cache"], manifest["policy"]["sha256"]),
    ]:
        artifact = ROOT / path
        actual = hashlib.sha256(artifact.read_bytes()).hexdigest() if artifact.is_file() else None
        checks.append({"kind": key, "path": path, "expected_sha256": expected, "actual_sha256": actual, "status": "match" if actual == expected else "missing" if actual is None else "mismatch"})
    old = subprocess.run(["git", "-C", str(runtime), "cat-file", "-e", manifest["runtime"]["previous_documented_revision"] + "^{commit}"], capture_output=True)
    return {"scope": "local_candidate_pin_inventory", "physical_acceptance": False,
            "profile_sha256": hashlib.sha256((ROOT / PROFILE).read_bytes()).hexdigest(),
            "checks": checks, "reviewed_inputs": reviewed_inputs, "previous_runtime_revision_available": old.returncode == 0,
            "status": "pins_match" if all(item["status"] == "match" for item in checks + reviewed_inputs) else "incomplete_or_mismatched"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-repo", type=Path, default=ROOT.parent / "microduck")
    parser.add_argument("--rl-repo", type=Path, default=ROOT.parent / "microduck_rl")
    args = parser.parse_args()
    report = review(args.runtime_repo, args.rl_repo)
    target = ROOT / "artifacts/robotics/m0-cw-d01/pin-review.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(f'{report["status"]}: {len(report["checks"])} candidates; {target.relative_to(ROOT)}')
    raise SystemExit(0 if report["status"] == "pins_match" else 1)
