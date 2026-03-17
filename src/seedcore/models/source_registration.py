from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Enum as SQLAlchemyEnum

from .task import Base


class SourceRegistrationStatus(str, enum.Enum):
    DRAFT = "draft"
    INGESTING = "ingesting"
    VERIFYING = "verifying"
    APPROVED = "approved"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


class RegistrationDecisionStatus(str, enum.Enum):
    APPROVED = "approved"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


class TrackingEventType(str, enum.Enum):
    SOURCE_CLAIM_DECLARED = "source_claim_declared"
    PROVENANCE_SCAN_CAPTURED = "provenance_scan_captured"
    SEAL_CHECK_CAPTURED = "seal_check_captured"
    ENVIRONMENTAL_READING_RECORDED = "environmental_reading_recorded"
    BIO_SIGNATURE_RECORDED = "bio_signature_recorded"
    OPERATOR_REQUEST_RECEIVED = "operator_request_received"
    RUNTIME_INCIDENT_DETECTED = "runtime_incident_detected"
    POLICY_IMPLEMENTATION_REPORTED = "policy_implementation_reported"
    POLICY_DECISION_RECORDED = "policy_decision_recorded"


class TrackingEventSourceKind(str, enum.Enum):
    SOURCE_DECLARATION = "source_declaration"
    PROVENANCE_SCAN = "provenance_scan"
    TELEMETRY = "telemetry"
    OPERATOR_REQUEST = "operator_request"
    SYSTEM = "system"
    APPLICATION_LOG = "application_log"
    POLICY_MONITOR = "policy_monitor"


class SourceRegistration(Base):
    __tablename__ = "source_registrations"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    source_claim_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    lot_id: Mapped[str] = mapped_column(String(128), nullable=False)
    producer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    rare_grade_profile_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[SourceRegistrationStatus] = mapped_column(
        SQLAlchemyEnum(
            SourceRegistrationStatus,
            values_callable=lambda e: [m.value for m in e],
            native_enum=False,
            name="source_registration_status_enum",
        ),
        nullable=False,
        default=SourceRegistrationStatus.DRAFT,
    )
    claimed_origin: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    collection_site: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    collected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    snapshot_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    submitted_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_source_registrations_status", "status"),
        Index("ix_source_registrations_lot_id", "lot_id"),
        Index("ix_source_registrations_snapshot_id", "snapshot_id"),
    )


class TrackingEvent(Base):
    __tablename__ = "tracking_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    registration_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("source_registrations.id", ondelete="CASCADE"),
        nullable=True,
    )
    event_type: Mapped[TrackingEventType] = mapped_column(
        SQLAlchemyEnum(
            TrackingEventType,
            values_callable=lambda e: [m.value for m in e],
            native_enum=False,
            name="tracking_event_type_enum",
        ),
        nullable=False,
    )
    source_kind: Mapped[TrackingEventSourceKind] = mapped_column(
        SQLAlchemyEnum(
            TrackingEventSourceKind,
            values_callable=lambda e: [m.value for m in e],
            native_enum=False,
            name="tracking_event_source_kind_enum",
        ),
        nullable=False,
    )
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    sha256: Mapped[str] = mapped_column(String(128), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    producer_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    device_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    operator_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    subject_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    snapshot_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    projected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_tracking_events_registration_id", "registration_id"),
        Index("ix_tracking_events_event_type", "event_type"),
        Index("ix_tracking_events_captured_at", "captured_at"),
        Index("ix_tracking_events_registration_captured_at", "registration_id", "captured_at"),
        Index("ix_tracking_events_subject", "subject_type", "subject_id"),
    )


class SourceRegistrationArtifact(Base):
    __tablename__ = "source_registration_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    registration_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("source_registrations.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tracking_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(128), nullable=False)
    captured_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    captured_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    device_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    meta_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_source_registration_artifacts_registration_id", "registration_id"),
        Index("ix_source_registration_artifacts_source_event_id", "source_event_id"),
        Index("ix_source_registration_artifacts_sha256", "sha256"),
        Index(
            "ux_source_registration_artifacts_registration_sha256",
            "registration_id",
            "sha256",
            unique=True,
        ),
    )


class SourceRegistrationMeasurement(Base):
    __tablename__ = "source_registration_measurements"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    registration_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("source_registrations.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tracking_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    measurement_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    measured_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sensor_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_artifact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("source_registration_artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    meta_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_source_registration_measurements_registration_id", "registration_id"),
        Index("ix_source_registration_measurements_source_event_id", "source_event_id"),
        Index("ix_source_registration_measurements_type", "measurement_type"),
    )


class RegistrationDecision(Base):
    __tablename__ = "registration_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    registration_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("source_registrations.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision: Mapped[RegistrationDecisionStatus] = mapped_column(
        SQLAlchemyEnum(
            RegistrationDecisionStatus,
            values_callable=lambda e: [m.value for m in e],
            native_enum=False,
            name="registration_decision_status_enum",
        ),
        nullable=False,
    )
    grade_result: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    policy_snapshot_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rule_trace: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    reason_codes: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="coordinator")

    __table_args__ = (
        Index("ix_registration_decisions_registration_id", "registration_id"),
        Index("ix_registration_decisions_decision", "decision"),
        Index("ix_registration_decisions_policy_snapshot_id", "policy_snapshot_id"),
    )
