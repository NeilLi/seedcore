from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from seedcore.models.edge_telemetry import (
    EDGE_TELEMETRY_ENVELOPE_VERSION,
    EdgeTelemetryEnvelopeV0,
    signed_telemetry_ref_from_envelope_v0,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "edge_telemetry" / "sample_envelope_v0.json"
_FIXTURE_WEIGHT = Path(__file__).resolve().parent / "fixtures" / "edge_telemetry" / "sample_envelope_v0_weight.json"


def test_edge_telemetry_envelope_v0_round_trip_from_fixture() -> None:
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    env = EdgeTelemetryEnvelopeV0.model_validate(raw)
    assert env.contract_version == EDGE_TELEMETRY_ENVELOPE_VERSION
    assert env.sensor_kind == "motor_torque"
    assert len(env.samples) == 2
    assert env.signer.key_ref.startswith("kms:")
    ref = signed_telemetry_ref_from_envelope_v0(env)
    assert ref.telemetry_id == env.telemetry_id
    assert ref.payload_sha256 == env.payload_sha256


def test_edge_telemetry_weight_cell_fixture_round_trip() -> None:
    raw = json.loads(_FIXTURE_WEIGHT.read_text(encoding="utf-8"))
    env = EdgeTelemetryEnvelopeV0.model_validate(raw)
    assert env.sensor_kind == "weight_cell"
    signed_telemetry_ref_from_envelope_v0(env)


def test_edge_telemetry_envelope_rejects_unknown_sensor_kind() -> None:
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    raw["sensor_kind"] = "invalid_kind"
    with pytest.raises(ValidationError):
        EdgeTelemetryEnvelopeV0.model_validate(raw)


def test_edge_telemetry_envelope_rejects_wrong_contract_version() -> None:
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    raw["contract_version"] = "seedcore.edge_telemetry_envelope.v1"
    with pytest.raises(ValidationError):
        EdgeTelemetryEnvelopeV0.model_validate(raw)
