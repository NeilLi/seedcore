from __future__ import annotations

import json
from pathlib import Path

from seedcore.models.edge_telemetry import EdgeTelemetryEnvelopeV0


def test_edge_telemetry_envelope_v0_schema_matches_checked_in_file() -> None:
    """Fail on drift; regenerate only via `python scripts/tools/export_edge_telemetry_json_schema.py`."""
    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / "docs" / "schemas" / "edge_telemetry_envelope_v0.schema.json"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    live = EdgeTelemetryEnvelopeV0.model_json_schema()
    assert live == on_disk
