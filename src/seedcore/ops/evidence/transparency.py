from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from seedcore.models.evidence_bundle import TransparencyProof


def anchor_receipt_hash(
    *,
    payload_hash: str,
    signature: Optional[str],
    public_key_material: Optional[str],
    key_algorithm: str,
    enabled: bool,
) -> TransparencyProof:
    if not enabled:
        return TransparencyProof(status="not_configured")
    mode = os.getenv("SEEDCORE_TRANSPARENCY_MODE", "stub").strip().lower()
    if mode == "rekor":
        return _anchor_with_rekor(
            payload_hash=payload_hash,
            signature=signature,
            public_key_material=public_key_material,
            key_algorithm=key_algorithm,
        )
    return _anchor_stub(payload_hash)


def verify_transparency_proof(
    *,
    transparency: TransparencyProof,
    payload_hash: str,
) -> bool:
    if transparency.status != "anchored":
        return False
    mode = os.getenv("SEEDCORE_TRANSPARENCY_MODE", "stub").strip().lower()
    if mode != "rekor":
        return True
    if not transparency.log_url or not transparency.entry_id:
        return False
    hash_hex = payload_hash.removeprefix("sha256:").strip().lower()
    if not hash_hex:
        return False
    timeout_s = float(os.getenv("SEEDCORE_TRANSPARENCY_HTTP_TIMEOUT_SECONDS", "8.0"))
    return _verify_rekor_hash_binding(
        log_url=transparency.log_url.strip().rstrip("/"),
        entry_id=transparency.entry_id,
        expected_hash_hex=hash_hex,
        timeout_s=timeout_s,
    )


def _anchor_stub(payload_hash: str) -> TransparencyProof:
    log_url = os.getenv("SEEDCORE_TRANSPARENCY_LOG_URL", "https://rekor.sigstore.dev")
    integrated_time = datetime.now(timezone.utc).isoformat()
    entry_material = f"{log_url}:{payload_hash}:{integrated_time}"
    entry_id = sha256(entry_material.encode("utf-8")).hexdigest()
    proof_hash = sha256(f"{entry_id}:{payload_hash}".encode("utf-8")).hexdigest()
    return TransparencyProof(
        status="anchored",
        log_url=log_url,
        entry_id=entry_id,
        integrated_time=integrated_time,
        proof_hash=proof_hash,
        details={"provider": "local_transparency_stub"},
    )


def _anchor_with_rekor(
    *,
    payload_hash: str,
    signature: Optional[str],
    public_key_material: Optional[str],
    key_algorithm: str,
) -> TransparencyProof:
    log_url = os.getenv("SEEDCORE_TRANSPARENCY_LOG_URL", "https://rekor.sigstore.dev").strip().rstrip("/")
    timeout_s = float(os.getenv("SEEDCORE_TRANSPARENCY_HTTP_TIMEOUT_SECONDS", "8.0"))
    hash_hex = payload_hash.removeprefix("sha256:").strip().lower()
    if not hash_hex:
        return TransparencyProof(
            status="anchor_verification_failed",
            log_url=log_url,
            details={"provider": "rekor", "error": "missing_payload_hash"},
        )
    if not signature:
        return TransparencyProof(
            status="anchor_verification_failed",
            log_url=log_url,
            details={"provider": "rekor", "error": "missing_signature"},
        )
    public_key_pem = _public_key_pem_from_material(public_key_material, key_algorithm)
    if not public_key_pem:
        return TransparencyProof(
            status="anchor_verification_failed",
            log_url=log_url,
            details={"provider": "rekor", "error": "missing_or_invalid_public_key"},
        )

    body = {
        "apiVersion": "0.0.1",
        "kind": "hashedrekord",
        "spec": {
            "data": {"hash": {"algorithm": "sha256", "value": hash_hex}},
            "signature": {
                "content": signature,
                "publicKey": {
                    "content": base64.b64encode(public_key_pem.encode("utf-8")).decode("ascii")
                },
            },
        },
    }
    try:
        entry = _post_json(
            f"{log_url}/api/v1/log/entries",
            body,
            timeout_s=timeout_s,
        )
    except Exception as exc:
        return TransparencyProof(
            status="anchor_verification_failed",
            log_url=log_url,
            details={"provider": "rekor", "error": f"rekor_upload_failed:{exc}"},
        )

    entry_id, integrated_time, proof_hash, details = _parse_rekor_entry(entry)
    if not entry_id:
        return TransparencyProof(
            status="anchor_verification_failed",
            log_url=log_url,
            details={"provider": "rekor", "error": "rekor_upload_response_invalid"},
        )

    verified = _verify_rekor_hash_binding(
        log_url=log_url,
        entry_id=entry_id,
        expected_hash_hex=hash_hex,
        timeout_s=timeout_s,
    )
    return TransparencyProof(
        status="anchored" if verified else "anchor_verification_failed",
        log_url=log_url,
        entry_id=entry_id,
        integrated_time=integrated_time,
        proof_hash=proof_hash,
        details={"provider": "rekor", **details},
    )


def _parse_rekor_entry(response_payload: Any) -> tuple[Optional[str], Optional[str], Optional[str], dict[str, Any]]:
    if not isinstance(response_payload, dict) or not response_payload:
        return None, None, None, {}
    entry_id = next(iter(response_payload.keys()), None)
    entry_obj = response_payload.get(entry_id) if isinstance(entry_id, str) else None
    if not isinstance(entry_obj, dict):
        return None, None, None, {}
    integrated_time_raw = entry_obj.get("integratedTime")
    integrated_time = None
    if isinstance(integrated_time_raw, (int, float)):
        integrated_time = datetime.fromtimestamp(float(integrated_time_raw), tz=timezone.utc).isoformat()
    body_b64 = entry_obj.get("body")
    proof_hash = None
    if isinstance(body_b64, str) and body_b64.strip():
        proof_hash = sha256(body_b64.encode("utf-8")).hexdigest()
    details = {
        "log_index": entry_obj.get("logIndex"),
        "log_id": entry_obj.get("logID"),
    }
    return entry_id, integrated_time, proof_hash, details


def _verify_rekor_hash_binding(
    *,
    log_url: str,
    entry_id: str,
    expected_hash_hex: str,
    timeout_s: float,
) -> bool:
    try:
        response = _get_json(f"{log_url}/api/v1/log/entries/{urllib.parse.quote(entry_id)}", timeout_s=timeout_s)
    except Exception:
        return False
    if not isinstance(response, dict):
        return False
    entry = response.get(entry_id)
    if not isinstance(entry, dict):
        return False
    body_b64 = entry.get("body")
    if not isinstance(body_b64, str) or not body_b64.strip():
        return False
    try:
        body_json = json.loads(base64.b64decode(body_b64).decode("utf-8"))
    except Exception:
        return False
    observed_hash = (
        body_json.get("spec", {})
        .get("data", {})
        .get("hash", {})
        .get("value")
    )
    return isinstance(observed_hash, str) and observed_hash.strip().lower() == expected_hash_hex.lower()


def _public_key_pem_from_material(public_key_material: Optional[str], key_algorithm: str) -> Optional[str]:
    if not isinstance(public_key_material, str) or not public_key_material.strip():
        return None
    raw = public_key_material.strip()
    if "BEGIN PUBLIC KEY" in raw:
        return raw
    try:
        public_key_bytes = base64.b64decode(raw, validate=True)
    except Exception:
        return None
    try:
        if key_algorithm == "ecdsa_p256_sha256":
            key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public_key_bytes)
            return key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("utf-8")
        if key_algorithm == "ed25519":
            key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
            return key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("utf-8")
    except Exception:
        return None
    return None


def _post_json(url: str, payload: Any, *, timeout_s: float) -> Any:
    request = urllib.request.Request(
        url=url,
        method="POST",
        data=json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout_s, context=context) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def _get_json(url: str, *, timeout_s: float) -> Any:
    request = urllib.request.Request(url=url, method="GET")
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout_s, context=context) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))
