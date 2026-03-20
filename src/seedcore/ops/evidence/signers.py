from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Optional, Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from seedcore.models.evidence_bundle import SignerMetadata


@dataclass(frozen=True)
class SigningResult:
    signature: str
    signing_scheme: str
    signer_id: str
    signer_type: str
    key_ref: Optional[str] = None
    public_key: Optional[str] = None
    attestation_level: str = "baseline"
    config_profile: Optional[str] = None


@dataclass(frozen=True)
class ArtifactSignerPolicy:
    artifact_type: str
    allowed_schemes: tuple[str, ...]
    default_scheme: str
    preferred_scheme: str
    require_attestation: bool = False
    config_profile: Optional[str] = None


class EvidenceSigner(Protocol):
    signing_scheme: str

    def sign(self, payload_hash: str) -> SigningResult:
        ...


class HMACSigner:
    signing_scheme = "hmac_sha256"

    def __init__(
        self,
        *,
        secret: Optional[str] = None,
        signer_id: Optional[str] = None,
        key_ref: Optional[str] = None,
        signer_type: str = "service",
        config_profile: Optional[str] = None,
    ) -> None:
        self._secret = secret or os.getenv(
            "SEEDCORE_EVIDENCE_SIGNING_SECRET",
            "seedcore-dev-evidence-secret",
        )
        self._signer_id = signer_id or os.getenv(
            "SEEDCORE_EVIDENCE_SIGNER_ID",
            "seedcore-evidence-service",
        )
        self._key_ref = key_ref or os.getenv("SEEDCORE_EVIDENCE_SIGNING_KEY_ID")
        self._signer_type = signer_type
        self._config_profile = config_profile or "baseline_hmac"

    def sign(self, payload_hash: str) -> SigningResult:
        signature = hmac.new(
            self._secret.encode("utf-8"),
            payload_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return SigningResult(
            signature=signature,
            signing_scheme=self.signing_scheme,
            signer_id=self._signer_id,
            signer_type=self._signer_type,
            key_ref=self._key_ref,
            attestation_level="baseline",
            config_profile=self._config_profile,
        )


class Ed25519Signer:
    signing_scheme = "ed25519"

    def __init__(
        self,
        *,
        private_key: Ed25519PrivateKey,
        signer_id: Optional[str] = None,
        key_ref: Optional[str] = None,
        signer_type: str = "service",
        config_profile: Optional[str] = None,
    ) -> None:
        self._private_key = private_key
        self._public_key_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self._signer_id = signer_id or os.getenv(
            "SEEDCORE_EVIDENCE_ED25519_SIGNER_ID",
            os.getenv("SEEDCORE_EVIDENCE_SIGNER_ID", "seedcore-evidence-service"),
        )
        self._key_ref = key_ref or os.getenv("SEEDCORE_EVIDENCE_ED25519_KEY_ID") or self._derive_key_ref(
            self._public_key_bytes
        )
        self._signer_type = signer_type
        self._config_profile = config_profile or "attested_ed25519"

    @classmethod
    def from_env(cls) -> Optional["Ed25519Signer"]:
        private_key = _load_ed25519_private_key_from_env()
        if private_key is None:
            return None
        return cls(
            private_key=private_key,
            signer_id=os.getenv("SEEDCORE_EVIDENCE_ED25519_SIGNER_ID"),
            key_ref=os.getenv("SEEDCORE_EVIDENCE_ED25519_KEY_ID"),
            config_profile=os.getenv("SEEDCORE_EVIDENCE_ED25519_PROFILE") or "attested_ed25519",
        )

    def sign(self, payload_hash: str) -> SigningResult:
        signature_bytes = self._private_key.sign(payload_hash.encode("utf-8"))
        return SigningResult(
            signature=base64.b64encode(signature_bytes).decode("ascii"),
            signing_scheme=self.signing_scheme,
            signer_id=self._signer_id,
            signer_type=self._signer_type,
            key_ref=self._key_ref,
            public_key=base64.b64encode(self._public_key_bytes).decode("ascii"),
            attestation_level="attested",
            config_profile=self._config_profile,
        )

    @staticmethod
    def _derive_key_ref(public_key_bytes: bytes) -> str:
        return hashlib.sha256(public_key_bytes).hexdigest()[:16]


DEFAULT_SIGNER_POLICIES: dict[str, ArtifactSignerPolicy] = {
    "policy_receipt": ArtifactSignerPolicy(
        artifact_type="policy_receipt",
        allowed_schemes=("hmac_sha256", "ed25519"),
        default_scheme="hmac_sha256",
        preferred_scheme="ed25519",
        config_profile="policy_receipt_baseline",
    ),
    "evidence_bundle": ArtifactSignerPolicy(
        artifact_type="evidence_bundle",
        allowed_schemes=("hmac_sha256", "ed25519"),
        default_scheme="hmac_sha256",
        preferred_scheme="ed25519",
        config_profile="evidence_bundle_baseline",
    ),
    "transition_receipt": ArtifactSignerPolicy(
        artifact_type="transition_receipt",
        allowed_schemes=("ed25519", "hmac_sha256"),
        default_scheme="hmac_sha256",
        preferred_scheme="ed25519",
        require_attestation=False,
        config_profile="transition_receipt_attested",
    ),
    "hal_capture": ArtifactSignerPolicy(
        artifact_type="hal_capture",
        allowed_schemes=("ed25519", "hmac_sha256"),
        default_scheme="hmac_sha256",
        preferred_scheme="ed25519",
        require_attestation=True,
        config_profile="hal_capture_attested",
    ),
    "jsonld_export": ArtifactSignerPolicy(
        artifact_type="jsonld_export",
        allowed_schemes=(),
        default_scheme="preserve_lineage",
        preferred_scheme="preserve_lineage",
        config_profile="preserve_lineage",
    ),
    "trust_certificate": ArtifactSignerPolicy(
        artifact_type="trust_certificate",
        allowed_schemes=("hmac_sha256", "ed25519"),
        default_scheme="hmac_sha256",
        preferred_scheme="hmac_sha256",
        config_profile="trust_certificate_baseline",
    ),
    "external_signed_intent": ArtifactSignerPolicy(
        artifact_type="external_signed_intent",
        allowed_schemes=("ed25519", "hmac_sha256"),
        default_scheme="ed25519",
        preferred_scheme="ed25519",
        config_profile="external_signed_intent_verified",
    ),
    "execution_token": ArtifactSignerPolicy(
        artifact_type="execution_token",
        allowed_schemes=("hmac_sha256",),
        default_scheme="hmac_sha256",
        preferred_scheme="hmac_sha256",
        config_profile="execution_token_hmac",
    ),
}


def get_signer_policy(
    *,
    artifact_type: str,
    endpoint_id: Optional[str] = None,
    trust_level: Optional[str] = None,
    attested: Optional[bool] = None,
) -> ArtifactSignerPolicy:
    base = DEFAULT_SIGNER_POLICIES.get(artifact_type, DEFAULT_SIGNER_POLICIES["evidence_bundle"])
    env_mode = os.getenv(
        f"SEEDCORE_{artifact_type.upper()}_SIGNER_MODE".replace("-", "_"),
        "",
    ).strip().lower()
    is_attested = bool(attested)
    if not is_attested and isinstance(endpoint_id, str):
        normalized = endpoint_id.strip().lower()
        is_attested = normalized.startswith("hal://") or normalized.startswith("robot_sim://")
    if trust_level == "attested":
        is_attested = True
    if env_mode == "ed25519":
        preferred = "ed25519"
    elif env_mode == "hmac":
        preferred = "hmac_sha256"
    else:
        preferred = base.preferred_scheme if is_attested else base.default_scheme
    return ArtifactSignerPolicy(
        artifact_type=base.artifact_type,
        allowed_schemes=base.allowed_schemes,
        default_scheme=base.default_scheme,
        preferred_scheme=preferred,
        require_attestation=base.require_attestation and is_attested,
        config_profile=base.config_profile,
    )


def resolve_artifact_signer(
    *,
    artifact_type: str,
    endpoint_id: Optional[str] = None,
    trust_level: Optional[str] = None,
    node_id: Optional[str] = None,
) -> EvidenceSigner:
    policy = get_signer_policy(
        artifact_type=artifact_type,
        endpoint_id=endpoint_id,
        trust_level=trust_level,
        attested=None,
    )
    ed25519_signer = Ed25519Signer.from_env()
    if policy.preferred_scheme == "ed25519":
        if ed25519_signer is not None:
            return ed25519_signer
        if policy.require_attestation:
            raise ValueError(f"{artifact_type} requires Ed25519 signing for attested paths")
    return HMACSigner(config_profile=policy.config_profile)


def build_signer_metadata(
    *,
    signing_result: SigningResult,
    node_id: Optional[str] = None,
) -> SignerMetadata:
    return SignerMetadata(
        signer_type=signing_result.signer_type,
        signer_id=signing_result.signer_id,
        signing_scheme=signing_result.signing_scheme,
        key_ref=signing_result.key_ref,
        attestation_level=signing_result.attestation_level,
        node_id=node_id,
        config_profile=signing_result.config_profile,
    )


def resolve_evidence_signer(*, endpoint_id: Optional[str]) -> EvidenceSigner:
    return resolve_artifact_signer(
        artifact_type="evidence_bundle",
        endpoint_id=endpoint_id,
    )


def _load_ed25519_private_key_from_env() -> Optional[Ed25519PrivateKey]:
    encoded = os.getenv("SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_B64", "").strip()
    pem = os.getenv("SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_PEM", "").strip()
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
