from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .task import Base


class CustodyGraphNode(Base):
    __tablename__ = "custody_graph_node"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    node_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_custody_graph_node_kind", "node_kind"),
        Index("ix_custody_graph_node_subject_id", "subject_id"),
    )


class CustodyGraphEdge(Base):
    __tablename__ = "custody_graph_edge"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    edge_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    edge_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    from_node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    to_node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_custody_graph_edge_kind", "edge_kind"),
        Index("ix_custody_graph_edge_from_node_id", "from_node_id"),
        Index("ix_custody_graph_edge_to_node_id", "to_node_id"),
        Index("ix_custody_graph_edge_recorded_at", "recorded_at"),
    )


class CustodyTransitionEvent(Base):
    __tablename__ = "custody_transition_event"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transition_event_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    asset_id: Mapped[str] = mapped_column(String(128), nullable=False)
    intent_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    token_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    authority_source: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    transition_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    from_zone: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    to_zone: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    actor_agent_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    actor_organ_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    endpoint_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    receipt_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    receipt_nonce: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    receipt_counter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    previous_transition_event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    previous_receipt_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    evidence_bundle_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    policy_receipt_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    transition_receipt_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    lineage_status: Mapped[str] = mapped_column(String(64), nullable=False, default="authoritative")
    source_registration_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    audit_record_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    details: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_custody_transition_event_asset_id", "asset_id"),
        Index("ix_custody_transition_event_intent_id", "intent_id"),
        Index("ix_custody_transition_event_task_id", "task_id"),
        Index("ix_custody_transition_event_token_id", "token_id"),
        Index("ix_custody_transition_event_transition_seq", "asset_id", "transition_seq"),
        Index("ix_custody_transition_event_recorded_at", "recorded_at"),
    )


class CustodyDisputeCase(Base):
    __tablename__ = "custody_dispute_case"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dispute_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="OPEN")
    asset_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    opened_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reference_map: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    details: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_custody_dispute_case_asset_id", "asset_id"),
        Index("ix_custody_dispute_case_status", "status"),
        Index("ix_custody_dispute_case_recorded_at", "recorded_at"),
    )


class CustodyDisputeEvent(Base):
    __tablename__ = "custody_dispute_event"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dispute_case_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("custody_dispute_case.id", ondelete="CASCADE"),
        nullable=False,
    )
    dispute_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_custody_dispute_event_dispute_id", "dispute_id"),
        Index("ix_custody_dispute_event_recorded_at", "recorded_at"),
        UniqueConstraint("dispute_id", "event_type", "recorded_at", name="uq_custody_dispute_event_signature"),
    )
