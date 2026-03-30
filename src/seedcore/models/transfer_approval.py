from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .task import Base


class TransferApprovalEnvelopeRecord(Base):
    __tablename__ = "transfer_approval_envelopes"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    approval_envelope_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    workflow_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    lot_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    policy_snapshot_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    approval_binding_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    envelope_payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_transfer_approval_envelopes_envelope_id", "approval_envelope_id"),
        Index(
            "ux_transfer_approval_envelopes_envelope_version",
            "approval_envelope_id",
            "version",
            unique=True,
        ),
        Index(
            "ux_transfer_approval_envelopes_current",
            "approval_envelope_id",
            unique=True,
            postgresql_where=(is_current.is_(True)),
        ),
        Index("ix_transfer_approval_envelopes_asset_ref", "asset_ref"),
        Index("ix_transfer_approval_envelopes_status", "status"),
    )


class TransferApprovalTransitionEventRecord(Base):
    __tablename__ = "transfer_approval_transition_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    approval_envelope_id: Mapped[str] = mapped_column(String(128), nullable=False)
    envelope_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(256), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    previous_event_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    previous_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    next_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    actor_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    transition_payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    transition_event: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_transfer_approval_transition_events_envelope_id", "approval_envelope_id"),
        Index(
            "ux_transfer_approval_transition_events_event_id",
            "event_id",
            unique=True,
        ),
        Index("ix_transfer_approval_transition_events_event_hash", "event_hash"),
    )
