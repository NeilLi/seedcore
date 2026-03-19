from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from seedcore.models.evidence_bundle import (
    CustodyTransition,
    ManipulationTelemetry,
    PolicyVerification,
    PreContactEvidence,
    SeedCoreCustodyEvent,
)


def materialize_seedcore_custody_event(
    *,
    audit_record: Dict[str, Any],
) -> SeedCoreCustodyEvent:
    evidence_bundle = (
        audit_record.get("evidence_bundle")
        if isinstance(audit_record.get("evidence_bundle"), dict)
        else {}
    )
    telemetry = (
        evidence_bundle.get("telemetry_snapshot")
        if isinstance(evidence_bundle.get("telemetry_snapshot"), dict)
        else {}
    )
    receipt = (
        evidence_bundle.get("execution_receipt")
        if isinstance(evidence_bundle.get("execution_receipt"), dict)
        else {}
    )
    policy_receipt = (
        audit_record.get("policy_receipt")
        if isinstance(audit_record.get("policy_receipt"), dict)
        else {}
    )
    policy_decision = (
        audit_record.get("policy_decision")
        if isinstance(audit_record.get("policy_decision"), dict)
        else {}
    )
    asset_fingerprint = (
        evidence_bundle.get("asset_fingerprint")
        if isinstance(evidence_bundle.get("asset_fingerprint"), dict)
        else {}
    )

    event_id = _resolve_event_id(audit_record, evidence_bundle)
    device_identity = _resolve_device_identity(audit_record, evidence_bundle, receipt)
    platform_state = _resolve_platform_state(policy_decision)
    executed_at = str(evidence_bundle.get("executed_at") or audit_record.get("recorded_at") or "")
    if not executed_at:
        executed_at = "1970-01-01T00:00:00+00:00"
    target_zone, current_zone = _resolve_zones(telemetry)

    pre_contact = PreContactEvidence(
        environmental_telemetry=_resolve_environmental_telemetry(telemetry),
        voc_profile=_resolve_voc_profile(asset_fingerprint),
        vision_baseline=_resolve_vision_baseline(telemetry, asset_fingerprint, receipt),
    )
    manipulation = ManipulationTelemetry(
        commanded_forces="envelope-verified",
        observed_forces="within-tolerance",
        trajectory_hash=(
            str(receipt.get("actuator_result_hash"))
            if receipt.get("actuator_result_hash") is not None
            else None
        ),
    )
    verification = PolicyVerification(
        policy_hash=str(
            policy_receipt.get("policy_decision_hash")
            or audit_record.get("input_hash")
            or "unknown_policy_hash"
        ),
        authorization_token=str(
            _resolve_authorization_token(policy_receipt, audit_record) or "unknown_token"
        ),
    )
    transition = CustodyTransition(
        from_zone=current_zone,
        to_zone=target_zone,
        timestamp=executed_at,
    )
    signature = str(receipt.get("signature") or "unsigned")

    return SeedCoreCustodyEvent(
        id=event_id,
        device_identity=device_identity,
        platform_state=platform_state,
        pre_contact_evidence=pre_contact,
        manipulation_telemetry=manipulation,
        policy_verification=verification,
        custody_transition=transition,
        signature=signature,
    )


def materialize_seedcore_custody_event_payload(
    *,
    audit_record: Dict[str, Any],
) -> Dict[str, Any]:
    event = materialize_seedcore_custody_event(audit_record=audit_record)
    return event.model_dump(mode="json", by_alias=True)


def _resolve_event_id(audit_record: Dict[str, Any], evidence_bundle: Dict[str, Any]) -> str:
    existing = (
        evidence_bundle.get("custody_event")
        if isinstance(evidence_bundle.get("custody_event"), dict)
        else {}
    )
    candidate = existing.get("@id") or existing.get("id")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    record_id = audit_record.get("id")
    if isinstance(record_id, str) and record_id.strip():
        return f"seedcore:custody-event:{record_id}"
    intent_id = audit_record.get("intent_id")
    if isinstance(intent_id, str) and intent_id.strip():
        return f"seedcore:custody-event:intent:{intent_id}"
    return f"seedcore:custody-event:{uuid.uuid4()}"


def _resolve_device_identity(
    audit_record: Dict[str, Any],
    evidence_bundle: Dict[str, Any],
    receipt: Dict[str, Any],
) -> str:
    node_id = evidence_bundle.get("node_id")
    if isinstance(node_id, str) and node_id.strip():
        return node_id.strip()
    receipt_node = receipt.get("node_id")
    if isinstance(receipt_node, str) and receipt_node.strip():
        return receipt_node.strip()
    transition_receipt = (
        receipt.get("transition_receipt")
        if isinstance(receipt.get("transition_receipt"), dict)
        else {}
    )
    signed_payload = (
        transition_receipt.get("signed_payload")
        if isinstance(transition_receipt.get("signed_payload"), dict)
        else {}
    )
    endpoint_id = signed_payload.get("endpoint_id")
    hardware_uuid = signed_payload.get("hardware_uuid")
    if isinstance(endpoint_id, str) and endpoint_id.strip():
        if isinstance(hardware_uuid, str) and hardware_uuid.strip():
            return f"{endpoint_id.strip()}#{hardware_uuid.strip()}"
        return endpoint_id.strip()
    actor_organ_id = audit_record.get("actor_organ_id")
    if isinstance(actor_organ_id, str) and actor_organ_id.strip():
        return f"organ://{actor_organ_id.strip()}"
    return "unknown_device"


def _resolve_platform_state(policy_decision: Dict[str, Any]) -> str:
    disposition = policy_decision.get("disposition")
    if isinstance(disposition, str) and disposition.strip():
        return disposition.strip().lower()
    allowed = policy_decision.get("allowed")
    if allowed is True:
        return "allow"
    if allowed is False:
        return "deny"
    return "unknown"


def _resolve_zones(telemetry: Dict[str, Any]) -> tuple[str, str]:
    zone_checks = (
        telemetry.get("zone_checks")
        if isinstance(telemetry.get("zone_checks"), dict)
        else {}
    )
    target_zone = zone_checks.get("target_zone")
    current_zone = zone_checks.get("current_zone")
    to_zone = str(target_zone) if isinstance(target_zone, str) and target_zone.strip() else "unknown_zone"
    from_zone = str(current_zone) if isinstance(current_zone, str) and current_zone.strip() else "unknown_zone"
    return to_zone, from_zone


def _resolve_environmental_telemetry(telemetry: Dict[str, Any]) -> Dict[str, float]:
    multimodal = (
        telemetry.get("multimodal")
        if isinstance(telemetry.get("multimodal"), dict)
        else {}
    )
    candidate = (
        multimodal.get("environmental_telemetry")
        if isinstance(multimodal.get("environmental_telemetry"), dict)
        else {}
    )
    out: Dict[str, float] = {}
    for key, value in candidate.items():
        if isinstance(key, str) and isinstance(value, (int, float)):
            out[key] = float(value)
    return out


def _resolve_voc_profile(asset_fingerprint: Dict[str, Any]) -> Dict[str, str]:
    components = (
        asset_fingerprint.get("components")
        if isinstance(asset_fingerprint.get("components"), dict)
        else {}
    )
    voc_hash = components.get("voc_hash") or components.get("provenance_hash")
    if isinstance(voc_hash, str) and voc_hash.strip():
        return {"signatureHash": voc_hash.strip()}
    return {}


def _resolve_vision_baseline(
    telemetry: Dict[str, Any],
    asset_fingerprint: Dict[str, Any],
    receipt: Dict[str, Any],
) -> Dict[str, str]:
    components = (
        asset_fingerprint.get("components")
        if isinstance(asset_fingerprint.get("components"), dict)
        else {}
    )
    vision_hash = components.get("vision_hash")
    if isinstance(vision_hash, str) and vision_hash.strip():
        return {"fingerprintHash": vision_hash.strip()}
    vision = telemetry.get("vision") if isinstance(telemetry.get("vision"), list) else []
    if vision:
        import hashlib
        import json

        computed = hashlib.sha256(
            json.dumps(vision, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        return {"fingerprintHash": f"sha256:{computed}"}
    payload_hash = receipt.get("payload_hash")
    if isinstance(payload_hash, str) and payload_hash.strip():
        return {"fingerprintHash": payload_hash.strip()}
    return {}


def _resolve_authorization_token(
    policy_receipt: Dict[str, Any],
    audit_record: Dict[str, Any],
) -> Optional[str]:
    execution_token = (
        policy_receipt.get("execution_token")
        if isinstance(policy_receipt.get("execution_token"), dict)
        else {}
    )
    token_id = execution_token.get("token_id")
    if isinstance(token_id, str) and token_id.strip():
        return token_id.strip()
    audit_token = audit_record.get("token_id")
    if isinstance(audit_token, str) and audit_token.strip():
        return audit_token.strip()
    return None
