from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def build_transition_receipt(
    *,
    intent_id: str,
    token_id: str,
    actuator_endpoint: str,
    hardware_uuid: str,
    actuator_result_hash: str,
    target_zone: Optional[str] = None,
    from_zone: Optional[str] = None,
    to_zone: Optional[str] = None,
    executed_at: Optional[str] = None,
    receipt_nonce: Optional[str] = None,
) -> Dict[str, Any]:
    payload = {
        "intent_id": str(intent_id),
        "token_id": str(token_id),
        "endpoint_id": str(actuator_endpoint),
        "hardware_uuid": str(hardware_uuid),
        "actuator_result_hash": str(actuator_result_hash),
        "target_zone": str(target_zone) if target_zone is not None else None,
        "from_zone": str(from_zone) if from_zone is not None else None,
        "to_zone": str(to_zone) if to_zone is not None else None,
        "executed_at": executed_at or datetime.now(timezone.utc).isoformat(),
        "receipt_nonce": receipt_nonce or str(uuid.uuid4()),
    }
    payload_hash = _sha256_hex(_canonical_json(payload))
    return {
        "receipt_id": str(uuid.uuid4()),
        "proof_type": "hmac_sha256",
        "payload_hash": payload_hash,
        "signature": _sign_payload_hash(payload_hash),
        "signed_payload": payload,
        "endpoint_id": payload["endpoint_id"],
        "hardware_uuid": payload["hardware_uuid"],
    }


def verify_transition_receipt(
    receipt: Dict[str, Any],
    *,
    expected_intent_id: Optional[str] = None,
    expected_token_id: Optional[str] = None,
    expected_endpoint_id: Optional[str] = None,
) -> Optional[str]:
    if not isinstance(receipt, dict):
        return "invalid_receipt"

    payload_hash = receipt.get("payload_hash")
    signature = receipt.get("signature")
    signed_payload = receipt.get("signed_payload")
    proof_type = receipt.get("proof_type")

    if proof_type != "hmac_sha256":
        return "unsupported_proof_type"
    if not isinstance(payload_hash, str) or not payload_hash:
        return "missing_payload_hash"
    if not isinstance(signature, str) or not signature:
        return "missing_signature"
    if not isinstance(signed_payload, dict) or not signed_payload:
        return "missing_signed_payload"

    expected_hash = _sha256_hex(_canonical_json(signed_payload))
    if not hmac.compare_digest(payload_hash, expected_hash):
        return "payload_hash_mismatch"
    if not hmac.compare_digest(signature, _sign_payload_hash(payload_hash)):
        return "signature_mismatch"

    if expected_intent_id is not None and str(signed_payload.get("intent_id")) != str(expected_intent_id):
        return "intent_id_mismatch"
    if expected_token_id is not None and str(signed_payload.get("token_id")) != str(expected_token_id):
        return "token_id_mismatch"
    if expected_endpoint_id is not None and str(signed_payload.get("endpoint_id")) != str(expected_endpoint_id):
        return "endpoint_id_mismatch"

    executed_at = signed_payload.get("executed_at")
    if not isinstance(executed_at, str) or not executed_at.strip():
        return "missing_executed_at"
    try:
        datetime.fromisoformat(executed_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return "invalid_executed_at"

    receipt_nonce = signed_payload.get("receipt_nonce")
    if not isinstance(receipt_nonce, str) or not receipt_nonce.strip():
        return "missing_receipt_nonce"

    return None


def is_attestable_transition_endpoint(endpoint_id: Optional[str]) -> bool:
    if not isinstance(endpoint_id, str):
        return False
    normalized = endpoint_id.strip().lower()
    return normalized.startswith("hal://") or normalized.startswith("robot_sim://")


def _sign_payload_hash(payload_hash: str) -> str:
    secret = os.getenv(
        "SEEDCORE_HAL_RECEIPT_SIGNING_SECRET",
        "seedcore-hal-receipt-secret",
    )
    return hmac.new(
        secret.encode("utf-8"),
        payload_hash.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
