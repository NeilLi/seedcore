"""Thin edge trust adapter for fixture-backed telemetry closure checks."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence

from seedcore.models.edge_telemetry import (
    EDGE_TELEMETRY_ENVELOPE_VERSION,
    SignedEdgeTelemetryRefV0,
)
from seedcore.models.edge_trust import (
    DeviceIdentity,
    EdgeTrustEnrollmentBundle,
    HardwareSignerRef,
    ZoneEvidence,
)


class EdgeTrustAdapter(Protocol):
    """Lookup surface for enrolled edge devices and hardware signers."""

    def get_device(self, edge_node_ref: str) -> DeviceIdentity | None:
        ...

    def get_signer(self, key_ref: str) -> HardwareSignerRef | None:
        ...


class FixtureEdgeTrustAdapter:
    """In-memory adapter backed by an enrollment fixture."""

    def __init__(self, enrollment: Mapping[str, Any] | EdgeTrustEnrollmentBundle) -> None:
        self.enrollment = (
            enrollment
            if isinstance(enrollment, EdgeTrustEnrollmentBundle)
            else EdgeTrustEnrollmentBundle.model_validate(dict(enrollment))
        )
        self._devices_by_edge = {
            device.edge_node_ref: device
            for device in self.enrollment.devices
        }
        self._devices_by_id = {
            device.device_id: device
            for device in self.enrollment.devices
        }
        self._signers_by_key = {
            signer.signer_key_ref: signer
            for signer in self.enrollment.signers
        }

    def get_device(self, edge_node_ref: str) -> DeviceIdentity | None:
        return self._devices_by_edge.get(str(edge_node_ref).strip())

    def get_device_by_id(self, device_id: str) -> DeviceIdentity | None:
        return self._devices_by_id.get(str(device_id).strip())

    def get_signer(self, key_ref: str) -> HardwareSignerRef | None:
        return self._signers_by_key.get(str(key_ref).strip())


def validate_edge_trust_telemetry_refs(
    *,
    telemetry_refs: Sequence[Mapping[str, Any]],
    enrollment: Mapping[str, Any] | EdgeTrustEnrollmentBundle,
    expected_asset_ref: str | None = None,
    expected_zone_ref: str | None = None,
    required_trust_anchor_types: Sequence[str] | None = None,
    required_device_profiles: Sequence[str] | None = None,
    reference_time: str | None = None,
    max_age_seconds: int | None = None,
    observed_not_before: str | None = None,
    observed_not_after: str | None = None,
    replayed_payload_hashes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Validate signed telemetry refs against an enrollment fixture.

    This is deliberately fixture-only. It validates enrollment posture and
    signer/zone/freshness claims, but it does not generate quotes or reach out
    to a TPM/KMS/TEE.
    """

    try:
        adapter = FixtureEdgeTrustAdapter(enrollment)
    except Exception as exc:
        return _failure("invalid_edge_trust_enrollment", detail=str(exc))
    fixture = adapter.enrollment

    signed_refs = []
    for ref in telemetry_refs:
        if not isinstance(ref, Mapping) or ref.get("contract_version") != EDGE_TELEMETRY_ENVELOPE_VERSION:
            continue
        try:
            signed_refs.append(SignedEdgeTelemetryRefV0.model_validate(dict(ref)))
        except Exception as exc:
            return _failure("invalid_signed_edge_telemetry_ref", detail=str(exc))

    result: dict[str, Any] = {
        "verified": True,
        "error": None,
        "signed_ref_count": len(signed_refs),
        "device_ids": [],
        "signer_key_refs": [],
        "trust_anchor_types": [],
    }
    if not signed_refs:
        return result

    required_anchors = {
        str(item).strip()
        for item in (required_trust_anchor_types or [])
        if str(item).strip()
    }
    required_profiles = {
        str(item).strip()
        for item in (required_device_profiles or [])
        if str(item).strip()
    }
    replayed_hashes = {
        str(item).strip()
        for item in (replayed_payload_hashes or [])
        if str(item).strip()
    }
    normalized_expected_asset = _normalize_asset_ref(expected_asset_ref)
    reference_dt = _parse_dt(reference_time) if reference_time else None
    not_before_dt = _parse_dt(observed_not_before) if observed_not_before else None
    not_after_dt = _parse_dt(observed_not_after) if observed_not_after else None

    for ref in signed_refs:
        if normalized_expected_asset and _normalize_asset_ref(ref.asset_ref) != normalized_expected_asset:
            return _failure("telemetry_asset_mismatch", telemetry_id=ref.telemetry_id)

        if ref.payload_sha256 in replayed_hashes:
            return _failure("telemetry_replay_detected", telemetry_id=ref.telemetry_id)

        device = adapter.get_device(ref.edge_node_ref)
        if device is None:
            return _failure("telemetry_edge_node_unknown", telemetry_id=ref.telemetry_id)
        if device.status == "revoked":
            return _failure("telemetry_device_revoked", telemetry_id=ref.telemetry_id)
        if device.status == "quarantined":
            return _failure("telemetry_device_quarantined", telemetry_id=ref.telemetry_id)
        if required_profiles and device.device_profile not in required_profiles:
            return _failure(
                "telemetry_device_profile_mismatch",
                telemetry_id=ref.telemetry_id,
                device_profile=device.device_profile,
                required_device_profiles=sorted(required_profiles),
            )
        if ref.sensor_kind not in device.trusted_for_evidence:
            return _failure(
                "telemetry_evidence_kind_mismatch",
                telemetry_id=ref.telemetry_id,
                sensor_kind=ref.sensor_kind,
            )
        if device.signer_key_ref != ref.signer_key_ref:
            return _failure("telemetry_signer_device_mismatch", telemetry_id=ref.telemetry_id)

        signer = adapter.get_signer(ref.signer_key_ref)
        if signer is None:
            return _failure("telemetry_signer_unknown", telemetry_id=ref.telemetry_id)
        if signer.status == "revoked" or signer.signer_key_ref in fixture.revoked_signer_key_refs:
            return _failure("telemetry_signer_revoked", telemetry_id=ref.telemetry_id)
        if signer.status == "quarantined":
            return _failure("telemetry_signer_quarantined", telemetry_id=ref.telemetry_id)
        if signer.device_id != device.device_id:
            return _failure("telemetry_signer_device_mismatch", telemetry_id=ref.telemetry_id)
        if required_anchors and signer.trust_anchor_type not in required_anchors:
            return _failure(
                "telemetry_trust_anchor_insufficient",
                telemetry_id=ref.telemetry_id,
                trust_anchor_type=signer.trust_anchor_type,
                required_trust_anchor_types=sorted(required_anchors),
            )

        if expected_zone_ref:
            if expected_zone_ref not in device.trusted_for_zones:
                return _failure("telemetry_scope_mismatch", telemetry_id=ref.telemetry_id)
            zone = _matching_zone_evidence(fixture.zone_evidence, ref.telemetry_id, ref.edge_node_ref)
            if zone is None:
                return _failure("telemetry_zone_evidence_missing", telemetry_id=ref.telemetry_id)
            if zone.zone_ref != expected_zone_ref:
                return _failure("telemetry_scope_mismatch", telemetry_id=ref.telemetry_id)

        observed_dt = _parse_dt(ref.observed_at)
        if not_before_dt and observed_dt < not_before_dt:
            return _failure("telemetry_outside_authority_window", telemetry_id=ref.telemetry_id)
        if not_after_dt and observed_dt > not_after_dt:
            return _failure("telemetry_outside_authority_window", telemetry_id=ref.telemetry_id)
        if reference_dt and max_age_seconds is not None:
            age = (reference_dt - observed_dt).total_seconds()
            if age < 0:
                return _failure("telemetry_outside_authority_window", telemetry_id=ref.telemetry_id)
            if age > max_age_seconds:
                return _failure("telemetry_too_stale", telemetry_id=ref.telemetry_id)

        result["device_ids"].append(device.device_id)
        result["signer_key_refs"].append(signer.signer_key_ref)
        result["trust_anchor_types"].append(signer.trust_anchor_type)

    result["device_ids"] = sorted(set(result["device_ids"]))
    result["signer_key_refs"] = sorted(set(result["signer_key_refs"]))
    result["trust_anchor_types"] = sorted(set(result["trust_anchor_types"]))
    return result


def _failure(error: str, **details: Any) -> dict[str, Any]:
    return {"verified": False, "error": error, **details}


def _normalize_asset_ref(value: str | None) -> str:
    normalized = str(value or "").strip()
    if normalized.startswith("asset:"):
        return normalized.split(":", 1)[1]
    return normalized


def _parse_dt(value: str) -> datetime:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("datetime value must be non-empty")
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _matching_zone_evidence(
    zone_evidence: Sequence[ZoneEvidence],
    telemetry_id: str,
    edge_node_ref: str,
) -> ZoneEvidence | None:
    for zone in zone_evidence:
        if zone.telemetry_id and zone.telemetry_id == telemetry_id:
            return zone
    for zone in zone_evidence:
        if zone.edge_node_ref and zone.edge_node_ref == edge_node_ref:
            return zone
    return None
