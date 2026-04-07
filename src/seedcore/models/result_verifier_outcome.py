"""Normalized RESULT_VERIFIER decision contract (in-memory / API-adjacent)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ResultVerifierOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: bool
    failure_code: Optional[str] = None
    failure_class: Optional[Literal["integrity", "trust", "none"]] = Field(
        default=None,
        description="integrity -> verification_failed twin event; trust -> verification_quarantined",
    )
    twin_event_type: Optional[str] = None
    asset_id: Optional[str] = None
    evidence_refs: List[str] = Field(default_factory=list)
    artifact_results: Dict[str, Any] = Field(default_factory=dict)
    issues: List[str] = Field(default_factory=list)
