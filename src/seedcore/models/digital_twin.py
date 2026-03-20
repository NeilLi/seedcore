from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .task import Base


class DigitalTwinState(Base):
    """Authoritative current-state projection for each governed digital twin."""

    __tablename__ = "digital_twin_state"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    twin_type: Mapped[str] = mapped_column(String(64), nullable=False)
    twin_id: Mapped[str] = mapped_column(String(128), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    authority_source: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    snapshot: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    last_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_intent_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
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
        UniqueConstraint("twin_type", "twin_id", name="uq_digital_twin_state_type_id"),
        Index("ix_digital_twin_state_twin_type", "twin_type"),
        Index("ix_digital_twin_state_twin_id", "twin_id"),
        Index("ix_digital_twin_state_updated_at", "updated_at"),
    )


class DigitalTwinHistory(Base):
    """Append-only version history for authoritative digital twin snapshots."""

    __tablename__ = "digital_twin_history"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    twin_state_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("digital_twin_state.id", ondelete="CASCADE"),
        nullable=False,
    )
    twin_type: Mapped[str] = mapped_column(String(64), nullable=False)
    twin_id: Mapped[str] = mapped_column(String(128), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    authority_source: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    change_reason: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_intent_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("twin_state_id", "state_version", name="uq_digital_twin_history_state_version"),
        Index("ix_digital_twin_history_twin_type_id", "twin_type", "twin_id"),
        Index("ix_digital_twin_history_recorded_at", "recorded_at"),
    )


class DigitalTwinEventJournal(Base):
    """Append-only normalized twin event stream for replay and state promotion."""

    __tablename__ = "digital_twin_event_journal"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    twin_type: Mapped[str] = mapped_column(String(64), nullable=False)
    twin_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    lifecycle_state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    intent_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_digital_twin_event_journal_twin_type_id", "twin_type", "twin_id"),
        Index("ix_digital_twin_event_journal_event_type", "event_type"),
        Index("ix_digital_twin_event_journal_recorded_at", "recorded_at"),
    )
