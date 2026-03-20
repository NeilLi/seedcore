from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from seedcore.models.evidence_bundle import SignerMetadata, TransitionReceipt
from seedcore.ops.evidence.signers import get_signer_policy

logger = logging.getLogger(__name__)


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
        "transition_receipt_id": str(uuid.uuid4()),
        "intent_id": str(intent_id),
        "execution_token_id": str(token_id),
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
    signer_metadata, signature = _sign_transition_payload(
        payload_hash=payload_hash,
        endpoint_id=actuator_endpoint,
    )
    return TransitionReceipt(
        **payload,
        payload_hash=payload_hash,
        signer_metadata=signer_metadata,
        signature=signature,
    ).model_dump(mode="json")


def verify_transition_receipt(
    receipt: Dict[str, Any],
    *,
    expected_intent_id: Optional[str] = None,
    expected_token_id: Optional[str] = None,
    expected_endpoint_id: Optional[str] = None,
) -> Optional[str]:
    try:
        model = TransitionReceipt(**dict(receipt))
    except Exception:
        return "invalid_receipt"

    payload = model.model_dump(mode="json", exclude={"payload_hash", "signer_metadata", "signature"})
    expected_hash = _sha256_hex(_canonical_json(payload))
    if not hmac.compare_digest(model.payload_hash, expected_hash):
        return "payload_hash_mismatch"

    if model.signer_metadata.signing_scheme == "hmac_sha256":
        expected_signature = _sign_payload_hash(model.payload_hash)
        if not hmac.compare_digest(model.signature, expected_signature):
            return "signature_mismatch"
    elif model.signer_metadata.signing_scheme == "ed25519":
        verification_error = _verify_ed25519_signature(model=model)
        if verification_error is not None:
            return verification_error
    else:
        return "unsupported_signing_scheme"

    if expected_intent_id is not None and model.intent_id != str(expected_intent_id):
        return "intent_id_mismatch"
    if expected_token_id is not None and model.execution_token_id != str(expected_token_id):
        return "token_id_mismatch"
    if expected_endpoint_id is not None and model.endpoint_id != str(expected_endpoint_id):
        return "endpoint_id_mismatch"

    try:
        datetime.fromisoformat(model.executed_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return "invalid_executed_at"

    if not model.receipt_nonce.strip():
        return "missing_receipt_nonce"
    return None


def is_attestable_transition_endpoint(endpoint_id: Optional[str]) -> bool:
    if not isinstance(endpoint_id, str):
        return False
    normalized = endpoint_id.strip().lower()
    return normalized.startswith("hal://") or normalized.startswith("robot_sim://")


def _sign_transition_payload(
    *,
    payload_hash: str,
    endpoint_id: str,
) -> tuple[SignerMetadata, str]:
    policy = get_signer_policy(
        artifact_type="transition_receipt",
        endpoint_id=endpoint_id,
        attested=is_attestable_transition_endpoint(endpoint_id),
    )
    private_key = _load_ed25519_private_key()
    if policy.preferred_scheme == "ed25519" and private_key is not None:
        public_key = private_key.public_key()
        public_key_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        key_ref = os.getenv("SEEDCORE_HAL_RECEIPT_KEY_ID") or _derive_key_ref(public_key_bytes)
        signature = base64.b64encode(
            private_key.sign(payload_hash.encode("utf-8"))
        ).decode("ascii")
        metadata = SignerMetadata(
            signer_type="hal_endpoint",
            signer_id=endpoint_id,
            signing_scheme="ed25519",
            key_ref=key_ref,
            attestation_level="attested",
            node_id=endpoint_id,
            config_profile=policy.config_profile,
        )
        return metadata, signature

    if policy.require_attestation:
        raise ValueError("transition_receipt requires Ed25519 signing on attested endpoints")

    metadata = SignerMetadata(
        signer_type="hal_endpoint",
        signer_id=endpoint_id,
        signing_scheme="hmac_sha256",
        key_ref=os.getenv("SEEDCORE_HAL_RECEIPT_KEY_ID"),
        attestation_level="baseline",
        node_id=endpoint_id,
        config_profile=policy.config_profile,
    )
    return metadata, _sign_payload_hash(payload_hash)


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


def _verify_ed25519_signature(*, model: TransitionReceipt) -> Optional[str]:
    public_key = _resolve_ed25519_public_key(model)
    if public_key is None:
        return "missing_public_key"
    try:
        signature_bytes = base64.b64decode(model.signature, validate=True)
    except Exception:
        return "invalid_signature_encoding"
    try:
        public_key.verify(signature_bytes, model.payload_hash.encode("utf-8"))
    except Exception:
        return "signature_mismatch"
    return None


def _resolve_ed25519_public_key(model: TransitionReceipt) -> Optional[Ed25519PublicKey]:
    raw_registry = os.getenv("SEEDCORE_HAL_RECEIPT_PUBLIC_KEYS_JSON", "").strip()
    if not raw_registry:
        return None
    try:
        registry = json.loads(raw_registry)
    except Exception:
        return None
    if not isinstance(registry, dict):
        return None
    for candidate in (model.endpoint_id, model.signer_metadata.key_ref):
        if isinstance(candidate, str) and candidate.strip():
            value = registry.get(candidate.strip())
            public_key = _extract_registry_public_key(value)
            if public_key is not None:
                return _load_ed25519_public_key(public_key)
    for value in registry.values():
        if not isinstance(value, dict):
            continue
        if value.get("key_id") == model.signer_metadata.key_ref:
            public_key = _extract_registry_public_key(value)
            if public_key is not None:
                return _load_ed25519_public_key(public_key)
    return None


def _extract_registry_public_key(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        candidate = value.get("public_key")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _load_ed25519_private_key() -> Optional[Ed25519PrivateKey]:
    encoded = os.getenv("SEEDCORE_HAL_RECEIPT_PRIVATE_KEY_B64", "").strip()
    pem = os.getenv("SEEDCORE_HAL_RECEIPT_PRIVATE_KEY_PEM", "").strip()
    if pem:
        try:
            loaded = serialization.load_pem_private_key(
                pem.encode("utf-8"),
                password=None,
            )
            if isinstance(loaded, Ed25519PrivateKey):
                return loaded
            return None
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
            loaded = serialization.load_pem_public_key(value.encode("utf-8"))
            if isinstance(loaded, Ed25519PublicKey):
                return loaded
            return None
        key_bytes = base64.b64decode(value, validate=True)
        return Ed25519PublicKey.from_public_bytes(key_bytes)
    except Exception:
        return None


def _derive_key_ref(public_key_bytes: bytes) -> str:
    return hashlib.sha256(public_key_bytes).hexdigest()[:16]


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
