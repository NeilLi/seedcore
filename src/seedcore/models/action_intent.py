from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)  # pyright: ignore[reportMissingImports]


def _normalize_required_str(value: str, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _normalize_optional_str(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_timestamp(value: str, *, field_name: str) -> str:
    normalized = _normalize_required_str(value, field_name=field_name)
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


class GovernedOperation(str, Enum):
    ACTION = "ACTION"
    READ = "READ"
    MUTATE = "MUTATE"
    TRANSFER_CUSTODY = "TRANSFER_CUSTODY"
    SPAWN_PROCESS = "SPAWN_PROCESS"
    TERMINATE = "TERMINATE"
    MOVE = "MOVE"
    PICK = "PICK"
    PLACE = "PLACE"
    SCAN = "SCAN"
    PACK = "PACK"
    RELEASE = "RELEASE"


class SecurityContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hash: str
    version: str

    @field_validator("hash", "version")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)


class IntentPrincipal(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    agent_id: str = Field(validation_alias=AliasChoices("agent_id", "actor_id"))
    role_profile: str
    session_token: str = ""
    actor_token: Optional[str] = None

    @field_validator("agent_id", "role_profile")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)

    @field_validator("session_token", "actor_token")
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)

    @model_validator(mode="after")
    def _require_identity_proof(self) -> "IntentPrincipal":
        if not self.session_token and not self.actor_token:
            raise ValueError("principal.session_token or principal.actor_token is required")
        return self


class IntentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    operation: Optional[GovernedOperation] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    security_contract: SecurityContract

    @field_validator("type")
    @classmethod
    def _normalize_type(cls, value: str) -> str:
        return _normalize_required_str(value, field_name="type").replace(" ", "_").upper()

    @model_validator(mode="after")
    def _derive_operation(self) -> "IntentAction":
        if self.operation is None:
            self.operation = _coerce_operation(self.type)
        return self


class IntentResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    resource_uri: Optional[str] = None
    resource_state_hash: Optional[str] = None
    target_zone: Optional[str] = None
    provenance_hash: str
    source_registration_id: Optional[str] = None
    registration_decision_id: Optional[str] = None
    lot_id: Optional[str] = None
    batch_twin_id: Optional[str] = None
    parent_asset_id: Optional[str] = None
    product_id: Optional[str] = None
    category_envelope: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("asset_id", "provenance_hash")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)

    @field_validator(
        "resource_uri",
        "resource_state_hash",
        "target_zone",
        "source_registration_id",
        "registration_decision_id",
        "lot_id",
        "batch_twin_id",
        "parent_asset_id",
        "product_id",
    )
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)

    @field_validator("resource_uri")
    @classmethod
    def _validate_resource_uri(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        parsed = urlparse(value)
        if not parsed.scheme:
            raise ValueError("resource_uri must include a URI scheme")
        if not parsed.netloc and not parsed.path:
            raise ValueError("resource_uri must include a resource target")
        return value


class IntentEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin_network: Optional[str] = None
    break_glass_token: Optional[str] = None
    break_glass_reason: Optional[str] = None

    @field_validator("origin_network", "break_glass_token", "break_glass_reason")
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)


class ActionIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_id: str
    timestamp: str
    valid_until: str
    principal: IntentPrincipal
    action: IntentAction
    resource: IntentResource
    environment: IntentEnvironment = Field(default_factory=IntentEnvironment)

    @field_validator("intent_id")
    @classmethod
    def _validate_intent_id(cls, value: str) -> str:
        return _normalize_required_str(value, field_name="intent_id")

    @field_validator("timestamp")
    @classmethod
    def _validate_timestamp(cls, value: str) -> str:
        return _normalize_timestamp(value, field_name="timestamp")

    @field_validator("valid_until")
    @classmethod
    def _validate_valid_until(cls, value: str) -> str:
        return _normalize_timestamp(value, field_name="valid_until")

    @model_validator(mode="after")
    def _validate_window(self) -> "ActionIntent":
        issued_at = datetime.fromisoformat(self.timestamp)
        valid_until = datetime.fromisoformat(self.valid_until)
        if valid_until <= issued_at:
            raise ValueError("valid_until must be greater than timestamp")
        return self


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
    authoritative_approval_envelope: Dict[str, Any] = Field(default_factory=dict)
    authoritative_approval_transition_history: List[Dict[str, Any]] = Field(default_factory=list)
    authoritative_approval_transition_head: Optional[str] = None


class ExecutionToken(BaseModel):
    token_id: str
    intent_id: str
    issued_at: str
    valid_until: str
    contract_version: str
    artifact_hash: Dict[str, Any] = Field(default_factory=dict)
    signature: Dict[str, Any] = Field(default_factory=dict)
    constraints: Dict[str, Any] = Field(default_factory=dict)


class BreakGlassDecisionContext(BaseModel):
    present: bool = False
    validated: bool = False
    used: bool = False
    override_applied: bool = False
    required: bool = False
    reason: Optional[str] = None
    principal_id: Optional[str] = None
    token_issued_at: Optional[str] = None
    token_expires_at: Optional[str] = None
    outcome: Optional[str] = None
    procedure_id: Optional[str] = None
    incident_id: Optional[str] = None
    reason_code: Optional[str] = None
    risk_score: Optional[float] = None
    ocps_score: Optional[float] = None


class PolicyDecision(BaseModel):
    allowed: bool
    execution_token: Optional[ExecutionToken] = None
    reason: Optional[str] = None
    policy_snapshot: Optional[str] = None
    deny_code: Optional[str] = None
    disposition: Literal["allow", "deny", "escalate", "quarantine"] = "deny"
    risk_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    explanations: List[str] = Field(default_factory=list)
    required_approvals: List[str] = Field(default_factory=list)
    evidence_gaps: List[str] = Field(default_factory=list)
    cognitive_trace_ref: Optional[str] = None
    obligations: List[Dict[str, Any]] = Field(default_factory=list)
    break_glass: BreakGlassDecisionContext = Field(default_factory=BreakGlassDecisionContext)
    authz_graph: Dict[str, Any] = Field(default_factory=dict)
    governed_receipt: Dict[str, Any] = Field(default_factory=dict)


def _coerce_operation(action_type: str) -> GovernedOperation:
    normalized = action_type.strip().replace(" ", "_").upper()
    if normalized in GovernedOperation.__members__:
        return GovernedOperation[normalized]
    if normalized in {"GET", "LIST", "QUERY", "OBSERVE"}:
        return GovernedOperation.READ
    if normalized in {"SPAWN", "CREATE_PROCESS", "FORK", "LAUNCH"}:
        return GovernedOperation.SPAWN_PROCESS
    if normalized in {"DELETE", "STOP", "KILL"}:
        return GovernedOperation.TERMINATE
    return GovernedOperation.MUTATE
