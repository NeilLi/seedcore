from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .action_intent import ExecutionToken
from .pdp_hot_path import HotPathDecisionView


GATEWAY_CONTRACT_VERSION = "seedcore.agent_action_gateway.v1"
WORKFLOW_TYPE_RCT = "restricted_custody_transfer"


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


class AgentActionPrincipal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    role_profile: str
    session_token: Optional[str] = None
    actor_token: Optional[str] = None
    owner_id: Optional[str] = None
    delegation_ref: Optional[str] = None
    organization_ref: Optional[str] = None

    @field_validator("agent_id", "role_profile")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)

    @field_validator("session_token", "actor_token", "owner_id", "delegation_ref", "organization_ref")
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)

    @model_validator(mode="after")
    def _require_identity_proof(self) -> "AgentActionPrincipal":
        if not self.session_token and not self.actor_token:
            raise ValueError("principal.session_token or principal.actor_token is required")
        return self


class AgentActionWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["restricted_custody_transfer"] = WORKFLOW_TYPE_RCT
    action_type: str = "TRANSFER_CUSTODY"
    valid_until: datetime

    @field_validator("action_type")
    @classmethod
    def _validate_action_type(cls, value: str) -> str:
        return _normalize_required_str(value, field_name="action_type")


class AgentActionAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    lot_id: Optional[str] = None
    from_custodian_ref: Optional[str] = None
    to_custodian_ref: Optional[str] = None
    from_zone: Optional[str] = None
    to_zone: Optional[str] = None
    provenance_hash: str
    declared_value_usd: Optional[float] = Field(default=None, ge=0)

    @field_validator("asset_id", "provenance_hash")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)

    @field_validator(
        "lot_id",
        "from_custodian_ref",
        "to_custodian_ref",
        "from_zone",
        "to_zone",
    )
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)


class AgentActionApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_envelope_id: str
    expected_envelope_version: Optional[str] = None

    @field_validator("approval_envelope_id")
    @classmethod
    def _validate_required_fields(cls, value: str) -> str:
        return _normalize_required_str(value, field_name="approval_envelope_id")

    @field_validator("expected_envelope_version")
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)


class AgentActionTelemetry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    freshness_seconds: Optional[int] = Field(default=None, ge=0)
    max_allowed_age_seconds: Optional[int] = Field(default=None, ge=0)
    evidence_refs: List[str] = Field(default_factory=list)


class AgentActionSecurityContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hash: str
    version: str

    @field_validator("hash", "version")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)


class AgentActionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    debug: bool = False
    no_execute: bool = False


class AgentActionEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["seedcore.agent_action_gateway.v1"] = GATEWAY_CONTRACT_VERSION
    request_id: str
    requested_at: datetime
    idempotency_key: str
    policy_snapshot_ref: Optional[str] = None
    principal: AgentActionPrincipal
    workflow: AgentActionWorkflow
    asset: AgentActionAsset
    approval: AgentActionApproval
    telemetry: AgentActionTelemetry
    security_contract: AgentActionSecurityContract
    options: AgentActionOptions = Field(default_factory=AgentActionOptions)

    @field_validator("request_id", "idempotency_key")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)

    @field_validator("policy_snapshot_ref")
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)


class AgentActionEvaluateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["seedcore.agent_action_gateway.v1"] = GATEWAY_CONTRACT_VERSION
    request_id: str
    decided_at: datetime
    latency_ms: int = Field(ge=0)
    decision: HotPathDecisionView
    required_approvals: List[str] = Field(default_factory=list)
    trust_gaps: List[str] = Field(default_factory=list)
    obligations: List[Dict[str, Any]] = Field(default_factory=list)
    minted_artifacts: List[str] = Field(default_factory=list)
    execution_token: Optional[ExecutionToken] = None
    governed_receipt: Dict[str, Any] = Field(default_factory=dict)


class AgentActionRequestRecordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["seedcore.agent_action_gateway.v1"] = GATEWAY_CONTRACT_VERSION
    request_id: str
    idempotency_key: str
    status: Literal["completed"] = "completed"
    recorded_at: datetime
    response: AgentActionEvaluateResponse


class AgentActionClosureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["seedcore.agent_action_gateway.v1"] = GATEWAY_CONTRACT_VERSION
    request_id: str
    closure_id: str
    idempotency_key: str
    closed_at: datetime
    outcome: Literal["completed", "quarantined", "failed"] = "completed"
    evidence_bundle_id: str
    transition_receipt_ids: List[str] = Field(default_factory=list)
    node_id: Optional[str] = None
    summary: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("request_id", "closure_id", "idempotency_key", "evidence_bundle_id")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)

    @field_validator("node_id")
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)


class AgentActionClosureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["seedcore.agent_action_gateway.v1"] = GATEWAY_CONTRACT_VERSION
    request_id: str
    closure_id: str
    accepted_at: datetime
    status: Literal["accepted_pending_settlement"] = "accepted_pending_settlement"
    settlement_status: Literal["pending", "applied", "rejected"] = "pending"
    replay_status: Literal["pending", "ready"] = "pending"
    linked_disposition: str
    settlement_result: Dict[str, Any] = Field(default_factory=dict)
    next_actions: List[str] = Field(default_factory=list)


class AgentActionClosureRecordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["seedcore.agent_action_gateway.v1"] = GATEWAY_CONTRACT_VERSION
    closure_id: str
    request_id: str
    idempotency_key: str
    status: Literal["completed"] = "completed"
    recorded_at: datetime
    response: AgentActionClosureResponse
