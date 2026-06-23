from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives import hashes

_SEEN_JTIS_LOCK = threading.Lock()
_SEEN_JTIS_CACHE: Dict[str, float] = {}
TRUSTED_SPIFFE_HEADER_ENV = "SEEDCORE_TRUST_WORKLOAD_IDENTITY_HEADERS"


def base64url_decode(payload: str) -> bytes:
    payload_clean = payload.replace('-', '+').replace('_', '/')
    rem = len(payload_clean) % 4
    if rem > 0:
        payload_clean += "=" * (4 - rem)
    return base64.b64decode(payload_clean.encode('utf-8'))


def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')


def jwk_to_public_key_and_jkt(jwk: Dict[str, Any]) -> Tuple[Any, str]:
    if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
        raise ValueError("Unsupported key type or curve, only EC/P-256 is supported")
    x_str = jwk.get("x", "")
    y_str = jwk.get("y", "")
    if not x_str or not y_str:
        raise ValueError("Missing x or y coordinate in EC key")

    x_bytes = base64url_decode(x_str)
    y_bytes = base64url_decode(y_str)
    if len(x_bytes) != 32 or len(y_bytes) != 32:
        raise ValueError("Invalid P-256 public key coordinate length")

    point = b"\x04" + x_bytes + y_bytes
    public_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)

    thumbprint_dict = {
        "crv": jwk["crv"],
        "kty": jwk["kty"],
        "x": jwk["x"],
        "y": jwk["y"]
    }
    thumbprint_str = json.dumps(thumbprint_dict, separators=(',', ':'), sort_keys=True)
    jkt = base64url_encode(hashlib.sha256(thumbprint_str.encode('utf-8')).digest())

    return public_key, jkt


def check_replay(jti: str, now: float, *, key_thumbprint: str | None = None) -> None:
    if not jti:
        raise ValueError("jti claim is required in DPoP payload")
    cache_key = f"{key_thumbprint or 'unknown'}:{jti}"
    with _SEEN_JTIS_LOCK:
        expired = [k for k, v in _SEEN_JTIS_CACHE.items() if v < now]
        for k in expired:
            _SEEN_JTIS_CACHE.pop(k, None)

        if cache_key in _SEEN_JTIS_CACHE:
            raise ValueError("DPoP jti has already been used (replay attempt)")
        _SEEN_JTIS_CACHE[cache_key] = now + 300


def _normalize_dpop_url(value: str) -> str:
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def _decode_es256_signature(signature: bytes) -> bytes:
    if len(signature) == 64:
        r = int.from_bytes(signature[:32], byteorder="big")
        s = int.from_bytes(signature[32:], byteorder="big")
        return encode_dss_signature(r, s)
    return signature


def verify_dpop_jwt(token: str, expected_method: str, expected_url: str) -> str:
    parts = token.split('.')
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    header_segment, payload_segment, signature_segment = parts

    try:
        header = json.loads(base64url_decode(header_segment).decode('utf-8'))
        payload = json.loads(base64url_decode(payload_segment).decode('utf-8'))
        signature = base64url_decode(signature_segment)
    except Exception as e:
        raise ValueError(f"Failed to decode DPoP token: {e}")

    if header.get("typ") != "dpop+jwt":
        raise ValueError("typ header must be 'dpop+jwt'")

    alg = header.get("alg")
    if alg != "ES256":
        raise ValueError("alg header must be 'ES256'")

    jwk = header.get("jwk")
    if not jwk:
        raise ValueError("jwk header is required")

    public_key, jkt = jwk_to_public_key_and_jkt(jwk)

    message = f"{header_segment}.{payload_segment}".encode('utf-8')
    try:
        public_key.verify(_decode_es256_signature(signature), message, ec.ECDSA(hashes.SHA256()))
    except Exception as e:
        raise ValueError(f"Signature verification failed: {e}")

    htm = payload.get("htm")
    if str(htm or "").upper() != str(expected_method or "").upper():
        raise ValueError(f"htm claim mismatch: expected {expected_method}, got {htm}")

    htu = payload.get("htu", "")
    if _normalize_dpop_url(str(htu)) != _normalize_dpop_url(expected_url):
        raise ValueError(f"htu claim mismatch: expected {expected_url}, got {htu}")

    iat = payload.get("iat")
    if not isinstance(iat, (int, float)):
        raise ValueError("iat claim must be numeric")
    now = time.time()
    if abs(now - iat) > 300:
        raise ValueError("DPoP proof has expired or is too far in the future")

    return jkt


def _valid_spiffe_id(value: str | None) -> str | None:
    normalized = str(value or "").strip().strip('"')
    if normalized.startswith("spiffe://"):
        return normalized
    return None


def extract_spiffe_id(headers: Dict[str, str], *, trust_forwarded_headers: bool = False) -> Optional[str]:
    if not trust_forwarded_headers:
        return None
    headers_lower = {k.lower(): v for k, v in headers.items()}
    if "x-spiffe-id" in headers_lower:
        return _valid_spiffe_id(headers_lower["x-spiffe-id"])

    xfcc = headers_lower.get("x-forwarded-client-cert", "")
    if xfcc:
        for part in xfcc.split(';'):
            if part.strip().startswith("URI="):
                return _valid_spiffe_id(part.split("=", 1)[1])
    return None


def extract_spiffe_id_from_jwt(auth_header: str, *, trust_unverified_subject: bool = False) -> Optional[str]:
    if not trust_unverified_subject:
        return None
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(' ', 1)[1]
    parts = token.split('.')
    if len(parts) == 3:
        try:
            payload = json.loads(base64url_decode(parts[1]).decode('utf-8'))
            return _valid_spiffe_id(payload.get("sub", ""))
        except Exception:
            pass
    return None


def verify_workload_request(
    headers: Dict[str, str],
    method: str,
    url: str,
    require_spiffe: bool = False,
    require_dpop: bool = False,
    trust_forwarded_spiffe_headers: bool | None = None,
    trust_bearer_spiffe_subject: bool = False,
) -> Dict[str, Any]:
    result = {
        "verified": False,
        "spiffe_id": None,
        "dpop_jkt": None,
        "error": None
    }

    headers_lower = {k.lower(): v for k, v in headers.items()}
    if trust_forwarded_spiffe_headers is None:
        trust_forwarded_spiffe_headers = str(
            os.getenv(TRUSTED_SPIFFE_HEADER_ENV, "false")
        ).strip().lower() in {"1", "true", "yes", "on"}

    spiffe_id = extract_spiffe_id(
        headers,
        trust_forwarded_headers=bool(trust_forwarded_spiffe_headers),
    )
    if not spiffe_id and "authorization" in headers_lower:
        spiffe_id = extract_spiffe_id_from_jwt(
            headers_lower["authorization"],
            trust_unverified_subject=trust_bearer_spiffe_subject,
        )

    result["spiffe_id"] = spiffe_id

    if require_spiffe and not spiffe_id:
        result["error"] = "missing_spiffe_identity"
        return result

    dpop_token = headers_lower.get("dpop")
    if dpop_token:
        try:
            jkt = verify_dpop_jwt(dpop_token, method, url)
            parts = dpop_token.split('.')
            payload = json.loads(base64url_decode(parts[1]).decode('utf-8'))
            check_replay(payload.get("jti"), time.time(), key_thumbprint=jkt)
            result["dpop_jkt"] = jkt
        except Exception as e:
            result["error"] = f"dpop_verification_failed: {e}"
            return result
    elif require_dpop:
        result["error"] = "missing_dpop_proof"
        return result

    result["verified"] = True
    return result
