from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field  # pyright: ignore[reportMissingImports]

from .action_intent import ActionIntent, ExecutionToken


HotPathDisposition = Literal["allow", "deny", "quarantine", "escalate"]
CheckResultState = Literal["pass", "fail", "skip"]


class HotPathAssetContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_ref: str
    current_custodian_ref: Optional[str] = None
    current_zone: Optional[str] = None
    source_registration_status: Optional[str] = None
    registration_decision_ref: Optional[str] = None


class HotPathTelemetryContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_at: str
    freshness_seconds: Optional[int] = Field(default=None, ge=0)
    max_allowed_age_seconds: Optional[int] = Field(default=None, ge=0)
    evidence_refs: List[str] = Field(default_factory=list)


class HotPathEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = "pdp.hot_path.asset_transfer.v1"
    request_id: str
    requested_at: datetime
    policy_snapshot_ref: str
    action_intent: ActionIntent
    asset_context: HotPathAssetContext
    telemetry_context: HotPathTelemetryContext
    request_schema_bundle: Optional[Dict[str, Any]] = None
    taxonomy_bundle: Optional[Dict[str, Any]] = None


class HotPathDecisionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    disposition: HotPathDisposition
    reason_code: str
    reason: str
    policy_snapshot_ref: str
    policy_snapshot_hash: Optional[str] = None


class HotPathCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str
    result: CheckResultState
    detail: Optional[str] = None


class HotPathSignerProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: str
    signer_type: str
    signer_id: str
    key_ref: str
    attestation_level: str


class HotPathEvaluateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = "pdp.hot_path.asset_transfer.v1"
    request_id: str
    decided_at: datetime
    latency_ms: int
    decision: HotPathDecisionView
    required_approvals: List[str] = Field(default_factory=list)
    trust_gaps: List[str] = Field(default_factory=list)
    obligations: List[Dict[str, Any]] = Field(default_factory=list)
    checks: List[HotPathCheckResult] = Field(default_factory=list)
    execution_token: Optional[ExecutionToken] = None
    governed_receipt: Dict[str, Any] = Field(default_factory=dict)
    signer_provenance: List[HotPathSignerProvenance] = Field(default_factory=list)
    request_schema_bundle: Optional[Dict[str, Any]] = None
    taxonomy_bundle: Optional[Dict[str, Any]] = None
