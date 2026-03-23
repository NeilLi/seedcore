from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Mapping
from urllib.parse import quote

from seedcore.models.action_intent import (
    ActionIntent,
    AuthorityLevel,
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
) -> PolicyCase:
    action_intent = task if isinstance(task, ActionIntent) else build_action_intent(task)
    resolved_snapshot = (
        policy_snapshot
        or action_intent.action.security_contract.version
    )
    resolved_twins = dict(relevant_twin_snapshot or {}) or build_twin_snapshot(task)
    action_intent = apply_twin_overrides_to_action_intent(action_intent, resolved_twins)
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
    approved_source_registrations: Mapping[str, str | None] | None = None,
    relevant_twin_snapshot: Mapping[str, Any] | None = None,
    telemetry_summary: Mapping[str, Any] | None = None,
    cognitive_assessment: Mapping[str, Any] | PolicyCaseAssessment | None = None,
    evidence_summary: Mapping[str, Any] | None = None,
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
        )
    )
    action_intent = policy_case.action_intent
    policy_snapshot = policy_case.policy_snapshot
    now = _utcnow()
    try:
        issued_at = _parse_iso8601(action_intent.timestamp)
        valid_until = _parse_iso8601(action_intent.valid_until)
    except ValueError:
        return _deny_decision(
            "ActionIntent contains invalid timestamps.",
            "invalid_timestamp",
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )

    if valid_until <= issued_at:
        return _deny_decision(
            "ActionIntent TTL is non-positive.",
            "expired_intent",
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )
    if valid_until <= now:
        return _deny_decision(
            "ActionIntent TTL is expired.",
            "expired_intent",
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )
    intent_age_ms = (now - issued_at).total_seconds() * 1000.0
    max_intent_age_ms = _pdp_max_intent_age_ms()
    if max_intent_age_ms > 0 and intent_age_ms > max_intent_age_ms:
        return _deny_decision(
            f"ActionIntent is older than the permitted freshness window ({max_intent_age_ms}ms).",
            STALE_INTENT_DENY_CODE,
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )

    if not action_intent.principal.agent_id.strip():
        return _deny_decision(
            "ActionIntent is missing principal.agent_id.",
            "missing_principal",
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )

    if not action_intent.principal.role_profile.strip():
        return _deny_decision(
            "ActionIntent is missing principal.role_profile.",
            "missing_role_profile",
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )

    if not action_intent.action.security_contract.version.strip():
        return _deny_decision(
            "ActionIntent is missing action.security_contract.version.",
            "missing_contract_version",
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )

    actor_token_violation = _evaluate_actor_token_policy(
        action_intent=action_intent,
        now=now,
        policy_snapshot=policy_snapshot,
        policy_case=policy_case,
    )
    if actor_token_violation is not None:
        return actor_token_violation

    registration_deny_code = _source_registration_deny_code(
        action_intent,
        policy_case.approved_source_registrations,
    )
    if registration_deny_code is not None:
        return _deny_decision(
            _source_registration_deny_reason(registration_deny_code),
            registration_deny_code,
            policy_snapshot,
            risk_score=_policy_case_risk_score(policy_case),
            cognitive_assessment=policy_case.cognitive_assessment,
        )

    twin_violation = _evaluate_twin_policy(policy_case)
    if twin_violation is not None:
        return twin_violation

    cognitive_violation = _evaluate_cognitive_policy(policy_case)
    if cognitive_violation is not None:
        return cognitive_violation

    token_valid_until = min(
        valid_until,
        now + timedelta(seconds=_execution_token_ttl_seconds()),
    )

    token_payload = {
        "token_id": str(uuid.uuid4()),
        "intent_id": action_intent.intent_id,
        "issued_at": _isoformat(now),
        "valid_until": _isoformat(token_valid_until),
        "contract_version": action_intent.action.security_contract.version,
        "constraints": _build_execution_constraints(action_intent),
    }
    signature = _sign_payload(token_payload)
    token = ExecutionToken(signature=signature, **token_payload)
    allow_reason = (
        EXPLICIT_ALLOW_RULE
        if _requires_approved_source_registration(action_intent)
        else "allowed"
    )
    return PolicyDecision(
        allowed=True,
        execution_token=token,
        reason=allow_reason,
        policy_snapshot=policy_snapshot or action_intent.action.security_contract.version,
        disposition="allow",
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
    )


def build_governance_context(
    task: TaskPayload | Mapping[str, Any] | Dict[str, Any],
    *,
    approved_source_registrations: Mapping[str, str | None] | None = None,
    relevant_twin_snapshot: Mapping[str, Any] | None = None,
    telemetry_summary: Mapping[str, Any] | None = None,
    cognitive_assessment: Mapping[str, Any] | PolicyCaseAssessment | None = None,
    evidence_summary: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    policy_case = prepare_policy_case(
        task,
        approved_source_registrations=approved_source_registrations,
        relevant_twin_snapshot=relevant_twin_snapshot,
        telemetry_summary=telemetry_summary,
        cognitive_assessment=cognitive_assessment,
        evidence_summary=evidence_summary,
    )
    intent = policy_case.action_intent
    decision = evaluate_intent(policy_case)
    policy_receipt = build_policy_receipt(
        policy_case=policy_case,
        policy_decision=decision,
    )
    context = {
        "action_intent": intent.model_dump(mode="json"),
        "policy_case": policy_case.model_dump(mode="json"),
        "policy_decision": decision.model_dump(mode="json"),
        "policy_receipt": policy_receipt,
    }
    if decision.execution_token is not None:
        context["execution_token"] = decision.execution_token.model_dump(mode="json")
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
    )


def _escalate_decision(
    reason: str,
    policy_snapshot: str | None,
    *,
    cognitive_assessment: PolicyCaseAssessment | None = None,
    explanations: list[str] | None = None,
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


def _derive_actor_token_claims(token: str) -> Dict[str, Any]:
    try:
        prefix, payload_segment, signature_segment = token.split(".", 2)
        if prefix != "seedcore_hmac_v1":
            raise ValueError("unsupported_actor_token_scheme")
        signing_input = f"{prefix}.{payload_segment}".encode("utf-8")
        secret = os.getenv("SEEDCORE_PDP_ACTOR_TOKEN_SECRET", "").strip()
        if not secret:
            raise ValueError("actor_token_secret_unconfigured")
        expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(_pad_base64(signature_segment))
        if not hmac.compare_digest(actual, expected):
            raise ValueError("actor_token_signature_invalid")
        payload_bytes = base64.urlsafe_b64decode(_pad_base64(payload_segment))
        claims = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(claims, dict):
            raise ValueError("actor_token_claims_invalid")
        return claims
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("actor_token_malformed") from exc


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


def _sign_payload(payload: Dict[str, Any]) -> str:
    secret = os.getenv("SEEDCORE_PDP_SIGNING_SECRET", "seedcore-dev-signing-secret")
    return hmac.new(
        secret.encode("utf-8"),
        _canonical_json(payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


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
