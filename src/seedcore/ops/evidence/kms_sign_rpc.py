"""Thin Cloud KMS asymmetric-sign contract layer (Path 2).

Path 1 remains PEM-backed :class:`~seedcore.ops.evidence.signers.KmsP256SignerProvider`
without RPC-shaped calls. This module models the digest + resource-name contract
used by ``google.cloud.kms_v1`` so tests can assert call sequences against a
recording PEM-backed fake, or optionally use the official client (emulator or
sandbox) without changing receipt fields.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils


@runtime_checkable
class KmsRpcP256Backend(Protocol):
    """Sign ``SHA256(message)`` with ECDSA P-256 (same semantics as local PEM path)."""

    key_resource_name: str

    def asymmetric_sign_ecdsa_sha256(self, message: bytes) -> tuple[bytes, str]:
        """Return ``(signature_der, public_key_x962_b64)``."""


@dataclass
class RecordingPemKmsBackend:
    """PEM-backed signer that records RPC-shaped (resource, digest) pairs for contract tests."""

    key_resource_name: str
    private_key: ec.EllipticCurvePrivateKey
    calls: list[tuple[str, bytes]] = field(default_factory=list)

    def asymmetric_sign_ecdsa_sha256(self, message: bytes) -> tuple[bytes, str]:
        digest = hashlib.sha256(message).digest()
        self.calls.append((self.key_resource_name, digest))
        sig = self.private_key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        pub_bytes = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        return sig, base64.b64encode(pub_bytes).decode("ascii")


@dataclass
class GoogleCloudKmsRpcBackend:
    """Official client; optional dependency ``google-cloud-kms``. Uses precomputed SHA-256 digest."""

    _client: Any
    key_resource_name: str
    _public_key_x962_b64: Optional[str] = None

    def asymmetric_sign_ecdsa_sha256(self, message: bytes) -> tuple[bytes, str]:
        digest = hashlib.sha256(message).digest()
        from google.cloud.kms_v1.types import AsymmetricSignRequest, Digest

        digest_pb = Digest()
        digest_pb.sha256 = digest
        req = AsymmetricSignRequest(name=self.key_resource_name, digest=digest_pb)
        response = self._client.asymmetric_sign(request=req)
        pub_b64 = self._public_key_x962_b64 or self._load_public_key_x962_b64()
        return response.signature, pub_b64

    def _load_public_key_x962_b64(self) -> str:
        response = self._client.get_public_key(name=self.key_resource_name)
        pem_raw = response.pem
        pem = pem_raw.encode("utf-8") if isinstance(pem_raw, str) else pem_raw
        loaded = serialization.load_pem_public_key(pem)
        if not isinstance(loaded, ec.EllipticCurvePublicKey):
            raise TypeError("cloud_kms_public_key_not_p256")
        pub_bytes = loaded.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        self._public_key_x962_b64 = base64.b64encode(pub_bytes).decode("ascii")
        return self._public_key_x962_b64


def try_build_google_cloud_kms_backend(
    *,
    key_version_name: str,
    api_endpoint: Optional[str] = None,
) -> Optional[GoogleCloudKmsRpcBackend]:
    """Return a live RPC backend, or ``None`` if the client library is missing or construction fails."""
    try:
        from google.api_core.client_options import ClientOptions
        from google.cloud.kms_v1 import KeyManagementServiceClient
    except ImportError:
        return None
    try:
        client_options = ClientOptions(api_endpoint=api_endpoint) if api_endpoint else None
        client = KeyManagementServiceClient(client_options=client_options)
        return GoogleCloudKmsRpcBackend(_client=client, key_resource_name=key_version_name)
    except Exception:
        return None


def kms_contract_private_key_pem_from_env() -> str:
    return os.getenv("SEEDCORE_CLOUD_KMS_CONTRACT_PRIVATE_KEY_PEM", "").strip()


def kms_crypto_key_version_from_env() -> str:
    return os.getenv("SEEDCORE_CLOUD_KMS_CRYPTO_KEY_VERSION", "").strip()


def kms_api_endpoint_from_env() -> Optional[str]:
    raw = os.getenv("SEEDCORE_CLOUD_KMS_API_ENDPOINT", "").strip()
    return raw or None
