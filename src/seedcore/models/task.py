from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    String,
    Text,
    DateTime,
    Float,
    Integer,
    CheckConstraint,
    Index,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.types import Enum as SQLAlchemyEnum


class Base(DeclarativeBase):
    pass


class TaskStatus(enum.Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY = "retry"


class Task(Base):
    __tablename__ = "tasks"

    # --- Identifiers ---
    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Task UUID (v4)",
    )

    # --- Classification ---
    type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Task type (short code, indexed)",
    )
    domain: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="Logical domain/namespace for routing/policy",
    )

    # --- Human context ---
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Optional human-readable description/input text",
    )

    # --- Inputs / outputs ---
    params: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Input parameters including fast_eventizer outputs (JSONB)",
    )
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Unified TaskResult schema (JSONB)",
    )
    error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Error message/details on failure",
    )

    # --- State & scheduling ---
    status: Mapped[TaskStatus] = mapped_column(
        SQLAlchemyEnum(
            TaskStatus,
            values_callable=lambda e: [m.value for m in e],
            native_enum=False,             # stores strings; safer for migrations
            name="taskstatus_enum",        # explicit name for Alembic diffs
        ),
        nullable=False,
        default=TaskStatus.CREATED,
        comment="Lifecycle status",
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of execution attempts",
    )
    locked_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="Lock owner (worker id) if any",
    )
    locked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the lock was taken",
    )
    run_after: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Earliest time this task may be scheduled",
    )
    drift_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="Model/policy drift indicator (0..1)",
    )

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Creation time (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Last update time (UTC)",
    )

    # --- Table-level constraints & indexes ---
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_tasks_attempts_nonneg"),
        # Scheduling hot-path: pick runnable tasks quickly
        Index("ix_tasks_status_runafter", "status", "run_after"),
        Index("ix_tasks_created_at_desc", "created_at"),
        Index("ix_tasks_type", "type"),
        Index("ix_tasks_domain", "domain"),
        # JSONB GIN index: enable filtering into params (e.g., confidence, tags)
        Index("ix_tasks_params_gin", "params", postgresql_using="gin"),
        # Optional: also index result if you query it often
        # Index("ix_tasks_result_gin", "result", postgresql_using="gin"),
    )

    # --- Helpers ---

    def short_id(self, length: int = 8) -> str:
        """Human-friendly short ID used in UIs/CLI."""
        return str(self.id).split("-")[0][:length]

    def queue(self, after: Optional[datetime] = None) -> None:
        """Mark task ready to run (optionally delayed)."""
        self.status = TaskStatus.QUEUED
        self.run_after = after

    def mark_running(self, worker_id: Optional[str] = None) -> None:
        self.status = TaskStatus.RUNNING
        self.locked_by = worker_id
        self.locked_at = func.now()  # server-side timestamp

    def mark_completed(self, result: Dict[str, Any]) -> None:
        self.status = TaskStatus.COMPLETED
        self.result = result
        self.error = None

    def mark_failed(self, error: str, result: Optional[Dict[str, Any]] = None) -> None:
        self.status = TaskStatus.FAILED
        self.error = error
        if result is not None:
            self.result = result

    def mark_cancelled(self) -> None:
        self.status = TaskStatus.CANCELLED

    def bump_attempts(self) -> None:
        self.attempts = (self.attempts or 0) + 1

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a dict with enum values flattened."""
        out: Dict[str, Any] = {}
        state = self.__dict__
        for col in self.__table__.columns:
            val = state.get(col.name)
            if isinstance(val, enum.Enum):
                out[col.name] = val.value
            else:
                out[col.name] = val
        return out

    def __repr__(self) -> str:
        return (
            f"<Task id={self.short_id()} type={self.type!r} "
            f"status={self.status.value} created_at={self.created_at}>"
        )
