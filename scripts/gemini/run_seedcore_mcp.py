#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from seedcore.plugin.gemini_stdio import main
except ModuleNotFoundError as exc:  # pragma: no cover - import wiring guard
    print(
        "Seedcore Gemini MCP launcher could not import the Seedcore package. "
        "Make sure this extension is launched from a Python environment with Seedcore dependencies installed.",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


if __name__ == "__main__":
    raise SystemExit(main())
