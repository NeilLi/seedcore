#!/usr/bin/env python3
"""Emit JSON Schema for EdgeTelemetryEnvelopeV0 (execution plan Window E)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from seedcore.models.edge_telemetry import EdgeTelemetryEnvelopeV0  # noqa: E402


def main() -> int:
    schema = EdgeTelemetryEnvelopeV0.model_json_schema()
    out = _REPO_ROOT / "docs" / "schemas" / "edge_telemetry_envelope_v0.schema.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
