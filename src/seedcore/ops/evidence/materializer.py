from __future__ import annotations

import uuid
from typing import Any, Dict, Optional


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
            "trust_gap_codes": trust_gap_codes,
            "custody_proof_count": len(governed_receipt.get("custody_proof") or []),
            "provenance_sources": list(governed_receipt.get("provenance_sources") or []),
        },
        "custody_transition": {
            "from": transition_receipt.get("from_zone") or zone_checks.get("current_zone") or "unknown_zone",
            "to": transition_receipt.get("to_zone") or transition_receipt.get("target_zone") or zone_checks.get("target_zone") or "unknown_zone",
            "timestamp": evidence_bundle.get("created_at") or audit_record.get("recorded_at"),
        },
        "signature": evidence_bundle.get("signature"),
        "signer_metadata": signer_metadata,
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
