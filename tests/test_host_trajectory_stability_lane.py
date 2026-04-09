from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_optional_host_lane_runs_and_writes_artifact(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "host" / "verify_trajectory_stability_scaffold.sh"
    artifact_dir = tmp_path / "traj"
    proc = subprocess.run(
        [
            "bash",
            str(script),
            "--runs",
            "1",
            "--perturbations",
            "memory_order_shuffle",
            "--artifact-dir",
            str(artifact_dir),
        ],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        check=True,
    )
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    summary_line = next(line for line in lines if line.startswith("[SUMMARY] "))
    summary = json.loads(summary_line[len("[SUMMARY] ") :])
    assert summary["runs"] == 1
    artifacts = list(artifact_dir.glob("trajectory_stability_*.json"))
    assert artifacts
