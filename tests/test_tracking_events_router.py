from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, List
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401

from fastapi import FastAPI
from fastapi.testclient import TestClient

import seedcore.api.routers.tracking_events_router as tracking_events_router_module
from seedcore.models.source_registration import (
    SourceRegistration,
    SourceRegistrationStatus,
    TrackingEvent,
    TrackingEventSourceKind,
    TrackingEventType,
)


class _ScalarResult:
    def __init__(self, *, all_items: List[Any] | None = None):
        self._all = all_items or []

    def scalars(self) -> "_ScalarResult":
        return self

    def all(self) -> List[Any]:
        return list(self._all)


class FakeAsyncSession:
    def __init__(self, *, registration: SourceRegistration | None = None, events: List[TrackingEvent] | None = None):
        self.registration = registration
        self.events = events or []
        self.commit = AsyncMock()
        self.refresh = AsyncMock()

    async def get(self, model: Any, key: Any) -> Any:
        model_name = getattr(model, "__name__", "")
        if model_name == "SourceRegistration":
            return self.registration
        if model_name == "TrackingEvent":
            for event in self.events:
                if event.id == key:
                    return event
            return None
        return None

    async def execute(self, statement: Any) -> _ScalarResult:
        return _ScalarResult(all_items=self.events)


def _make_app(session: FakeAsyncSession) -> TestClient:
    app = FastAPI()
    app.include_router(tracking_events_router_module.router)

    async def override_session():
        return session

    app.dependency_overrides[tracking_events_router_module.get_async_pg_session] = override_session
    return TestClient(app)


def _make_registration() -> SourceRegistration:
    return SourceRegistration(
        id=uuid.uuid4(),
        lot_id="lot-1",
        producer_id="producer-1",
        status=SourceRegistrationStatus.INGESTING,
        claimed_origin={},
        collection_site={},
    )


def test_create_tracking_event_returns_projected_event(monkeypatch) -> None:
    registration = _make_registration()
    session = FakeAsyncSession(registration=registration)
    client = _make_app(session)

    projected_event = TrackingEvent(
        id=uuid.uuid4(),
        registration_id=registration.id,
        event_type=TrackingEventType.ENVIRONMENTAL_READING_RECORDED,
        source_kind=TrackingEventSourceKind.TELEMETRY,
        payload={"measurement_type": "humidity", "value": 67.2, "unit": "percent"},
        sha256="humidity-hash",
        captured_at=datetime(2026, 3, 11, 11, 0, tzinfo=timezone.utc),
        producer_id="sensor-hub",
        device_id="humid-1",
        correlation_id="corr-1",
        snapshot_id=7,
        projected_at=datetime(2026, 3, 11, 11, 0, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 11, 11, 0, tzinfo=timezone.utc),
    )

    async def fake_record_tracking_event(*args, **kwargs):
        return projected_event

    monkeypatch.setattr(
        tracking_events_router_module,
        "record_tracking_event",
        fake_record_tracking_event,
    )

    response = client.post(
        "/tracking-events",
        json={
            "registration_id": str(registration.id),
            "event_type": "environmental_reading_recorded",
            "source_kind": "telemetry",
            "payload": {"measurement_type": "humidity", "value": 67.2, "unit": "percent"},
            "producer_id": "sensor-hub",
            "device_id": "humid-1",
            "correlation_id": "corr-1",
            "snapshot_id": 7,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["registration_id"] == str(registration.id)
    assert body["event_type"] == "environmental_reading_recorded"
    assert body["source_kind"] == "telemetry"
    assert body["payload"]["measurement_type"] == "humidity"
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once()


def test_list_registration_tracking_events_returns_scoped_events() -> None:
    registration = _make_registration()
    matching_event = TrackingEvent(
        id=uuid.uuid4(),
        registration_id=registration.id,
        event_type=TrackingEventType.PROVENANCE_SCAN_CAPTURED,
        source_kind=TrackingEventSourceKind.PROVENANCE_SCAN,
        payload={"artifact_type": "honeycomb_macro_image"},
        sha256="scan-hash",
        captured_at=datetime(2026, 3, 11, 11, 5, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 11, 11, 5, tzinfo=timezone.utc),
    )
    session = FakeAsyncSession(registration=registration, events=[matching_event])
    client = _make_app(session)

    response = client.get(f"/source-registrations/{registration.id}/tracking-events")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(matching_event.id)
    assert body[0]["event_type"] == "provenance_scan_captured"
