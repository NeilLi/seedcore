from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GovernanceAdvisoryOutputV1(BaseModel):
    """Bounded shadow-only advisory output for governance-learning students."""

    model_config = ConfigDict(extra="forbid")

    reason_code: str
    trust_gap_codes: List[str] = Field(default_factory=list)
    missing_authority_context: List[str] = Field(default_factory=list)
    evidence_risk_flags: List[str] = Field(default_factory=list)
    required_obligations: List[Dict[str, Any]] = Field(default_factory=list)
    abstain: bool = True
    abstain_reasons: List[str] = Field(default_factory=list)
    shadow_only: Literal[True] = True
    final_authority: Literal[False] = False
    student_final_authority_usage: Literal[0] = 0

    @field_validator("reason_code")
    @classmethod
    def _required_reason_code(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("reason_code must not be empty")
        return normalized

    @field_validator(
        "trust_gap_codes",
        "missing_authority_context",
        "evidence_risk_flags",
        "abstain_reasons",
    )
    @classmethod
    def _normalize_string_list(cls, value: List[str]) -> List[str]:
        normalized: List[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized


# Window I Groundwork: Abstention taxonomy categories mapping
WINDOW_I_ABSTENTION_CATEGORIES: Dict[str, str] = {
    "stale_missing_freshness": "stale/missing freshness context",
    "invalid_delegation_principal": "invalid delegation/principal context",
    "coordinate_zone_mismatch": "coordinate or zone scope mismatch",
    "missing_approval_cosignature": "missing approval/co-signature context",
    "missing_evidence_closure": "missing evidence closure",
    "verifier_replay_mismatch": "verifier/replay mismatch",
    "token_scope_anomaly": "token/scope anomaly",
    "unknown_out_of_distribution": "unknown/out-of-distribution sample",
}
