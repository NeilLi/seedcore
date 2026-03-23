from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from seedcore.hal.custody.transition_receipts import is_attestable_transition_endpoint, verify_transition_receipt
from seedcore.models.evidence_bundle import (
    AssetFingerprint,
    EvidenceBundle,
    HALCaptureEnvelope,
    PolicyReceipt,
    TransitionReceipt,
)
from seedcore.ops.evidence.verification import build_signed_artifact


def build_policy_receipt_artifact(
    *,
    task_dict: Dict[str, Any],
    timestamp: str,
) -> Optional[PolicyReceipt]:
    params = task_dict.get("params", {}) if isinstance(task_dict.get("params"), dict) else {}
    governance = params.get("governance", {}) if isinstance(params.get("governance"), dict) else {}
    existing_receipt = governance.get("policy_receipt")
    if isinstance(existing_receipt, dict):
        try:
            return PolicyReceipt(**existing_receipt)
        except Exception:
            pass

    policy_decision = governance.get("policy_decision") if isinstance(governance.get("policy_decision"), dict) else {}
    action_intent = governance.get("action_intent") if isinstance(governance.get("action_intent"), dict) else {}
    execution_token = governance.get("execution_token") if isinstance(governance.get("execution_token"), dict) else {}
    policy_case = governance.get("policy_case") if isinstance(governance.get("policy_case"), dict) else {}
    authz_graph = policy_decision.get("authz_graph") if isinstance(policy_decision.get("authz_graph"), dict) else {}
    governed_receipt = (
        policy_decision.get("governed_receipt")
        if isinstance(policy_decision.get("governed_receipt"), dict)
        else {}
    )
    resource = action_intent.get("resource") if isinstance(action_intent.get("resource"), dict) else {}
    principal = action_intent.get("principal") if isinstance(action_intent.get("principal"), dict) else {}

    if not policy_decision and not execution_token:
        return None

    payload = {
        "policy_receipt_id": str(uuid.uuid4()),
        "policy_decision_id": _sha256_hex(_canonical_json(policy_decision or execution_token)),
        "task_id": str(task_dict.get("task_id") or task_dict.get("id") or "unknown_task"),
        "intent_id": str(action_intent.get("intent_id") or "unknown_intent"),
        "policy_version": (
            policy_decision.get("policy_snapshot")
            or policy_case.get("policy_snapshot")
            or ((action_intent.get("action") or {}).get("security_contract") or {}).get("version")
        ),
        "decision": dict(policy_decision or {}),
        "evaluated_rules": _extract_evaluated_rules(policy_decision),
        "subject_ref": (
            str(principal.get("agent_id"))
            if principal.get("agent_id") is not None
            else None
        ),
        "asset_ref": (
            str(resource.get("asset_id"))
            if resource.get("asset_id") is not None
            else None
        ),
        "authz_disposition": (
            str(policy_decision.get("disposition"))
            if policy_decision.get("disposition") is not None
            else None
        ),
        "governed_receipt_hash": (
            str(governed_receipt.get("decision_hash"))
            if governed_receipt.get("decision_hash") is not None
            else None
        ),
        "trust_gap_codes": _extract_trust_gap_codes(governed_receipt, authz_graph),
        "timestamp": timestamp,
    }
    endpoint_id = (
        (execution_token.get("constraints") or {}).get("endpoint_id")
        if isinstance(execution_token.get("constraints"), dict)
        else None
    )
    _, signer_metadata, signature = build_signed_artifact(
        artifact_type="policy_receipt",
        payload=payload,
        endpoint_id=str(endpoint_id) if endpoint_id is not None else None,
        trust_level="attested" if is_attestable_transition_endpoint(endpoint_id) else "baseline",
        node_id=str(endpoint_id) if endpoint_id is not None else None,
    )
    return PolicyReceipt(
        **payload,
        signer_metadata=signer_metadata,
        signature=signature,
    )


def build_evidence_bundle(
    *,
    task_dict: Dict[str, Any],
    envelope: Dict[str, Any],
    organ_id: str,
    agent_id: str,
) -> EvidenceBundle:
    params = task_dict.get("params", {}) if isinstance(task_dict.get("params"), dict) else {}
    governance = params.get("governance", {}) if isinstance(params.get("governance"), dict) else {}
    action_intent = governance.get("action_intent", {}) if isinstance(governance.get("action_intent"), dict) else {}
    execution_token = governance.get("execution_token", {}) if isinstance(governance.get("execution_token"), dict) else {}

    executed_at = _derive_executed_at(envelope)
    actuator_entries = _extract_actuator_entries(envelope)
    actuator_endpoint = _extract_actuator_endpoint(task_dict, actuator_entries)
    node_id = _derive_node_id(task_dict, actuator_entries, organ_id)
    transition_receipts = _extract_transition_receipts(actuator_entries)
    policy_receipt = build_policy_receipt_artifact(task_dict=task_dict, timestamp=executed_at)
    asset_fingerprint = _build_asset_fingerprint(task_dict, timestamp=executed_at, node_id=node_id)
    telemetry_snapshot = _build_telemetry_snapshot(
        task_dict,
        envelope,
        organ_id,
        agent_id,
        executed_at,
        node_id=node_id,
        actuator_entries=actuator_entries,
    )
    hal_capture = _extract_hal_capture(envelope)
    media_refs = _extract_media_refs(hal_capture=hal_capture, telemetry_snapshot=telemetry_snapshot)
    execution_summary = _build_execution_summary(
        task_dict=task_dict,
        actuator_endpoint=actuator_endpoint,
        actuator_entries=actuator_entries,
        node_id=node_id,
        executed_at=executed_at,
    )
    payload = {
        "evidence_bundle_id": str(uuid.uuid4()),
        "task_id": str(task_dict.get("task_id") or task_dict.get("id") or "unknown_task"),
        "intent_id": str(action_intent.get("intent_id") or "unknown_intent"),
        "intent_ref": (
            f"governance://action-intent/{action_intent.get('intent_id')}"
            if action_intent.get("intent_id") is not None
            else None
        ),
        "execution_token_id": (
            str(execution_token.get("token_id"))
            if execution_token.get("token_id") is not None
            else None
        ),
        "policy_receipt_id": (
            policy_receipt.policy_receipt_id
            if policy_receipt is not None
            else None
        ),
        "transition_receipt_ids": [
            receipt.transition_receipt_id
            for receipt in transition_receipts
        ],
        "asset_fingerprint": (
            asset_fingerprint.model_dump(mode="json")
            if asset_fingerprint is not None
            else None
        ),
        "evidence_inputs": {
            "execution_summary": execution_summary,
            "policy_receipt": (
                policy_receipt.model_dump(mode="json")
                if policy_receipt is not None
                else None
            ),
            "transition_receipts": [
                receipt.model_dump(mode="json")
                for receipt in transition_receipts
            ],
            "hal_capture": (
                hal_capture.model_dump(mode="json")
                if hal_capture is not None
                else None
            ),
        },
        "telemetry_refs": [
            {
                "kind": "telemetry_snapshot",
                "captured_at": executed_at,
                "hash": _sha256_hex(_canonical_json(telemetry_snapshot)),
                "inline": telemetry_snapshot,
            }
        ],
        "media_refs": media_refs,
        "node_id": node_id,
        "created_at": executed_at,
    }
    _, signer_metadata, signature = build_signed_artifact(
        artifact_type="evidence_bundle",
        payload=payload,
        endpoint_id=actuator_endpoint,
        trust_level="attested" if is_attestable_transition_endpoint(actuator_endpoint) else "baseline",
        node_id=node_id,
    )
    bundle_payload = dict(payload)
    bundle_payload["asset_fingerprint"] = asset_fingerprint
    return EvidenceBundle(
        **bundle_payload,
        signer_metadata=signer_metadata,
        signature=signature,
    )


def attach_evidence_bundle(
    *,
    task_dict: Dict[str, Any],
    envelope: Dict[str, Any],
    organ_id: str,
    agent_id: str,
) -> Dict[str, Any]:
    evidence = build_evidence_bundle(
        task_dict=task_dict,
        envelope=envelope,
        organ_id=organ_id,
        agent_id=agent_id,
    ).model_dump(mode="json")

    meta = envelope.get("meta", {}) if isinstance(envelope.get("meta"), dict) else {}
    meta["evidence_bundle"] = evidence
    envelope["meta"] = meta

    payload = envelope.get("payload")
    if isinstance(payload, dict):
        payload_meta = payload.get("meta", {}) if isinstance(payload.get("meta"), dict) else {}
        payload_meta["evidence_bundle"] = evidence
        payload["meta"] = payload_meta
        envelope["payload"] = payload
    return envelope


def _derive_executed_at(envelope: Dict[str, Any]) -> str:
    meta = envelope.get("meta", {}) if isinstance(envelope.get("meta"), dict) else {}
    exec_meta = meta.get("exec", {}) if isinstance(meta.get("exec"), dict) else {}
    finished_at = exec_meta.get("finished_at")
    if isinstance(finished_at, str) and finished_at.strip():
        return finished_at
    return datetime.now(timezone.utc).isoformat()


def _extract_evaluated_rules(policy_decision: Dict[str, Any]) -> List[str]:
    explanations = policy_decision.get("explanations")
    if isinstance(explanations, list):
        return [str(item) for item in explanations if isinstance(item, str) and item.strip()]
    reason = policy_decision.get("reason")
    if isinstance(reason, str) and reason.strip():
        return [reason.strip()]
    return []


def _extract_trust_gap_codes(
    governed_receipt: Dict[str, Any],
    authz_graph: Dict[str, Any],
) -> List[str]:
    receipt_codes = governed_receipt.get("trust_gap_codes")
    if isinstance(receipt_codes, list):
        return [str(item) for item in receipt_codes if str(item).strip()]
    trust_gaps = authz_graph.get("trust_gaps")
    if isinstance(trust_gaps, list):
        codes: List[str] = []
        for item in trust_gaps:
            if isinstance(item, dict) and item.get("code") is not None:
                codes.append(str(item.get("code")))
        return codes
    return []


def _build_telemetry_snapshot(
    task_dict: Dict[str, Any],
    envelope: Dict[str, Any],
    organ_id: str,
    agent_id: str,
    executed_at: str,
    *,
    node_id: str | None,
    actuator_entries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    params = task_dict.get("params", {}) if isinstance(task_dict.get("params"), dict) else {}
    multimodal = params.get("multimodal", {}) if isinstance(params.get("multimodal"), dict) else {}
    governance = params.get("governance", {}) if isinstance(params.get("governance"), dict) else {}
    action_intent = governance.get("action_intent", {}) if isinstance(governance.get("action_intent"), dict) else {}
    resource = action_intent.get("resource", {}) if isinstance(action_intent.get("resource"), dict) else {}
    payload = envelope.get("payload", {}) if isinstance(envelope.get("payload"), dict) else {}
    result_data = payload.get("result", {}) if isinstance(payload.get("result"), dict) else {}
    enqueued = result_data.get("enqueued") if isinstance(result_data.get("enqueued"), list) else []
    tool_results = payload.get("results") if isinstance(payload.get("results"), list) else []
    sensors: List[Dict[str, Any]] = []
    vision: List[Dict[str, Any]] = []
    gps: Dict[str, Any] = {}
    zone_checks: Dict[str, Any] = {
        "target_zone": resource.get("target_zone") or multimodal.get("location_context") or params.get("location_context"),
        "current_zone": params.get("current_zone") or multimodal.get("current_zone"),
    }

    if isinstance(multimodal.get("gps"), dict):
        gps = dict(multimodal.get("gps"))
    elif isinstance(params.get("gps"), dict):
        gps = dict(params.get("gps"))
    elif all(multimodal.get(k) is not None for k in ("lat", "lon")):
        gps = {"lat": multimodal.get("lat"), "lon": multimodal.get("lon")}

    if isinstance(multimodal.get("sensor_data"), list):
        sensors.extend([s for s in multimodal["sensor_data"] if isinstance(s, dict)])
    if isinstance(multimodal.get("sensors"), list):
        sensors.extend([s for s in multimodal["sensors"] if isinstance(s, dict)])
    if isinstance(multimodal.get("detections"), list):
        vision.extend([d for d in multimodal["detections"] if isinstance(d, dict)])
    if isinstance(multimodal.get("vision"), list):
        vision.extend([v for v in multimodal["vision"] if isinstance(v, dict)])

    for item in enqueued:
        if not isinstance(item, dict):
            continue
        resp = item.get("resp")
        if isinstance(resp, dict):
            if "robot_state" in resp:
                sensors.append({"source": "hal", "robot_state": resp.get("robot_state")})
            if "status" in resp and "device_id" in resp:
                sensors.append({"source": "tuya", "device_id": resp.get("device_id"), "status": resp.get("status")})

    for item in tool_results:
        if not isinstance(item, dict):
            continue
        output = item.get("output")
        if not isinstance(output, dict):
            continue
        if output.get("robot_state") is not None:
            sensors.append({"source": "tool", "tool": item.get("tool"), "robot_state": output.get("robot_state")})
        if output.get("status") is not None and output.get("device_id") is not None:
            sensors.append(
                {
                    "source": "tool",
                    "tool": item.get("tool"),
                    "device_id": output.get("device_id"),
                    "status": output.get("status"),
                }
            )

    return {
        "executed_by": {
            "organ_id": organ_id,
            "agent_id": agent_id,
            "node_id": node_id,
        },
        "captured_at": executed_at,
        "vision": vision,
        "sensors": sensors,
        "gps": gps,
        "zone_checks": zone_checks,
        "multimodal": multimodal,
        "endpoint_responses": _extract_endpoint_responses(actuator_entries),
    }


def _build_execution_summary(
    *,
    task_dict: Dict[str, Any],
    actuator_endpoint: Optional[str],
    actuator_entries: List[Dict[str, Any]],
    node_id: Optional[str],
    executed_at: str,
) -> Dict[str, Any]:
    params = task_dict.get("params", {}) if isinstance(task_dict.get("params"), dict) else {}
    governance = params.get("governance", {}) if isinstance(params.get("governance"), dict) else {}
    policy_decision = governance.get("policy_decision") if isinstance(governance.get("policy_decision"), dict) else {}
    action_intent = governance.get("action_intent") if isinstance(governance.get("action_intent"), dict) else {}
    execution_token = governance.get("execution_token") if isinstance(governance.get("execution_token"), dict) else {}
    transition_receipts = _extract_transition_receipts(actuator_entries)
    payload = {
        "intent_id": action_intent.get("intent_id"),
        "task_id": task_dict.get("task_id") or task_dict.get("id"),
        "execution_token_id": execution_token.get("token_id"),
        "executed_at": executed_at,
        "actuator_endpoint": actuator_endpoint,
        "actuator_result_hash": _extract_actuator_result_hash(actuator_entries),
        "transition_receipt_ids": [item.transition_receipt_id for item in transition_receipts],
        "policy_decision": policy_decision,
        "node_id": node_id,
    }
    payload["payload_hash"] = _sha256_hex(_canonical_json(payload))
    return payload


def _build_asset_fingerprint(
    task_dict: Dict[str, Any],
    *,
    timestamp: str,
    node_id: Optional[str],
) -> AssetFingerprint | None:
    params = task_dict.get("params", {}) if isinstance(task_dict.get("params"), dict) else {}
    governance = params.get("governance", {}) if isinstance(params.get("governance"), dict) else {}
    action_intent = governance.get("action_intent") if isinstance(governance.get("action_intent"), dict) else {}
    resource = action_intent.get("resource", {}) if isinstance(action_intent.get("resource"), dict) else {}
    multimodal = params.get("multimodal", {}) if isinstance(params.get("multimodal"), dict) else {}

    asset_id = resource.get("asset_id") or params.get("asset_id")
    provenance_hash = resource.get("provenance_hash") or params.get("provenance_hash")
    if not asset_id and not provenance_hash and not multimodal:
        return None

    modality_map: Dict[str, str] = {}
    if provenance_hash is not None:
        modality_map["provenance"] = str(provenance_hash)
    if isinstance(multimodal.get("detections"), list) and multimodal.get("detections"):
        modality_map["visual_hash"] = _sha256_hex(_canonical_json(multimodal.get("detections")))
    if isinstance(multimodal.get("sensors"), list) and multimodal.get("sensors"):
        modality_map["sensor_hash"] = _sha256_hex(_canonical_json(multimodal.get("sensors")))
    if isinstance(multimodal.get("sensor_data"), list) and multimodal.get("sensor_data"):
        modality_map["telemetry_hash"] = _sha256_hex(_canonical_json(multimodal.get("sensor_data")))
    if isinstance(multimodal.get("gps"), dict) and multimodal.get("gps"):
        modality_map["gps_hash"] = _sha256_hex(_canonical_json(multimodal.get("gps")))

    payload = {
        "asset_id": asset_id,
        "modality_map": modality_map,
    }
    return AssetFingerprint(
        fingerprint_id=str(uuid.uuid4()),
        fingerprint_hash=_sha256_hex(_canonical_json(payload)),
        modality_map=modality_map,
        derivation_logic={"algorithm": "sha256", "builder": "ops.evidence.builder"},
        capture_context={
            "asset_id": asset_id,
            "source_registration_id": resource.get("source_registration_id"),
            "target_zone": resource.get("target_zone"),
        },
        hardware_witness={"node_id": node_id} if node_id is not None else {},
        captured_at=timestamp,
    )


def _derive_node_id(
    task_dict: Dict[str, Any],
    actuator_entries: List[Dict[str, Any]],
    organ_id: str,
) -> str:
    params = task_dict.get("params", {}) if isinstance(task_dict.get("params"), dict) else {}
    governance = params.get("governance", {}) if isinstance(params.get("governance"), dict) else {}
    explicit_node = governance.get("node_id") or params.get("node_id")
    if isinstance(explicit_node, str) and explicit_node.strip():
        return explicit_node.strip()

    for item in actuator_entries:
        if not isinstance(item, dict):
            continue
        for container in (item.get("resp"), item.get("output")):
            if not isinstance(container, dict):
                continue
            receipt = container.get("transition_receipt")
            if isinstance(receipt, dict):
                try:
                    transition = TransitionReceipt(**receipt)
                except Exception:
                    transition = None
                if transition is not None:
                    return transition.endpoint_id
            endpoint = container.get("actuator_endpoint")
            device_id = container.get("device_id")
            if isinstance(endpoint, str) and endpoint.strip():
                if isinstance(device_id, str) and device_id.strip():
                    return f"{endpoint.strip()}#{device_id.strip()}"
                return endpoint.strip()
            if isinstance(device_id, str) and device_id.strip():
                return f"device://{device_id.strip()}"
    return f"organ://{organ_id}"


def _extract_actuator_entries(envelope: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload = envelope.get("payload", {}) if isinstance(envelope.get("payload"), dict) else {}
    entries: List[Dict[str, Any]] = []

    result_data = payload.get("result", {}) if isinstance(payload.get("result"), dict) else {}
    enqueued = result_data.get("enqueued")
    if isinstance(enqueued, list):
        for item in enqueued:
            if isinstance(item, dict):
                entries.append(item)

    results = payload.get("results")
    if isinstance(results, list):
        for item in results:
            if isinstance(item, dict):
                entries.append(item)
    return entries


def _extract_actuator_endpoint(task_dict: Dict[str, Any], actuator_entries: List[Dict[str, Any]]) -> str | None:
    for item in actuator_entries:
        if not isinstance(item, dict):
            continue
        for container_key in ("resp", "output"):
            payload = item.get(container_key)
            if not isinstance(payload, dict):
                continue
            receipt = payload.get("transition_receipt")
            if isinstance(receipt, dict):
                endpoint_id = receipt.get("endpoint_id")
                if isinstance(endpoint_id, str) and endpoint_id.strip():
                    return endpoint_id.strip()
            endpoint = payload.get("actuator_endpoint")
            if isinstance(endpoint, str) and endpoint.strip():
                return endpoint.strip()
            endpoint_response = payload.get("endpoint_response")
            if isinstance(endpoint_response, dict):
                endpoint = endpoint_response.get("actuator_endpoint")
                if isinstance(endpoint, str) and endpoint.strip():
                    return endpoint.strip()
    params = task_dict.get("params", {}) if isinstance(task_dict.get("params"), dict) else {}
    routing = params.get("routing", {}) if isinstance(params.get("routing"), dict) else {}
    hint = routing.get("target_organ_hint")
    if isinstance(hint, str) and hint.strip():
        return f"organ://{hint.strip()}"
    return None


def _extract_transition_receipts(actuator_entries: List[Dict[str, Any]]) -> List[TransitionReceipt]:
    receipts: List[TransitionReceipt] = []
    for item in actuator_entries:
        if not isinstance(item, dict):
            continue
        for container in (item.get("resp"), item.get("output")):
            if not isinstance(container, dict):
                continue
            raw = container.get("transition_receipt")
            if not isinstance(raw, dict):
                continue
            if verify_transition_receipt(raw) is not None:
                continue
            try:
                receipts.append(TransitionReceipt(**raw))
            except Exception:
                continue
    return receipts


def _extract_actuator_result_hash(actuator_entries: List[Dict[str, Any]]) -> str | None:
    for item in actuator_entries:
        if not isinstance(item, dict):
            continue
        for key in ("resp", "output"):
            payload = item.get(key)
            if not isinstance(payload, dict):
                continue
            result_hash = payload.get("result_hash")
            if isinstance(result_hash, str) and result_hash.strip():
                return result_hash.strip()
            endpoint_response = payload.get("endpoint_response")
            if isinstance(endpoint_response, dict):
                nested_hash = endpoint_response.get("result_hash")
                if isinstance(nested_hash, str) and nested_hash.strip():
                    return nested_hash.strip()
    return None


def _extract_hal_capture(envelope: Dict[str, Any]) -> Optional[HALCaptureEnvelope]:
    meta = envelope.get("meta", {}) if isinstance(envelope.get("meta"), dict) else {}
    for key in ("hal_capture", "custody_event"):
        candidate = meta.get(key)
        if isinstance(candidate, dict):
            try:
                return HALCaptureEnvelope(**candidate)
            except Exception:
                continue
    return None


def _extract_media_refs(
    *,
    hal_capture: Optional[HALCaptureEnvelope],
    telemetry_snapshot: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if hal_capture is not None:
        return list(hal_capture.media_refs)
    vision = telemetry_snapshot.get("vision") if isinstance(telemetry_snapshot.get("vision"), list) else []
    if not vision:
        return []
    return [
        {
            "kind": "vision_snapshot",
            "hash": _sha256_hex(_canonical_json(vision)),
            "inline": vision,
        }
    ]


def _extract_endpoint_responses(actuator_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    endpoint_responses: List[Dict[str, Any]] = []
    for item in actuator_entries:
        if not isinstance(item, dict):
            continue
        tool_name = item.get("tool")
        for key in ("resp", "output"):
            payload = item.get(key)
            if not isinstance(payload, dict):
                continue
            nested_endpoint_response = payload.get("endpoint_response")
            if isinstance(nested_endpoint_response, dict) and nested_endpoint_response:
                endpoint_responses.append(
                    {
                        "source": key,
                        "tool": tool_name,
                        "endpoint_response": nested_endpoint_response,
                    }
                )
                continue
            endpoint_like = {}
            for field in ("actuator_endpoint", "status", "device_id", "result_hash", "actuator_ack"):
                if payload.get(field) is not None:
                    endpoint_like[field] = payload.get(field)
            if endpoint_like:
                endpoint_responses.append(
                    {
                        "source": key,
                        "tool": tool_name,
                        "endpoint_response": endpoint_like,
                    }
                )
    return endpoint_responses


def _sha256_hex(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
