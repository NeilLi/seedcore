from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Mapping, Sequence
from urllib.parse import quote

from seedcore.integrations.rust_kernel import (
    approval_binding_hash_with_rust,
    evaluate_policy_with_rust,
    mint_execution_token_with_rust,
    summarize_transfer_approval_with_rust,
    validate_transfer_approval_with_rust,
)
from seedcore.models.action_intent import (
    ActionIntent,
    AuthorityLevel,
    BreakGlassDecisionContext,
    DelegatedAuthority,
    ExecutionToken,
    IntentAction,
    IntentEnvironment,
    IntentPrincipal,
    IntentResource,
    OwnerTwin,
    PolicyCase,
    PolicyCaseAssessment,
    PolicyDecision,
    SecurityContract,
    TwinRevisionStage,
    TwinSnapshot,
)
from seedcore.models.task_payload import TaskPayload
from seedcore.ops.evidence.builder import build_policy_receipt_artifact
from seedcore.ops.pkg.authz_graph.compiler import (
    AuthzDecisionDisposition,
    AuthzTransitionRequest,
    CompiledAuthzIndex,
    CompiledPermissionMatch,
    CompiledTransitionEvaluation,
)


SYSTEM_PARAM_KEYS = {
    "routing",
    "interaction",
    "multimodal",
    "cognitive",
    "chat",
    "graph",
    "tool_calls",
    "resource",
    "executor",
    "source_registration",
    "governance",
    "policy",
    "_router",
    "_emission",
    "debug",
    "trace",
    "telemetry",
    "metadata",
}

PACKING_ACTION_TYPES = {"PACK", "RELEASE"}
SOURCE_REGISTRATION_REQUIRED_DENY_CODE = "missing_source_registration"
SOURCE_REGISTRATION_UNAPPROVED_DENY_CODE = "unapproved_source_registration"
SOURCE_REGISTRATION_MISMATCH_DENY_CODE = "mismatched_registration_decision"
EXPLICIT_ALLOW_RULE = "allow_release_with_approved_source_registration"
EXPLICIT_DENY_RULE = "deny_release_without_approved_source_registration"
STALE_TWIN_DENY_CODE = "stale_twin_state"
REVOKED_DELEGATION_DENY_CODE = "revoked_delegation"
FORBIDDEN_TWIN_STATE_DENY_CODE = "forbidden_twin_state"
OWNER_SCOPE_VIOLATION_DENY_CODE = "owner_scope_violation"
OWNER_ZONE_VIOLATION_DENY_CODE = "owner_zone_violation"
OWNER_MODALITY_VIOLATION_DENY_CODE = "owner_modality_violation"
OWNER_OBSERVER_DENY_CODE = "owner_observer_restricted"
MISSING_MANDATORY_EVIDENCE_DENY_CODE = "missing_mandatory_evidence"
COGNITIVE_DENY_CODE = "cognitive_policy_denied"
POLICY_ESCALATION_CODE = "policy_escalation_required"
STALE_INTENT_DENY_CODE = "stale_intent"
INVALID_ACTOR_TOKEN_DENY_CODE = "invalid_actor_token"
ACTOR_TOKEN_SUBJECT_MISMATCH_DENY_CODE = "actor_token_subject_mismatch"
ACTOR_TOKEN_EXPIRED_DENY_CODE = "actor_token_expired"
MISSING_ACTOR_TOKEN_DENY_CODE = "missing_actor_token"
INVALID_BREAK_GLASS_TOKEN_DENY_CODE = "invalid_break_glass_token"
BREAK_GLASS_TOKEN_SUBJECT_MISMATCH_DENY_CODE = "break_glass_token_subject_mismatch"
BREAK_GLASS_TOKEN_EXPIRED_DENY_CODE = "break_glass_token_expired"
BREAK_GLASS_PROCEDURE_REQUIRED_DENY_CODE = "break_glass_procedure_required"
AUTHZ_GRAPH_DENY_CODE = "authz_graph_denied"
AUTHZ_GRAPH_SNAPSHOT_MISMATCH_DENY_CODE = "authz_graph_snapshot_mismatch"
EXECUTION_TOKEN_CONSTRAINT_KEYS = (
    "action_type",
    "target_zone",
    "asset_id",
    "principal_agent_id",
    "source_registration_id",
    "registration_decision_id",
    "endpoint_id",
)
DEFAULT_EXECUTION_TOKEN_TTL_SECONDS = 5
RESTRICTED_CUSTODY_TRANSFER_WORKFLOW_TYPE = "custody_transfer"
RESTRICTED_CUSTODY_TRANSFER_ACTION_TYPES = {"TRANSFER_CUSTODY"}


def requires_action_intent(task: TaskPayload | Mapping[str, Any] | Dict[str, Any]) -> bool:
    payload = _task_to_dict(task)
    task_type = str(payload.get("type") or "").strip().lower()
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    governance = params.get("governance") if isinstance(params.get("governance"), dict) else {}
    return task_type == "action" or bool(governance.get("require_action_intent"))


def build_action_intent(task: TaskPayload | Mapping[str, Any] | Dict[str, Any]) -> ActionIntent:
    payload = _task_to_dict(task)
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    governance = params.get("governance") if isinstance(params.get("governance"), dict) else {}
    embedded_intent = governance.get("action_intent")
    derived_intent = _derive_action_intent_from_task(payload, params, governance)
    if isinstance(embedded_intent, ActionIntent):
        merged_payload = _merge_action_intent_payload(
            derived_intent.model_dump(mode="json"),
            embedded_intent.model_dump(mode="json"),
        )
        return ActionIntent(**merged_payload)
    if isinstance(embedded_intent, Mapping) and embedded_intent:
        merged_payload = _merge_action_intent_payload(
            derived_intent.model_dump(mode="json"),
            dict(embedded_intent),
        )
        return ActionIntent(**merged_payload)
    return derived_intent


def _derive_action_intent_from_task(
    payload: Dict[str, Any],
    params: Dict[str, Any],
    governance: Dict[str, Any],
) -> ActionIntent:
    routing = params.get("routing") if isinstance(params.get("routing"), dict) else {}
    interaction = params.get("interaction") if isinstance(params.get("interaction"), dict) else {}
    multimodal = params.get("multimodal") if isinstance(params.get("multimodal"), dict) else {}
    resource = params.get("resource") if isinstance(params.get("resource"), dict) else {}
    executor = params.get("executor") if isinstance(params.get("executor"), dict) else {}
    cognitive = params.get("cognitive") if isinstance(params.get("cognitive"), dict) else {}
    metadata = params.get("metadata") if isinstance(params.get("metadata"), dict) else {}
    trace = params.get("trace") if isinstance(params.get("trace"), dict) else {}
    source_registration = (
        params.get("source_registration")
        if isinstance(params.get("source_registration"), dict)
        else {}
    )
    registration_decision = (
        governance.get("registration_decision")
        if isinstance(governance.get("registration_decision"), dict)
        else {}
    )

    issued_at = _utcnow()
    ttl_seconds = _derive_ttl_seconds(payload, routing, governance)
    valid_until = issued_at + timedelta(seconds=ttl_seconds)

    role_profile = (
        routing.get("required_specialization")
        or routing.get("specialization")
        or executor.get("specialization")
        or cognitive.get("role_profile")
        or "coordinator_service"
    )
    principal_agent = (
        interaction.get("assigned_agent_id")
        or cognitive.get("agent_id")
        or payload.get("agent_id")
        or "coordinator_service"
    )
    fallback_entropy = _stable_fallback_entropy(payload)
    session_token = (
        interaction.get("session_token")
        or interaction.get("conversation_id")
        or payload.get("correlation_id")
        or payload.get("task_id")
        or f"session_{fallback_entropy}"
    )
    actor_token = (
        interaction.get("actor_token")
        or interaction.get("principal_token")
        or governance.get("actor_token")
    )

    target_zone = (
        multimodal.get("location_context")
        or resource.get("target_zone")
        or params.get("location_context")
    )
    asset_id = (
        resource.get("asset_id")
        or params.get("asset_id")
        or multimodal.get("asset_id")
        or payload.get("task_id")
        or f"asset_{fallback_entropy}"
    )
    provenance_hash = (
        resource.get("provenance_hash")
        or params.get("provenance_hash")
        or _sha256_hex(
            _canonical_json(
                params.get("provenance")
                or {
                    "task_id": payload.get("task_id"),
                    "description": payload.get("description"),
                    "media_uri": multimodal.get("media_uri"),
                    "source": multimodal.get("source"),
                }
            )
        )
    )
    resource_uri = (
        resource.get("resource_uri")
        or params.get("resource_uri")
        or _derive_resource_uri(asset_id=asset_id, target_zone=target_zone)
    )
    twin_inputs = (
        governance.get("digital_twins")
        if isinstance(governance.get("digital_twins"), dict)
        else {}
    )
    resource_state_hash = (
        resource.get("resource_state_hash")
        or params.get("resource_state_hash")
        or _derive_resource_state_hash(
            asset_id=asset_id,
            target_zone=target_zone,
            twin_inputs=twin_inputs,
            resource=resource,
        )
    )
    source_registration_id = (
        resource.get("source_registration_id")
        or params.get("source_registration_id")
        or source_registration.get("registration_id")
        or registration_decision.get("registration_id")
    )
    registration_decision_id = (
        resource.get("registration_decision_id")
        or params.get("registration_decision_id")
        or registration_decision.get("decision_id")
        or registration_decision.get("id")
    )
    lot_id = (
        resource.get("lot_id")
        or params.get("lot_id")
        or source_registration.get("lot_id")
    )
    batch_twin_id = (
        resource.get("batch_twin_id")
        or (f"batch:{lot_id}" if lot_id is not None else None)
    )
    parent_asset_id = resource.get("parent_asset_id") or params.get("parent_asset_id")
    category_envelope = (
        dict(resource.get("category_envelope"))
        if isinstance(resource.get("category_envelope"), dict)
        else {}
    )
    product_id = (
        resource.get("product_id")
        or category_envelope.get("product_id")
    )
    origin_network = (
        interaction.get("origin_network")
        or trace.get("origin_network")
        or metadata.get("origin_network")
        or payload.get("origin_network")
    )
    break_glass_token = (
        interaction.get("break_glass_token")
        or governance.get("break_glass_token")
        or metadata.get("break_glass_token")
    )
    break_glass_reason = (
        interaction.get("break_glass_reason")
        or governance.get("break_glass_reason")
        or metadata.get("break_glass_reason")
    )

    contract_version = _derive_contract_version(payload, governance)
    action_type = _derive_action_type(payload, params)
    action_parameters = _derive_action_parameters(params)
    if governance.get("requires_approved_source_registration") is not None:
        action_parameters.setdefault(
            "requires_approved_source_registration",
            bool(governance.get("requires_approved_source_registration")),
        )
    security_contract = SecurityContract(
        hash=_sha256_hex(
            _canonical_json(
                {
                    "role_profile": role_profile,
                    "contract_version": contract_version,
                    "routing_tools": routing.get("tools") or [],
                    "skills": routing.get("skills") or {},
                    "target_zone": target_zone,
                    "task_type": payload.get("type"),
                    "action_type": action_type,
                    "source_registration_id": source_registration_id,
                    "lot_id": lot_id,
                    "product_id": product_id,
                }
            )
        ),
        version=contract_version,
    )

    return ActionIntent(
        intent_id=str(uuid.uuid4()),
        timestamp=_isoformat(issued_at),
        valid_until=_isoformat(valid_until),
        principal=IntentPrincipal(
            agent_id=str(principal_agent),
            role_profile=str(role_profile),
            session_token=str(session_token),
            actor_token=str(actor_token) if actor_token is not None else None,
        ),
        action=IntentAction(
            type=action_type,
            parameters=action_parameters,
            security_contract=security_contract,
        ),
        resource=IntentResource(
            asset_id=str(asset_id),
            resource_uri=str(resource_uri) if resource_uri is not None else None,
            resource_state_hash=(
                str(resource_state_hash)
                if resource_state_hash is not None
                else None
            ),
            target_zone=str(target_zone) if target_zone is not None else None,
            provenance_hash=str(provenance_hash),
            source_registration_id=(
                str(source_registration_id) if source_registration_id is not None else None
            ),
            registration_decision_id=(
                str(registration_decision_id)
                if registration_decision_id is not None
                else None
            ),
            lot_id=(str(lot_id) if lot_id is not None else None),
            batch_twin_id=(str(batch_twin_id) if batch_twin_id is not None else None),
            parent_asset_id=(
                str(parent_asset_id)
                if parent_asset_id is not None
                else None
            ),
            product_id=(str(product_id) if product_id is not None else None),
            category_envelope=category_envelope,
        ),
        environment=IntentEnvironment(
            origin_network=str(origin_network) if origin_network is not None else None,
            break_glass_token=(
                str(break_glass_token) if break_glass_token is not None else None
            ),
            break_glass_reason=(
                str(break_glass_reason) if break_glass_reason is not None else None
            ),
        ),
    )


def prepare_policy_case(
    task: TaskPayload | Mapping[str, Any] | Dict[str, Any] | ActionIntent,
    *,
    policy_snapshot: str | None = None,
    approved_source_registrations: Mapping[str, str | None] | None = None,
    relevant_twin_snapshot: Mapping[str, Any] | None = None,
    telemetry_summary: Mapping[str, Any] | None = None,
    cognitive_assessment: Mapping[str, Any] | PolicyCaseAssessment | None = None,
    evidence_summary: Mapping[str, Any] | None = None,
    authoritative_approval_envelope: Mapping[str, Any] | None = None,
    authoritative_approval_transition_history: Sequence[Mapping[str, Any]] | None = None,
    authoritative_approval_transition_head: str | None = None,
) -> PolicyCase:
    action_intent = task if isinstance(task, ActionIntent) else build_action_intent(task)
    resolved_snapshot = (
        policy_snapshot
        or action_intent.action.security_contract.version
    )
    resolved_twins = dict(relevant_twin_snapshot or {}) or build_twin_snapshot(task)
    action_intent = apply_twin_overrides_to_action_intent(action_intent, resolved_twins)
    _sanitize_transfer_approval_context(action_intent)
    _apply_authoritative_transfer_approval(
        action_intent,
        approval_envelope=authoritative_approval_envelope,
        transition_history=authoritative_approval_transition_history,
        transition_head=authoritative_approval_transition_head,
    )
    resolved_cognitive = _coerce_policy_case_assessment(cognitive_assessment)
    return PolicyCase(
        action_intent=action_intent,
        policy_snapshot=resolved_snapshot,
        relevant_twin_snapshot={
            key: _coerce_twin_snapshot(key, value)
            for key, value in resolved_twins.items()
        },
        approved_source_registrations=dict(approved_source_registrations or {}),
        telemetry_summary=dict(telemetry_summary or {}),
        cognitive_assessment=resolved_cognitive,
        evidence_summary=dict(evidence_summary or {}),
        authoritative_approval_envelope=(
            dict(authoritative_approval_envelope)
            if isinstance(authoritative_approval_envelope, Mapping)
            else {}
        ),
        authoritative_approval_transition_history=[
            dict(item)
            for item in (authoritative_approval_transition_history or [])
            if isinstance(item, Mapping)
        ],
        authoritative_approval_transition_head=(
            str(authoritative_approval_transition_head).strip()
            if authoritative_approval_transition_head is not None and str(authoritative_approval_transition_head).strip()
            else None
        ),
    )


def merge_authoritative_twins(
    baseline_twins: Dict[str, TwinSnapshot],
    authoritative_state: Dict[str, Any],
) -> Dict[str, TwinSnapshot]:
    """
    Overrides untrusted AI-provided twin states with authoritative system ground truth.
    """
    normalized_state = normalize_authoritative_state(authoritative_state)
    agents_state = normalized_state.get("agents", {})
    assets_state = normalized_state.get("assets", {})
    
    if "assistant" in baseline_twins:
        agent_id = baseline_twins["assistant"].identity.get("agent_id")
        if agent_id and agent_id in agents_state:
            agent_data = agents_state[agent_id]
            baseline_twins["assistant"].delegation["revoked"] = bool(agent_data.get("is_revoked", False))
            if "role_profile" in agent_data:
                baseline_twins["assistant"].delegation["role_profile"] = str(agent_data["role_profile"])
            if "risk_score" in agent_data:
                baseline_twins["assistant"].risk["score"] = float(agent_data["risk_score"])
                
    if "asset" in baseline_twins:
        # Asset ID is stored in custody, or we can fallback to identity/twin_id parsing
        asset_id = (
            baseline_twins["asset"].custody.get("asset_id") 
            or baseline_twins["asset"].identity.get("asset_id")
            or baseline_twins["asset"].twin_id.replace("asset:", "")
        )
        if asset_id and asset_id in assets_state:
            asset_data = assets_state[asset_id]
            baseline_twins["asset"].custody["quarantined"] = bool(asset_data.get("is_quarantined", False))
            if "current_zone" in asset_data:
                auth_zone = str(asset_data["current_zone"])
                baseline_twins["asset"].custody["target_zone"] = auth_zone
                if "edge" in baseline_twins:
                    baseline_twins["edge"].telemetry["target_zone"] = auth_zone
                    
    return baseline_twins


def _authoritative_approval_envelope(policy_case: PolicyCase) -> Dict[str, Any] | None:
    payload = (
        policy_case.authoritative_approval_envelope
        if isinstance(policy_case.authoritative_approval_envelope, Mapping)
        else {}
    )
    return dict(payload) if payload else None


def _authoritative_approval_transition_history(policy_case: PolicyCase) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in (
            policy_case.authoritative_approval_transition_history
            if isinstance(policy_case.authoritative_approval_transition_history, list)
            else []
        )
        if isinstance(item, Mapping)
    ]


def _authoritative_approval_transition_head(policy_case: PolicyCase) -> str | None:
    raw = policy_case.authoritative_approval_transition_head
    if raw is None:
        return None
    normalized = str(raw).strip()
    return normalized or None


def normalize_authoritative_state(authoritative_state: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(authoritative_state, dict):
        return {"agents": {}, "assets": {}}

    payload = authoritative_state.get("payload")
    if isinstance(payload, dict):
        agents_state = payload.get("agents", {})
        assets_state = payload.get("assets", {})
    else:
        agents_state = authoritative_state.get("agents", {})
        assets_state = authoritative_state.get("assets", {})

    return {
        "agents": dict(agents_state) if isinstance(agents_state, dict) else {},
        "assets": dict(assets_state) if isinstance(assets_state, dict) else {},
    }


def apply_twin_overrides_to_action_intent(
    action_intent: ActionIntent,
    relevant_twin_snapshot: Mapping[str, Any] | None,
) -> ActionIntent:
    if not relevant_twin_snapshot:
        return action_intent

    twins = {
        key: _coerce_twin_snapshot(key, value)
        for key, value in dict(relevant_twin_snapshot).items()
    }

    assistant_twin = twins.get("assistant")
    asset_twin = twins.get("asset")

    if assistant_twin is not None:
        authoritative_role = assistant_twin.delegation.get("role_profile")
        if isinstance(authoritative_role, str) and authoritative_role.strip():
            action_intent.principal.role_profile = authoritative_role.strip()

    if asset_twin is not None:
        authoritative_zone = asset_twin.custody.get("target_zone")
        if isinstance(authoritative_zone, str) and authoritative_zone.strip():
            action_intent.resource.target_zone = authoritative_zone.strip()
            action_intent.resource.resource_uri = _derive_resource_uri(
                asset_id=action_intent.resource.asset_id,
                target_zone=action_intent.resource.target_zone,
            )
        action_intent.resource.resource_state_hash = _sha256_hex(
            _canonical_json(asset_twin.model_dump(mode="json"))
        )

    action_intent.action.security_contract.hash = _sha256_hex(
        _canonical_json(
            {
                "role_profile": action_intent.principal.role_profile,
                "contract_version": action_intent.action.security_contract.version,
                "target_zone": action_intent.resource.target_zone,
                "action_type": action_intent.action.type,
                "asset_id": action_intent.resource.asset_id,
                "source_registration_id": action_intent.resource.source_registration_id,
                "registration_decision_id": action_intent.resource.registration_decision_id,
                "lot_id": action_intent.resource.lot_id,
                "product_id": action_intent.resource.product_id,
            }
        )
    )

    return action_intent

def build_twin_snapshot(
    task: TaskPayload | Mapping[str, Any] | Dict[str, Any] | ActionIntent,
) -> Dict[str, TwinSnapshot]:
    if isinstance(task, ActionIntent):
        intent = task
        payload: Dict[str, Any] = {}
        params: Dict[str, Any] = {}
    else:
        payload = _task_to_dict(task)
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        intent = build_action_intent(payload)

    governance = params.get("governance") if isinstance(params.get("governance"), dict) else {}
    twin_inputs = governance.get("digital_twins") if isinstance(governance.get("digital_twins"), dict) else {}
    multimodal = params.get("multimodal") if isinstance(params.get("multimodal"), dict) else {}
    resource = params.get("resource") if isinstance(params.get("resource"), dict) else {}
    owner_input = (
        governance.get("owner_twin")
        if isinstance(governance.get("owner_twin"), dict)
        else (
            twin_inputs.get("owner")
            if isinstance(twin_inputs.get("owner"), dict)
            else {}
        )
    )

    def _snapshot(
        twin_key: str,
        twin_id: str,
        *,
        lifecycle_state: str,
        lineage_refs: list[str] | None = None,
        identity: Mapping[str, Any] | None = None,
        governance_state: Mapping[str, Any] | None = None,
        risk: Mapping[str, Any] | None = None,
        delegation: Mapping[str, Any] | None = None,
        custody: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any] | None = None,
        telemetry: Mapping[str, Any] | None = None,
    ) -> TwinSnapshot:
        source = twin_inputs.get(twin_key) if isinstance(twin_inputs.get(twin_key), dict) else {}
        freshness = source.get("freshness") if isinstance(source.get("freshness"), dict) else {}
        return TwinSnapshot(
            twin_kind=str(source.get("twin_kind") or twin_key),
            twin_id=str(source.get("twin_id") or twin_id),
            revision_stage=str(source.get("revision_stage") or TwinRevisionStage.PROPOSED.value),
            lifecycle_state=str(source.get("lifecycle_state") or lifecycle_state),
            lineage_refs=[
                str(item)
                for item in (
                    source.get("lineage_refs")
                    if isinstance(source.get("lineage_refs"), list)
                    else (lineage_refs or [])
                )
            ],
            evidence_refs=[
                str(item)
                for item in (
                    source.get("evidence_refs")
                    if isinstance(source.get("evidence_refs"), list)
                    else []
                )
            ],
            freshness={
                "status": source.get("freshness_status") or freshness.get("status") or "unknown",
                "observed_at": source.get("observed_at") or freshness.get("observed_at"),
                "max_age_seconds": source.get("max_age_seconds") or freshness.get("max_age_seconds"),
            },
            identity=dict(identity or source.get("identity") or {}),
            governance=dict(governance_state or source.get("governance") or {}),
            risk=dict(risk or source.get("risk") or {}),
            delegation=dict(delegation or source.get("delegation") or {}),
            custody=dict(custody or source.get("custody") or {}),
            provenance=dict(provenance or source.get("provenance") or {}),
            telemetry=dict(telemetry or source.get("telemetry") or {}),
        )

    target_zone = intent.resource.target_zone or multimodal.get("location_context")
    category_envelope = (
        dict(intent.resource.category_envelope)
        if isinstance(intent.resource.category_envelope, dict)
        else (
            dict(resource.get("category_envelope"))
            if isinstance(resource.get("category_envelope"), dict)
            else {}
        )
    )
    lot_id = (
        intent.resource.lot_id
        or resource.get("lot_id")
        or (
            params.get("source_registration", {}).get("lot_id")
            if isinstance(params.get("source_registration"), dict)
            else None
        )
    )
    batch_twin_id = (
        intent.resource.batch_twin_id
        or resource.get("batch_twin_id")
        or (f"batch:{lot_id}" if lot_id else None)
    )
    parent_twin_id = (
        resource.get("parent_twin_id")
        or batch_twin_id
        or intent.resource.parent_asset_id
        or resource.get("parent_asset_id")
    )
    product_id = (
        intent.resource.product_id
        or category_envelope.get("product_id")
    )
    product_twin_id = f"product:{product_id}" if product_id else None
    owner_id = (
        resource.get("current_custodian_id")
        or resource.get("owner_id")
        or owner_input.get("owner_id")
        or owner_input.get("did")
        or payload.get("owner_id")
        or f"did:seedcore:owner:{intent.resource.asset_id}"
    )
    owner_id = str(owner_id)
    if not owner_id.startswith("did:"):
        owner_id = f"did:seedcore:owner:{owner_id}"

    owner_delegations = owner_input.get("delegations")
    if not isinstance(owner_delegations, list):
        owner_delegations = []
    parsed_delegations: list[DelegatedAuthority] = []
    for entry in owner_delegations:
        if not isinstance(entry, dict):
            continue
        try:
            parsed_delegations.append(DelegatedAuthority(**entry))
        except Exception:
            continue

    owner_twin = OwnerTwin(
        owner_id=owner_id,
        public_key_fingerprint=(
            str(owner_input.get("public_key_fingerprint"))
            if owner_input.get("public_key_fingerprint") is not None
            else None
        ),
        delegations=parsed_delegations,
        state=str(owner_input.get("state") or "ACTIVE"),
        graph_ref=(
            str(owner_input.get("graph_ref"))
            if owner_input.get("graph_ref") is not None
            else None
        ),
    )

    asset_lineage_refs: list[str] = []
    if batch_twin_id:
        asset_lineage_refs.append(str(batch_twin_id))
    elif parent_twin_id:
        asset_lineage_refs.append(str(parent_twin_id))

    snapshots = {
        "owner": _snapshot(
            "owner",
            f"owner:{owner_twin.owner_id}",
            lifecycle_state=owner_twin.state,
            identity={
                "owner_id": owner_twin.owner_id,
                "public_key_fingerprint": owner_twin.public_key_fingerprint,
                "graph_ref": owner_twin.graph_ref,
            },
            governance_state={
                "current_custodian_id": owner_twin.owner_id,
                "owner_state": owner_twin.state,
                "lockouts": [],
                "pending_exceptions": [],
                "conflicts": [],
            },
            risk={},
            delegation={
                "principal_agent_id": intent.principal.agent_id,
                "delegations": [item.model_dump(mode="json") for item in owner_twin.delegations],
            },
        ),
        "assistant": _snapshot(
            "assistant",
            f"assistant:{intent.principal.agent_id}",
            lifecycle_state="READY",
            identity={"agent_id": intent.principal.agent_id},
            governance_state={
                "current_custodian_id": owner_twin.owner_id,
                "lockouts": [],
                "pending_exceptions": [],
                "conflicts": [],
            },
            risk={},
            delegation={"role_profile": intent.principal.role_profile},
        ),
        "asset": _snapshot(
            "asset",
            f"asset:{intent.resource.asset_id}",
            lifecycle_state="REGISTERED",
            lineage_refs=asset_lineage_refs,
            custody={
                "asset_id": intent.resource.asset_id,
                "target_zone": target_zone,
                "current_custodian_id": owner_twin.owner_id,
                "category_envelope": category_envelope,
                "lot_id": lot_id,
                "batch_twin_id": batch_twin_id,
                "product_id": product_id,
            },
            governance_state={
                "current_custodian_id": owner_twin.owner_id,
                "lockouts": [],
                "pending_exceptions": [],
                "conflicts": [],
            },
            risk={},
            provenance={"provenance_hash": intent.resource.provenance_hash},
        ),
        "edge": _snapshot(
            "edge",
            f"edge:{target_zone or 'unknown'}",
            lifecycle_state="OBSERVED",
            governance_state={"lockouts": [], "pending_exceptions": [], "conflicts": []},
            risk={},
            telemetry={"target_zone": target_zone},
        ),
        "transaction": _snapshot(
            "transaction",
            f"transaction:{intent.intent_id}",
            lifecycle_state="PREPARED",
            governance_state={
                "current_custodian_id": owner_twin.owner_id,
                "lockouts": [],
                "pending_exceptions": [],
                "conflicts": [],
            },
            risk={},
            custody={"intent_id": intent.intent_id},
            telemetry={"session_token": intent.principal.session_token},
        ),
    }
    if batch_twin_id:
        snapshots["batch"] = _snapshot(
            "batch",
            str(batch_twin_id),
            lifecycle_state="REGISTERED",
            lineage_refs=[str(product_twin_id)] if product_twin_id else [],
            identity={
                "batch_twin_id": str(batch_twin_id),
                "lot_id": lot_id,
            },
            governance_state={
                "current_custodian_id": owner_twin.owner_id,
                "lockouts": [],
                "pending_exceptions": [],
                "conflicts": [],
            },
            custody={
                "asset_id": intent.resource.asset_id,
                "target_zone": target_zone,
                "current_custodian_id": owner_twin.owner_id,
                "lot_id": lot_id,
                "batch_twin_id": str(batch_twin_id),
            },
            provenance={
                "source_registration_id": intent.resource.source_registration_id,
                "provenance_hash": intent.resource.provenance_hash,
            },
        )
    if product_twin_id:
        snapshots["product"] = _snapshot(
            "product",
            str(product_twin_id),
            lifecycle_state="REGISTERED",
            identity={"product_id": str(product_id)},
            governance_state={"lockouts": [], "pending_exceptions": [], "conflicts": []},
            provenance={
                "source_registration_id": intent.resource.source_registration_id,
                "category_envelope": category_envelope,
            },
        )
    return snapshots


def evaluate_intent(
    action_intent: ActionIntent | PolicyCase,
    *,
    policy_snapshot: str | None = None,
    compiled_authz_index: CompiledAuthzIndex | None = None,
    approved_source_registrations: Mapping[str, str | None] | None = None,
    relevant_twin_snapshot: Mapping[str, Any] | None = None,
    telemetry_summary: Mapping[str, Any] | None = None,
    cognitive_assessment: Mapping[str, Any] | PolicyCaseAssessment | None = None,
    evidence_summary: Mapping[str, Any] | None = None,
    authoritative_approval_envelope: Mapping[str, Any] | None = None,
    authoritative_approval_transition_history: Sequence[Mapping[str, Any]] | None = None,
    authoritative_approval_transition_head: str | None = None,
) -> PolicyDecision:
    policy_case = (
        action_intent
        if isinstance(action_intent, PolicyCase)
        else prepare_policy_case(
            action_intent,
            policy_snapshot=policy_snapshot,
            approved_source_registrations=approved_source_registrations,
            relevant_twin_snapshot=relevant_twin_snapshot,
            telemetry_summary=telemetry_summary,
            cognitive_assessment=cognitive_assessment,
            evidence_summary=evidence_summary,
            authoritative_approval_envelope=authoritative_approval_envelope,
            authoritative_approval_transition_history=authoritative_approval_transition_history,
            authoritative_approval_transition_head=authoritative_approval_transition_head,
        )
    )
    action_intent = policy_case.action_intent
    policy_snapshot = policy_case.policy_snapshot
    now = _utcnow()
    try:
        issued_at = _parse_iso8601(action_intent.timestamp)
        valid_until = _parse_iso8601(action_intent.valid_until)
    except ValueError:
        return _finalize_policy_decision_contract(
            policy_case=policy_case,
            policy_decision=_deny_decision(
                "ActionIntent contains invalid timestamps.",
                "invalid_timestamp",
                policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
            ),
        )

    if valid_until <= issued_at:
        return _finalize_policy_decision_contract(
            policy_case=policy_case,
            policy_decision=_deny_decision(
                "ActionIntent TTL is non-positive.",
                "expired_intent",
                policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
            ),
        )
    if valid_until <= now:
        return _finalize_policy_decision_contract(
            policy_case=policy_case,
            policy_decision=_deny_decision(
                "ActionIntent TTL is expired.",
                "expired_intent",
                policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
            ),
        )
    intent_age_ms = (now - issued_at).total_seconds() * 1000.0
    max_intent_age_ms = _pdp_max_intent_age_ms()
    if max_intent_age_ms > 0 and intent_age_ms > max_intent_age_ms:
        return _finalize_policy_decision_contract(
            policy_case=policy_case,
            policy_decision=_deny_decision(
                f"ActionIntent is older than the permitted freshness window ({max_intent_age_ms}ms).",
                STALE_INTENT_DENY_CODE,
                policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
            ),
        )

    if not action_intent.principal.agent_id.strip():
        return _finalize_policy_decision_contract(
            policy_case=policy_case,
            policy_decision=_deny_decision(
                "ActionIntent is missing principal.agent_id.",
                "missing_principal",
                policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
            ),
        )

    if not action_intent.principal.role_profile.strip():
        return _finalize_policy_decision_contract(
            policy_case=policy_case,
            policy_decision=_deny_decision(
                "ActionIntent is missing principal.role_profile.",
                "missing_role_profile",
                policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
            ),
        )

    if not action_intent.action.security_contract.version.strip():
        return _finalize_policy_decision_contract(
            policy_case=policy_case,
            policy_decision=_deny_decision(
                "ActionIntent is missing action.security_contract.version.",
                "missing_contract_version",
                policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
            ),
        )

    actor_token_violation = _evaluate_actor_token_policy(
        action_intent=action_intent,
        now=now,
        policy_snapshot=policy_snapshot,
        policy_case=policy_case,
    )
    if actor_token_violation is not None:
        return _finalize_policy_decision_contract(
            policy_case=policy_case,
            policy_decision=actor_token_violation,
        )

    registration_deny_code = _source_registration_deny_code(
        action_intent,
        policy_case.approved_source_registrations,
    )
    if registration_deny_code is not None:
        return _finalize_policy_decision_contract(
            policy_case=policy_case,
            policy_decision=_deny_decision(
                _source_registration_deny_reason(registration_deny_code),
                registration_deny_code,
                policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
            ),
        )

    twin_violation = _evaluate_twin_policy(policy_case)
    if twin_violation is not None:
        return _finalize_policy_decision_contract(
            policy_case=policy_case,
            policy_decision=twin_violation,
        )

    cognitive_violation = _evaluate_cognitive_policy(policy_case)
    if cognitive_violation is not None:
        return _finalize_policy_decision_contract(
            policy_case=policy_case,
            policy_decision=cognitive_violation,
        )

    transfer_prerequisite_violation = _evaluate_restricted_custody_transfer_prerequisites(
        policy_case=policy_case,
    )
    use_rust_policy_core = (
        _is_restricted_custody_transfer(action_intent)
        and _pdp_use_rust_policy_core_for_restricted_transfer()
    )
    if transfer_prerequisite_violation is not None:
        transfer_prereq_disposition = str(transfer_prerequisite_violation.disposition or "deny").strip().lower()
    else:
        transfer_prereq_disposition = None
    if transfer_prerequisite_violation is not None and (
        not use_rust_policy_core
        or transfer_prereq_disposition in {"escalate", "quarantine"}
    ):
        return _finalize_policy_decision_contract(
            policy_case=policy_case,
            policy_decision=transfer_prerequisite_violation,
        )

    authz_graph_violation = None
    break_glass_context = BreakGlassDecisionContext()
    transition_evaluation = None
    compiled_match = None
    authz_evaluator = None
    if transfer_prerequisite_violation is None or use_rust_policy_core:
        authz_graph_violation, break_glass_context, transition_evaluation, compiled_match, authz_evaluator = _evaluate_compiled_authz_graph_policy(
            action_intent=action_intent,
            policy_case=policy_case,
            compiled_authz_index=_resolve_compiled_authz_index(compiled_authz_index),
        )
        if authz_graph_violation is not None and not use_rust_policy_core:
            return _finalize_policy_decision_contract(
                policy_case=policy_case,
                policy_decision=authz_graph_violation,
            )

    if use_rust_policy_core:
        authority_graph = _authz_graph_decision_metadata(
            transition_evaluation=transition_evaluation,
            compiled_match=compiled_match,
            evaluator=authz_evaluator,
        )
        transfer_missing = (
            _extract_policy_codes(transfer_prerequisite_violation.authz_graph.get("missing_prerequisites"))
            if transfer_prerequisite_violation is not None and isinstance(transfer_prerequisite_violation.authz_graph, Mapping)
            else []
        )
        if transfer_prerequisite_violation is not None and isinstance(transfer_prerequisite_violation.authz_graph, Mapping):
            transfer_authz_graph = dict(transfer_prerequisite_violation.authz_graph)
            if not authority_graph:
                authority_graph = transfer_authz_graph
            elif authority_graph.get("reason") is None and transfer_authz_graph.get("reason") is not None:
                authority_graph["reason"] = transfer_authz_graph.get("reason")
        transition_missing = _extract_policy_codes(authority_graph.get("missing_prerequisites"))
        transition_gaps = _extract_policy_codes(authority_graph.get("trust_gaps"))
        if authz_graph_violation is not None and isinstance(authz_graph_violation.authz_graph, Mapping):
            transition_missing = _merge_policy_code_lists(
                transition_missing,
                _extract_policy_codes(authz_graph_violation.authz_graph.get("missing_prerequisites")),
            )
            transition_gaps = _merge_policy_code_lists(
                transition_gaps,
                _extract_policy_codes(authz_graph_violation.authz_graph.get("trust_gaps")),
            )
            if not authority_graph:
                authority_graph = dict(authz_graph_violation.authz_graph)

        approval_context = _approval_context(action_intent)
        approval_envelope = _authoritative_approval_envelope(policy_case)
        telemetry_summary = policy_case.telemetry_summary if isinstance(policy_case.telemetry_summary, Mapping) else {}
        rust_input = {
            "action_intent": {
                "intent_id": action_intent.intent_id,
                "timestamp": action_intent.timestamp,
                "valid_until": action_intent.valid_until,
                "principal": {
                    "principal_ref": f"principal:{action_intent.principal.agent_id}",
                    "organization_ref": None,
                    "role_refs": [f"role:{action_intent.principal.role_profile}"],
                },
                "action": {
                    "action_type": action_intent.action.type,
                    "target_zone": action_intent.resource.target_zone,
                    "endpoint_id": (
                        action_intent.action.parameters.get("endpoint_id")
                        if isinstance(action_intent.action.parameters, Mapping)
                        else None
                    ),
                },
                "resource": {
                    "asset_ref": action_intent.resource.asset_id,
                    "lot_id": action_intent.resource.lot_id,
                },
                "environment": {
                    "source_registration_id": action_intent.resource.source_registration_id,
                    "registration_decision_id": action_intent.resource.registration_decision_id,
                    "attributes": {},
                },
            },
            "approval_envelope": approval_envelope,
            "policy_snapshot_ref": policy_snapshot or action_intent.action.security_contract.version,
            "asset_state": {
                "asset_ref": action_intent.resource.asset_id,
                "current_custodian_ref": _transfer_context_value(
                    action_intent,
                    "expected_current_custodian",
                    "from_custodian_ref",
                ),
                "current_zone_ref": _transfer_context_value(action_intent, "from_zone"),
                "custody_point_ref": _transfer_context_value(action_intent, "custody_point_ref"),
                "transferable": bool(
                    (transition_evaluation is None)
                    or (
                        getattr(getattr(transition_evaluation, "asset_state", None), "transferable", True)
                    )
                ),
                "restricted": bool(
                    getattr(getattr(transition_evaluation, "asset_state", None), "restricted", False)
                ),
                "evidence_refs": [],
                "approved_registration_refs": [],
            },
            "authority_graph_summary": {
                "matched_policy_refs": list(
                    authority_graph.get("matched_policy_refs")
                    if isinstance(authority_graph.get("matched_policy_refs"), list)
                    else []
                ),
                "authority_paths": list(
                    authority_graph.get("authority_path_summary")
                    if isinstance(authority_graph.get("authority_path_summary"), list)
                    else []
                ),
                "missing_prerequisites": _merge_policy_code_lists(
                    _rust_kernel_missing_prerequisites(transfer_missing),
                    _rust_kernel_missing_prerequisites(transition_missing),
                ),
                "trust_gaps": transition_gaps,
            },
            "telemetry_summary": {
                "observed_at": telemetry_summary.get("observed_at"),
                "stale": bool(
                    any(code in {"stale_telemetry", "telemetry_freshness"} for code in transition_gaps)
                    or bool(telemetry_summary.get("stale"))
                ),
                "attested": not bool(telemetry_summary.get("missing_attestation", False)),
                "seal_present": telemetry_summary.get("seal_present"),
            },
            "break_glass": {
                "present": bool(getattr(break_glass_context, "present", False)),
                "validated": bool(getattr(break_glass_context, "validated", False)),
                "principal_ref": (
                    f"principal:{break_glass_context.principal_id}"
                    if getattr(break_glass_context, "principal_id", None)
                    else None
                ),
                "reason": getattr(break_glass_context, "reason", None),
            },
        }
        rust_eval = evaluate_policy_with_rust(rust_input)
        if rust_eval.get("error") is not None:
            return _finalize_policy_decision_contract(
                policy_case=policy_case,
                policy_decision=_deny_decision(
                    "Rust policy kernel evaluation failed.",
                    "rust_policy_evaluation_failed",
                    policy_snapshot,
                    risk_score=_policy_case_risk_score(policy_case),
                    cognitive_assessment=policy_case.cognitive_assessment,
                    explanations=_policy_case_explanations(
                        policy_case,
                        "rust_policy_evaluation_failed",
                    ),
                    authz_graph={"mode": "rust_policy_core", "rust_error": rust_eval.get("error")},
                ),
            )

        rust_disposition = str(rust_eval.get("disposition") or "deny").strip().lower()
        if rust_disposition not in {"allow", "deny", "quarantine", "escalate"}:
            rust_disposition = "deny"
        token_valid_until = min(
            valid_until,
            now + timedelta(seconds=_execution_token_ttl_seconds()),
        )
        execution_constraints = dict(
            _transition_execution_constraints(transition_evaluation)
            if transition_evaluation is not None
            else {}
        )
        if _is_restricted_custody_transfer(action_intent):
            execution_constraints.update(_restricted_custody_transfer_execution_constraints(action_intent))
        token = (
            _mint_execution_token(
                action_intent=action_intent,
                issued_at=now,
                valid_until=token_valid_until,
                extra_constraints=execution_constraints or None,
            )
            if rust_disposition == "allow"
            else None
        )
        explanation = rust_eval.get("explanation") if isinstance(rust_eval.get("explanation"), Mapping) else {}
        explanation_missing = _extract_policy_codes(explanation.get("missing_prerequisites"))
        explanation_gaps = _extract_policy_codes(explanation.get("trust_gaps"))
        authority_graph["mode"] = "rust_policy_core"
        authority_graph["disposition"] = rust_disposition
        authority_graph["missing_prerequisites"] = [
            {"code": code, "outcome": "missing"}
            for code in _merge_policy_code_lists(
                _extract_policy_codes(authority_graph.get("missing_prerequisites")),
                explanation_missing,
            )
        ]
        authority_graph["trust_gaps"] = [
            {"code": code}
            for code in _merge_policy_code_lists(
                _extract_policy_codes(authority_graph.get("trust_gaps")),
                explanation_gaps,
            )
        ]
        authority_graph["matched_policy_refs"] = (
            list(explanation.get("matched_policy_refs"))
            if isinstance(explanation.get("matched_policy_refs"), list)
            else list(authority_graph.get("matched_policy_refs") or [])
        )
        authority_graph["authority_path_summary"] = (
            list(explanation.get("authority_path_summary"))
            if isinstance(explanation.get("authority_path_summary"), list)
            else list(authority_graph.get("authority_path_summary") or [])
        )
        rust_obligations = [
            {"code": str(item.get("obligation_type")).strip()}
            for item in (explanation.get("obligations") if isinstance(explanation.get("obligations"), list) else [])
            if isinstance(item, Mapping) and str(item.get("obligation_type") or "").strip()
        ]
        return _finalize_policy_decision_contract(
            policy_case=policy_case,
            policy_decision=PolicyDecision(
                allowed=rust_disposition == "allow",
                execution_token=token,
                reason=_rust_policy_reason(rust_disposition),
                policy_snapshot=policy_snapshot or action_intent.action.security_contract.version,
                disposition=rust_disposition,  # type: ignore[arg-type]
                risk_score=_policy_case_risk_score(policy_case),
                explanations=_policy_case_explanations(policy_case, _rust_policy_reason(rust_disposition)),
                required_approvals=_transfer_required_approvals(action_intent),
                evidence_gaps=_extract_policy_codes(authority_graph.get("trust_gaps")),
                cognitive_trace_ref=(
                    policy_case.cognitive_assessment.trace_ref
                    if policy_case.cognitive_assessment is not None
                    else None
                ),
                obligations=rust_obligations,
                break_glass=break_glass_context,
                authz_graph=authority_graph,
                governed_receipt=_serialize_governed_receipt(transition_evaluation),
            ),
        )

    token_valid_until = min(
        valid_until,
        now + timedelta(seconds=_execution_token_ttl_seconds()),
    )
    execution_constraints = dict(
        _transition_execution_constraints(transition_evaluation)
        if transition_evaluation is not None
        else {}
    )
    if _is_restricted_custody_transfer(action_intent):
        execution_constraints.update(_restricted_custody_transfer_execution_constraints(action_intent))
    token = _mint_execution_token(
        action_intent=action_intent,
        issued_at=now,
        valid_until=token_valid_until,
        extra_constraints=execution_constraints or None,
    )
    allow_reason = _allow_reason(action_intent)
    disposition = "allow"
    if transition_evaluation is not None and transition_evaluation.disposition == AuthzDecisionDisposition.QUARANTINE:
        allow_reason = "quarantine"
        disposition = "quarantine"
    return _finalize_policy_decision_contract(
        policy_case=policy_case,
        policy_decision=PolicyDecision(
            allowed=True,
            execution_token=token,
            reason=allow_reason,
            policy_snapshot=policy_snapshot or action_intent.action.security_contract.version,
            disposition=disposition,
            risk_score=_policy_case_risk_score(policy_case),
            explanations=_policy_case_explanations(policy_case, allow_reason),
            required_approvals=(
                policy_case.cognitive_assessment.required_approvals
                if policy_case.cognitive_assessment is not None
                else []
            ),
            evidence_gaps=(
                policy_case.cognitive_assessment.missing_evidence
                if policy_case.cognitive_assessment is not None
                else []
            ),
            cognitive_trace_ref=(
                policy_case.cognitive_assessment.trace_ref
                if policy_case.cognitive_assessment is not None
                else None
            ),
            break_glass=break_glass_context,
            authz_graph=_authz_graph_decision_metadata(
                transition_evaluation=transition_evaluation,
                compiled_match=compiled_match,
                evaluator=authz_evaluator,
            ),
            governed_receipt=_serialize_governed_receipt(transition_evaluation),
        ),
    )


def build_governance_context(
    task: TaskPayload | Mapping[str, Any] | Dict[str, Any],
    *,
    compiled_authz_index: CompiledAuthzIndex | None = None,
    approved_source_registrations: Mapping[str, str | None] | None = None,
    relevant_twin_snapshot: Mapping[str, Any] | None = None,
    telemetry_summary: Mapping[str, Any] | None = None,
    cognitive_assessment: Mapping[str, Any] | PolicyCaseAssessment | None = None,
    evidence_summary: Mapping[str, Any] | None = None,
    authoritative_approval_envelope: Mapping[str, Any] | None = None,
    authoritative_approval_transition_history: Sequence[Mapping[str, Any]] | None = None,
    authoritative_approval_transition_head: str | None = None,
) -> Dict[str, Any]:
    policy_case = prepare_policy_case(
        task,
        approved_source_registrations=approved_source_registrations,
        relevant_twin_snapshot=relevant_twin_snapshot,
        telemetry_summary=telemetry_summary,
        cognitive_assessment=cognitive_assessment,
        evidence_summary=evidence_summary,
        authoritative_approval_envelope=authoritative_approval_envelope,
        authoritative_approval_transition_history=authoritative_approval_transition_history,
        authoritative_approval_transition_head=authoritative_approval_transition_head,
    )
    decision = evaluate_intent(policy_case, compiled_authz_index=compiled_authz_index)
    return build_governance_context_from_policy_case(
        policy_case,
        policy_decision=decision,
    )


def build_governance_context_from_policy_case(
    policy_case: PolicyCase,
    *,
    policy_decision: PolicyDecision,
) -> Dict[str, Any]:
    intent = policy_case.action_intent
    policy_receipt = build_policy_receipt(
        policy_case=policy_case,
        policy_decision=policy_decision,
    )
    context = {
        "action_intent": intent.model_dump(mode="json"),
        "policy_case": policy_case.model_dump(mode="json"),
        "policy_decision": policy_decision.model_dump(mode="json"),
        "policy_receipt": policy_receipt,
    }
    if policy_decision.execution_token is not None:
        context["execution_token"] = policy_decision.execution_token.model_dump(mode="json")
    return context


def build_policy_receipt(
    *,
    policy_case: PolicyCase,
    policy_decision: PolicyDecision,
) -> Dict[str, Any]:
    execution_token = (
        policy_decision.execution_token.model_dump(mode="json")
        if policy_decision.execution_token is not None
        else {}
    )
    task_dict = {
        "task_id": policy_case.action_intent.intent_id,
        "params": {
            "governance": {
                "action_intent": policy_case.action_intent.model_dump(mode="json"),
                "policy_case": policy_case.model_dump(mode="json"),
                "policy_decision": policy_decision.model_dump(mode="json"),
                "execution_token": execution_token,
            }
        },
    }
    receipt = build_policy_receipt_artifact(
        task_dict=task_dict,
        timestamp=_isoformat(_utcnow()),
    )
    return receipt.model_dump(mode="json") if receipt is not None else {}


def _task_to_dict(task: TaskPayload | Mapping[str, Any] | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(task, TaskPayload):
        return task.model_dump()
    if hasattr(task, "model_dump"):
        return task.model_dump()
    return dict(task)


def _derive_action_type(payload: Dict[str, Any], params: Dict[str, Any]) -> str:
    action = params.get("action") if isinstance(params.get("action"), dict) else {}
    raw = (
        action.get("type")
        or params.get("action_type")
        or params.get("intent")
        or payload.get("type")
        or "ACTION"
    )
    return str(raw).strip().replace(" ", "_").upper()


def _derive_action_parameters(params: Dict[str, Any]) -> Dict[str, Any]:
    explicit_action = params.get("action")
    if isinstance(explicit_action, dict) and explicit_action:
        action_parameters = {
            k: v
            for k, v in explicit_action.items()
            if k != "type"
        }
        return {
            key: action_parameters[key]
            for key in sorted(action_parameters)
        }
    action_parameters = {
        key: value
        for key, value in params.items()
        if key not in SYSTEM_PARAM_KEYS and not key.startswith("_")
    }
    return {
        key: action_parameters[key]
        for key in sorted(action_parameters)
    }


def _execution_token_ttl_seconds() -> int:
    raw = os.getenv(
        "SEEDCORE_EXECUTION_TOKEN_TTL_SECONDS",
        str(DEFAULT_EXECUTION_TOKEN_TTL_SECONDS),
    )
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_EXECUTION_TOKEN_TTL_SECONDS


def _requires_approved_source_registration(action_intent: ActionIntent) -> bool:
    action_type = str(action_intent.action.type or "").strip().upper()
    if action_type in PACKING_ACTION_TYPES:
        return True
    parameters = (
        action_intent.action.parameters
        if isinstance(action_intent.action.parameters, dict)
        else {}
    )
    return bool(parameters.get("requires_approved_source_registration"))


def _source_registration_deny_code(
    action_intent: ActionIntent,
    approved_source_registrations: Mapping[str, str | None],
) -> str | None:
    if not _requires_approved_source_registration(action_intent):
        return None

    registration_id = (action_intent.resource.source_registration_id or "").strip()
    if not registration_id:
        return SOURCE_REGISTRATION_REQUIRED_DENY_CODE
    if registration_id not in approved_source_registrations:
        return SOURCE_REGISTRATION_UNAPPROVED_DENY_CODE

    required_decision_id = (action_intent.resource.registration_decision_id or "").strip()
    approved_decision_id = approved_source_registrations.get(registration_id)
    if required_decision_id and approved_decision_id != required_decision_id:
        return SOURCE_REGISTRATION_MISMATCH_DENY_CODE
    return None


def _source_registration_deny_reason(deny_code: str) -> str:
    if deny_code == SOURCE_REGISTRATION_REQUIRED_DENY_CODE:
        return (
            f"{EXPLICIT_DENY_RULE}: physical packing actions must reference "
            "an approved SourceRegistration."
        )
    if deny_code == SOURCE_REGISTRATION_MISMATCH_DENY_CODE:
        return (
            f"{EXPLICIT_DENY_RULE}: registration_decision_id must match the "
            "approved SourceRegistration decision."
        )
    return (
        f"{EXPLICIT_DENY_RULE}: physical packing actions require an approved "
        "SourceRegistration decision."
    )


def _evaluate_twin_policy(policy_case: PolicyCase) -> PolicyDecision | None:
    twins = policy_case.relevant_twin_snapshot
    stale_twins = [
        f"{key}:{twin.twin_id}"
        for key, twin in twins.items()
        if twin.freshness.status == "stale"
    ]
    if stale_twins:
        return _deny_decision(
            "Digital twin state is stale for policy evaluation.",
            STALE_TWIN_DENY_CODE,
            policy_case.policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case, floor=0.7),
            cognitive_assessment=policy_case.cognitive_assessment,
            explanations=[f"stale_twins={','.join(stale_twins)}"],
        )

    owner_violation = _evaluate_owner_delegation_policy(policy_case)
    if owner_violation is not None:
        return owner_violation

    for twin in twins.values():
        if bool(twin.delegation.get("revoked")):
            return _deny_decision(
                "Delegation is revoked for this action.",
                REVOKED_DELEGATION_DENY_CODE,
                policy_case.policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case, floor=0.8),
                cognitive_assessment=policy_case.cognitive_assessment,
                explanations=[f"revoked_twin={twin.twin_kind}:{twin.twin_id}"],
            )
        governance_state = twin.governance if isinstance(twin.governance, Mapping) else {}
        lockouts = governance_state.get("lockouts") if isinstance(governance_state.get("lockouts"), list) else []
        pending_exceptions = (
            governance_state.get("pending_exceptions")
            if isinstance(governance_state.get("pending_exceptions"), list)
            else []
        )
        if lockouts or pending_exceptions or bool(twin.custody.get("quarantined")):
            return _deny_decision(
                "Digital twin state blocks execution.",
                FORBIDDEN_TWIN_STATE_DENY_CODE,
                policy_case.policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case, floor=0.75),
                cognitive_assessment=policy_case.cognitive_assessment,
                explanations=[
                    f"blocked_twin={twin.twin_kind}:{twin.twin_id}",
                    *[f"lockout={item}" for item in lockouts],
                    *[f"pending_exception={item}" for item in pending_exceptions],
                ],
            )

    evidence_gaps = _missing_mandatory_evidence(policy_case)
    if evidence_gaps:
        return _deny_decision(
            "Mandatory policy evidence is missing.",
            MISSING_MANDATORY_EVIDENCE_DENY_CODE,
            policy_case.policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case, floor=0.65),
            cognitive_assessment=policy_case.cognitive_assessment,
            evidence_gaps=evidence_gaps,
        )
    return None


def _evaluate_owner_delegation_policy(policy_case: PolicyCase) -> PolicyDecision | None:
    owner_twin = policy_case.relevant_twin_snapshot.get("owner")
    if owner_twin is None:
        return None

    delegation_entries = owner_twin.delegation.get("delegations")
    if not isinstance(delegation_entries, list):
        return None
    if not delegation_entries:
        return None

    assistant_id = policy_case.action_intent.principal.agent_id
    assistant_did = assistant_id if assistant_id.startswith("did:") else f"did:seedcore:assistant:{assistant_id}"

    matched: DelegatedAuthority | None = None
    for raw in delegation_entries:
        if not isinstance(raw, Mapping):
            continue
        try:
            candidate = DelegatedAuthority(**dict(raw))
        except Exception:
            continue
        if candidate.assistant_id in {assistant_id, assistant_did}:
            matched = candidate
            break

    if matched is None:
        return _deny_decision(
            "Assistant is outside owner delegation scope.",
            OWNER_SCOPE_VIOLATION_DENY_CODE,
            policy_case.policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case, floor=0.8),
            cognitive_assessment=policy_case.cognitive_assessment,
            explanations=[f"assistant_id={assistant_id}", "owner_delegation=missing"],
        )

    if not _delegation_scope_allows(matched, policy_case.action_intent.resource.asset_id):
        return _deny_decision(
            "Owner delegation scope does not permit this asset.",
            OWNER_SCOPE_VIOLATION_DENY_CODE,
            policy_case.policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case, floor=0.75),
            cognitive_assessment=policy_case.cognitive_assessment,
            explanations=[f"assistant_id={assistant_id}", "owner_delegation=scope_restricted"],
        )

    if matched.authority_level == AuthorityLevel.OBSERVER:
        return _deny_decision(
            "Owner delegation is observer-only and cannot authorize execution.",
            OWNER_OBSERVER_DENY_CODE,
            policy_case.policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case, floor=0.8),
            cognitive_assessment=policy_case.cognitive_assessment,
            explanations=[f"assistant_id={assistant_id}", "owner_delegation=observer_only"],
        )

    if (
        matched.authority_level == AuthorityLevel.CONTRIBUTOR
        and str(policy_case.action_intent.action.type or "").upper()
        in {"TRANSFER", "MOVE", "RELEASE", "DELIVER", "SHIP"}
    ):
        return _deny_decision(
            "Owner delegation contributor role cannot authorize custody transitions.",
            OWNER_OBSERVER_DENY_CODE,
            policy_case.policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case, floor=0.75),
            cognitive_assessment=policy_case.cognitive_assessment,
            explanations=[f"assistant_id={assistant_id}", "owner_delegation=contributor_transition_block"],
        )

    target_zone = (policy_case.action_intent.resource.target_zone or "").strip()
    allowed_zones = [item.strip() for item in matched.constraints.allowed_zones if str(item).strip()]
    if allowed_zones and target_zone and target_zone not in set(allowed_zones):
        return _deny_decision(
            "Target zone is not permitted by owner delegation.",
            OWNER_ZONE_VIOLATION_DENY_CODE,
            policy_case.policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case, floor=0.78),
            cognitive_assessment=policy_case.cognitive_assessment,
            explanations=[f"target_zone={target_zone}", f"allowed_zones={','.join(allowed_zones)}"],
        )

    required_modality = [item.strip() for item in matched.constraints.required_modality if str(item).strip()]
    available = set(
        str(item).strip()
        for item in (
            policy_case.evidence_summary.get("available")
            if isinstance(policy_case.evidence_summary.get("available"), list)
            else []
        )
        if str(item).strip()
    )
    if required_modality and not set(required_modality).issubset(available):
        return _deny_decision(
            "Owner delegation required modality evidence is missing.",
            OWNER_MODALITY_VIOLATION_DENY_CODE,
            policy_case.policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case, floor=0.72),
            cognitive_assessment=policy_case.cognitive_assessment,
            evidence_gaps=sorted(set(required_modality) - available),
            explanations=[f"required_modality={','.join(required_modality)}"],
        )

    if matched.requires_step_up:
        assessment = policy_case.cognitive_assessment
        if assessment is not None and assessment.recommended_disposition != "allow":
            return _escalate_decision(
                "Owner delegation requires step-up approval.",
                policy_case.policy_snapshot,
                cognitive_assessment=assessment,
                explanations=["owner_step_up=true"],
            )

    return None


def _delegation_scope_allows(delegation: DelegatedAuthority, asset_id: str) -> bool:
    scopes = [str(item).strip() for item in delegation.scope if str(item).strip()]
    if not scopes:
        return False
    if "*" in scopes:
        return True
    asset_urn = f"asset:{asset_id}"
    return asset_id in scopes or asset_urn in scopes


def _evaluate_cognitive_policy(policy_case: PolicyCase) -> PolicyDecision | None:
    assessment = policy_case.cognitive_assessment
    if assessment is None:
        return None
    if assessment.policy_conflicts:
        return _escalate_decision(
            assessment.explanation or "Policy conflicts require escalation.",
            policy_case.policy_snapshot,
            cognitive_assessment=assessment,
            explanations=[f"policy_conflict={item}" for item in assessment.policy_conflicts],
        )
    if assessment.missing_evidence:
        return _escalate_decision(
            assessment.explanation or "Missing evidence requires escalation.",
            policy_case.policy_snapshot,
            cognitive_assessment=assessment,
        )
    if assessment.recommended_disposition == "deny":
        return _deny_decision(
            assessment.explanation or "Cognitive policy assessment denied execution.",
            COGNITIVE_DENY_CODE,
            policy_case.policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case, floor=assessment.risk_score),
            cognitive_assessment=assessment,
        )
    if assessment.recommended_disposition == "escalate":
        return _escalate_decision(
            assessment.explanation or "Cognitive policy assessment requires escalation.",
            policy_case.policy_snapshot,
            cognitive_assessment=assessment,
        )
    return None


def _evaluate_compiled_authz_graph_policy(
    *,
    action_intent: ActionIntent,
    policy_case: PolicyCase,
    compiled_authz_index: CompiledAuthzIndex | None,
) -> tuple[
    PolicyDecision | None,
    BreakGlassDecisionContext,
    CompiledTransitionEvaluation | None,
    CompiledPermissionMatch | None,
    str,
]:
    break_glass_violation, break_glass_context = _evaluate_break_glass_context(
        action_intent=action_intent,
        now=_parse_iso8601(action_intent.timestamp),
        policy_snapshot=policy_case.policy_snapshot,
        policy_case=policy_case,
    )
    if break_glass_violation is not None:
        return break_glass_violation, break_glass_context, None, None, "compiled_index"

    if compiled_authz_index is None:
        return None, break_glass_context, None, None, "disabled"

    expected_snapshot = (policy_case.policy_snapshot or "").strip()
    compiled_snapshot = (compiled_authz_index.snapshot_version or "").strip()
    if expected_snapshot and compiled_snapshot and compiled_snapshot != expected_snapshot:
        return (
            _deny_decision(
                "Compiled authorization graph snapshot does not match the requested policy snapshot.",
                AUTHZ_GRAPH_SNAPSHOT_MISMATCH_DENY_CODE,
                policy_case.policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
                explanations=_policy_case_explanations(
                    policy_case,
                    f"compiled_authz_snapshot_mismatch expected={expected_snapshot} actual={compiled_snapshot}",
                ),
            ),
            BreakGlassDecisionContext(),
            None,
            None,
            "compiled_index",
        )

    transition_evaluation: CompiledTransitionEvaluation | None = None
    authz_evaluator = "compiled_index"
    if _pdp_use_ray_authz_cache():
        ray_result = _evaluate_compiled_authz_graph_with_ray(
            action_intent=action_intent,
            policy_case=policy_case,
            break_glass=break_glass_context.validated,
            compiled_authz_index=compiled_authz_index,
        )
        if ray_result is not None:
            transition_evaluation = ray_result.get("transition_evaluation")
            match = ray_result["match"]
            authz_evaluator = str(ray_result.get("source") or "ray_actor")
        elif _pdp_use_authz_graph_transitions():
            transition_evaluation = compiled_authz_index.evaluate_transition(
                _compiled_authz_transition_request(
                    action_intent=action_intent,
                    break_glass=break_glass_context.validated,
                )
            )
            match = transition_evaluation.permission_match
        else:
            match = compiled_authz_index.can_access(
                principal_ref=_compiled_authz_principal_ref(action_intent),
                operation=_compiled_authz_operation(action_intent),
                resource_ref=_compiled_authz_resource_ref(action_intent),
                zone_ref=_compiled_authz_zone_ref(action_intent),
                network_ref=_compiled_authz_network_ref(action_intent),
                workflow_stage_ref=_compiled_authz_workflow_stage_ref(action_intent),
                resource_state_hash=_compiled_authz_resource_state_hash(action_intent),
                at=_parse_iso8601(action_intent.timestamp),
                break_glass=break_glass_context.validated,
            )
    elif _pdp_use_authz_graph_transitions():
        transition_evaluation = compiled_authz_index.evaluate_transition(
            _compiled_authz_transition_request(
                action_intent=action_intent,
                break_glass=break_glass_context.validated,
            )
        )
        match = transition_evaluation.permission_match
    else:
        match = compiled_authz_index.can_access(
            principal_ref=_compiled_authz_principal_ref(action_intent),
            operation=_compiled_authz_operation(action_intent),
            resource_ref=_compiled_authz_resource_ref(action_intent),
            zone_ref=_compiled_authz_zone_ref(action_intent),
            network_ref=_compiled_authz_network_ref(action_intent),
            workflow_stage_ref=_compiled_authz_workflow_stage_ref(action_intent),
            resource_state_hash=_compiled_authz_resource_state_hash(action_intent),
            at=_parse_iso8601(action_intent.timestamp),
            break_glass=break_glass_context.validated,
        )
    break_glass_context = break_glass_context.model_copy(
        update={
            "used": bool(match.break_glass_used),
            "override_applied": match.reason == "break_glass_override",
            "required": bool(match.break_glass_required),
            "outcome": match.reason,
        }
    )
    if transition_evaluation is not None:
        if transition_evaluation.disposition == AuthzDecisionDisposition.ALLOW:
            return None, break_glass_context, transition_evaluation, transition_evaluation.permission_match, authz_evaluator
        if transition_evaluation.disposition == AuthzDecisionDisposition.QUARANTINE:
            return None, break_glass_context, transition_evaluation, transition_evaluation.permission_match, authz_evaluator
        return (
            _compiled_authz_transition_deny_decision(
                policy_case=policy_case,
                evaluation=transition_evaluation,
                break_glass=break_glass_context,
                authz_evaluator=authz_evaluator,
            ),
            break_glass_context,
            transition_evaluation,
            transition_evaluation.permission_match,
            authz_evaluator,
        )
    if match.allowed:
        return None, break_glass_context, None, match, authz_evaluator
    return (
        _compiled_authz_deny_decision(
            policy_case=policy_case,
            match=match,
            break_glass=break_glass_context,
            authz_evaluator=authz_evaluator,
        ),
        break_glass_context,
        None,
        match,
        authz_evaluator,
    )


def _resolve_compiled_authz_index(
    explicit_index: CompiledAuthzIndex | None,
) -> CompiledAuthzIndex | None:
    if explicit_index is not None:
        return explicit_index
    if not _pdp_use_active_authz_graph():
        return None
    try:
        from seedcore.ops.pkg.manager import get_global_pkg_manager
    except Exception:
        return None
    manager = get_global_pkg_manager()
    if manager is None:
        return None
    getter = getattr(manager, "get_active_compiled_authz_index", None)
    if getter is None:
        return None
    return getter()


def _evaluate_compiled_authz_graph_with_ray(
    *,
    action_intent: ActionIntent,
    policy_case: PolicyCase,
    break_glass: bool,
    compiled_authz_index: CompiledAuthzIndex | None = None,
) -> Dict[str, Any] | None:
    try:
        from seedcore.ops.pkg.authz_graph.ray_cache import evaluate_authz_with_ray_cache
    except Exception:
        return None

    payload: Dict[str, Any]
    if _pdp_use_authz_graph_transitions():
        payload = {
            "principal_ref": _compiled_authz_principal_ref(action_intent),
            "operation": _compiled_authz_operation(action_intent),
            "resource_ref": _compiled_authz_resource_ref(action_intent),
            "asset_ref": _compiled_authz_asset_ref(action_intent),
            "product_ref": _compiled_authz_product_ref(action_intent),
            "lot_ref": _compiled_authz_lot_ref(action_intent),
            "facility_ref": _compiled_authz_facility_ref(action_intent),
            "source_registration_ref": _compiled_authz_source_registration_ref(action_intent),
            "registration_decision_ref": _compiled_authz_registration_decision_ref(action_intent),
            "workflow_stage_ref": _compiled_authz_workflow_stage_ref(action_intent),
            "zone_ref": _compiled_authz_zone_ref(action_intent),
            "network_ref": _compiled_authz_network_ref(action_intent),
            "custody_point_ref": _compiled_authz_custody_point_ref(action_intent),
            "resource_state_hash": _compiled_authz_resource_state_hash(action_intent),
            "require_approved_source_registration": _requires_approved_source_registration(action_intent),
            "shard_key": _compiled_authz_shard_key(action_intent),
            "at": action_intent.timestamp,
            "break_glass": break_glass,
        }
    else:
        payload = {
            "principal_ref": _compiled_authz_principal_ref(action_intent),
            "operation": _compiled_authz_operation(action_intent),
            "resource_ref": _compiled_authz_resource_ref(action_intent),
            "product_ref": _compiled_authz_product_ref(action_intent),
            "lot_ref": _compiled_authz_lot_ref(action_intent),
            "facility_ref": _compiled_authz_facility_ref(action_intent),
            "zone_ref": _compiled_authz_zone_ref(action_intent),
            "network_ref": _compiled_authz_network_ref(action_intent),
            "workflow_stage_ref": _compiled_authz_workflow_stage_ref(action_intent),
            "resource_state_hash": _compiled_authz_resource_state_hash(action_intent),
            "shard_key": _compiled_authz_shard_key(action_intent),
            "at": action_intent.timestamp,
            "break_glass": break_glass,
        }
    return evaluate_authz_with_ray_cache(
        snapshot_id=getattr(compiled_authz_index, "snapshot_id", None),
        snapshot_version=(
            getattr(compiled_authz_index, "snapshot_version", None)
            or (policy_case.policy_snapshot or "").strip()
            or None
        ),
        snapshot_ref=(
            getattr(compiled_authz_index, "snapshot_ref", None)
            or (f"authz_graph@{policy_case.policy_snapshot}" if policy_case.policy_snapshot else None)
        ),
        payload=payload,
        transitions=_pdp_use_authz_graph_transitions(),
        timeout_seconds=_pdp_ray_authz_cache_timeout_seconds(),
    )


def _missing_mandatory_evidence(policy_case: PolicyCase) -> list[str]:
    evidence = policy_case.evidence_summary
    required = evidence.get("required") if isinstance(evidence.get("required"), list) else []
    available = evidence.get("available") if isinstance(evidence.get("available"), list) else []
    missing = [str(item) for item in required if item not in available]
    telemetry_required = evidence.get("telemetry_required") if isinstance(evidence.get("telemetry_required"), list) else []
    for item in telemetry_required:
        if item not in policy_case.telemetry_summary:
            missing.append(str(item))
    return sorted(set(missing))


def _policy_case_risk_score(
    policy_case: PolicyCase,
    *,
    floor: float | None = None,
) -> float | None:
    risk_score = None
    if policy_case.cognitive_assessment is not None:
        risk_score = policy_case.cognitive_assessment.risk_score
    for twin in policy_case.relevant_twin_snapshot.values():
        twin_score = twin.risk.get("score")
        if isinstance(twin_score, (int, float)):
            risk_score = max(float(risk_score or 0.0), float(twin_score))
    if floor is not None:
        risk_score = max(float(risk_score or 0.0), floor)
    return round(max(0.0, min(1.0, float(risk_score))), 3) if risk_score is not None else None


def _policy_case_explanations(policy_case: PolicyCase, base_reason: str) -> list[str]:
    explanations = [base_reason]
    assessment = policy_case.cognitive_assessment
    if assessment is not None:
        if assessment.explanation:
            explanations.append(assessment.explanation)
        explanations.extend([f"risk_factor={item}" for item in assessment.risk_factors])
    return explanations


def _deny_decision(
    reason: str,
    deny_code: str,
    policy_snapshot: str | None,
    *,
    risk_score: float | None = None,
    cognitive_assessment: PolicyCaseAssessment | None = None,
    explanations: list[str] | None = None,
    evidence_gaps: list[str] | None = None,
    break_glass: BreakGlassDecisionContext | None = None,
    authz_graph: Mapping[str, Any] | None = None,
    governed_receipt: Mapping[str, Any] | None = None,
) -> PolicyDecision:
    return PolicyDecision(
        allowed=False,
        reason=reason,
        policy_snapshot=policy_snapshot,
        deny_code=deny_code,
        disposition="deny",
        risk_score=risk_score,
        explanations=(explanations or _decision_explanations(reason, cognitive_assessment)),
        required_approvals=(
            cognitive_assessment.required_approvals if cognitive_assessment is not None else []
        ),
        evidence_gaps=(
            evidence_gaps
            if evidence_gaps is not None
            else (cognitive_assessment.missing_evidence if cognitive_assessment is not None else [])
        ),
        cognitive_trace_ref=(
            cognitive_assessment.trace_ref if cognitive_assessment is not None else None
        ),
        break_glass=(break_glass or BreakGlassDecisionContext()),
        authz_graph=dict(authz_graph or {}),
        governed_receipt=dict(governed_receipt or {}),
    )


def _escalate_decision(
    reason: str,
    policy_snapshot: str | None,
    *,
    cognitive_assessment: PolicyCaseAssessment | None = None,
    explanations: list[str] | None = None,
    break_glass: BreakGlassDecisionContext | None = None,
    authz_graph: Mapping[str, Any] | None = None,
    governed_receipt: Mapping[str, Any] | None = None,
) -> PolicyDecision:
    return PolicyDecision(
        allowed=False,
        reason=reason,
        policy_snapshot=policy_snapshot,
        deny_code=POLICY_ESCALATION_CODE,
        disposition="escalate",
        risk_score=_coerce_risk_score(cognitive_assessment.risk_score if cognitive_assessment is not None else None),
        explanations=(explanations or _decision_explanations(reason, cognitive_assessment)),
        required_approvals=(
            cognitive_assessment.required_approvals if cognitive_assessment is not None else []
        ),
        evidence_gaps=(
            cognitive_assessment.missing_evidence if cognitive_assessment is not None else []
        ),
        cognitive_trace_ref=(
            cognitive_assessment.trace_ref if cognitive_assessment is not None else None
        ),
        break_glass=(break_glass or BreakGlassDecisionContext()),
        authz_graph=dict(authz_graph or {}),
        governed_receipt=dict(governed_receipt or {}),
    )


def _decision_explanations(
    reason: str,
    cognitive_assessment: PolicyCaseAssessment | None,
) -> list[str]:
    explanations = [reason]
    if cognitive_assessment is not None:
        if cognitive_assessment.explanation:
            explanations.append(cognitive_assessment.explanation)
        explanations.extend([f"risk_factor={item}" for item in cognitive_assessment.risk_factors])
    return explanations


def _transfer_context(action_intent: ActionIntent) -> Dict[str, Any]:
    category_envelope = (
        action_intent.resource.category_envelope
        if isinstance(action_intent.resource.category_envelope, dict)
        else {}
    )
    transfer_context = category_envelope.get("transfer_context")
    return dict(transfer_context) if isinstance(transfer_context, Mapping) else {}


def _approval_context(action_intent: ActionIntent) -> Dict[str, Any]:
    parameters = action_intent.action.parameters if isinstance(action_intent.action.parameters, dict) else {}
    approval_context = parameters.get("approval_context")
    return dict(approval_context) if isinstance(approval_context, Mapping) else {}


def _set_approval_context(action_intent: ActionIntent, approval_context: Mapping[str, Any]) -> None:
    parameters = (
        dict(action_intent.action.parameters)
        if isinstance(action_intent.action.parameters, Mapping)
        else {}
    )
    parameters["approval_context"] = dict(approval_context)
    action_intent.action.parameters = parameters


def _sanitize_transfer_approval_context(action_intent: ActionIntent) -> None:
    if not _is_restricted_custody_transfer(action_intent):
        return
    approval_context = _approval_context(action_intent)
    if not approval_context:
        return
    for key in (
        "approval_envelope",
        "approval_transition",
        "approval_transition_history",
        "approval_transition_count",
        "approval_transition_head",
        "last_approval_transition_event",
        "expected_co_signers",
        "co_sign_binding_hash",
        "co_sign_status",
        "co_signatures",
    ):
        approval_context.pop(key, None)
    _set_approval_context(action_intent, approval_context)


def _approval_roles_from_envelope(approval_envelope: Mapping[str, Any]) -> list[str]:
    roles: list[str] = []
    raw = approval_envelope.get("required_approvals")
    if not isinstance(raw, list):
        return roles
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "").strip()
        if role and role not in roles:
            roles.append(role)
    return roles


def _approved_principals_from_envelope(approval_envelope: Mapping[str, Any]) -> list[str]:
    principals: list[str] = []
    raw = approval_envelope.get("required_approvals")
    if not isinstance(raw, list):
        return principals
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        status = str(item.get("status") or "").strip().upper()
        principal_ref = str(item.get("principal_ref") or "").strip()
        if status == "APPROVED" and principal_ref and principal_ref not in principals:
            principals.append(principal_ref)
    return principals


def _apply_authoritative_transfer_approval(
    action_intent: ActionIntent,
    *,
    approval_envelope: Mapping[str, Any] | None = None,
    transition_history: Sequence[Mapping[str, Any]] | None = None,
    transition_head: str | None = None,
) -> None:
    approval_context = _approval_context(action_intent)
    if not isinstance(approval_envelope, Mapping) and not transition_history and transition_head is None:
        if approval_context:
            _set_approval_context(action_intent, approval_context)
        return
    if isinstance(approval_envelope, Mapping):
        envelope_payload = dict(approval_envelope)
        envelope_id = str(envelope_payload.get("approval_envelope_id") or "").strip()
        if envelope_id:
            approval_context["approval_envelope_id"] = envelope_id
        binding_hash = _approval_binding_hash_string(envelope_payload.get("approval_binding_hash"))
        if binding_hash:
            approval_context["approval_binding_hash"] = binding_hash
        version = envelope_payload.get("version")
        if version is not None:
            approval_context["approval_envelope_version"] = int(version)
            approval_context["observed_version"] = int(version)
        derived_roles = _approval_roles_from_envelope(envelope_payload)
        if derived_roles:
            approval_context["required_roles"] = derived_roles
        derived_approved_by = _approved_principals_from_envelope(envelope_payload)
        if derived_approved_by:
            approval_context["approved_by"] = derived_approved_by
        else:
            approval_context.pop("approved_by", None)
    if transition_history:
        normalized_history: list[dict[str, Any]] = []
        derived_head: str | None = None
        for item in transition_history:
            if not isinstance(item, Mapping):
                continue
            transition_event = (
                dict(item.get("transition_event"))
                if isinstance(item.get("transition_event"), Mapping)
                else dict(item)
            )
            if transition_event:
                normalized_history.append(transition_event)
            event_hash = item.get("event_hash")
            if event_hash is not None and str(event_hash).strip():
                derived_head = str(event_hash).strip()
        if normalized_history:
            approval_context["approval_transition_count"] = len(normalized_history)
        if normalized_history:
            approval_context["last_approval_transition_event"] = dict(normalized_history[-1])
        else:
            approval_context.pop("last_approval_transition_event", None)
        if derived_head and transition_head is None:
            transition_head = derived_head
    normalized_head = (
        str(transition_head).strip()
        if transition_head is not None and str(transition_head).strip()
        else None
    )
    if normalized_head is not None:
        approval_context["approval_transition_head"] = normalized_head
    else:
        approval_context.pop("approval_transition_head", None)
    _set_approval_context(action_intent, approval_context)


def _is_restricted_custody_transfer(action_intent: ActionIntent) -> bool:
    action_type = str(action_intent.action.type or "").strip().upper()
    return (
        action_type in RESTRICTED_CUSTODY_TRANSFER_ACTION_TYPES
        or bool(_transfer_context(action_intent))
        or bool(_approval_context(action_intent))
    )


def _workflow_type_for_intent(action_intent: ActionIntent) -> str | None:
    if _is_restricted_custody_transfer(action_intent):
        return RESTRICTED_CUSTODY_TRANSFER_WORKFLOW_TYPE
    return None


def _transfer_context_value(action_intent: ActionIntent, *keys: str) -> str | None:
    context = _transfer_context(action_intent)
    for key in keys:
        value = context.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _transfer_required_approvals(action_intent: ActionIntent) -> list[str]:
    approval_context = _approval_context(action_intent)
    required_roles = approval_context.get("required_roles")
    if not isinstance(required_roles, list):
        return []
    values: list[str] = []
    for item in required_roles:
        if item is None:
            continue
        value = str(item).strip()
        if value and value not in values:
            values.append(value)
    return values


def _is_zone_administrator(action_intent: ActionIntent) -> bool:
    role = str(action_intent.principal.role_profile or "").strip().upper()
    return role in {"ZONE_ADMIN", "ZONE_ADMINISTRATOR"}


def _transfer_expected_co_signers(
    action_intent: ActionIntent,
    *,
    approval_context: Mapping[str, Any] | None = None,
    approval_envelope: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    approval_context = approval_context if isinstance(approval_context, Mapping) else {}
    approval_envelope = approval_envelope if isinstance(approval_envelope, Mapping) else {}
    expected: list[dict[str, str]] = []

    sender_ref = (
        _transfer_context_value(action_intent, "expected_current_custodian", "from_custodian_ref")
        or (
            str(approval_envelope.get("from_custodian_ref")).strip()
            if approval_envelope.get("from_custodian_ref") is not None
            else None
        )
    )
    receiver_ref = (
        _transfer_context_value(action_intent, "next_custodian", "to_custodian_ref")
        or (
            str(approval_envelope.get("to_custodian_ref")).strip()
            if approval_envelope.get("to_custodian_ref") is not None
            else None
        )
    )

    for principal_ref, signer_role, signer_party in (
        (sender_ref, "SENDER", "initiator"),
        (receiver_ref, "RECEIVER", "receiver"),
    ):
        if principal_ref is None or not str(principal_ref).strip():
            continue
        normalized = str(principal_ref).strip()
        if any(item["principal_ref"] == normalized for item in expected):
            continue
        expected.append(
            {
                "principal_ref": normalized,
                "signer_role": signer_role,
                "signer_party": signer_party,
            }
        )

    override_principal = approval_context.get("emergency_override_principal_ref")
    if override_principal is not None and str(override_principal).strip():
        expected.append(
            {
                "principal_ref": str(override_principal).strip(),
                "signer_role": "ZONE_ADMINISTRATOR",
                "signer_party": "override",
            }
        )
    return expected


def _transfer_co_sign_status(
    *,
    action_intent: ActionIntent,
    required_approvals: list[str],
    approved_by: list[str],
    break_glass: BreakGlassDecisionContext | None = None,
) -> str | None:
    if break_glass is not None and bool(break_glass.validated) and _is_zone_administrator(action_intent):
        return "emergency_override"
    if not required_approvals:
        return None
    if len(set(approved_by)) >= len(required_approvals):
        return "co_signed"
    if approved_by:
        return "pending_co_sign"
    return "awaiting_primary_signature"


def _transfer_outcome_label(
    *,
    action_intent: ActionIntent,
    break_glass: BreakGlassDecisionContext | None = None,
    allowed: bool = False,
) -> str | None:
    if break_glass is not None and bool(break_glass.validated) and _is_zone_administrator(action_intent):
        return "EMERGENCY_OVERRIDE"
    if allowed and _is_restricted_custody_transfer(action_intent):
        return "STANDARD_TRANSFER"
    return None


def _transfer_co_sign_binding_hash(
    *,
    action_intent: ActionIntent,
    approval_context: Mapping[str, Any],
    approval_envelope: Mapping[str, Any] | None = None,
    snapshot_hash: str | None = None,
    transfer_outcome: str | None = None,
) -> str | None:
    expected = _transfer_expected_co_signers(
        action_intent,
        approval_context=approval_context,
        approval_envelope=approval_envelope,
    )
    if not expected:
        return None
    material = {
        "intent_id": action_intent.intent_id,
        "asset_id": action_intent.resource.asset_id,
        "approval_envelope_id": approval_context.get("approval_envelope_id"),
        "approval_binding_hash": _approval_binding_hash_string(approval_context.get("approval_binding_hash")),
        "snapshot_hash": snapshot_hash,
        "expected_co_signers": expected,
        "transfer_outcome": transfer_outcome,
    }
    return f"sha256:{hashlib.sha256(json.dumps(material, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()}"


def _approval_binding_hash_string(value: Any) -> str | None:
    if isinstance(value, Mapping):
        algorithm = str(value.get("algorithm") or "").strip()
        digest = str(value.get("value") or "").strip()
        if algorithm and digest:
            return f"{algorithm}:{digest}"
        return None
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _evaluate_restricted_custody_transfer_prerequisites(
    *,
    policy_case: PolicyCase,
) -> PolicyDecision | None:
    action_intent = policy_case.action_intent
    if not _is_restricted_custody_transfer(action_intent):
        return None

    approval_context = _approval_context(action_intent)
    required_approvals = _transfer_required_approvals(action_intent)
    approved_by_raw = approval_context.get("approved_by")
    approved_by: list[str] = []
    if isinstance(approved_by_raw, list):
        for item in approved_by_raw:
            if item is None:
                continue
            value = str(item).strip()
            if value and value not in approved_by:
                approved_by.append(value)

    approval_envelope_payload = _authoritative_approval_envelope(policy_case)

    if not isinstance(approval_envelope_payload, Mapping):
        return _deny_decision(
            "Restricted custody transfer requires an authoritative approval envelope snapshot.",
            "approval_envelope",
            policy_case.policy_snapshot,
            cognitive_assessment=policy_case.cognitive_assessment,
            explanations=_policy_case_explanations(
                policy_case,
                "restricted_custody_transfer_approval_missing",
            ),
            authz_graph={
                "mode": "transfer_prerequisite_check",
                "disposition": "deny",
                "reason": "approval_envelope_missing",
                "matched_policy_refs": [],
                "authority_paths": [],
                "authority_path_summary": [],
                "missing_prerequisites": [
                    {
                        "code": "approval_envelope",
                        "outcome": "missing",
                        "message": "Restricted custody transfer requires a persisted approval envelope snapshot.",
                        "details": {"authoritative_runtime_required": True},
                    }
                ],
                "trust_gaps": [],
            },
        ).model_copy(update={"required_approvals": required_approvals})

    if isinstance(approval_envelope_payload, Mapping):
        rust_summary = summarize_transfer_approval_with_rust(dict(approval_envelope_payload))
        if not bool(rust_summary.get("valid")):
            rust_validation = validate_transfer_approval_with_rust(dict(approval_envelope_payload))
            rust_error_code = (
                rust_summary.get("error_code")
                or rust_validation.get("error_code")
                or "approval_invalid"
            )
            rust_details = list(rust_summary.get("details") or rust_validation.get("details") or [])
            missing_prerequisites = [
                {
                    "code": "approval_envelope",
                    "outcome": "invalid",
                    "message": "Restricted custody transfer approval envelope failed Rust validation.",
                    "details": {
                        "rust_error_code": rust_error_code,
                        "rust_details": rust_details,
                    },
                }
            ]
            return _escalate_decision(
                "Restricted custody transfer requires a valid approval envelope.",
                policy_case.policy_snapshot,
                cognitive_assessment=policy_case.cognitive_assessment,
                explanations=_policy_case_explanations(
                    policy_case,
                    "restricted_custody_transfer_approval_envelope_invalid",
                ),
                authz_graph={
                    "mode": "transfer_prerequisite_check",
                    "disposition": "escalate",
                    "reason": "approval_envelope_invalid",
                    "matched_policy_refs": [],
                    "authority_paths": [],
                    "authority_path_summary": [],
                    "missing_prerequisites": missing_prerequisites,
                    "trust_gaps": [],
                },
            ).model_copy(update={"required_approvals": required_approvals})

        computed_binding_hash = _approval_binding_hash_string(rust_summary.get("binding_hash"))
        if computed_binding_hash is None:
            rust_binding = approval_binding_hash_with_rust(dict(approval_envelope_payload))
            missing_prerequisites = [
                {
                    "code": "approval_binding",
                    "outcome": "invalid",
                    "message": "Restricted custody transfer approval binding hash could not be computed by Rust.",
                    "details": {
                        "rust_error_code": rust_binding.get("error_code") or rust_summary.get("error_code"),
                        "rust_details": list(
                            rust_binding.get("details") or rust_summary.get("details") or []
                        ),
                    },
                }
            ]
            return _escalate_decision(
                "Restricted custody transfer requires a valid approval binding hash.",
                policy_case.policy_snapshot,
                cognitive_assessment=policy_case.cognitive_assessment,
                explanations=_policy_case_explanations(
                    policy_case,
                    "restricted_custody_transfer_binding_hash_invalid",
                ),
                authz_graph={
                    "mode": "transfer_prerequisite_check",
                    "disposition": "escalate",
                    "reason": "approval_binding_invalid",
                    "matched_policy_refs": [],
                    "authority_paths": [],
                    "authority_path_summary": [],
                    "missing_prerequisites": missing_prerequisites,
                    "trust_gaps": [],
                },
            ).model_copy(update={"required_approvals": required_approvals})

        provided_binding_hash = (
            _approval_binding_hash_string(approval_context.get("approval_binding_hash"))
            or _approval_binding_hash_string(approval_envelope_payload.get("approval_binding_hash"))
        )
        if provided_binding_hash is not None and provided_binding_hash != computed_binding_hash:
            missing_prerequisites = [
                {
                    "code": "approval_binding",
                    "outcome": "mismatch",
                    "message": "Restricted custody transfer approval binding hash does not match Rust canonical hash.",
                    "details": {
                        "provided": provided_binding_hash,
                        "computed": computed_binding_hash,
                    },
                }
            ]
            return _escalate_decision(
                "Restricted custody transfer requires a matching approval binding hash.",
                policy_case.policy_snapshot,
                cognitive_assessment=policy_case.cognitive_assessment,
                explanations=_policy_case_explanations(
                    policy_case,
                    "restricted_custody_transfer_binding_hash_mismatch",
                ),
                authz_graph={
                    "mode": "transfer_prerequisite_check",
                    "disposition": "escalate",
                    "reason": "approval_binding_mismatch",
                    "matched_policy_refs": [],
                    "authority_paths": [],
                    "authority_path_summary": [],
                    "missing_prerequisites": missing_prerequisites,
                    "trust_gaps": [],
                },
            ).model_copy(update={"required_approvals": required_approvals})

        approval_context["approval_binding_hash"] = computed_binding_hash
        envelope_id = str(approval_envelope_payload.get("approval_envelope_id") or "").strip()
        if envelope_id and not str(approval_context.get("approval_envelope_id") or "").strip():
            approval_context["approval_envelope_id"] = envelope_id
        envelope_version = approval_envelope_payload.get("version")
        if envelope_version is not None:
            approval_context["approval_envelope_version"] = int(envelope_version)
            approval_context["observed_version"] = int(envelope_version)
        authoritative_required_approvals: list[str] = []
        required_roles_raw = rust_summary.get("required_roles")
        if isinstance(required_roles_raw, list):
            for item in required_roles_raw:
                value = str(item).strip()
                if value and value not in authoritative_required_approvals:
                    authoritative_required_approvals.append(value)
        if authoritative_required_approvals:
            required_approvals = authoritative_required_approvals
        authoritative_approved_by: list[str] = []
        approved_by_raw = rust_summary.get("approved_by")
        if isinstance(approved_by_raw, list):
            for item in approved_by_raw:
                value = str(item).strip()
                if value and value not in authoritative_approved_by:
                    authoritative_approved_by.append(value)
        approved_by = authoritative_approved_by

    expected_co_signers = _transfer_expected_co_signers(
        action_intent,
        approval_context=approval_context,
        approval_envelope=approval_envelope_payload if isinstance(approval_envelope_payload, Mapping) else None,
    )
    if expected_co_signers:
        approval_context["expected_co_signers"] = [dict(item) for item in expected_co_signers]
    co_sign_status = _transfer_co_sign_status(
        action_intent=action_intent,
        required_approvals=required_approvals,
        approved_by=approved_by,
    )
    if co_sign_status is not None:
        approval_context["co_sign_status"] = co_sign_status
    transfer_outcome = _transfer_outcome_label(action_intent=action_intent, allowed=False)
    co_sign_binding_hash = _transfer_co_sign_binding_hash(
        action_intent=action_intent,
        approval_context=approval_context,
        approval_envelope=approval_envelope_payload if isinstance(approval_envelope_payload, Mapping) else None,
        transfer_outcome=transfer_outcome,
    )
    if co_sign_binding_hash is not None:
        approval_context["co_sign_binding_hash"] = co_sign_binding_hash

    missing_prerequisites: list[dict[str, Any]] = []
    approval_envelope_id = approval_context.get("approval_envelope_id")
    if approval_envelope_id is None or not str(approval_envelope_id).strip():
        missing_prerequisites.append(
            {
                "code": "approval_envelope",
                "outcome": "missing",
                "message": "Restricted custody transfer requires an approval envelope reference.",
                "details": {},
            }
        )

    approval_binding_hash = _approval_binding_hash_string(approval_context.get("approval_binding_hash"))
    if approval_binding_hash is None:
        missing_prerequisites.append(
            {
                "code": "approval_binding",
                "outcome": "missing",
                "message": "Restricted custody transfer requires an approval binding hash.",
                "details": {},
            }
        )
    else:
        approval_context["approval_binding_hash"] = approval_binding_hash

    if required_approvals:
        approval_context["required_roles"] = list(required_approvals)
    if approved_by:
        approval_context["approved_by"] = list(approved_by)
    _set_approval_context(action_intent, approval_context)

    if not required_approvals:
        missing_prerequisites.append(
            {
                "code": "required_approvals",
                "outcome": "missing",
                "message": "Restricted custody transfer requires explicit approval roles.",
                "details": {},
            }
        )

    if required_approvals and len(approved_by) < len(required_approvals):
        missing_prerequisites.append(
            {
                "code": "co_signatures",
                "outcome": "missing",
                "message": "Restricted custody transfer is waiting for the distinct counterparty co-signature set.",
                "details": {
                    "required_approvals": required_approvals,
                    "approved_by": approved_by,
                    "expected_co_signers": expected_co_signers,
                    "co_sign_status": co_sign_status,
                },
            }
        )
        missing_prerequisites.append(
            {
                "code": "approved_by",
                "outcome": "missing",
                "message": "Restricted custody transfer is still waiting for the full approval set.",
                "details": {
                    "required_approvals": required_approvals,
                    "approved_by": approved_by,
                },
            }
        )

    if missing_prerequisites:
        return _deny_decision(
            "Restricted custody transfer requires completed dual approval.",
            "approval_incomplete",
            policy_case.policy_snapshot,
            cognitive_assessment=policy_case.cognitive_assessment,
            explanations=_policy_case_explanations(
                policy_case,
                "restricted_custody_transfer_approval_incomplete",
            ),
            authz_graph={
                "mode": "transfer_prerequisite_check",
                "disposition": "deny",
                "reason": "pending_co_sign" if co_sign_status == "pending_co_sign" else "approval_incomplete",
                "matched_policy_refs": [],
                "authority_paths": [],
                "authority_path_summary": [],
                "missing_prerequisites": missing_prerequisites,
                "trust_gaps": [],
                "co_sign_required": bool(expected_co_signers),
                "co_sign_status": co_sign_status,
                "transfer_outcome": transfer_outcome,
                "expected_co_signers": expected_co_signers,
                "co_sign_binding_hash": co_sign_binding_hash,
            },
        ).model_copy(update={"required_approvals": required_approvals})
    return None


def _authority_path_summary(authority_paths: Any) -> list[str]:
    if not isinstance(authority_paths, list):
        return []
    summaries: list[str] = []
    for raw_path in authority_paths:
        if not isinstance(raw_path, list):
            continue
        path = [str(item).strip() for item in raw_path if str(item).strip()]
        if path:
            summaries.append(" -> ".join(path))
    return summaries


def _decision_minted_artifacts(policy_decision: PolicyDecision) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    if policy_decision.execution_token is not None:
        artifacts.append(
            {
                "kind": "execution_token",
                "ref": policy_decision.execution_token.token_id,
            }
        )
    governed_receipt = policy_decision.governed_receipt if isinstance(policy_decision.governed_receipt, dict) else {}
    decision_hash = governed_receipt.get("decision_hash")
    if decision_hash is not None and str(decision_hash).strip():
        artifacts.append(
            {
                "kind": "governed_receipt",
                "ref": str(decision_hash).strip(),
            }
        )
    return artifacts


def _transfer_has_telemetry_requirement(authz_graph: Mapping[str, Any]) -> bool:
    checked_constraints = authz_graph.get("checked_constraints")
    if isinstance(checked_constraints, list):
        for item in checked_constraints:
            if isinstance(item, Mapping) and str(item.get("code") or "").strip() == "telemetry_freshness":
                return True
    trust_gaps = authz_graph.get("trust_gaps")
    if isinstance(trust_gaps, list):
        for item in trust_gaps:
            if not isinstance(item, Mapping):
                continue
            if str(item.get("code") or "").strip() in {"stale_telemetry", "missing_telemetry"}:
                return True
    return False


def _workflow_obligations(
    *,
    action_intent: ActionIntent,
    policy_decision: PolicyDecision,
    authz_graph: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not _is_restricted_custody_transfer(action_intent):
        return []

    obligation_codes: list[str]
    if policy_decision.disposition == "allow":
        obligation_codes = [
            "generate_transition_receipt",
            "publish_replay_artifact",
            "close_prior_custodian_state",
            "update_verification_surface",
        ]
    elif policy_decision.disposition == "quarantine":
        obligation_codes = [
            "preserve_restricted_state",
            "manual_review",
            "update_verification_surface",
        ]
    else:
        obligation_codes = ["update_verification_surface"]

    if (
        policy_decision.disposition in {"allow", "quarantine"}
        and _transfer_has_telemetry_requirement(authz_graph)
        and "attach_telemetry_proof" not in obligation_codes
    ):
        obligation_codes.append("attach_telemetry_proof")

    return [{"code": code} for code in obligation_codes]


def _restricted_custody_transfer_execution_constraints(
    action_intent: ActionIntent,
) -> Dict[str, Any]:
    approval_context = _approval_context(action_intent)
    approved_by = approval_context.get("approved_by") if isinstance(approval_context.get("approved_by"), list) else []
    required_approvals = _transfer_required_approvals(action_intent)
    co_sign_status = _transfer_co_sign_status(
        action_intent=action_intent,
        required_approvals=required_approvals,
        approved_by=[str(item).strip() for item in approved_by if str(item).strip()],
    )
    constraints = {
        "from_zone": _transfer_context_value(action_intent, "from_zone"),
        "target_zone": _transfer_context_value(action_intent, "to_zone") or action_intent.resource.target_zone,
        "expected_current_custodian": _transfer_context_value(action_intent, "expected_current_custodian", "from_custodian_ref"),
        "next_custodian": _transfer_context_value(action_intent, "next_custodian", "to_custodian_ref"),
        "approval_envelope_id": approval_context.get("approval_envelope_id"),
        "approval_envelope_version": approval_context.get("approval_envelope_version") or approval_context.get("observed_version"),
        "approval_binding_hash": _approval_binding_hash_string(approval_context.get("approval_binding_hash")),
        "approval_transition_head": (
            str(approval_context.get("approval_transition_head")).strip()
            if approval_context.get("approval_transition_head") is not None and str(approval_context.get("approval_transition_head")).strip()
            else None
        ),
        "approved_by": list(approved_by),
        "co_signed": bool(required_approvals and len(set(str(item).strip() for item in approved_by if str(item).strip())) >= len(required_approvals)),
        "co_sign_status": co_sign_status,
        "transfer_outcome": _transfer_outcome_label(action_intent=action_intent, allowed=True),
    }
    return {key: value for key, value in constraints.items() if value is not None}


def _workflow_status_for_decision(policy_decision: PolicyDecision) -> str:
    if policy_decision.disposition == "allow":
        return "verified"
    if policy_decision.disposition == "quarantine":
        return "quarantined"
    if policy_decision.disposition == "deny":
        return "rejected"
    co_sign_status = (
        str(policy_decision.authz_graph.get("co_sign_status")).strip().lower()
        if isinstance(policy_decision.authz_graph, Mapping) and policy_decision.authz_graph.get("co_sign_status") is not None
        else None
    )
    if co_sign_status in {"pending_co_sign", "awaiting_primary_signature"}:
        return "pending_approval"
    if policy_decision.required_approvals:
        return "pending_approval"
    return "review_required"


def _finalize_policy_decision_contract(
    *,
    policy_case: PolicyCase,
    policy_decision: PolicyDecision,
) -> PolicyDecision:
    action_intent = policy_case.action_intent
    authz_graph = (
        dict(policy_decision.authz_graph)
        if isinstance(policy_decision.authz_graph, Mapping)
        else {}
    )
    authz_graph["disposition"] = str(authz_graph.get("disposition") or policy_decision.disposition)
    authz_graph["matched_policy_refs"] = (
        list(authz_graph.get("matched_policy_refs"))
        if isinstance(authz_graph.get("matched_policy_refs"), list)
        else []
    )
    authz_graph["authority_paths"] = (
        list(authz_graph.get("authority_paths"))
        if isinstance(authz_graph.get("authority_paths"), list)
        else []
    )
    authz_graph["authority_path_summary"] = _authority_path_summary(authz_graph.get("authority_paths"))
    authz_graph["missing_prerequisites"] = (
        list(authz_graph.get("missing_prerequisites"))
        if isinstance(authz_graph.get("missing_prerequisites"), list)
        else []
    )
    authz_graph["trust_gaps"] = (
        list(authz_graph.get("trust_gaps"))
        if isinstance(authz_graph.get("trust_gaps"), list)
        else []
    )
    authz_graph["snapshot_hash"] = (
        str(authz_graph.get("snapshot_hash")).strip()
        if authz_graph.get("snapshot_hash") is not None and str(authz_graph.get("snapshot_hash")).strip()
        else None
    )

    if _is_restricted_custody_transfer(action_intent):
        authz_graph["workflow_type"] = RESTRICTED_CUSTODY_TRANSFER_WORKFLOW_TYPE
        authz_graph["workflow_status"] = _workflow_status_for_decision(policy_decision)
        approval_context = _approval_context(action_intent)
        authoritative_approval_envelope = _authoritative_approval_envelope(policy_case)
        authoritative_transition_history = _authoritative_approval_transition_history(policy_case)
        authoritative_transition_head = _authoritative_approval_transition_head(policy_case)
        if bool(policy_decision.break_glass.validated) and _is_zone_administrator(action_intent):
            approval_context["emergency_override_principal_ref"] = f"principal:{action_intent.principal.agent_id}"
        expected_co_signers = _transfer_expected_co_signers(
            action_intent,
            approval_context=approval_context,
            approval_envelope=authoritative_approval_envelope,
        )
        approved_by = (
            list(approval_context.get("approved_by"))
            if isinstance(approval_context.get("approved_by"), list)
            else []
        )
        co_sign_status = _transfer_co_sign_status(
            action_intent=action_intent,
            required_approvals=list(policy_decision.required_approvals or _transfer_required_approvals(action_intent)),
            approved_by=[str(item).strip() for item in approved_by if str(item).strip()],
            break_glass=policy_decision.break_glass,
        )
        transfer_outcome = _transfer_outcome_label(
            action_intent=action_intent,
            break_glass=policy_decision.break_glass,
            allowed=policy_decision.disposition == "allow",
        )
        authz_graph["required_approvals"] = list(
            policy_decision.required_approvals or _transfer_required_approvals(action_intent)
        )
        authz_graph["approval_envelope_id"] = (
            str(approval_context.get("approval_envelope_id")).strip()
            if approval_context.get("approval_envelope_id") is not None and str(approval_context.get("approval_envelope_id")).strip()
            else None
        )
        authz_graph["approval_envelope_version"] = (
            int(approval_context.get("approval_envelope_version") or approval_context.get("observed_version"))
            if approval_context.get("approval_envelope_version") is not None or approval_context.get("observed_version") is not None
            else None
        )
        authz_graph["approval_binding_hash"] = _approval_binding_hash_string(approval_context.get("approval_binding_hash"))
        authz_graph["approved_by"] = approved_by
        authz_graph["approval_transition_count"] = len(authoritative_transition_history)
        authz_graph["co_sign_required"] = bool(expected_co_signers)
        authz_graph["co_sign_status"] = co_sign_status
        authz_graph["transfer_outcome"] = transfer_outcome
        authz_graph["expected_co_signers"] = [dict(item) for item in expected_co_signers]
        authz_graph["co_sign_binding_hash"] = (
            str(approval_context.get("co_sign_binding_hash")).strip()
            if approval_context.get("co_sign_binding_hash") is not None and str(approval_context.get("co_sign_binding_hash")).strip()
                else _transfer_co_sign_binding_hash(
                    action_intent=action_intent,
                    approval_context=approval_context,
                    approval_envelope=authoritative_approval_envelope,
                    snapshot_hash=(
                        str(authz_graph.get("snapshot_hash")).strip()
                        if authz_graph.get("snapshot_hash") is not None and str(authz_graph.get("snapshot_hash")).strip()
                        else None
                    ),
                    transfer_outcome=transfer_outcome,
                )
        )
        authz_graph["approval_transition_head"] = (
            str(authoritative_transition_head).strip()
            if authoritative_transition_head is not None and str(authoritative_transition_head).strip()
            else None
        )

    policy_decision.required_approvals = list(policy_decision.required_approvals or _transfer_required_approvals(action_intent))
    policy_decision.obligations = _workflow_obligations(
        action_intent=action_intent,
        policy_decision=policy_decision,
        authz_graph=authz_graph,
    )
    authz_graph["obligations"] = list(policy_decision.obligations)
    authz_graph["minted_artifacts"] = _decision_minted_artifacts(policy_decision)

    governed_receipt = (
        dict(policy_decision.governed_receipt)
        if isinstance(policy_decision.governed_receipt, Mapping)
        else {}
    )
    if _is_restricted_custody_transfer(action_intent) and governed_receipt:
        approval_context = _approval_context(action_intent)
        authoritative_approval_envelope = _authoritative_approval_envelope(policy_case)
        authoritative_transition_history = _authoritative_approval_transition_history(policy_case)
        authoritative_transition_head = _authoritative_approval_transition_head(policy_case)
        if bool(policy_decision.break_glass.validated) and _is_zone_administrator(action_intent):
            approval_context["emergency_override_principal_ref"] = f"principal:{action_intent.principal.agent_id}"
        approved_by = approval_context.get("approved_by") if isinstance(approval_context.get("approved_by"), list) else []
        expected_co_signers = _transfer_expected_co_signers(
            action_intent,
            approval_context=approval_context,
            approval_envelope=authoritative_approval_envelope,
        )
        transfer_outcome = _transfer_outcome_label(
            action_intent=action_intent,
            break_glass=policy_decision.break_glass,
            allowed=policy_decision.disposition == "allow",
        )
        co_sign_status = _transfer_co_sign_status(
            action_intent=action_intent,
            required_approvals=list(policy_decision.required_approvals),
            approved_by=[str(item).strip() for item in approved_by if str(item).strip()],
            break_glass=policy_decision.break_glass,
        )
        advisory = dict(governed_receipt.get("advisory") or {})
        advisory.update(
            {
                "workflow_type": RESTRICTED_CUSTODY_TRANSFER_WORKFLOW_TYPE,
                "approval_envelope_id": approval_context.get("approval_envelope_id"),
                "approval_envelope_version": approval_context.get("approval_envelope_version") or approval_context.get("observed_version"),
                "approval_binding_hash": approval_context.get("approval_binding_hash"),
                "approved_by": list(approved_by),
                "co_signed": bool(policy_decision.required_approvals and len(set(str(item).strip() for item in approved_by if str(item).strip())) >= len(policy_decision.required_approvals)),
                "co_sign_required": bool(expected_co_signers),
                "co_sign_status": co_sign_status,
                "transfer_outcome": transfer_outcome,
                "expected_co_signers": [dict(item) for item in expected_co_signers],
                "co_sign_binding_hash": (
                    str(approval_context.get("co_sign_binding_hash")).strip()
                    if approval_context.get("co_sign_binding_hash") is not None and str(approval_context.get("co_sign_binding_hash")).strip()
                    else authz_graph.get("co_sign_binding_hash")
                ),
                "co_signatures": (
                    [dict(item) for item in approval_context.get("co_signatures") if isinstance(item, Mapping)]
                    if isinstance(approval_context.get("co_signatures"), list)
                    else []
                ),
                "approval_transition_count": len(authoritative_transition_history),
                "approval_transition_head": (
                    str(authoritative_transition_head).strip()
                    if authoritative_transition_head is not None and str(authoritative_transition_head).strip()
                    else None
                ),
                "last_approval_transition_event": (
                    dict(authoritative_transition_history[-1].get("transition_event"))
                    if authoritative_transition_history
                    and isinstance(authoritative_transition_history[-1], Mapping)
                    and isinstance(authoritative_transition_history[-1].get("transition_event"), Mapping)
                    else dict(authoritative_transition_history[-1])
                    if authoritative_transition_history
                    and isinstance(authoritative_transition_history[-1], Mapping)
                    else {}
                ),
                "from_zone": _transfer_context_value(action_intent, "from_zone"),
                "to_zone": _transfer_context_value(action_intent, "to_zone") or action_intent.resource.target_zone,
                "expected_current_custodian": _transfer_context_value(action_intent, "expected_current_custodian", "from_custodian_ref"),
                "next_custodian": _transfer_context_value(action_intent, "next_custodian", "to_custodian_ref"),
            }
        )
        governed_receipt.update(
            {
                "workflow_type": RESTRICTED_CUSTODY_TRANSFER_WORKFLOW_TYPE,
                "approval_envelope_id": approval_context.get("approval_envelope_id"),
                "approval_envelope_version": approval_context.get("approval_envelope_version") or approval_context.get("observed_version"),
                "approval_binding_hash": approval_context.get("approval_binding_hash"),
                "approved_by": list(approved_by),
                "co_signed": advisory["co_signed"],
                "co_sign_required": advisory["co_sign_required"],
                "co_sign_status": advisory["co_sign_status"],
                "transfer_outcome": advisory["transfer_outcome"],
                "expected_co_signers": advisory["expected_co_signers"],
                "co_sign_binding_hash": advisory["co_sign_binding_hash"],
                "co_signatures": advisory["co_signatures"],
                "approval_transition_count": advisory["approval_transition_count"],
                "approval_transition_head": advisory["approval_transition_head"],
                "last_approval_transition_event": advisory["last_approval_transition_event"],
                "from_zone": advisory["from_zone"],
                "target_zone": advisory["to_zone"],
                "expected_current_custodian": advisory["expected_current_custodian"],
                "next_custodian": advisory["next_custodian"],
                "advisory": advisory,
            }
        )
        if governed_receipt.get("snapshot_hash") is None and authz_graph.get("snapshot_hash") is not None:
            governed_receipt["snapshot_hash"] = authz_graph.get("snapshot_hash")
        if approval_context.get("approval_envelope_id") is not None and str(approval_context.get("approval_envelope_id")).strip():
            evidence_refs = list(governed_receipt.get("evidence_refs") or [])
            approval_ref = f"approval-envelope:{str(approval_context.get('approval_envelope_id')).strip()}"
            if approval_ref not in evidence_refs:
                evidence_refs.append(approval_ref)
            governed_receipt["evidence_refs"] = evidence_refs
        if approval_context.get("approval_binding_hash") is not None and str(approval_context.get("approval_binding_hash")).strip():
            provenance_sources = list(governed_receipt.get("provenance_sources") or [])
            binding_ref = f"approval_binding:{str(approval_context.get('approval_binding_hash')).strip()}"
            if binding_ref not in provenance_sources:
                provenance_sources.append(binding_ref)
            governed_receipt["provenance_sources"] = provenance_sources

    policy_decision.authz_graph = authz_graph
    policy_decision.governed_receipt = governed_receipt
    return policy_decision


def _compiled_authz_principal_ref(action_intent: ActionIntent) -> str:
    return f"principal:{action_intent.principal.agent_id.strip()}"


def _compiled_authz_operation(action_intent: ActionIntent) -> str:
    operation = action_intent.action.operation
    if operation is not None:
        return str(operation.value).strip().upper()
    return str(action_intent.action.type).strip().upper()


def _compiled_authz_resource_ref(action_intent: ActionIntent) -> str:
    resource_uri = (action_intent.resource.resource_uri or "").strip()
    if resource_uri:
        return resource_uri
    return f"resource:{action_intent.resource.asset_id.strip()}"


def _compiled_authz_zone_ref(action_intent: ActionIntent) -> str | None:
    zone = (
        _transfer_context_value(action_intent, "to_zone")
        or action_intent.resource.target_zone
        or ""
    ).strip()
    return f"zone:{zone}" if zone else None


def _compiled_authz_network_ref(action_intent: ActionIntent) -> str | None:
    network = (action_intent.environment.origin_network or "").strip()
    return f"network:{network}" if network else None


def _compiled_authz_product_ref(action_intent: ActionIntent) -> str | None:
    product_id = (action_intent.resource.product_id or "").strip()
    return f"product:{product_id}" if product_id else None


def _compiled_authz_lot_ref(action_intent: ActionIntent) -> str | None:
    lot_id = (action_intent.resource.lot_id or "").strip()
    return f"asset_batch:{lot_id}" if lot_id else None


def _compiled_authz_facility_ref(action_intent: ActionIntent) -> str | None:
    transfer_facility = _transfer_context_value(action_intent, "facility_ref", "facility_id")
    if transfer_facility is not None and transfer_facility.strip():
        facility = transfer_facility.strip()
        return facility if facility.startswith("facility:") else f"facility:{facility}"
    parameters = action_intent.action.parameters if isinstance(action_intent.action.parameters, dict) else {}
    for key in ("facility_id", "warehouse_id"):
        value = parameters.get(key)
        if value is not None and str(value).strip():
            return f"facility:{str(value).strip()}"
    custody_point_ref = _compiled_authz_custody_point_ref(action_intent)
    if custody_point_ref and custody_point_ref.startswith("custody_point:"):
        return f"facility:{custody_point_ref.removeprefix('custody_point:')}"
    return None


def _compiled_authz_shard_key(action_intent: ActionIntent) -> str:
    for value in (
        _compiled_authz_facility_ref(action_intent),
        _compiled_authz_custody_point_ref(action_intent),
        _compiled_authz_zone_ref(action_intent),
        _compiled_authz_product_ref(action_intent),
        _compiled_authz_lot_ref(action_intent),
        _compiled_authz_network_ref(action_intent),
    ):
        if value is not None and str(value).strip():
            return str(value)
    return "global"


def _compiled_authz_source_registration_ref(action_intent: ActionIntent) -> str | None:
    registration_id = (action_intent.resource.source_registration_id or "").strip()
    return f"registration:{registration_id}" if registration_id else None


def _compiled_authz_registration_decision_ref(action_intent: ActionIntent) -> str | None:
    decision_id = (action_intent.resource.registration_decision_id or "").strip()
    return f"registration_decision:{decision_id}" if decision_id else None


def _compiled_authz_workflow_stage_ref(action_intent: ActionIntent) -> str | None:
    parameters = action_intent.action.parameters if isinstance(action_intent.action.parameters, dict) else {}
    for key in ("workflow_stage", "stage", "workflow_step", "step"):
        value = parameters.get(key)
        if value is not None and str(value).strip():
            return f"workflow_stage:{str(value).strip()}"
    return None


def _compiled_authz_asset_ref(action_intent: ActionIntent) -> str | None:
    asset_id = (action_intent.resource.asset_id or "").strip()
    return f"asset:{asset_id}" if asset_id else None


def _compiled_authz_custody_point_ref(action_intent: ActionIntent) -> str | None:
    transfer_custody_point = _transfer_context_value(action_intent, "custody_point_ref")
    if transfer_custody_point is not None and transfer_custody_point.strip():
        custody_point = transfer_custody_point.strip()
        return custody_point if custody_point.startswith("custody_point:") else f"custody_point:{custody_point}"
    parameters = action_intent.action.parameters if isinstance(action_intent.action.parameters, dict) else {}
    for key in ("custody_point", "custody_point_id", "facility_id", "warehouse_id"):
        value = parameters.get(key)
        if value is not None and str(value).strip():
            return f"custody_point:{str(value).strip()}"
    return None


def _compiled_authz_resource_state_hash(action_intent: ActionIntent) -> str | None:
    resource_state_hash = (action_intent.resource.resource_state_hash or "").strip()
    return resource_state_hash or None


def _compiled_authz_transition_request(
    *,
    action_intent: ActionIntent,
    break_glass: bool,
) -> AuthzTransitionRequest:
    return AuthzTransitionRequest(
        principal_ref=_compiled_authz_principal_ref(action_intent),
        operation=_compiled_authz_operation(action_intent),
        resource_ref=_compiled_authz_resource_ref(action_intent),
        asset_ref=_compiled_authz_asset_ref(action_intent),
        source_registration_ref=_compiled_authz_source_registration_ref(action_intent),
        registration_decision_ref=_compiled_authz_registration_decision_ref(action_intent),
        workflow_stage_ref=_compiled_authz_workflow_stage_ref(action_intent),
        zone_ref=_compiled_authz_zone_ref(action_intent),
        network_ref=_compiled_authz_network_ref(action_intent),
        custody_point_ref=_compiled_authz_custody_point_ref(action_intent),
        resource_state_hash=_compiled_authz_resource_state_hash(action_intent),
        expected_custodian_ref=_transfer_context_value(
            action_intent,
            "expected_current_custodian",
            "from_custodian_ref",
        ),
        require_approved_source_registration=_requires_approved_source_registration(action_intent),
        at=_parse_iso8601(action_intent.timestamp),
        break_glass=break_glass,
    )


def _compiled_authz_deny_decision(
    *,
    policy_case: PolicyCase,
    match: CompiledPermissionMatch,
    break_glass: BreakGlassDecisionContext | None = None,
    authz_evaluator: str = "compiled_index",
) -> PolicyDecision:
    matched_subjects = ", ".join(match.matched_subjects) if match.matched_subjects else "none"
    deny_count = len(match.deny_permissions)
    allow_count = len(match.matched_permissions)
    break_glass_count = len(match.break_glass_permissions)
    if match.reason == "explicit_deny":
        reason = "Compiled authorization graph returned an explicit deny for the ActionIntent."
    elif match.reason == "break_glass_required":
        reason = "Compiled authorization graph requires a valid break-glass token for this ActionIntent."
    else:
        reason = "Compiled authorization graph denied the ActionIntent."
    return _deny_decision(
        reason,
        AUTHZ_GRAPH_DENY_CODE,
        policy_case.policy_snapshot,
        risk_score=_policy_case_risk_score(policy_case),
        cognitive_assessment=policy_case.cognitive_assessment,
        explanations=_policy_case_explanations(
            policy_case,
            f"compiled_authz_result={match.reason}",
        )
        + [
            f"compiled_authz_subjects={matched_subjects}",
            f"compiled_authz_allow_matches={allow_count}",
            f"compiled_authz_deny_matches={deny_count}",
            f"compiled_authz_break_glass_matches={break_glass_count}",
            f"compiled_authz_break_glass_required={match.break_glass_required}",
        ],
        break_glass=break_glass,
        authz_graph=_authz_graph_decision_metadata(
            transition_evaluation=None,
            compiled_match=match,
            evaluator=authz_evaluator,
        ),
    )


def _compiled_authz_transition_deny_decision(
    *,
    policy_case: PolicyCase,
    evaluation: CompiledTransitionEvaluation,
    break_glass: BreakGlassDecisionContext | None = None,
    authz_evaluator: str = "compiled_index",
) -> PolicyDecision:
    trust_gap_codes = [gap.code for gap in evaluation.trust_gaps]
    if evaluation.reason == "principal_not_current_custodian":
        reason = "Compiled authorization graph denied the requested asset transition because the principal is not the current custodian."
    elif evaluation.reason == "expected_custodian_mismatch":
        reason = "Compiled authorization graph denied the requested asset transition because the expected custodian does not match the compiled custody chain."
    elif evaluation.reason == "asset_not_transferable":
        reason = "Compiled authorization graph denied the requested asset transition because the asset is not in a transferable state."
    elif evaluation.reason == "asset_restricted":
        reason = "Compiled authorization graph denied the requested asset transition because the asset is already restricted."
    elif evaluation.reason == "missing_source_registration":
        reason = "Compiled authorization graph denied the requested asset transition because a required source registration was missing from the asset lineage."
    elif evaluation.reason == "unapproved_source_registration":
        reason = "Compiled authorization graph denied the requested asset transition because the linked source registration is not approved."
    elif evaluation.reason == "mismatched_registration_decision":
        reason = "Compiled authorization graph denied the requested asset transition because the provided registration decision does not match the approved lineage."
    elif evaluation.reason == "trust_gap_denied":
        reason = "Compiled authorization graph denied the requested asset transition because required trust evidence is incomplete."
    else:
        reason = "Compiled authorization graph denied the requested asset transition."
    return _deny_decision(
        reason,
        AUTHZ_GRAPH_DENY_CODE,
        policy_case.policy_snapshot,
        risk_score=_policy_case_risk_score(policy_case),
        cognitive_assessment=policy_case.cognitive_assessment,
        explanations=_policy_case_explanations(
            policy_case,
            f"compiled_authz_transition_result={evaluation.reason}",
        )
        + [
            f"compiled_authz_transition_disposition={evaluation.disposition.value}",
            f"compiled_authz_transition_asset_ref={evaluation.asset_ref or 'none'}",
            f"compiled_authz_transition_resource_ref={evaluation.resource_ref or 'none'}",
            f"compiled_authz_transition_current_custodian={evaluation.current_custodian or 'none'}",
            f"compiled_authz_transition_trust_gaps={','.join(trust_gap_codes) if trust_gap_codes else 'none'}",
        ],
        evidence_gaps=trust_gap_codes or None,
        break_glass=break_glass,
        authz_graph=_authz_graph_decision_metadata(
            transition_evaluation=evaluation,
            compiled_match=evaluation.permission_match,
            evaluator=authz_evaluator,
        ),
        governed_receipt=_serialize_governed_receipt(evaluation),
    )


def _pdp_use_active_authz_graph() -> bool:
    raw = os.getenv("SEEDCORE_PDP_USE_ACTIVE_AUTHZ_GRAPH", "false")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _pdp_use_authz_graph_transitions() -> bool:
    raw = os.getenv("SEEDCORE_PDP_USE_AUTHZ_GRAPH_TRANSITIONS", "false")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _pdp_use_rust_policy_core_for_restricted_transfer() -> bool:
    raw = os.getenv("SEEDCORE_PDP_USE_RUST_POLICY_CORE_TRANSFER", "true")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _pdp_use_ray_authz_cache() -> bool:
    raw = os.getenv("SEEDCORE_PDP_USE_RAY_AUTHZ_CACHE", "false")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _pdp_ray_authz_cache_timeout_seconds() -> float:
    raw = os.getenv("SEEDCORE_PDP_RAY_AUTHZ_CACHE_TIMEOUT_SECONDS", "1.0")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return max(0.1, value)


def _coerce_twin_snapshot(key: str, value: Any) -> TwinSnapshot:
    if isinstance(value, TwinSnapshot):
        return value
    if isinstance(value, Mapping):
        payload = dict(value)
        payload.setdefault("twin_kind", key)
        payload.setdefault("twin_id", str(payload.get("twin_id") or key))
        return TwinSnapshot(**payload)
    return TwinSnapshot(twin_kind=key, twin_id=str(value))


def _coerce_policy_case_assessment(
    value: Mapping[str, Any] | PolicyCaseAssessment | None,
) -> PolicyCaseAssessment | None:
    if value is None:
        return None
    if isinstance(value, PolicyCaseAssessment):
        return value
    if isinstance(value, Mapping):
        payload = dict(value)
        if isinstance(payload.get("advisory"), Mapping):
            payload = dict(payload["advisory"])
        if payload.get("kind") == "policy_case_assessment" or "recommended_disposition" in payload:
            payload.setdefault("trace_ref", payload.get("advisory_id"))
            return PolicyCaseAssessment(**payload)
    return None


def _coerce_risk_score(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return round(max(0.0, min(1.0, float(value))), 3)


def _extract_policy_codes(values: Any) -> list[str]:
    codes: list[str] = []
    if not isinstance(values, list):
        return codes
    for item in values:
        if isinstance(item, Mapping):
            candidate = item.get("code")
        else:
            candidate = item
        value = str(candidate or "").strip()
        if value and value not in codes:
            codes.append(value)
    return codes


def _merge_policy_code_lists(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for item in group:
            value = str(item).strip()
            if value and value not in merged:
                merged.append(value)
    return merged


def _rust_kernel_missing_prerequisites(codes: list[str]) -> list[str]:
    telemetry_codes = {"telemetry_freshness", "stale_telemetry", "missing_telemetry"}
    return [code for code in codes if code not in telemetry_codes]


def _synthesized_transfer_approval_envelope(
    *,
    action_intent: ActionIntent,
    policy_snapshot: str,
) -> dict[str, Any]:
    approval_context = _approval_context(action_intent)
    required_roles = _transfer_required_approvals(action_intent)
    approved_by = [
        str(item).strip()
        for item in (approval_context.get("approved_by") if isinstance(approval_context.get("approved_by"), list) else [])
        if str(item).strip()
    ]
    from_custodian = _transfer_context_value(action_intent, "expected_current_custodian", "from_custodian_ref") or ""
    to_custodian = _transfer_context_value(action_intent, "next_custodian", "to_custodian_ref") or ""
    if required_roles and len(approved_by) >= len(required_roles):
        status = "APPROVED"
    elif approved_by:
        status = "PARTIALLY_APPROVED"
    else:
        status = "PENDING"
    binding_hash = _approval_binding_hash_string(approval_context.get("approval_binding_hash"))

    required_approvals: list[dict[str, Any]] = []
    for role in required_roles:
        principal = next(
            (ref for ref in approved_by if role.split("_")[0].lower() in ref.lower()),
            approved_by[0] if approved_by else from_custodian or None,
        )
        required_approvals.append(
            {
                "role": role,
                "principal_ref": principal or "principal:unknown",
                "status": "APPROVED" if principal in approved_by else "PENDING",
                "approved_at": action_intent.timestamp,
                "approval_ref": f"approval:{role.lower()}",
            }
        )

    return {
        "approval_envelope_id": str(approval_context.get("approval_envelope_id") or f"approval:{action_intent.intent_id}"),
        "workflow_type": RESTRICTED_CUSTODY_TRANSFER_WORKFLOW_TYPE,
        "status": status,
        "asset_ref": str(action_intent.resource.asset_id),
        "lot_id": action_intent.resource.lot_id,
        "from_custodian_ref": from_custodian or "principal:unknown",
        "to_custodian_ref": to_custodian or "principal:unknown",
        "transfer_context": {
            "from_zone": _transfer_context_value(action_intent, "from_zone"),
            "to_zone": _transfer_context_value(action_intent, "to_zone") or action_intent.resource.target_zone,
            "facility_ref": _transfer_context_value(action_intent, "facility_ref"),
            "custody_point_ref": _transfer_context_value(action_intent, "custody_point_ref"),
        },
        "required_approvals": required_approvals,
        "approval_binding_hash": (
            {"algorithm": "sha256", "value": binding_hash.split(":", 1)[1]}
            if binding_hash and ":" in binding_hash
            else None
        ),
        "policy_snapshot_ref": policy_snapshot,
        "expires_at": action_intent.valid_until,
        "created_at": action_intent.timestamp,
        "version": 1,
    }


def _rust_policy_reason(disposition: str) -> str:
    if disposition == "allow":
        return "restricted_custody_transfer"
    if disposition == "deny":
        return "approval_incomplete"
    if disposition == "quarantine":
        return "quarantine"
    return POLICY_ESCALATION_CODE


def _build_execution_constraints(action_intent: ActionIntent) -> Dict[str, Any]:
    parameters = action_intent.action.parameters if isinstance(action_intent.action.parameters, dict) else {}
    values = {
        "action_type": action_intent.action.type,
        "target_zone": action_intent.resource.target_zone,
        "asset_id": action_intent.resource.asset_id,
        "principal_agent_id": action_intent.principal.agent_id,
        "source_registration_id": action_intent.resource.source_registration_id,
        "registration_decision_id": action_intent.resource.registration_decision_id,
        "endpoint_id": parameters.get("endpoint_id"),
    }
    return {
        key: values[key]
        for key in EXECUTION_TOKEN_CONSTRAINT_KEYS
    }


def _mint_execution_token(
    *,
    action_intent: ActionIntent,
    issued_at: datetime,
    valid_until: datetime,
    extra_constraints: Mapping[str, Any] | None = None,
) -> ExecutionToken:
    constraints = _build_execution_constraints(action_intent)
    if extra_constraints:
        constraints.update(
            {
                key: value
                for key, value in extra_constraints.items()
                if value is not None
            }
        )
    token_payload = {
        "token_id": str(uuid.uuid4()),
        "intent_id": action_intent.intent_id,
        "issued_at": _isoformat(issued_at),
        "valid_until": _isoformat(valid_until),
        "contract_version": action_intent.action.security_contract.version,
        "constraints": constraints,
    }
    minted = mint_execution_token_with_rust(token_payload)
    if minted.get("error") is not None:
        raise ValueError(f"rust_token_mint_failed:{minted.get('error')}")
    # Preserve strict Rust-minted constraints while carrying transfer-specific
    # workflow bindings required by the execution spine.
    minted_constraints = minted.get("constraints")
    merged_constraints: Dict[str, Any] = dict(constraints)
    if isinstance(minted_constraints, Mapping):
        merged_constraints.update(dict(minted_constraints))
    minted["constraints"] = merged_constraints
    return ExecutionToken(**minted)


def _allow_reason(action_intent: ActionIntent) -> str:
    return EXPLICIT_ALLOW_RULE if _requires_approved_source_registration(action_intent) else "allowed"


def _serialize_governed_receipt(
    evaluation: CompiledTransitionEvaluation | None,
) -> Dict[str, Any]:
    if evaluation is None:
        return {}
    receipt = evaluation.receipt
    return {
        "decision_hash": receipt.decision_hash,
        "disposition": receipt.disposition.value,
        "snapshot_ref": receipt.snapshot_ref,
        "snapshot_id": receipt.snapshot_id,
        "snapshot_version": receipt.snapshot_version,
        "snapshot_hash": receipt.snapshot_hash,
        "principal_ref": receipt.principal_ref,
        "operation": receipt.operation,
        "asset_ref": receipt.asset_ref,
        "resource_ref": receipt.resource_ref,
        "twin_ref": receipt.twin_ref,
        "reason": receipt.reason,
        "generated_at": receipt.generated_at,
        "custody_proof": list(receipt.custody_proof),
        "evidence_refs": list(receipt.evidence_refs),
        "trust_gap_codes": list(receipt.trust_gap_codes),
        "provenance_sources": list(receipt.provenance_sources),
        "advisory": dict(receipt.advisory),
    }


def _authz_graph_decision_metadata(
    *,
    transition_evaluation: CompiledTransitionEvaluation | None,
    compiled_match: CompiledPermissionMatch | None,
    evaluator: str | None = None,
) -> Dict[str, Any]:
    if transition_evaluation is None:
        if compiled_match is None:
            return {"evaluator": evaluator} if evaluator else {}
        payload = {
            "mode": "permission_match",
            "match_reason": compiled_match.reason,
            "matched_subjects": list(compiled_match.matched_subjects),
            "authority_paths": [list(path) for path in compiled_match.authority_paths],
            "authority_path_summary": _authority_path_summary([list(path) for path in compiled_match.authority_paths]),
            "matched_policy_refs": _policy_refs(compiled_match.matched_permissions),
            "deny_policy_refs": _policy_refs(compiled_match.deny_permissions),
            "break_glass_policy_refs": _policy_refs(compiled_match.break_glass_permissions),
            "missing_prerequisites": [],
            "break_glass_required": compiled_match.break_glass_required,
            "break_glass_used": compiled_match.break_glass_used,
        }
        if evaluator:
            payload["evaluator"] = evaluator
        return payload
    payload = {
        "mode": "transition_evaluation",
        "disposition": transition_evaluation.disposition.value,
        "reason": transition_evaluation.reason,
        "snapshot_ref": transition_evaluation.receipt.snapshot_ref,
        "snapshot_id": transition_evaluation.receipt.snapshot_id,
        "snapshot_version": transition_evaluation.receipt.snapshot_version,
        "snapshot_hash": transition_evaluation.receipt.snapshot_hash,
        "asset_ref": transition_evaluation.asset_ref,
        "resource_ref": transition_evaluation.resource_ref,
        "current_custodian": transition_evaluation.current_custodian,
        "restricted_token_recommended": transition_evaluation.restricted_token_recommended,
        "permission_match_reason": transition_evaluation.permission_match.reason,
        "matched_subjects": list(transition_evaluation.permission_match.matched_subjects),
        "authority_paths": [list(path) for path in transition_evaluation.permission_match.authority_paths],
        "authority_path_summary": _authority_path_summary(
            [list(path) for path in transition_evaluation.permission_match.authority_paths]
        ),
        "matched_policy_refs": _policy_refs(transition_evaluation.permission_match.matched_permissions),
        "deny_policy_refs": _policy_refs(transition_evaluation.permission_match.deny_permissions),
        "break_glass_policy_refs": _policy_refs(transition_evaluation.permission_match.break_glass_permissions),
        "trust_gaps": [
            {
                "code": gap.code,
                "message": gap.message,
                "details": dict(gap.details),
            }
            for gap in transition_evaluation.trust_gaps
        ],
        "checked_constraints": [
            {
                "code": check.code,
                "outcome": check.outcome,
                "message": check.message,
                "details": dict(check.details),
            }
            for check in transition_evaluation.checked_constraints
        ],
        "missing_prerequisites": _missing_prerequisites(transition_evaluation),
    }
    if evaluator:
        payload["evaluator"] = evaluator
    return payload


def _policy_refs(permissions: Iterable[CompiledPermission]) -> list[str]:
    return sorted({item.provenance_source for item in permissions if item.provenance_source})


def _missing_prerequisites(evaluation: CompiledTransitionEvaluation) -> list[dict[str, Any]]:
    return [
        {
            "code": check.code,
            "outcome": check.outcome,
            "message": check.message,
            "details": dict(check.details),
        }
        for check in evaluation.checked_constraints
        if check.outcome in {"missing", "failed"}
    ]


def _transition_execution_constraints(
    evaluation: CompiledTransitionEvaluation | None,
) -> Dict[str, Any]:
    if evaluation is None:
        return {}
    payload = {
        "authz_disposition": evaluation.disposition.value,
        "authz_reason": evaluation.reason,
        "governed_receipt_hash": evaluation.receipt.decision_hash,
        "asset_ref": evaluation.asset_ref,
    }
    if evaluation.disposition == AuthzDecisionDisposition.QUARANTINE:
        payload.update(
            {
                "restricted_state": True,
                "trust_gap_codes": [gap.code for gap in evaluation.trust_gaps],
            }
        )
    return payload


def _merge_action_intent_payload(
    baseline: Mapping[str, Any],
    override: Mapping[str, Any],
) -> Dict[str, Any]:
    merged = dict(baseline)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _merge_action_intent_payload(
                dict(merged[key]),
                dict(value),
            )
        else:
            merged[key] = value
    action_override = override.get("action")
    action_merged = merged.get("action")
    if isinstance(action_override, Mapping) and isinstance(action_merged, Mapping):
        if action_override.get("type") is not None and "operation" not in action_override:
            merged["action"] = dict(action_merged)
            merged["action"].pop("operation", None)
    return merged


def _derive_resource_uri(*, asset_id: Any, target_zone: Any) -> str:
    asset_segment = quote(str(asset_id), safe=":-_.")
    if target_zone is not None and str(target_zone).strip():
        zone_segment = quote(str(target_zone), safe=":-_.")
        return f"seedcore://zones/{zone_segment}/assets/{asset_segment}"
    return f"seedcore://assets/{asset_segment}"


def _derive_resource_state_hash(
    *,
    asset_id: Any,
    target_zone: Any,
    twin_inputs: Mapping[str, Any],
    resource: Mapping[str, Any],
) -> str | None:
    asset_twin = twin_inputs.get("asset") if isinstance(twin_inputs.get("asset"), Mapping) else {}
    if isinstance(resource.get("state"), Mapping):
        state_source = dict(resource["state"])
    elif asset_twin:
        state_source = dict(asset_twin)
    else:
        state_source = {}
    if not state_source:
        return None
    state_source.setdefault("asset_id", str(asset_id))
    if target_zone is not None:
        state_source.setdefault("target_zone", str(target_zone))
    return _sha256_hex(_canonical_json(state_source))


def _derive_hmac_token_claims(
    *,
    token: str,
    prefix: str,
    secret_env: str,
) -> Dict[str, Any]:
    try:
        token_prefix, payload_segment, signature_segment = token.split(".", 2)
        if token_prefix != prefix:
            raise ValueError("unsupported_token_scheme")
        signing_input = f"{prefix}.{payload_segment}".encode("utf-8")
        secret = os.getenv(secret_env, "").strip()
        if not secret:
            raise ValueError("token_secret_unconfigured")
        expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(_pad_base64(signature_segment))
        if not hmac.compare_digest(actual, expected):
            raise ValueError("token_signature_invalid")
        payload_bytes = base64.urlsafe_b64decode(_pad_base64(payload_segment))
        claims = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(claims, dict):
            raise ValueError("token_claims_invalid")
        return claims
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("token_malformed") from exc


def _derive_actor_token_claims(token: str) -> Dict[str, Any]:
    try:
        return _derive_hmac_token_claims(
            token=token,
            prefix="seedcore_hmac_v1",
            secret_env="SEEDCORE_PDP_ACTOR_TOKEN_SECRET",
        )
    except ValueError as exc:
        mapping = {
            "unsupported_token_scheme": "unsupported_actor_token_scheme",
            "token_secret_unconfigured": "actor_token_secret_unconfigured",
            "token_signature_invalid": "actor_token_signature_invalid",
            "token_claims_invalid": "actor_token_claims_invalid",
            "token_malformed": "actor_token_malformed",
        }
        raise ValueError(mapping.get(str(exc), str(exc))) from exc


def _derive_break_glass_claims(token: str) -> Dict[str, Any]:
    try:
        return _derive_hmac_token_claims(
            token=token,
            prefix="seedcore_break_glass_v1",
            secret_env="SEEDCORE_PDP_BREAK_GLASS_SECRET",
        )
    except ValueError as exc:
        mapping = {
            "unsupported_token_scheme": "unsupported_break_glass_token_scheme",
            "token_secret_unconfigured": "break_glass_token_secret_unconfigured",
            "token_signature_invalid": "break_glass_token_signature_invalid",
            "token_claims_invalid": "break_glass_token_claims_invalid",
            "token_malformed": "break_glass_token_malformed",
        }
        raise ValueError(mapping.get(str(exc), str(exc))) from exc


def _build_break_glass_context(
    action_intent: ActionIntent,
    *,
    claims: Mapping[str, Any] | None = None,
    validated: bool = False,
    used: bool = False,
    override_applied: bool = False,
    required: bool = False,
    outcome: str | None = None,
    procedure_id: str | None = None,
    incident_id: str | None = None,
    reason_code: str | None = None,
    risk_score: float | None = None,
    ocps_score: float | None = None,
) -> BreakGlassDecisionContext:
    token_issued_at = None
    token_expires_at = None
    if claims is not None:
        issued_at_raw = claims.get("iat")
        expires_at_raw = claims.get("exp")
        if isinstance(issued_at_raw, (int, float)):
            token_issued_at = _isoformat(datetime.fromtimestamp(float(issued_at_raw), tz=timezone.utc))
        if isinstance(expires_at_raw, (int, float)):
            token_expires_at = _isoformat(datetime.fromtimestamp(float(expires_at_raw), tz=timezone.utc))

    return BreakGlassDecisionContext(
        present=bool(action_intent.environment.break_glass_token),
        validated=validated,
        used=used,
        override_applied=override_applied,
        required=required,
        reason=action_intent.environment.break_glass_reason,
        principal_id=action_intent.principal.agent_id,
        token_issued_at=token_issued_at,
        token_expires_at=token_expires_at,
        outcome=outcome,
        procedure_id=procedure_id,
        incident_id=incident_id,
        reason_code=reason_code,
        risk_score=_coerce_risk_score(risk_score),
        ocps_score=_coerce_risk_score(ocps_score),
    )


def _evaluate_actor_token_policy(
    *,
    action_intent: ActionIntent,
    now: datetime,
    policy_snapshot: str | None,
    policy_case: PolicyCase,
) -> PolicyDecision | None:
    actor_token = action_intent.principal.actor_token
    if _pdp_actor_token_required() and not actor_token:
        return _deny_decision(
            "ActionIntent is missing principal.actor_token.",
            MISSING_ACTOR_TOKEN_DENY_CODE,
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )
    if not actor_token:
        return None
    try:
        claims = _derive_actor_token_claims(actor_token)
    except ValueError as exc:
        return _deny_decision(
            f"Actor token verification failed: {exc}.",
            INVALID_ACTOR_TOKEN_DENY_CODE,
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )

    subject = str(claims.get("sub") or "").strip()
    if subject != action_intent.principal.agent_id:
        return _deny_decision(
            "Actor token subject does not match principal.agent_id.",
            ACTOR_TOKEN_SUBJECT_MISMATCH_DENY_CODE,
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )

    issued_at_raw = claims.get("iat")
    expires_at_raw = claims.get("exp")
    if not isinstance(issued_at_raw, (int, float)) or not isinstance(expires_at_raw, (int, float)):
        return _deny_decision(
            "Actor token is missing numeric iat/exp claims.",
            INVALID_ACTOR_TOKEN_DENY_CODE,
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )

    skew_seconds = _pdp_actor_token_max_skew_seconds()
    now_ts = now.timestamp()
    if float(expires_at_raw) <= float(issued_at_raw):
        return _deny_decision(
            "Actor token expiry window is invalid.",
            INVALID_ACTOR_TOKEN_DENY_CODE,
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )
    if now_ts > float(expires_at_raw) + skew_seconds:
        return _deny_decision(
            "Actor token is expired.",
            ACTOR_TOKEN_EXPIRED_DENY_CODE,
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )
    if float(issued_at_raw) - skew_seconds > now_ts:
        return _deny_decision(
            "Actor token iat is in the future.",
            INVALID_ACTOR_TOKEN_DENY_CODE,
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )

    audience = os.getenv("SEEDCORE_PDP_ACTOR_TOKEN_AUDIENCE", "").strip()
    if audience:
        token_audience = claims.get("aud")
        if isinstance(token_audience, list):
            valid_audience = audience in [str(item) for item in token_audience]
        else:
            valid_audience = str(token_audience or "").strip() == audience
        if not valid_audience:
            return _deny_decision(
                "Actor token audience does not match PDP expectations.",
                INVALID_ACTOR_TOKEN_DENY_CODE,
                policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
            )

    origin_network = action_intent.environment.origin_network
    token_origin = claims.get("origin_network")
    if origin_network and token_origin and str(token_origin).strip() != origin_network:
        return _deny_decision(
            "Actor token origin_network does not match ActionIntent.environment.origin_network.",
            INVALID_ACTOR_TOKEN_DENY_CODE,
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )

    session_claim = str(claims.get("session_token") or "").strip()
    if session_claim and action_intent.principal.session_token and session_claim != action_intent.principal.session_token:
        return _deny_decision(
            "Actor token session_token does not match principal.session_token.",
            INVALID_ACTOR_TOKEN_DENY_CODE,
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )

    return None


def _evaluate_break_glass_context(
    *,
    action_intent: ActionIntent,
    now: datetime,
    policy_snapshot: str | None,
    policy_case: PolicyCase,
) -> tuple[PolicyDecision | None, BreakGlassDecisionContext]:
    break_glass_token = action_intent.environment.break_glass_token
    base_context = _build_break_glass_context(action_intent)
    if not break_glass_token:
        return None, base_context
    try:
        claims = _derive_break_glass_claims(break_glass_token)
    except ValueError as exc:
        context = base_context.model_copy(update={"outcome": "verification_failed"})
        return (
            _deny_decision(
                f"Break-glass token verification failed: {exc}.",
                INVALID_BREAK_GLASS_TOKEN_DENY_CODE,
                policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
                break_glass=context,
            ),
            context,
        )

    subject = str(claims.get("sub") or "").strip()
    if subject != action_intent.principal.agent_id:
        context = _build_break_glass_context(action_intent, claims=claims, outcome="subject_mismatch")
        return (
            _deny_decision(
                "Break-glass token subject does not match principal.agent_id.",
                BREAK_GLASS_TOKEN_SUBJECT_MISMATCH_DENY_CODE,
                policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
                break_glass=context,
            ),
            context,
        )

    issued_at_raw = claims.get("iat")
    expires_at_raw = claims.get("exp")
    if not isinstance(issued_at_raw, (int, float)) or not isinstance(expires_at_raw, (int, float)):
        context = _build_break_glass_context(
            action_intent,
            claims=claims,
            outcome="claims_invalid",
        )
        return (
            _deny_decision(
                "Break-glass token is missing numeric iat/exp claims.",
                INVALID_BREAK_GLASS_TOKEN_DENY_CODE,
                policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
                break_glass=context,
            ),
            context,
        )

    skew_seconds = _pdp_break_glass_token_max_skew_seconds()
    now_ts = now.timestamp()
    if float(expires_at_raw) <= float(issued_at_raw):
        context = _build_break_glass_context(
            action_intent,
            claims=claims,
            outcome="window_invalid",
        )
        return (
            _deny_decision(
                "Break-glass token expiry window is invalid.",
                INVALID_BREAK_GLASS_TOKEN_DENY_CODE,
                policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
                break_glass=context,
            ),
            context,
        )
    if now_ts > float(expires_at_raw) + skew_seconds:
        context = _build_break_glass_context(
            action_intent,
            claims=claims,
            outcome="expired",
        )
        return (
            _deny_decision(
                "Break-glass token is expired.",
                BREAK_GLASS_TOKEN_EXPIRED_DENY_CODE,
                policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
                break_glass=context,
            ),
            context,
        )
    if float(issued_at_raw) - skew_seconds > now_ts:
        context = _build_break_glass_context(
            action_intent,
            claims=claims,
            outcome="issued_in_future",
        )
        return (
            _deny_decision(
                "Break-glass token iat is in the future.",
                INVALID_BREAK_GLASS_TOKEN_DENY_CODE,
                policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
                break_glass=context,
            ),
            context,
        )

    required_reason = bool(claims.get("require_reason"))
    if required_reason and not (action_intent.environment.break_glass_reason or "").strip():
        context = _build_break_glass_context(
            action_intent,
            claims=claims,
            required=True,
            outcome="reason_required",
        )
        return (
            _deny_decision(
                "Break-glass token requires a non-empty break_glass_reason.",
                INVALID_BREAK_GLASS_TOKEN_DENY_CODE,
                policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case),
                cognitive_assessment=policy_case.cognitive_assessment,
                break_glass=context,
            ),
            context,
        )

    high_risk, risk_score, ocps_score, profile_reasons = _break_glass_high_risk_profile(
        action_intent=action_intent,
        policy_case=policy_case,
    )
    procedure_id = str(claims.get("procedure_id") or "").strip() or None
    incident_id = str(claims.get("incident_id") or "").strip() or None
    reason_code = str(claims.get("reason_code") or "").strip().lower() or None

    if high_risk and _pdp_break_glass_require_deterministic_procedure():
        missing_claims: list[str] = []
        if not procedure_id:
            missing_claims.append("procedure_id")
        if not incident_id:
            missing_claims.append("incident_id")
        if not reason_code:
            missing_claims.append("reason_code")
        if missing_claims:
            context = _build_break_glass_context(
                action_intent,
                claims=claims,
                required=True,
                outcome="deterministic_procedure_required",
                procedure_id=procedure_id,
                incident_id=incident_id,
                reason_code=reason_code,
                risk_score=risk_score,
                ocps_score=ocps_score,
            )
            return (
                _deny_decision(
                    (
                        "High-risk break-glass requires deterministic procedure claims "
                        "(procedure_id, incident_id, reason_code)."
                    ),
                    BREAK_GLASS_PROCEDURE_REQUIRED_DENY_CODE,
                    policy_snapshot,
                    risk_score=_policy_case_risk_score(policy_case),
                    cognitive_assessment=policy_case.cognitive_assessment,
                    explanations=_policy_case_explanations(
                        policy_case,
                        "break_glass_deterministic_procedure_required",
                    )
                    + [
                        f"break_glass_missing_claims={','.join(missing_claims)}",
                        f"break_glass_profile={','.join(profile_reasons) if profile_reasons else 'none'}",
                    ],
                    break_glass=context,
                ),
                context,
            )

        allowed_reason_codes = _pdp_break_glass_reason_codes()
        if allowed_reason_codes and reason_code not in allowed_reason_codes:
            context = _build_break_glass_context(
                action_intent,
                claims=claims,
                required=True,
                outcome="reason_code_not_allowed",
                procedure_id=procedure_id,
                incident_id=incident_id,
                reason_code=reason_code,
                risk_score=risk_score,
                ocps_score=ocps_score,
            )
            return (
                _deny_decision(
                    (
                        "High-risk break-glass reason_code is not in the deterministic allowlist."
                    ),
                    BREAK_GLASS_PROCEDURE_REQUIRED_DENY_CODE,
                    policy_snapshot,
                    risk_score=_policy_case_risk_score(policy_case),
                    cognitive_assessment=policy_case.cognitive_assessment,
                    explanations=_policy_case_explanations(
                        policy_case,
                        "break_glass_reason_code_not_allowed",
                    )
                    + [
                        f"break_glass_reason_code={reason_code}",
                        f"break_glass_profile={','.join(profile_reasons) if profile_reasons else 'none'}",
                    ],
                    break_glass=context,
                ),
                context,
            )

    return (
        None,
        _build_break_glass_context(
            action_intent,
            claims=claims,
            validated=True,
            required=required_reason,
            outcome="validated",
            procedure_id=procedure_id,
            incident_id=incident_id,
            reason_code=reason_code,
            risk_score=risk_score,
            ocps_score=ocps_score,
        ),
    )


def _derive_ttl_seconds(
    payload: Dict[str, Any],
    routing: Dict[str, Any],
    governance: Dict[str, Any],
) -> int:
    hints = routing.get("hints") if isinstance(routing.get("hints"), dict) else {}
    raw_ttl = (
        payload.get("ttl_seconds")
        or hints.get("ttl_seconds")
        or governance.get("ttl_seconds")
        or os.getenv("SEEDCORE_ACTION_INTENT_DEFAULT_TTL_S", "300")
    )
    try:
        ttl = int(raw_ttl)
    except (TypeError, ValueError):
        ttl = 300
    return max(1, ttl)


def _derive_contract_version(payload: Dict[str, Any], governance: Dict[str, Any]) -> str:
    snapshot_id = payload.get("snapshot_id")
    return str(
        governance.get("policy_contract_version")
        or payload.get("policy_contract_version")
        or (f"snapshot:{snapshot_id}" if snapshot_id is not None else "")
        or os.getenv("SEEDCORE_POLICY_CONTRACT_VERSION", "policy:current")
    )


def _pdp_max_intent_age_ms() -> int:
    raw = os.getenv("SEEDCORE_PDP_MAX_INTENT_AGE_MS", "0").strip()
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _pdp_actor_token_required() -> bool:
    return os.getenv("SEEDCORE_PDP_REQUIRE_ACTOR_TOKEN", "").strip().lower() in {"1", "true", "yes", "on"}


def _pdp_actor_token_max_skew_seconds() -> float:
    raw = os.getenv("SEEDCORE_PDP_ACTOR_TOKEN_MAX_SKEW_SECONDS", "1").strip()
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 1.0


def _pdp_break_glass_token_max_skew_seconds() -> float:
    raw = os.getenv("SEEDCORE_PDP_BREAK_GLASS_TOKEN_MAX_SKEW_SECONDS", "1").strip()
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 1.0


def _pdp_break_glass_require_deterministic_procedure() -> bool:
    raw = os.getenv("SEEDCORE_PDP_BREAK_GLASS_REQUIRE_DETERMINISTIC_PROCEDURE", "true").strip()
    return raw.lower() in {"1", "true", "yes", "on"}


def _pdp_break_glass_high_risk_score_threshold() -> float:
    raw = os.getenv("SEEDCORE_PDP_BREAK_GLASS_HIGH_RISK_SCORE", "0.85").strip()
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.85


def _pdp_break_glass_high_ocps_threshold() -> float:
    raw = os.getenv("SEEDCORE_PDP_BREAK_GLASS_OCPS_THRESHOLD", "0.70").strip()
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.70


def _pdp_break_glass_reason_codes() -> set[str]:
    raw = os.getenv(
        "SEEDCORE_PDP_BREAK_GLASS_REASON_CODES",
        "safety_incident,custody_breach,service_continuity,regulatory_hold",
    )
    values = {
        str(item).strip().lower()
        for item in str(raw).split(",")
        if str(item).strip()
    }
    return values


def _extract_ocps_signal(summary: Mapping[str, Any] | None) -> float | None:
    if not isinstance(summary, Mapping):
        return None
    candidates: list[Any] = [
        summary.get("s_drift"),
        summary.get("drift_score"),
        summary.get("ocps_s_t"),
    ]
    ocps_payload = summary.get("ocps")
    if isinstance(ocps_payload, Mapping):
        candidates.extend(
            [
                ocps_payload.get("S_t"),
                ocps_payload.get("s_drift"),
                ocps_payload.get("drift_score"),
            ]
        )

    resolved: float | None = None
    for candidate in candidates:
        if not isinstance(candidate, (int, float)):
            continue
        value = max(0.0, min(1.0, float(candidate)))
        resolved = value if resolved is None else max(resolved, value)
    return resolved


def _break_glass_high_risk_profile(
    *,
    action_intent: ActionIntent,
    policy_case: PolicyCase,
) -> tuple[bool, float | None, float | None, list[str]]:
    reasons: list[str] = []
    risk_score = _policy_case_risk_score(policy_case)
    ocps_score = _extract_ocps_signal(policy_case.telemetry_summary)

    if isinstance(risk_score, (int, float)) and float(risk_score) >= _pdp_break_glass_high_risk_score_threshold():
        reasons.append("risk_score_threshold")
    if isinstance(ocps_score, (int, float)) and float(ocps_score) >= _pdp_break_glass_high_ocps_threshold():
        reasons.append("ocps_threshold")
    if _is_restricted_custody_transfer(action_intent):
        reasons.append("restricted_custody_transfer")

    return bool(reasons), _coerce_risk_score(risk_score), _coerce_risk_score(ocps_score), reasons


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _stable_fallback_entropy(payload: Dict[str, Any]) -> str:
    return _sha256_hex(_canonical_json(payload))[:12]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_iso8601(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _pad_base64(value: str) -> str:
    padding = (-len(value)) % 4
    return value + ("=" * padding)
