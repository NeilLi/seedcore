from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401

import seedcore.api.routers.source_registrations_router as source_registrations_router_module
from seedcore.models.source_registration import (
    SourceRegistration,
    SourceRegistrationArtifact,
    SourceRegistrationMeasurement,
    SourceRegistrationStatus,
    TrackingEvent,
    TrackingEventSourceKind,
    TrackingEventType,
)


def test_measurement_payload_for_tracking_event_promotes_gps_metadata() -> None:
    measurement = source_registrations_router_module.MeasurementCreate(
        measurement_type="gps",
        value=2438.7,
        unit="meters",
        measured_at=datetime(2026, 3, 13, 10, 3, tzinfo=timezone.utc),
        sensor_id="gps-demo-01",
        quality_score=0.99,
        metadata={
            "lat": 18.801,
            "lon": 98.921,
            "altitude_meters": 2438.7,
        },
    )

    payload = source_registrations_router_module._measurement_payload_for_tracking_event(
        measurement
    )

    assert payload["measurement_type"] == "gps"
    assert payload["lat"] == 18.801
    assert payload["lon"] == 98.921
    assert payload["altitude_meters"] == 2438.7
    assert payload["metadata"]["altitude_meters"] == 2438.7


def test_build_raw_source_registration_uses_latest_measurements_and_stable_order() -> None:
    registration = SourceRegistration(
        id=uuid.uuid4(),
        lot_id="lot-demo-001",
        producer_id="producer-demo-001",
        status=SourceRegistrationStatus.INGESTING,
        claimed_origin={"zone_id": "vault_alpha", "altitude_meters": 2430},
        collection_site={"site_id": "site-demo-001"},
        submitted_task_id=uuid.uuid4(),
    )
    artifact_early = SourceRegistrationArtifact(
        id=uuid.uuid4(),
        registration_id=registration.id,
        artifact_type="honeycomb_macro_image",
        uri="s3://seedcore-demo/happy/honeycomb_macro.jpg",
        sha256="happy-honeycomb-sha256",
        captured_at=datetime(2026, 3, 13, 10, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 13, 10, 1, tzinfo=timezone.utc),
        meta_data={"lens": "macro"},
    )
    artifact_late = SourceRegistrationArtifact(
        id=uuid.uuid4(),
        registration_id=registration.id,
        artifact_type="seal_macro_image",
        uri="s3://seedcore-demo/happy/seal_macro.jpg",
        sha256="happy-seal-sha256",
        captured_at=datetime(2026, 3, 13, 10, 2, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 13, 10, 2, tzinfo=timezone.utc),
        meta_data={"lens": "macro"},
    )
    humidity_older = SourceRegistrationMeasurement(
        id=uuid.uuid4(),
        registration_id=registration.id,
        measurement_type="humidity",
        value=61.1,
        unit="percent",
        measured_at=datetime(2026, 3, 13, 10, 3, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 13, 10, 3, tzinfo=timezone.utc),
        sensor_id="humid-demo-01",
        meta_data={},
    )
    humidity_latest = SourceRegistrationMeasurement(
        id=uuid.uuid4(),
        registration_id=registration.id,
        measurement_type="humidity",
        value=67.2,
        unit="percent",
        measured_at=datetime(2026, 3, 13, 10, 6, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 13, 10, 6, tzinfo=timezone.utc),
        sensor_id="humid-demo-01",
        meta_data={},
    )
    gps_measurement = SourceRegistrationMeasurement(
        id=uuid.uuid4(),
        registration_id=registration.id,
        measurement_type="gps",
        value=2438.7,
        unit="meters",
        measured_at=datetime(2026, 3, 13, 10, 4, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 13, 10, 4, tzinfo=timezone.utc),
        sensor_id="gps-demo-01",
        meta_data={
            "lat": 18.801,
            "lon": 98.921,
            "altitude_meters": 2438.7,
        },
    )
    claim_event = TrackingEvent(
        id=uuid.uuid4(),
        registration_id=registration.id,
        event_type=TrackingEventType.SOURCE_CLAIM_DECLARED,
        source_kind=TrackingEventSourceKind.SOURCE_DECLARATION,
        payload={"source_claim_id": "claim-demo-001"},
        sha256="claim-hash",
        captured_at=datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc),
    )
    submit_event = TrackingEvent(
        id=uuid.uuid4(),
        registration_id=registration.id,
        event_type=TrackingEventType.OPERATOR_REQUEST_RECEIVED,
        source_kind=TrackingEventSourceKind.OPERATOR_REQUEST,
        payload={"command": "submit_for_decision"},
        sha256="submit-hash",
        captured_at=datetime(2026, 3, 13, 10, 7, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 13, 10, 7, tzinfo=timezone.utc),
    )

    raw = source_registrations_router_module._build_raw_source_registration(
        registration,
        artifacts=[artifact_late, artifact_early],
        measurements=[humidity_latest, gps_measurement, humidity_older],
        tracking_events=[submit_event, claim_event],
    )

    assert raw["status"] == "ingesting"
    assert raw["submitted_task_id"] == str(registration.submitted_task_id)
    assert [item["artifact_type"] for item in raw["artifacts"]] == [
        "honeycomb_macro_image",
        "seal_macro_image",
    ]
    assert raw["measurements"]["humidity"]["value"] == 67.2
    assert raw["measurements"]["gps"]["altitude_meters"] == 2438.7
    assert [item["event_type"] for item in raw["tracking_events"]] == [
        "source_claim_declared",
        "operator_request_received",
    ]
