"""
Pydantic Task model for SeedCore API operations.

This module defines the Pydantic Task model used for API operations,
separate from the SQLAlchemy database model.
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import uuid


class Task(BaseModel):
    """Pydantic Task model for API operations."""
    
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: str
    description: Optional[str] = ""
    params: Dict[str, Any] = {}
    domain: Optional[str] = None
    features: Dict[str, Any] = {}
    history_ids: List[str] = []
