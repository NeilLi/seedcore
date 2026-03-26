from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_phase0_contract_freeze_gate_passes() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts/tools/verify_phase0_contract_freeze.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout
