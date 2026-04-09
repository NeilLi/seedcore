from __future__ import annotations

import os
from typing import Any, List, Mapping, Optional


RCT_WORKFLOW_TYPE = "restricted_custody_transfer"
CONTROL_MODE = "control"

_ALLOWED_TRUST_ANCHORS = {"tpm2", "kms", "vtpm"}


def _truthy_env(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def is_control_mode(mode: Optional[str] = None) -> bool:
    resolved = _optional_str(mode) or _optional_str(os.getenv("PKG_MODE")) or CONTROL_MODE
    return str(resolved).strip().lower() == CONTROL_MODE


def is_restricted_custody_transfer_workflow(workflow_type: Any) -> bool:
    return (_optional_str(workflow_type) or "").lower() == RCT_WORKFLOW_TYPE


def is_restricted_custody_transfer_record(record: Mapping[str, Any]) -> bool:
    action_intent = record.get("action_intent") if isinstance(record.get("action_intent"), Mapping) else {}
    action = action_intent.get("action") if isinstance(action_intent.get("action"), Mapping) else {}
    params = action.get("parameters") if isinstance(action.get("parameters"), Mapping) else {}
    gateway = params.get("gateway") if isinstance(params.get("gateway"), Mapping) else {}
    gateway_workflow = _optional_str(gateway.get("workflow_type"))
    if is_restricted_custody_transfer_workflow(gateway_workflow):
        return True

    policy_case = record.get("policy_case") if isinstance(record.get("policy_case"), Mapping) else {}
    workflow_hints = (
        policy_case.get("workflow_hints")
        if isinstance(policy_case.get("workflow_hints"), Mapping)
        else {}
    )
    hints_workflow = _optional_str(workflow_hints.get("workflow_type"))
    if is_restricted_custody_transfer_workflow(hints_workflow):
        return True

    reasons = policy_case.get("reasons")
    if isinstance(reasons, list) and any((_optional_str(item) or "").lower() == RCT_WORKFLOW_TYPE for item in reasons):
        return True
    return False


def rct_control_fail_closed_env_issues() -> List[str]:
    issues: List[str] = []
    required_flags = (
        "SEEDCORE_RCT_REPLAY_STRICT_TRIPLE_HASH",
        "SEEDCORE_PKG_RCT_ACTIVATION_ENFORCE",
        "SEEDCORE_PKG_RCT_ACTIVATION_PREFLIGHT",
        "SEEDCORE_PKG_RCT_PUBLISH_VALIDATE",
    )
    for name in required_flags:
        if not _truthy_env(name):
            issues.append(f"missing_required_flag:{name}")

    if _truthy_env("SEEDCORE_TPM2_ALLOW_SOFTWARE_FALLBACK"):
        issues.append("invalid_trust_posture:SEEDCORE_TPM2_ALLOW_SOFTWARE_FALLBACK")

    anchor = (_optional_str(os.getenv("SEEDCORE_RECEIPT_REQUIRED_TRUST_ANCHOR")) or "").lower()
    if anchor and anchor not in _ALLOWED_TRUST_ANCHORS:
        issues.append("invalid_trust_posture:SEEDCORE_RECEIPT_REQUIRED_TRUST_ANCHOR")
    return issues


def rct_control_fail_closed_issues(
    *,
    record: Mapping[str, Any] | None = None,
    workflow_type: Any = None,
    mode: Optional[str] = None,
) -> List[str]:
    if not is_control_mode(mode):
        return []
    if record is not None:
        if not is_restricted_custody_transfer_record(record):
            return []
    elif not is_restricted_custody_transfer_workflow(workflow_type):
        return []
    return rct_control_fail_closed_env_issues()
