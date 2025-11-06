"""
Unified result schema for SeedCore task results.

This module defines the standard structure for storing task results in the database,
ensuring consistency between fast-path routing and HGNN escalation paths.
"""

import json
import ast
from typing import Any, Dict, List, Optional, Union, Literal
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum

# Flexible JSON value type that supports lists, dicts, and scalars
JSONValue = Union[None, bool, int, float, str, Dict[str, Any], List[Any]]


def _maybe_parse_str(value: Any) -> Any:
    """Parse stringified results, trying JSON first, then ast.literal_eval, then fallback."""
    if isinstance(value, str):
        s = value.strip()
        try:
            return json.loads(s)
        except Exception:
            try:
                return ast.literal_eval(s)
            except Exception:
                return value
    return value


class ResultKind(str, Enum):
    """Canonical routing or processing path kinds across Coordinator and Cognitive subsystems."""
    FAST_PATH = "fast"          # Direct organism execution
    COGNITIVE = "planner"       # Reasoning route on cognitive
    ESCALATED = "hgnn"          # HGNN-based multi-plan decomposition (legacy escalation path)
    ERROR = "error"             # Fallback or failure condition


class TaskStep(BaseModel):
    """Individual step in a multi-step task plan."""
    model_config = {"extra": "ignore"}
    
    organ_id: str = Field(..., description="Target organ for this step")
    success: bool = Field(..., description="Whether this step completed successfully")
    task: Optional[JSONValue] = Field(None, description="Task definition for this step")
    result: Optional[JSONValue] = Field(None, description="Result from this step execution")
    error: Optional[str] = Field(None, description="Error message if step failed")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional step metadata")
    
    @field_validator("result", "task", mode="before")
    @classmethod
    def _coerce_result(cls, v):
        return _maybe_parse_str(v)


class FastPathResult(BaseModel):
    """Result from direct routing (fast path)."""
    model_config = {"extra": "ignore"}
    
    routed_to: str = Field(..., description="Organ that processed the task")
    organ_id: str = Field(..., description="ID of the organ that handled the task")
    processing_time_ms: Optional[float] = Field(None, description="Task processing time in milliseconds")
    result: JSONValue = Field(..., description="Direct result from the organ")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional fast path metadata")
    
    @field_validator("result", mode="before")
    @classmethod
    def _coerce_result(cls, v):
        return _maybe_parse_str(v)


class EscalatedResult(BaseModel):
    """Result from HGNN escalation and decomposition."""
    model_config = {"extra": "ignore"}
    
    solution_steps: List[TaskStep] = Field(..., description="List of decomposed solution steps")
    plan_source: str = Field(default="cognitive_service", description="Source of the decomposition plan")
    estimated_complexity: Optional[str] = Field(None, description="Estimated task complexity")
    explanations: Optional[str] = Field(None, description="Explanation of the decomposition strategy")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional escalation metadata")


class CognitiveResult(BaseModel):
    """Result from cognitive reasoning tasks."""
    model_config = {"extra": "ignore"}
    
    agent_id: str = Field(..., description="ID of the cognitive agent")
    task_type: str = Field(..., description="Type of cognitive task performed")
    result: JSONValue = Field(..., description="Cognitive reasoning result")
    confidence_score: Optional[float] = Field(None, description="Confidence in the result")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional cognitive metadata")
    
    @field_validator("result", mode="before")
    @classmethod
    def _coerce_result(cls, v):
        return _maybe_parse_str(v)


class ErrorResult(BaseModel):
    """Result when a task fails."""
    error: str = Field(..., description="Error message")
    error_type: str = Field(..., description="Type of error that occurred")
    original_type: Optional[str] = Field(None, description="Original result type that caused the error")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional error metadata")


class TaskResult(BaseModel):
    """Unified envelope for all task results."""
    kind: ResultKind = Field(..., description="Type of result processing path")
    success: bool = Field(..., description="Whether the overall task succeeded")
    payload: Union[FastPathResult, EscalatedResult, CognitiveResult, ErrorResult] = Field(
        ..., description="The actual result payload"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Top-level metadata about the result"
    )
    created_at: Optional[datetime] = Field(None, description="When this result was created")
    version: Literal["1.0"] = Field(default="1.0", description="Schema version for future compatibility")
    
    @model_validator(mode="after")
    def _sync_success(self):
        """Compute success for escalated results based on step successes."""
        if self.kind == ResultKind.ESCALATED and isinstance(self.payload, EscalatedResult):
            self.success = all(step.success for step in self.payload.solution_steps)
        return self


# Convenience constructors for common result types
def create_fast_path_result(
    routed_to: str,
    organ_id: str,
    result: JSONValue,
    processing_time_ms: Optional[float] = None,
    **metadata
) -> TaskResult:
    """
    Create a fast path result for Coordinator routing.
    
    CoordinatorHttpRouter checks kind == ResultKind.FAST_PATH.value ("fast")
    and then delegates task_data to OrganismRouter for execution.
    
    The organ_id indicates the target organ where the task should be routed.
    This result is returned as a routing decision; actual execution happens downstream.
    
    Args:
        routed_to: Organ that processed the task (e.g., "random", "hotel_ops", "organism")
        organ_id: ID of the organ that handled the task (e.g., "random", "hotel_ops")
        result: Result payload (typically {"status": "routed"} for routing decisions)
        processing_time_ms: Optional processing time in milliseconds
        **metadata: Additional metadata (decision, surprise, proto_plan, etc.)
    
    Returns:
        TaskResult with kind=ResultKind.FAST_PATH suitable for router delegation
    """
    fast_path = FastPathResult(
        routed_to=routed_to,
        organ_id=organ_id,
        result=result,
        processing_time_ms=processing_time_ms,
        metadata=metadata
    )
    
    return TaskResult(
        kind=ResultKind.FAST_PATH,
        success=True,
        payload=fast_path,
        metadata={"path": "direct_routing"}
    )


def create_escalated_result(
    solution_steps: List[TaskStep],
    plan_source: str = "cognitive_service",
    estimated_complexity: Optional[str] = None,
    explanations: Optional[str] = None,
    **metadata
) -> TaskResult:
    """Create an escalated result with HGNN decomposition."""
    escalated = EscalatedResult(
        solution_steps=solution_steps,
        plan_source=plan_source,
        estimated_complexity=estimated_complexity,
        explanations=explanations,
        metadata=metadata
    )
    
    return TaskResult(
        kind=ResultKind.ESCALATED,
        success=True,
        payload=escalated,
        metadata={
            "path": "hgnn_decomposition",
            "step_count": len(solution_steps),
            "escalated": True
        }
    )


def create_cognitive_result(
    agent_id: str,
    task_type: str,
    result: JSONValue,
    confidence_score: Optional[float] = None,
    **metadata
) -> TaskResult:
    """
    Create a cognitive reasoning result for Coordinator routing.
    
    CoordinatorHttpRouter checks kind == ResultKind.COGNITIVE.value ("cognitive")
    and then delegates to CognitiveRouter with both task_data and execute_result.
    
    CognitiveRouter extracts proto_plan from:
      - prior_result["payload"]["result"]["proto_plan"] (primary)
      - prior_result["payload"]["metadata"]["proto_plan"] (fallback)
      - task_data["proto_plan"] (fallback)
    
    The result field should contain {"proto_plan": <proto_plan_dict>} to seed
    the cognitive planner with Coordinator's initial analysis.
    
    Args:
        agent_id: Agent ID for cognitive processing (e.g., "planner")
        task_type: Actual task type being processed (e.g., "ping", "general_query", "execute",
                   "fact_search", "unknown_task", etc.). Should NOT be routing metadata like
                   "planner" or "fast" - those are routing decisions, not task types.
        result: Result payload containing proto_plan and other hints
                Expected shape: {"proto_plan": {...}, ...}
        confidence_score: Optional confidence score
        **metadata: Additional metadata (decision, surprise, etc.)
    
    Returns:
        TaskResult with kind=ResultKind.COGNITIVE suitable for router escalation
    """
    cognitive = CognitiveResult(
        agent_id=agent_id,
        task_type=task_type,
        result=result,
        confidence_score=confidence_score,
        metadata=metadata
    )
    
    return TaskResult(
        kind=ResultKind.COGNITIVE,
        success=True,
        payload=cognitive,
        metadata={"path": "cognitive_reasoning"}
    )


def create_error_result(
    error: str,
    error_type: str,
    original_type: Optional[str] = None,
    **metadata
) -> TaskResult:
    """Create an error result."""
    error_result = ErrorResult(
        error=error,
        error_type=error_type,
        original_type=original_type,
        metadata=metadata
    )
    
    return TaskResult(
        kind=ResultKind.ERROR,
        success=False,
        payload=error_result,
        metadata={"path": "error_handling"}
    )


# Legacy support for existing raw_result format
def from_legacy_result(legacy_result: Dict[str, Any]) -> TaskResult:
    """Convert legacy raw_result format to new schema."""
    raw = legacy_result.get("raw_result")
    if raw is not None:
        parsed = _maybe_parse_str(raw)
        if isinstance(parsed, list):
            steps: List[TaskStep] = []
            for item in parsed:
                if isinstance(item, dict):
                    step = TaskStep(
                        organ_id=item.get("organ_id", "unknown"),
                        success=bool(item.get("success", False)),
                        task=_maybe_parse_str(item.get("task")),
                        result=_maybe_parse_str(item.get("result")),
                        error=item.get("error"),
                        metadata={k:v for k,v in item.items() if k not in {"organ_id","success","task","result","error"}}
                    )
                    steps.append(step)
            return create_escalated_result(solution_steps=steps, plan_source="legacy")
        # fallback to error if not list-like
        return create_error_result("Legacy raw_result unparseable", "legacy_format", metadata={"legacy_data": legacy_result})

    # Escalation-shaped legacy
    if "solution_steps" in legacy_result or "plan" in legacy_result:
        steps_in = legacy_result.get("solution_steps", legacy_result.get("plan", []))
        steps = []
        if isinstance(steps_in, list):
            for s in steps_in:
                if isinstance(s, dict):
                    steps.append(TaskStep(**{**s, "result": _maybe_parse_str(s.get("result"))}))
        meta = {k:v for k,v in legacy_result.items() if k not in {"solution_steps","plan","plan_source"}}
        return create_escalated_result(solution_steps=steps, plan_source=legacy_result.get("plan_source", "unknown"), **meta)

    # Default fast path
    meta = {k:v for k,v in legacy_result.items() if k not in {"routed_to","organ_id","result"}}
    return create_fast_path_result(
        routed_to=legacy_result.get("routed_to", "unknown"),
        organ_id=legacy_result.get("organ_id", "unknown"),
        result=_maybe_parse_str(legacy_result.get("result", legacy_result)),
        **meta
    )


# Database helpers for JSONB compatibility
def to_db_dict(tr: TaskResult) -> Dict[str, Any]:
    """Convert TaskResult to a JSON-serializable dict for database storage."""
    return tr.model_dump(mode="json", by_alias=True)


def from_db_dict(d: Dict[str, Any]) -> TaskResult:
    """Create TaskResult from a database dict."""
    return TaskResult.model_validate(d)
