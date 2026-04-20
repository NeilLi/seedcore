from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping

from ..models.agent_action_gateway import (
    AgentActionEvaluateRequest,
    AgentActionExecutionDirective,
    AgentActionExecutionPlan,
    AgentActionExecutionPlanStep,
    PLANNER_TYPE_CONDITIONAL_ESCROW,
    PLANNER_TYPE_DELEGATED_AUTHORITY,
    PLANNER_TYPE_PHYSICAL_HANDOVER,
)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash_ref(value: Any, *, prefix: str, fallback: str) -> str:
    normalized = str(value or "").strip()
    if normalized:
        return normalized if normalized.startswith("sha256:") else f"sha256:{_sha256_hex(normalized)}"
    return f"{prefix}:{_sha256_hex(fallback)}"


def _approval_anchor(authoritative_transfer_approval: Mapping[str, Any] | None) -> str | None:
    if not isinstance(authoritative_transfer_approval, Mapping):
        return None
    head = authoritative_transfer_approval.get("authoritative_approval_transition_head")
    if isinstance(head, str) and head.strip():
        return head.strip()
    envelope = authoritative_transfer_approval.get("authoritative_approval_envelope")
    if isinstance(envelope, Mapping) and envelope:
        return f"sha256:{_sha256_hex(_canonical_json(dict(envelope)))}"
    return None


def _owner_anchor(owner_twin_snapshot: Mapping[str, Any] | None) -> str | None:
    if not isinstance(owner_twin_snapshot, Mapping) or not owner_twin_snapshot:
        return None
    return f"sha256:{_sha256_hex(_canonical_json(dict(owner_twin_snapshot)))}"


def _telemetry_anchor(payload: AgentActionEvaluateRequest) -> str:
    telemetry = {
        "observed_at": payload.telemetry.observed_at.isoformat(),
        "current_zone": payload.telemetry.current_zone,
        "current_coordinate_ref": payload.telemetry.current_coordinate_ref,
        "evidence_refs": list(payload.telemetry.evidence_refs),
    }
    return f"sha256:{_sha256_hex(_canonical_json(telemetry))}"


def _asset_state_anchor(payload: AgentActionEvaluateRequest) -> str:
    material = {
        "asset_id": payload.asset.asset_id,
        "lot_id": payload.asset.lot_id,
        "provenance_hash": payload.asset.provenance_hash,
        "from_zone": payload.asset.from_zone,
        "to_zone": payload.asset.to_zone,
    }
    return f"sha256:{_sha256_hex(_canonical_json(material))}"


def _sender_hash(payload: AgentActionEvaluateRequest) -> str:
    return _hash_ref(
        payload.asset.from_custodian_ref,
        prefix="sha256",
        fallback=f"sender:{payload.request_id}:{payload.asset.asset_id}",
    )


def _receiver_hash(payload: AgentActionEvaluateRequest, planner_inputs: Mapping[str, Any]) -> str:
    receiver_identity = (
        planner_inputs.get("receiver_identity_hash")
        or planner_inputs.get("recipient_actor_token")
        or payload.asset.to_custodian_ref
    )
    return _hash_ref(
        receiver_identity,
        prefix="sha256",
        fallback=f"receiver:{payload.request_id}:{payload.asset.asset_id}",
    )


def _plan_hash_material(
    *,
    plan_id: str,
    planner_type: str,
    operation_type: str,
    state_anchors: Mapping[str, Any],
    steps: List[AgentActionExecutionPlanStep],
    metadata: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "plan_id": plan_id,
        "planner_type": planner_type,
        "operation_type": operation_type,
        "state_anchors": dict(state_anchors),
        "steps": [step.model_dump(mode="json", exclude_none=True) for step in steps],
        "metadata": dict(metadata),
    }


def _plan_dag_hash(
    *,
    plan_id: str,
    planner_type: str,
    operation_type: str,
    state_anchors: Mapping[str, Any],
    steps: List[AgentActionExecutionPlanStep],
    metadata: Mapping[str, Any],
) -> str:
    material = _plan_hash_material(
        plan_id=plan_id,
        planner_type=planner_type,
        operation_type=operation_type,
        state_anchors=state_anchors,
        steps=steps,
        metadata=metadata,
    )
    return f"sha256:{_sha256_hex(_canonical_json(material))}"


def executable_directives_from_plan(plan: AgentActionExecutionPlan | None) -> List[AgentActionExecutionDirective]:
    if plan is None:
        return []
    directives: List[AgentActionExecutionDirective] = []
    for step in plan.steps:
        if step.directive is not None:
            directives.append(step.directive)
    return directives


@dataclass
class PlannerContext:
    owner_twin_snapshot: Mapping[str, Any] | None = None
    authoritative_transfer_approval: Mapping[str, Any] | None = None

    @property
    def approval_anchor(self) -> str | None:
        return _approval_anchor(self.authoritative_transfer_approval)

    @property
    def owner_anchor(self) -> str | None:
        return _owner_anchor(self.owner_twin_snapshot)


class BaseExecutionPlanner:
    planner_type = PLANNER_TYPE_PHYSICAL_HANDOVER

    def build_plan(
        self,
        payload: AgentActionEvaluateRequest,
        *,
        context: PlannerContext,
    ) -> AgentActionExecutionPlan:
        raise NotImplementedError

    def _base_state_anchors(
        self,
        payload: AgentActionEvaluateRequest,
        *,
        context: PlannerContext,
    ) -> Dict[str, Any]:
        anchors: Dict[str, Any] = {
            "asset_state_anchor": _asset_state_anchor(payload),
            "telemetry_anchor": _telemetry_anchor(payload),
            "approval_anchor": context.approval_anchor,
            "owner_anchor": context.owner_anchor,
            "target_zone": payload.asset.to_zone or payload.authority_scope.expected_to_zone,
        }
        return anchors

    def _default_release_directive(
        self,
        payload: AgentActionEvaluateRequest,
    ) -> AgentActionExecutionDirective:
        behavior_params: Dict[str, Any] = {
            "asset_id": payload.asset.asset_id,
            "request_id": payload.request_id,
            "from_zone": payload.asset.from_zone,
            "to_zone": payload.asset.to_zone,
            "to_custodian_ref": payload.asset.to_custodian_ref,
            "scope_id": payload.authority_scope.scope_id,
            "release_mode": "custody_handover",
        }
        return AgentActionExecutionDirective(
            tool_name="reachy.motion",
            args={
                "behavior_name": "move_forward",
                "behavior_params": behavior_params,
            },
        )


class RoboticHandoverPlanner(BaseExecutionPlanner):
    planner_type = PLANNER_TYPE_PHYSICAL_HANDOVER

    def build_plan(
        self,
        payload: AgentActionEvaluateRequest,
        *,
        context: PlannerContext,
    ) -> AgentActionExecutionPlan:
        planner_inputs = payload.execution.planner_inputs if payload.execution is not None else {}
        release_directive = (
            payload.execution.default_directive
            if payload.execution is not None and payload.execution.default_directive is not None
            else self._default_release_directive(payload)
        )
        triple_hash = f"sha256:{_sha256_hex(_canonical_json({
            'sender_hash': _sender_hash(payload),
            'receiver_hash': _receiver_hash(payload, planner_inputs),
            'asset_state_hash': _asset_state_anchor(payload),
        }))}"
        state_anchors = self._base_state_anchors(payload, context=context)
        state_anchors["rct_triple_hash"] = triple_hash
        recipient_zone = (
            planner_inputs.get("recipient_coordinate_ref")
            or payload.authority_scope.expected_coordinate_ref
            or payload.asset.to_zone
        )
        steps = [
            AgentActionExecutionPlanStep(
                step_id="verify_recipient_binding",
                step_type="guard",
                description="Confirm recipient identity proof and custody-zone proximity before release.",
                state_anchors={
                    "recipient_actor_token_present": bool(
                        planner_inputs.get("recipient_actor_token") or payload.principal.actor_token
                    ),
                    "custody_zone": recipient_zone,
                },
                on_failure="quarantine_twin_custody",
            ),
            AgentActionExecutionPlanStep(
                step_id="lock_ready_for_transfer",
                step_type="state_lock",
                description="Bind the asset to ReadyForTransfer before any mechanical release.",
                depends_on=["verify_recipient_binding"],
                state_anchors={
                    "asset_id": payload.asset.asset_id,
                    "ready_state": "ReadyForTransfer",
                },
                on_failure="revert_ready_for_transfer_lock",
            ),
            AgentActionExecutionPlanStep(
                step_id="commit_triple_hash",
                step_type="commitment",
                description="Commit sender, receiver, and asset-state anchors into the governed receipt.",
                depends_on=["lock_ready_for_transfer"],
                state_anchors={
                    "sender_hash": _sender_hash(payload),
                    "receiver_hash": _receiver_hash(payload, planner_inputs),
                    "asset_state_hash": _asset_state_anchor(payload),
                    "triple_hash": triple_hash,
                },
                on_failure="quarantine_twin_custody",
            ),
            AgentActionExecutionPlanStep(
                step_id="mechanical_release",
                step_type="actuate",
                description="Release the robot-held asset after custody commitment alignment succeeds.",
                depends_on=["commit_triple_hash"],
                directive=release_directive,
                state_anchors={
                    "endpoint_id": payload.principal.hardware_fingerprint.endpoint_id
                    or payload.principal.hardware_fingerprint.node_id,
                    "triple_hash": triple_hash,
                },
                on_failure="quarantine_twin_custody",
                metadata={
                    "safety_gate": "double_grasp_or_drop_detected",
                },
            ),
            AgentActionExecutionPlanStep(
                step_id="seal_transition_receipt",
                step_type="audit",
                description="Seal the governed custody receipt with the RCT triple hash for replay.",
                depends_on=["mechanical_release"],
                directive=AgentActionExecutionDirective(
                    tool_name="forensic.seal",
                    args={
                        "event_id": f"urn:seedcore:rct:{payload.request_id}",
                        "platform_state": "ready-for-transfer-complete",
                        "trajectory_hash": triple_hash,
                        "policy_hash": payload.security_contract.hash,
                        "auth_token": payload.request_id,
                        "from_zone": payload.asset.from_zone or "unknown",
                        "to_zone": payload.asset.to_zone or "unknown",
                    },
                ),
                state_anchors={"triple_hash": triple_hash},
                on_failure="mark_for_replay_review",
            ),
        ]
        metadata = {
            "plan_family": "robotic_rct",
            "bind_payload_hash": False,
            "triple_hash": triple_hash,
        }
        plan_id = f"plan:{payload.request_id}:{self.planner_type}"
        return AgentActionExecutionPlan(
            plan_id=plan_id,
            planner_type=self.planner_type,
            operation_type=payload.workflow.action_type,
            plan_dag_hash=_plan_dag_hash(
                plan_id=plan_id,
                planner_type=self.planner_type,
                operation_type=payload.workflow.action_type,
                state_anchors=state_anchors,
                steps=steps,
                metadata=metadata,
            ),
            state_anchors=state_anchors,
            steps=steps,
            metadata=metadata,
        )


class ConditionalEscrowPlanner(BaseExecutionPlanner):
    planner_type = PLANNER_TYPE_CONDITIONAL_ESCROW

    def build_plan(
        self,
        payload: AgentActionEvaluateRequest,
        *,
        context: PlannerContext,
    ) -> AgentActionExecutionPlan:
        planner_inputs = payload.execution.planner_inputs if payload.execution is not None else {}
        dead_mans_switch_seconds = int(planner_inputs.get("dead_mans_switch_seconds") or 300)
        governed_vault_ref = str(
            planner_inputs.get("governed_vault_ref")
            or f"vault:{payload.asset.asset_id}"
        ).strip()
        oracle_ref = str(planner_inputs.get("oracle_ref") or "telemetry.oracle").strip()
        condition_ref = str(
            planner_inputs.get("condition_ref")
            or planner_inputs.get("one_time_scan_ref")
            or f"condition:{payload.request_id}"
        ).strip()
        state_anchors = self._base_state_anchors(payload, context=context)
        state_anchors.update(
            {
                "governed_vault_ref": governed_vault_ref,
                "oracle_ref": oracle_ref,
                "condition_ref": condition_ref,
            }
        )
        steps = [
            AgentActionExecutionPlanStep(
                step_id="lock_governed_vault",
                step_type="state_lock",
                description="Move the governed asset into a restricted vault state before escrow release.",
                state_anchors={
                    "governed_vault_ref": governed_vault_ref,
                    "asset_id": payload.asset.asset_id,
                },
                on_failure="retain_principal_custody",
            ),
            AgentActionExecutionPlanStep(
                step_id="poll_release_condition",
                step_type="observe",
                description="Poll the escrow oracle until the buyer-side condition is satisfied.",
                depends_on=["lock_governed_vault"],
                state_anchors={
                    "oracle_ref": oracle_ref,
                    "condition_ref": condition_ref,
                },
                on_failure="revert_to_principal",
            ),
            AgentActionExecutionPlanStep(
                step_id="commit_atomic_swap",
                step_type="commitment",
                description="Atomically update asset provenance and release the escrowed status/funds.",
                depends_on=["poll_release_condition"],
                state_anchors={
                    "asset_id": payload.asset.asset_id,
                    "provenance_hash": payload.asset.provenance_hash,
                },
                on_failure="revert_to_principal",
            ),
            AgentActionExecutionPlanStep(
                step_id="dead_mans_revert",
                step_type="rollback",
                description="Revert governed custody to the principal if the release condition times out.",
                depends_on=["poll_release_condition"],
                state_anchors={"deadline_seconds": dead_mans_switch_seconds},
                on_failure="audit_timeout_revert",
            ),
        ]
        metadata = {
            "plan_family": "conditional_escrow",
            "bind_payload_hash": False,
            "dead_mans_switch_seconds": dead_mans_switch_seconds,
        }
        plan_id = f"plan:{payload.request_id}:{self.planner_type}"
        return AgentActionExecutionPlan(
            plan_id=plan_id,
            planner_type=self.planner_type,
            operation_type=payload.workflow.action_type,
            plan_dag_hash=_plan_dag_hash(
                plan_id=plan_id,
                planner_type=self.planner_type,
                operation_type=payload.workflow.action_type,
                state_anchors=state_anchors,
                steps=steps,
                metadata=metadata,
            ),
            state_anchors=state_anchors,
            steps=steps,
            metadata=metadata,
        )


class DelegatedAuthorityPlanner(BaseExecutionPlanner):
    planner_type = PLANNER_TYPE_DELEGATED_AUTHORITY

    def build_plan(
        self,
        payload: AgentActionEvaluateRequest,
        *,
        context: PlannerContext,
    ) -> AgentActionExecutionPlan:
        planner_inputs = payload.execution.planner_inputs if payload.execution is not None else {}
        delegate_agent_id = str(
            planner_inputs.get("delegate_agent_id")
            or planner_inputs.get("assistant_id")
            or payload.principal.agent_id
        ).strip()
        delegate_endpoint_id = str(
            planner_inputs.get("delegate_endpoint_id")
            or payload.principal.hardware_fingerprint.endpoint_id
            or payload.principal.hardware_fingerprint.node_id
            or ""
        ).strip()
        subtoken_ttl_seconds = int(planner_inputs.get("subtoken_ttl_seconds") or 90)
        state_anchors = self._base_state_anchors(payload, context=context)
        state_anchors.update(
            {
                "delegate_agent_id": delegate_agent_id,
                "delegate_endpoint_id": delegate_endpoint_id or None,
                "delegation_ref": payload.principal.delegation_ref,
            }
        )
        steps = [
            AgentActionExecutionPlanStep(
                step_id="mint_subtoken",
                step_type="delegate",
                description="Narrow the parent authority into a short-lived delegated sub-token.",
                state_anchors={
                    "delegate_agent_id": delegate_agent_id,
                    "delegate_endpoint_id": delegate_endpoint_id or None,
                    "subtoken_ttl_seconds": subtoken_ttl_seconds,
                },
                on_failure="revoke_parent_session",
            ),
            AgentActionExecutionPlanStep(
                step_id="proxy_execute",
                step_type="observe",
                description="Monitor delegated API/tool execution against the sub-token scope in real time.",
                depends_on=["mint_subtoken"],
                state_anchors={
                    "delegate_agent_id": delegate_agent_id,
                    "delegate_endpoint_id": delegate_endpoint_id or None,
                },
                on_failure="revoke_parent_session",
            ),
            AgentActionExecutionPlanStep(
                step_id="aggregate_delegate_evidence",
                step_type="audit",
                description="Collect delegated evidence summaries for result verification and replay.",
                depends_on=["proxy_execute"],
                state_anchors={"delegate_agent_id": delegate_agent_id},
                on_failure="quarantine_delegate_outcome",
            ),
        ]
        metadata = {
            "plan_family": "delegated_authority",
            "bind_payload_hash": False,
            "delegate_agent_id": delegate_agent_id,
            "delegate_endpoint_id": delegate_endpoint_id or None,
            "subtoken_ttl_seconds": subtoken_ttl_seconds,
        }
        plan_id = f"plan:{payload.request_id}:{self.planner_type}"
        return AgentActionExecutionPlan(
            plan_id=plan_id,
            planner_type=self.planner_type,
            operation_type=payload.workflow.action_type,
            plan_dag_hash=_plan_dag_hash(
                plan_id=plan_id,
                planner_type=self.planner_type,
                operation_type=payload.workflow.action_type,
                state_anchors=state_anchors,
                steps=steps,
                metadata=metadata,
            ),
            state_anchors=state_anchors,
            steps=steps,
            metadata=metadata,
        )


class ExecutionPlannerRegistry:
    def __init__(self) -> None:
        self._planners = {
            PLANNER_TYPE_PHYSICAL_HANDOVER: RoboticHandoverPlanner(),
            PLANNER_TYPE_CONDITIONAL_ESCROW: ConditionalEscrowPlanner(),
            PLANNER_TYPE_DELEGATED_AUTHORITY: DelegatedAuthorityPlanner(),
        }

    def get_planner(self, payload: AgentActionEvaluateRequest) -> BaseExecutionPlanner:
        planner_type = (
            payload.execution.planner_type
            if payload.execution is not None
            else PLANNER_TYPE_PHYSICAL_HANDOVER
        )
        return self._planners.get(planner_type, self._planners[PLANNER_TYPE_PHYSICAL_HANDOVER])


_REGISTRY = ExecutionPlannerRegistry()


def build_execution_plan(
    payload: AgentActionEvaluateRequest,
    *,
    owner_twin_snapshot: Mapping[str, Any] | None = None,
    authoritative_transfer_approval: Mapping[str, Any] | None = None,
) -> AgentActionExecutionPlan:
    planner = _REGISTRY.get_planner(payload)
    context = PlannerContext(
        owner_twin_snapshot=owner_twin_snapshot,
        authoritative_transfer_approval=authoritative_transfer_approval,
    )
    return planner.build_plan(payload, context=context)
