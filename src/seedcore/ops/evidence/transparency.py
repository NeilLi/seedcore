from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
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
    if mode == "local":
        return _anchor_local(payload_hash)
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
        if mode == "local":
            return _verify_local_hash_binding(
                log_url=transparency.log_url,
                entry_id=transparency.entry_id,
                expected_hash=payload_hash,
            )
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


def _local_log_path() -> Path:
    configured = os.getenv("SEEDCORE_TRANSPARENCY_LOCAL_LOG_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path("/tmp/seedcore_transparency_log.jsonl")


def _anchor_local(payload_hash: str) -> TransparencyProof:
    log_path = _local_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rows = _read_local_log_entries(log_path)
    previous_entry_id = None
    previous_proof_hash = None
    if rows:
        previous = rows[-1]
        previous_entry_id = str(previous.get("entry_id") or "").strip() or None
        previous_proof_hash = str(previous.get("proof_hash") or "").strip() or None
    integrated_time = datetime.now(timezone.utc).isoformat()
    entry_id = sha256(
        f"{payload_hash}:{integrated_time}:{previous_entry_id or ''}".encode("utf-8")
    ).hexdigest()
    proof_hash = sha256(
        f"{entry_id}:{payload_hash}:{previous_proof_hash or ''}".encode("utf-8")
    ).hexdigest()
    record = {
        "entry_id": entry_id,
        "integrated_time": integrated_time,
        "payload_hash": payload_hash,
        "proof_hash": proof_hash,
        "previous_entry_id": previous_entry_id,
        "previous_proof_hash": previous_proof_hash,
    }
    with log_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False))
        fp.write("\n")
    return TransparencyProof(
        status="anchored",
        log_url=f"file://{log_path}",
        entry_id=entry_id,
        integrated_time=integrated_time,
        proof_hash=proof_hash,
        details={"provider": "local_append_only"},
    )


def _read_local_log_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except Exception:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
    return rows


def _verify_local_hash_binding(*, log_url: Optional[str], entry_id: Optional[str], expected_hash: str) -> bool:
    if not isinstance(log_url, str) or not log_url.strip():
        return False
    if not isinstance(entry_id, str) or not entry_id.strip():
        return False
    raw_path = log_url.strip()
    if raw_path.startswith("file://"):
        raw_path = raw_path[len("file://") :]
    path = Path(raw_path).expanduser()
    rows = _read_local_log_entries(path)
    if not rows:
        return False
    previous_proof_hash: Optional[str] = None
    for row in rows:
        current_entry_id = str(row.get("entry_id") or "").strip()
        current_payload_hash = str(row.get("payload_hash") or "").strip()
        current_proof_hash = str(row.get("proof_hash") or "").strip()
        expected_proof_hash = sha256(
            f"{current_entry_id}:{current_payload_hash}:{previous_proof_hash or ''}".encode("utf-8")
        ).hexdigest()
        if current_proof_hash != expected_proof_hash:
            return False
        if current_entry_id == entry_id:
            return current_payload_hash == expected_hash
        previous_proof_hash = current_proof_hash
    return False


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
