from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field  # pyright: ignore[reportMissingImports]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AmbiguityAssessment(BaseModel):
    score: float = Field(0.0, ge=0.0, le=1.0)
    needs_clarification: bool = False
    signals: List[str] = Field(default_factory=list)


class ProposedRouting(BaseModel):
    required_specialization: Optional[str] = None
    specialization: Optional[str] = None
    skills: Dict[str, float] = Field(default_factory=dict)
    tools: List[str] = Field(default_factory=list)
    source: str = "task_payload"


class AdvisoryPlan(BaseModel):
    kind: Literal["advisory_plan"] = "advisory_plan"
    advisory_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    generated_at: str = Field(default_factory=utc_now_iso)
    baseline: str = "cognitive_core_baseline"
    stateless: bool = True
    summary: str
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    ambiguity: AmbiguityAssessment
    structured_interpretation: Dict[str, Any] = Field(default_factory=dict)
    proposed_routing: ProposedRouting
    proto_plan: Dict[str, Any] = Field(default_factory=dict)
    next_action: str = "agent_formulate_action_intent"


class RiskSummary(BaseModel):
    kind: Literal["risk_summary"] = "risk_summary"
    advisory_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    generated_at: str = Field(default_factory=utc_now_iso)
    baseline: str = "cognitive_core_baseline"
    stateless: bool = True
    risk_score: float = Field(0.0, ge=0.0, le=1.0)
    risk_level: Literal["low", "medium", "high", "critical"] = "low"
    triggers: List[str] = Field(default_factory=list)
    recommended_action: Literal[
        "allow_with_policy",
        "step_up_approval",
        "quarantine",
    ] = "allow_with_policy"
    ambiguity: AmbiguityAssessment
    structured_interpretation: Dict[str, Any] = Field(default_factory=dict)


class PolicyCaseAssessment(BaseModel):
    kind: Literal["policy_case_assessment"] = "policy_case_assessment"
    advisory_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    generated_at: str = Field(default_factory=utc_now_iso)
    baseline: str = "cognitive_core_policy"
    stateless: bool = True
    recommended_disposition: Literal["allow", "deny", "escalate"] = "escalate"
    risk_score: float = Field(0.0, ge=0.0, le=1.0)
    risk_factors: List[str] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list)
    policy_conflicts: List[str] = Field(default_factory=list)
    required_approvals: List[str] = Field(default_factory=list)
    explanation: str = ""
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    ambiguity: AmbiguityAssessment = Field(default_factory=AmbiguityAssessment)
    structured_interpretation: Dict[str, Any] = Field(default_factory=dict)
    next_action: str = "policy_evaluate_case"


AdvisoryPayload = Union[AdvisoryPlan, RiskSummary, PolicyCaseAssessment]


class AdvisoryContractResponse(BaseModel):
    success: bool
    advisory: Optional[AdvisoryPayload] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
