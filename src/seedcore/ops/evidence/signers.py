from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Optional, Protocol

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from seedcore.models.evidence_bundle import (
    AttestationProof,
    KeyBindingProof,
    ReplayProof,
    SignerMetadata,
    TransparencyProof,
    TrustProof,
)
from seedcore.ops.evidence.transparency import anchor_receipt_hash


ECDSA_P256_SCHEME = "ecdsa_p256_sha256"
RESTRICTED_CUSTODY_TRANSFER_WORKFLOW_TYPES = {
    "custody_transfer",
    "restricted_custody_transfer",
}
_SOFTWARE_COUNTERS: dict[str, int] = {}
_SOFTWARE_COUNTER_LOCK = Lock()


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name, "true" if default else "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


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
    trust_anchor_type: str = "software"
    key_algorithm: str = ""
    trust_proof: Optional[TrustProof] = None
    revocation_id: Optional[str] = None


@dataclass(frozen=True)
class ArtifactSignerPolicy:
    artifact_type: str
    allowed_schemes: tuple[str, ...]
    default_scheme: str
    preferred_scheme: str
    require_attestation: bool = False
    config_profile: Optional[str] = None


@dataclass(frozen=True)
class SignerRequest:
    artifact_type: str
    signer_profile: str
    payload_hash: str
    endpoint_id: Optional[str] = None
    node_id: Optional[str] = None
    trust_level: Optional[str] = None
    workflow_type: Optional[str] = None
    receipt_nonce: Optional[str] = None
    previous_receipt_hash: Optional[str] = None
    previous_receipt_counter: Optional[int] = None
    require_trust_anchor: Optional[str] = None
    required_key_algorithm: Optional[str] = None
    transparency_enabled: bool = False


class SignerProvider(Protocol):
    provider_name: str

    def sign_hash(self, request: SignerRequest) -> SigningResult:
        ...


class EvidenceSigner(Protocol):
    signing_scheme: str

    def sign(self, payload_hash: str) -> SigningResult:
        ...


class LegacyHmacSignerProvider:
    provider_name = "legacy_hmac"

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

    def sign_hash(self, request: SignerRequest) -> SigningResult:
        signature = hmac.new(
            self._secret.encode("utf-8"),
            request.payload_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return SigningResult(
            signature=signature,
            signing_scheme="hmac_sha256",
            signer_id=self._signer_id,
            signer_type=self._signer_type,
            key_ref=self._key_ref,
            attestation_level="baseline",
            config_profile=self._config_profile,
            trust_anchor_type="software",
            key_algorithm="hmac_sha256",
            trust_proof=_build_trust_proof(
                request,
                trust_anchor_type="software",
                key_algorithm="hmac_sha256",
                key_ref=self._key_ref or f"legacy-hmac:{self._signer_id}",
                public_key_material=None,
                signature=signature,
                attestation_level="baseline",
                revocation_id=f"hmac:{self._key_ref or self._signer_id}",
            ),
            revocation_id=f"hmac:{self._key_ref or self._signer_id}",
        )


class HMACSigner(LegacyHmacSignerProvider):
    signing_scheme = "hmac_sha256"

    def sign(self, payload_hash: str) -> SigningResult:
        return self.sign_hash(
            SignerRequest(
                artifact_type="legacy",
                signer_profile="legacy",
                payload_hash=payload_hash,
            )
        )


class LegacyEd25519SignerProvider:
    provider_name = "legacy_ed25519"

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
        self._key_ref = key_ref or os.getenv("SEEDCORE_EVIDENCE_ED25519_KEY_ID") or _derive_key_ref(
            self._public_key_bytes
        )
        self._signer_type = signer_type
        self._config_profile = config_profile or "attested_ed25519"

    @classmethod
    def from_env(cls) -> Optional["LegacyEd25519SignerProvider"]:
        private_key = _load_ed25519_private_key_from_env()
        if private_key is None:
            return None
        return cls(
            private_key=private_key,
            signer_id=os.getenv("SEEDCORE_EVIDENCE_ED25519_SIGNER_ID"),
            key_ref=os.getenv("SEEDCORE_EVIDENCE_ED25519_KEY_ID"),
            config_profile=os.getenv("SEEDCORE_EVIDENCE_ED25519_PROFILE") or "attested_ed25519",
        )

    def sign_hash(self, request: SignerRequest) -> SigningResult:
        signature_bytes = self._private_key.sign(request.payload_hash.encode("utf-8"))
        public_key = base64.b64encode(self._public_key_bytes).decode("ascii")
        signature = base64.b64encode(signature_bytes).decode("ascii")
        return SigningResult(
            signature=signature,
            signing_scheme="ed25519",
            signer_id=self._signer_id,
            signer_type=self._signer_type,
            key_ref=self._key_ref,
            public_key=public_key,
            attestation_level="attested",
            config_profile=self._config_profile,
            trust_anchor_type="software",
            key_algorithm="ed25519",
            trust_proof=_build_trust_proof(
                request,
                trust_anchor_type="software",
                key_algorithm="ed25519",
                key_ref=self._key_ref,
                public_key_material=public_key,
                signature=signature,
                attestation_level="attested",
                revocation_id=f"ed25519:{self._key_ref}",
            ),
            revocation_id=f"ed25519:{self._key_ref}",
        )


class Ed25519Signer(LegacyEd25519SignerProvider):
    signing_scheme = "ed25519"

    def sign(self, payload_hash: str) -> SigningResult:
        return self.sign_hash(
            SignerRequest(
                artifact_type="legacy",
                signer_profile="legacy",
                payload_hash=payload_hash,
            )
        )


class KmsP256SignerProvider:
    provider_name = "kms_p256"

    def __init__(
        self,
        *,
        private_key_pem: Optional[str] = None,
        signer_id: Optional[str] = None,
        key_ref: Optional[str] = None,
        signer_type: str = "service",
        config_profile: Optional[str] = None,
        trust_anchor_type: str = "kms",
    ) -> None:
        self._private_key = _load_p256_private_key_from_pem(
            private_key_pem or os.getenv("SEEDCORE_ECDSA_P256_PRIVATE_KEY_PEM", "").strip()
        )
        self._public_key_bytes = (
            self._private_key.public_key().public_bytes(
                encoding=serialization.Encoding.X962,
                format=serialization.PublicFormat.UncompressedPoint,
            )
            if self._private_key is not None
            else None
        )
        self._signer_id = signer_id or os.getenv(
            "SEEDCORE_ECDSA_P256_SIGNER_ID",
            os.getenv("SEEDCORE_EVIDENCE_SIGNER_ID", "seedcore-p256-signer"),
        )
        self._key_ref = key_ref or os.getenv("SEEDCORE_ECDSA_P256_KEY_ID")
        if self._key_ref is None and self._public_key_bytes is not None:
            self._key_ref = _derive_key_ref(self._public_key_bytes)
        self._signer_type = signer_type
        self._config_profile = config_profile or "kms_ecdsa_p256"
        self._trust_anchor_type = trust_anchor_type

    def is_available(self) -> bool:
        return self._private_key is not None and self._public_key_bytes is not None and self._key_ref is not None

    @property
    def trust_anchor_type(self) -> str:
        return self._trust_anchor_type

    def sign_hash(self, request: SignerRequest) -> SigningResult:
        if not self.is_available():
            raise ValueError("kms_p256_signer_not_configured")
        signature_bytes = self._private_key.sign(
            request.payload_hash.encode("utf-8"),
            ec.ECDSA(hashes.SHA256()),
        )
        public_key = base64.b64encode(self._public_key_bytes).decode("ascii")
        signature = base64.b64encode(signature_bytes).decode("ascii")
        revocation_id = f"{self._trust_anchor_type}:{self._key_ref}"
        return SigningResult(
            signature=signature,
            signing_scheme=ECDSA_P256_SCHEME,
            signer_id=self._signer_id,
            signer_type=self._signer_type,
            key_ref=self._key_ref,
            public_key=public_key,
            attestation_level="attested",
            config_profile=self._config_profile,
            trust_anchor_type=self._trust_anchor_type,
            key_algorithm=ECDSA_P256_SCHEME,
            trust_proof=_build_trust_proof(
                request,
                trust_anchor_type=self._trust_anchor_type,
                key_algorithm=ECDSA_P256_SCHEME,
                key_ref=self._key_ref,
                public_key_material=public_key,
                signature=signature,
                attestation_level="attested",
                revocation_id=revocation_id,
                attestation_type="kms_binding" if self._trust_anchor_type == "kms" else "vtpm_binding",
            ),
            revocation_id=revocation_id,
        )


class Tpm2P256SignerProvider:
    provider_name = "tpm2_p256"

    def __init__(self) -> None:
        self._signer_id = os.getenv(
            "SEEDCORE_TPM2_SIGNER_ID",
            os.getenv("SEEDCORE_ECDSA_P256_SIGNER_ID", "seedcore-tpm2-signer"),
        )
        self._key_ref = os.getenv("SEEDCORE_TPM2_KEY_ID", "").strip() or None
        self._persistent_handle = os.getenv("SEEDCORE_TPM2_PERSISTENT_HANDLE", "").strip() or None
        self._public_key_b64 = os.getenv("SEEDCORE_TPM2_PUBLIC_KEY_B64", "").strip() or None
        self._public_key_pem = os.getenv("SEEDCORE_TPM2_PUBLIC_KEY_PEM", "").strip() or None
        self._private_key_pem = os.getenv("SEEDCORE_TPM2_SOFTWARE_FALLBACK_PRIVATE_KEY_PEM", "").strip() or None
        self._software_fallback = _env_flag("SEEDCORE_TPM2_ALLOW_SOFTWARE_FALLBACK", default=False)
        self._config_profile = os.getenv("SEEDCORE_TPM2_PROFILE", "tpm2_receipt_p256")

    def is_available(self) -> bool:
        return self.is_hardware_available() or (
            self._software_fallback and _load_p256_private_key_from_pem(self._private_key_pem) is not None
        )

    def is_hardware_available(self) -> bool:
        return self._can_use_tpm2_tools()

    def sign_hash(self, request: SignerRequest) -> SigningResult:
        signature_bytes: bytes
        public_key_material: Optional[str] = None
        metadata: dict[str, Any] = {}

        if self._can_use_tpm2_tools():
            signature_bytes = self._sign_with_tpm2_tools(request.payload_hash)
            public_key_material = self._resolve_public_key_material()
            metadata["provider_mode"] = "tpm2_tools"
        elif self._software_fallback:
            private_key = _load_p256_private_key_from_pem(self._private_key_pem)
            if private_key is None:
                raise ValueError("tpm2_p256_signer_not_configured")
            signature_bytes = private_key.sign(
                request.payload_hash.encode("utf-8"),
                ec.ECDSA(hashes.SHA256()),
            )
            public_bytes = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.X962,
                format=serialization.PublicFormat.UncompressedPoint,
            )
            public_key_material = base64.b64encode(public_bytes).decode("ascii")
            metadata["provider_mode"] = "software_fallback"
        else:
            raise ValueError("tpm2_p256_signer_not_configured")

        key_ref = self._key_ref or _derive_key_ref(base64.b64decode(public_key_material)) if public_key_material else self._key_ref
        if not key_ref:
            raise ValueError("tpm2_key_ref_missing")
        revocation_id = f"tpm2:{key_ref}"
        signature = base64.b64encode(signature_bytes).decode("ascii")
        return SigningResult(
            signature=signature,
            signing_scheme=ECDSA_P256_SCHEME,
            signer_id=self._signer_id,
            signer_type="hal_endpoint",
            key_ref=key_ref,
            public_key=public_key_material,
            attestation_level="attested",
            config_profile=self._config_profile,
            trust_anchor_type="tpm2",
            key_algorithm=ECDSA_P256_SCHEME,
            trust_proof=_build_trust_proof(
                request,
                trust_anchor_type="tpm2",
                key_algorithm=ECDSA_P256_SCHEME,
                key_ref=key_ref,
                public_key_material=public_key_material,
                signature=signature,
                attestation_level="attested",
                revocation_id=revocation_id,
                attestation_type="tpm2_ak_binding",
                extra_binding_metadata=metadata,
            ),
            revocation_id=revocation_id,
        )

    def _can_use_tpm2_tools(self) -> bool:
        return (
            self._persistent_handle is not None
            and shutil.which("tpm2_sign") is not None
            and self._resolve_public_key_material() is not None
        )

    def _resolve_public_key_material(self) -> Optional[str]:
        if self._public_key_b64:
            return self._public_key_b64
        if self._public_key_pem:
            try:
                key = serialization.load_pem_public_key(self._public_key_pem.encode("utf-8"))
                public_bytes = key.public_bytes(
                    encoding=serialization.Encoding.X962,
                    format=serialization.PublicFormat.UncompressedPoint,
                )
                return base64.b64encode(public_bytes).decode("ascii")
            except Exception:
                return None
        return None

    def _sign_with_tpm2_tools(self, payload_hash: str) -> bytes:
        tmp_dir = os.getenv("SEEDCORE_TPM2_TMPDIR", "/tmp")
        digest_path = os.path.join(tmp_dir, f"seedcore-tpm2-digest-{os.getpid()}.bin")
        sig_path = os.path.join(tmp_dir, f"seedcore-tpm2-sig-{os.getpid()}.bin")
        try:
            with open(digest_path, "wb") as digest_file:
                digest_file.write(payload_hash.encode("utf-8"))
            completed = subprocess.run(
                [
                    "tpm2_sign",
                    "-Q",
                    "-c",
                    self._persistent_handle or "",
                    "-g",
                    "sha256",
                    "-f",
                    "plain",
                    "-o",
                    sig_path,
                    digest_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                raise ValueError(f"tpm2_sign_failed:{completed.stderr.strip() or completed.stdout.strip()}")
            with open(sig_path, "rb") as sig_file:
                return sig_file.read()
        finally:
            for path in (digest_path, sig_path):
                try:
                    os.unlink(path)
                except OSError:
                    pass


DEFAULT_SIGNER_POLICIES: dict[str, ArtifactSignerPolicy] = {
    "policy_receipt": ArtifactSignerPolicy(
        artifact_type="policy_receipt",
        allowed_schemes=("hmac_sha256", "ed25519", ECDSA_P256_SCHEME),
        default_scheme="hmac_sha256",
        preferred_scheme="ed25519",
        config_profile="policy_receipt_baseline",
    ),
    "evidence_bundle": ArtifactSignerPolicy(
        artifact_type="evidence_bundle",
        allowed_schemes=("hmac_sha256", "ed25519", ECDSA_P256_SCHEME),
        default_scheme="hmac_sha256",
        preferred_scheme="ed25519",
        config_profile="evidence_bundle_baseline",
    ),
    "transition_receipt": ArtifactSignerPolicy(
        artifact_type="transition_receipt",
        allowed_schemes=("hmac_sha256", "ed25519", ECDSA_P256_SCHEME),
        default_scheme="hmac_sha256",
        preferred_scheme=ECDSA_P256_SCHEME,
        require_attestation=False,
        config_profile="transition_receipt_attested",
    ),
    "hal_capture": ArtifactSignerPolicy(
        artifact_type="hal_capture",
        allowed_schemes=("hmac_sha256", "ed25519", ECDSA_P256_SCHEME),
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
        allowed_schemes=("hmac_sha256", "ed25519", ECDSA_P256_SCHEME),
        default_scheme="hmac_sha256",
        preferred_scheme="hmac_sha256",
        config_profile="trust_certificate_baseline",
    ),
    "external_signed_intent": ArtifactSignerPolicy(
        artifact_type="external_signed_intent",
        allowed_schemes=("ed25519", "hmac_sha256", ECDSA_P256_SCHEME),
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


def artifact_signer_profile(artifact_type: str) -> str:
    mapping = {
        "policy_receipt": "pdp",
        "evidence_bundle": "execution",
        "hal_capture": "execution",
        "transition_receipt": "receipt",
    }
    return mapping.get(artifact_type, "execution")


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
    elif env_mode in {"ecdsa_p256", ECDSA_P256_SCHEME, "p256"}:
        preferred = ECDSA_P256_SCHEME
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
    workflow_type: Optional[str] = None,
    receipt_nonce: Optional[str] = None,
    previous_receipt_hash: Optional[str] = None,
    previous_receipt_counter: Optional[int] = None,
    transparency_enabled: bool = False,
) -> SignerProvider:
    request = SignerRequest(
        artifact_type=artifact_type,
        signer_profile=artifact_signer_profile(artifact_type),
        payload_hash="",
        endpoint_id=endpoint_id,
        node_id=node_id,
        trust_level=trust_level,
        workflow_type=workflow_type,
        receipt_nonce=receipt_nonce,
        previous_receipt_hash=previous_receipt_hash,
        previous_receipt_counter=previous_receipt_counter,
        require_trust_anchor=_required_trust_anchor_for_request(
            artifact_type=artifact_type,
            endpoint_id=endpoint_id,
            workflow_type=workflow_type,
        ),
        required_key_algorithm=_required_key_algorithm_for_request(
            artifact_type=artifact_type,
            endpoint_id=endpoint_id,
            workflow_type=workflow_type,
        ),
        transparency_enabled=transparency_enabled,
    )
    return resolve_signer_provider(request=request)


def resolve_signer_provider(*, request: SignerRequest) -> SignerProvider:
    explicit_provider = _explicit_provider_for_profile(request.signer_profile)
    if explicit_provider is not None:
        provider = explicit_provider
        if _provider_matches_requirements(provider, request):
            return provider

    if request.required_key_algorithm == ECDSA_P256_SCHEME:
        for provider in (
            Tpm2P256SignerProvider(),
            KmsP256SignerProvider(trust_anchor_type="kms"),
            KmsP256SignerProvider(
                private_key_pem=os.getenv("SEEDCORE_VTPM_P256_PRIVATE_KEY_PEM", "").strip(),
                signer_id=os.getenv("SEEDCORE_VTPM_SIGNER_ID"),
                key_ref=os.getenv("SEEDCORE_VTPM_KEY_ID"),
                config_profile="vtpm_ecdsa_p256",
                trust_anchor_type="vtpm",
            ),
        ):
            if _provider_matches_requirements(provider, request):
                return provider
        raise ValueError(f"{request.artifact_type} requires {ECDSA_P256_SCHEME} signer provider")

    policy = get_signer_policy(
        artifact_type=request.artifact_type,
        endpoint_id=request.endpoint_id,
        trust_level=request.trust_level,
        attested=None,
    )
    if policy.preferred_scheme == "ed25519":
        provider = LegacyEd25519SignerProvider.from_env()
        if provider is not None:
            return provider
        if policy.require_attestation:
            raise ValueError(f"{request.artifact_type} requires Ed25519 signing for attested paths")
    return LegacyHmacSignerProvider(config_profile=policy.config_profile)


def sign_artifact_request(request: SignerRequest) -> SigningResult:
    provider = resolve_signer_provider(request=request)
    return provider.sign_hash(request)


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
    provider = resolve_artifact_signer(
        artifact_type="evidence_bundle",
        endpoint_id=endpoint_id,
    )
    return provider  # type: ignore[return-value]


def _explicit_provider_for_profile(profile: str) -> Optional[SignerProvider]:
    configured = os.getenv(f"SEEDCORE_SIGNER_PROVIDER_{profile.upper()}", "").strip().lower()
    if not configured:
        return None
    if configured == "tpm2":
        return Tpm2P256SignerProvider()
    if configured == "kms":
        return KmsP256SignerProvider(trust_anchor_type="kms")
    if configured == "vtpm":
        return KmsP256SignerProvider(
            private_key_pem=os.getenv("SEEDCORE_VTPM_P256_PRIVATE_KEY_PEM", "").strip(),
            signer_id=os.getenv("SEEDCORE_VTPM_SIGNER_ID"),
            key_ref=os.getenv("SEEDCORE_VTPM_KEY_ID"),
            config_profile="vtpm_ecdsa_p256",
            trust_anchor_type="vtpm",
        )
    if configured == "ed25519":
        provider = LegacyEd25519SignerProvider.from_env()
        if provider is not None:
            return provider
        return None
    if configured == "hmac":
        return LegacyHmacSignerProvider()
    return None


def _provider_matches_requirements(provider: SignerProvider, request: SignerRequest) -> bool:
    trust_anchor = request.require_trust_anchor
    if trust_anchor == "tpm2":
        if not isinstance(provider, Tpm2P256SignerProvider):
            return False
        if _env_flag("SEEDCORE_TPM2_REQUIRE_HARDWARE", default=True):
            return provider.is_hardware_available()
        return provider.is_available()
    if trust_anchor == "kms":
        return (
            isinstance(provider, KmsP256SignerProvider)
            and provider.is_available()
            and provider.trust_anchor_type == "kms"
        )
    if trust_anchor == "vtpm":
        return (
            isinstance(provider, KmsP256SignerProvider)
            and provider.is_available()
            and provider.trust_anchor_type == "vtpm"
        )
    if request.required_key_algorithm == ECDSA_P256_SCHEME:
        if isinstance(provider, Tpm2P256SignerProvider):
            return provider.is_available()
        if isinstance(provider, KmsP256SignerProvider):
            return provider.is_available()
        return False
    return True


def _required_key_algorithm_for_request(
    *,
    artifact_type: str,
    endpoint_id: Optional[str],
    workflow_type: Optional[str],
) -> Optional[str]:
    if artifact_type == "transition_receipt" and _requires_restricted_receipt_hardening(
        endpoint_id=endpoint_id,
        workflow_type=workflow_type,
    ):
        return ECDSA_P256_SCHEME
    return None


def _required_trust_anchor_for_request(
    *,
    artifact_type: str,
    endpoint_id: Optional[str],
    workflow_type: Optional[str],
) -> Optional[str]:
    if artifact_type != "transition_receipt":
        return None
    if not _requires_restricted_receipt_hardening(endpoint_id=endpoint_id, workflow_type=workflow_type):
        return None
    if isinstance(endpoint_id, str) and endpoint_id.strip().lower().startswith("hal://"):
        return os.getenv("SEEDCORE_RECEIPT_REQUIRED_TRUST_ANCHOR", "tpm2").strip().lower() or "tpm2"
    return os.getenv("SEEDCORE_RECEIPT_REQUIRED_TRUST_ANCHOR", "kms").strip().lower() or "kms"


def _requires_restricted_receipt_hardening(
    *,
    endpoint_id: Optional[str],
    workflow_type: Optional[str],
) -> bool:
    if not isinstance(endpoint_id, str):
        return False
    normalized_workflow = str(workflow_type or "").strip().lower()
    if normalized_workflow not in RESTRICTED_CUSTODY_TRANSFER_WORKFLOW_TYPES:
        return False
    endpoint = endpoint_id.strip().lower()
    return endpoint.startswith("hal://") or endpoint.startswith("robot_sim://")


def _build_trust_proof(
    request: SignerRequest,
    *,
    trust_anchor_type: str,
    key_algorithm: str,
    key_ref: str,
    public_key_material: Optional[str],
    signature: Optional[str],
    attestation_level: str,
    revocation_id: str,
    attestation_type: str = "none",
    extra_binding_metadata: Optional[dict[str, Any]] = None,
) -> TrustProof:
    public_key_fingerprint = _fingerprint_public_key(public_key_material)
    attestation_summary: dict[str, str] = {"attestation_level": attestation_level}
    if isinstance(request.endpoint_id, str) and request.endpoint_id.strip():
        attestation_summary["endpoint_id"] = request.endpoint_id
    if isinstance(request.node_id, str) and request.node_id.strip():
        attestation_summary["node_id"] = request.node_id
    if isinstance(request.workflow_type, str) and request.workflow_type.strip():
        attestation_summary["workflow_type"] = request.workflow_type
    replay = ReplayProof(
        receipt_nonce=request.receipt_nonce,
        receipt_counter=_next_receipt_counter(
            key=request.node_id or request.endpoint_id or key_ref,
            previous=request.previous_receipt_counter,
        )
        if request.signer_profile == "receipt"
        else None,
        previous_receipt_hash=request.previous_receipt_hash,
    )
    transparency = _maybe_anchor_transparency(
        payload_hash=request.payload_hash,
        signature=signature,
        public_key_material=public_key_material,
        key_algorithm=key_algorithm,
        enabled=request.transparency_enabled and request.signer_profile == "receipt",
    )
    return TrustProof(
        signer_profile=request.signer_profile,
        trust_anchor_type=trust_anchor_type,
        key_algorithm=key_algorithm,
        key_ref=key_ref,
        public_key_fingerprint=public_key_fingerprint,
        key_binding=KeyBindingProof(
            binding_type=attestation_type if attestation_type != "none" else f"{trust_anchor_type}_binding",
            key_handle=os.getenv("SEEDCORE_TPM2_PERSISTENT_HANDLE", "").strip() or None,
            key_label=request.endpoint_id or request.node_id,
            certificate_chain=_split_env_lines("SEEDCORE_TPM2_AK_CERT_CHAIN"),
            metadata=dict(extra_binding_metadata or {}),
        ),
        attestation=AttestationProof(
            attestation_type=attestation_type,
            ak_key_ref=os.getenv("SEEDCORE_TPM2_AK_KEY_REF", "").strip() or None,
            quote=_resolve_tpm_quote_payload(request=request),
            endorsement_chain=_split_env_lines("SEEDCORE_TPM2_ENDORSEMENT_CHAIN"),
            summary=attestation_summary,
            issued_at=datetime.now(timezone.utc).isoformat(),
        ),
        replay=replay if request.signer_profile == "receipt" else None,
        revocation_id=revocation_id,
        transparency=transparency,
    )


def _maybe_anchor_transparency(
    *,
    payload_hash: str,
    signature: Optional[str],
    public_key_material: Optional[str],
    key_algorithm: str,
    enabled: bool,
) -> TransparencyProof:
    return anchor_receipt_hash(
        payload_hash=payload_hash,
        signature=signature,
        public_key_material=public_key_material,
        key_algorithm=key_algorithm,
        enabled=enabled,
    )


def _split_env_lines(name: str) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item).strip()]
        except Exception:
            return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _resolve_tpm_quote_payload(*, request: SignerRequest) -> Optional[str]:
    explicit_quote = os.getenv("SEEDCORE_TPM2_ATTESTATION_QUOTE", "").strip()
    if explicit_quote:
        return explicit_quote
    message_b64 = os.getenv("SEEDCORE_TPM2_QUOTE_MESSAGE_B64", "").strip()
    signature_b64 = os.getenv("SEEDCORE_TPM2_QUOTE_SIGNATURE_B64", "").strip()
    if not message_b64 or not signature_b64:
        return None
    payload = {
        "format": "seedcore_tpm_quote_v1",
        "message_b64": message_b64,
        "signature_b64": signature_b64,
        "nonce": (
            os.getenv("SEEDCORE_TPM2_QUOTE_NONCE", "").strip()
            or request.receipt_nonce
        ),
        "pcr_digest": os.getenv("SEEDCORE_TPM2_QUOTE_PCR_DIGEST", "").strip() or None,
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _fingerprint_public_key(public_key_material: Optional[str]) -> str:
    if not public_key_material:
        return "sha256:unknown"
    digest = hashlib.sha256(public_key_material.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _next_receipt_counter(*, key: str, previous: Optional[int]) -> int:
    if previous is not None:
        return int(previous) + 1
    with _SOFTWARE_COUNTER_LOCK:
        current = _SOFTWARE_COUNTERS.get(key, 0) + 1
        _SOFTWARE_COUNTERS[key] = current
        return current


def _derive_key_ref(public_key_bytes: bytes) -> str:
    return hashlib.sha256(public_key_bytes).hexdigest()[:16]


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


def _load_p256_private_key_from_pem(value: str) -> Optional[ec.EllipticCurvePrivateKey]:
    if not value:
        return None
    try:
        loaded = serialization.load_pem_private_key(value.encode("utf-8"), password=None)
        if isinstance(loaded, ec.EllipticCurvePrivateKey):
            return loaded
    except Exception:
        return None
    return None
