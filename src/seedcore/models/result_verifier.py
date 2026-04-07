"""Persistence models for Coordinator RESULT_VERIFIER job queue and outcomes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .task import Base


class ResultVerifierJob(Base):
    __tablename__ = "result_verifier_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    event_journal_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("digital_twin_event_journal.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    intent_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    asset_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_error_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_result_verifier_jobs_status_next_attempt", "status", "next_attempt_at"),
        Index("ix_result_verifier_jobs_task_id", "task_id"),
    )


class ResultVerifierOutcomeRecord(Base):
    """Immutable persisted row for a terminal verification decision."""

    __tablename__ = "result_verifier_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("result_verifier_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_journal_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verified: Mapped[bool] = mapped_column(nullable=False)
    failure_code: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    failure_class: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    twin_event_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    asset_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    evidence_refs: Mapped[List[Any]] = mapped_column(JSONB, nullable=False, default=list)
    artifact_results: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    issues: Mapped[List[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_result_verifier_outcomes_job_id", "job_id"),
        Index("ix_result_verifier_outcomes_event_journal_id", "event_journal_id"),
    )


class ResultVerifierRuntimeState(Base):
    """Durable high-watermark state for RESULT_VERIFIER event-stream intake."""

    __tablename__ = "result_verifier_runtime_state"

    stream_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    watermark_recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    watermark_event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
