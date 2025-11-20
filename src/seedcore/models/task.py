from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (  # pyright: ignore[reportMissingImports]
    String,
    Text,
    DateTime,
    Float,
    Integer,
    CheckConstraint,
    Index,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column  # pyright: ignore[reportMissingImports]
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB  # pyright: ignore[reportMissingImports]
from sqlalchemy.types import Enum as SQLAlchemyEnum  # pyright: ignore[reportMissingImports]

class Base(DeclarativeBase):
    """Declarative base for ORM models."""

    pass

class TaskStatus(enum.Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY = "retry"

class TaskType(str, enum.Enum):
    """Canonical task types for routing and dispatch.

    These types are what the RoutingDirectory / dispatchers
    (GraphDispatcher, QueueDispatcher, etc.) should switch on.
    """

    # ==========================================================
    # Graph / KG tasks (handled by GraphDispatcher)
    # ==========================================================
    GRAPH_EMBED = "graph_embed"
    # Embed graph nodes/entities (concepts, devices, users) into a vector space.

    GRAPH_RAG_QUERY = "graph_rag_query"
    # Hybrid RAG over graph + vector stores (structural hops + dense retrieval).

    GRAPH_FACT_EMBED = "graph_fact_embed"
    # Embed atomic facts/edges (triples, propositions) into vector space.

    GRAPH_FACT_QUERY = "graph_fact_query"
    # Logical / fact-level graph query (e.g., constraints over facts/edges).

    NIM_TASK_EMBED = "nim_task_embed"
    # Embed tasks into NIM / task-space embedding for meta-control / routing.

    GRAPH_SYNC_NODES = "graph_sync_nodes"
    # Sync external state (devices, rooms, users, configs) into graph nodes.

    # ==========================================================
    # General / queue-based tasks (handled by QueueDispatcher)
    # ==========================================================
    PING = "ping"
    # Very cheap liveness / connectivity probe (no heavy work).

    HEALTH_CHECK = "health_check"
    # Deeper component / system health check (may touch multiple subsystems).

    GENERAL_QUERY = "general_query"
    # Primary "ask the system a question" pathway (LLM + tools + memory).

    CHAT = "chat"
    # Lightweight conversational path for agent-tunneled interactions.
    # Uses CognitiveType.CHAT for fast, low-latency conversational responses.

    TEST_QUERY = "test_query"
    # Synthetic / integration / load-test query (non-user-facing).

    FACT_SEARCH = "fact_search"
    # Non-graph factual lookup (e.g., local store, config, or KV memory).

    EXECUTE = "execute"
    # Execute an action/plan/tool/agent step (downstream may route to actuator).

    UNKNOWN_TASK = "unknown_task"
    # Fallback when we cannot classify the task; should be rare in practice.

class Task(Base):
    """Unified task schema with routing and execution metadata stored in JSONB."""

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
        comment=(
            "Input parameters including fast_eventizer outputs "
            "and Router inbox fields under params.routing"
        ),
    )
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Unified TaskResult schema (JSONB, includes result.meta.*)",
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
            native_enum=False,
            name="taskstatus_enum",
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
        Index("ix_tasks_status_runafter", "status", "run_after"),
        Index("ix_tasks_created_at_desc", "created_at"),
        Index("ix_tasks_type", "type"),
        Index("ix_tasks_domain", "domain"),
        Index("ix_tasks_params_gin", "params", postgresql_using="gin"),
        # Optional JSONB path indexes defined in migration 007_task_schema_enhancements.sql:
        #   ix_tasks_params_routing_spec
        #   ix_tasks_params_routing_priority
        #   ix_tasks_params_routing_deadline
    )

    # --- Helpers ---

    def short_id(self, length: int = 8) -> str:
        """Human-friendly short ID used in logs and UI."""
        return str(self.id).split("-")[0][:length]

    def queue(self, after: Optional[datetime] = None) -> None:
        """Mark task ready to run (optionally delayed)."""
        self.status = TaskStatus.QUEUED
        self.run_after = after

    def mark_running(self, worker_id: Optional[str] = None) -> None:
        """Transition task to RUNNING state."""
        self.status = TaskStatus.RUNNING
        self.locked_by = worker_id
        self.locked_at = func.now()

    def mark_completed(self, result: Dict[str, Any]) -> None:
        """Mark task as successfully completed."""
        self.status = TaskStatus.COMPLETED
        self.result = result
        self.error = None

    def mark_failed(self, error: str, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark task as failed."""
        self.status = TaskStatus.FAILED
        self.error = error
        if result is not None:
            self.result = result

    def mark_cancelled(self) -> None:
        """Mark task as cancelled."""
        self.status = TaskStatus.CANCELLED

    def bump_attempts(self) -> None:
        """Increment attempt counter safely."""
        self.attempts = (self.attempts or 0) + 1

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict, flattening enums."""
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
