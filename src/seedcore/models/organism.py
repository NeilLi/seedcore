"""Centralized Pydantic models for organism service contracts."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field  # type: ignore[reportMissingImports]

from .task_payload import TaskPayload


class OrganismRequest(TaskPayload):
    """Inbound request payload for organism task handling."""

    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    app_state: Optional[Dict[str, Any]] = Field(default_factory=dict)

    @property
    def task_type(self) -> str:
        """Compatibility accessor for legacy logging/messages."""
        return self.type


class OrganismResponse(BaseModel):
    success: bool
    result: Dict[str, Any]
    error: Optional[str] = None
    task_type: Optional[str] = None


class OrganismStatusResponse(BaseModel):
    status: str
    organism_initialized: bool
    organism_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ResolveRouteRequest(BaseModel):
    task: Dict[str, Any]
    preferred_logical_id: Optional[str] = None


class ResolveRouteResponse(BaseModel):
    logical_id: str
    resolved_from: str
    epoch: str
    instance_id: Optional[str] = None


class BulkResolveItem(BaseModel):
    index: Optional[int] = None  # Optional for key-based de-duplication
    key: Optional[str] = None  # For de-duplication: "type|domain"
    type: str
    domain: Optional[str] = None
    preferred_logical_id: Optional[str] = None


class BulkResolveRequest(BaseModel):
    tasks: List[BulkResolveItem]


class BulkResolveResult(BaseModel):
    index: Optional[int] = None  # Optional for key-based responses
    key: Optional[str] = None  # For de-duplication responses
    logical_id: Optional[str] = None
    resolved_from: Optional[str] = None
    epoch: Optional[str] = None
    instance_id: Optional[str] = None
    status: str = "ok"  # "ok" | "fallback" | "no_active_instance" | "unknown_type" | "error"
    error: Optional[str] = None
    cache_hit: bool = False
    cache_age_ms: Optional[float] = None


class BulkResolveResponse(BaseModel):
    epoch: str
    results: List[BulkResolveResult]


__all__ = [
    "OrganismRequest",
    "OrganismResponse",
    "OrganismStatusResponse",
    "ResolveRouteRequest",
    "ResolveRouteResponse",
    "BulkResolveItem",
    "BulkResolveRequest",
    "BulkResolveResult",
    "BulkResolveResponse",
]

