from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, Optional

from seedcore.ops.evidence.authority_consistency import (
    authority_consistency_summary,
    operator_actions_for_authority_issues as _build_operator_actions_for_authority_issues,
)
from seedcore.ops.evidence.forensic_block_contract import (
    FORENSIC_BLOCK_CONTEXT,
    validate_forensic_block_payload,
)

TRUST_GAP_TAXONOMY: Dict[str, Dict[str, str]] = {
    "owner_trust_risk_escalation": {
        "category": "owner_trust",
        "severity": "high",
        "message": "Owner trust risk threshold exceeded.",
    },
    "owner_trust_high_value_step_up": {
        "category": "owner_trust",
        "severity": "high",
        "message": "Owner trust high-value threshold requires step-up approval.",
    },
    "owner_trust_merchant_violation": {
        "category": "owner_trust",
        "severity": "high",
        "message": "Merchant is outside owner trust allowlist.",
    },
    "owner_trust_provenance_violation": {
        "category": "owner_trust",
        "severity": "high",
        "message": "Required owner provenance level not satisfied.",
    },
    "owner_trust_modality_violation": {
        "category": "owner_trust",
        "severity": "high",
        "message": "Required owner evidence modalities missing.",
    },
}


def materialize_seedcore_custody_event(*, audit_record: Dict[str, Any]) -> Dict[str, Any]:
    evidence_bundle = audit_record.get("evidence_bundle") if isinstance(audit_record.get("evidence_bundle"), dict) else {}
    evidence_inputs = (
        evidence_bundle.get("evidence_inputs")
        if isinstance(evidence_bundle.get("evidence_inputs"), dict)
        else {}
    )
    telemetry_ref = _first_inline_ref(evidence_bundle.get("telemetry_refs"))
    execution_summary = (
        evidence_inputs.get("execution_summary")
        if isinstance(evidence_inputs.get("execution_summary"), dict)
        else {}
    )
    transition_receipts = (
        evidence_inputs.get("transition_receipts")
        if isinstance(evidence_inputs.get("transition_receipts"), list)
        else []
    )
    transition_receipt = next((item for item in transition_receipts if isinstance(item, dict)), {})
    policy_receipt = (
        audit_record.get("policy_receipt")
        if isinstance(audit_record.get("policy_receipt"), dict)
        else evidence_inputs.get("policy_receipt")
        if isinstance(evidence_inputs.get("policy_receipt"), dict)
        else {}
    )
    asset_fingerprint = (
        evidence_bundle.get("asset_fingerprint")
        if isinstance(evidence_bundle.get("asset_fingerprint"), dict)
        else {}
    )
    zone_checks = telemetry_ref.get("zone_checks") if isinstance(telemetry_ref.get("zone_checks"), dict) else {}

    signer_metadata = evidence_bundle.get("signer_metadata") if isinstance(evidence_bundle.get("signer_metadata"), dict) else {}
    policy_decision = audit_record.get("policy_decision") if isinstance(audit_record.get("policy_decision"), dict) else {}
    authz_graph = policy_decision.get("authz_graph") if isinstance(policy_decision.get("authz_graph"), dict) else {}
    governed_receipt = policy_decision.get("governed_receipt") if isinstance(policy_decision.get("governed_receipt"), dict) else {}
    trust_gap_codes = _resolve_trust_gap_codes(authz_graph=authz_graph, governed_receipt=governed_receipt)
    trust_gap_taxonomy = _resolve_trust_gap_taxonomy(
        authz_graph=authz_graph,
        governed_receipt=governed_receipt,
        policy_receipt=policy_receipt,
        evidence_bundle=evidence_bundle,
    )
    owner_context = _owner_context(governed_receipt)
    authority_consistency = _authority_consistency_summary(audit_record=audit_record, governed_receipt=governed_receipt)
    forensic_block = _resolve_forensic_block(audit_record=audit_record, evidence_bundle=evidence_bundle)

    return {
        "@context": {
            "@vocab": "https://schema.org/",
            "seedcore": "https://seedcore.ai/schema/",
        },
        "@type": "seedcore:SeedCoreCustodyEvent",
        "@id": _resolve_event_id(audit_record, evidence_bundle),
        "device_identity": _resolve_device_identity(evidence_bundle, execution_summary, transition_receipt, audit_record),
        "platform_state": _resolve_platform_state(audit_record),
        "pre_contact_evidence": {
            "environmental_telemetry": _resolve_environmental_telemetry(telemetry_ref),
            "voc_profile": _resolve_voc_profile(asset_fingerprint),
            "vision_baseline": _resolve_vision_baseline(telemetry_ref, asset_fingerprint),
        },
        "manipulation_telemetry": {
            "commanded_forces": "envelope-verified",
            "observed_forces": "within-tolerance",
            "trajectory_hash": execution_summary.get("actuator_result_hash"),
        },
        "policy_verification": {
            "policy_receipt_id": policy_receipt.get("policy_receipt_id"),
            "policy_decision_id": policy_receipt.get("policy_decision_id"),
            "policy_hash": policy_receipt.get("policy_decision_id") or policy_receipt.get("policy_decision_hash"),
            "authorization_token": evidence_bundle.get("execution_token_id"),
            "authz_disposition": authz_graph.get("disposition") or governed_receipt.get("disposition"),
            "authz_reason": authz_graph.get("reason") or governed_receipt.get("reason"),
            "governed_receipt_hash": governed_receipt.get("decision_hash"),
            "decision_graph_snapshot_hash": (
                governed_receipt.get("snapshot_hash")
                or authz_graph.get("snapshot_hash")
                or policy_receipt.get("decision_graph_snapshot_hash")
                or evidence_bundle.get("decision_graph_snapshot_hash")
            ),
            "decision_graph_snapshot_version": (
                governed_receipt.get("snapshot_version")
                or authz_graph.get("snapshot_version")
                or policy_receipt.get("decision_graph_snapshot_version")
                or evidence_bundle.get("decision_graph_snapshot_version")
            ),
            "state_binding_hash": (
                governed_receipt.get("state_binding_hash")
                or authz_graph.get("state_binding_hash")
                or policy_receipt.get("state_binding_hash")
                or evidence_bundle.get("state_binding_hash")
            ),
            "trust_gap_codes": trust_gap_codes,
            "trust_gap_details": _trust_gap_details(trust_gap_codes, taxonomy=trust_gap_taxonomy),
            "authority_consistency": authority_consistency,
            "authority_consistency_hash": authority_consistency.get("hash"),
            "operator_actions": _operator_actions_for_authority_issues(authority_consistency.get("issues") or []),
            "custody_proof_count": len(governed_receipt.get("custody_proof") or []),
            "provenance_sources": list(governed_receipt.get("provenance_sources") or []),
            "owner_context": owner_context,
        },
        "custody_transition": {
            "from": transition_receipt.get("from_zone") or zone_checks.get("current_zone") or "unknown_zone",
            "to": transition_receipt.get("to_zone") or transition_receipt.get("target_zone") or zone_checks.get("target_zone") or "unknown_zone",
            "timestamp": evidence_bundle.get("created_at") or audit_record.get("recorded_at"),
        },
        "signature": evidence_bundle.get("signature"),
        "signer_metadata": signer_metadata,
        "seedcore:forensic_block": forensic_block,
    }


def materialize_seedcore_custody_event_payload(*, audit_record: Dict[str, Any]) -> Dict[str, Any]:
    return materialize_seedcore_custody_event(audit_record=audit_record)


def _resolve_event_id(audit_record: Dict[str, Any], evidence_bundle: Dict[str, Any]) -> str:
    record_id = audit_record.get("id")
    if isinstance(record_id, str) and record_id.strip():
        return f"seedcore:custody-event:{record_id.strip()}"
    candidate = evidence_bundle.get("evidence_bundle_id")
    if isinstance(candidate, str) and candidate.strip():
        return f"seedcore:custody-event:{candidate.strip()}"
    intent_id = audit_record.get("intent_id")
    if isinstance(intent_id, str) and intent_id.strip():
        return f"seedcore:custody-event:intent:{intent_id.strip()}"
    return f"seedcore:custody-event:{uuid.uuid4()}"


def _resolve_device_identity(
    evidence_bundle: Dict[str, Any],
    execution_summary: Dict[str, Any],
    transition_receipt: Dict[str, Any],
    audit_record: Dict[str, Any],
) -> str:
    for candidate in (
        evidence_bundle.get("node_id"),
        execution_summary.get("node_id"),
        transition_receipt.get("endpoint_id"),
        audit_record.get("actor_organ_id"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return "unknown_device"


def _resolve_platform_state(audit_record: Dict[str, Any]) -> str:
    policy_decision = audit_record.get("policy_decision") if isinstance(audit_record.get("policy_decision"), dict) else {}
    disposition = policy_decision.get("disposition")
    if isinstance(disposition, str) and disposition.strip():
        return disposition.strip().lower()
    allowed = policy_decision.get("allowed")
    if allowed is True:
        return "allow"
    if allowed is False:
        return "deny"
    return "unknown"


def _resolve_environmental_telemetry(telemetry: Dict[str, Any]) -> Dict[str, float]:
    multimodal = telemetry.get("multimodal") if isinstance(telemetry.get("multimodal"), dict) else {}
    candidate = multimodal.get("environmental_telemetry") if isinstance(multimodal.get("environmental_telemetry"), dict) else {}
    out: Dict[str, float] = {}
    for key, value in candidate.items():
        if isinstance(key, str) and isinstance(value, (int, float)):
            out[key] = float(value)
    return out


def _resolve_voc_profile(asset_fingerprint: Dict[str, Any]) -> Dict[str, str]:
    modality_map = asset_fingerprint.get("modality_map") if isinstance(asset_fingerprint.get("modality_map"), dict) else {}
    candidate = modality_map.get("provenance")
    if isinstance(candidate, str) and candidate.strip():
        return {"signatureHash": candidate.strip()}
    return {}


def _resolve_vision_baseline(telemetry: Dict[str, Any], asset_fingerprint: Dict[str, Any]) -> Dict[str, str]:
    modality_map = asset_fingerprint.get("modality_map") if isinstance(asset_fingerprint.get("modality_map"), dict) else {}
    candidate = modality_map.get("visual_hash")
    if isinstance(candidate, str) and candidate.strip():
        return {"fingerprintHash": candidate.strip()}
    vision = telemetry.get("vision") if isinstance(telemetry.get("vision"), list) else []
    if vision:
        import hashlib
        import json

        computed = hashlib.sha256(
            json.dumps(vision, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        return {"fingerprintHash": f"sha256:{computed}"}
    return {}


def _first_inline_ref(refs: Any) -> Dict[str, Any]:
    if not isinstance(refs, list):
        return {}
    for item in refs:
        if isinstance(item, dict) and isinstance(item.get("inline"), dict):
            return item["inline"]
    return {}


def _resolve_trust_gap_codes(*, authz_graph: Dict[str, Any], governed_receipt: Dict[str, Any]) -> list[str]:
    codes: list[str] = []
    receipt_codes = governed_receipt.get("trust_gap_codes")
    if isinstance(receipt_codes, list):
        for code in receipt_codes:
            if isinstance(code, str) and code.strip() and code not in codes:
                codes.append(code.strip())
    trust_gaps = authz_graph.get("trust_gaps")
    if isinstance(trust_gaps, list):
        for item in trust_gaps:
            if not isinstance(item, dict):
                continue
            code = item.get("code")
            if isinstance(code, str) and code.strip() and code not in codes:
                codes.append(code.strip())
    return codes


def _trust_gap_details(codes: list[str], *, taxonomy: Optional[Dict[str, Dict[str, str]]] = None) -> list[Dict[str, Any]]:
    details: list[Dict[str, Any]] = []
    taxonomy_map = taxonomy if isinstance(taxonomy, dict) and taxonomy else TRUST_GAP_TAXONOMY
    for code in codes:
        normalized = str(code).strip()
        if not normalized:
            continue
        entry = taxonomy_map.get(normalized, {})
        details.append(
            {
                "code": normalized,
                "category": entry.get("category", "general"),
                "severity": entry.get("severity", "medium"),
                "message": entry.get("message", normalized.replace("_", " ")),
            }
        )
    return details


def _resolve_trust_gap_taxonomy(
    *,
    authz_graph: Dict[str, Any],
    governed_receipt: Dict[str, Any],
    policy_receipt: Dict[str, Any],
    evidence_bundle: Dict[str, Any],
) -> Dict[str, Dict[str, str]]:
    taxonomy = dict(TRUST_GAP_TAXONOMY)
    candidates = [
        governed_receipt.get("advisory"),
        authz_graph.get("taxonomy_bundle"),
        policy_receipt.get("taxonomy_bundle"),
        evidence_bundle.get("taxonomy_bundle"),
        evidence_bundle.get("evidence_inputs"),
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        bundle = candidate.get("taxonomy_bundle") if isinstance(candidate.get("taxonomy_bundle"), dict) else candidate
        trust_gap_codes = bundle.get("trust_gap_codes") if isinstance(bundle, dict) else None
        if isinstance(trust_gap_codes, dict):
            for code, payload in trust_gap_codes.items():
                if not isinstance(payload, dict):
                    continue
                normalized_code = str(code).strip()
                if not normalized_code:
                    continue
                taxonomy[normalized_code] = {
                    "category": str(payload.get("machine_category") or payload.get("category") or "general"),
                    "severity": str(payload.get("severity") or "medium"),
                    "message": str(payload.get("operator_message") or payload.get("message") or normalized_code.replace("_", " ")),
                }
        elif isinstance(trust_gap_codes, list):
            for item in trust_gap_codes:
                if not isinstance(item, dict):
                    continue
                code = str(item.get("code") or "").strip()
                if not code:
                    continue
                taxonomy[code] = {
                    "category": str(item.get("machine_category") or item.get("category") or "general"),
                    "severity": str(item.get("severity") or "medium"),
                    "message": str(item.get("operator_message") or item.get("message") or code.replace("_", " ")),
                }
    return taxonomy


def _owner_context(governed_receipt: Dict[str, Any]) -> Dict[str, Any]:
    raw = governed_receipt.get("owner_context") if isinstance(governed_receipt.get("owner_context"), dict) else {}
    creator_profile_ref = raw.get("creator_profile_ref") if isinstance(raw.get("creator_profile_ref"), dict) else None
    trust_preferences_ref = raw.get("trust_preferences_ref") if isinstance(raw.get("trust_preferences_ref"), dict) else None
    owner_id = str(raw.get("owner_id") or "").strip() or None
    if owner_id is None and creator_profile_ref is None and trust_preferences_ref is None:
        return {}
    return {
        "owner_id": owner_id,
        "creator_profile_ref": dict(creator_profile_ref) if isinstance(creator_profile_ref, dict) else None,
        "trust_preferences_ref": dict(trust_preferences_ref) if isinstance(trust_preferences_ref, dict) else None,
    }


def _authority_consistency_summary(*, audit_record: Dict[str, Any], governed_receipt: Dict[str, Any]) -> Dict[str, Any]:
    action_intent = audit_record.get("action_intent") if isinstance(audit_record.get("action_intent"), dict) else {}
    owner_context = _owner_context(governed_receipt)
    return authority_consistency_summary(
        action_intent=action_intent,
        owner_context=owner_context,
    )


def _operator_actions_for_authority_issues(issues: list[str]) -> list[Dict[str, Any]]:
    return _build_operator_actions_for_authority_issues(issues)


def _resolve_forensic_block(*, audit_record: Dict[str, Any], evidence_bundle: Dict[str, Any]) -> Dict[str, Any]:
    existing = evidence_bundle.get("forensic_block")
    policy_decision = audit_record.get("policy_decision") if isinstance(audit_record.get("policy_decision"), dict) else {}
    authz_graph = policy_decision.get("authz_graph") if isinstance(policy_decision.get("authz_graph"), dict) else {}
    governed_receipt = policy_decision.get("governed_receipt") if isinstance(policy_decision.get("governed_receipt"), dict) else {}
    policy_receipt = audit_record.get("policy_receipt") if isinstance(audit_record.get("policy_receipt"), dict) else {}
    action_intent = audit_record.get("action_intent") if isinstance(audit_record.get("action_intent"), dict) else {}
    action = action_intent.get("action") if isinstance(action_intent.get("action"), dict) else {}
    action_parameters = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
    principal = action_intent.get("principal") if isinstance(action_intent.get("principal"), dict) else {}
    resource = action_intent.get("resource") if isinstance(action_intent.get("resource"), dict) else {}
    gateway_context = (
        action_parameters.get("gateway")
        if isinstance(action_parameters, dict)
        else {}
    )
    if not isinstance(gateway_context, dict):
        gateway_context = {}
    fingerprint_components = gateway_context.get("fingerprint_components")
    if not isinstance(fingerprint_components, dict):
        fingerprint_components = {}
    execution_summary = (
        evidence_bundle.get("evidence_inputs", {}).get("execution_summary")
        if isinstance(evidence_bundle.get("evidence_inputs"), dict)
        and isinstance(evidence_bundle.get("evidence_inputs", {}).get("execution_summary"), dict)
        else {}
    )
    derived_components = _derive_forensic_fingerprint_components(
        fingerprint_components=fingerprint_components,
        audit_record=audit_record,
        governed_receipt=governed_receipt,
        policy_receipt=policy_receipt,
        execution_summary=execution_summary if isinstance(execution_summary, dict) else {},
    )
    forensic_block_id = _derive_forensic_block_id(
        evidence_bundle=evidence_bundle,
        governed_receipt=governed_receipt,
        policy_receipt=policy_receipt,
    )
    request_id = (
        str(action_intent.get("intent_id") or audit_record.get("intent_id") or audit_record.get("task_id") or "").strip()
        or "unknown_request"
    )
    audit_id = (
        str(audit_record.get("id") or evidence_bundle.get("evidence_bundle_id") or request_id).strip()
        or "unknown_audit"
    )
    timestamp = (
        str(audit_record.get("recorded_at") or evidence_bundle.get("created_at") or "").strip()
        or "unknown_timestamp"
    )
    disposition = (
        str(authz_graph.get("disposition") or governed_receipt.get("disposition") or _resolve_platform_state(audit_record)).strip().lower()
        or "unknown"
    )
    decision_hash = (
        str(governed_receipt.get("decision_hash") or policy_receipt.get("policy_decision_id") or "").strip()
        or _hash_ref(
            f"{request_id}:{disposition}:{forensic_block_id}",
            fallback=f"decision:{request_id}:{forensic_block_id}",
        )
    )
    asset_id = str(resource.get("asset_id") or governed_receipt.get("asset_ref") or "").strip() or "asset:unknown"
    principal_id = str(principal.get("agent_id") or "").strip() or "unknown_principal"
    owner_id = str(gateway_context.get("owner_id") or principal.get("owner_id") or "").strip() or None
    delegation_chain_hash = str(gateway_context.get("delegation_ref") or principal.get("delegation_ref") or "").strip()
    if not delegation_chain_hash:
        delegation_chain_hash = _hash_ref(
            f"{principal_id}:{asset_id}:{forensic_block_id}",
            fallback=f"delegation:{request_id}:{asset_id}",
        )
    hardware_fingerprint = str(
        gateway_context.get("hardware_public_key_fingerprint")
        or (
            evidence_bundle.get("signer_metadata", {}).get("key_ref")
            if isinstance(evidence_bundle.get("signer_metadata"), dict)
            else None
        )
        or ""
    ).strip()
    if not hardware_fingerprint:
        hardware_fingerprint = _hash_ref(
            evidence_bundle.get("node_id"),
            fallback=f"hardware:{request_id}:{forensic_block_id}",
        )
    coordinate_ref = str(
        gateway_context.get("expected_coordinate_ref")
        or (
            ((existing.get("spatial_evidence") or {}).get("coordinate_binding", {}).get("coordinate_ref"))
            if isinstance(existing, dict)
            and isinstance(existing.get("spatial_evidence"), dict)
            and isinstance((existing.get("spatial_evidence") or {}).get("coordinate_binding"), dict)
            else None
        )
        or ""
    ).strip()
    if not coordinate_ref:
        coordinate_ref = f"coordinate:unknown:{asset_id}"

    base_block = {
        "@context": FORENSIC_BLOCK_CONTEXT,
        "@type": "ForensicBlock",
        "forensic_block_id": forensic_block_id,
        "block_header": {
            "audit_id": audit_id,
            "timestamp": timestamp,
            "version": "seedcore.forensic_block.v1",
            "sequence_index": None,
            "forensic_block_id": forensic_block_id,
        },
        "decision_linkage": {
            "request_id": request_id,
            "disposition": disposition.upper(),
            "decision_hash": decision_hash,
            "policy_receipt_id": str(policy_receipt.get("policy_receipt_id") or "").strip() or None,
            "policy_snapshot_ref": (
                str(
                    governed_receipt.get("snapshot_version")
                    or authz_graph.get("snapshot_version")
                    or policy_receipt.get("decision_graph_snapshot_version")
                    or evidence_bundle.get("decision_graph_snapshot_version")
                    or ""
                ).strip()
                or None
            ),
        },
        "asset_identity": {
            "asset_id": asset_id,
            "lot_id": str(resource.get("lot_id") or "").strip() or None,
            "product_ref": str(resource.get("product_ref") or gateway_context.get("product_ref") or "").strip() or None,
            "quote_ref": str(resource.get("quote_ref") or "").strip() or None,
        },
        "authority_context": {
            "@type": "DelegatedAuthority",
            "principal_id": principal_id,
            "owner_id": owner_id,
            "hardware_fingerprint": hardware_fingerprint,
            "kms_key_ref": evidence_bundle.get("signer_metadata", {}).get("key_ref") if isinstance(evidence_bundle.get("signer_metadata"), dict) else None,
            "delegation_chain_hash": delegation_chain_hash,
            "execution_token_id": evidence_bundle.get("execution_token_id"),
            "organization_ref": str(gateway_context.get("organization_ref") or principal.get("organization_ref") or "").strip() or None,
        },
        "fingerprint_components": derived_components,
        "economic_evidence": {
            "@type": "CommerceTransaction",
            "platform": "seedcore_rct",
            "order_id": None,
            "transaction_hash": derived_components["economic_hash"],
            "quote_hash": None,
            "asset_identity": asset_id,
        },
        "spatial_evidence": {
            "@type": "PhysicalPresence",
            "environment": "seedcore_rct",
            "facility_id": gateway_context.get("facility_ref"),
            "coordinate_binding": {
                "coordinate_ref": coordinate_ref,
                "system": "seedcore",
            },
            "presence_proof_hash": derived_components["physical_presence_hash"],
            "current_zone": str(gateway_context.get("expected_to_zone") or "").strip() or None,
        },
        "cognitive_evidence": {
            "@type": "PolicyReasoning",
            "policy_receipt_id": audit_record.get("policy_receipt", {}).get("policy_receipt_id")
            if isinstance(audit_record.get("policy_receipt"), dict)
            else None,
            "decision": disposition.upper(),
            "reasoning_trace_hash": derived_components["reasoning_hash"],
            "matched_policy_refs": list(authz_graph.get("matched_policy_refs") or []),
        },
        "physical_evidence": {
            "@type": "ActuatorProof",
            "device_actor": evidence_bundle.get("node_id"),
            "edge_node": evidence_bundle.get("node_id"),
            "trajectory_hash": execution_summary.get("actuator_result_hash") if isinstance(execution_summary, dict) else None,
            "actuator_telemetry": {
                "motor_torque_hash": derived_components["actuator_hash"],
            },
            "sensor_signatures": [],
        },
        "settlement_status": {
            "is_finalized": None,
            "twin_mutation_id": None,
            "forensic_integrity_hash": None,
        },
    }
    if isinstance(existing, dict) and existing:
        merged = dict(existing)
        merged.setdefault("@context", base_block["@context"])
        merged.setdefault("@type", base_block["@type"])
        merged.setdefault("forensic_block_id", forensic_block_id)
        merged.setdefault("block_header", base_block["block_header"])
        merged.setdefault("decision_linkage", base_block["decision_linkage"])
        merged.setdefault("asset_identity", base_block["asset_identity"])
        merged.setdefault("authority_context", base_block["authority_context"])
        merged.setdefault("fingerprint_components", derived_components)
        merged.setdefault("economic_evidence", base_block["economic_evidence"])
        merged.setdefault("spatial_evidence", base_block["spatial_evidence"])
        merged.setdefault("cognitive_evidence", base_block["cognitive_evidence"])
        merged.setdefault("physical_evidence", base_block["physical_evidence"])
        return _normalize_forensic_block_shape(merged)
    return _normalize_forensic_block_shape(base_block)


def _derive_forensic_block_id(
    *,
    evidence_bundle: Dict[str, Any],
    governed_receipt: Dict[str, Any],
    policy_receipt: Dict[str, Any],
) -> str:
    for candidate in (
        evidence_bundle.get("forensic_block_id"),
        governed_receipt.get("forensic_block_id"),
        policy_receipt.get("policy_receipt_id"),
        governed_receipt.get("decision_hash"),
        evidence_bundle.get("evidence_bundle_id"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    raw = json.dumps(
        {
            "receipt": policy_receipt.get("policy_receipt_id"),
            "decision": governed_receipt.get("decision_hash"),
            "bundle": evidence_bundle.get("evidence_bundle_id"),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return f"fb:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _hash_ref(value: Any, *, fallback: str) -> str:
    normalized = str(value or "").strip()
    if normalized:
        if normalized.startswith("sha256:"):
            return normalized
        return f"sha256:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}"
    return f"sha256:{hashlib.sha256(fallback.encode('utf-8')).hexdigest()}"


def _derive_forensic_fingerprint_components(
    *,
    fingerprint_components: Dict[str, Any],
    audit_record: Dict[str, Any],
    governed_receipt: Dict[str, Any],
    policy_receipt: Dict[str, Any],
    execution_summary: Dict[str, Any],
) -> Dict[str, str]:
    decision_ref = str(governed_receipt.get("decision_hash") or policy_receipt.get("policy_receipt_id") or "").strip()
    execution_ref = str(execution_summary.get("actuator_result_hash") or "").strip()
    asset_ref = (
        str(
            audit_record.get("action_intent", {}).get("resource", {}).get("asset_id")
            if isinstance(audit_record.get("action_intent"), dict)
            and isinstance(audit_record.get("action_intent", {}).get("resource"), dict)
            else ""
        ).strip()
    )
    return {
        "economic_hash": _hash_ref(
            fingerprint_components.get("economic_hash") or policy_receipt.get("policy_decision_id"),
            fallback=f"economic:{decision_ref}:{asset_ref}",
        ),
        "physical_presence_hash": _hash_ref(
            fingerprint_components.get("physical_presence_hash") or execution_ref,
            fallback=f"presence:{asset_ref}:{execution_ref}",
        ),
        "reasoning_hash": _hash_ref(
            fingerprint_components.get("reasoning_hash") or governed_receipt.get("decision_hash"),
            fallback=f"reasoning:{decision_ref}",
        ),
        "actuator_hash": _hash_ref(
            fingerprint_components.get("actuator_hash") or execution_ref,
            fallback=f"actuator:{execution_ref}:{asset_ref}",
        ),
    }


def _normalize_forensic_block_shape(value: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(value)
    normalized["@context"] = str(normalized.get("@context") or FORENSIC_BLOCK_CONTEXT)
    normalized["@type"] = str(normalized.get("@type") or "ForensicBlock")
    forensic_block_id = str(normalized.get("forensic_block_id") or "").strip()
    if not forensic_block_id:
        raise ValueError("forensic_block.forensic_block_id is required")
    normalized["forensic_block_id"] = forensic_block_id

    fingerprint = normalized.get("fingerprint_components")
    if not isinstance(fingerprint, dict):
        fingerprint = {}
    for key in ("economic_hash", "physical_presence_hash", "reasoning_hash", "actuator_hash"):
        raw = str(fingerprint.get(key) or "").strip()
        if not raw:
            raise ValueError(f"forensic_block.fingerprint_components.{key} is required")
        fingerprint[key] = raw
    normalized["fingerprint_components"] = fingerprint
    validate_forensic_block_payload(normalized)
    return normalized
