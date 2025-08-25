"""
Fact database model for SeedCore.
"""

import uuid
from sqlalchemy import String, DateTime, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
from typing import List, Dict, Any

class Base(DeclarativeBase):
    pass

class Fact(Base):
    __tablename__ = "facts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    text: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[List[str]] = mapped_column(ARRAY(String), nullable=True, default=list)
    meta_data: Mapped[dict] = mapped_column(JSON, nullable=True, default=dict)
    
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def to_dict(self):
        """Convert the fact to a dictionary representation."""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}
