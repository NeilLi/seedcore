from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .task import Base


class GovernedExecutionAudit(Base):
    """Append-only audit trail for governed execution decisions and receipts."""

    __tablename__ = "governed_execution_audit"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Append-only record stage, e.g. policy_decision or execution_receipt.",
    )
    intent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    token_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    policy_snapshot: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    policy_decision: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    action_intent: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    policy_case: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    policy_receipt: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    evidence_bundle: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    actor_agent_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    actor_organ_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    input_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    evidence_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_governed_execution_audit_task_id", "task_id"),
        Index("ix_governed_execution_audit_intent_id", "intent_id"),
        Index("ix_governed_execution_audit_token_id", "token_id"),
        Index("ix_governed_execution_audit_record_type", "record_type"),
        Index("ix_governed_execution_audit_recorded_at_desc", "recorded_at"),
    )
