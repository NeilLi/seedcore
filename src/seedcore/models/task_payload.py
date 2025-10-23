"""
TaskPayload model for SeedCore.

This module defines the TaskPayload model used for task routing and processing
across the coordinator and dispatcher services.
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, field_validator


class TaskPayload(BaseModel):
    """Task payload model for coordinator and dispatcher services."""
    
    type: str
    params: Dict[str, Any] = {}
    description: str = ""
    domain: Optional[str] = None
    drift_score: float = 0.0
    task_id: str

    @field_validator("params", mode="before")
    @classmethod
    def parse_params(cls, v):
        """Parse params from JSON string if needed."""
        if isinstance(v, str):
            try:
                import json
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return {}
        return v or {}

    @field_validator("domain", mode="before")
    @classmethod
    def parse_domain(cls, v):
        """Convert None domain to empty string."""
        return v or ""
