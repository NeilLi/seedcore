from __future__ import annotations

import json
import time
import uuid
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives import hashes
from pydantic import ValidationError

from seedcore.models.action_intent import IntentPrincipal
from seedcore.ops.identity.workload import (
    base64url_encode,
    base64url_decode,
    jwk_to_public_key_and_jkt,
    verify_workload_request,
)


def test_spiffe_metadata_does_not_satisfy_action_identity_proof() -> None:
    with pytest.raises(ValidationError):
        IntentPrincipal(
            agent_id="agent:custody_runtime_01",
            role_profile="TRANSFER_COORDINATOR",
            spiffe_id="spiffe://seedcore.internal/ns/default/sa/pdp-service",
        )


def _gen_test_key_and_jwk() -> tuple[ec.EllipticCurvePrivateKey, dict[str, str]]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    # Extract public key X, Y coordinates as bytes
    numbers = public_key.public_numbers()
    x_bytes = numbers.x.to_bytes(32, byteorder='big')
    y_bytes = numbers.y.to_bytes(32, byteorder='big')

    jwk = {
        "kty": "EC",
        "crv": "P-256",
        "x": base64url_encode(x_bytes),
        "y": base64url_encode(y_bytes),
    }
    return private_key, jwk


def _create_dpop_token(
    private_key: ec.EllipticCurvePrivateKey,
    jwk: dict[str, str],
    method: str,
    url: str,
    iat: int | None = None,
    jti: str | None = None,
) -> str:
    header = {
        "typ": "dpop+jwt",
        "alg": "ES256",
        "jwk": jwk,
    }
    payload = {
        "htm": method,
        "htu": url,
        "iat": iat if iat is not None else int(time.time()),
        "jti": jti if jti is not None else str(uuid.uuid4()),
    }

    header_b64 = base64url_encode(json.dumps(header).encode('utf-8'))
    payload_b64 = base64url_encode(json.dumps(payload).encode('utf-8'))

    message = f"{header_b64}.{payload_b64}".encode('utf-8')
    der_signature = private_key.sign(message, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    signature = r.to_bytes(32, byteorder="big") + s.to_bytes(32, byteorder="big")
    signature_b64 = base64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def test_verify_workload_request_happy_path() -> None:
    private_key, jwk = _gen_test_key_and_jwk()
    method = "POST"
    url = "https://api.seedcore.internal/api/v1/workflows"

    token = _create_dpop_token(private_key, jwk, method, url)
    headers = {
        "DPoP": token,
        "X-SPIFFE-ID": "spiffe://seedcore.internal/ns/default/sa/pdp-service",
    }

    res = verify_workload_request(
        headers,
        method,
        url,
        require_spiffe=True,
        require_dpop=True,
        trust_forwarded_spiffe_headers=True,
    )
    assert res["verified"] is True
    assert res["spiffe_id"] == "spiffe://seedcore.internal/ns/default/sa/pdp-service"
    assert res["dpop_jkt"] is not None
    assert res["error"] is None


def test_verify_workload_request_missing_spiffe() -> None:
    private_key, jwk = _gen_test_key_and_jwk()
    method = "GET"
    url = "https://api.seedcore.internal/api/v1/status"

    token = _create_dpop_token(private_key, jwk, method, url)
    headers = {
        "DPoP": token,
    }

    res = verify_workload_request(headers, method, url, require_spiffe=True, require_dpop=True)
    assert res["verified"] is False
    assert res["error"] == "missing_spiffe_identity"


def test_verify_workload_request_does_not_trust_spiffe_header_by_default() -> None:
    headers = {
        "X-SPIFFE-ID": "spiffe://seedcore.internal/ns/default/sa/pdp-service",
    }
    res = verify_workload_request(headers, "GET", "https://api.seedcore.internal/status", require_spiffe=True)
    assert res["verified"] is False
    assert res["spiffe_id"] is None
    assert res["error"] == "missing_spiffe_identity"


def test_verify_workload_request_missing_dpop() -> None:
    headers = {
        "X-SPIFFE-ID": "spiffe://seedcore.internal/ns/default/sa/pdp-service",
    }
    res = verify_workload_request(headers, "GET", "http://foo", require_spiffe=False, require_dpop=True)
    assert res["verified"] is False
    assert res["error"] == "missing_dpop_proof"


def test_verify_workload_request_replay_attack() -> None:
    private_key, jwk = _gen_test_key_and_jwk()
    method = "POST"
    url = "https://api.seedcore.internal/api/v1/workflows"
    jti = "fixed-jti-token-value"

    token = _create_dpop_token(private_key, jwk, method, url, jti=jti)
    headers = {
        "DPoP": token,
    }

    # First request should succeed
    res1 = verify_workload_request(headers, method, url, require_spiffe=False, require_dpop=True)
    assert res1["verified"] is True

    # Second request with the same JTI should fail as a replay
    res2 = verify_workload_request(headers, method, url, require_spiffe=False, require_dpop=True)
    assert res2["verified"] is False
    assert "replay attempt" in str(res2["error"])


def test_verify_workload_request_method_mismatch() -> None:
    private_key, jwk = _gen_test_key_and_jwk()
    url = "https://api.seedcore.internal/api/v1/workflows"

    token = _create_dpop_token(private_key, jwk, "POST", url)
    headers = {
        "DPoP": token,
    }

    # Requested method is GET but DPoP claimed POST
    res = verify_workload_request(headers, "GET", url, require_spiffe=False, require_dpop=True)
    assert res["verified"] is False
    assert "htm claim mismatch" in str(res["error"])


def test_verify_workload_request_url_mismatch() -> None:
    private_key, jwk = _gen_test_key_and_jwk()
    method = "POST"

    token = _create_dpop_token(private_key, jwk, method, "https://api.seedcore.internal/api/v1/workflows")
    headers = {
        "DPoP": token,
    }

    # Requested URL is slightly different
    res = verify_workload_request(headers, method, "https://api.seedcore.internal/api/v2/workflows", require_spiffe=False, require_dpop=True)
    assert res["verified"] is False
    assert "htu claim mismatch" in str(res["error"])


def test_verify_workload_request_expired_token() -> None:
    private_key, jwk = _gen_test_key_and_jwk()
    method = "POST"
    url = "https://api.seedcore.internal/api/v1/workflows"

    # Create token issued 10 minutes ago
    token = _create_dpop_token(private_key, jwk, method, url, iat=int(time.time()) - 600)
    headers = {
        "DPoP": token,
    }

    res = verify_workload_request(headers, method, url, require_spiffe=False, require_dpop=True)
    assert res["verified"] is False
    assert "expired" in str(res["error"])


def test_verify_workload_request_xfcc_header() -> None:
    private_key, jwk = _gen_test_key_and_jwk()
    method = "GET"
    url = "https://api.seedcore.internal/api/v1/workflows"
    token = _create_dpop_token(private_key, jwk, method, url)

    # Test spiffe ID extraction from x-forwarded-client-cert
    headers = {
        "DPoP": token,
        "X-Forwarded-Client-Cert": 'By=spiffe://trust;Hash=123;URI="spiffe://seedcore.internal/ns/default/sa/verifier"',
    }
    res = verify_workload_request(
        headers,
        method,
        url,
        require_spiffe=True,
        require_dpop=True,
        trust_forwarded_spiffe_headers=True,
    )
    assert res["verified"] is True
    assert res["spiffe_id"] == "spiffe://seedcore.internal/ns/default/sa/verifier"
