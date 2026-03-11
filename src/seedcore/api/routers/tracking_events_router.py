from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_async_pg_session
from ...models.source_registration import (
    SourceRegistration,
    TrackingEvent,
    TrackingEventSourceKind,
    TrackingEventType,
)
from ...ops.source_registration.projector import record_tracking_event


router = APIRouter()


class TrackingEventCreate(BaseModel):
    registration_id: uuid.UUID
    event_type: TrackingEventType
    source_kind: TrackingEventSourceKind
    payload: Dict[str, Any] = Field(default_factory=dict)
    captured_at: Optional[datetime] = None
    producer_id: Optional[str] = None
    device_id: Optional[str] = None
    operator_id: Optional[str] = None
    correlation_id: Optional[str] = None
    snapshot_id: Optional[int] = None
    sha256: Optional[str] = None


class TrackingEventRead(BaseModel):
    id: uuid.UUID
    registration_id: uuid.UUID
    event_type: str
    source_kind: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    sha256: str
    captured_at: datetime
    producer_id: Optional[str] = None
    device_id: Optional[str] = None
    operator_id: Optional[str] = None
    correlation_id: Optional[str] = None
    snapshot_id: Optional[int] = None
    projected_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


def _to_read(event: TrackingEvent) -> TrackingEventRead:
    return TrackingEventRead(
        id=event.id,
        registration_id=event.registration_id,
        event_type=event.event_type.value,
        source_kind=event.source_kind.value,
        payload=event.payload or {},
        sha256=event.sha256,
        captured_at=event.captured_at,
        producer_id=event.producer_id,
        device_id=event.device_id,
        operator_id=event.operator_id,
        correlation_id=event.correlation_id,
        snapshot_id=event.snapshot_id,
        projected_at=event.projected_at,
        created_at=event.created_at,
    )


@router.post("/tracking-events", response_model=TrackingEventRead)
async def create_tracking_event(
    payload: TrackingEventCreate,
    session: AsyncSession = Depends(get_async_pg_session),
) -> TrackingEventRead:
    registration = await session.get(SourceRegistration, payload.registration_id)
    if registration is None:
        raise HTTPException(status_code=404, detail="SourceRegistration not found")

    event = await record_tracking_event(
        session,
        registration=registration,
        event_type=payload.event_type,
        source_kind=payload.source_kind,
        payload=payload.payload,
        captured_at=payload.captured_at,
        producer_id=payload.producer_id,
        device_id=payload.device_id,
        operator_id=payload.operator_id,
        correlation_id=payload.correlation_id,
        snapshot_id=payload.snapshot_id,
        sha256=payload.sha256,
    )
    await session.commit()
    await session.refresh(event)
    return _to_read(event)


@router.get("/tracking-events", response_model=List[TrackingEventRead])
async def list_tracking_events(
    registration_id: Optional[uuid.UUID] = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_async_pg_session),
) -> List[TrackingEventRead]:
    stmt = select(TrackingEvent).order_by(TrackingEvent.captured_at.desc()).limit(limit).offset(offset)
    if registration_id is not None:
        stmt = stmt.where(TrackingEvent.registration_id == registration_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [_to_read(row) for row in rows]


@router.get("/tracking-events/{event_id}", response_model=TrackingEventRead)
async def get_tracking_event(
    event_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_pg_session),
) -> TrackingEventRead:
    event = await session.get(TrackingEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="TrackingEvent not found")
    return _to_read(event)


@router.get(
    "/source-registrations/{registration_id}/tracking-events",
    response_model=List[TrackingEventRead],
)
async def list_registration_tracking_events(
    registration_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_async_pg_session),
) -> List[TrackingEventRead]:
    registration = await session.get(SourceRegistration, registration_id)
    if registration is None:
        raise HTTPException(status_code=404, detail="SourceRegistration not found")
    rows = (
        await session.execute(
            select(TrackingEvent)
            .where(TrackingEvent.registration_id == registration_id)
            .order_by(TrackingEvent.captured_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return [_to_read(row) for row in rows]
