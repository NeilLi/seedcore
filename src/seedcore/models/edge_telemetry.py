"""Versioned edge telemetry envelope (Workstream 3 — Q4 forensic evidence population)."""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field  # pyright: ignore[reportMissingImports]

EDGE_TELEMETRY_ENVELOPE_VERSION = "seedcore.edge_telemetry_envelope.v0"

SensorKindV0 = Literal["motor_torque", "weight_cell", "temperature", "generic"]


class EdgeTelemetrySampleV0(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t_offset_ms: float = Field(default=0.0, description="Milliseconds relative to observed_at.")
    value: float


class EdgeTelemetrySignerV0(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_ref: str
    algorithm: str = "ed25519"
    signature_b64: str


class EdgeTelemetryEnvelopeV0(BaseModel):
    """
    Cryptographically signed bundle of edge sensor readings bound to an asset.

    Intended to hash into physical-presence fingerprint components at twin closure.
    """

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["seedcore.edge_telemetry_envelope.v0"] = EDGE_TELEMETRY_ENVELOPE_VERSION
    telemetry_id: str
    edge_node_ref: str
    asset_ref: str
    observed_at: str
    sensor_kind: SensorKindV0
    samples: List[EdgeTelemetrySampleV0] = Field(default_factory=list)
    payload_sha256: str | None = Field(
        default=None,
        description="Optional precomputed canonical JSON hash of samples + metadata (excluding signature).",
    )
    nonce: str
    signer: EdgeTelemetrySignerV0
