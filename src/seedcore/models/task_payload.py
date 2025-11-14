# seedcore/models/task_payload.py

from __future__ import annotations
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field, field_validator

# ------------ Helper payloads (router inbox) ------------
class ToolCallPayload(BaseModel):
    name: str
    args: Dict[str, Any] = Field(default_factory=dict)

class RouterHints(BaseModel):
    min_capability: Optional[float] = None
    max_mem_util: Optional[float] = None
    priority: int = 0
    deadline_at: Optional[str] = None  # ISO8601
    ttl_seconds: Optional[int] = None

class RouterInbox(BaseModel):
    required_specialization: Optional[str] = None
    desired_skills: Dict[str, float] = Field(default_factory=dict)
    tool_calls: List[ToolCallPayload] = Field(default_factory=list)
    hints: RouterHints = Field(default_factory=RouterHints)
    v: int = 1  # payload schema versioning for the routing envelope

# ------------ Main TaskPayload ------------
class TaskPayload(BaseModel):
    """
    In-memory payload used by dispatcher & routers.
    - DB stays the same: we persist everything inside params (JSONB).
    - Router-facing “inbox” is stored in params.routing.
    """

    # Core (existing)
    type: str
    params: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    domain: Optional[str] = None
    drift_score: float = 0.0
    task_id: str

    # Router inbox (convenience mirrors; will be packed into params.routing)
    required_specialization: Optional[str] = None
    desired_skills: Dict[str, float] = Field(default_factory=dict)
    tool_calls: List[ToolCallPayload] = Field(default_factory=list)
    min_capability: Optional[float] = None
    max_mem_util: Optional[float] = None
    priority: int = 0
    deadline_at: Optional[str] = None
    ttl_seconds: Optional[int] = None

    # ------------ validators / normalizers ------------

    @field_validator("params", mode="before")
    @classmethod
    def parse_params(cls, v):
        if isinstance(v, str):
            try:
                import json
                return json.loads(v)
            except Exception:
                return {}
        return v or {}

    @field_validator("domain", mode="before")
    @classmethod
    def parse_domain(cls, v):
        return v or ""

    # ------------ packing/unpacking helpers ------------

    def to_db_params(self) -> Dict[str, Any]:
        """Return params with routing envelope injected under params['routing']."""
        p = dict(self.params or {})
        routing = p.get("routing", {})

        # Merge: top-level convenience -> routing envelope
        merged = {
            "required_specialization": self.required_specialization,
            "desired_skills": self.desired_skills or {},
            "tool_calls": [tc.model_dump() if isinstance(tc, ToolCallPayload) else tc for tc in self.tool_calls],
            "hints": {
                "min_capability": self.min_capability,
                "max_mem_util": self.max_mem_util,
                "priority": self.priority,
                "deadline_at": self.deadline_at,
                "ttl_seconds": self.ttl_seconds,
            },
            "v": 1,
        }

        # Keep any pre-existing keys (but top-level mirrors override)
        routing = {**routing, **{k: v for k, v in merged.items() if v is not None}}
        p["routing"] = routing
        return p

    def model_dump(self, *args, **kwargs) -> Dict[str, Any]:  # type: ignore[override]
        """
        Ensure serialized payload always contains params.routing
        so routers and services have a stable contract.
        """
        as_dict = super().model_dump(*args, **kwargs)
        as_dict["params"] = self.to_db_params()
        return as_dict

    @classmethod
    def from_db(cls, row: Dict[str, Any]) -> "TaskPayload":
        """
        Construct from a DB task row or an existing dict. Safely extracts params.routing.
        """
        params = row.get("params") or {}
        routing = params.get("routing") or {}

        hints = routing.get("hints") or {}
        tool_calls_raw = routing.get("tool_calls") or []

        tool_calls = [
            (tc if isinstance(tc, ToolCallPayload) else ToolCallPayload(**tc))
            for tc in tool_calls_raw
            if isinstance(tc, dict) or isinstance(tc, ToolCallPayload)
        ]

        return cls(
            type=row.get("type") or row.get("task_type") or "unknown_task",
            params=params,
            description=row.get("description") or "",
            domain=row.get("domain"),
            drift_score=float(row.get("drift_score") or 0.0),
            task_id=str(row.get("id") or row.get("task_id")),

            required_specialization=routing.get("required_specialization"),
            desired_skills=routing.get("desired_skills") or {},
            tool_calls=tool_calls,
            min_capability=hints.get("min_capability"),
            max_mem_util=hints.get("max_mem_util"),
            priority=int(hints.get("priority") or 0),
            deadline_at=hints.get("deadline_at"),
            ttl_seconds=hints.get("ttl_seconds"),
        )
