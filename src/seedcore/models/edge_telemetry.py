"""Versioned edge telemetry envelope (Workstream 3 — Q4 forensic evidence population)."""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator  # pyright: ignore[reportMissingImports]

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


class SignedEdgeTelemetryRefV0(BaseModel):
    """
    Frozen reference to a signed edge telemetry envelope (closure / receipt input).

    Carries digest binding fields only — not the full sample payload.
    """

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["seedcore.edge_telemetry_envelope.v0"] = EDGE_TELEMETRY_ENVELOPE_VERSION
    telemetry_id: str
    asset_ref: str
    edge_node_ref: str
    observed_at: str
    sensor_kind: SensorKindV0
    payload_sha256: str
    signer_key_ref: str

    @field_validator("telemetry_id", "asset_ref", "edge_node_ref", "observed_at", "payload_sha256", "signer_key_ref")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("signed telemetry ref fields must be non-empty")
        return normalized


def signed_telemetry_ref_from_envelope_v0(envelope: EdgeTelemetryEnvelopeV0) -> SignedEdgeTelemetryRefV0:
    """Build a closure-grade ref from a validated envelope (fixtures / exporters)."""
    payload_sha256 = str(envelope.payload_sha256 or "").strip()
    if not payload_sha256:
        raise ValueError("EdgeTelemetryEnvelopeV0.payload_sha256 is required for signed telemetry refs")
    signer_key_ref = str(envelope.signer.key_ref or "").strip()
    if not signer_key_ref:
        raise ValueError("EdgeTelemetryEnvelopeV0.signer.key_ref is required for signed telemetry refs")
    return SignedEdgeTelemetryRefV0(
        telemetry_id=envelope.telemetry_id,
        asset_ref=envelope.asset_ref,
        edge_node_ref=envelope.edge_node_ref,
        observed_at=envelope.observed_at,
        sensor_kind=envelope.sensor_kind,
        payload_sha256=payload_sha256,
        signer_key_ref=signer_key_ref,
    )


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
