"""Strict, non-authoritative visual-evidence contracts for rare-shoe RCT.

The models freeze capture, processing, fingerprint, and comparison records.
They describe evidence only: they cannot mint execution authority, mutate
custody, clear quarantine, or close a verifier job.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VISUAL_CAPTURE_BINDING_VERSION = "seedcore.visual_capture_binding.v0"
VISUAL_EVIDENCE_OBSERVATION_VERSION: Literal[
    "seedcore.visual_evidence_observation.v0"
] = "seedcore.visual_evidence_observation.v0"
VISUAL_EVIDENCE_COMPARISON_VERSION: Literal[
    "seedcore.visual_evidence_comparison.v0"
] = "seedcore.visual_evidence_comparison.v0"
VISUAL_EVIDENCE_REPLAY_VERSION: Literal["seedcore.visual_evidence_replay.v0"] = (
    "seedcore.visual_evidence_replay.v0"
)
VISUAL_EVIDENCE_REASON_CODES = frozenset(
    {
        "SPATIAL_FINGERPRINT_MISMATCH",
        "CONDITION_DRIFT_DETECTED",
        "FORENSIC_VIDEO_BINDING_INVALID",
        "HARDWARE_ANCHOR_MISMATCH",
        "DYNAMIC_NFC_PROOF_INVALID",
        "TELEMETRY_STALE",
        "CROSS_ASSET_REPLAY",
        "VISUAL_EVIDENCE_REQUIRED",
        "VISUAL_CAPTURE_BINDING_INVALID",
        "VISUAL_RAW_CAPTURE_MISSING",
        "VISUAL_CAPTURE_INSUFFICIENT_COVERAGE",
        "VISUAL_PIPELINE_PROFILE_NOT_ADMITTED",
        "VISUAL_GENERATIVE_TRANSFORM_DETECTED",
        "VISUAL_COMPARISON_UNCALIBRATED",
    }
)
VISUAL_MISMATCH_REASON_CODES = frozenset(
    {
        "SPATIAL_FINGERPRINT_MISMATCH",
        "CONDITION_DRIFT_DETECTED",
    }
)

_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class VisualCapturePhase(str, Enum):
    REGISTRATION = "registration"
    HANDOFF = "handoff"
    DELIVERY = "delivery"


class VisualEvidenceOutcome(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    ANOMALY_FLAGGED = "ANOMALY_FLAGGED"


class VisualEvidenceDisposition(str, Enum):
    ACCEPTED = "accepted"
    DENY = "deny"
    REVIEW_REQUIRED = "review_required"
    QUARANTINE = "quarantine"


class ClientIntegrityV0(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: str = Field(min_length=1)
    assertion_ref: str = Field(min_length=1)
    client_data_hash: str
    verifier_disposition: Literal["verified", "invalid", "unavailable"]

    @field_validator("client_data_hash")
    @classmethod
    def validate_client_data_hash(cls, value: str) -> str:
        return _validate_sha256(value)


class PhysicalAnchorBindingV0(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required: bool
    nfc_proof_ref: str | None = None
    binding_disposition: Literal["verified", "invalid", "missing", "not_required"]

    @model_validator(mode="after")
    def validate_required_ref(self) -> "PhysicalAnchorBindingV0":
        if self.required and not self.nfc_proof_ref:
            raise ValueError("required physical anchor must include nfc_proof_ref")
        if not self.required and self.binding_disposition != "not_required":
            raise ValueError(
                "optional physical anchor must use not_required disposition"
            )
        return self


class RawCaptureManifestV0(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_ref: str = Field(min_length=1)
    payload_sha256: str
    frame_count: int = Field(ge=1)
    raw_preserved: bool
    c2pa_manifest_ref: str | None = None

    @field_validator("payload_sha256")
    @classmethod
    def validate_payload_hash(cls, value: str) -> str:
        return _validate_sha256(value)


class VisualCaptureQualityV0(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_ref: str = Field(min_length=1)
    coverage_disposition: Literal["pass", "fail", "unknown"]
    blur_disposition: Literal["pass", "fail", "unknown"]
    scale_disposition: Literal["pass", "fail", "unknown"]
    calibration_disposition: Literal["pass", "fail", "unknown"]
    quality_metrics_ref: str = Field(min_length=1)
    missing_regions: tuple[str, ...] = ()


class VisualProcessingV0(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    segmentation_profile: str = Field(min_length=1)
    reconstruction_profile: str = Field(min_length=1)
    generative_fill_used: bool
    derived_manifest_hash: str

    @field_validator("derived_manifest_hash")
    @classmethod
    def validate_derived_hash(cls, value: str) -> str:
        return _validate_sha256(value)


class VisualFingerprintV0(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fingerprint_profile_ref: str = Field(min_length=1)
    spatial_fingerprint_hash: str
    descriptor_artifact_ref: str = Field(min_length=1)
    geometry_artifact_ref: str = Field(min_length=1)

    @field_validator("spatial_fingerprint_hash")
    @classmethod
    def validate_fingerprint_hash(cls, value: str) -> str:
        return _validate_sha256(value)


class VisualEvidenceObservationV0(BaseModel):
    """One capture phase and its exact recorded derivation lineage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["seedcore.visual_evidence_observation.v0"] = (
        VISUAL_EVIDENCE_OBSERVATION_VERSION
    )
    evidence_id: str = Field(min_length=1)
    capture_session_id: str = Field(min_length=1)
    capture_phase: VisualCapturePhase
    asset_id: str = Field(min_length=1)
    workflow_join_key: str
    authorized_device_ref: str = Field(min_length=1)
    observed_at: datetime
    server_nonce_hash: str
    capture_binding_hash: str
    client_integrity: ClientIntegrityV0
    physical_anchor_ref: PhysicalAnchorBindingV0
    raw_capture_manifest: RawCaptureManifestV0
    capture_quality: VisualCaptureQualityV0
    processing: VisualProcessingV0
    fingerprint: VisualFingerprintV0
    signer_ref: str = Field(min_length=1)

    @field_validator(
        "workflow_join_key",
        "server_nonce_hash",
        "capture_binding_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _validate_sha256(value)

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value


class VisualConfidenceSummaryV0(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    score: float = Field(ge=0.0, le=1.0)
    calibration_profile_ref: str = Field(min_length=1)
    threshold_profile_ref: str = Field(min_length=1)


class VisualEvidenceComparisonV0(BaseModel):
    """Recorded comparison between an approved baseline and later observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["seedcore.visual_evidence_comparison.v0"] = (
        VISUAL_EVIDENCE_COMPARISON_VERSION
    )
    comparison_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    workflow_join_key: str
    baseline_evidence_ref: str = Field(min_length=1)
    observed_evidence_ref: str = Field(min_length=1)
    comparison_profile_ref: str = Field(min_length=1)
    outcome: VisualEvidenceOutcome
    confidence_summary: VisualConfidenceSummaryV0
    quality_disposition: Literal["sufficient", "insufficient", "anomalous"]
    condition_delta_ref: str | None = None
    reason_codes: tuple[str, ...] = ()
    payload_sha256: str
    signer_ref: str = Field(min_length=1)

    @field_validator("workflow_join_key", "payload_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _validate_sha256(value)

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(set(value) - VISUAL_EVIDENCE_REASON_CODES)
        if unknown:
            raise ValueError(f"unknown visual evidence reason codes: {unknown}")
        if len(value) != len(set(value)):
            raise ValueError("visual evidence reason codes must be unique")
        return value

    @model_validator(mode="after")
    def validate_outcome_shape(self) -> "VisualEvidenceComparisonV0":
        expected_quality = {
            VisualEvidenceOutcome.MATCH: "sufficient",
            VisualEvidenceOutcome.MISMATCH: "sufficient",
            VisualEvidenceOutcome.INSUFFICIENT_COVERAGE: "insufficient",
            VisualEvidenceOutcome.ANOMALY_FLAGGED: "anomalous",
        }.get(self.outcome)
        if (
            expected_quality is not None
            and self.quality_disposition != expected_quality
        ):
            raise ValueError(
                f"{self.outcome.value} requires quality_disposition={expected_quality!r}"
            )
        if self.outcome == VisualEvidenceOutcome.MATCH and self.reason_codes:
            raise ValueError("MATCH comparison cannot carry failure reason codes")
        reason_codes = set(self.reason_codes)
        if (
            self.outcome == VisualEvidenceOutcome.MISMATCH
            and not reason_codes.intersection(VISUAL_MISMATCH_REASON_CODES)
        ):
            raise ValueError(
                "MISMATCH comparison requires a stable mismatch reason code"
            )
        if (
            self.outcome == VisualEvidenceOutcome.INSUFFICIENT_COVERAGE
            and "VISUAL_CAPTURE_INSUFFICIENT_COVERAGE" not in reason_codes
        ):
            raise ValueError(
                "INSUFFICIENT_COVERAGE comparison requires its stable reason code"
            )
        if self.outcome == VisualEvidenceOutcome.ANOMALY_FLAGGED and not reason_codes:
            raise ValueError("ANOMALY_FLAGGED comparison requires a stable reason code")
        return self


class VisualEvidenceReplayContextV0(BaseModel):
    """Pinned context supplied by the accountable replay/verifier caller."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_asset_id: str = Field(min_length=1)
    expected_workflow_join_key: str
    evaluated_at: datetime
    max_capture_age_seconds: int = Field(gt=0)
    admitted_capture_profiles: frozenset[str]
    admitted_segmentation_profiles: frozenset[str]
    admitted_reconstruction_profiles: frozenset[str]
    admitted_fingerprint_profiles: frozenset[str]
    admitted_comparison_profiles: frozenset[str]
    admitted_calibration_profiles: frozenset[str]
    admitted_threshold_profiles: frozenset[str]
    non_visual_authority_valid: bool = True
    non_visual_reason_codes: tuple[str, ...] = ()

    @field_validator("expected_workflow_join_key")
    @classmethod
    def validate_workflow_hash(cls, value: str) -> str:
        return _validate_sha256(value)

    @field_validator("evaluated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def require_non_visual_reason(self) -> "VisualEvidenceReplayContextV0":
        if not self.non_visual_authority_valid and not self.non_visual_reason_codes:
            raise ValueError(
                "invalid non-visual authority requires a stable reason code"
            )
        return self


class VisualEvidenceReplayResultV0(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["seedcore.visual_evidence_replay.v0"] = (
        VISUAL_EVIDENCE_REPLAY_VERSION
    )
    evidence_disposition: VisualEvidenceDisposition
    reason_codes: tuple[str, ...]
    observation_outcome: VisualEvidenceOutcome
    binding_verified: bool
    recorded_artifacts_replayed: bool = True
    model_rerun_required: bool = False
    authority_effect: Literal["none"] = "none"
    action_authorized: Literal[False] = False


def _validate_sha256(value: str) -> str:
    if not _SHA256_PATTERN.fullmatch(value):
        raise ValueError("value must use sha256:<64 lowercase hex characters>")
    return value


def canonical_json_sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _canonical_datetime(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def capture_binding_payload(
    observation: VisualEvidenceObservationV0,
) -> dict[str, object]:
    """Return the versioned fields co-bound to one capture session."""

    return {
        "binding_version": VISUAL_CAPTURE_BINDING_VERSION,
        "capture_session_id": observation.capture_session_id,
        "capture_phase": observation.capture_phase.value,
        "asset_id": observation.asset_id,
        "workflow_join_key": observation.workflow_join_key,
        "authorized_device_ref": observation.authorized_device_ref,
        "observed_at": _canonical_datetime(observation.observed_at),
        "server_nonce_hash": observation.server_nonce_hash,
        "client_data_hash": observation.client_integrity.client_data_hash,
        "raw_manifest_sha256": observation.raw_capture_manifest.payload_sha256,
        "physical_anchor_required": observation.physical_anchor_ref.required,
        "nfc_proof_ref": observation.physical_anchor_ref.nfc_proof_ref,
    }


def compute_capture_binding_hash(observation: VisualEvidenceObservationV0) -> str:
    return canonical_json_sha256(capture_binding_payload(observation))


def comparison_payload(comparison: VisualEvidenceComparisonV0) -> dict[str, object]:
    """Return the signed comparison content, excluding its digest and signer."""

    payload = comparison.model_dump(mode="json")
    payload.pop("payload_sha256", None)
    payload.pop("signer_ref", None)
    return payload


def compute_comparison_payload_hash(comparison: VisualEvidenceComparisonV0) -> str:
    return canonical_json_sha256(comparison_payload(comparison))


__all__ = [
    "VISUAL_CAPTURE_BINDING_VERSION",
    "VISUAL_EVIDENCE_COMPARISON_VERSION",
    "VISUAL_EVIDENCE_OBSERVATION_VERSION",
    "VISUAL_EVIDENCE_REASON_CODES",
    "VISUAL_EVIDENCE_REPLAY_VERSION",
    "VISUAL_MISMATCH_REASON_CODES",
    "ClientIntegrityV0",
    "PhysicalAnchorBindingV0",
    "RawCaptureManifestV0",
    "VisualCapturePhase",
    "VisualCaptureQualityV0",
    "VisualConfidenceSummaryV0",
    "VisualEvidenceComparisonV0",
    "VisualEvidenceDisposition",
    "VisualEvidenceObservationV0",
    "VisualEvidenceOutcome",
    "VisualEvidenceReplayContextV0",
    "VisualEvidenceReplayResultV0",
    "VisualFingerprintV0",
    "VisualProcessingV0",
    "canonical_json_sha256",
    "capture_binding_payload",
    "comparison_payload",
    "compute_capture_binding_hash",
    "compute_comparison_payload_hash",
]
