from __future__ import annotations

from seedcore.hal.custody.forensic_sealer import ForensicSealer


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
