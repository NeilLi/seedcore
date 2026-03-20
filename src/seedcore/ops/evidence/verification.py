from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any, Mapping, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from seedcore.models.evidence_bundle import EvidenceBundle, HALCaptureEnvelope, PolicyReceipt, SignerMetadata
from seedcore.ops.evidence.signers import build_signer_metadata, resolve_artifact_signer


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_signed_artifact(
    *,
    artifact_type: str,
    payload: dict[str, Any],
    endpoint_id: Optional[str] = None,
    trust_level: Optional[str] = None,
    node_id: Optional[str] = None,
) -> tuple[str, SignerMetadata, str]:
    signer = resolve_artifact_signer(
        artifact_type=artifact_type,
        endpoint_id=endpoint_id,
        trust_level=trust_level,
        node_id=node_id,
    )
    payload_hash = sha256_hex(canonical_json(payload))
    signing_result = signer.sign(payload_hash)
    signer_metadata = build_signer_metadata(
        signing_result=signing_result,
        node_id=node_id,
    )
    return payload_hash, signer_metadata, signing_result.signature


def verify_artifact_signature(
    *,
    payload: Mapping[str, Any],
    signer_metadata: Mapping[str, Any] | SignerMetadata,
    signature: str,
) -> Optional[str]:
    try:
        metadata = (
            signer_metadata
            if isinstance(signer_metadata, SignerMetadata)
            else SignerMetadata(**dict(signer_metadata))
        )
    except Exception:
        return "invalid_signer_metadata"

    payload_hash = sha256_hex(canonical_json(dict(payload)))
    if metadata.signing_scheme == "hmac_sha256":
        expected = hmac.new(
            os.getenv(
                "SEEDCORE_EVIDENCE_SIGNING_SECRET",
                "seedcore-dev-evidence-secret",
            ).encode("utf-8"),
            payload_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return "signature_mismatch"
        return None

    if metadata.signing_scheme == "ed25519":
        public_key = _resolve_ed25519_public_key(metadata)
        if public_key is None:
            return "missing_public_key"
        try:
            signature_bytes = base64.b64decode(signature, validate=True)
        except Exception:
            return "invalid_signature_encoding"
        try:
            public_key.verify(signature_bytes, payload_hash.encode("utf-8"))
        except Exception:
            return "signature_mismatch"
        return None

    return "unsupported_signing_scheme"


def verify_policy_receipt(receipt: Mapping[str, Any] | PolicyReceipt) -> Optional[str]:
    try:
        model = receipt if isinstance(receipt, PolicyReceipt) else PolicyReceipt(**dict(receipt))
    except Exception:
        return "invalid_policy_receipt"
    payload = model.model_dump(mode="json", exclude={"signature", "signer_metadata"})
    return verify_artifact_signature(
        payload=payload,
        signer_metadata=model.signer_metadata,
        signature=model.signature,
    )


def verify_evidence_bundle(bundle: Mapping[str, Any] | EvidenceBundle) -> Optional[str]:
    try:
        model = bundle if isinstance(bundle, EvidenceBundle) else EvidenceBundle(**dict(bundle))
    except Exception:
        return "invalid_evidence_bundle"
    payload = model.model_dump(mode="json", exclude={"signature", "signer_metadata"})
    return verify_artifact_signature(
        payload=payload,
        signer_metadata=model.signer_metadata,
        signature=model.signature,
    )


def verify_hal_capture_envelope(envelope: Mapping[str, Any] | HALCaptureEnvelope) -> Optional[str]:
    try:
        model = envelope if isinstance(envelope, HALCaptureEnvelope) else HALCaptureEnvelope(**dict(envelope))
    except Exception:
        return "invalid_hal_capture_envelope"
    payload = model.model_dump(mode="json", exclude={"signature", "signer_metadata"})
    return verify_artifact_signature(
        payload=payload,
        signer_metadata=model.signer_metadata,
        signature=model.signature,
    )


def _resolve_ed25519_public_key(metadata: SignerMetadata) -> Optional[Ed25519PublicKey]:
    raw_registry = os.getenv("SEEDCORE_EVIDENCE_PUBLIC_KEYS_JSON", "").strip()
    if not raw_registry:
        return None
    try:
        registry = json.loads(raw_registry)
    except Exception:
        return None
    if not isinstance(registry, dict):
        return None
    for candidate in (metadata.key_ref, metadata.signer_id):
        if isinstance(candidate, str) and candidate.strip():
            material = registry.get(candidate.strip())
            if isinstance(material, str) and material.strip():
                return _load_ed25519_public_key(material.strip())
            if isinstance(material, dict):
                public_key = material.get("public_key")
                if isinstance(public_key, str) and public_key.strip():
                    return _load_ed25519_public_key(public_key.strip())
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
