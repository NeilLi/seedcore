"""
Unified result schema for SeedCore task results.

This module defines the standard structure for storing task results in the database,
ensuring consistency between fast-path routing and HGNN escalation paths.
"""

import json
import ast
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator  # pyright: ignore[reportMissingImports]

from .cognitive import DecisionKind

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


class TaskStep(BaseModel):
    """Individual step in a multi-step task plan."""

    model_config = {"extra": "ignore"}

    organ_id: str = Field(..., description="Target organ for this step")
    success: bool = Field(..., description="Whether this step completed successfully")
    task: Optional[JSONValue] = Field(None, description="Task definition for this step")
    result: Optional[JSONValue] = Field(
        None, description="Result from this step execution"
    )
    error: Optional[str] = Field(None, description="Error message if step failed")
    metadata: Optional[Dict[str, Any]] = Field(
        None, description="Additional step metadata"
    )

    @field_validator("result", "task", mode="before")
    @classmethod
    def _coerce_result(cls, v):
        return _maybe_parse_str(v)


class FastPathResult(BaseModel):
    """Result from direct routing (fast path)."""

    model_config = {"extra": "ignore"}

    routed_to: str = Field(..., description="Organ that processed the task")
    organ_id: str = Field(..., description="ID of the organ that handled the task")
    processing_time_ms: Optional[float] = Field(
        None, description="Task processing time in milliseconds"
    )
    result: JSONValue = Field(..., description="Direct result from the organ")
    metadata: Optional[Dict[str, Any]] = Field(
        None, description="Additional fast path metadata"
    )

    @field_validator("result", mode="before")
    @classmethod
    def _coerce_result(cls, v):
        return _maybe_parse_str(v)


class EscalatedPathResult(BaseModel):
    """Result from HGNN escalation and decomposition."""

    model_config = {"extra": "ignore"}

    solution_steps: List[TaskStep] = Field(
        ..., description="List of decomposed solution steps"
    )
    plan_source: str = Field(
        default="cognitive_service", description="Source of the decomposition plan"
    )
    estimated_complexity: Optional[str] = Field(
        None, description="Estimated task complexity"
    )
    explanations: Optional[str] = Field(
        None, description="Explanation of the decomposition strategy"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None, description="Additional escalation metadata"
    )


class CognitivePathResult(BaseModel):
    """Result from cognitive reasoning tasks."""

    model_config = {"extra": "ignore"}

    agent_id: str = Field(..., description="ID of the cognitive agent")
    task_type: str = Field(..., description="Type of cognitive task performed")
    result: JSONValue = Field(..., description="Cognitive reasoning result")
    confidence_score: Optional[float] = Field(
        None, description="Confidence in the result"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None, description="Additional cognitive metadata"
    )

    @field_validator("result", mode="before")
    @classmethod
    def _coerce_result(cls, v):
        return _maybe_parse_str(v)


class CognitiveResultPayload(BaseModel):
    """Payload structure for cognitive result used in CognitiveCore."""

    model_config = {"extra": "ignore"}

    result: JSONValue = Field(..., description="Cognitive reasoning result")
    cog_type: str = Field(..., description="Type of cognitive task performed")
    agent_id: Optional[str] = Field(None, description="ID of the cognitive agent")
    confidence_score: Optional[float] = Field(
        None, description="Confidence in the result"
    )
    cache_hit: Optional[bool] = Field(
        None, description="Whether this result was from cache"
    )
    sufficiency: Optional[Dict[str, Any]] = Field(
        None, description="Retrieval sufficiency metrics"
    )
    post_condition_violations: Optional[List[str]] = Field(
        None, description="Post-condition validation violations"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None, description="Additional cognitive metadata"
    )

    @field_validator("result", mode="before")
    @classmethod
    def _coerce_result(cls, v):
        return _maybe_parse_str(v)


class CognitiveResult(BaseModel):
    """Standard cognitive result structure used by CognitiveCore."""

    model_config = {"extra": "ignore"}

    success: bool = Field(
        ..., description="Whether the cognitive task completed successfully"
    )
    payload: CognitiveResultPayload = Field(
        ..., description="The cognitive result payload"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Top-level metadata about the result"
    )


class ErrorPathResult(BaseModel):
    """Result when a task fails."""

    error: str = Field(..., description="Error message")
    error_type: str = Field(..., description="Type of error that occurred")
    original_type: Optional[str] = Field(
        None, description="Original result type that caused the error"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None, description="Additional error metadata"
    )


class TaskResult(BaseModel):
    """Unified envelope for all task results."""

    kind: DecisionKind = Field(..., description="Type of result processing path")
    payload: Union[
        FastPathResult, EscalatedPathResult, CognitivePathResult, ErrorPathResult
    ] = Field(..., description="The actual result payload")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Top-level metadata about the result"
    )


# Convenience constructors for common result types
def create_fast_path_result(
    target_organ_id: Optional[str] = None,
    routing_params: Optional[Dict[str, Any]] = None,
    interaction_mode: str = "coordinator_routed",
    processing_time_ms: Optional[float] = None,
    **metadata,
) -> TaskResult:
    """
    Create a Fast Path decision (System 1) for the Coordinator.

    This signals that the Coordinator has decided NOT to perform deep planning,
    and is delegating execution to the Organism Service.

    Args:
        target_organ_id: Optional hint for the specific organ (e.g., "utility_organ").
                         If None, OrganismRouter will resolve based on specialization.
        routing_params: Dictionary to merge into TaskPayload.params.routing
                        (e.g. {"required_specialization": "USER_LIAISON"}).
        interaction_mode: V2 Interaction mode (default: "coordinator_routed").
        processing_time_ms: Policy evaluation time.
        **metadata: Additional context (surprise scores, rule_id matched, etc.)

    Returns:
        TaskResult with kind=DecisionKind.FAST_PATH.
    """
    fast_path_metadata = {
        **(metadata or {}),
        "routing_params": routing_params or {},  # Matches params.routing structure
        "interaction_mode": interaction_mode,  # Will be merged into params.interaction.mode
    }
    # Use same value for routed_to and organ_id to avoid duplication
    # Both fields are required by FastPathResult model
    target_organ = target_organ_id or "organism"
    fast_path_payload = FastPathResult(
        routed_to=target_organ,
        organ_id=target_organ,
        processing_time_ms=processing_time_ms,
        result={
            "status": "routed",
            "pending_execution": True,
        },  # Placeholder result for routing decisions
        metadata=fast_path_metadata,
    )

    # 2. Wrap in TaskResult
    # Note: path information is already encoded in kind (DecisionKind.FAST_PATH)
    # The actual path used in final envelope comes from normalize_envelope() parameter
    # All routing information (organ_id, processing_time_ms) is in payload, so metadata is empty
    return TaskResult(
        kind=DecisionKind.FAST_PATH,
        payload=fast_path_payload,
        metadata={},  # Empty - all routing info is in payload (organ_id, processing_time_ms)
    )


def create_cognitive_path_result(
    confidence_score: Optional[float] = None, **metadata
) -> TaskResult:
    """
    Create a System 2 Escalation Result (Cognitive Reasoning).

    This signals that the Coordinator has detected high entropy or complexity (OCPS),
    and is delegating the task to the Intelligence Plane (Cognitive Service)
    for decomposition, planning, or deep analysis.

    Args:
        confidence_score: Optional confidence in the decision to escalate.
        **metadata: Context (OCPS drift scores, trace IDs, proto_plan, ocps_payload, etc.).
                     Note: pkg_meta is embedded in proto_plan.metadata.

    Returns:
        TaskResult with kind=DecisionKind.COGNITIVE.
    """

    # Extract router_latency_ms for TaskResult.metadata (top-level routing metadata)
    router_latency_ms = metadata.pop("router_latency_ms", None)

    cognitive_payload = CognitivePathResult(
        # Sentinel ID: Signals this is a service-level request, not an actor-level task
        agent_id="coordinator_service",
        result={},  # Empty result - all data is in metadata
        confidence_score=confidence_score,
        metadata=metadata,  # Contains proto_plan (with pkg_meta embedded), ocps_payload, insight, etc.
    )

    # TaskResult.metadata contains top-level routing/execution metadata
    # (separate from CognitivePathResult.metadata which contains detailed context)
    # Note: path is set by normalize_envelope() caller, not here
    # All routing info (agent_id, target) is in payload, so metadata is minimal
    task_result_metadata = {}
    if router_latency_ms is not None:
        task_result_metadata["exec_time_ms"] = router_latency_ms

    return TaskResult(
        kind=DecisionKind.COGNITIVE,
        payload=cognitive_payload,
        metadata=task_result_metadata,
    )


def create_escalated_path_result(
    solution_steps: List[TaskStep],
    plan_source: str = "cognitive_service",
    estimated_complexity: Optional[str] = None,
    explanations: Optional[str] = None,
    **metadata,
) -> TaskResult:
    """Create an escalated result with HGNN decomposition."""
    escalated_payload = EscalatedPathResult(
        solution_steps=solution_steps,
        plan_source=plan_source,
        estimated_complexity=estimated_complexity,
        explanations=explanations,
        metadata=metadata,
    )

    return TaskResult(
        kind=DecisionKind.ESCALATED,
        payload=escalated_payload,
        metadata={
            "path": "hgnn_decomposition",
            "step_count": len(solution_steps),
            "escalated": True,
        },
    )


def create_cognitive_result(
    agent_id: str,
    cog_type: Optional[str] = None,
    task_type: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
    confidence_score: Optional[float] = None,
    cache_hit: Optional[bool] = None,
    sufficiency: Optional[Dict[str, Any]] = None,
    post_condition_violations: Optional[List[str]] = None,
    **metadata,
) -> CognitiveResult:
    """
    Create a standard cognitive result structure for CognitiveCore.

    This function creates a CognitiveResult that matches the structure expected
    by CognitiveCore._package_result(), which accesses:
    - out.success
    - out.payload.result
    - out.payload.cog_type
    - out.metadata

    Args:
        agent_id: ID of the cognitive agent that processed the task
        cog_type: Type of cognitive task (e.g., "chat", "task_planning")
                  Takes precedence over task_type if both are provided.
                  Required if task_type is not provided.
        task_type: Alternative parameter name for cog_type (for backward compatibility).
                   Used if cog_type is not provided.
        result: The cognitive reasoning result payload (defaults to empty dict if None)
        confidence_score: Optional confidence score for the result
        cache_hit: Whether this result was retrieved from cache
        sufficiency: Optional retrieval sufficiency metrics
        post_condition_violations: Optional list of post-condition violations
        **metadata: Additional metadata to include

    Returns:
        CognitiveResult with success=True, payload containing result and cog_type, and metadata

    Raises:
        ValueError: If neither cog_type nor task_type is provided
    """
    # Support both cog_type and task_type for compatibility
    final_cog_type = cog_type or task_type
    if not final_cog_type:
        raise ValueError("Either 'cog_type' or 'task_type' must be provided")

    # Default result to empty dict if None
    final_result = result if result is not None else {}

    payload = CognitiveResultPayload(
        result=final_result,
        cog_type=final_cog_type,
        agent_id=agent_id,
        confidence_score=confidence_score,
        cache_hit=cache_hit,
        sufficiency=sufficiency,
        post_condition_violations=post_condition_violations,
        metadata=metadata,
    )

    return CognitiveResult(success=True, payload=payload, metadata=metadata)


def create_error_result(
    error: str, error_type: str, original_type: Optional[str] = None, **metadata
) -> TaskResult:
    """Create an error result."""
    error_result = ErrorPathResult(
        error=error,
        error_type=error_type,
        original_type=original_type,
        metadata=metadata,
    )

    return TaskResult(
        kind=DecisionKind.ERROR,
        payload=error_result,
        metadata={"path": "error_handling"},
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
                        metadata={
                            k: v
                            for k, v in item.items()
                            if k
                            not in {"organ_id", "success", "task", "result", "error"}
                        },
                    )
                    steps.append(step)
            return create_escalated_path_result(
                solution_steps=steps, plan_source="legacy"
            )
        # fallback to error if not list-like
        return create_error_result(
            "Legacy raw_result unparseable",
            "legacy_format",
            metadata={"legacy_data": legacy_result},
        )

    # Escalation-shaped legacy
    if "solution_steps" in legacy_result or "plan" in legacy_result:
        steps_in = legacy_result.get("solution_steps", legacy_result.get("plan", []))
        steps = []
        if isinstance(steps_in, list):
            for s in steps_in:
                if isinstance(s, dict):
                    steps.append(
                        TaskStep(**{**s, "result": _maybe_parse_str(s.get("result"))})
                    )
        meta = {
            k: v
            for k, v in legacy_result.items()
            if k not in {"solution_steps", "plan", "plan_source"}
        }
        return create_escalated_path_result(
            solution_steps=steps,
            plan_source=legacy_result.get("plan_source", "unknown"),
            **meta,
        )

    # Default fast path
    meta = {
        k: v
        for k, v in legacy_result.items()
        if k not in {"routed_to", "organ_id", "result"}
    }
    return create_fast_path_result(
        routed_to=legacy_result.get("routed_to", "unknown"),
        organ_id=legacy_result.get("organ_id", "unknown"),
        result=_maybe_parse_str(legacy_result.get("result", legacy_result)),
        **meta,
    )


# Database helpers for JSONB compatibility
def to_db_dict(tr: TaskResult) -> Dict[str, Any]:
    """Convert TaskResult to a JSON-serializable dict for database storage."""
    return tr.model_dump(mode="json", by_alias=True)


def from_db_dict(d: Dict[str, Any]) -> TaskResult:
    """Create TaskResult from a database dict."""
    return TaskResult.model_validate(d)


# Canonical response envelope for router responses
# Every router call returns exactly this structure (no kind field)
# Derive valid decision kinds from the DecisionKind enum to avoid duplication
DECISION_KINDS = {dk.value for dk in DecisionKind}


def make_envelope(
    *,
    task_id: str,
    success: bool,
    payload: Any = None,
    error: Optional[str] = None,
    error_type: Optional[str] = None,
    retry: bool = True,
    decision_kind: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
    path: str = "coordinator",
) -> Dict[str, Any]:
    """
    Create a canonical response envelope for router responses.

    This is the single source of truth for all router return values.
    Every router call returns exactly this structure (no kind field).

    Args:
        task_id: Task identifier
        success: Whether the task completed successfully
        payload: The actual result data (any type)
        error: Optional error message
        error_type: Optional machine-readable error type
        retry: Whether the dispatcher should retry on failure
        decision_kind: Optional DecisionKind value (fast|planner|hgnn|error)
        meta: Optional metadata dict (routing decisions, scores, metrics)
        path: Producer trace path (default: "coordinator")

    Returns:
        Dict[str, Any] with canonical envelope structure
    """
    return {
        "task_id": str(task_id),
        "success": bool(success),
        "error": error,
        "error_type": error_type,
        "retry": bool(retry),
        "decision_kind": decision_kind,
        "payload": payload,
        "meta": meta or {},
        "path": path,
    }


def normalize_envelope(raw: Any, *, task_id: str, path: str) -> Dict[str, Any]:
    """
    Convert legacy results into the new canonical envelope format.

    This is the single source of truth for understanding legacy shapes.
    Handles conversion from:
    - TaskResult-like dict: {"kind": DecisionKind, "payload": ..., "metadata": ...}
    - Old router dicts containing kind=timeout/cancelled/error
    - Already-envelope dicts containing "success"
    - Anything else => type error envelope

    Args:
        raw: Raw result in any legacy or current format
        task_id: Task identifier to include in envelope
        path: Producer trace path

    Returns:
        Dict[str, Any] in canonical envelope format
    """
    # Already in new envelope format
    if (
        isinstance(raw, dict)
        and "success" in raw
        and "payload" in raw
        and "error_type" in raw
    ):
        raw.setdefault("task_id", str(task_id))
        raw.setdefault("path", path)
        raw.setdefault("meta", {})
        raw.setdefault("retry", True)
        raw.setdefault("decision_kind", None)
        # Ensure no stray kind
        raw.pop("kind", None)
        return raw

    # TaskResult-like dict (internal): {"kind": "...", "payload": ..., "metadata": ...}
    if isinstance(raw, dict) and "payload" in raw and "kind" in raw:
        k = raw.get("kind")
        payload = raw.get("payload")
        metadata = raw.get("metadata") or raw.get("meta") or {}
        if k in DECISION_KINDS:
            # DecisionKind mapped to decision_kind
            if k == "error":
                # payload is ErrorPathResult-like dict
                err = (
                    payload.get("error")
                    if isinstance(payload, dict)
                    else "unknown_error"
                )
                err_type = (
                    payload.get("error_type") if isinstance(payload, dict) else "error"
                )
                return make_envelope(
                    task_id=task_id,
                    success=False,
                    payload=payload,
                    error=err,
                    error_type=err_type,
                    retry=True,
                    decision_kind="error",
                    meta=metadata,
                    path=path,
                )
            return make_envelope(
                task_id=task_id,
                success=True,
                payload=payload,
                error=None,
                error_type=None,
                retry=True,
                decision_kind=str(k),
                meta=metadata,
                path=path,
            )

        # Legacy: kind used as error_type ("timeout", "cancelled", "error", etc.)
        # Convert to envelope using kind => error_type
        if k in {"timeout", "cancelled"}:
            return make_envelope(
                task_id=task_id,
                success=False,
                payload=raw,
                error=raw.get("error") or f"{k}",
                error_type=k,
                retry=True,
                decision_kind=None,
                meta=raw.get("meta") or {},
                path=path,
            )

        # Unknown kind: treat as generic error
        return make_envelope(
            task_id=task_id,
            success=False,
            payload=raw,
            error=raw.get("error") or "unknown_error",
            error_type="unknown_error",
            retry=True,
            decision_kind=None,
            meta=raw.get("meta") or {},
            path=path,
        )

    # Old envelope-like dict without error_type/payload fields
    if isinstance(raw, dict) and "success" in raw:
        # Best-effort upgrade
        payload = raw.get("payload", raw.get("result", raw))
        error = raw.get("error")
        success = bool(raw.get("success"))
        return make_envelope(
            task_id=task_id,
            success=success,
            payload=payload,
            error=error,
            error_type=None if success else "error",
            retry=bool(raw.get("retry", True)),
            decision_kind=raw.get("decision_kind"),
            meta=raw.get("meta") or {},
            path=raw.get("path") or path,
        )

    # Non-dict => type error
    return make_envelope(
        task_id=task_id,
        success=False,
        payload=raw,
        error=f"Invalid result type: {type(raw).__name__}",
        error_type="coordinator_type_error",
        retry=True,
        decision_kind=None,
        meta={},
        path=path,
    )
