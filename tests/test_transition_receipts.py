from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from seedcore.hal.custody.transition_receipts import (
    build_transition_receipt,
    verify_transition_receipt,
)


def test_build_and_verify_transition_receipt_with_ed25519(monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    endpoint_id = "robot_sim://pybullet_r2d2_01"

    monkeypatch.setenv(
        "SEEDCORE_HAL_RECEIPT_PRIVATE_KEY_B64",
        base64.b64encode(private_bytes).decode("ascii"),
    )
    monkeypatch.setenv(
        "SEEDCORE_HAL_RECEIPT_PUBLIC_KEYS_JSON",
        json.dumps({endpoint_id: base64.b64encode(public_bytes).decode("ascii")}),
    )

    receipt = build_transition_receipt(
        intent_id="intent-ed-1",
        token_id="tok-ed-1",
        actuator_endpoint=endpoint_id,
        hardware_uuid="robot-hw-1",
        actuator_result_hash="hash-ed-1",
        target_zone="zone-ed",
        to_zone="zone-ed",
    )

    assert receipt["proof_type"] == "ed25519"
    assert isinstance(receipt.get("key_id"), str)
    assert verify_transition_receipt(
        receipt,
        expected_intent_id="intent-ed-1",
        expected_token_id="tok-ed-1",
        expected_endpoint_id=endpoint_id,
    ) is None


def test_verify_transition_receipt_rejects_missing_registered_public_key(monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )

    monkeypatch.setenv(
        "SEEDCORE_HAL_RECEIPT_PRIVATE_KEY_B64",
        base64.b64encode(private_bytes).decode("ascii"),
    )
    monkeypatch.delenv("SEEDCORE_HAL_RECEIPT_PUBLIC_KEYS_JSON", raising=False)
    monkeypatch.delenv("SEEDCORE_HAL_RECEIPT_TRUST_EMBEDDED_PUBLIC_KEY", raising=False)

    receipt = build_transition_receipt(
        intent_id="intent-ed-2",
        token_id="tok-ed-2",
        actuator_endpoint="robot_sim://missing-registry",
        hardware_uuid="robot-hw-2",
        actuator_result_hash="hash-ed-2",
    )

    assert verify_transition_receipt(receipt) == "missing_public_key"
