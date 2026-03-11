from __future__ import annotations

import pytest

from seedcore.ops.source_registration.normalizer import (
    normalize_source_registration_context,
)


def test_normalize_source_registration_context_canonicalizes_multimodal_inputs() -> None:
    result = normalize_source_registration_context(
        {
            "registration_id": "reg-1",
            "source_claim_id": "claim-9",
            "lot_id": "LOT-7",
            "producer_id": "Producer-3",
            "claimed_origin": {"zone_id": "zone-a", "altitude_meters": "2430"},
            "artifacts": [
                {
                    "artifact_id": "art-1",
                    "artifact_type": " Honeycomb Macro Image ",
                    "uri": "s3://bucket/honeycomb.jpg",
                    "sha256": "ABC123",
                },
                {
                    "artifact_id": "art-2",
                    "artifact_type": "seal macro image",
                    "uri": "s3://bucket/seal.jpg",
                    "sha256": "DEF456",
                },
            ],
            "measurements": {
                "GPS": {
                    "altitude_meters": "2438.7",
                    "lat": 18.801,
                    "lon": 98.921,
                    "unit": "Meters",
                },
                "Purity Score": {
                    "value": "0.992",
                    "unit": "Ratio",
                },
            },
            "tracking_events": [
                {
                    "id": "evt-1",
                    "event_type": "source_claim_declared",
                    "source_kind": "source_declaration",
                    "payload": {},
                },
                {
                    "id": "evt-2",
                    "event_type": "operator_request_received",
                    "source_kind": "operator_request",
                    "payload": {"command": "submit_for_decision"},
                },
            ],
        },
        multimodal_context={"camera_id": "cam-9"},
        task_description="Source registration for rare honey",
    )

    registration = result.registration
    assert registration["ingress_event_ids"] == ["evt-1", "evt-2"]
    assert registration["artifacts"][0]["artifact_type"] == "honeycomb_macro_image"
    assert registration["artifacts"][0]["sha256"] == "abc123"
    assert registration["measurements"]["gps"]["value"] == pytest.approx(2438.7)
    assert registration["measurements"]["gps"]["unit"] == "meters"
    assert registration["measurements"]["purity_score"]["value"] == pytest.approx(0.992)
    assert registration["normalization"]["stream_kinds"] == [
        "source_declaration",
        "operator_request",
        "provenance_scan",
        "telemetry",
    ]
    assert registration["normalization"]["modalities"] == [
        "declaration",
        "vision",
        "sensor",
        "biosignature",
        "operator",
    ]
    assert registration["normalization"]["cognitive_enrichment_required"] is True
    assert "submit_for_decision" in registration["normalization"]["operator_commands"]
    assert "Purity" not in result.eventizer_text
    assert "purity_score=0.992 ratio" in result.eventizer_text

    multimodal = result.multimodal_context
    assert multimodal["modality"] == "vision"
    assert multimodal["source_registration"]["artifact_types"] == [
        "honeycomb_macro_image",
        "seal_macro_image",
    ]
