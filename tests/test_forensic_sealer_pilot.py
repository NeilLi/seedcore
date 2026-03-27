from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from seedcore.hal.custody.forensic_sealer import ForensicSealer


def _generate_p256_private_key_pem() -> str:
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def test_forensic_sealer_pilot_uses_signed_hal_capture_envelope():
    sealer = ForensicSealer(device_identity="hardware-1")
    media_refs = [
        {"sha256": "sha256:media-a", "uri": "camera://line-a/front"},
        {"sha256": "sha256:media-b", "uri": "s3://bucket/frame-2.jpg"},
    ]

    event = sealer.seal_custody_event_pilot(
        event_id="urn:seedcore:event:pilot-1",
        platform_state="allow",
        policy_hash="policy-receipt-1",
        auth_token="token-1",
        from_zone="zone-a",
        to_zone="zone-b",
        transition_receipt={"transition_receipt_id": "tr-1", "actuator_result_hash": "trajectory-hash-1"},
        actuator_telemetry={},
        media_hash_references=media_refs,
        trajectory_hash=None,
        environmental_data={"temperatureC": 23.1},
    )

    payload = event.model_dump(mode="json")
    assert payload["event_id"] == "urn:seedcore:event:pilot-1"
    assert payload["transition_receipt_id"] == "tr-1"
    assert payload["trajectory_hash"] == "trajectory-hash-1"
    assert payload["signer_metadata"]["signing_scheme"] == "hmac_sha256"
    assert payload["media_refs"][-1]["from_zone"] == "zone-a"
    assert payload["media_refs"][-1]["to_zone"] == "zone-b"


def test_forensic_sealer_requires_attested_signing_for_attested_hal_paths(monkeypatch):
    monkeypatch.delenv("SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_B64", raising=False)
    monkeypatch.delenv("SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_PEM", raising=False)

    sealer = ForensicSealer(device_identity="robot_sim://unit-1")

    with pytest.raises(ValueError, match="hal_capture requires Ed25519 signing"):
        sealer.seal_custody_event_pilot(
            event_id="urn:seedcore:event:pilot-2",
            platform_state="allow",
            policy_hash="policy-receipt-2",
            auth_token="token-2",
            from_zone="zone-a",
            to_zone="zone-b",
            transition_receipt={"transition_receipt_id": "tr-2", "actuator_result_hash": "trajectory-hash-2"},
            actuator_telemetry={},
            media_hash_references=[],
            trajectory_hash=None,
            environmental_data={"temperatureC": 22.0},
        )


def test_forensic_sealer_hardened_mode_uses_p256_trust_anchor(monkeypatch):
    monkeypatch.setenv("SEEDCORE_HARDENED_RESTRICTED_CUSTODY_MODE", "true")
    monkeypatch.setenv("SEEDCORE_SIGNER_PROVIDER_EXECUTION", "kms")
    monkeypatch.setenv("SEEDCORE_ECDSA_P256_PRIVATE_KEY_PEM", _generate_p256_private_key_pem())
    monkeypatch.setenv("SEEDCORE_ECDSA_P256_KEY_ID", "kms-hal-capture-k1")
    monkeypatch.setenv("SEEDCORE_RECEIPT_REQUIRED_TRUST_ANCHOR", "kms")
    monkeypatch.delenv("SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_B64", raising=False)
    monkeypatch.delenv("SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_PEM", raising=False)

    sealer = ForensicSealer(device_identity="robot_sim://unit-2")
    event = sealer.seal_custody_event_pilot(
        event_id="urn:seedcore:event:pilot-3",
        platform_state="allow",
        policy_hash="policy-receipt-3",
        auth_token="token-3",
        from_zone="zone-a",
        to_zone="zone-b",
        transition_receipt={"transition_receipt_id": "tr-3", "actuator_result_hash": "trajectory-hash-3"},
        actuator_telemetry={},
        media_hash_references=[],
        trajectory_hash=None,
        environmental_data={"temperatureC": 24.0},
    )

    payload = event.model_dump(mode="json")
    assert payload["signer_metadata"]["signing_scheme"] == "ecdsa_p256_sha256"
    assert payload["trust_proof"]["trust_anchor_type"] == "kms"
