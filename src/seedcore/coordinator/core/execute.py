"""
Core execution orchestration for Coordinator (Tier-0 Cortex).

Architecture:
- Coordinator = Policy + Planning Cortex
  - Intent decomposition (natural language → structured intent)
  - Surprise/OCPS (fast-path vs cognitive-path decision)
  - PKG policy evaluation (rules, constraints, safety, multi-step planning)
  - Plan synthesis (concrete execution plan with routing hints)

This module:
- Evaluates PKG policy to produce proto_plan with routing hints
- Extracts routing intent FROM proto_plan (PKG-first architecture)
- Delegates execution to Organism with routing hints already embedded
- Does NOT do device/vendor inference (that's Organism's job)
- Does NOT do intent decomposition (that's PKG's job)
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
import uuid
from dataclasses import dataclass
from typing import (
    Any,
    Dict,
    List,
    Tuple,
    Callable,
    Awaitable,
    Sequence,
    Mapping,
    Optional,
    Set,
)

from seedcore.agents.roles import Specialization
from seedcore.coordinator.core.ocps_valve import NeuralCUSUMValve
from seedcore.coordinator.core.intent import (
    RoutingIntent,
    PKGPlanIntentExtractor,
    IntentEnricher,
    IntentValidator,
    IntentSource,
    IntentConfidence,
    SummaryGenerator,
    IntentInsight,
)
from seedcore.logging_setup import ensure_serve_logger, setup_logging
from seedcore.models.cognitive import CognitiveType, DecisionKind
from seedcore.models.task import TaskType
from seedcore.models.task_payload import TaskPayload
from seedcore.models.result_schema import (
    create_cognitive_path_result,
    create_fast_path_result,
    make_envelope,
    normalize_envelope,
)
from ..utils import extract_from_nested
from .policies import SurpriseComputer
from .signals import SignalEnricher
from .plan import persist_and_register_dependencies

setup_logging(app_name="seedcore.coordinator.core.execute.driver")
logger = ensure_serve_logger("seedcore.coordinator.core.execute", level="DEBUG")

# Tunables
DEFAULT_ORGAN_TIMEOUT_S = 30.0
MIN_ORGAN_TIMEOUT_S = 20.0
MAX_ORGAN_TIMEOUT_S = 300.0
DEFAULT_PKG_TIMEOUT_S = 2
MAX_STEPS_DEFAULT = 32

# Global embedder instance (singleton for efficiency)
# This prevents redundant configuration checks and API re-authentication on every task
_global_embedder: Optional[Any] = None
_embedder_lock = None


def _get_global_embedder():
    """Get or create the global SynopsisEmbedder instance (thread-safe singleton)."""
    global _global_embedder, _embedder_lock

    if _global_embedder is not None:
        return _global_embedder

    # Use threading lock for initialization (SynopsisEmbedder uses threading internally)
    if _embedder_lock is None:
        _embedder_lock = threading.Lock()

    with _embedder_lock:
        # Double-check after acquiring lock
        if _global_embedder is not None:
            return _global_embedder

        from seedcore.ml.embedding.synopsis_embedder import SynopsisEmbedder

        _global_embedder = SynopsisEmbedder(dim=1024)
        logger.debug(
            "[Coordinator] Initialized global embedder: backend=%s, model=%s, dim=1024",
            _global_embedder.backend,
            _global_embedder.model,
        )
        return _global_embedder


# ---------------------------------------------------------------------------
# Configuration Objects
# ---------------------------------------------------------------------------

# Type signature for PKG evaluation function
# Supports both old signature (without embedding) and new signature (with embedding)
# The embedding parameter is optional and can be passed as a keyword argument
PkgEvalFn = Callable[
    ...,
    Awaitable[dict[str, Any]],
]

IntentResolverFn = Callable[["TaskContext"], RoutingIntent]


@dataclass(frozen=True)
class TaskContext:
    """Task-derived context: everything extracted from task/eventizer/facts."""

    task_id: str
    task_type: str
    domain: str | None
    description: str  # Refined description (processed_text from Eventizer if available)
    params: dict[str, Any]

    # eventizer
    eventizer_data: dict[str, Any]
    eventizer_tags: dict[str, Any]
    tags: set[str]
    attributes: dict[str, Any]
    confidence: dict[str, Any]
    signals: dict[str, Any]  # x1..x6 surprise signals from Eventizer
    pii_redacted: bool

    # placeholders for future integrations
    fact_reads: list[str]
    fact_produced: list[str]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskContext":
        return cls(
            task_id=d["task_id"],
            task_type=d["task_type"],
            domain=d["domain"],
            description=d.get("description") or "",
            params=d["params"],
            eventizer_data=d["eventizer_data"],
            eventizer_tags=d["eventizer_tags"],
            tags=set(d["tags"]),
            attributes=d["attributes"],
            confidence=d["confidence"],
            signals=d.get("signals", {}),  # Extract signals for SurpriseComputer
            pii_redacted=d["pii_redacted"],
            fact_reads=list(d["fact_reads"]),
            fact_produced=list(d["fact_produced"]),
        )


@dataclass(frozen=True)
class RouteConfig:
    """Routing decision_kind configuration."""

    surprise_computer: SurpriseComputer
    ocps_valve: NeuralCUSUMValve
    tau_fast_exit: float
    tau_plan_exit: float

    signal_enricher: SignalEnricher | None = None
    evaluate_pkg_func: PkgEvalFn | None = None
    ood_to01: Callable[[float], float] | None = None
    pkg_timeout_s: int = DEFAULT_PKG_TIMEOUT_S

    # DEPRECATED: intent_resolver is legacy. PKG should provide routing hints.
    # Architecture: PKG (policy layer) decides WHAT and IN WHAT ORDER.
    # Routing intent should be extracted from proto_plan, not computed separately.
    # This field is kept for backward compatibility but should not be used.
    intent_resolver: IntentResolverFn | None = None


@dataclass(frozen=True)
class ExecutionConfig:
    """Configuration for task execution dependencies."""

    # NOTE: signature may vary across versions; we tolerate multiple call patterns
    compute_drift_score: Callable[..., Awaitable[float]]

    organism_execute: Callable[
        [str, dict[str, Any], float, str], Awaitable[dict[str, Any]]
    ]
    graph_task_repo: Any
    ml_client: Any
    metrics: Any
    cid: str
    normalize_domain: Callable[[str | None], str | None]

    cognitive_client: Any | None = None
    persist_proto_plan_func: (
        Callable[[Any, str, Any, dict[str, Any]], Awaitable[None]] | None
    ) = None
    record_router_telemetry_func: (
        Callable[[Any, str, dict[str, Any]], Awaitable[None]] | None
    ) = None
    resolve_session_factory_func: Callable[[Any], Any] | None = None

    fast_path_latency_slo_ms: float = 5000.0
    eventizer_helper: Callable[[Any], Any] | None = None

    # Safety valves
    max_steps: int = MAX_STEPS_DEFAULT
    
    # Coordinator reference for embedding enqueue (1024d worker architecture)
    coordinator: Any | None = None
    
    # Enable Phase 2 result consolidation (asynchronous memory write-back)
    enable_consolidation: bool = True


# RoutingIntent is now imported from coordinator.core.intent
# This import maintains backward compatibility for type hints

# ---------------------------------------------------------------------------
# Generic async call helpers
# ---------------------------------------------------------------------------


async def _maybe_await(x: Any) -> Any:
    if inspect.isawaitable(x):
        return await x
    return x


def _clamp_timeout_s(x: float) -> float:
    try:
        x = float(x)
    except Exception:
        x = DEFAULT_ORGAN_TIMEOUT_S
    return max(MIN_ORGAN_TIMEOUT_S, min(MAX_ORGAN_TIMEOUT_S, x))


async def _call_compute_drift_score(
    fn: Callable[..., Awaitable[float]],
    task_dict: Dict[str, Any],
    text_payload: Dict[str, Any],
    ml_client: Any = None,
    metrics: Any = None,
) -> float:
    """
    Signature-tolerant drift score call.
    Common variants:
      - compute_drift_score(task_dict, text_payload)
      - compute_drift_score(task=task_dict, text_payload=text_payload, ml_client=..., metrics=...)
      - compute_drift_score(task_dict, text_payload, ml_client, metrics)
    """
    # Try keyword-rich (newer style)
    try:
        return float(
            await _maybe_await(
                fn(
                    task=task_dict,
                    text_payload=text_payload,
                    ml_client=ml_client,
                    metrics=metrics,
                )
            )
        )
    except TypeError:
        pass
    except Exception:
        # If it's a real failure (not signature mismatch), fall through to simpler forms
        logger.debug(
            "compute_drift_score keyword call failed; trying alternate signatures",
            exc_info=True,
        )

    # Try (task_dict, text_payload, ml_client, metrics)
    try:
        return float(
            await _maybe_await(fn(task_dict, text_payload, ml_client, metrics))
        )
    except TypeError:
        pass
    except Exception:
        logger.debug(
            "compute_drift_score 4-arg call failed; trying 2-arg", exc_info=True
        )

    # Try (task_dict, text_payload)
    return float(await _maybe_await(fn(task_dict, text_payload)))


async def _call_pkg_eval(
    fn: PkgEvalFn,
    *,
    tags: Sequence[str],
    signals: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    timeout_s: int,
    embedding: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """
    PKG evaluator call wrapper that tolerates positional/keyword implementations.
    
    ENHANCEMENT: Supports embedding parameter for semantic context hydration.
    """
    try:
        # Try with embedding parameter (new signature)
        return await _maybe_await(
            fn(tags=tags, signals=signals, context=context, timeout_s=timeout_s, embedding=embedding)
        )
    except TypeError:
        try:
            # Fallback to original signature without embedding
            return await _maybe_await(
                fn(tags=tags, signals=signals, context=context, timeout_s=timeout_s)
            )
        except TypeError:
            # Fallback to positional arguments
            return await _maybe_await(fn(tags, signals, context, timeout_s))


# ---------------------------------------------------------------------------
# Routing Intent Extraction (PKG-First Architecture)
# ---------------------------------------------------------------------------
# Intent extraction is now handled by coordinator.core.intent module
# These are convenience wrappers that maintain backward compatibility


def _extract_routing_intent_from_proto_plan(
    proto_plan: Dict[str, Any], ctx: TaskContext
) -> Optional[RoutingIntent]:
    """
    Extract routing intent from PKG-generated proto_plan.
    
    DEPRECATED: Use PKGPlanIntentExtractor.extract() directly.
    This wrapper maintains backward compatibility.
    
    Architecture: Coordinator (PKG) decides WHAT and IN WHAT ORDER.
    This function extracts the routing hints that PKG embedded in the plan.
    """
    return PKGPlanIntentExtractor.extract_with_validation(proto_plan, ctx)


def _minimal_fallback_intent(ctx: TaskContext) -> RoutingIntent:
    """
    Structurally neutral fallback routing intent when PKG is unavailable.

    This is ONLY used when:
    1. PKG evaluation is disabled/not configured
    2. FAST_PATH (non-escalated) and no proto_plan available

    Architecture Note: This is a safety fallback only. PKG should always
    be the source of routing meaning. This fallback is structurally neutral
    and does not encode business semantics (no device/vendor inference).

    WARNING: Using this fallback weakens policy guarantees. PKG evaluation
    should be enabled for production deployments.
    """
    # Structurally neutral fallback - no semantic meaning
    # PKG should always provide proper routing hints
    return RoutingIntent(
        specialization=Specialization.GENERALIST.value,
        skills={},
        source=IntentSource.FALLBACK_NEUTRAL,
        confidence=IntentConfidence.MINIMAL,
    )


# ---------------------------------------------------------------------------
# Proto-plan extraction
# ---------------------------------------------------------------------------


def _extract_proto_plan(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return extract_from_nested(
        payload,
        key_paths=[
            ("result", "proto_plan"),
            ("proto_plan",),
            ("metadata", "proto_plan"),
        ],
        value_type=dict,
    )


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def execute_task(
    task: TaskPayload,
    route_config: RouteConfig,
    execution_config: ExecutionConfig,
) -> Dict[str, Any]:
    task_context_dict = await _process_task_input(
        task=task,
        eventizer_helper=execution_config.eventizer_helper,
        normalize_domain=execution_config.normalize_domain,
    )
    ctx = TaskContext.from_dict(task_context_dict)

    # 2. PHASE 1: INTENT EMBEDDING (Reliability Optimized)
    # We try a synchronous persist for the Semantic Cache.
    # If it fails (Ray timeout/DB lock), we trigger a "Fast Enqueue" to the background worker.
    # This implements Layer 1 of the Three-Layer Safety System:
    #   - Sync Path: Attempt 1024d write for immediate Cache Hit potential
    #   - Fast Enqueue: If Sync fails, push to runtime_ctx queue for immediate worker pickup
    try:
        embedding_vector = await asyncio.wait_for(
            _generate_and_persist_task_embedding(ctx, execution_config),
            timeout=3.0,  # Tight timeout for API responsiveness
        )
    except asyncio.TimeoutError:
        logger.warning(
            f"[Coordinator] Sync embedding timeout for {ctx.task_id}. "
            "Triggering Layer 1 (Fast Enqueue)."
        )
        embedding_vector = None
        # Trigger Layer 1 Safety: Background enqueue so worker handles it while we proceed
        if execution_config.coordinator:
            await execution_config.coordinator._enqueue_task_embedding_now(
                ctx.task_id, reason="sync_fallback"
            )
    except Exception as e:
        logger.warning(
            f"[Coordinator] Sync embedding failed for {ctx.task_id}: {e}. "
            "Triggering Layer 1 (Fast Enqueue)."
        )
        embedding_vector = None
        # Trigger Layer 1 Safety: Background enqueue so worker handles it while we proceed
        if execution_config.coordinator:
            await execution_config.coordinator._enqueue_task_embedding_now(
                ctx.task_id, reason="sync_fallback"
            )

    # 2.5. SEMANTIC CACHE CHECK (System 0 Fast Path)
    # Check for near-identical completed tasks before expensive route-and-execute
    if embedding_vector and execution_config.graph_task_repo:
        cached_result = await _check_semantic_cache(ctx, embedding_vector, execution_config)
        if cached_result:
            logger.info(
                f"[Coordinator] Semantic Cache HIT for task {ctx.task_id} - returning cached result"
            )
            # Normalize cached result to canonical format
            return normalize_envelope(cached_result, task_id=ctx.task_id, path="coordinator_cache")

    routing_dec = await _compute_routing_decision(
        task=task,
        ctx=ctx,
        route_cfg=route_config,
        exec_cfg=execution_config,
        correlation_id=task.correlation_id or execution_config.cid,
        embedding=embedding_vector,  # Pass embedding for PKG hydration
    )

    # Extract decision_kind from TaskResult.kind and payload from TaskResult
    decision_kind = routing_dec.get("kind") or routing_dec.get("decision_kind")
    router_result_payload = routing_dec

    if decision_kind == DecisionKind.FAST_PATH.value:
        # Extract routing information from FastPathResult
        routing_params = extract_from_nested(
            router_result_payload,
            key_paths=[
                ("payload", "metadata", "routing_params"),  # FastPathResult.metadata.routing_params
                ("metadata", "routing_params"),  # Top-level fallback
                ("metadata", "routing", "params"),  # Alternative structure
            ],
            value_type=dict,
        ) or {}
        
        interaction_mode = extract_from_nested(
            router_result_payload,
            key_paths=[
                ("payload", "metadata", "interaction_mode"),  # FastPathResult.metadata.interaction_mode
                ("metadata", "interaction_mode"),  # Top-level fallback
            ],
            value_type=str,
        ) or "coordinator_routed"
        
        target_organ_id = extract_from_nested(
            router_result_payload,
            key_paths=[
                ("payload", "organ_id"),  # FastPathResult.organ_id
                ("payload", "routed_to"),  # FastPathResult.routed_to (fallback)
            ],
            value_type=str,
        ) or "organism"
        
        result = await _handle_fast_path(
            task=task,
            routing_params=routing_params,
            interaction_mode=interaction_mode,
            target_organ_id=target_organ_id,
            config=execution_config,
        )
        # Normalize to canonical format (idempotent - safe even if already canonical)
        # organism_execute now returns canonical envelope, but normalization ensures
        # all required fields are present and task_id/path are set correctly
        final_result = normalize_envelope(result, task_id=ctx.task_id, path="coordinator_fast_path")
        
        # PHASE 2: RESULT CONSOLIDATION (Asynchronous)
        if final_result and execution_config.enable_consolidation and execution_config.coordinator:
            asyncio.create_task(
                _consolidate_result_embedding(ctx, final_result, execution_config)
            )
        
        return final_result

    if decision_kind == DecisionKind.COGNITIVE.value:
        result = await _handle_cognitive_path(
            task=task,
            decision_payload=router_result_payload,
            decision_kind=DecisionKind(decision_kind),
            config=execution_config,
        )
        # Normalize to canonical format
        final_result = normalize_envelope(result, task_id=ctx.task_id, path="coordinator_cognitive_path")
        
        # PHASE 2: RESULT CONSOLIDATION (Asynchronous)
        if final_result and execution_config.enable_consolidation and execution_config.coordinator:
            asyncio.create_task(
                _consolidate_result_embedding(ctx, final_result, execution_config)
            )
        
        return final_result

    logger.warning(
        "[Coordinator] Routing decision '%s' not handled; returning router payload",
        decision_kind,
    )
    # Normalize router payload to canonical format
    final_result = normalize_envelope(router_result_payload, task_id=ctx.task_id, path="coordinator_unknown")

    # 5. PHASE 2: RESULT CONSOLIDATION (Asynchronous)
    # Once we have a result, we "consolidate" the memory.
    # This embeds the OUTCOME of the task so future semantic cache hits are more accurate.
    # Fire-and-forget background task - user already has their result.
    if final_result and execution_config.enable_consolidation and execution_config.coordinator:
        asyncio.create_task(
            _consolidate_result_embedding(ctx, final_result, execution_config)
        )

    return final_result


# =========================================================================
# FAST PATH (System 1)
# =========================================================================


async def _handle_fast_path(
    task: TaskPayload,
    routing_params: Dict[str, Any],
    interaction_mode: str,
    target_organ_id: str,
    config: ExecutionConfig,
) -> Dict[str, Any]:
    """
    Handle fast path execution by merging routing information from FastPathResult into TaskPayload.
    
    This function correctly extracts and applies:
    - routing_params: Merged into params.routing (specialization, skills, etc.)
    - interaction_mode: Merged into params.interaction.mode
    - target_organ_id: Used as the target organ for execution (from FastPathResult.organ_id)
    """
    task_payload_dict = task.model_dump()
    params = task_payload_dict.setdefault("params", {})

    # Merge routing_params into params.routing (never replace wholesale)
    if routing_params:
        existing = params.get("routing") or {}
        if isinstance(existing, dict):
            params["routing"] = {**existing, **routing_params}
        else:
            params["routing"] = dict(routing_params)

    # Merge interaction_mode into params.interaction.mode
    interaction = params.setdefault("interaction", {})
    if isinstance(interaction, dict):
        interaction["mode"] = interaction_mode
    else:
        params["interaction"] = {"mode": interaction_mode}

    timeout = _clamp_timeout_s((config.fast_path_latency_slo_ms / 1000.0) * 2.0)

    try:
        return await config.organism_execute(
            target_organ_id,  # Use target_organ_id from FastPathResult instead of hardcoded "organism"
            task_payload_dict,
            timeout,
            config.cid,
        )
    except Exception as e:
        logger.error("[Coordinator] Fast Path delegation failed: %s", e, exc_info=True)
        return make_envelope(
            task_id=task.task_id,
            success=False,
            error=str(e),
            error_type="execution_error",
            decision_kind=DecisionKind.ERROR.value,
            path="coordinator_fast_path",
        )


# =========================================================================
# COGNITIVE PATH (System 2)
# =========================================================================


async def _handle_cognitive_path(
    task: TaskPayload,
    decision_payload: Dict[str, Any],
    decision_kind: DecisionKind,
    config: ExecutionConfig,
) -> Dict[str, Any]:
    if not config.cognitive_client:
        logger.error("[Coordinator] Cognitive Client missing.")
        return make_envelope(
            task_id=task.task_id,
            success=False,
            error="System 2 unavailable",
            error_type="config_error",
            decision_kind=DecisionKind.ERROR.value,
            path="coordinator_cognitive_path",
        )

    try:
        # Extract metadata from TaskResult.payload.metadata (CognitivePathResult.metadata)
        payload_metadata = decision_payload.get("payload", {}).get("metadata", {})
        proto_plan_from_router = payload_metadata.get("proto_plan") or {}
        ocps_payload = (
            payload_metadata.get("ocps") or payload_metadata.get("ocps_payload") or {}
        )

        # 1) Ask cognitive service to refine / expand plan
        # Note: pkg_meta is embedded in proto_plan.metadata, no need to pass separately
        plan_res = await config.cognitive_client.execute_async(
            agent_id="coordinator_service",
            cog_type=CognitiveType.TASK_PLANNING,
            decision_kind=decision_kind,
            task=task,
            proto_plan=proto_plan_from_router or None,
            ocps=ocps_payload or None,
        )

        # 2) Extract executable steps (before persistence)
        solution_steps = _extract_solution_steps(plan_res)

        # 2a) Enforce MAX_STEPS before persistence (prevents DB pollution)
        max_steps_limit = int(config.max_steps or MAX_STEPS_DEFAULT)
        if solution_steps and len(solution_steps) > max_steps_limit:
            return make_envelope(
                task_id=task.task_id,
                success=False,
                error=f"Refusing to execute {len(solution_steps)} steps (max_steps={max_steps_limit})",
                error_type="plan_too_large",
                decision_kind=DecisionKind.ERROR.value,
                path="coordinator_cognitive_path",
            )

        # 2b) Persist proto-plan (PKG-first; fallback to cognitive)
        proto_plan_to_persist = (
            proto_plan_from_router or _extract_proto_plan(plan_res) or {}
        )
        if proto_plan_to_persist and config.persist_proto_plan_func:
            await config.persist_proto_plan_func(
                config.graph_task_repo,
                task.task_id,
                decision_kind,
                proto_plan_to_persist,
            )

        # 2c) Persist plan DAG + register dependencies (Graph Task Repo)
        # Architecture: Coordinator owns the execution graph. This persists the
        # declarative plan structure (steps + dependencies) to the task graph,
        # making plans inspectable, resumable, and enabling future parallel execution.
        # This is non-blocking - execution proceeds even if graph persistence fails.
        if (
            proto_plan_to_persist
            and config.graph_task_repo
            and "steps" in proto_plan_to_persist
            and proto_plan_to_persist["steps"]
        ):
            try:
                await persist_and_register_dependencies(
                    plan=proto_plan_to_persist["steps"],
                    repo=config.graph_task_repo,
                    task={
                        "id": task.task_id,
                        "task_id": task.task_id,
                        "type": task.type,
                    },
                    root_db_id=task.task_id,  # Use task_id as root identifier
                )
                logger.debug(
                    "[Coordinator] Plan dependency graph persisted for task %s (%d steps)",
                    task.task_id,
                    len(proto_plan_to_persist["steps"]),
                )
            except Exception as e:
                logger.warning(
                    "[Coordinator] Plan dependency persistence failed (non-fatal) for task %s: %s",
                    task.task_id,
                    e,
                    exc_info=True,
                )
                # Non-blocking: execution continues even if graph persistence fails

        # 3) Handle direct response (no steps)
        if not solution_steps:
            # Cognitive agent returned direct response (no steps)
            # Normalize to canonical format
            direct_result = (
                plan_res
                if isinstance(plan_res, dict)
                else {"success": True, "result": plan_res, "error": None}
            )
            return normalize_envelope(direct_result, task_id=task.task_id, path="coordinator_cognitive_path")

        # 4) Execute steps (dependency-aware)

        logger.info(
            "[Coordinator] System 2 executing %d steps for task %s.",
            len(solution_steps),
            task.task_id,
        )

        timeout = _clamp_timeout_s((config.fast_path_latency_slo_ms / 1000.0) * 2.0)

        # Extract routing intent from proto_plan for step injection
        routing_intent = None
        if proto_plan_from_router:
            # PKGPlanIntentExtractor.extract() only uses proto_plan, not ctx
            routing_intent = PKGPlanIntentExtractor.extract(proto_plan_from_router)

        step_results = await _execute_steps_dependency_aware(
            parent_task=task,
            steps=solution_steps,
            organism_execute=config.organism_execute,
            timeout_s=timeout,
            cid=config.cid,
            routing_intent=routing_intent,
        )

        # 5) Aggregate
        return _aggregate_execution_results(
            parent_task_id=task.task_id,
            solution_steps=solution_steps,
            step_results=step_results,
            decision_kind=decision_kind.value,
            original_meta={"ocps": ocps_payload},
        )

    except Exception as e:
        logger.error("[Coordinator] Cognitive Path failed: %s", e, exc_info=True)
        return make_envelope(
            task_id=task.task_id,
            success=False,
            error=str(e),
            error_type="cognitive_error",
            decision_kind=DecisionKind.ERROR.value,
            path="coordinator_cognitive_path",
        )


# ---------------------------------------------------------------------------
# Step execution (dependency-aware)
# ---------------------------------------------------------------------------


async def _execute_steps_dependency_aware(
    *,
    parent_task: TaskPayload,
    steps: List[Dict[str, Any]],
    organism_execute: Callable[
        [str, dict[str, Any], float, str], Awaitable[dict[str, Any]]
    ],
    timeout_s: float,
    cid: str,
    routing_intent: Optional[RoutingIntent] = None,
) -> List[Dict[str, Any]]:
    """
    Executes steps respecting `depends_on` (by index or alias/id).
    Runs sequentially but only when dependencies are satisfied.

    Architecture: Coordinator controls order, Organism controls execution.
    This function ensures routing hints from PKG are attached to each step
    before delegation to Organism.

    Args:
        routing_intent: Optional routing intent from PKG to inject into steps.
                       If provided, ensures each step has routing hints even if
                       PKG didn't explicitly set them per-step.
    """

    # Map each step -> canonical step key used for dependency resolution
    # Priority: step["id"] -> step["task"].get("task_id"/"id") -> str(index)
    step_keys: List[str] = []
    key_to_index: Dict[str, int] = {}
    for i, step in enumerate(steps):
        k = (
            str(step.get("id") or "")
            or str(
                (step.get("task") or {}).get("task_id")
                or (step.get("task") or {}).get("id")
                or ""
            )
            or str(i)
        )
        k = k.strip() or str(i)
        step_keys.append(k)
        key_to_index[k] = i
        # also allow pure index string
        key_to_index[str(i)] = i

    # Build dependency list per step index
    deps: Dict[int, Set[int]] = {i: set() for i in range(len(steps))}
    for i, step in enumerate(steps):
        raw = step.get("depends_on") or (step.get("task") or {}).get("depends_on")
        if not raw:
            continue
        # Normalize depends entries -> indexes
        entries = raw if isinstance(raw, list) else [raw]
        for ent in entries:
            if isinstance(ent, int):
                if 0 <= ent < len(steps):
                    deps[i].add(ent)
                continue
            if isinstance(ent, str):
                ent = ent.strip()
                if ent in key_to_index:
                    deps[i].add(key_to_index[ent])
                    continue
                if ent.isdigit():
                    j = int(ent)
                    if 0 <= j < len(steps):
                        deps[i].add(j)

    done: Set[int] = set()
    in_progress: Set[int] = set()
    results: List[Dict[str, Any]] = []

    # Simple scheduler loop
    while len(done) < len(steps):
        runnable = [
            i
            for i in range(len(steps))
            if i not in done and i not in in_progress and deps[i].issubset(done)
        ]
        if not runnable:
            # cycle or unresolved deps
            missing = {
                i: sorted(list(deps[i] - done))
                for i in range(len(steps))
                if i not in done
            }
            return results + [
                {
                    "step": None,
                    "success": False,
                    "result": {
                        "error": "dependency_deadlock",
                        "missing": missing,
                    },
                }
            ]

        # deterministic: pick the smallest index next
        i = runnable[0]
        in_progress.add(i)

        step = steps[i]
        step_task_dict, organ_hint = _prepare_step_task_payload(
            parent_task=parent_task,
            step=step,
            index=i,
            cid=cid,
            routing_intent=routing_intent,
        )

        step_res = await organism_execute(
            organ_hint or "organism",
            step_task_dict,
            timeout_s,
            cid,
        )

        ok = bool(step_res.get("success"))
        results.append({"step": i, "success": ok, "result": step_res})

        in_progress.remove(i)
        done.add(i)

        if not ok:
            # stop on first failure (Coordinator policy; can be made configurable)
            break

    return results


# ---------------------------------------------------------------------------
# Helper Functions (Data Processing)
# ---------------------------------------------------------------------------


def _extract_solution_steps(plan_res: Any) -> List[Dict[str, Any]]:
    return (
        extract_from_nested(
            plan_res,
            key_paths=[
                ("result", "solution_steps"),
                ("result", "steps"),
                ("solution_steps",),
                ("steps",),
                ("metadata", "solution_steps"),
            ],
            value_type=list,
        )
        or []
    )


async def _generate_and_persist_task_embedding(
    ctx: TaskContext,
    execution_config: ExecutionConfig,
) -> Optional[List[float]]:
    """
    Phase 1: Intent Embedding Generation and Persistence.
    
    Generates a 1024d embedding from the task's intent (description + type + params)
    and persists it to the Knowledge Graph (graph_embeddings_1024) via the new worker architecture.
    
    This is the "Intent Embedding" that captures what the user *wanted* to do.
    Phase 2 (Consolidation) will later update this with what the system *did*.
    
    Architecture: Uses the new 1024d task embedding worker which:
    - Generates embeddings using the LTM embedder (Ray actor)
    - Persists to graph_embeddings_1024 with label='task.primary'
    - Uses content_hash for idempotency (prevents duplicate work)
    - Handles isolated nodes gracefully (inserts placeholder)
    
    Returns:
        The 1024d embedding vector as a list, or None if generation/persistence failed.
        The vector can be used for PKG semantic context hydration and semantic cache checks.
    
    Note:
        This operation is synchronous but has a timeout. Failures trigger fallback to
        the Fast Enqueue layer (Layer 1 of the Three-Layer Safety System).
    """
    if not ctx.description and not ctx.task_type:
        logger.debug("[Coordinator] Task has no description or type, skipping embedding")
        return None

    try:
        # Use the new 1024d worker architecture for Phase 1 (Intent Embedding)
        from seedcore.graph.task_embedding_worker import generate_and_persist_task_embedding
        
        # Convert task_id to UUID if needed
        try:
            task_id_uuid = (
                uuid.UUID(ctx.task_id) if isinstance(ctx.task_id, str) else ctx.task_id
            )
        except ValueError:
            logger.error(
                "[Coordinator] Malformed task_id '%s', skipping embedding persistence",
                ctx.task_id,
            )
            return None
        
        # Call the new worker function which handles:
        # - Content hash computation (matches SQL views exactly)
        # - Node mapping (ensure_task_node)
        # - Ray actor embedding generation
        # - Persistence to graph_embeddings_1024
        embedding_vector = await generate_and_persist_task_embedding(
            task_id=task_id_uuid,
            description=ctx.description,
            task_type=ctx.task_type,
            params=ctx.params or {},
            reason="coordinator_execute",
        )
        
        if embedding_vector:
            logger.debug(
                "[Coordinator] Phase 1 (Intent) embedding persisted for task %s",
                ctx.task_id,
            )
            return embedding_vector
        else:
            logger.debug(
                "[Coordinator] Phase 1 embedding returned None for task %s "
                "(may be isolated node or empty content)",
                ctx.task_id,
            )
            return None
            
    except ImportError as e:
        # Fallback to old multimodal embedding approach if new worker not available
        logger.debug(
            "[Coordinator] New embedding worker not available, falling back to multimodal: %s",
            e,
        )
        return await _generate_multimodal_embedding_fallback(ctx, execution_config)
    except Exception as e:
        # Non-blocking: embedding persistence failure should not break execution
        logger.debug(
            "[Coordinator] Failed to persist Phase 1 embedding for task %s (non-fatal): %s",
            ctx.task_id,
            e,
            exc_info=True,
        )
        return None


async def _generate_multimodal_embedding_fallback(
    ctx: TaskContext,
    execution_config: ExecutionConfig,
) -> Optional[List[float]]:
    """
    Fallback to old multimodal embedding approach for backward compatibility.
    
    This is used when the new 1024d worker architecture is not available.
    """
    if not execution_config.graph_task_repo:
        return None

    if not execution_config.resolve_session_factory_func:
        return None

    try:
        # Use global singleton embedder (prevents redundant initialization)
        embedder = _get_global_embedder()

        # Generate 1024d embedding from refined description (Eventizer-processed text)
        vec = embedder.embed_text(ctx.description or "", dim=1024)
        if vec is None:
            return None

        # Persist as plain list (repository expects List[float])
        embedding_vector = vec.tolist()

        # Get session factory and persist to Unified Memory (multimodal table)
        session_factory = execution_config.resolve_session_factory_func()
        async with session_factory() as session:
            async with session.begin():
                task_id_uuid = (
                    uuid.UUID(ctx.task_id) if isinstance(ctx.task_id, str) else ctx.task_id
                )

                # Extract modality from params if available
                source_modality = "text"
                if ctx.params and isinstance(ctx.params, dict):
                    multimodal = ctx.params.get("multimodal", {})
                    if isinstance(multimodal, dict):
                        source_modality = multimodal.get("modality", "text") or "text"

                # Construct model version string
                model_name_short = (
                    embedder.model.split("/")[-1] if "/" in embedder.model else embedder.model
                )
                model_version = f"{embedder.backend}-{model_name_short}-1024"

                await execution_config.graph_task_repo.save_task_multimodal_embedding(
                    session=session,
                    task_id=task_id_uuid,
                    embedding=embedding_vector,
                    source_modality=source_modality,
                    model_version=model_version,
                )
                
                return embedding_vector
    except Exception as e:
        logger.debug(
            "[Coordinator] Fallback embedding failed for task %s: %s",
            ctx.task_id,
            e,
            exc_info=True,
        )
        return None

def _prepare_step_task_payload(
    parent_task: TaskPayload,
    step: Dict[str, Any],
    index: int,
    cid: str | None,
    routing_intent: Optional[RoutingIntent] = None,
) -> Tuple[Dict[str, Any], str]:
    """
    Prepares a sub-task payload dict with safe inheritance from parent.

    Architecture: Ensures routing hints from PKG are attached to each step.
    This guarantees Organism always receives routing hints, even if PKG
    didn't explicitly set them per-step.

    Args:
        routing_intent: Optional routing intent from PKG to inject into step.
                       Used defensively to ensure routing hints are present.
    """
    raw_task = step.get("task", step)
    step_task = dict(raw_task) if isinstance(raw_task, dict) else {}

    # Ensure task_id exists (stability is good for persistence/telemetry)
    if not step_task.get("task_id") and not step_task.get("id"):
        # prefer task_id field
        step_task["task_id"] = f"{parent_task.task_id}:{index}:{uuid.uuid4().hex[:6]}"

    # Ensure params exists
    params = step_task.setdefault("params", {})

    # Inherit parent params (shallow merge)
    parent_params = dict(parent_task.params or {})

    # CRITICAL: Preserve params.executor from step_task (for JIT agent spawning)
    # CapabilityRegistry.build_step_task_from_subtask() creates params.executor with:
    # - executor.specialization
    # - executor.behaviors (for Behavior Plugin System)
    # - executor.behavior_config (for Behavior Plugin System)
    # This must be preserved for OrganismCore._ensure_agent_handle() to extract behaviors
    step_executor = params.get("executor")
    if not step_executor:
        # If step doesn't have executor, inherit from parent (fallback)
        step_executor = parent_params.get("executor")
    if isinstance(step_executor, dict) and step_executor:
        params["executor"] = dict(step_executor)  # Preserve executor hints

    # Merge routing (child overrides)
    parent_routing = dict(parent_params.get("routing", {}) or {})
    child_routing = dict(params.get("routing", {}) or {})
    params["routing"] = {**parent_routing, **child_routing}

    # Defensive: Inject routing hints from PKG if step doesn't have them
    # This ensures Organism always sees routing hints, even if PKG omitted them
    if routing_intent:
        routing = params.setdefault("routing", {})
        if not routing.get("required_specialization") and routing_intent.specialization:
            routing["required_specialization"] = routing_intent.specialization
        if routing_intent.skills:
            existing_skills = routing.get("skills", {})
            routing["skills"] = {**existing_skills, **(routing_intent.skills or {})}

    # Merge interaction (child overrides)
    parent_interaction = dict(parent_params.get("interaction", {}) or {})
    child_interaction = dict(params.get("interaction", {}) or {})
    params["interaction"] = {**parent_interaction, **child_interaction}

    # Context injection
    params["parent_task_id"] = parent_task.task_id
    params["step_index"] = index
    if cid:
        step_task.setdefault("correlation_id", cid)

    # Default task type if missing
    if "type" not in step_task and "task_type" not in step_task:
        step_task["type"] = TaskType.ACTION.value

    # Target resolution
    organ_hint = (
        step.get("organ_id")
        or params.get("routing", {}).get("target_organ_hint")
        or "organism"
    )

    return step_task, organ_hint


def _aggregate_execution_results(
    parent_task_id: str,
    solution_steps: List[Dict[str, Any]],
    step_results: List[Dict[str, Any]],
    decision_kind: str,
    original_meta: Dict | None = None,
) -> Dict[str, Any]:
    all_succeeded = all(
        r.get("success", False) for r in step_results if r.get("step") is not None
    )
    aggregated = {
        "success": bool(all_succeeded),
        "error": None if all_succeeded else "plan_failed",
        "result": {
            "plan": {
                "parent_task_id": parent_task_id,
                "total_steps": len(solution_steps),
                "completed_steps": len(
                    [r for r in step_results if r.get("step") is not None]
                ),
                "steps": step_results,
            }
        },
        "metadata": {
            "decomposition": True,
            "decision_kind": decision_kind,
        },
        "path": "coordinator_execute",
        "kind": "plan_execution",
    }
    if original_meta:
        aggregated["metadata"].update(original_meta)
    return aggregated


# ---------------------------------------------------------------------------
# Routing decision logic (OCPS + optional PKG)
# ---------------------------------------------------------------------------


async def _compute_routing_decision(
    *,
    task: TaskPayload,
    ctx: TaskContext,
    route_cfg: RouteConfig,
    exec_cfg: ExecutionConfig,
    correlation_id: str | None = None,
    embedding: Optional[List[float]] = None,
) -> Dict[str, Any]:
    t0 = time.perf_counter()

    # 1) Drift + OCPS
    # Derive task_dict from task when needed (for drift score computation)
    task_dict = task.model_dump()
    raw_drift = await _call_compute_drift_score(
        exec_cfg.compute_drift_score,
        task_dict=task_dict,
        text_payload=ctx.eventizer_data or {"text": ctx.description or ""},
        ml_client=exec_cfg.ml_client,
        metrics=exec_cfg.metrics,
    )

    drift_state = route_cfg.ocps_valve.update(raw_drift)
    is_escalated = bool(getattr(drift_state, "is_breached", False))

    decision_kind = (
        DecisionKind.COGNITIVE.value if is_escalated else DecisionKind.FAST_PATH.value
    )

    # 2) PKG Evaluation (Primary Source of Routing Intent)
    # Architecture: PKG is the policy layer that decides WHAT and IN WHAT ORDER.
    # PKG should always be evaluated (not optional) to provide routing hints.
    proto_plan: Dict[str, Any] = {"metadata": {"evaluated": False}}

    if route_cfg.evaluate_pkg_func:
        # PKG evaluation should happen for both FAST_PATH and COGNITIVE paths
        # PKG provides routing hints even for simple tasks
        # ENHANCEMENT: Pass embedding for semantic context hydration
        try:
            proto_plan = await _try_run_pkg_evaluation(
                ctx=ctx,
                cfg=route_cfg,
                intent=None,  # PKG doesn't need pre-computed intent
                raw_drift=raw_drift,
                drift_state=drift_state,
                embedding=embedding,  # Pass embedding for Unified Memory hydration
            )
        except Exception as e:
            logger.debug(f"[Coordinator] PKG evaluation failed: {e}, using fallback")
            # Ensure proto_plan has evaluated=False when PKG fails
            proto_plan = {"metadata": {"evaluated": False}}

    # 3) Extract Routing Intent (PKG-First)
    # Priority: proto_plan > config resolver > minimal fallback
    intent: Optional[RoutingIntent] = None

    # First: Extract from PKG proto_plan (authoritative)
    if proto_plan:
        intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)
        
        # Enrich intent with semantic context from Unified Memory (if available)
        if intent:
            semantic_context = proto_plan.get("semantic_context") or proto_plan.get("metadata", {}).get("semantic_context")
            if semantic_context:
                intent = IntentEnricher.enrich(intent, ctx, semantic_context=semantic_context)
        
        # Validate intent (handles both None and extracted intent)
        validation_errors = IntentValidator.validate(intent, ctx)
        if validation_errors:
            logger.warning(
                f"[Coordinator] Intent validation errors for task {ctx.task_id}: "
                f"{'; '.join(validation_errors)}. Falling back to baseline intent."
            )
            # Reset invalid intent to trigger baseline synthesis fallback
            intent = None

    # Second: Use config-driven resolver if provided (LEGACY - deprecated)
    if not intent and route_cfg.intent_resolver:
        logger.warning(
            f"[Coordinator] Using deprecated intent_resolver for task {ctx.task_id}. "
            "intent_resolver is legacy; PKG should supply routing hints via proto_plan. "
            "Consider migrating to PKG-based routing."
        )
        legacy_intent = route_cfg.intent_resolver(ctx)
        # Wrap legacy intent with provenance metadata
        if legacy_intent:
            legacy_intent.source = IntentSource.LEGACY_RESOLVER
            legacy_intent.confidence = IntentConfidence.LOW
        intent = legacy_intent

    # Third: Coordinator baseline synthesis (perception-based fallback)
    # Uses IntentEnricher to synthesize intent from Eventizer perception
    # This ensures Coordinator is "Never Blind" even if PKG provides no hints
    if not intent:
        intent = IntentEnricher.synthesize_baseline(ctx)
        logger.info(
            f"[Coordinator] Synthesized baseline intent for task {ctx.task_id} from Eventizer perception: "
            f"{intent.specialization} (source={intent.source.value}, confidence={intent.confidence.value})"
        )

    if intent.skills is None:
        intent.skills = {}

    # Determine target organ for routing
    # Architecture: If organ_hint is explicitly set (from PKG), use it.
    # Otherwise, delegate to "organism" and let Organism's router resolve
    # the organ based on specialization. This allows Organism to handle
    # dynamic organ discovery and JIT agent spawning.
    target_organ = intent.organ_hint or "organism"
    
    # Log routing decision for observability
    if intent.specialization and not intent.organ_hint:
        logger.debug(
            f"[Coordinator] Routing task {ctx.task_id} to 'organism' with "
            f"specialization={intent.specialization} (organ_hint not set, "
            "delegating to Organism router for organ resolution)"
        )

    router_latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    # Generate Cognitive Audit Trail (Explainability)
    insight: Optional[IntentInsight] = None
    try:
        insight = SummaryGenerator.generate(
            ctx=ctx,
            proto_plan=proto_plan,
            intent=intent,
            decision_kind=decision_kind,
            raw_drift=raw_drift,
            drift_state=drift_state,
        )
        logger.info(
            f"[Cortex Insight] Task {ctx.task_id}: {insight.summary}"
        )
    except Exception as e:
        logger.debug(
            f"[Coordinator] Failed to generate intent insight (non-fatal): {e}",
            exc_info=True,
        )

    # Prepare payload common with insight metadata
    # Note: pkg_meta is now embedded in proto_plan.metadata, no need to extract separately
    payload_common = _create_payload_common(
        task_id=ctx.task_id,
        decision_kind=decision_kind,
        proto_plan=proto_plan,
        router_latency_ms=router_latency_ms,
        correlation_id=correlation_id,
        ocps_payload={
            "drift": raw_drift,
            "cusum_score": getattr(drift_state, "score", None),
            "breached": getattr(drift_state, "is_breached", False),
            "severity": getattr(drift_state, "severity", None),
        },
    )
    
    # Attach insight to payload_common metadata for auditability
    confidence_score: Optional[float] = None
    if insight:
        payload_common["insight"] = insight.to_dict()
        confidence_score = insight.confidence_score

    if is_escalated:
        # Note: The cognitive service uses cog_type=TASK_PLANNING (hardcoded),
        # so task_type here is primarily for metadata/observability
        task_result = create_cognitive_path_result(
            confidence_score=confidence_score,
            **payload_common,
        )
    else:
        # Extract interaction_mode from TaskPayload (top-level or params.interaction.mode)
        interaction_mode = (
            task.interaction_mode
            or (task.params or {}).get("interaction", {}).get("mode")
            or "coordinator_routed"  # Default fallback
        )
        
        # Use RoutingIntent.to_routing_params() to generate correct routing envelope
        # This correctly handles required_specialization (HARD) vs specialization (SOFT)
        # based on whether intent is explicit (PKG) or synthesized (fallback)
        routing_params = intent.to_routing_params()
        
        task_result = create_fast_path_result(
            target_organ_id=target_organ,
            routing_params=routing_params,
            interaction_mode=interaction_mode,
            processing_time_ms=router_latency_ms,
            **payload_common,
        )

    # Insight is already attached via payload_common metadata
    # optional telemetry hook
    if exec_cfg.record_router_telemetry_func:
        try:
            await exec_cfg.record_router_telemetry_func(
                exec_cfg.graph_task_repo, ctx.task_id, task_result.model_dump()
            )
        except Exception:
            logger.debug(
                "record_router_telemetry_func failed (non-blocking)", exc_info=True
            )

    # Return task_result.model_dump() directly - it contains all routing information:
    # - kind: DecisionKind (decision_kind)
    # - payload: FastPathResult or CognitivePathResult (contains organ_id, routing_params, etc.)
    # - metadata: path, target, exec_time_ms, etc.
    return task_result.model_dump()


async def _try_run_pkg_evaluation(
    *,
    ctx: TaskContext,
    cfg: RouteConfig,
    intent: Optional[RoutingIntent],  # Optional - PKG doesn't need pre-computed intent
    raw_drift: float,
    drift_state: Any,
    embedding: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """
    Evaluate PKG policy to produce proto_plan with routing hints.

    Architecture: PKG is the policy layer that decides WHAT and IN WHAT ORDER.
    PKG should produce proto_plan with steps containing params.routing.required_specialization.

    Note: PKG does NOT need pre-computed intent. PKG evaluates policy independently
    and produces routing hints as part of the plan.
    
    Returns proto_plan with evaluation metadata embedded in proto_plan.metadata.
    """
    proto_plan: Dict[str, Any] = {"metadata": {"evaluated": False}}

    try:
        # Extract Eventizer signals (x1..x6) from TaskContext
        # These signals come from the Eventizer's "System 1" perception:
        # - x1_cache_novelty: Pattern matching cache hit/miss
        # - x2_semantic_drift: Semantic drift detected by Eventizer
        # - x3_multimodal_anomaly: Multimodal anomaly (voice/vision weirdness)
        # - x4_graph_context_drift: Graph context drift
        # - x5_logic_uncertainty: Logic/dependency uncertainty
        # - x6_cost_risk: Cost/risk signal
        eventizer_signals = ctx.signals or {}
        
        pkg_signals: Dict[str, Any] = {
            "ocps_drift": raw_drift,
            "ocps_cusum": getattr(drift_state, "score", None),
            "ocps_breached": getattr(drift_state, "is_breached", False),
            "ocps_severity": getattr(drift_state, "severity", None),
            # Inject Eventizer signals for PKG evaluation
            "x1_cache_novelty": eventizer_signals.get("x1_cache_novelty", 0.0),
            "x2_semantic_drift": eventizer_signals.get("x2_semantic_drift", 0.0),
            "x3_multimodal_anomaly": eventizer_signals.get("x3_multimodal_anomaly", 0.0),
            "x4_graph_context_drift": eventizer_signals.get("x4_graph_context_drift", 0.0),
            "x5_logic_uncertainty": eventizer_signals.get("x5_logic_uncertainty", 0.0),
            "x6_cost_risk": eventizer_signals.get("x6_cost_risk", 0.0),
            # Embedding metadata for Unified Memory System
            "embedding_id": eventizer_signals.get("embedding_id"),
            "vector_dimension": eventizer_signals.get("vector_dimension", 1024),
            "embedding_model": eventizer_signals.get("embedding_model"),
        }

        if cfg.signal_enricher:
            try:
                # Signal enricher can use task context, not pre-computed intent
                extra = await cfg.signal_enricher.compute_contextual_signals(
                    intent, {"task_id": ctx.task_id, "params": ctx.params}
                )
                if isinstance(extra, dict):
                    pkg_signals.update(extra)
            except Exception:
                logger.debug("[Coordinator] SignalEnricher warning", exc_info=True)

        # PKG evaluation: PKG receives task context and produces proto_plan
        # PKG is responsible for policy evaluation and routing hint generation
        # ENHANCEMENT: Pass embedding for semantic context hydration
        pkg_res = await _call_pkg_eval(
            cfg.evaluate_pkg_func,  # type: ignore[arg-type]
            tags=list(ctx.tags),
            signals=pkg_signals,
            context={
                "domain": ctx.domain,
                "type": ctx.task_type,
                "task_id": ctx.task_id,
                "description": ctx.description,
                # Note: We don't pass intent.specialization - PKG decides this
            },
            timeout_s=int(cfg.pkg_timeout_s or DEFAULT_PKG_TIMEOUT_S),
            embedding=embedding,  # Pass embedding for Unified Memory hydration
        )

        proto_plan = pkg_res or {}
        # Embed evaluation metadata directly in proto_plan
        if not proto_plan.get("metadata"):
            proto_plan["metadata"] = {}
        proto_plan["metadata"]["evaluated"] = True
        # version is already at top level of proto_plan, accessible via proto_plan.get("version")

    except Exception as e:
        logger.debug("[Coordinator] PKG evaluation failed: %s", e)
        proto_plan = {"metadata": {"evaluated": False}}

    return proto_plan


# ---------------------------------------------------------------------------
# Semantic Cache (System 0 Fast Path)
# ---------------------------------------------------------------------------


async def _check_semantic_cache(
    ctx: TaskContext,
    embedding: List[float],
    execution_config: ExecutionConfig,
) -> Optional[Dict[str, Any]]:
    """Check Unified Memory for a near-identical task result.
    
    This is a "System 0" optimization that occurs after embedding generation
    but before the expensive route-and-execute call. If a very similar task
    (similarity >= 0.98) was completed in the last 24 hours, return its cached result.
    
    Args:
        ctx: TaskContext containing task metadata.
        embedding: The 1024d embedding vector for the current task.
        execution_config: ExecutionConfig with graph_task_repo and session factory.
    
    Returns:
        Cached task result dictionary if a match is found, None otherwise.
    """
    if not execution_config.graph_task_repo:
        return None
    
    if not execution_config.resolve_session_factory_func:
        return None
    
    try:
        session_factory = execution_config.resolve_session_factory_func()
        async with session_factory() as session:
            # Get snapshot_id for current task (for snapshot-aware semantic caching)
            # Use repository method instead of direct SQL (DAO pattern)
            snapshot_id = None
            try:
                snapshot_id = await execution_config.graph_task_repo.get_task_snapshot_id(
                    session=session,
                    task_id=ctx.task_id,
                )
            except Exception as e:
                logger.debug(f"Could not get snapshot_id for task {ctx.task_id}: {e}")
            
            # Query for similar completed tasks with high precision threshold
            # Pass snapshot_id to ensure snapshot-aware semantic caching (prevents historical bleed)
            cached_task = await execution_config.graph_task_repo.find_similar_task(
                session=session,
                embedding=embedding,
                threshold=0.98,  # High precision for near-exact matches
                limit=1,
                hours_back=24,  # Look back 24 hours
                snapshot_id=snapshot_id,  # Snapshot-aware caching
            )
            
            if cached_task and cached_task.get("result"):
                logger.info(
                    f"[Coordinator] Semantic Cache HIT for task {ctx.task_id} "
                    f"(Source: {cached_task.get('id')}, Similarity: {cached_task.get('similarity', 0.0):.4f})"
                )
                # Return the cached result wrapped in a proper TaskResult structure
                result = cached_task["result"]
                # Ensure it's a dict (it might already be parsed from JSONB)
                if isinstance(result, str):
                    import json
                    result = json.loads(result)
                
                # Return result in expected format (may need to wrap based on your result schema)
                return result
            else:
                logger.debug(
                    f"[Coordinator] Semantic Cache MISS for task {ctx.task_id} "
                    f"(no similar completed tasks found in last 24h)"
                )
                return None
    except Exception as e:
        # Non-fatal: log and continue with normal execution
        logger.warning(
            f"[Coordinator] Semantic cache check failed for task {ctx.task_id}: {e}. "
            "Continuing with normal execution."
        )
        return None


async def _consolidate_result_embedding(
    ctx: TaskContext,
    final_result: Dict[str, Any],
    execution_config: ExecutionConfig,
) -> None:
    """
    Phase 2: Result Consolidation.
    
    Updates the 1024d knowledge graph embedding with the task's outcome.
    This is critical because a task like "Check room status" always has the same
    Intent Embedding, but the Result Embedding changes based on whether the room
    was "Ready" or "Occupied." Consolidation ensures the "Semantic Cache" is
    actually useful for future queries.
    
    This helper runs asynchronously (fire-and-forget). It builds a "Consolidated
    Text Blob" that combines the original task and the outcome, then triggers an
    update to the 1024d embedding via the worker queue.
    
    Architecture:
    - Phase 1 (Intent): Captures what the user *wanted*
    - Phase 2 (Consolidation): Captures what the system *did*
    
    The consolidation ensures that future semantic cache queries can match on
    both intent AND outcome, making the cache more accurate and useful.
    
    Args:
        ctx: TaskContext containing task metadata and description.
        final_result: The final result dictionary from task execution.
        execution_config: ExecutionConfig with coordinator reference for enqueue.
    """
    task_id_str = str(ctx.task_id)
    
    try:
        # Extract the "Meat" of the result
        # We focus on the 'payload' or 'data' to keep the embedding clean
        result_data = final_result.get("payload") or final_result.get("data") or {}
        
        # Build pretty-printed JSON for the consolidated text
        import json
        result_pretty = json.dumps(result_data, indent=2)
        
        # Build the Consolidated Text Blob
        # We combine Intent + Outcome to create a "Unified Memory"
        # This format matches the Python build_task_text() logic for consistency
        consolidated_text = (
            f"TASK_INTENT: {ctx.description or ''}\n"
            f"TASK_TYPE: {ctx.task_type or ''}\n"
            f"EXECUTION_OUTCOME: {result_pretty}"
        )
        
        # Log consolidation preparation (debug level to avoid noise)
        logger.debug(
            f"[Memory] Preparing consolidation for task {task_id_str} "
            f"(result_size={len(consolidated_text)} chars)"
        )
        
        # Use the Layer 1 'Fast Enqueue' logic to update the embedding
        # We don't do this synchronously because the user already has their result.
        # By enqueuing with a specific reason, the worker knows to perform an 'upsert'.
        if execution_config.coordinator:
            success = await execution_config.coordinator._enqueue_task_embedding_now(
                task_id_str,
                reason="consolidation_result"
            )
            
            if success:
                logger.debug(f"[Memory] Consolidation enqueued for task {task_id_str}")
            else:
                # If the queue is full, the Outbox Reliability Layer will catch it later
                logger.warning(
                    f"[Memory] Fast consolidation failed for {task_id_str}; "
                    "relying on Outbox."
                )
        else:
            logger.debug(
                f"[Memory] Coordinator not available for consolidation of task {task_id_str}"
            )
            
    except Exception as e:
        # Non-fatal: consolidation failure should not break execution
        logger.error(
            f"[Memory] Failed to prepare consolidation for {task_id_str}: {e}",
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Input processing (eventizer)
# ---------------------------------------------------------------------------


async def _process_task_input(
    *,
    task: TaskPayload,
    eventizer_helper: Callable[[Any], Any] | None,
    normalize_domain: Callable[[str | None], str | None],
) -> Dict[str, Any]:
    """
    Process task input with Eventizer integration (System 1 perception).
    
    Architecture: Eventizer is the primary signal generator that:
    - Normalizes text (de-obfuscation, unit grounding: "6 PM" -> "18:00")
    - Extracts event tags and attributes for PKG evaluation
    - Generates surprise signals (x1..x6) for SurpriseComputer
    - Handles multimodal context (voice/vision/sensor metadata)
    
    The processed_text from Eventizer becomes the "source of truth" for
    downstream ML models and PKG evaluation, as it has been normalized and
    de-obfuscated.
    """
    # Derive task_dict from task when needed (for eventizer_helper)
    task_dict = task.model_dump()
    
    # 1. Execute Eventizer Helper (The 'Reflex' / System 1)
    eventizer_data: Dict[str, Any] = {}
    if eventizer_helper:
        try:
            res = await _maybe_await(eventizer_helper(task_dict))
            eventizer_data = res or {}
        except Exception:
            logger.debug("Eventizer failed (non-blocking)", exc_info=True)

    # 2. Extract Event Tags and Signals
    event_tags = eventizer_data.get("event_tags", {}) or {}
    tags = set(event_tags.get("event_types", []) or [])
    signals = eventizer_data.get("signals", {}) or {}
    
    # 3. Use the cleaned/normalized text from Eventizer as the "source of truth"
    # This ensures downstream PKG/ML models see:
    # - De-obfuscated text (S.E.C.U.R.I.T.Y -> security)
    # - Grounded units (6 PM -> 18:00, 100 sqft -> 100sqft)
    # - Audio artifacts stripped ([laughter] removed)
    refined_description = (
        eventizer_data.get("processed_text")
        or eventizer_data.get("normalized_text")
        or task.description
        or task_dict.get("description")
        or ""
    )

    return {
        "task_id": task.task_id,
        "task_type": task.type,
        "domain": normalize_domain(task.domain),
        "description": refined_description,  # GROUNDED TEXT (e.g., 6 PM -> 18:00)
        "params": task.params or {},
        "eventizer_data": eventizer_data,
        "eventizer_tags": event_tags,
        "tags": tags,
        "attributes": eventizer_data.get("attributes", {}) or {},
        "confidence": eventizer_data.get("confidence", {}) or {},
        "signals": signals,  # x1..x6 signals passed to SurpriseComputer via PKG
        "pii_redacted": bool(eventizer_data.get("pii_redacted", False)),
        "fact_reads": [],
        "fact_produced": [],
    }


def _create_payload_common(**kwargs):
    """Simple wrapper to standardize metadata output."""
    return kwargs
