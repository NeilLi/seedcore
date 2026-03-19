from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Optional, Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from seedcore.hal.custody.transition_receipts import is_attestable_transition_endpoint


@dataclass
class SigningResult:
    signature: str
    proof_type: str
    signer_id: str
    signer_type: str
    key_id: Optional[str] = None
    public_key: Optional[str] = None


class EvidenceSigner(Protocol):
    proof_type: str

    def sign(self, payload_hash: str) -> SigningResult:
        ...


class HMACSigner:
    proof_type = "hmac_sha256"

    def __init__(
        self,
        *,
        secret: Optional[str] = None,
        signer_id: Optional[str] = None,
        key_id: Optional[str] = None,
    ) -> None:
        self._secret = secret or os.getenv(
            "SEEDCORE_EVIDENCE_SIGNING_SECRET",
            "seedcore-dev-evidence-secret",
        )
        self._signer_id = signer_id or os.getenv(
            "SEEDCORE_EVIDENCE_SIGNER_ID",
            "seedcore-evidence-service",
        )
        self._key_id = key_id or os.getenv("SEEDCORE_EVIDENCE_SIGNING_KEY_ID")

    def sign(self, payload_hash: str) -> SigningResult:
        signature = hmac.new(
            self._secret.encode("utf-8"),
            payload_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return SigningResult(
            signature=signature,
            proof_type=self.proof_type,
            signer_id=self._signer_id,
            signer_type="service",
            key_id=self._key_id,
            public_key=None,
        )


class Ed25519Signer:
    proof_type = "ed25519"

    def __init__(
        self,
        *,
        private_key: Ed25519PrivateKey,
        signer_id: Optional[str] = None,
        key_id: Optional[str] = None,
    ) -> None:
        self._private_key = private_key
        self._public_key_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self._signer_id = signer_id or os.getenv(
            "SEEDCORE_EVIDENCE_SIGNER_ID",
            "seedcore-evidence-service",
        )
        self._key_id = key_id or os.getenv("SEEDCORE_EVIDENCE_ED25519_KEY_ID") or self._derive_key_id(
            self._public_key_bytes
        )

    @classmethod
    def from_env(cls) -> Optional["Ed25519Signer"]:
        private_key = _load_ed25519_private_key_from_env()
        if private_key is None:
            return None
        return cls(
            private_key=private_key,
            signer_id=os.getenv("SEEDCORE_EVIDENCE_ED25519_SIGNER_ID"),
            key_id=os.getenv("SEEDCORE_EVIDENCE_ED25519_KEY_ID"),
        )

    def sign(self, payload_hash: str) -> SigningResult:
        signature_bytes = self._private_key.sign(payload_hash.encode("utf-8"))
        return SigningResult(
            signature=base64.b64encode(signature_bytes).decode("ascii"),
            proof_type=self.proof_type,
            signer_id=self._signer_id,
            signer_type="service",
            key_id=self._key_id,
            public_key=base64.b64encode(self._public_key_bytes).decode("ascii"),
        )

    @staticmethod
    def _derive_key_id(public_key_bytes: bytes) -> str:
        return hashlib.sha256(public_key_bytes).hexdigest()[:16]


def resolve_evidence_signer(*, endpoint_id: Optional[str]) -> EvidenceSigner:
    mode = os.getenv("SEEDCORE_EVIDENCE_SIGNER_MODE", "hmac").strip().lower()
    ed25519_signer = Ed25519Signer.from_env()

    if mode == "ed25519":
        if ed25519_signer is not None:
            return ed25519_signer
        return HMACSigner()

    if mode == "auto":
        if is_attestable_transition_endpoint(endpoint_id) and ed25519_signer is not None:
            return ed25519_signer
        return HMACSigner()

    return HMACSigner()


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
