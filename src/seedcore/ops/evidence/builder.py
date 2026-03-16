from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from seedcore.models.evidence_bundle import EvidenceBundle, ExecutionReceipt


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

    intent_id = str(action_intent.get("intent_id") or "unknown_intent")
    intent_ref = f"governance://action-intent/{intent_id}"
    executed_at = _derive_executed_at(envelope)
    telemetry_snapshot = _build_telemetry_snapshot(task_dict, envelope, organ_id, agent_id, executed_at)
    receipt = _build_execution_receipt(
        task_dict=task_dict,
        envelope=envelope,
        execution_token=execution_token,
        executed_at=executed_at,
        intent_id=intent_id,
    )
    return EvidenceBundle(
        intent_ref=intent_ref,
        executed_at=executed_at,
        telemetry_snapshot=telemetry_snapshot,
        execution_receipt=receipt,
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


def _build_telemetry_snapshot(
    task_dict: Dict[str, Any],
    envelope: Dict[str, Any],
    organ_id: str,
    agent_id: str,
    executed_at: str,
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
    actuator_entries = _extract_actuator_entries(envelope)

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
                sensors.append(
                    {
                        "source": "tuya",
                        "device_id": resp.get("device_id"),
                        "status": resp.get("status"),
                    }
                )

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

    endpoint_responses = _extract_endpoint_responses(actuator_entries)

    return {
        "executed_by": {
            "organ_id": organ_id,
            "agent_id": agent_id,
        },
        "captured_at": executed_at,
        "vision": vision,
        "sensors": sensors,
        "gps": gps,
        "zone_checks": zone_checks,
        "multimodal": multimodal,
        "endpoint_responses": endpoint_responses,
    }


def _build_execution_receipt(
    *,
    task_dict: Dict[str, Any],
    envelope: Dict[str, Any],
    execution_token: Dict[str, Any],
    executed_at: str,
    intent_id: str,
) -> ExecutionReceipt:
    params = task_dict.get("params", {}) if isinstance(task_dict.get("params"), dict) else {}
    governance = params.get("governance", {}) if isinstance(params.get("governance"), dict) else {}
    policy_decision = governance.get("policy_decision") if isinstance(governance.get("policy_decision"), dict) else {}
    actuator_entries = _extract_actuator_entries(envelope)
    actuator_result_hash = _extract_actuator_result_hash(actuator_entries)
    if actuator_result_hash is None and actuator_entries:
        actuator_result_hash = _sha256_hex(_canonical_json(actuator_entries))
    actuator_endpoint = _extract_actuator_endpoint(task_dict, actuator_entries)
    token_id = execution_token.get("token_id") if isinstance(execution_token, dict) else None

    signed_payload = {
        "intent_id": intent_id,
        "task_id": task_dict.get("task_id") or task_dict.get("id"),
        "executed_at": executed_at,
        "token_id": token_id,
        "actuator_result_hash": actuator_result_hash,
        "actuator_endpoint": actuator_endpoint,
        "policy_decision": policy_decision,
    }
    payload_hash = _sha256_hex(_canonical_json(signed_payload))
    signature = _sign_payload(payload_hash)

    return ExecutionReceipt(
        receipt_id=str(uuid.uuid4()),
        signature=signature,
        payload_hash=payload_hash,
        signed_payload=signed_payload,
        actuator_endpoint=actuator_endpoint,
        actuator_result_hash=actuator_result_hash,
    )


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
        resp = item.get("resp")
        if isinstance(resp, dict):
            if isinstance(resp.get("actuator_endpoint"), str) and resp.get("actuator_endpoint"):
                return str(resp.get("actuator_endpoint"))
            if resp.get("device_id"):
                return f"tuya://{resp.get('device_id')}"
            if resp.get("robot_state") is not None:
                return "hal://reachy"
        output = item.get("output")
        if isinstance(output, dict):
            if isinstance(output.get("actuator_endpoint"), str) and output.get("actuator_endpoint"):
                return str(output.get("actuator_endpoint"))
            if output.get("device_id"):
                return f"tool://{item.get('tool')}/{output.get('device_id')}"
            if output.get("robot_state") is not None:
                return f"tool://{item.get('tool') or 'hal'}"
            endpoint_response = output.get("endpoint_response")
            if isinstance(endpoint_response, dict):
                endpoint = endpoint_response.get("actuator_endpoint")
                if isinstance(endpoint, str) and endpoint.strip():
                    return endpoint

    params = task_dict.get("params", {}) if isinstance(task_dict.get("params"), dict) else {}
    routing = params.get("routing", {}) if isinstance(params.get("routing"), dict) else {}
    hint = routing.get("target_organ_hint")
    if isinstance(hint, str) and hint.strip():
        return f"organ://{hint}"
    return None


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
                return result_hash
            endpoint_response = payload.get("endpoint_response")
            if isinstance(endpoint_response, dict):
                nested_hash = endpoint_response.get("result_hash")
                if isinstance(nested_hash, str) and nested_hash.strip():
                    return nested_hash
    return None


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


def _sign_payload(payload_hash: str) -> str:
    secret = os.getenv("SEEDCORE_EVIDENCE_SIGNING_SECRET", "seedcore-dev-evidence-secret")
    return hmac.new(
        secret.encode("utf-8"),
        payload_hash.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _sha256_hex(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
