from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field  # pyright: ignore[reportMissingImports]


class SecurityContract(BaseModel):
    hash: str
    version: str


class IntentPrincipal(BaseModel):
    agent_id: str
    role_profile: str
    session_token: str


class IntentAction(BaseModel):
    type: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    security_contract: SecurityContract


class IntentResource(BaseModel):
    asset_id: str
    target_zone: Optional[str] = None
    provenance_hash: str
    source_registration_id: Optional[str] = None
    registration_decision_id: Optional[str] = None


class ActionIntent(BaseModel):
    intent_id: str
    timestamp: str
    valid_until: str
    principal: IntentPrincipal
    action: IntentAction
    resource: IntentResource


class TwinFreshness(BaseModel):
    status: Literal["fresh", "stale", "unknown"] = "unknown"
    observed_at: Optional[str] = None
    max_age_seconds: Optional[int] = None


class AuthorityLevel(str, Enum):
    OBSERVER = "observer"
    CONTRIBUTOR = "contributor"
    SIGNER = "signer"


class DelegationConstraint(BaseModel):
    max_value_usd: Optional[float] = None
    allowed_zones: List[str] = Field(default_factory=list)
    required_modality: List[str] = Field(default_factory=list)
    time_window: Optional[Dict[str, str]] = None


class DelegatedAuthority(BaseModel):
    assistant_id: str
    authority_level: AuthorityLevel = AuthorityLevel.OBSERVER
    scope: List[str] = Field(default_factory=list)
    constraints: DelegationConstraint = Field(default_factory=DelegationConstraint)
    requires_step_up: bool = True


class OwnerTwin(BaseModel):
    owner_id: str = Field(description="did:seedcore:owner:uuid")
    public_key_fingerprint: Optional[str] = None
    delegations: List[DelegatedAuthority] = Field(default_factory=list)
    state: str = "ACTIVE"
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    graph_ref: Optional[str] = None


class TwinRevisionStage(str, Enum):
    PROPOSED = "PROPOSED"
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    AUTHORITATIVE = "AUTHORITATIVE"
    DISPUTED = "DISPUTED"


class TwinSnapshot(BaseModel):
    twin_kind: str
    twin_id: str
    revision_stage: TwinRevisionStage = TwinRevisionStage.PROPOSED
    lifecycle_state: str = "UNKNOWN"
    lineage_refs: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    freshness: TwinFreshness = Field(default_factory=TwinFreshness)
    identity: Dict[str, Any] = Field(default_factory=dict)
    governance: Dict[str, Any] = Field(default_factory=dict)
    risk: Dict[str, Any] = Field(default_factory=dict)
    delegation: Dict[str, Any] = Field(default_factory=dict)
    custody: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    telemetry: Dict[str, Any] = Field(default_factory=dict)


class PolicyCaseAssessment(BaseModel):
    advisory_id: Optional[str] = None
    recommended_disposition: Literal["allow", "deny", "escalate"] = "escalate"
    risk_score: float = Field(0.0, ge=0.0, le=1.0)
    risk_factors: List[str] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list)
    policy_conflicts: List[str] = Field(default_factory=list)
    required_approvals: List[str] = Field(default_factory=list)
    explanation: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    provider: Optional[str] = None
    trace_ref: Optional[str] = None


class PolicyCase(BaseModel):
    action_intent: ActionIntent
    policy_snapshot: Optional[str] = None
    relevant_twin_snapshot: Dict[str, TwinSnapshot] = Field(default_factory=dict)
    approved_source_registrations: Dict[str, Optional[str]] = Field(default_factory=dict)
    telemetry_summary: Dict[str, Any] = Field(default_factory=dict)
    cognitive_assessment: Optional[PolicyCaseAssessment] = None
    evidence_summary: Dict[str, Any] = Field(default_factory=dict)


class ExecutionToken(BaseModel):
    token_id: str
    intent_id: str
    issued_at: str
    valid_until: str
    contract_version: str
    signature: str
    constraints: Dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    allowed: bool
    execution_token: Optional[ExecutionToken] = None
    reason: Optional[str] = None
    policy_snapshot: Optional[str] = None
    deny_code: Optional[str] = None
    disposition: Literal["allow", "deny", "escalate"] = "deny"
    risk_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    explanations: List[str] = Field(default_factory=list)
    required_approvals: List[str] = Field(default_factory=list)
    evidence_gaps: List[str] = Field(default_factory=list)
    cognitive_trace_ref: Optional[str] = None
