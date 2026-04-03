from __future__ import annotations

import base64
import hashlib
import os
import sys

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from seedcore.ops.evidence.kms_sign_rpc import RecordingPemKmsBackend
from seedcore.ops.evidence.policy import load_p256_public_key
from seedcore.ops.evidence.signers import (
    ECDSA_P256_SCHEME,
    CloudKmsRpcP256SignerProvider,
    KmsP256SignerProvider,
    SignerRequest,
    try_cloud_kms_rpc_signer_provider_from_env,
)


def _p256_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def test_recording_pem_backend_records_digest_and_matches_sha256_of_message() -> None:
    pem = _p256_pem()
    from cryptography.hazmat.primitives import serialization as ser

    loaded = ser.load_pem_private_key(pem.encode("utf-8"), password=None)
    assert isinstance(loaded, ec.EllipticCurvePrivateKey)
    backend = RecordingPemKmsBackend(
        key_resource_name="projects/p/locations/l/keyRings/k/cryptoKeys/x/cryptoKeyVersions/1",
        private_key=loaded,
    )
    msg = b"payload-hash-string"
    digest = hashlib.sha256(msg).digest()
    sig, pub_b64 = backend.asymmetric_sign_ecdsa_sha256(msg)
    assert backend.calls == [(backend.key_resource_name, digest)]
    pub = load_p256_public_key(pub_b64)
    assert pub is not None
    pub.verify(sig, msg, ec.ECDSA(hashes.SHA256()))


def test_cloud_kms_rpc_provider_round_trip_matches_policy_verifier_semantics() -> None:
    pem = _p256_pem()
    from cryptography.hazmat.primitives import serialization as ser

    loaded = ser.load_pem_private_key(pem.encode("utf-8"), password=None)
    assert isinstance(loaded, ec.EllipticCurvePrivateKey)
    backend = RecordingPemKmsBackend(
        key_resource_name="projects/demo/locations/global/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1",
        private_key=loaded,
    )
    provider = CloudKmsRpcP256SignerProvider(backend=backend, key_ref="test-key-ref")
    payload_hash = "abc123deadbeef"
    req = SignerRequest(
        artifact_type="transition_receipt",
        signer_profile="receipt",
        payload_hash=payload_hash,
    )
    result = provider.sign_hash(req)
    assert result.signing_scheme == ECDSA_P256_SCHEME
    assert result.trust_anchor_type == "kms"
    pub = load_p256_public_key(result.public_key or "")
    assert pub is not None
    pub.verify(
        base64.b64decode(result.signature, validate=True),
        payload_hash.encode("utf-8"),
        ec.ECDSA(hashes.SHA256()),
    )


def test_try_cloud_kms_rpc_from_env_contract_pem(monkeypatch: pytest.MonkeyPatch) -> None:
    pem = _p256_pem()
    monkeypatch.delenv("SEEDCORE_CLOUD_KMS_CRYPTO_KEY_VERSION", raising=False)
    monkeypatch.delenv("SEEDCORE_CLOUD_KMS_CONTRACT_PRIVATE_KEY_PEM", raising=False)
    monkeypatch.setenv(
        "SEEDCORE_CLOUD_KMS_CRYPTO_KEY_VERSION",
        "projects/p/locations/l/keyRings/k/cryptoKeys/c/cryptoKeyVersions/1",
    )
    monkeypatch.setenv("SEEDCORE_CLOUD_KMS_CONTRACT_PRIVATE_KEY_PEM", pem)
    prov = try_cloud_kms_rpc_signer_provider_from_env()
    assert prov is not None
    assert prov.is_available()


def test_try_cloud_kms_rpc_without_key_version_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEEDCORE_CLOUD_KMS_CRYPTO_KEY_VERSION", raising=False)
    monkeypatch.delenv("SEEDCORE_CLOUD_KMS_CONTRACT_PRIVATE_KEY_PEM", raising=False)
    assert try_cloud_kms_rpc_signer_provider_from_env() is None


def test_kms_p256_pem_still_verifies_after_rpc_path_added() -> None:
    """Regression: Path 1 PEM KMS provider unchanged for verification semantics."""
    pem = _p256_pem()
    provider = KmsP256SignerProvider(private_key_pem=pem, key_ref="regression-kms", trust_anchor_type="kms")
    assert provider.is_available()
    payload_hash = "stable-hash-for-regression"
    result = provider.sign_hash(
        SignerRequest(
            artifact_type="transition_receipt",
            signer_profile="receipt",
            payload_hash=payload_hash,
        )
    )
    pub = load_p256_public_key(result.public_key or "")
    assert pub is not None
    pub.verify(
        base64.b64decode(result.signature, validate=True),
        payload_hash.encode("utf-8"),
        ec.ECDSA(hashes.SHA256()),
    )


@pytest.mark.skipif(
    not os.getenv("SEEDCORE_CLOUD_KMS_INTEGRATION_TEST"),
    reason="Path 3: set SEEDCORE_CLOUD_KMS_INTEGRATION_TEST=1, ADC, and key version for live KMS smoke",
)
def test_live_cloud_kms_optional_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt-in sandbox round-trip; requires ``pip install -e '.[cloud-kms]'`` and IAM."""
    key = os.getenv("SEEDCORE_CLOUD_KMS_CRYPTO_KEY_VERSION", "").strip()
    if not key:
        pytest.skip("SEEDCORE_CLOUD_KMS_CRYPTO_KEY_VERSION not set")
    monkeypatch.delenv("SEEDCORE_CLOUD_KMS_CONTRACT_PRIVATE_KEY_PEM", raising=False)
    prov = try_cloud_kms_rpc_signer_provider_from_env()
    if prov is None:
        pytest.skip("google-cloud-kms unavailable or client construction failed")
    result = prov.sign_hash(
        SignerRequest(
            artifact_type="transition_receipt",
            signer_profile="receipt",
            payload_hash="seedcore-live-kms-smoke",
        )
    )
    assert result.signing_scheme == ECDSA_P256_SCHEME
    pub = load_p256_public_key(result.public_key or "")
    assert pub is not None
    pub.verify(
        base64.b64decode(result.signature, validate=True),
        b"seedcore-live-kms-smoke",
        ec.ECDSA(hashes.SHA256()),
    )
