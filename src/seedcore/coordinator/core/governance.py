from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Mapping

from seedcore.models.action_intent import (
    ActionIntent,
    ExecutionToken,
    IntentAction,
    IntentPrincipal,
    IntentResource,
    PolicyCase,
    PolicyCaseAssessment,
    PolicyDecision,
    SecurityContract,
    TwinSnapshot,
)
from seedcore.models.task_payload import TaskPayload


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
MISSING_MANDATORY_EVIDENCE_DENY_CODE = "missing_mandatory_evidence"
COGNITIVE_DENY_CODE = "cognitive_policy_denied"
POLICY_ESCALATION_CODE = "policy_escalation_required"
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
    routing = params.get("routing") if isinstance(params.get("routing"), dict) else {}
    interaction = params.get("interaction") if isinstance(params.get("interaction"), dict) else {}
    multimodal = params.get("multimodal") if isinstance(params.get("multimodal"), dict) else {}
    governance = params.get("governance") if isinstance(params.get("governance"), dict) else {}
    resource = params.get("resource") if isinstance(params.get("resource"), dict) else {}
    executor = params.get("executor") if isinstance(params.get("executor"), dict) else {}
    cognitive = params.get("cognitive") if isinstance(params.get("cognitive"), dict) else {}
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
        ),
        action=IntentAction(
            type=action_type,
            parameters=action_parameters,
            security_contract=security_contract,
        ),
        resource=IntentResource(
            asset_id=str(asset_id),
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

    def _snapshot(
        twin_key: str,
        twin_id: str,
        *,
        identity: Mapping[str, Any] | None = None,
        delegation: Mapping[str, Any] | None = None,
        risk: Mapping[str, Any] | None = None,
        custody: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any] | None = None,
        telemetry: Mapping[str, Any] | None = None,
    ) -> TwinSnapshot:
        source = twin_inputs.get(twin_key) if isinstance(twin_inputs.get(twin_key), dict) else {}
        freshness = source.get("freshness") if isinstance(source.get("freshness"), dict) else {}
        return TwinSnapshot(
            twin_type=twin_key,
            twin_id=str(source.get("twin_id") or twin_id),
            freshness={
                "status": source.get("freshness_status") or freshness.get("status") or "unknown",
                "observed_at": source.get("observed_at") or freshness.get("observed_at"),
                "max_age_seconds": source.get("max_age_seconds") or freshness.get("max_age_seconds"),
            },
            identity=dict(identity or source.get("identity") or {}),
            delegation=dict(delegation or source.get("delegation") or {}),
            risk=dict(risk or source.get("risk") or {}),
            custody=dict(custody or source.get("custody") or {}),
            provenance=dict(provenance or source.get("provenance") or {}),
            telemetry=dict(telemetry or source.get("telemetry") or {}),
            pending_exceptions=list(source.get("pending_exceptions") or []),
            lockouts=list(source.get("lockouts") or []),
            conflicts=list(source.get("conflicts") or []),
        )

    target_zone = intent.resource.target_zone or multimodal.get("location_context")
    snapshots = {
        "owner": _snapshot(
            "owner",
            f"owner:{intent.resource.asset_id}",
            identity={"asset_id": intent.resource.asset_id},
            delegation={"principal_agent_id": intent.principal.agent_id},
        ),
        "assistant": _snapshot(
            "assistant",
            f"assistant:{intent.principal.agent_id}",
            identity={"agent_id": intent.principal.agent_id},
            delegation={"role_profile": intent.principal.role_profile},
        ),
        "asset": _snapshot(
            "asset",
            f"asset:{intent.resource.asset_id}",
            custody={"asset_id": intent.resource.asset_id, "target_zone": target_zone},
            provenance={"provenance_hash": intent.resource.provenance_hash},
        ),
        "edge": _snapshot(
            "edge",
            f"edge:{target_zone or 'unknown'}",
            telemetry={"target_zone": target_zone},
        ),
        "transaction": _snapshot(
            "transaction",
            f"transaction:{intent.intent_id}",
            custody={"intent_id": intent.intent_id},
            telemetry={"session_token": intent.principal.session_token},
        ),
    }
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
    policy_case_payload = policy_case.model_dump(mode="json")
    policy_decision_payload = policy_decision.model_dump(mode="json")
    policy_snapshot = (
        policy_decision.policy_snapshot
        or policy_case.policy_snapshot
        or (
            policy_case.action_intent.action.security_contract.version
            if policy_case.action_intent.action.security_contract.version
            else None
        )
    )
    proof_type = "hmac_sha256"
    if isinstance(execution_token, dict):
        token_proof = execution_token.get("proof_type")
        if isinstance(token_proof, str) and token_proof.strip():
            proof_type = token_proof.strip()

    return {
        "receipt_id": str(uuid.uuid4()),
        "issued_at": _isoformat(_utcnow()),
        "policy_snapshot": str(policy_snapshot) if policy_snapshot is not None else None,
        "policy_case_hash": _sha256_hex(_canonical_json(policy_case_payload)),
        "policy_decision_hash": _sha256_hex(_canonical_json(policy_decision_payload)),
        "execution_token": execution_token,
        "signer": {
            "signer_id": os.getenv("SEEDCORE_PDP_SIGNER_ID", "seedcore-pdp"),
            "signer_type": "policy_decision_point",
            "key_id": os.getenv("SEEDCORE_POLICY_SIGNING_KEY_ID"),
            "public_key": None,
            "proof_type": proof_type,
        },
    }


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

    for twin in twins.values():
        if bool(twin.delegation.get("revoked")):
            return _deny_decision(
                "Delegation is revoked for this action.",
                REVOKED_DELEGATION_DENY_CODE,
                policy_case.policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case, floor=0.8),
                cognitive_assessment=policy_case.cognitive_assessment,
                explanations=[f"revoked_twin={twin.twin_type}:{twin.twin_id}"],
            )
        if twin.lockouts or twin.pending_exceptions or bool(twin.custody.get("quarantined")):
            return _deny_decision(
                "Digital twin state blocks execution.",
                FORBIDDEN_TWIN_STATE_DENY_CODE,
                policy_case.policy_snapshot,
                risk_score=_policy_case_risk_score(policy_case, floor=0.75),
                cognitive_assessment=policy_case.cognitive_assessment,
                explanations=[
                    f"blocked_twin={twin.twin_type}:{twin.twin_id}",
                    *[f"lockout={item}" for item in twin.lockouts],
                    *[f"pending_exception={item}" for item in twin.pending_exceptions],
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
        payload.setdefault("twin_type", key)
        payload.setdefault("twin_id", str(payload.get("twin_id") or key))
        return TwinSnapshot(**payload)
    return TwinSnapshot(twin_type=key, twin_id=str(value))


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
