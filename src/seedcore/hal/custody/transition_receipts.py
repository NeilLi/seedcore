from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


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
    ed25519_private_key = _load_ed25519_private_key()
    if ed25519_private_key is not None:
        public_key = ed25519_private_key.public_key()
        public_key_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        key_id = os.getenv("SEEDCORE_HAL_RECEIPT_KEY_ID") or _derive_key_id(public_key_bytes)
        signature = base64.b64encode(
            ed25519_private_key.sign(payload_hash.encode("utf-8"))
        ).decode("ascii")
        return {
            "receipt_id": str(uuid.uuid4()),
            "proof_type": "ed25519",
            "payload_hash": payload_hash,
            "signature": signature,
            "signed_payload": payload,
            "endpoint_id": payload["endpoint_id"],
            "hardware_uuid": payload["hardware_uuid"],
            "key_id": key_id,
            "public_key": base64.b64encode(public_key_bytes).decode("ascii"),
        }
    logger.warning("attested endpoint fell back to HMAC signature. Ed25519 is preferred.")
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

    if not isinstance(payload_hash, str) or not payload_hash:
        return "missing_payload_hash"
    if not isinstance(signature, str) or not signature:
        return "missing_signature"
    if not isinstance(signed_payload, dict) or not signed_payload:
        return "missing_signed_payload"

    expected_hash = _sha256_hex(_canonical_json(signed_payload))
    if not hmac.compare_digest(payload_hash, expected_hash):
        return "payload_hash_mismatch"
    if proof_type == "hmac_sha256":
        logger.warning("attested endpoint verified HMAC signature. Ed25519 is preferred.")
        if not hmac.compare_digest(signature, _sign_payload_hash(payload_hash)):
            return "signature_mismatch"
    elif proof_type == "ed25519":
        verification_error = _verify_ed25519_signature(
            receipt=receipt,
            payload_hash=payload_hash,
        )
        if verification_error is not None:
            return verification_error
    else:
        return "unsupported_proof_type"

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


def _verify_ed25519_signature(
    *,
    receipt: Dict[str, Any],
    payload_hash: str,
) -> Optional[str]:
    public_key = _resolve_ed25519_public_key(receipt)
    if public_key is None:
        return "missing_public_key"

    signature = receipt.get("signature")
    try:
        signature_bytes = base64.b64decode(str(signature), validate=True)
    except Exception:
        return "invalid_signature_encoding"

    try:
        public_key.verify(signature_bytes, payload_hash.encode("utf-8"))
    except Exception:
        return "signature_mismatch"
    return None


def _resolve_ed25519_public_key(receipt: Dict[str, Any]) -> Optional[Ed25519PublicKey]:
    key_material = _lookup_registered_public_key(receipt)
    if key_material is None and _trust_embedded_public_key():
        embedded = receipt.get("public_key")
        if isinstance(embedded, str) and embedded.strip():
            key_material = embedded.strip()
    if key_material is None:
        return None
    return _load_ed25519_public_key(key_material)


def _lookup_registered_public_key(receipt: Dict[str, Any]) -> Optional[str]:
    raw_registry = os.getenv("SEEDCORE_HAL_RECEIPT_PUBLIC_KEYS_JSON", "").strip()
    if not raw_registry:
        return None
    try:
        registry = json.loads(raw_registry)
    except Exception:
        return None
    if not isinstance(registry, dict):
        return None

    signed_payload = (
        receipt.get("signed_payload")
        if isinstance(receipt.get("signed_payload"), dict)
        else {}
    )
    endpoint_id = signed_payload.get("endpoint_id")
    key_id = receipt.get("key_id")

    direct_candidates = []
    if isinstance(endpoint_id, str) and endpoint_id.strip():
        direct_candidates.append(endpoint_id.strip())
    if isinstance(key_id, str) and key_id.strip():
        direct_candidates.append(key_id.strip())

    for candidate in direct_candidates:
        public_key = _extract_registry_public_key(registry.get(candidate))
        if public_key is not None:
            return public_key

    for value in registry.values():
        if not isinstance(value, dict):
            continue
        if key_id and value.get("key_id") == key_id:
            public_key = _extract_registry_public_key(value)
            if public_key is not None:
                return public_key
        if endpoint_id and value.get("endpoint_id") == endpoint_id:
            public_key = _extract_registry_public_key(value)
            if public_key is not None:
                return public_key
    return None


def _extract_registry_public_key(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("public_key", "public_key_b64"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


def _trust_embedded_public_key() -> bool:
    return os.getenv(
        "SEEDCORE_HAL_RECEIPT_TRUST_EMBEDDED_PUBLIC_KEY",
        "false",
    ).lower() in {"1", "true", "yes"}


def _load_ed25519_private_key() -> Optional[Ed25519PrivateKey]:
    encoded = os.getenv("SEEDCORE_HAL_RECEIPT_PRIVATE_KEY_B64", "").strip()
    pem = os.getenv("SEEDCORE_HAL_RECEIPT_PRIVATE_KEY_PEM", "").strip()
    if pem:
        try:
            return serialization.load_pem_private_key(
                pem.encode("utf-8"),
                password=None,
            )
        except Exception:
            return None
    if not encoded:
        return None
    try:
        key_bytes = base64.b64decode(encoded, validate=True)
        return Ed25519PrivateKey.from_private_bytes(key_bytes)
    except Exception:
        return None


def _load_ed25519_public_key(value: str) -> Optional[Ed25519PublicKey]:
    try:
        if "BEGIN PUBLIC KEY" in value:
            return serialization.load_pem_public_key(value.encode("utf-8"))
        key_bytes = base64.b64decode(value, validate=True)
        return Ed25519PublicKey.from_public_bytes(key_bytes)
    except Exception:
        return None


def _derive_key_id(public_key_bytes: bytes) -> str:
    return hashlib.sha256(public_key_bytes).hexdigest()[:16]


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
