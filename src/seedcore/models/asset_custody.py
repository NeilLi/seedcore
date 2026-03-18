from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .task import Base


class AssetCustodyState(Base):
    """Authoritative mutable custody/location state for governed assets."""

    __tablename__ = "asset_custody_state"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    asset_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    source_registration_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    lot_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_claim_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    producer_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    current_zone: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_quarantined: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    authority_source: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    last_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_intent_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_token_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
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
        Index("ix_asset_custody_state_asset_id", "asset_id"),
        Index("ix_asset_custody_state_source_registration_id", "source_registration_id"),
        Index("ix_asset_custody_state_lot_id", "lot_id"),
        Index("ix_asset_custody_state_updated_at", "updated_at"),
    )
