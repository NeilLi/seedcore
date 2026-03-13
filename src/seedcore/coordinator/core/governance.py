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
    PolicyDecision,
    SecurityContract,
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
EXECUTION_TOKEN_CONSTRAINT_KEYS = (
    "action_type",
    "target_zone",
    "asset_id",
    "principal_agent_id",
    "source_registration_id",
    "registration_decision_id",
)


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


def evaluate_intent(
    action_intent: ActionIntent,
    *,
    policy_snapshot: str | None = None,
    approved_source_registrations: Mapping[str, str | None] | None = None,
) -> PolicyDecision:
    now = _utcnow()
    try:
        issued_at = _parse_iso8601(action_intent.timestamp)
        valid_until = _parse_iso8601(action_intent.valid_until)
    except ValueError:
        return PolicyDecision(
            allowed=False,
            reason="ActionIntent contains invalid timestamps.",
            deny_code="invalid_timestamp",
            policy_snapshot=policy_snapshot,
        )

    if valid_until <= issued_at:
        return PolicyDecision(
            allowed=False,
            reason="ActionIntent TTL is non-positive.",
            deny_code="expired_intent",
            policy_snapshot=policy_snapshot,
        )
    if valid_until <= now:
        return PolicyDecision(
            allowed=False,
            reason="ActionIntent TTL is expired.",
            deny_code="expired_intent",
            policy_snapshot=policy_snapshot,
        )

    if not action_intent.principal.agent_id.strip():
        return PolicyDecision(
            allowed=False,
            reason="ActionIntent is missing principal.agent_id.",
            deny_code="missing_principal",
            policy_snapshot=policy_snapshot,
        )

    if not action_intent.principal.role_profile.strip():
        return PolicyDecision(
            allowed=False,
            reason="ActionIntent is missing principal.role_profile.",
            deny_code="missing_role_profile",
            policy_snapshot=policy_snapshot,
        )

    if not action_intent.action.security_contract.version.strip():
        return PolicyDecision(
            allowed=False,
            reason="ActionIntent is missing action.security_contract.version.",
            deny_code="missing_contract_version",
            policy_snapshot=policy_snapshot,
        )

    registration_deny_code = _source_registration_deny_code(
        action_intent,
        approved_source_registrations or {},
    )
    if registration_deny_code is not None:
        return PolicyDecision(
            allowed=False,
            reason=_source_registration_deny_reason(registration_deny_code),
            deny_code=registration_deny_code,
            policy_snapshot=policy_snapshot,
        )

    token_payload = {
        "token_id": str(uuid.uuid4()),
        "intent_id": action_intent.intent_id,
        "issued_at": _isoformat(now),
        "valid_until": action_intent.valid_until,
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
    )


def build_governance_context(
    task: TaskPayload | Mapping[str, Any] | Dict[str, Any],
    *,
    approved_source_registrations: Mapping[str, str | None] | None = None,
) -> Dict[str, Any]:
    intent = build_action_intent(task)
    decision = evaluate_intent(
        intent,
        policy_snapshot=intent.action.security_contract.version,
        approved_source_registrations=approved_source_registrations,
    )
    context = {
        "action_intent": intent.model_dump(mode="json"),
        "policy_decision": decision.model_dump(mode="json"),
    }
    if decision.execution_token is not None:
        context["execution_token"] = decision.execution_token.model_dump(mode="json")
    return context


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


def _build_execution_constraints(action_intent: ActionIntent) -> Dict[str, Any]:
    values = {
        "action_type": action_intent.action.type,
        "target_zone": action_intent.resource.target_zone,
        "asset_id": action_intent.resource.asset_id,
        "principal_agent_id": action_intent.principal.agent_id,
        "source_registration_id": action_intent.resource.source_registration_id,
        "registration_decision_id": action_intent.resource.registration_decision_id,
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
