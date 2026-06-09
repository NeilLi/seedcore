from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .action_intent import ExecutionPreconditions, ExecutionToken
from .edge_telemetry import SignedEdgeTelemetryRefV0
from .pdp_hot_path import (
    HotPathContextFreshness,
    HotPathDecisionView,
    HotPathSignedContextEnvelope,
)


GATEWAY_CONTRACT_VERSION = "seedcore.agent_action_gateway.v1"
WORKFLOW_TYPE_RCT = "restricted_custody_transfer"
PLANNER_TYPE_PHYSICAL_HANDOVER = "physical_digital_handover"
PLANNER_TYPE_CONDITIONAL_ESCROW = "conditional_escrow"
PLANNER_TYPE_DELEGATED_AUTHORITY = "delegated_authority"


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
    owner_id: str
    delegation_ref: str
    organization_ref: Optional[str] = None
    hardware_fingerprint: "AgentActionHardwareFingerprint"

    @field_validator("agent_id", "role_profile")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)

    @field_validator("session_token", "actor_token", "organization_ref")
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)

    @field_validator("owner_id", "delegation_ref")
    @classmethod
    def _validate_binding_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)

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
    product_ref: Optional[str] = None
    order_ref: Optional[str] = None
    quote_ref: Optional[str] = None
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
        "product_ref",
        "order_ref",
        "quote_ref",
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
    current_zone: Optional[str] = None
    current_coordinate_ref: Optional[str] = None
    evidence_refs: List[str] = Field(default_factory=list)

    @field_validator("current_zone", "current_coordinate_ref")
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)


class AgentActionHardwareFingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fingerprint_id: str
    node_id: Optional[str] = None
    endpoint_id: Optional[str] = None
    public_key_fingerprint: str
    attestation_type: Optional[str] = None
    key_ref: Optional[str] = None
    hardware_tpm_hash: Optional[str] = None

    @field_validator("fingerprint_id", "public_key_fingerprint")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)

    @field_validator("node_id", "endpoint_id", "attestation_type", "key_ref", "hardware_tpm_hash")
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)


class AgentActionAuthorityScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_id: str
    asset_ref: str
    product_ref: Optional[str] = None
    facility_ref: Optional[str] = None
    expected_from_zone: Optional[str] = None
    expected_to_zone: Optional[str] = None
    expected_coordinate_ref: Optional[str] = None
    max_radius_meters: Optional[float] = Field(default=None, ge=0)

    @field_validator("scope_id", "asset_ref")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)

    @field_validator(
        "product_ref",
        "facility_ref",
        "expected_from_zone",
        "expected_to_zone",
        "expected_coordinate_ref",
    )
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)

    @model_validator(mode="after")
    def _require_physical_scope_binding(self) -> "AgentActionAuthorityScope":
        if not self.expected_to_zone and not self.expected_coordinate_ref:
            raise ValueError(
                "authority_scope.expected_to_zone or authority_scope.expected_coordinate_ref is required"
            )
        return self


class AgentActionFingerprintComponents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    economic_hash: Optional[str] = None
    physical_presence_hash: Optional[str] = None
    reasoning_hash: Optional[str] = None
    actuator_hash: Optional[str] = None

    @field_validator("economic_hash", "physical_presence_hash", "reasoning_hash", "actuator_hash")
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)


class AgentActionForensicBlockFingerprintComponents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    economic_hash: str
    physical_presence_hash: str
    reasoning_hash: str
    actuator_hash: str

    @field_validator("economic_hash", "physical_presence_hash", "reasoning_hash", "actuator_hash")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)


class AgentActionForensicBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forensic_block_id: str
    fingerprint_components: AgentActionForensicBlockFingerprintComponents
    current_coordinate_ref: Optional[str] = None
    current_zone: Optional[str] = None

    @field_validator("forensic_block_id")
    @classmethod
    def _validate_forensic_block_id(cls, value: str) -> str:
        return _normalize_required_str(value, field_name="forensic_block_id")

    @field_validator("current_coordinate_ref", "current_zone")
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)


class AgentActionForensicContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_trace_ref: Optional[str] = None
    fingerprint_components: Optional[AgentActionFingerprintComponents] = None

    @field_validator("reason_trace_ref")
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)


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


class AgentActionExecutionDirective(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    args: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("tool_name")
    @classmethod
    def _validate_tool_name(cls, value: str) -> str:
        return _normalize_required_str(value, field_name="tool_name")

    @model_validator(mode="after")
    def _validate_reserved_args(self) -> "AgentActionExecutionDirective":
        reserved = {
            key
            for key in ("execution_token", "execution_context", "_governance")
            if key in self.args
        }
        if reserved:
            raise ValueError(
                "execution.args must not include reserved governance keys: "
                + ", ".join(sorted(reserved))
            )
        return self


class AgentActionExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planner_type: Literal[
        "physical_digital_handover",
        "conditional_escrow",
        "delegated_authority",
    ] = PLANNER_TYPE_PHYSICAL_HANDOVER
    planner_inputs: Dict[str, Any] = Field(default_factory=dict)
    default_directive: Optional[AgentActionExecutionDirective] = None


class AgentActionExecutionPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    step_type: str
    description: str
    depends_on: List[str] = Field(default_factory=list)
    directive: Optional[AgentActionExecutionDirective] = None
    state_anchors: Dict[str, Any] = Field(default_factory=dict)
    on_failure: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("step_id", "step_type", "description")
    @classmethod
    def _validate_required_step_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)

    @field_validator("on_failure")
    @classmethod
    def _validate_optional_step_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)


class AgentActionExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    planner_type: Literal[
        "physical_digital_handover",
        "conditional_escrow",
        "delegated_authority",
    ]
    operation_type: str
    plan_dag_hash: str
    state_anchors: Dict[str, Any] = Field(default_factory=dict)
    steps: List[AgentActionExecutionPlanStep] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("plan_id", "operation_type", "plan_dag_hash")
    @classmethod
    def _validate_required_plan_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)


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
    authority_scope: AgentActionAuthorityScope
    telemetry: AgentActionTelemetry
    context_freshness: Optional[HotPathContextFreshness] = None
    signed_context_envelopes: List[HotPathSignedContextEnvelope] = Field(default_factory=list)
    forensic_context: Optional[AgentActionForensicContext] = None
    security_contract: AgentActionSecurityContract
    options: AgentActionOptions = Field(default_factory=AgentActionOptions)
    execution: Optional[AgentActionExecutionRequest] = None

    @field_validator("request_id", "idempotency_key")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)

    @field_validator("policy_snapshot_ref")
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)

    @model_validator(mode="after")
    def _validate_scope_invariants(self) -> "AgentActionEvaluateRequest":
        if self.authority_scope.asset_ref != self.asset.asset_id:
            raise ValueError("authority_scope.asset_ref must equal asset.asset_id")
        if self.authority_scope.product_ref and self.asset.product_ref:
            if self.authority_scope.product_ref != self.asset.product_ref:
                raise ValueError("authority_scope.product_ref must equal asset.product_ref when both are provided")
        return self


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
    authority_scope_verdict: Dict[str, Any] = Field(
        default_factory=lambda: {
            "status": "unverified",
            "scope_id": None,
            "mismatch_keys": [],
        }
    )
    fingerprint_verdict: Dict[str, Any] = Field(
        default_factory=lambda: {
            "status": "incomplete",
            "missing_components": [],
            "mismatch_keys": [],
        }
    )
    execution_plan: Optional[AgentActionExecutionPlan] = None
    execution_token: Optional[ExecutionToken] = None
    execution_context: Optional[ExecutionPreconditions] = None
    governed_receipt: Dict[str, Any] = Field(default_factory=dict)
    forensic_linkage: Dict[str, Any] = Field(
        default_factory=lambda: {
            "forensic_block_id": None,
            "reason_trace_ref": None,
            "public_replay_ready": False,
            # Commerce slice join keys: kept on every evaluate response so
            # degraded-edge drills (stale-graph / dependency outage /
            # coordinate tamper / replay injection) can bind their evidence
            # to product_ref and the workflow audit join key, not just to a
            # generic asset_id. See
            # `src/seedcore/adapters/rct_gateway_correlation.py` for the
            # canonical `workflow_join_key` contract (= audit_id, with a
            # deterministic UUIDv5 fallback derived from request_id when no
            # audit_id was minted).
            "workflow_join_key": None,
            "audit_id": None,
            "request_id": None,
            "product_ref": None,
            "order_ref": None,
            "quote_ref": None,
            "asset_id": None,
        }
    )
    request_schema_bundle: Optional[Dict[str, Any]] = None
    taxonomy_bundle: Optional[Dict[str, Any]] = None


class AgentActionExecuteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["seedcore.agent_action_gateway.v1"] = GATEWAY_CONTRACT_VERSION
    request_id: str
    executed_at: datetime
    evaluation: AgentActionEvaluateResponse
    execution_plan: Optional[AgentActionExecutionPlan] = None
    execution_task: Optional[Dict[str, Any]] = None
    execution_result: Optional[Dict[str, Any]] = None


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
    telemetry_refs: List[SignedEdgeTelemetryRefV0] = Field(default_factory=list)
    node_id: Optional[str] = None
    forensic_block: AgentActionForensicBlock
    summary: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("request_id", "closure_id", "idempotency_key", "evidence_bundle_id")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        return _normalize_required_str(value, field_name=info.field_name)

    @field_validator("node_id")
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)

    @model_validator(mode="after")
    def _validate_telemetry_ref_ids(self) -> "AgentActionClosureRequest":
        seen: set[str] = set()
        for ref in self.telemetry_refs:
            tid = str(ref.telemetry_id).strip()
            if tid in seen:
                raise ValueError(f"duplicate telemetry_id in telemetry_refs: {tid}")
            seen.add(tid)
        return self


class AgentActionClosureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["seedcore.agent_action_gateway.v1"] = GATEWAY_CONTRACT_VERSION
    request_id: str
    closure_id: str
    accepted_at: datetime
    status: Literal["accepted_pending_settlement"] = "accepted_pending_settlement"
    settlement_status: Literal[
        "pending",
        "pending_reconcile",
        "applied",
        "contradicted",
        "rejected",
    ] = "pending"
    replay_status: Literal[
        "pending",
        "pending_reconcile",
        "ready",
        "contradicted",
    ] = "pending"
    linked_disposition: str
    forensic_block_id: Optional[str] = None
    telemetry_refs: List[SignedEdgeTelemetryRefV0] = Field(default_factory=list)
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
