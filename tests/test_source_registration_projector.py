from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List

import pytest

from seedcore.models.source_registration import (
    SourceRegistration,
    SourceRegistrationStatus,
    TrackingEvent,
    TrackingEventSourceKind,
    TrackingEventType,
)
from seedcore.ops.source_registration.projector import (
    project_tracking_event,
    record_tracking_event,
)


class _ScalarResult:
    def __init__(self, *, first: Any = None, all_items: List[Any] | None = None):
        self._first = first
        self._all = all_items or []

    def scalars(self) -> "_ScalarResult":
        return self

    def first(self) -> Any:
        return self._first

    def all(self) -> List[Any]:
        return list(self._all)


class FakeAsyncSession:
    def __init__(self, *, get_result: Any = None, execute_results: List[_ScalarResult] | None = None):
        self.added: List[Any] = []
        self._get_result = get_result
        self._execute_results = list(execute_results or [])
        self.flush_count = 0

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flush_count += 1

    async def get(self, model: Any, key: Any) -> Any:
        return self._get_result

    async def execute(self, statement: Any) -> _ScalarResult:
        if self._execute_results:
            return self._execute_results.pop(0)
        return _ScalarResult()


def _make_registration() -> SourceRegistration:
    return SourceRegistration(
        lot_id="lot-1",
        producer_id="producer-1",
        status=SourceRegistrationStatus.DRAFT,
        claimed_origin={},
        collection_site={},
        snapshot_id=7,
    )


@pytest.mark.asyncio
async def test_record_tracking_event_projects_source_claim_into_registration() -> None:
    registration = _make_registration()
    session = FakeAsyncSession(get_result=registration)

    event = await record_tracking_event(
        session,
        registration=registration,
        event_type=TrackingEventType.SOURCE_CLAIM_DECLARED,
        source_kind=TrackingEventSourceKind.SOURCE_DECLARATION,
        payload={
            "source_claim_id": "claim-1",
            "lot_id": "lot-99",
            "producer_id": "producer-99",
            "rare_grade_profile_id": "rare-gold",
            "claimed_origin": {"zone_id": "zone-a", "altitude_meters": 2430},
            "collection_site": {"site_id": "site-1"},
            "collected_at": "2026-03-11T10:00:00+00:00",
        },
        captured_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
    )

    assert isinstance(session.added[0], TrackingEvent)
    assert event.event_type == TrackingEventType.SOURCE_CLAIM_DECLARED
    assert registration.source_claim_id == "claim-1"
    assert registration.lot_id == "lot-99"
    assert registration.producer_id == "producer-99"
    assert registration.rare_grade_profile_id == "rare-gold"
    assert registration.claimed_origin["zone_id"] == "zone-a"
    assert registration.collection_site["site_id"] == "site-1"
    assert registration.status == SourceRegistrationStatus.INGESTING
    assert event.projected_at is not None


@pytest.mark.asyncio
async def test_project_tracking_event_creates_provenance_artifact_projection() -> None:
    registration = _make_registration()
    session = FakeAsyncSession(execute_results=[_ScalarResult(), _ScalarResult()])
    event = TrackingEvent(
        registration_id=registration.id,
        event_type=TrackingEventType.PROVENANCE_SCAN_CAPTURED,
        source_kind=TrackingEventSourceKind.PROVENANCE_SCAN,
        payload={
            "artifact_type": "honeycomb_macro_image",
            "uri": "s3://bucket/honeycomb.jpg",
            "sha256": "abc123",
            "captured_at": "2026-03-11T10:01:00+00:00",
            "device_id": "cam-1",
            "metadata": {"lens": "macro"},
        },
        sha256="abc123",
        captured_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
    )

    await project_tracking_event(session, event, registration=registration)

    artifact = next(item for item in session.added if item.__class__.__name__ == "SourceRegistrationArtifact")
    assert artifact.registration_id == registration.id
    assert artifact.source_event_id == event.id
    assert artifact.artifact_type == "honeycomb_macro_image"
    assert artifact.device_id == "cam-1"
    assert artifact.meta_data["lens"] == "macro"


@pytest.mark.asyncio
async def test_project_tracking_event_creates_measurement_projection_with_gps_metadata() -> None:
    registration = _make_registration()
    session = FakeAsyncSession(execute_results=[_ScalarResult(all_items=[])])
    event = TrackingEvent(
        registration_id=registration.id,
        event_type=TrackingEventType.ENVIRONMENTAL_READING_RECORDED,
        source_kind=TrackingEventSourceKind.TELEMETRY,
        payload={
            "measurement_type": "gps",
            "value": 2438.7,
            "unit": "meters",
            "lat": 18.801,
            "lon": 98.921,
            "altitude_meters": 2438.7,
            "sensor_id": "gps-7",
        },
        sha256="gpshash",
        captured_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
    )

    await project_tracking_event(session, event, registration=registration)

    measurement = next(item for item in session.added if item.__class__.__name__ == "SourceRegistrationMeasurement")
    assert measurement.registration_id == registration.id
    assert measurement.source_event_id == event.id
    assert measurement.measurement_type == "gps"
    assert measurement.value == pytest.approx(2438.7)
    assert measurement.sensor_id == "gps-7"
    assert measurement.meta_data["lat"] == pytest.approx(18.801)
    assert measurement.meta_data["lon"] == pytest.approx(98.921)
    assert measurement.meta_data["altitude_meters"] == pytest.approx(2438.7)
