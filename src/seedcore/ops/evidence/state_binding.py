from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping, Optional, Sequence


def _to_mapping(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    return {}


def _norm_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _norm_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _norm_str_list(values: Any) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return []
    normalized: list[str] = []
    for item in values:
        value = _norm_str(item)
        if value is None or value in normalized:
            continue
        normalized.append(value)
    return normalized


def _compact_dict(payload: Mapping[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and len(value) == 0:
            continue
        compact[str(key)] = value
    return compact


def build_authority_state_binding_material(
    *,
    action_intent: Any = None,
    approval_context: Mapping[str, Any] | None = None,
    governed_receipt: Mapping[str, Any] | None = None,
    authz_graph: Mapping[str, Any] | None = None,
    telemetry_summary: Mapping[str, Any] | None = None,
    relevant_twin_snapshot: Mapping[str, Any] | None = None,
    evidence_refs: Sequence[Any] | None = None,
) -> Dict[str, Any]:
    intent = _to_mapping(action_intent)
    action = intent.get("action") if isinstance(intent.get("action"), Mapping) else {}
    resource = intent.get("resource") if isinstance(intent.get("resource"), Mapping) else {}
    parameters = action.get("parameters") if isinstance(action.get("parameters"), Mapping) else {}
    transfer_context = parameters.get("transfer_context") if isinstance(parameters.get("transfer_context"), Mapping) else {}

    approval = dict(approval_context or {})
    receipt = dict(governed_receipt or {})
    graph = dict(authz_graph or {})
    telemetry = dict(telemetry_summary or {})
    twin_snapshot = dict(relevant_twin_snapshot or {})
    twin_asset = twin_snapshot.get("asset") if isinstance(twin_snapshot.get("asset"), Mapping) else {}
    twin_asset_telemetry = twin_asset.get("telemetry") if isinstance(twin_asset.get("telemetry"), Mapping) else {}

    merged_evidence_refs = _norm_str_list(evidence_refs)
    merged_evidence_refs.extend(
        item for item in _norm_str_list(telemetry.get("evidence_refs")) if item not in merged_evidence_refs
    )
    merged_evidence_refs.extend(
        item for item in _norm_str_list(receipt.get("evidence_refs")) if item not in merged_evidence_refs
    )

    approval_binding = _compact_dict(
        {
            "approval_envelope_id": _norm_str(
                approval.get("approval_envelope_id")
                or receipt.get("approval_envelope_id")
                or graph.get("approval_envelope_id")
            ),
            "approval_envelope_version": _norm_int(
                approval.get("approval_envelope_version")
                or approval.get("observed_version")
                or receipt.get("approval_envelope_version")
                or graph.get("approval_envelope_version")
            ),
            "approval_binding_hash": _norm_str(
                approval.get("approval_binding_hash")
                or receipt.get("approval_binding_hash")
                or graph.get("approval_binding_hash")
            ),
            "approval_transition_head": _norm_str(
                approval.get("approval_transition_head")
                or receipt.get("approval_transition_head")
                or graph.get("approval_transition_head")
            ),
        }
    )

    custody_binding = _compact_dict(
        {
            "asset_ref": _norm_str(resource.get("asset_id") or receipt.get("asset_ref") or graph.get("asset_ref")),
            "resource_ref": _norm_str(resource.get("resource_uri") or receipt.get("resource_ref") or graph.get("resource_ref")),
            "current_custodian": _norm_str(graph.get("current_custodian")),
            "expected_current_custodian": _norm_str(
                transfer_context.get("expected_current_custodian")
                or transfer_context.get("from_custodian_ref")
                or receipt.get("expected_current_custodian")
            ),
            "next_custodian": _norm_str(
                transfer_context.get("next_custodian")
                or transfer_context.get("to_custodian_ref")
                or receipt.get("next_custodian")
            ),
            "from_zone": _norm_str(transfer_context.get("from_zone") or receipt.get("from_zone")),
            "to_zone": _norm_str(
                transfer_context.get("to_zone")
                or resource.get("target_zone")
                or receipt.get("target_zone")
            ),
        }
    )

    telemetry_binding = _compact_dict(
        {
            "observed_at": _norm_str(
                telemetry.get("observed_at")
                or twin_asset_telemetry.get("observed_at")
                or intent.get("timestamp")
            ),
            "freshness_seconds": _norm_int(telemetry.get("freshness_seconds")),
            "max_allowed_age_seconds": _norm_int(telemetry.get("max_allowed_age_seconds")),
            "evidence_refs": merged_evidence_refs,
        }
    )

    twin_binding = _compact_dict(
        {
            "twin_ref": _norm_str(
                receipt.get("twin_ref")
                or twin_asset.get("twin_id")
                or twin_asset.get("id")
            ),
            "twin_revision_stage": _norm_str(twin_asset.get("revision_stage")),
            "twin_lifecycle_state": _norm_str(twin_asset.get("lifecycle_state")),
        }
    )

    identity_binding = _compact_dict(
        {
            "intent_id": _norm_str(intent.get("intent_id")),
            "principal_ref": _norm_str(
                receipt.get("principal_ref")
                or (
                    f"principal:{_norm_str((intent.get('principal') or {}).get('agent_id'))}"
                    if isinstance(intent.get("principal"), Mapping) and _norm_str((intent.get("principal") or {}).get("agent_id"))
                    else None
                )
            ),
            "operation": _norm_str(
                receipt.get("operation")
                or (action.get("operation") if isinstance(action.get("operation"), str) else action.get("type"))
            ),
            "policy_snapshot_hash": _norm_str(
                receipt.get("snapshot_hash")
                or graph.get("snapshot_hash")
            ),
        }
    )

    material = _compact_dict(
        {
            "identity": identity_binding,
            "approval": approval_binding,
            "custody": custody_binding,
            "telemetry": telemetry_binding,
            "twin": twin_binding,
        }
    )
    return material


def compute_authority_state_binding_hash(
    *,
    action_intent: Any = None,
    approval_context: Mapping[str, Any] | None = None,
    governed_receipt: Mapping[str, Any] | None = None,
    authz_graph: Mapping[str, Any] | None = None,
    telemetry_summary: Mapping[str, Any] | None = None,
    relevant_twin_snapshot: Mapping[str, Any] | None = None,
    evidence_refs: Sequence[Any] | None = None,
) -> Optional[str]:
    material = build_authority_state_binding_material(
        action_intent=action_intent,
        approval_context=approval_context,
        governed_receipt=governed_receipt,
        authz_graph=authz_graph,
        telemetry_summary=telemetry_summary,
        relevant_twin_snapshot=relevant_twin_snapshot,
        evidence_refs=evidence_refs,
    )
    if not material:
        return None
    payload = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
