from __future__ import annotations

import pytest
from fastapi import HTTPException

from seedcore.hal.custody.forensic_sealer import ForensicSealer
from seedcore.hal.service.main import _validate_hashed_media_references


def test_forensic_sealer_pilot_uses_transition_receipt_and_media_hashes():
    sealer = ForensicSealer(device_identity="hardware-1")
    transition_receipt = {
        "payload_hash": "payload-hash-1",
        "signed_payload": {
            "actuator_result_hash": "trajectory-hash-1",
        },
    }
    media_refs = [
        {"sha256": "sha256:media-a", "uri": "camera://line-a/front"},
        {"sha256": "sha256:media-b", "uri": "s3://bucket/frame-2.jpg"},
    ]

    event = sealer.seal_custody_event_pilot(
        event_id="urn:seedcore:event:pilot-1",
        platform_state="allow",
        policy_hash="policy-hash-1",
        auth_token="token-1",
        from_zone="zone-a",
        to_zone="zone-b",
        transition_receipt=transition_receipt,
        actuator_telemetry={},
        media_hash_references=media_refs,
        trajectory_hash=None,
        environmental_data={"temperatureC": 23.1},
    )

    payload = event.model_dump(mode="json", by_alias=True)
    assert payload["@type"] == "seedcore:SeedCoreCustodyEvent"
    assert payload["pre_contact_evidence"]["voc_profile"]["transitionReceiptHash"] == "payload-hash-1"
    assert payload["pre_contact_evidence"]["vision_baseline"]["fingerprintHash"].startswith("sha256:")
    assert payload["manipulation_telemetry"]["trajectory_hash"] == "trajectory-hash-1"


def test_validate_hashed_media_references_rejects_social_urls():
    with pytest.raises(HTTPException) as exc:
        _validate_hashed_media_references(
            [{"sha256": "sha256:abc", "uri": "https://youtube.com/watch?v=123"}]
        )
    assert exc.value.status_code == 422
    assert "social/video URLs" in str(exc.value.detail)


def test_validate_hashed_media_references_requires_hash_digest():
    with pytest.raises(HTTPException) as exc:
        _validate_hashed_media_references(
            [{"uri": "camera://line-a/front"}]
        )
    assert exc.value.status_code == 422
    assert "requires sha256/hash/digest" in str(exc.value.detail)


def test_validate_hashed_media_references_accepts_non_social_references():
    _validate_hashed_media_references(
        [{"sha256": "sha256:abc", "uri": "s3://bucket/frame.jpg"}]
    )
