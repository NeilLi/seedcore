from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


GovernanceVerdict = Literal[
    "clean_allow",
    "clean_deny",
    "near_miss_allow",
    "near_miss_deny",
    "quarantine",
    "escalate",
    "verification_mismatch",
    "stale_context",
]


def _normalize_required_str(value: str, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


class GovernanceFeatureVector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    telemetry_age_seconds: float = 0.0
    has_valid_coordinates: bool = False
    has_valid_signature: bool = False
    has_matching_assets: bool = False
    device_enrolled: bool = False
    is_approved_zone: bool = False
    approval_envelope_present: bool = False
    declared_value_usd: float = 0.0
    requires_co_signature: bool = False
    trust_gap_count: int = 0
    distance_to_boundary: float = 0.0


class GovernanceEvidenceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    has_transition_receipts: bool = False
    has_policy_receipt: bool = False
    has_asset_fingerprint: bool = False
    signer_profile: str = "none"
    telemetry_count: int = 0
    media_count: int = 0


class GovernanceLearningSampleV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str
    request_id: str
    intent_id: str
    replay_ref: str
    evidence_bundle_id: str
    policy_snapshot_hash: str
    decision_graph_snapshot_hash: str
    pdp_disposition: str
    reason_code: str
    trust_gap_codes: List[str] = Field(default_factory=list)
    obligations: List[Dict[str, Any]] = Field(default_factory=list)
    verifier_outcome: str
    verdict: GovernanceVerdict
    features: GovernanceFeatureVector
    evidence_summary: GovernanceEvidenceSummary
    created_at: str
    state_binding_hash: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "sample_id",
        "request_id",
        "intent_id",
        "replay_ref",
        "evidence_bundle_id",
        "policy_snapshot_hash",
        "decision_graph_snapshot_hash",
        "pdp_disposition",
        "reason_code",
        "verifier_outcome",
        "created_at",
    )
    @classmethod
    def _validate_required_strings(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)
