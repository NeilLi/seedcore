from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from seedcore.models.evidence_bundle import SignerMetadata, TransitionReceipt
from seedcore.ops.evidence.policy import (
    canonical_json,
    load_ed25519_public_key,
    resolve_public_key_from_registry,
    sha256_hex,
    verify_payload_signature,
)
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
    payload_hash = sha256_hex(canonical_json(payload))
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
    return verify_transition_receipt_result(
        receipt,
        expected_intent_id=expected_intent_id,
        expected_token_id=expected_token_id,
        expected_endpoint_id=expected_endpoint_id,
    ).get("error")


def verify_transition_receipt_result(
    receipt: Dict[str, Any],
    *,
    expected_intent_id: Optional[str] = None,
    expected_token_id: Optional[str] = None,
    expected_endpoint_id: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        model = TransitionReceipt(**dict(receipt))
    except Exception:
        return {
            "artifact_type": "transition_receipt",
            "verified": False,
            "error": "invalid_receipt",
            "policy": {},
        }

    payload = model.model_dump(mode="json", exclude={"payload_hash", "signer_metadata", "signature"})
    expected_hash = sha256_hex(canonical_json(payload))
    if not hmac.compare_digest(model.payload_hash, expected_hash):
        return {
            "artifact_type": "transition_receipt",
            "verified": False,
            "error": "payload_hash_mismatch",
            "policy": {},
        }

    verification = verify_payload_signature(
        artifact_type="transition_receipt",
        payload=payload,
        signer_metadata=model.signer_metadata,
        signature=model.signature,
        endpoint_id=model.endpoint_id,
        trust_level=(
            "attested"
            if is_attestable_transition_endpoint(model.endpoint_id)
            else "baseline"
        ),
        attested=is_attestable_transition_endpoint(model.endpoint_id),
        public_key_resolver=_resolve_ed25519_public_key,
        secret_resolver=lambda _metadata: os.getenv(
            "SEEDCORE_HAL_RECEIPT_SIGNING_SECRET",
            "seedcore-hal-receipt-secret",
        ),
    )
    if verification.get("error") is not None:
        return verification

    if expected_intent_id is not None and model.intent_id != str(expected_intent_id):
        verification["verified"] = False
        verification["error"] = "intent_id_mismatch"
        return verification
    if expected_token_id is not None and model.execution_token_id != str(expected_token_id):
        verification["verified"] = False
        verification["error"] = "token_id_mismatch"
        return verification
    if expected_endpoint_id is not None and model.endpoint_id != str(expected_endpoint_id):
        verification["verified"] = False
        verification["error"] = "endpoint_id_mismatch"
        return verification

    try:
        datetime.fromisoformat(model.executed_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        verification["verified"] = False
        verification["error"] = "invalid_executed_at"
        return verification

    if not model.receipt_nonce.strip():
        verification["verified"] = False
        verification["error"] = "missing_receipt_nonce"
        return verification
    return verification


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


def _resolve_ed25519_public_key(metadata: SignerMetadata) -> Optional[Ed25519PublicKey]:
    return resolve_public_key_from_registry(
        metadata,
        registry_env="SEEDCORE_HAL_RECEIPT_PUBLIC_KEYS_JSON",
        candidate_fields=("node_id", "signer_id", "key_ref"),
    )


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
    return load_ed25519_public_key(value)


def _derive_key_ref(public_key_bytes: bytes) -> str:
    return hashlib.sha256(public_key_bytes).hexdigest()[:16]
