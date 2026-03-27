from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any, Callable, Mapping, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from seedcore.models.evidence_bundle import SignerMetadata
from seedcore.ops.evidence.signers import ArtifactSignerPolicy, ECDSA_P256_SCHEME, get_signer_policy

PublicKeyResolver = Callable[[SignerMetadata], Optional[Any]]
SecretResolver = Callable[[SignerMetadata], Optional[str]]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_policy_summary(
    *,
    artifact_type: str,
    endpoint_id: Optional[str] = None,
    trust_level: Optional[str] = None,
    attested: Optional[bool] = None,
) -> dict[str, Any]:
    policy = get_signer_policy(
        artifact_type=artifact_type,
        endpoint_id=endpoint_id,
        trust_level=trust_level,
        attested=attested,
    )
    return _policy_to_dict(policy)


def verify_payload_signature(
    *,
    artifact_type: str,
    payload: Mapping[str, Any],
    signer_metadata: Mapping[str, Any] | SignerMetadata,
    signature: str,
    endpoint_id: Optional[str] = None,
    trust_level: Optional[str] = None,
    attested: Optional[bool] = None,
    public_key_resolver: Optional[PublicKeyResolver] = None,
    secret_resolver: Optional[SecretResolver] = None,
) -> dict[str, Any]:
    policy = get_signer_policy(
        artifact_type=artifact_type,
        endpoint_id=endpoint_id,
        trust_level=trust_level,
        attested=attested,
    )
    payload_hash = sha256_hex(canonical_json(dict(payload)))
    metadata = _coerce_signer_metadata(signer_metadata)
    result = {
        "artifact_type": artifact_type,
        "verified": False,
        "error": None,
        "payload_hash": payload_hash,
        "signing_scheme": None,
        "attestation_level": None,
        "policy": _policy_to_dict(policy),
    }
    if metadata is None:
        result["error"] = "invalid_signer_metadata"
        return result

    result["signing_scheme"] = metadata.signing_scheme
    result["attestation_level"] = metadata.attestation_level
    if policy.allowed_schemes and metadata.signing_scheme not in policy.allowed_schemes:
        result["error"] = "signing_scheme_not_allowed"
        return result
    if policy.require_attestation and (
        metadata.signing_scheme != "ed25519" or metadata.attestation_level != "attested"
    ):
        result["error"] = "attestation_required"
        return result

    if metadata.signing_scheme == "hmac_sha256":
        secret = (
            secret_resolver(metadata)
            if secret_resolver is not None
            else os.getenv(
                "SEEDCORE_EVIDENCE_SIGNING_SECRET",
                "seedcore-dev-evidence-secret",
            )
        )
        if not isinstance(secret, str) or not secret:
            result["error"] = "missing_hmac_secret"
            return result
        expected = hmac.new(
            secret.encode("utf-8"),
            payload_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            result["error"] = "signature_mismatch"
            return result
        result["verified"] = True
        return result

    if metadata.signing_scheme == "ed25519":
        public_key = public_key_resolver(metadata) if public_key_resolver is not None else None
        if public_key is None:
            result["error"] = "missing_public_key"
            return result
        try:
            signature_bytes = base64.b64decode(signature, validate=True)
        except Exception:
            result["error"] = "invalid_signature_encoding"
            return result
        try:
            public_key.verify(signature_bytes, payload_hash.encode("utf-8"))
        except Exception:
            result["error"] = "signature_mismatch"
            return result
        result["verified"] = True
        return result

    if metadata.signing_scheme == ECDSA_P256_SCHEME:
        public_key = public_key_resolver(metadata) if public_key_resolver is not None else None
        if public_key is None or not isinstance(public_key, ec.EllipticCurvePublicKey):
            result["error"] = "missing_public_key"
            return result
        try:
            signature_bytes = base64.b64decode(signature, validate=True)
        except Exception:
            result["error"] = "invalid_signature_encoding"
            return result
        try:
            public_key.verify(
                signature_bytes,
                payload_hash.encode("utf-8"),
                ec.ECDSA(hashlib_to_cryptography_hash("sha256")),
            )
        except Exception:
            result["error"] = "signature_mismatch"
            return result
        result["verified"] = True
        return result

    result["error"] = "unsupported_signing_scheme"
    return result


def load_ed25519_public_key(value: str) -> Optional[Ed25519PublicKey]:
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


def load_p256_public_key(value: str) -> Optional[ec.EllipticCurvePublicKey]:
    try:
        if "BEGIN PUBLIC KEY" in value:
            loaded = serialization.load_pem_public_key(value.encode("utf-8"))
            if isinstance(loaded, ec.EllipticCurvePublicKey):
                return loaded
            return None
        key_bytes = base64.b64decode(value, validate=True)
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), key_bytes)
    except Exception:
        return None


def resolve_public_key_from_registry(
    metadata: SignerMetadata,
    *,
    registry_env: str,
    candidate_fields: tuple[str, ...] = ("key_ref", "signer_id", "node_id"),
) -> Optional[Ed25519PublicKey]:
    raw_registry = os.getenv(registry_env, "").strip()
    if not raw_registry:
        return None
    try:
        registry = json.loads(raw_registry)
    except Exception:
        return None
    if not isinstance(registry, dict):
        return None
    for field in candidate_fields:
        candidate = getattr(metadata, field, None)
        if isinstance(candidate, str) and candidate.strip():
            public_key = _extract_registry_public_key(registry.get(candidate.strip()))
            if public_key is not None:
                return load_public_key_for_scheme(metadata.signing_scheme, public_key)
    for value in registry.values():
        if not isinstance(value, dict):
            continue
        if value.get("key_id") == metadata.key_ref:
            public_key = _extract_registry_public_key(value)
            if public_key is not None:
                return load_public_key_for_scheme(metadata.signing_scheme, public_key)
    return None


def resolve_hmac_secret_from_registry(
    metadata: SignerMetadata,
    *,
    registry_env: str,
    candidate_fields: tuple[str, ...] = ("signer_id", "key_ref", "node_id"),
) -> Optional[str]:
    raw_registry = os.getenv(registry_env, "").strip()
    if not raw_registry:
        return None
    try:
        registry = json.loads(raw_registry)
    except Exception:
        return None
    if not isinstance(registry, dict):
        return None
    for field in candidate_fields:
        candidate = getattr(metadata, field, None)
        if isinstance(candidate, str) and candidate.strip():
            secret = registry.get(candidate.strip())
            if isinstance(secret, str) and secret.strip():
                return secret.strip()
    return None


def _coerce_signer_metadata(
    signer_metadata: Mapping[str, Any] | SignerMetadata,
) -> Optional[SignerMetadata]:
    try:
        if isinstance(signer_metadata, SignerMetadata):
            return signer_metadata
        return SignerMetadata(**dict(signer_metadata))
    except Exception:
        return None


def _policy_to_dict(policy: ArtifactSignerPolicy) -> dict[str, Any]:
    return {
        "artifact_type": policy.artifact_type,
        "allowed_schemes": list(policy.allowed_schemes),
        "default_scheme": policy.default_scheme,
        "preferred_scheme": policy.preferred_scheme,
        "require_attestation": bool(policy.require_attestation),
        "config_profile": policy.config_profile,
    }


def _extract_registry_public_key(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        public_key = value.get("public_key")
        if isinstance(public_key, str) and public_key.strip():
            return public_key.strip()
    return None


def load_public_key_for_scheme(signing_scheme: str, value: str) -> Optional[Any]:
    if signing_scheme == "ed25519":
        return load_ed25519_public_key(value)
    if signing_scheme == ECDSA_P256_SCHEME:
        return load_p256_public_key(value)
    return None


def hashlib_to_cryptography_hash(name: str):
    if name == "sha256":
        from cryptography.hazmat.primitives import hashes

        return hashes.SHA256()
    raise ValueError(f"unsupported_hash:{name}")
