from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping, Sequence


def normalize_delegation_ref(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if normalized.startswith("delegation:"):
        normalized = normalized.split(":", 1)[1].strip()
    return normalized or None


def authority_consistency_summary(
    *,
    action_intent: Mapping[str, Any] | None,
    owner_context: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    action_payload = action_intent if isinstance(action_intent, Mapping) else {}
    owner_payload = owner_context if isinstance(owner_context, Mapping) else {}
    principal = action_payload.get("principal") if isinstance(action_payload.get("principal"), Mapping) else {}
    action = action_payload.get("action") if isinstance(action_payload.get("action"), Mapping) else {}
    parameters = action.get("parameters") if isinstance(action.get("parameters"), Mapping) else {}
    gateway = parameters.get("gateway") if isinstance(parameters.get("gateway"), Mapping) else {}
    creator_profile_ref = (
        owner_payload.get("creator_profile_ref")
        if isinstance(owner_payload.get("creator_profile_ref"), Mapping)
        else {}
    )
    trust_preferences_ref = (
        owner_payload.get("trust_preferences_ref")
        if isinstance(owner_payload.get("trust_preferences_ref"), Mapping)
        else {}
    )
    principal_owner_id = str(principal.get("owner_id") or "").strip()
    gateway_owner_id = str(gateway.get("owner_id") or "").strip()
    owner_context_owner_id = str(owner_payload.get("owner_id") or "").strip()
    creator_profile_owner_id = str(creator_profile_ref.get("owner_id") or "").strip()
    trust_preferences_owner_id = str(trust_preferences_ref.get("owner_id") or "").strip()
    owner_id_candidates = [
        candidate
        for candidate in [
            principal_owner_id,
            gateway_owner_id,
            owner_context_owner_id,
            creator_profile_owner_id,
            trust_preferences_owner_id,
        ]
        if candidate
    ]
    issues: list[str] = []
    if len(set(owner_id_candidates)) > 1:
        issues.append("owner_identity_mismatch")

    principal_delegation_ref = normalize_delegation_ref(principal.get("delegation_ref"))
    gateway_delegation_ref = normalize_delegation_ref(gateway.get("delegation_ref"))
    if (
        principal_delegation_ref is not None
        and gateway_delegation_ref is not None
        and principal_delegation_ref != gateway_delegation_ref
    ):
        issues.append("delegation_ref_mismatch")

    summary: Dict[str, Any] = {"ok": not issues, "issues": issues}
    digest = hashlib.sha256(
        json.dumps(summary, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    summary["hash"] = f"sha256:{digest}"
    return summary


def operator_actions_for_authority_issues(issues: Sequence[str]) -> list[Dict[str, Any]]:
    actions: list[Dict[str, Any]] = []
    issue_set = {str(item).strip() for item in issues if str(item).strip()}
    if "owner_identity_mismatch" in issue_set:
        actions.append(
            {
                "code": "reconcile_owner_identity",
                "priority": "high",
                "summary": "Reconcile owner DID bindings across principal, gateway, and owner context.",
            }
        )
    if "delegation_ref_mismatch" in issue_set:
        actions.append(
            {
                "code": "reconcile_delegation_ref",
                "priority": "high",
                "summary": "Reconcile delegation reference bindings across principal and gateway.",
            }
        )
    mapped = {"owner_identity_mismatch", "delegation_ref_mismatch"}
    for issue in sorted(issue_set):
        if issue in mapped:
            continue
        actions.append(
            {
                "code": f"review_{issue}",
                "priority": "medium",
                "summary": f"Review authority consistency issue: {issue}.",
            }
        )
    return actions
