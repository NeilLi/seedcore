from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from seedcore.hal.custody.transition_receipts import verify_transition_receipt
from seedcore.models.evidence_bundle import (
    AssetFingerprint,
    EvidenceBundle,
    ExecutionReceipt,
    PolicyReceipt,
    SignerMetadata,
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

    intent_id = str(action_intent.get("intent_id") or "unknown_intent")
    intent_ref = f"governance://action-intent/{intent_id}"
    executed_at = _derive_executed_at(envelope)
    actuator_entries = _extract_actuator_entries(envelope)
    node_id = _derive_node_id(task_dict, actuator_entries, organ_id)
    telemetry_snapshot = _build_telemetry_snapshot(
        task_dict,
        envelope,
        organ_id,
        agent_id,
        executed_at,
        node_id=node_id,
        actuator_entries=actuator_entries,
    )
    receipt = _build_execution_receipt(
        task_dict=task_dict,
        envelope=envelope,
        execution_token=execution_token,
        executed_at=executed_at,
        intent_id=intent_id,
        node_id=node_id,
        actuator_entries=actuator_entries,
    )
    policy_receipt = _build_policy_receipt(
        task_dict=task_dict,
        executed_at=executed_at,
    )
    asset_fingerprint = _build_asset_fingerprint(task_dict)
    return EvidenceBundle(
        intent_ref=intent_ref,
        executed_at=executed_at,
        node_id=node_id,
        telemetry_snapshot=telemetry_snapshot,
        execution_receipt=receipt,
        policy_receipt=policy_receipt,
        asset_fingerprint=asset_fingerprint,
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
            "node_id": node_id,
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
    node_id: str | None,
    actuator_entries: List[Dict[str, Any]],
) -> ExecutionReceipt:
    params = task_dict.get("params", {}) if isinstance(task_dict.get("params"), dict) else {}
    governance = params.get("governance", {}) if isinstance(params.get("governance"), dict) else {}
    policy_decision = governance.get("policy_decision") if isinstance(governance.get("policy_decision"), dict) else {}
    actuator_result_hash = _extract_actuator_result_hash(actuator_entries)
    if actuator_result_hash is None and actuator_entries:
        actuator_result_hash = _sha256_hex(_canonical_json(actuator_entries))
    actuator_endpoint = _extract_actuator_endpoint(task_dict, actuator_entries)
    transition_receipt = _extract_transition_receipt(actuator_entries)
    transition_receipt_hash = (
        _sha256_hex(_canonical_json(transition_receipt))
        if isinstance(transition_receipt, dict)
        else None
    )
    token_id = execution_token.get("token_id") if isinstance(execution_token, dict) else None

    signed_payload = {
        "intent_id": intent_id,
        "task_id": task_dict.get("task_id") or task_dict.get("id"),
        "executed_at": executed_at,
        "token_id": token_id,
        "actuator_result_hash": actuator_result_hash,
        "actuator_endpoint": actuator_endpoint,
        "transition_receipt_hash": transition_receipt_hash,
        "policy_decision": policy_decision,
        "node_id": node_id,
    }
    payload_hash = _sha256_hex(_canonical_json(signed_payload))
    signature = _sign_payload(payload_hash)
    signer = _derive_execution_signer(proof_type="hmac_sha256", transition_receipt=transition_receipt)

    return ExecutionReceipt(
        receipt_id=str(uuid.uuid4()),
        proof_type="hmac_sha256",
        signature=signature,
        payload_hash=payload_hash,
        signed_payload=signed_payload,
        actuator_endpoint=actuator_endpoint,
        actuator_result_hash=actuator_result_hash,
        transition_receipt=transition_receipt if isinstance(transition_receipt, dict) else None,
        transition_receipt_hash=transition_receipt_hash,
        node_id=node_id,
        signer=signer,
    )


def _build_policy_receipt(
    *,
    task_dict: Dict[str, Any],
    executed_at: str,
) -> PolicyReceipt | None:
    params = task_dict.get("params", {}) if isinstance(task_dict.get("params"), dict) else {}
    governance = params.get("governance", {}) if isinstance(params.get("governance"), dict) else {}
    policy_decision = (
        governance.get("policy_decision")
        if isinstance(governance.get("policy_decision"), dict)
        else {}
    )
    execution_token = (
        governance.get("execution_token")
        if isinstance(governance.get("execution_token"), dict)
        else {}
    )
    policy_case = (
        governance.get("policy_case")
        if isinstance(governance.get("policy_case"), dict)
        else {}
    )
    action_intent = (
        governance.get("action_intent")
        if isinstance(governance.get("action_intent"), dict)
        else {}
    )
    if not policy_decision and not execution_token:
        return None

    receipt_id = str(uuid.uuid4())
    policy_snapshot = (
        policy_decision.get("policy_snapshot")
        or policy_case.get("policy_snapshot")
        or action_intent.get("action", {}).get("security_contract", {}).get("version")
    )
    policy_case_hash = (
        _sha256_hex(_canonical_json(policy_case)) if isinstance(policy_case, dict) and policy_case else None
    )
    policy_decision_hash = (
        _sha256_hex(_canonical_json(policy_decision))
        if isinstance(policy_decision, dict) and policy_decision
        else None
    )
    signer = _derive_policy_signer(execution_token)
    issued_at = str(execution_token.get("issued_at") or executed_at)
    return PolicyReceipt(
        receipt_id=receipt_id,
        issued_at=issued_at,
        policy_snapshot=str(policy_snapshot) if policy_snapshot is not None else None,
        policy_case_hash=policy_case_hash,
        policy_decision_hash=policy_decision_hash,
        execution_token=dict(execution_token),
        signer=signer,
    )


def _build_asset_fingerprint(task_dict: Dict[str, Any]) -> AssetFingerprint | None:
    params = task_dict.get("params", {}) if isinstance(task_dict.get("params"), dict) else {}
    governance = params.get("governance", {}) if isinstance(params.get("governance"), dict) else {}
    action_intent = (
        governance.get("action_intent")
        if isinstance(governance.get("action_intent"), dict)
        else {}
    )
    resource = action_intent.get("resource", {}) if isinstance(action_intent.get("resource"), dict) else {}
    multimodal = params.get("multimodal", {}) if isinstance(params.get("multimodal"), dict) else {}
    explicit = (
        governance.get("asset_fingerprint")
        if isinstance(governance.get("asset_fingerprint"), dict)
        else {}
    )
    explicit_hash = explicit.get("fingerprint_hash")
    if isinstance(explicit_hash, str) and explicit_hash.strip():
        return AssetFingerprint(
            fingerprint_hash=explicit_hash.strip(),
            algorithm=str(explicit.get("algorithm") or "sha256"),
            asset_id=str(explicit.get("asset_id") or resource.get("asset_id") or "") or None,
            source_modalities=[
                str(m)
                for m in (explicit.get("source_modalities") or [])
                if isinstance(m, str) and m.strip()
            ],
            components={
                str(k): str(v)
                for k, v in (explicit.get("components") or {}).items()
                if isinstance(k, str)
            },
        )

    provenance_hash = resource.get("provenance_hash") or params.get("provenance_hash")
    asset_id = resource.get("asset_id") or params.get("asset_id")
    if not provenance_hash and not multimodal and not asset_id:
        return None

    modalities: List[str] = []
    components: Dict[str, str] = {}
    if provenance_hash is not None:
        components["provenance_hash"] = str(provenance_hash)
    if isinstance(multimodal.get("detections"), list) and multimodal.get("detections"):
        modalities.append("vision")
        components["vision_hash"] = _sha256_hex(_canonical_json(multimodal.get("detections")))
    if isinstance(multimodal.get("gps"), dict) and multimodal.get("gps"):
        modalities.append("gps")
        components["gps_hash"] = _sha256_hex(_canonical_json(multimodal.get("gps")))
    if isinstance(multimodal.get("sensors"), list) and multimodal.get("sensors"):
        modalities.append("sensors")
        components["sensors_hash"] = _sha256_hex(_canonical_json(multimodal.get("sensors")))
    if isinstance(multimodal.get("sensor_data"), list) and multimodal.get("sensor_data"):
        if "sensors" not in modalities:
            modalities.append("sensors")
        components["sensor_data_hash"] = _sha256_hex(_canonical_json(multimodal.get("sensor_data")))

    fingerprint_payload = {
        "asset_id": asset_id,
        "provenance_hash": provenance_hash,
        "components": components,
    }
    return AssetFingerprint(
        fingerprint_hash=_sha256_hex(_canonical_json(fingerprint_payload)),
        algorithm="sha256",
        asset_id=str(asset_id) if asset_id is not None else None,
        source_modalities=modalities,
        components=components,
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
            transition_receipt = (
                container.get("transition_receipt")
                if isinstance(container.get("transition_receipt"), dict)
                else None
            )
            if transition_receipt:
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
            endpoint = container.get("actuator_endpoint")
            device_id = container.get("device_id")
            if isinstance(endpoint, str) and endpoint.strip():
                if isinstance(device_id, str) and device_id.strip():
                    return f"{endpoint.strip()}#{device_id.strip()}"
                return endpoint.strip()
            if isinstance(device_id, str) and device_id.strip():
                return f"device://{device_id.strip()}"
    return f"organ://{organ_id}"


def _derive_execution_signer(
    *,
    proof_type: str,
    transition_receipt: Dict[str, Any] | None,
) -> SignerMetadata:
    if isinstance(transition_receipt, dict):
        return SignerMetadata(
            signer_id=(
                str(transition_receipt.get("endpoint_id"))
                if transition_receipt.get("endpoint_id") is not None
                else None
            ),
            signer_type="transition_receipt",
            key_id=(
                str(transition_receipt.get("key_id"))
                if transition_receipt.get("key_id") is not None
                else None
            ),
            public_key=(
                str(transition_receipt.get("public_key"))
                if transition_receipt.get("public_key") is not None
                else None
            ),
            proof_type=(
                str(transition_receipt.get("proof_type"))
                if transition_receipt.get("proof_type") is not None
                else proof_type
            ),
        )
    return SignerMetadata(
        signer_id=os.getenv("SEEDCORE_EVIDENCE_SIGNER_ID", "seedcore-evidence-service"),
        signer_type="service",
        key_id=os.getenv("SEEDCORE_EVIDENCE_SIGNING_KEY_ID"),
        public_key=None,
        proof_type=proof_type,
    )


def _derive_policy_signer(execution_token: Dict[str, Any]) -> SignerMetadata:
    return SignerMetadata(
        signer_id=str(execution_token.get("issuer") or "seedcore-pdp"),
        signer_type="policy_decision_point",
        key_id=(
            str(execution_token.get("key_id"))
            if execution_token.get("key_id") is not None
            else os.getenv("SEEDCORE_POLICY_SIGNING_KEY_ID")
        ),
        public_key=(
            str(execution_token.get("public_key"))
            if execution_token.get("public_key") is not None
            else None
        ),
        proof_type=(
            str(execution_token.get("proof_type"))
            if execution_token.get("proof_type") is not None
            else "hmac_sha256"
        ),
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


def _extract_transition_receipt(actuator_entries: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    for item in actuator_entries:
        if not isinstance(item, dict):
            continue
        for container in (item.get("resp"), item.get("output")):
            if not isinstance(container, dict):
                continue
            receipt = container.get("transition_receipt")
            if isinstance(receipt, dict):
                token_id = (
                    receipt.get("signed_payload", {}).get("token_id")
                    if isinstance(receipt.get("signed_payload"), dict)
                    else None
                )
                intent_id = (
                    receipt.get("signed_payload", {}).get("intent_id")
                    if isinstance(receipt.get("signed_payload"), dict)
                    else None
                )
                endpoint_id = (
                    receipt.get("signed_payload", {}).get("endpoint_id")
                    if isinstance(receipt.get("signed_payload"), dict)
                    else None
                )
                if (
                    verify_transition_receipt(
                        receipt,
                        expected_token_id=str(token_id) if token_id is not None else None,
                        expected_intent_id=str(intent_id) if intent_id is not None else None,
                        expected_endpoint_id=str(endpoint_id) if endpoint_id is not None else None,
                    )
                    is None
                ):
                    return receipt
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
