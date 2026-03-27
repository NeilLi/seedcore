from __future__ import annotations

import base64
import json
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from seedcore.models.evidence_bundle import TransparencyProof
from seedcore.ops.evidence import transparency as transparency_module


def _generate_p256_public_key_b64() -> str:
    private_key = ec.generate_private_key(ec.SECP256R1())
    return base64.b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
    ).decode("ascii")


def _rekor_entry(entry_id: str, payload_hash_hex: str) -> dict[str, object]:
    body = {
        "kind": "hashedrekord",
        "spec": {"data": {"hash": {"algorithm": "sha256", "value": payload_hash_hex}}},
    }
    body_b64 = base64.b64encode(
        json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    return {
        entry_id: {
            "integratedTime": 1_775_118_640,
            "logIndex": 17,
            "logID": "rekor-test-log",
            "body": body_b64,
        }
    }


def test_rekor_anchor_success(monkeypatch) -> None:
    payload_hash_hex = "ab" * 32
    payload_hash = f"sha256:{payload_hash_hex}"
    entry_id = "rekor-entry-test-001"
    observed: dict[str, object] = {}

    monkeypatch.setenv("SEEDCORE_TRANSPARENCY_MODE", "rekor")
    monkeypatch.setenv("SEEDCORE_TRANSPARENCY_LOG_URL", "https://rekor.example")
    monkeypatch.setenv("SEEDCORE_TRANSPARENCY_HTTP_TIMEOUT_SECONDS", "2.0")

    def _fake_post(url: str, payload: object, *, timeout_s: float) -> object:
        observed["url"] = url
        observed["payload"] = payload
        observed["timeout_s"] = timeout_s
        return _rekor_entry(entry_id, payload_hash_hex)

    def _fake_get(url: str, *, timeout_s: float) -> object:
        observed["get_url"] = url
        observed["get_timeout_s"] = timeout_s
        return _rekor_entry(entry_id, payload_hash_hex)

    monkeypatch.setattr(transparency_module, "_post_json", _fake_post)
    monkeypatch.setattr(transparency_module, "_get_json", _fake_get)

    proof = transparency_module.anchor_receipt_hash(
        payload_hash=payload_hash,
        signature=base64.b64encode(b"test-signature").decode("ascii"),
        public_key_material=_generate_p256_public_key_b64(),
        key_algorithm="ecdsa_p256_sha256",
        enabled=True,
    )
    assert proof.status == "anchored"
    assert proof.log_url == "https://rekor.example"
    assert proof.entry_id == entry_id
    assert proof.details and proof.details["provider"] == "rekor"
    assert observed["url"] == "https://rekor.example/api/v1/log/entries"
    assert observed["get_url"] == f"https://rekor.example/api/v1/log/entries/{entry_id}"


def test_rekor_verify_detects_hash_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("SEEDCORE_TRANSPARENCY_MODE", "rekor")
    expected_payload_hash = f"sha256:{'11' * 32}"
    entry_id = "rekor-entry-mismatch-001"

    def _fake_get(url: str, *, timeout_s: float) -> object:
        del url, timeout_s
        return _rekor_entry(entry_id, "22" * 32)

    monkeypatch.setattr(transparency_module, "_get_json", _fake_get)
    proof = TransparencyProof(
        status="anchored",
        log_url="https://rekor.example",
        entry_id=entry_id,
    )
    assert (
        transparency_module.verify_transparency_proof(
            transparency=proof,
            payload_hash=expected_payload_hash,
        )
        is False
    )
