from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from seedcore.models.source_registration import (
    SourceRegistration,
    SourceRegistrationArtifact,
    SourceRegistrationMeasurement,
    SourceRegistrationStatus,
    TrackingEvent,
    TrackingEventSourceKind,
    TrackingEventType,
)


def compute_tracking_event_sha256(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


async def record_tracking_event(
    session: AsyncSession,
    *,
    registration: Optional[SourceRegistration] = None,
    event_type: TrackingEventType,
    source_kind: TrackingEventSourceKind,
    payload: Dict[str, Any],
    captured_at: Optional[datetime] = None,
    producer_id: Optional[str] = None,
    device_id: Optional[str] = None,
    operator_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    snapshot_id: Optional[int] = None,
    sha256: Optional[str] = None,
) -> TrackingEvent:
    event = TrackingEvent(
        registration_id=registration.id if registration is not None else None,
        event_type=event_type,
        source_kind=source_kind,
        payload=payload or {},
        sha256=sha256 or compute_tracking_event_sha256(payload or {}),
        captured_at=captured_at or datetime.now(timezone.utc),
        producer_id=producer_id,
        device_id=device_id,
        operator_id=operator_id,
        correlation_id=correlation_id,
        subject_type=subject_type,
        subject_id=subject_id,
        snapshot_id=snapshot_id or (registration.snapshot_id if registration is not None else None),
    )
    session.add(event)
    await session.flush()
    if registration is not None:
        await project_tracking_event(session, event, registration=registration)
    return event


async def project_tracking_event(
    session: AsyncSession,
    event: TrackingEvent,
    *,
    registration: Optional[SourceRegistration] = None,
) -> SourceRegistration:
    registration = registration or await session.get(SourceRegistration, event.registration_id)
    if registration is None:
        raise ValueError(f"SourceRegistration {event.registration_id} not found")

    payload = event.payload or {}
    if registration.snapshot_id is None and event.snapshot_id is not None:
        registration.snapshot_id = event.snapshot_id

    if event.event_type == TrackingEventType.SOURCE_CLAIM_DECLARED:
        if payload.get("source_claim_id") is not None:
            registration.source_claim_id = payload.get("source_claim_id")
        if payload.get("lot_id"):
            registration.lot_id = str(payload["lot_id"])
        if payload.get("producer_id"):
            registration.producer_id = str(payload["producer_id"])
        if payload.get("rare_grade_profile_id") is not None:
            registration.rare_grade_profile_id = payload.get("rare_grade_profile_id")
        if isinstance(payload.get("claimed_origin"), dict) and payload.get("claimed_origin"):
            registration.claimed_origin = {
                **dict(registration.claimed_origin or {}),
                **dict(payload["claimed_origin"]),
            }
        if isinstance(payload.get("collection_site"), dict) and payload.get("collection_site"):
            registration.collection_site = {
                **dict(registration.collection_site or {}),
                **dict(payload["collection_site"]),
            }
        if payload.get("collected_at") is not None:
            registration.collected_at = _coerce_datetime(payload.get("collected_at"))
        if registration.status == SourceRegistrationStatus.DRAFT:
            registration.status = SourceRegistrationStatus.INGESTING

    elif event.event_type in {
        TrackingEventType.PROVENANCE_SCAN_CAPTURED,
        TrackingEventType.SEAL_CHECK_CAPTURED,
    }:
        await _project_artifact_event(session, registration, event)
        if registration.status == SourceRegistrationStatus.DRAFT:
            registration.status = SourceRegistrationStatus.INGESTING

    elif event.event_type in {
        TrackingEventType.ENVIRONMENTAL_READING_RECORDED,
        TrackingEventType.BIO_SIGNATURE_RECORDED,
    }:
        await _project_measurement_event(session, registration, event)
        if registration.status == SourceRegistrationStatus.DRAFT:
            registration.status = SourceRegistrationStatus.INGESTING

    elif event.event_type == TrackingEventType.OPERATOR_REQUEST_RECEIVED:
        command = str(payload.get("command") or payload.get("request_type") or "").strip().lower()
        if payload.get("task_id") is not None:
            task_id = _coerce_optional_uuid(payload.get("task_id"))
            if task_id is not None:
                registration.submitted_task_id = task_id
        if command in {"submit", "submit_for_decision"}:
            registration.status = SourceRegistrationStatus.VERIFYING
        elif registration.status == SourceRegistrationStatus.DRAFT:
            registration.status = SourceRegistrationStatus.INGESTING

    event.projected_at = datetime.now(timezone.utc)
    await session.flush()
    return registration


async def _project_artifact_event(
    session: AsyncSession,
    registration: SourceRegistration,
    event: TrackingEvent,
) -> None:
    existing = (
        await session.execute(
            select(SourceRegistrationArtifact).where(
                SourceRegistrationArtifact.source_event_id == event.id
            )
        )
    ).scalars().first()
    if existing is not None:
        return

    payload = event.payload or {}
    artifact_sha = str(payload.get("sha256") or event.sha256)
    duplicate = (
        await session.execute(
            select(SourceRegistrationArtifact).where(
                SourceRegistrationArtifact.registration_id == registration.id,
                SourceRegistrationArtifact.sha256 == artifact_sha,
            )
        )
    ).scalars().first()
    if duplicate is not None:
        duplicate.source_event_id = event.id
        return

    session.add(
        SourceRegistrationArtifact(
            registration_id=registration.id,
            source_event_id=event.id,
            artifact_type=str(payload.get("artifact_type") or "unknown_artifact"),
            uri=str(payload.get("uri") or ""),
            sha256=artifact_sha,
            captured_at=_coerce_datetime(payload.get("captured_at")) or event.captured_at,
            captured_by=_coerce_optional_str(payload.get("captured_by")),
            device_id=_coerce_optional_str(payload.get("device_id") or event.device_id),
            content_type=_coerce_optional_str(payload.get("content_type")),
            meta_data=dict(payload.get("metadata") or {}),
        )
    )


async def _project_measurement_event(
    session: AsyncSession,
    registration: SourceRegistration,
    event: TrackingEvent,
) -> None:
    existing_rows = (
        await session.execute(
            select(SourceRegistrationMeasurement).where(
                SourceRegistrationMeasurement.source_event_id == event.id
            )
        )
    ).scalars().all()
    if existing_rows:
        return

    seen_projection_keys: set[str] = set()
    for measurement in _iter_measurements(event.payload or {}):
        measured_at = measurement["measured_at"] or event.captured_at
        projection_key = _measurement_projection_key(
            measurement,
            measured_at=measured_at,
        )
        if projection_key in seen_projection_keys:
            continue
        seen_projection_keys.add(projection_key)

        duplicate_rows = (
            await session.execute(
                select(SourceRegistrationMeasurement).where(
                    SourceRegistrationMeasurement.registration_id == registration.id,
                    SourceRegistrationMeasurement.measurement_type
                    == str(measurement["measurement_type"]),
                )
            )
        ).scalars().all()
        if any(
            _measurement_projection_key_for_row(row) == projection_key for row in duplicate_rows
        ):
            continue

        session.add(
            SourceRegistrationMeasurement(
                registration_id=registration.id,
                source_event_id=event.id,
                measurement_type=str(measurement["measurement_type"]),
                value=float(measurement["value"]),
                unit=str(measurement["unit"]),
                measured_at=measured_at,
                sensor_id=measurement["sensor_id"],
                raw_artifact_id=measurement["raw_artifact_id"],
                quality_score=measurement["quality_score"],
                meta_data=measurement["metadata"],
            )
        )


def _iter_measurements(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    if isinstance(payload.get("measurements"), list):
        for item in payload["measurements"]:
            if isinstance(item, dict):
                parsed = _normalize_measurement_dict(item)
                if parsed is not None:
                    yield parsed
        return

    if isinstance(payload.get("measurements"), dict):
        for measurement_type, item in payload["measurements"].items():
            if isinstance(item, dict):
                enriched = dict(item)
                enriched.setdefault("measurement_type", measurement_type)
                parsed = _normalize_measurement_dict(enriched)
                if parsed is not None:
                    yield parsed
        return

    parsed = _normalize_measurement_dict(payload)
    if parsed is not None:
        yield parsed


def _normalize_measurement_dict(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    measurement_type = raw.get("measurement_type")
    if not measurement_type:
        return None

    metadata = dict(raw.get("metadata") or {})
    lat = raw.get("lat", metadata.get("lat"))
    lon = raw.get("lon", metadata.get("lon"))
    altitude = raw.get("altitude_meters", metadata.get("altitude_meters"))
    if lat is not None:
        metadata.setdefault("lat", lat)
    if lon is not None:
        metadata.setdefault("lon", lon)
    if altitude is not None:
        metadata.setdefault("altitude_meters", altitude)

    value = raw.get("value")
    if value is None and altitude is not None:
        value = altitude
    if value is None:
        return None

    return {
        "measurement_type": str(measurement_type),
        "value": float(value),
        "unit": str(raw.get("unit") or ("geo" if measurement_type == "gps" else "unitless")),
        "measured_at": _coerce_datetime(raw.get("measured_at")),
        "sensor_id": _coerce_optional_str(raw.get("sensor_id")),
        "quality_score": _coerce_optional_float(raw.get("quality_score")),
        "raw_artifact_id": _coerce_optional_uuid(raw.get("raw_artifact_id")),
        "metadata": metadata,
    }


def _measurement_projection_key(
    measurement: Dict[str, Any],
    *,
    measured_at: Optional[datetime],
) -> str:
    normalized = {
        "measurement_type": str(measurement["measurement_type"]),
        "value": float(measurement["value"]),
        "unit": str(measurement["unit"]),
        "measured_at": measured_at.astimezone(timezone.utc).isoformat() if measured_at is not None else None,
        "sensor_id": measurement["sensor_id"],
        "raw_artifact_id": str(measurement["raw_artifact_id"]) if measurement["raw_artifact_id"] is not None else None,
        "quality_score": measurement["quality_score"],
        "metadata": dict(measurement["metadata"] or {}),
    }
    return hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _measurement_projection_key_for_row(row: SourceRegistrationMeasurement) -> str:
    return _measurement_projection_key(
        {
            "measurement_type": row.measurement_type,
            "value": row.value,
            "unit": row.unit,
            "sensor_id": row.sensor_id,
            "raw_artifact_id": row.raw_artifact_id,
            "quality_score": row.quality_score,
            "metadata": dict(row.meta_data or {}),
        },
        measured_at=row.measured_at,
    )


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _coerce_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _coerce_optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_uuid(value: Any) -> Optional[uuid.UUID]:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None
