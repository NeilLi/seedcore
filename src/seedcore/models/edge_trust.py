"""Fixture-backed edge trust enrollment models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EDGE_TRUST_ENROLLMENT_VERSION = "seedcore.edge_trust_enrollment.v0"

DeviceProfile = Literal["simulator", "prototype_edge", "trusted_edge"]
DeviceStatus = Literal["active", "revoked", "quarantined"]
TrustAnchorType = Literal["software_dev_key", "tpm", "kms", "tee"]
AttestationLevel = Literal["prototype", "tpm_quote", "kms_derived"]
AssetAnchorType = Literal["nfc_scan", "qr_scan", "vision_fingerprint", "manual_fixture"]
ZoneEvidenceType = Literal["device_zone_claim", "gps_fix", "coordinate_geofence", "manual_fixture"]


def _strip_non_empty(value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError("field must be non-empty")
    return normalized


def _strip_list(values: list[str]) -> list[str]:
    normalized = [_strip_non_empty(value) for value in values]
    if not normalized:
        raise ValueError("list must contain at least one value")
    return normalized


class DeviceIdentity(BaseModel):
    """Enrolled physical or simulator endpoint identity."""

    model_config = ConfigDict(extra="forbid")

    device_id: str
    edge_node_ref: str
    device_profile: DeviceProfile
    hardware_fingerprint: str
    signer_key_ref: str
    attestation_level: AttestationLevel
    trusted_for_zones: list[str] = Field(default_factory=list)
    trusted_for_evidence: list[str] = Field(default_factory=list)
    status: DeviceStatus = "active"
    platform_family: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("device_id", "edge_node_ref", "hardware_fingerprint", "signer_key_ref", "attestation_level")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _strip_non_empty(value)

    @field_validator("trusted_for_zones", "trusted_for_evidence")
    @classmethod
    def _required_list_items(cls, values: list[str]) -> list[str]:
        return _strip_list(values)


class HardwareSignerRef(BaseModel):
    """Enrollment reference for an edge telemetry signing key."""

    model_config = ConfigDict(extra="forbid")

    signer_key_ref: str
    algorithm: str
    trust_anchor_type: TrustAnchorType
    public_key_fingerprint: str
    device_id: str
    valid_from: str
    valid_until: str | None = None
    revocation_id: str
    status: DeviceStatus = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "signer_key_ref",
        "algorithm",
        "public_key_fingerprint",
        "device_id",
        "valid_from",
        "revocation_id",
    )
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _strip_non_empty(value)


class AssetAnchor(BaseModel):
    """Asset binding observed by an enrolled device."""

    model_config = ConfigDict(extra="forbid")

    asset_ref: str
    product_ref: str | None = None
    anchor_type: AssetAnchorType
    anchor_hash: str
    observed_at: str
    telemetry_id: str | None = None
    edge_node_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("asset_ref", "anchor_hash", "observed_at")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _strip_non_empty(value)


class ZoneEvidence(BaseModel):
    """Place or authority-scope binding observed by an enrolled device."""

    model_config = ConfigDict(extra="forbid")

    zone_ref: str
    coordinate_ref: str | None = None
    evidence_type: ZoneEvidenceType
    observed_at: str
    confidence: float = 1.0
    telemetry_id: str | None = None
    edge_node_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("zone_ref", "observed_at")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _strip_non_empty(value)

    @field_validator("confidence")
    @classmethod
    def _valid_confidence(cls, value: float) -> float:
        if value < 0.0 or value > 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return value


class EdgeTrustEnrollmentBundle(BaseModel):
    """Small enrollment fixture consumed by the edge trust adapter."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["seedcore.edge_trust_enrollment.v0"] = EDGE_TRUST_ENROLLMENT_VERSION
    devices: list[DeviceIdentity] = Field(default_factory=list)
    signers: list[HardwareSignerRef] = Field(default_factory=list)
    asset_anchors: list[AssetAnchor] = Field(default_factory=list)
    zone_evidence: list[ZoneEvidence] = Field(default_factory=list)
    revoked_signer_key_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_unique_refs(self) -> EdgeTrustEnrollmentBundle:
        device_ids = [device.device_id for device in self.devices]
        edge_refs = [device.edge_node_ref for device in self.devices]
        signer_refs = [signer.signer_key_ref for signer in self.signers]
        if len(device_ids) != len(set(device_ids)):
            raise ValueError("device_id values must be unique")
        if len(edge_refs) != len(set(edge_refs)):
            raise ValueError("edge_node_ref values must be unique")
        if len(signer_refs) != len(set(signer_refs)):
            raise ValueError("signer_key_ref values must be unique")
        return self
