from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_rct_signoff_bundle_manifest_matches_files() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "tools" / "verify_rct_signoff_bundle.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS rct sign-off bundle verification" in result.stdout
