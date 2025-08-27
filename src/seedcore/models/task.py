"""
Task database model for SeedCore.
"""

import uuid
from sqlalchemy import String, DateTime, JSON, Float, Enum as SQLAlchemyEnum, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import enum

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

    # Columns
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=True)
    params: Mapped[dict] = mapped_column(JSON, nullable=True, default=dict)
    
    # COA-specific fields
    domain: Mapped[str] = mapped_column(String, nullable=True)
    drift_score: Mapped[float] = mapped_column(Float, default=0.0)
    
    # State and results
    status: Mapped[TaskStatus] = mapped_column(
        SQLAlchemyEnum(TaskStatus, values_callable=lambda obj: [e.value for e in obj]), 
        nullable=False, default=TaskStatus.CREATED
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_by: Mapped[str] = mapped_column(String, nullable=True)
    locked_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    run_after: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(String, nullable=True)
    
    # Timestamps
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __init__(self, **kwargs):
        """Initialize the task with default values."""
        # Set default status if not provided
        if 'status' not in kwargs:
            kwargs['status'] = TaskStatus.CREATED
        super().__init__(**kwargs)

    def to_dict(self):
        """Convert the task to a dictionary representation."""
        result = {}
        # Use SQLAlchemy's state directly to avoid lazy loading
        state = self.__dict__
        for c in self.__table__.columns:
            if c.name in state:
                value = state[c.name]
                # Handle special cases like enums
                if hasattr(value, 'value'):
                    result[c.name] = value.value
                else:
                    result[c.name] = value
            else:
                # For unloaded attributes, set to None to avoid lazy loading
                result[c.name] = None
        return result
