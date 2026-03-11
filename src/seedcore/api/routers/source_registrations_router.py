from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_async_pg_session
from ...models import DatabaseTask as Task, TaskStatus
from ...models.source_registration import (
    RegistrationDecision,
    SourceRegistration,
    SourceRegistrationArtifact,
    SourceRegistrationMeasurement,
    SourceRegistrationStatus,
)


router = APIRouter()


class ArtifactCreate(BaseModel):
    artifact_type: str
    uri: str
    sha256: str
    captured_at: Optional[datetime] = None
    captured_by: Optional[str] = None
    device_id: Optional[str] = None
    content_type: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MeasurementCreate(BaseModel):
    measurement_type: str
    value: float
    unit: str
    measured_at: Optional[datetime] = None
    sensor_id: Optional[str] = None
    quality_score: Optional[float] = None
    raw_artifact_id: Optional[uuid.UUID] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SourceRegistrationCreate(BaseModel):
    source_claim_id: Optional[str] = None
    lot_id: str
    producer_id: str
    rare_grade_profile_id: Optional[str] = None
    claimed_origin: Dict[str, Any] = Field(default_factory=dict)
    collection_site: Dict[str, Any] = Field(default_factory=dict)
    collected_at: Optional[datetime] = None
    snapshot_id: Optional[int] = None
    artifacts: List[ArtifactCreate] = Field(default_factory=list)
    measurements: List[MeasurementCreate] = Field(default_factory=list)


class ArtifactRead(BaseModel):
    id: uuid.UUID
    artifact_type: str
    uri: str
    sha256: str
    captured_at: Optional[datetime] = None
    captured_by: Optional[str] = None
    device_id: Optional[str] = None
    content_type: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class MeasurementRead(BaseModel):
    id: uuid.UUID
    measurement_type: str
    value: float
    unit: str
    measured_at: Optional[datetime] = None
    sensor_id: Optional[str] = None
    quality_score: Optional[float] = None
    raw_artifact_id: Optional[uuid.UUID] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class RegistrationDecisionRead(BaseModel):
    id: uuid.UUID
    registration_id: uuid.UUID
    decision: str
    grade_result: Optional[str] = None
    confidence: float
    policy_snapshot_id: Optional[int] = None
    rule_trace: Dict[str, Any] = Field(default_factory=dict)
    reason_codes: Dict[str, Any] = Field(default_factory=dict)
    decided_at: datetime
    created_by: str

    model_config = ConfigDict(from_attributes=True)


class SourceRegistrationRead(BaseModel):
    id: uuid.UUID
    source_claim_id: Optional[str] = None
    lot_id: str
    producer_id: str
    rare_grade_profile_id: Optional[str] = None
    status: str
    claimed_origin: Dict[str, Any] = Field(default_factory=dict)
    collection_site: Dict[str, Any] = Field(default_factory=dict)
    collected_at: Optional[datetime] = None
    snapshot_id: Optional[int] = None
    submitted_task_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
    artifacts: List[ArtifactRead] = Field(default_factory=list)
    measurements: List[MeasurementRead] = Field(default_factory=list)
    latest_decision: Optional[RegistrationDecisionRead] = None

    model_config = ConfigDict(from_attributes=True)


class SubmitRegistrationResponse(BaseModel):
    registration_id: uuid.UUID
    task_id: uuid.UUID
    status: str


async def _ensure_task_node_mapping(session: AsyncSession, task_id: uuid.UUID) -> None:
    await session.execute(
        text("SELECT ensure_task_node(CAST(:task_id AS uuid))"),
        {"task_id": task_id},
    )


async def _resolve_snapshot_id(
    session: AsyncSession,
    explicit_snapshot_id: Optional[int],
) -> Optional[int]:
    if explicit_snapshot_id is not None:
        return explicit_snapshot_id
    try:
        result = await session.execute(text("SELECT pkg_active_snapshot_id('prod')"))
        return result.scalar_one_or_none()
    except Exception:
        return None


async def _get_registration_or_404(
    session: AsyncSession,
    registration_id: uuid.UUID,
) -> SourceRegistration:
    registration = await session.get(SourceRegistration, registration_id)
    if registration is None:
        raise HTTPException(status_code=404, detail="SourceRegistration not found")
    return registration


async def _build_registration_read(
    session: AsyncSession,
    registration: SourceRegistration,
) -> SourceRegistrationRead:
    artifact_rows = (
        await session.execute(
            select(SourceRegistrationArtifact).where(
                SourceRegistrationArtifact.registration_id == registration.id
            )
        )
    ).scalars().all()
    measurement_rows = (
        await session.execute(
            select(SourceRegistrationMeasurement).where(
                SourceRegistrationMeasurement.registration_id == registration.id
            )
        )
    ).scalars().all()
    latest_decision = (
        await session.execute(
            select(RegistrationDecision)
            .where(RegistrationDecision.registration_id == registration.id)
            .order_by(RegistrationDecision.decided_at.desc())
            .limit(1)
        )
    ).scalars().first()

    return SourceRegistrationRead(
        id=registration.id,
        source_claim_id=registration.source_claim_id,
        lot_id=registration.lot_id,
        producer_id=registration.producer_id,
        rare_grade_profile_id=registration.rare_grade_profile_id,
        status=registration.status.value,
        claimed_origin=registration.claimed_origin or {},
        collection_site=registration.collection_site or {},
        collected_at=registration.collected_at,
        snapshot_id=registration.snapshot_id,
        submitted_task_id=registration.submitted_task_id,
        created_at=registration.created_at,
        updated_at=registration.updated_at,
        artifacts=[
            ArtifactRead(
                id=row.id,
                artifact_type=row.artifact_type,
                uri=row.uri,
                sha256=row.sha256,
                captured_at=row.captured_at,
                captured_by=row.captured_by,
                device_id=row.device_id,
                content_type=row.content_type,
                metadata=row.meta_data or {},
            )
            for row in artifact_rows
        ],
        measurements=[
            MeasurementRead(
                id=row.id,
                measurement_type=row.measurement_type,
                value=row.value,
                unit=row.unit,
                measured_at=row.measured_at,
                sensor_id=row.sensor_id,
                quality_score=row.quality_score,
                raw_artifact_id=row.raw_artifact_id,
                metadata=row.meta_data or {},
            )
            for row in measurement_rows
        ],
        latest_decision=(
            RegistrationDecisionRead(
                id=latest_decision.id,
                registration_id=latest_decision.registration_id,
                decision=latest_decision.decision.value,
                grade_result=latest_decision.grade_result,
                confidence=latest_decision.confidence,
                policy_snapshot_id=latest_decision.policy_snapshot_id,
                rule_trace=latest_decision.rule_trace or {},
                reason_codes=latest_decision.reason_codes or {},
                decided_at=latest_decision.decided_at,
                created_by=latest_decision.created_by,
            )
            if latest_decision is not None
            else None
        ),
    )


@router.post("/source-registrations", response_model=SourceRegistrationRead)
async def create_source_registration(
    payload: SourceRegistrationCreate,
    session: AsyncSession = Depends(get_async_pg_session),
) -> SourceRegistrationRead:
    registration = SourceRegistration(
        source_claim_id=payload.source_claim_id,
        lot_id=payload.lot_id,
        producer_id=payload.producer_id,
        rare_grade_profile_id=payload.rare_grade_profile_id,
        status=SourceRegistrationStatus.INGESTING,
        claimed_origin=payload.claimed_origin,
        collection_site=payload.collection_site,
        collected_at=payload.collected_at,
        snapshot_id=await _resolve_snapshot_id(session, payload.snapshot_id),
    )
    session.add(registration)
    await session.flush()

    for artifact in payload.artifacts:
        session.add(
            SourceRegistrationArtifact(
                registration_id=registration.id,
                artifact_type=artifact.artifact_type,
                uri=artifact.uri,
                sha256=artifact.sha256,
                captured_at=artifact.captured_at,
                captured_by=artifact.captured_by,
                device_id=artifact.device_id,
                content_type=artifact.content_type,
                meta_data=artifact.metadata,
            )
        )

    for measurement in payload.measurements:
        session.add(
            SourceRegistrationMeasurement(
                registration_id=registration.id,
                measurement_type=measurement.measurement_type,
                value=measurement.value,
                unit=measurement.unit,
                measured_at=measurement.measured_at,
                sensor_id=measurement.sensor_id,
                quality_score=measurement.quality_score,
                raw_artifact_id=measurement.raw_artifact_id,
                meta_data=measurement.metadata,
            )
        )

    await session.commit()
    await session.refresh(registration)
    return await _build_registration_read(session, registration)


@router.get("/source-registrations/{registration_id}", response_model=SourceRegistrationRead)
async def get_source_registration(
    registration_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_pg_session),
) -> SourceRegistrationRead:
    registration = await _get_registration_or_404(session, registration_id)
    return await _build_registration_read(session, registration)


@router.post(
    "/source-registrations/{registration_id}/artifacts",
    response_model=SourceRegistrationRead,
)
async def add_source_registration_artifact(
    registration_id: uuid.UUID,
    payload: ArtifactCreate,
    session: AsyncSession = Depends(get_async_pg_session),
) -> SourceRegistrationRead:
    registration = await _get_registration_or_404(session, registration_id)
    session.add(
        SourceRegistrationArtifact(
            registration_id=registration.id,
            artifact_type=payload.artifact_type,
            uri=payload.uri,
            sha256=payload.sha256,
            captured_at=payload.captured_at,
            captured_by=payload.captured_by,
            device_id=payload.device_id,
            content_type=payload.content_type,
            meta_data=payload.metadata,
        )
    )
    if registration.status == SourceRegistrationStatus.DRAFT:
        registration.status = SourceRegistrationStatus.INGESTING
    await session.commit()
    await session.refresh(registration)
    return await _build_registration_read(session, registration)


@router.post(
    "/source-registrations/{registration_id}/submit",
    response_model=SubmitRegistrationResponse,
)
async def submit_source_registration(
    registration_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_pg_session),
) -> SubmitRegistrationResponse:
    registration = await _get_registration_or_404(session, registration_id)
    if registration.status == SourceRegistrationStatus.APPROVED:
        raise HTTPException(status_code=409, detail="SourceRegistration already approved")

    artifacts = (
        await session.execute(
            select(SourceRegistrationArtifact).where(
                SourceRegistrationArtifact.registration_id == registration.id
            )
        )
    ).scalars().all()
    measurements = (
        await session.execute(
            select(SourceRegistrationMeasurement).where(
                SourceRegistrationMeasurement.registration_id == registration.id
            )
        )
    ).scalars().all()

    task = Task(
        type="registration",
        description=(
            f"Source registration for lot {registration.lot_id} "
            f"from producer {registration.producer_id}"
        ),
        domain="provenance",
        drift_score=0.0,
        status=TaskStatus.QUEUED,
        snapshot_id=registration.snapshot_id or await _resolve_snapshot_id(session, None),
        params={
            "source_registration": {
                "registration_id": str(registration.id),
                "source_claim_id": registration.source_claim_id,
                "lot_id": registration.lot_id,
                "producer_id": registration.producer_id,
                "rare_grade_profile_id": registration.rare_grade_profile_id,
                "claimed_origin": registration.claimed_origin or {},
                "collection_site": registration.collection_site or {},
                "collected_at": (
                    registration.collected_at.isoformat()
                    if registration.collected_at is not None
                    else None
                ),
                "artifacts": [
                    {
                        "artifact_id": str(artifact.id),
                        "artifact_type": artifact.artifact_type,
                        "uri": artifact.uri,
                        "sha256": artifact.sha256,
                        "captured_at": (
                            artifact.captured_at.isoformat()
                            if artifact.captured_at is not None
                            else None
                        ),
                        "device_id": artifact.device_id,
                        "content_type": artifact.content_type,
                        "metadata": artifact.meta_data or {},
                    }
                    for artifact in artifacts
                ],
                "measurements": {
                    measurement.measurement_type: {
                        "measurement_id": str(measurement.id),
                        "value": measurement.value,
                        "unit": measurement.unit,
                        "measured_at": (
                            measurement.measured_at.isoformat()
                            if measurement.measured_at is not None
                            else None
                        ),
                        "sensor_id": measurement.sensor_id,
                        "quality_score": measurement.quality_score,
                        "raw_artifact_id": (
                            str(measurement.raw_artifact_id)
                            if measurement.raw_artifact_id is not None
                            else None
                        ),
                        "metadata": measurement.meta_data or {},
                    }
                    for measurement in measurements
                },
            },
            "multimodal": {
                "artifacts": [
                    {
                        "artifact_type": artifact.artifact_type,
                        "uri": artifact.uri,
                        "sha256": artifact.sha256,
                        "device_id": artifact.device_id,
                    }
                    for artifact in artifacts
                ],
            },
            "governance": {
                "workflow": "source_registration",
                "require_registration_verdict": True,
            },
        },
    )
    session.add(task)
    await session.flush()
    await _ensure_task_node_mapping(session, task.id)

    registration.status = SourceRegistrationStatus.VERIFYING
    registration.submitted_task_id = task.id

    await session.commit()

    return SubmitRegistrationResponse(
        registration_id=registration.id,
        task_id=task.id,
        status=registration.status.value,
    )


@router.get(
    "/source-registrations/{registration_id}/verdict",
    response_model=RegistrationDecisionRead,
)
async def get_source_registration_verdict(
    registration_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_pg_session),
) -> RegistrationDecisionRead:
    await _get_registration_or_404(session, registration_id)
    latest_decision = (
        await session.execute(
            select(RegistrationDecision)
            .where(RegistrationDecision.registration_id == registration_id)
            .order_by(RegistrationDecision.decided_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if latest_decision is None:
        raise HTTPException(status_code=404, detail="RegistrationDecision not found")
    return RegistrationDecisionRead(
        id=latest_decision.id,
        registration_id=latest_decision.registration_id,
        decision=latest_decision.decision.value,
        grade_result=latest_decision.grade_result,
        confidence=latest_decision.confidence,
        policy_snapshot_id=latest_decision.policy_snapshot_id,
        rule_trace=latest_decision.rule_trace or {},
        reason_codes=latest_decision.reason_codes or {},
        decided_at=latest_decision.decided_at,
        created_by=latest_decision.created_by,
    )
