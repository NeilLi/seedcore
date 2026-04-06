from __future__ import annotations

import json
from pathlib import Path

from seedcore.models.edge_telemetry import (
    EdgeTelemetryEnvelopeV0,
    SignedEdgeTelemetryRefV0,
    signed_telemetry_ref_from_envelope_v0,
)


def test_signed_telemetry_ref_fixture_matches_envelope_derived_refs() -> None:
    tests_dir = Path(__file__).resolve().parent
    env_paths = [
        tests_dir / "fixtures" / "edge_telemetry" / "sample_envelope_v0.json",
        tests_dir / "fixtures" / "edge_telemetry" / "sample_envelope_v0_weight.json",
    ]
    derived = [
        signed_telemetry_ref_from_envelope_v0(
            EdgeTelemetryEnvelopeV0.model_validate(json.loads(p.read_text(encoding="utf-8")))
        ).model_dump(mode="json")
        for p in env_paths
    ]
    shared_path = (
        tests_dir
        / "fixtures"
        / "demo"
        / "rct_signoff_v1"
        / "shared"
        / "signed_edge_telemetry_closure_refs.json"
    )
    shared = json.loads(shared_path.read_text(encoding="utf-8"))
    assert shared["telemetry_refs"] == derived
    SignedEdgeTelemetryRefV0.model_validate(shared["telemetry_refs"][0])
