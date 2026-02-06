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
import json
import os
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
from seedcore.coordinator.core.enrichment import enrich_task_payload
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
            ("payload", "metadata", "proto_plan"),
        ],
        value_type=dict,
    )


def _proto_plan_has_routing_hints(proto_plan: Dict[str, Any]) -> bool:
    """Check whether PKG proto_plan includes routing hints anywhere."""
    if not isinstance(proto_plan, dict):
        return False

    routing = proto_plan.get("routing")
    if isinstance(routing, dict) and (
        routing.get("required_specialization")
        or routing.get("specialization")
        or routing.get("tools")
    ):
        return True

    steps = proto_plan.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            task_obj = step.get("task") if isinstance(step.get("task"), dict) else {}
            params = task_obj.get("params") if isinstance(task_obj.get("params"), dict) else {}
            step_routing = params.get("routing") if isinstance(params.get("routing"), dict) else {}
            if step_routing.get("required_specialization") or step_routing.get("specialization") or step_routing.get("tools"):
                return True

    return False


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

    # 1.5. TASK ENRICHMENT (Deterministic Coordinator Enrichment)
    # Enrich task with missing operational intent before PKG evaluation.
    # This implements the architectural principle:
    #   API captures reality
    #   Coordinator adds meaning
    #   Cognitive executes intent
    # Enrichment happens after Eventizer processing but before PKG evaluation,
    # ensuring tasks have complete operational intent before routing decisions.
    #
    # Operator control: deterministic task enrichment can be disabled via env.
    # This is useful if you want Coordinator to rely solely on PKG + routing inbox
    # + intent enrichers, without bootstrap heuristics.
    #
    # EXCEPTION: Even when enrichment is enabled, skip enrichment for action tasks
    # with required_specialization. These tasks already have accurate routing
    # information (hard constraint) and should not be mutated by heuristics.
    task_dict = task.model_dump()
    routing = task_dict.get("params", {}).get("routing", {}) if task_dict.get("params") else {}
    has_required_specialization = bool(routing.get("required_specialization"))
    is_action_task = task_dict.get("type") == "action"

    enrichment_enabled = os.getenv("COORDINATOR_TASK_ENRICHMENT_ENABLED", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    
    if not enrichment_enabled:
        logger.info(
            f"[Coordinator] Skipping deterministic task enrichment for {ctx.task_id} "
            "(COORDINATOR_TASK_ENRICHMENT_ENABLED=0)"
        )
        enriched_task_dict = task_dict
    elif is_action_task and has_required_specialization:
        logger.info(
            f"[Coordinator] ⚡ Skipping enrichment for action task {ctx.task_id} "
            f"with required_specialization={routing.get('required_specialization')} - "
            "task already has accurate routing, routing directly to fast path"
        )
        # Skip enrichment - task already has accurate routing information
        enriched_task_dict = task_dict
    else:
        enriched_task_dict = enrich_task_payload(task_dict, ctx)
    
    # Update task object with enriched data (for downstream use)
    task = TaskPayload.model_validate(enriched_task_dict)
    
    # 1.75. CHAT FAST-PATH OPTIMIZATION
    # Chat tasks should be routed directly to the fast organism path with a
    # hard specialization constraint for USER_LIAISON.
    if task.type == TaskType.CHAT.value:
        task_params = task.params or {}
        routing_env = task_params.get("routing") or {}
        if not isinstance(routing_env, dict):
            routing_env = {}
        routing_env["required_specialization"] = Specialization.USER_LIAISON.name
        task_params["routing"] = routing_env
        task.params = task_params
        # Keep mirror fields in sync for downstream convenience
        task.required_specialization = Specialization.USER_LIAISON.name

        interaction_env = task_params.get("interaction") or {}
        interaction_mode = (
            interaction_env.get("mode")
            if isinstance(interaction_env, dict)
            else None
        ) or "coordinator_routed"

        logger.info(
            f"[Coordinator] Chat task {ctx.task_id} detected. "
            "Forcing FAST path with required_specialization=USER_LIAISON."
        )

        result = await _handle_fast_path(
            task=task,
            routing_params={"required_specialization": Specialization.USER_LIAISON.name},
            interaction_mode=interaction_mode,
            target_organ_id="organism",
            config=execution_config,
        )

        final_result = normalize_envelope(
            result, task_id=ctx.task_id, path="coordinator_fast_path"
        )
        if final_result.get("decision_kind") is None:
            final_result["decision_kind"] = DecisionKind.FAST_PATH.value
        return final_result

    pkg_mandatory = _is_pkg_mandatory_action(task)

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

    # PKG-mandatory gate: forbid cognitive planning and require PKG output
    if pkg_mandatory:
        proto_plan = _extract_proto_plan(router_result_payload)
        if proto_plan is None and isinstance(router_result_payload, dict):
            payload_meta = (router_result_payload.get("payload") or {}).get("metadata") or {}
            proto_plan = payload_meta.get("proto_plan") or router_result_payload.get("proto_plan")
        if isinstance(proto_plan, str):
            try:
                proto_plan = json.loads(proto_plan)
            except Exception:
                proto_plan = None
        proto_plan = proto_plan or {}
        if isinstance(router_result_payload, dict):
            logger.debug(
                "[Coordinator] PKG-mandatory debug task_id=%s decision_kind=%s "
                "router_keys=%s payload_keys=%s payload_meta_keys=%s proto_plan_type=%s",
                ctx.task_id,
                decision_kind,
                list(router_result_payload.keys()),
                list((router_result_payload.get("payload") or {}).keys()),
                list(((router_result_payload.get("payload") or {}).get("metadata") or {}).keys()),
                type(proto_plan).__name__,
            )
        logger.debug(
            "[Coordinator] PKG-mandatory proto_plan summary task_id=%s evaluated=%s steps=%s routing=%s",
            ctx.task_id,
            (proto_plan.get("metadata") or {}).get("evaluated"),
            len(proto_plan.get("steps") or []),
            bool(proto_plan.get("routing")),
        )
        pkg_meta = proto_plan.get("metadata", {}) if isinstance(proto_plan, dict) else {}
        pkg_evaluated = bool(pkg_meta.get("evaluated", False))
        pkg_skipped = bool(pkg_meta.get("pkg_skipped", False))
        pkg_empty = _is_pkg_result_empty(proto_plan) if isinstance(proto_plan, dict) else True
        pkg_has_routing = _proto_plan_has_routing_hints(proto_plan) if isinstance(proto_plan, dict) else False

        if decision_kind == DecisionKind.COGNITIVE.value:
            error_msg = (
                "Execution planning without PKG is forbidden for action tasks. "
                "PKG-mandatory gate blocked cognitive planning."
            )
            logger.error("[Coordinator] %s task_id=%s", error_msg, ctx.task_id)
            return make_envelope(
                task_id=ctx.task_id,
                success=False,
                error=error_msg,
                error_type="pkg_mandatory_violation",
                decision_kind=DecisionKind.ERROR.value,
                path="coordinator_pkg_gate",
                meta={"pkg_mandatory": True, "decision_kind": decision_kind},
            )

        if not pkg_evaluated or pkg_skipped or pkg_empty or not pkg_has_routing:
            error_msg = (
                "PKG evaluation required for action task but PKG returned no usable plan."
            )
            logger.error(
                "[Coordinator] %s task_id=%s evaluated=%s skipped=%s empty=%s has_routing=%s",
                error_msg,
                ctx.task_id,
                pkg_evaluated,
                pkg_skipped,
                pkg_empty,
                pkg_has_routing,
            )
            return make_envelope(
                task_id=ctx.task_id,
                success=False,
                error=error_msg,
                error_type="pkg_incomplete",
                decision_kind=DecisionKind.ERROR.value,
                path="coordinator_pkg_gate",
                meta={
                    "pkg_mandatory": True,
                    "evaluated": pkg_evaluated,
                    "pkg_skipped": pkg_skipped,
                    "pkg_empty": pkg_empty,
                    "has_routing": pkg_has_routing,
                },
            )
        # PKG is valid for mandatory action tasks -> finalize fast path decision now.
        decision_kind = DecisionKind.FAST_PATH.value

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
        # Preserve decision_kind from routing decision
        final_result = normalize_envelope(result, task_id=ctx.task_id, path="coordinator_fast_path")
        if final_result.get("decision_kind") is None:
            final_result["decision_kind"] = DecisionKind.FAST_PATH.value
        
        # PHASE 2: RESULT CONSOLIDATION (Asynchronous)
        # Architecture: Gate memory writes for actuator commands
        # ACTION + FAST path tasks are state changes, not knowledge
        # They should not trigger memory consolidation
        should_consolidate = (
            execution_config.enable_consolidation and
            execution_config.coordinator and
            not (task.type == TaskType.ACTION.value and decision_kind == DecisionKind.FAST_PATH.value)
        )
        if final_result and should_consolidate:
            asyncio.create_task(
                _consolidate_result_embedding(ctx, final_result, execution_config)
            )
        elif task.type == TaskType.ACTION.value and decision_kind == DecisionKind.FAST_PATH.value:
            logger.debug(
                f"[Coordinator] Skipping memory consolidation for ACTION+FAST task {ctx.task_id} "
                "(actuator commands are state changes, not knowledge)"
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
        # Preserve decision_kind from routing decision
        final_result = normalize_envelope(result, task_id=ctx.task_id, path="coordinator_cognitive_path")
        if final_result.get("decision_kind") is None:
            final_result["decision_kind"] = DecisionKind.COGNITIVE.value
        
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
        
        # ARCHITECTURAL FIX: Enforce planner contract - System-2 must return machine-binding plan
        # Cognitive planner MUST emit structured DAG (no routing/tool emission)
        planner_valid, planner_errors = _validate_planner_output(plan_res, task)
        
        if not planner_valid:
            error_msg = (
                f"Cognitive planner contract violation for task {task.task_id}. "
                f"Planner must return a structured plan with nodes/edges (no routing/tool emission). "
                f"Validation errors: {', '.join(planner_errors)}. "
                f"System-2 output is non-binding - cannot proceed with execution."
            )
            logger.error(error_msg)
            return make_envelope(
                task_id=task.task_id,
                success=False,
                error=error_msg,
                error_type="planner_contract_violation",
                decision_kind=DecisionKind.ERROR.value,
                path="coordinator_cognitive_path",
                meta={
                    "planner_errors": planner_errors,
                    "retry_recommended": False,
                    "escalate": True,
                }
            )

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


def _has_rich_domain_facts(params: Dict[str, Any]) -> bool:
    """
    Heuristic detector for rich domain facts in action tasks.

    We avoid semantic inference and only look for structural signals:
    - Known domain keys (design, intent, fabricType, etc.)
    - Multiple non-empty non-meta fields
    """
    if not isinstance(params, dict) or not params:
        return False

    rich_keys = {
        "design",
        "intent",
        "fabricType",
        "fabric_type",
        "material",
        "pattern",
        "dimensions",
        "specs",
        "specifications",
        "quantity",
        "color",
        "size",
        "style",
        "blueprint",
        "assembly",
        "recipe",
    }
    if any(params.get(k) not in (None, "", [], {}) for k in rich_keys):
        return True

    meta_keys = {
        "routing",
        "interaction",
        "cognitive",
        "risk",
        "_router",
        "_emission",
        "skills",
        "tools",
        "hints",
        "policy",
        "debug",
        "trace",
        "telemetry",
        "metadata",
    }

    non_empty_fields = 0
    for key, value in params.items():
        if key in meta_keys or key.startswith("_"):
            continue
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and len(value) == 0:
            continue
        non_empty_fields += 1
        if non_empty_fields >= 2:
            return True

    return False


def _is_pkg_mandatory_action(task: TaskPayload) -> bool:
    """
    Structural gate: ACTION tasks with rich domain facts and no executor identity
    must be decomposed by PKG (Cognitive may not plan execution).
    """
    if not task or task.type != TaskType.ACTION.value:
        return False

    params = task.params or {}
    routing = params.get("routing", {}) if isinstance(params, dict) else {}
    has_specialization = bool(
        routing.get("required_specialization") or routing.get("specialization")
    )
    has_emission = "_emission" in params and params.get("_emission") is not None

    return (not has_specialization) and (not has_emission) and _has_rich_domain_facts(params)


def _validate_planner_output(plan_res: Any, task: TaskPayload) -> Tuple[bool, List[str]]:
    """
    Validate that cognitive planner output is machine-binding and structurally complete.
    
    Architecture: System-2 must NEVER return free-text as primary output.
    Planner output must be a structured, executable plan artifact.
    
    Required structure:
    - Must contain nodes (explicit DAG) OR solution_steps with depends_on (implicit DAG)
    - Must contain ≥1 action node
    - Must be JSON-serializable (not free-text)

    Forbidden in Cognitive output:
    - routing / specialization / tools (execution identity belongs to PKG + Coordinator)
    
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    if not isinstance(plan_res, dict):
        errors.append("Planner output must be a dictionary, not free-text")
        return False, errors
    
    # Skip validation if this is an error result (Cognitive Core already validated and rejected)
    if plan_res.get("success") is False or plan_res.get("error"):
        # This is an error result from Cognitive Core, not a planner output to validate
        # The error should have been logged by Cognitive Core
        errors.append(f"Cognitive Core returned error: {plan_res.get('error', 'Unknown error')}")
        return False, errors
    
    # Extract plan structure
    result = plan_res.get("result", {})

    # Detect CognitiveCore error envelope wrapped inside result
    if isinstance(result, dict) and result.get("kind") == DecisionKind.ERROR.value:
        payload = result.get("payload", {}) if isinstance(result.get("payload"), dict) else {}
        err_msg = payload.get("error") or "Cognitive Core returned error"
        errors.append(err_msg)
        return False, errors
    dag = plan_res.get("dag") or result.get("dag")
    edges = plan_res.get("edges") or result.get("edges")
    nodes = plan_res.get("nodes") or result.get("nodes")
    solution_steps = _extract_solution_steps(plan_res)
    
    # Defensive normalization: Ensure solution_steps have required fields if they exist
    if solution_steps and isinstance(solution_steps, list):
        for idx, step in enumerate(solution_steps):
            if isinstance(step, dict):
                # Ensure step has ID
                if "id" not in step:
                    step["id"] = step.get("name") or f"step_{idx}"

                # Ensure depends_on exists (for DAG structure)
                if "depends_on" not in step:
                    step["depends_on"] = []
                elif not isinstance(step["depends_on"], list):
                    step["depends_on"] = [step["depends_on"]]

                # Infer sequential dependencies if missing
                if not step.get("depends_on") and idx > 0:
                    prev_step = solution_steps[idx - 1] if solution_steps else None
                    if prev_step and prev_step.get("id"):
                        step["depends_on"] = [prev_step["id"]]

    # Write normalized solution_steps back to plan_res for validation
    if solution_steps and isinstance(solution_steps, list):
        if "result" not in plan_res:
            plan_res["result"] = {}
        plan_res["result"]["solution_steps"] = solution_steps
        plan_res["solution_steps"] = solution_steps
    
    # Check for explicit DAG structure
    has_explicit_dag = False
    if dag and isinstance(dag, list) and len(dag) > 0:
        has_explicit_dag = True
        node_ids = set()
        for idx, node in enumerate(dag):
            if not isinstance(node, dict):
                errors.append(f"dag[{idx}] must be an object")
                continue
            if "id" not in node:
                errors.append(f"dag[{idx}] missing required 'id' field")
                continue
            node_ids.add(node["id"])
        
        if len(node_ids) == 0:
            errors.append("DAG contains no valid nodes with IDs")
        else:
            # Validate edges reference valid nodes
            if edges and isinstance(edges, list):
                for idx, edge in enumerate(edges):
                    if not isinstance(edge, (list, tuple)) or len(edge) != 2:
                        errors.append(f"edges[{idx}] must be [from_id, to_id]")
                        continue
                    from_id, to_id = edge[0], edge[1]
                    if from_id not in node_ids:
                        errors.append(f"edges[{idx}] references unknown node: {from_id}")
                    if to_id not in node_ids:
                        errors.append(f"edges[{idx}] references unknown node: {to_id}")
    
    # Check for nodes array (alternative explicit format)
    if nodes and isinstance(nodes, list) and len(nodes) > 0:
        has_explicit_dag = True
        node_ids = set()
        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                errors.append(f"nodes[{idx}] must be an object")
                continue
            if "id" not in node:
                errors.append(f"nodes[{idx}] missing required 'id' field")
                continue
            node_ids.add(node["id"])
    
    # Check for implicit DAG in solution_steps
    has_implicit_dag = False
    if solution_steps and len(solution_steps) > 0:
        step_ids = set()
        has_action_nodes = False
        
        for idx, step in enumerate(solution_steps):
            if not isinstance(step, dict):
                errors.append(f"solution_steps[{idx}] must be an object")
                continue
            
            # Extract step ID
            step_id = (
                step.get("id") or
                step.get("task", {}).get("task_id") or
                step.get("task", {}).get("id")
            )
            if step_id:
                step_ids.add(str(step_id))
            
            # Check for action nodes
            step_type = step.get("type") or (step.get("task", {}) or {}).get("type")
            if step_type and step_type != "query":
                has_action_nodes = True
        
        if len(step_ids) > 0:
            has_implicit_dag = True
            if not has_action_nodes:
                errors.append("solution_steps contains no action nodes (only queries)")
    
    # Must have either explicit or implicit DAG
    if not has_explicit_dag and not has_implicit_dag:
        errors.append("Planner output must contain DAG structure (dag/nodes) or solution_steps with depends_on")
    
    # Forbidden: routing/specialization/tools in Cognitive output (execution identity)
    forbidden_keys = {"routing", "specialization", "required_specialization", "tools", "tool_calls"}
    def _has_forbidden_in_step(step_obj: Any) -> bool:
        if not isinstance(step_obj, dict):
            return False
        if any(k in step_obj for k in forbidden_keys):
            return True
        task_obj = step_obj.get("task") if isinstance(step_obj.get("task"), dict) else {}
        params_obj = step_obj.get("params") if isinstance(step_obj.get("params"), dict) else {}
        task_params = task_obj.get("params") if isinstance(task_obj.get("params"), dict) else {}
        for obj in (task_obj, params_obj, task_params):
            if any(k in obj for k in forbidden_keys):
                return True
            if "routing" in obj and isinstance(obj.get("routing"), dict):
                return True
        return False

    # Top-level routing/tool emission is forbidden
    if any(k in plan_res for k in forbidden_keys) or any(k in result for k in forbidden_keys):
        errors.append("Cognitive planner output must not include routing, specialization, or tool selection")

    if solution_steps:
        for idx, step in enumerate(solution_steps):
            if _has_forbidden_in_step(step):
                errors.append(f"solution_steps[{idx}] contains routing/specialization/tools (forbidden)")
                break
    
    # Check for free-text reasoning (should not be primary output)
    # If result contains only text fields without structure, it's invalid
    text_fields = ["thought", "reasoning", "explanation", "analysis"]
    has_only_text = all(
        key in text_fields or (isinstance(val, str) and not val.startswith("{"))
        for key, val in result.items()
        if key not in ["solution_steps", "steps", "dag", "nodes", "edges", "routing"]
    )
    
    if has_only_text and not (has_explicit_dag or has_implicit_dag):
        errors.append("Planner output contains only free-text reasoning, no structured plan")
    
    is_valid = len(errors) == 0
    return is_valid, errors


def _validate_cognitive_dag(plan_res: Any) -> bool:
    """
    Validate that cognitive planner output contains structured DAG.
    
    Architecture: Cognitive planner MUST emit DAG structure for:
    - Conditional tasks (event dependencies)
    - Multi-action tasks (multiple distinct actions)
    
    DAG can be in two formats:
    1. Explicit DAG: {"dag": [...], "edges": [...]}
    2. Implicit DAG: solution_steps with depends_on fields
    
    Returns:
        True if DAG structure is present and valid, False otherwise
    """
    if not isinstance(plan_res, dict):
        return False
    
    # Check for explicit DAG structure
    dag = plan_res.get("dag") or plan_res.get("result", {}).get("dag")
    edges = plan_res.get("edges") or plan_res.get("result", {}).get("edges")
    
    if dag and isinstance(dag, list) and len(dag) > 0:
        # Validate DAG nodes have IDs
        node_ids = set()
        for node in dag:
            if isinstance(node, dict) and "id" in node:
                node_ids.add(node["id"])
        
        if len(node_ids) > 0:
            # Validate edges reference valid nodes (if edges provided)
            if edges and isinstance(edges, list):
                for edge in edges:
                    if isinstance(edge, (list, tuple)) and len(edge) == 2:
                        from_id, to_id = edge[0], edge[1]
                        if from_id not in node_ids or to_id not in node_ids:
                            return False
            return True
    
    # Check for implicit DAG in solution_steps (with depends_on)
    steps = _extract_solution_steps(plan_res)
    if steps and isinstance(steps, list) and len(steps) > 0:
        step_ids = set()
        
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            
            # Extract step ID
            step_id = (
                step.get("id") or
                step.get("task", {}).get("task_id") or
                step.get("task", {}).get("id")
            )
            if step_id:
                step_ids.add(str(step_id))
        
        # If we have steps with IDs, consider it a valid DAG
        # (sequential execution is valid even without explicit depends_on)
        if len(step_ids) > 0:
            return True
    
    # No DAG structure found
    return False


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


def _convert_eventizer_signals_to_surprise_signals(
    ctx: TaskContext,
    drift_state: Any,
    raw_drift: float,
    ocps_valve: Any,
) -> Dict[str, Any]:
    """
    Convert Eventizer signals (x1..x6) to SurpriseSignals format for SurpriseComputer.
    
    Architecture: Eventizer produces signals in EventSignals format (x1_cache_novelty, etc.),
    but SurpriseComputer expects SurpriseSignals format (mw_hit, ocps dict, etc.).
    This function bridges the gap.
    
    Args:
        ctx: TaskContext containing Eventizer signals
        drift_state: OCPS valve drift state
        raw_drift: Raw drift score
        ocps_valve: OCPS valve instance (for threshold values)
    
    Returns:
        Dict in SurpriseSignals format for SurpriseComputer.compute()
    """
    signals = ctx.signals or {}
    eventizer_data = ctx.eventizer_data or {}
    
    # Extract event_tags if available (for x6 semantic urgency)
    event_tags = eventizer_data.get("event_tags") or ctx.eventizer_tags or {}
    
    # Convert Eventizer signal names to SurpriseSignals format
    # x1_cache_novelty -> mw_hit (inverted: 1.0 - x1)
    x1_cache_novelty = signals.get("x1_cache_novelty", 0.0)
    mw_hit = 1.0 - float(x1_cache_novelty) if isinstance(x1_cache_novelty, (int, float)) else None
    
    # x2_semantic_drift -> ocps dict (OCPS state from valve)
    ocps_dict = {
        "S_t": getattr(drift_state, "score", 0.0),
        "h": getattr(ocps_valve, "h", 2.5),
        "h_clr": getattr(ocps_valve, "h", 2.5) * 0.5,
        "flag_on": getattr(drift_state, "is_breached", False),
        "drift_flag": getattr(drift_state, "is_breached", False),
        "drift": raw_drift,
    }
    
    # x3_multimodal_anomaly -> ood_dist
    x3_multimodal_anomaly = signals.get("x3_multimodal_anomaly") or signals.get("x3_ood_novelty")
    ood_dist = float(x3_multimodal_anomaly) * 10.0 if isinstance(x3_multimodal_anomaly, (int, float)) else None
    
    # x4_graph_context_drift -> graph_delta, mu_delta
    x4_graph_context_drift = signals.get("x4_graph_context_drift") or signals.get("x4_graph_novelty")
    graph_delta = float(x4_graph_context_drift) if isinstance(x4_graph_context_drift, (int, float)) else None
    mu_delta = 1.0  # Default expected delta (can be enhanced with historical data)
    
    # x5_logic_uncertainty -> dep_probs (convert single value to probability distribution)
    # High uncertainty means uniform distribution (high entropy)
    x5_logic_uncertainty = signals.get("x5_logic_uncertainty") or signals.get("x5_dep_uncertainty")
    if isinstance(x5_logic_uncertainty, (int, float)):
        # Convert uncertainty score to probability distribution
        # High uncertainty (near 1.0) -> uniform distribution (high entropy)
        # Low uncertainty (near 0.0) -> peaked distribution (low entropy)
        uncertainty = float(x5_logic_uncertainty)
        # Create a simple 2-element distribution: [confidence, uncertainty]
        # This approximates dependency uncertainty
        dep_probs = [1.0 - uncertainty, uncertainty]
    else:
        dep_probs = None
    
    # x6_cost_risk -> est_runtime, SLO, kappa, criticality, event_tags
    x6_cost_risk = signals.get("x6_cost_risk", 0.0)
    criticality = float(x6_cost_risk) if isinstance(x6_cost_risk, (int, float)) else None
    
    # Build SurpriseSignals dict
    surprise_signals = {
        "mw_hit": mw_hit,
        "ocps": ocps_dict,
        "ood_dist": ood_dist,
        "ood_to01": None,  # Can be provided by signal_enricher if available
        "graph_delta": graph_delta,
        "mu_delta": mu_delta,
        "dep_probs": dep_probs,
        "est_runtime": None,  # Can be enriched by signal_enricher
        "SLO": None,  # Can be enriched by signal_enricher
        "kappa": None,  # Can be enriched by signal_enricher
        "criticality": criticality,
        "event_tags": event_tags,  # For semantic urgency (x6)
    }
    
    return surprise_signals


def _is_pkg_result_empty(proto_plan: Dict[str, Any]) -> bool:
    """
    Detect if PKG evaluation returned empty/unknown results.
    
    Architecture: If PKG was evaluated but returned no subtasks, no rules,
    and no routing hints, this indicates uncertainty - PKG doesn't know
    what to do with this task. Such tasks should route to cognitive path
    for deeper analysis.
    
    Args:
        proto_plan: PKG evaluation result
    
    Returns:
        True if PKG result is empty (no subtasks, no rules, no routing hints)
    """
    if not proto_plan:
        return False
    
    # Check if PKG was actually evaluated (not skipped)
    metadata = proto_plan.get("metadata", {})
    if not metadata.get("evaluated", False):
        return False  # PKG wasn't evaluated, so can't be "empty"
    
    # Check for empty subtasks/steps
    subtasks = proto_plan.get("subtasks", [])
    steps = proto_plan.get("steps", [])
    if (subtasks and len(subtasks) > 0) or (steps and len(steps) > 0):
        return False  # Has subtasks/steps, not empty
    
    # Check for empty rules
    rules = proto_plan.get("rules", [])
    if rules and len(rules) > 0:
        return False  # Has rules, not empty
    
    # Check for empty DAG
    dag = proto_plan.get("dag", [])
    if dag and len(dag) > 0:
        return False  # Has DAG, not empty
    
    # Check if routing hints exist (top-level or in steps)
    routing = proto_plan.get("routing")
    if routing and isinstance(routing, dict):
        # Has top-level routing hints
        if routing.get("specialization") or routing.get("required_specialization"):
            return False
    
    # Check steps for routing hints
    all_steps = steps or subtasks or []
    for step in all_steps:
        task = step.get("task", step) if isinstance(step, dict) else {}
        if isinstance(task, dict):
            step_routing = task.get("params", {}).get("routing", {})
            if step_routing.get("specialization") or step_routing.get("required_specialization"):
                return False  # Has routing hints in steps
    
    # PKG was evaluated but returned completely empty - this is uncertainty
    return True


def _has_conditional_trigger(description: str, params: Dict[str, Any]) -> bool:
    """
    Detect if task has conditional triggers (event dependencies, temporal conditions).
    
    Architecture: Conditional triggers mandate System-2 (cognitive) planning.
    These patterns indicate event-driven or temporal dependencies that require
    explicit DAG structure, not reflex execution.
    
    Conditional indicators:
    - "following X", "after X", "when X", "once X", "if X"
    - Event references: "noise", "sound", "motion", "door", "sensor"
    - Temporal dependencies: "then", "after that", "subsequently"
    
    Returns:
        True if task has conditional triggers, False otherwise
    """
    if not description:
        return False
    
    desc_lower = description.lower()
    
    import re
    
    # Conditional trigger patterns (event dependencies)
    CONDITIONAL_PATTERNS = [
        r'\bfollowing\s+.*?\b',  # "following noise from the door"
        r'\bafter\s+.*?\b(?!\s+(?:the|a|an|this|that))',  # "after X" but not "after the door"
        r'\bwhen\s+.*?\b',  # "when X happens"
        r'\bonce\s+.*?\b',  # "once X occurs"
        r'\bif\s+.*?\b',  # "if X happens"
        r'\bupon\s+.*?\b',  # "upon X"
        r'\btriggered\s+by\b',  # "triggered by X"
        r'\bwait\s+for\b',  # "wait for X"
        r'\bdetect\s+.*?\s+then\b',  # "detect X then Y"
    ]
    
    for pattern in CONDITIONAL_PATTERNS:
        if re.search(pattern, desc_lower):
            return True
    
    # Event/sensor keywords that suggest conditional behavior
    EVENT_KEYWORDS = [
        "noise", "sound", "motion", "movement", "door", "sensor", "detection",
        "alert", "alarm", "notification", "event", "trigger", "signal"
    ]
    
    # Check if description contains event keywords AND action verbs
    # This suggests "do X when Y happens" pattern
    has_event_keyword = any(re.search(rf'\b{kw}\b', desc_lower) for kw in EVENT_KEYWORDS)
    action_verbs = [
        "set", "turn", "change", "adjust", "open", "close", "lock", "unlock",
        "start", "stop", "enable", "disable", "activate", "deactivate"
    ]
    has_action_verb = any(re.search(rf'\b{verb}\b', desc_lower) for verb in action_verbs)
    
    if has_event_keyword and has_action_verb:
        # Likely conditional: "set temperature following noise"
        return True
    
    return False


def _has_multiple_actions(description: str, params: Dict[str, Any]) -> bool:
    """
    Detect if task has multiple distinct actions (not just multi-step).
    
    Architecture: Multiple actions mandate System-2 (cognitive) planning.
    This is a HARD gate - enrichment cannot override this.
    
    Multi-action indicators:
    - Multiple action verbs with different targets
    - Multiple tool calls already extracted
    - Comma-separated actions with "and"
    
    Returns:
        True if task has multiple actions, False otherwise
    """
    if not description:
        return False
    
    desc_lower = description.lower()
    
    import re
    
    # Check for multiple tool calls (already extracted)
    tool_calls = params.get("tool_calls", []) if params else []
    if len(tool_calls) > 1:
        return True
    
    # Check for multiple distinct action verbs with different targets
    # Pattern: "verb1 X and verb2 Y" (not "verb X and Y")
    action_verb_patterns = [
        (r'\b(set|turn|change|adjust)\s+.*?\s+and\s+(set|turn|change|adjust)\s+', 2),
        (r'\b(open|close|lock|unlock)\s+.*?\s+and\s+(open|close|lock|unlock)\s+', 2),
        (r'\b(start|stop|enable|disable)\s+.*?\s+and\s+(start|stop|enable|disable)\s+', 2),
    ]
    
    for pattern, min_count in action_verb_patterns:
        matches = re.findall(pattern, desc_lower)
        if len(matches) >= min_count:
            return True
    
    # Check for comma-separated actions with "and"
    # Pattern: "do X, and do Y" or "do X and do Y"
    comma_and_pattern = r',\s*(?:and|then)\s+\w+\s+'
    if re.search(comma_and_pattern, desc_lower):
        # Verify it's actually multiple actions, not just "X and Y" (single action with two objects)
        action_verbs = [
            "set", "turn", "change", "adjust", "open", "close", "lock", "unlock",
            "start", "stop", "enable", "disable", "activate", "deactivate"
        ]
        action_count = sum(1 for verb in action_verbs if re.search(rf'\b{verb}\b', desc_lower))
        if action_count > 1:
            return True
    
    return False


def _requires_planning(description: str, params: Dict[str, Any]) -> bool:
    """
    Detect if task requires planning (multi-step/complex).
    
    Architecture: This function must use the SAME canonical text that enrichment sees.
    Use Eventizer refined text (canonical_description) to ensure consistency.
    
    Multi-step indicators:
    - Conjunction words (and, then, also, plus, after)
    - Multiple tool calls already extracted
    - Multiple action verbs in description
    - Complex descriptions with multiple clauses
    
    Returns:
        True if task requires planning, False if single-action
    """
    if not description:
        return False
    
    # Use canonical description (already refined by Eventizer)
    # This ensures _requires_planning sees the same text as enrichment
    desc_lower = description.lower()
    
    # Check for conjunction words (multi-step indicators)
    CONJUNCTION_PATTERNS = [
        r'\b(and|then|also|plus|after|before|next|followed by)\b',
        r'\b(, and|, then|, also)\b',  # Comma-separated actions
        r'\b(set|turn|change|adjust).*?(and|then|also).*?(set|turn|change|adjust)',  # Multiple actions
    ]
    
    import re
    for pattern in CONJUNCTION_PATTERNS:
        if re.search(pattern, desc_lower):
            return True
    
    # Check for multiple tool calls (already extracted)
    tool_calls = params.get("tool_calls", []) if params else []
    if len(tool_calls) > 1:
        return True
    
    # Check for multiple action verbs (heuristic)
    action_verbs = [
        "set", "turn", "change", "adjust", "open", "close", "lock", "unlock",
        "start", "stop", "enable", "disable", "activate", "deactivate",
        "schedule", "book", "reserve", "cancel", "send", "deliver", "notify"
    ]
    action_count = sum(1 for verb in action_verbs if re.search(rf'\b{verb}\b', desc_lower))
    if action_count > 1:
        return True
    
    # Check for multiple numeric values (multiple settings)
    numeric_values = re.findall(r'\d+(?:\.\d+)?', description)
    if len(numeric_values) > 1:
        # Multiple numeric values might indicate multiple actions
        # But be careful - "72 degrees" is one value, not multiple actions
        # Only flag if we also have conjunction words
        if any(re.search(pattern, desc_lower) for pattern in CONJUNCTION_PATTERNS[:2]):
            return True
    
    return False


def _is_extremely_simple_query_precheck(ctx: TaskContext) -> bool:
    """
    Fast pre-check to detect extremely simple queries BEFORE expensive operations.
    
    This is a lightweight check that can be used to skip:
    - Drift calculation (~135ms)
    - Signal enrichment (~50-60ms)
    - PKG evaluation (~9ms)
    
    Returns:
        True if query is extremely simple and can skip expensive operations
    """
    # Simple task types
    SIMPLE_TASK_TYPES = {"query", "health_check", "maintenance"}
    task_type = (ctx.task_type or "").lower()
    if task_type not in SIMPLE_TASK_TYPES:
        return False
    
    # Very short queries (1-3 chars) are always trivial
    description = (ctx.description or "").strip().lower()
    if len(description) <= 3:
        return len(ctx.tags) <= 2  # Allow if minimal tags
    
    # Check against known simple patterns
    EXTREMELY_SIMPLE_PATTERNS = {
        "hello", "hi", "hey", "he", "ha", "ho", "test", "ping", "pong", 
        "status", "health", "how are you", "how are u", "how r u",
        "what", "who", "when", "where", "why", "ok", "okay", "yes", "no",
        "thanks", "thank you", "ty", "bye", "goodbye"
    }
    
    if description in EXTREMELY_SIMPLE_PATTERNS:
        return len(ctx.tags) <= 2  # Allow if minimal tags
    
    return False


def _is_extremely_simple_task(
    ctx: TaskContext,
    raw_drift: float,
    drift_state: Any,
) -> bool:
    """
    Detect extremely simple tasks that can skip PKG evaluation.
    
    Architecture: PKG should be evaluated for device ACTION tasks because the policy gate matters.
    Only allow skipping for truly trivial queries: greetings, health checks, ping.
    
    Criteria for simple tasks (ALL must be true):
    1. Simple task types ONLY: query, health_check (NOT action)
    2. Extremely simple patterns: greetings, ping, health checks
    3. Very short descriptions (≤ 3 chars) OR known simple patterns
    4. No or very few tags - minimal eventizer complexity
    5. All signals near zero - no anomalies or special conditions
    6. OCPS not breached - no drift escalation
    
    Returns:
        True if task is simple enough to skip PKG evaluation
    """
    # Higher threshold for extremely simple queries (allows skipping even with moderate drift)
    SIMPLE_QUERY_DRIFT_THRESHOLD = float(os.getenv("PKG_SKIP_SIMPLE_QUERY_DRIFT_THRESHOLD", "0.3"))
    
    # Simple task types that rarely need PKG routing hints
    # NOTE: ACTION is NOT in this list - device ACTION should almost always be PKG-evaluated
    SIMPLE_TASK_TYPES = {"query", "health_check", "maintenance"}
    
    # Extremely simple query patterns (common greetings/simple interactions)
    # These are so trivial that drift score may be unreliable
    # Includes very short queries (1-2 chars) and common greetings
    EXTREMELY_SIMPLE_PATTERNS = {
        "hello", "hi", "hey", "he", "ha", "ho", "test", "ping", "pong", 
        "status", "health", "how are you", "how are u", "how r u",
        "what", "who", "when", "where", "why", "ok", "okay", "yes", "no",
        "thanks", "thank you", "ty", "bye", "goodbye"
    }
    
    # Check 1: Simple task type ONLY (ACTION must always be PKG-evaluated)
    task_type = (ctx.task_type or "").lower()
    if task_type not in SIMPLE_TASK_TYPES:
        # ACTION tasks should almost always be PKG-evaluated because policy gate matters
        return False
    
    # Check 2: Short description (simple queries are typically brief)
    description = (ctx.description or "").strip().lower()
    if len(description) > 200:  # Long descriptions may need policy evaluation
        return False
    
    # Check 3: Extremely simple queries can skip regardless of drift
    # This handles cases where drift detector sees "hello" as novel
    # but the query is so trivial that PKG adds no value
    # Also handles very short queries (1-3 chars) which are always trivial
    is_extremely_simple_pattern = description in EXTREMELY_SIMPLE_PATTERNS
    is_very_short = len(description) <= 3  # Single/double char queries like "he", "hi"
    
    if not (is_extremely_simple_pattern or is_very_short):
        # Not a trivial pattern - require PKG evaluation
        return False
    
    # Check 4: No or very few tags (simple tasks have minimal eventizer complexity)
    if len(ctx.tags) > 2:
        return False
    
    # Check 5: All signals near zero (no anomalies or special conditions)
    signals = ctx.signals or {}
    signal_values = [
        (k, v) for k, v in signals.items()
        if isinstance(v, (int, float)) and abs(v) > 0.01
    ]
    if len(signal_values) > 0:  # Any non-zero signal suggests complexity
        return False
    
    # Check 6: OCPS not breached (no drift escalation)
    if hasattr(drift_state, "is_breached") and drift_state.is_breached:
        return False
    
    # Allow skipping even with moderate drift for extremely simple queries
    if raw_drift < SIMPLE_QUERY_DRIFT_THRESHOLD:
        return True
    
    return False


def _get_intent_authority(task: TaskPayload) -> str:
    """Extracts and normalizes the authority level from enrichment metadata."""
    cog = task.params.get("cognitive", {}) if task.params else {}
    meta = cog.get("metadata", {}) or {}
    intent = meta.get("intent_class", {}) or {}
    auth = intent.get("authority", "LOW")
    return auth if auth in ("HIGH", "MEDIUM", "LOW") else "LOW"


async def _process_drift_signals(
    ctx: TaskContext,
    task: TaskPayload,
    exec_cfg: ExecutionConfig,
    route_cfg: RouteConfig,
    is_simple: bool,
) -> Tuple[float, Any]:
    """
    Process drift signals and update OCPS valve.
    
    Returns:
        Tuple of (raw_drift, drift_state)
    """
    if is_simple:
        raw_drift = 0.0
        desc_preview = ctx.description[:20] if ctx.description else ""
        logger.debug(
            f"[Coordinator] Using fallback drift=0.0 for simple query {ctx.task_id}: "
            f"description='{desc_preview}...'"
        )
    else:
        raw_drift = await _call_compute_drift_score(
            exec_cfg.compute_drift_score,
            task_dict=task.model_dump(),
            text_payload=ctx.eventizer_data or {"text": ctx.description or ""},
            ml_client=exec_cfg.ml_client,
            metrics=exec_cfg.metrics,
        )
    
    drift_state = route_cfg.ocps_valve.update(raw_drift)
    return raw_drift, drift_state


async def _evaluate_surprise_signals(
    ctx: TaskContext,
    task: TaskPayload,
    route_cfg: RouteConfig,
    drift_state: Any,
    raw_drift: float,
    is_simple: bool,
    requires_planning: bool,
) -> Dict[str, Any]:
    """
    Evaluate surprise signals and compute surprise score.
    
    Returns:
        Dict with keys: is_escalated, score, result
    """
    if not route_cfg.surprise_computer:
        return {"is_escalated": False, "score": 0.0, "result": None}
    
    auth = _get_intent_authority(task)
    signals = _convert_eventizer_signals_to_surprise_signals(
        ctx=ctx,
        drift_state=drift_state,
        raw_drift=raw_drift,
        ocps_valve=route_cfg.ocps_valve,
    )
    
    # Multiplier Logic: Enhance x5 logic uncertainty based on authority/complexity
    x5 = float(ctx.signals.get("x5_logic_uncertainty", 0.0) if ctx.signals else 0.0)
    if auth == "LOW":
        x5 = max(x5, 0.3)  # Minimum uncertainty for LOW authority
    if requires_planning:
        x5 = max(x5, 0.5)  # Multi-action increases uncertainty
    
    # Update x5 in signals for surprise computation
    if ctx.signals:
        ctx.signals["x5_logic_uncertainty"] = x5
    
    # Update dep_probs in surprise_signals with enhanced uncertainty
    if x5 > 0.0:
        dep_probs = [1.0 - x5, x5]
        signals["dep_probs"] = dep_probs
    
    # Enrich signals with signal_enricher if available (adds runtime/SLO/kappa)
    if route_cfg.signal_enricher and not is_simple:
        try:
            extra_signals = await route_cfg.signal_enricher.compute_contextual_signals(
                None, {"task_id": ctx.task_id, "params": ctx.params}
            )
            if isinstance(extra_signals, dict):
                signals.update(extra_signals)
        except Exception:
            logger.debug("[Coordinator] SignalEnricher enrichment failed (non-fatal)", exc_info=True)
    
    try:
        res = route_cfg.surprise_computer.compute(signals)
        is_esc = res.get("decision_kind") in (
            DecisionKind.COGNITIVE.value,
            DecisionKind.ESCALATED.value,
        )
        score = res.get("S", 0.0)
        
        logger.debug(
            f"[Coordinator] Surprise score for task {ctx.task_id}: S={score:.3f}, "
            f"decision={res.get('decision_kind')}, x5_uncertainty={x5:.3f}, "
            f"authority={auth}, requires_planning={requires_planning}"
        )
        
        return {"is_escalated": is_esc, "score": score, "result": res}
    except Exception as e:
        logger.debug(
            f"[Coordinator] SurpriseComputer computation failed (non-fatal): {e}",
            exc_info=True,
        )
        return {"is_escalated": False, "score": 0.0, "result": None}


async def _evaluate_policy_layer(
    ctx: TaskContext,
    task: TaskPayload,
    route_cfg: RouteConfig,
    raw_drift: float,
    drift_state: Any,
    embedding: Optional[List[float]],
    is_simple: bool,
    requires_planning: bool,
    *,
    pkg_mandatory: bool = False,
) -> Tuple[Dict[str, Any], bool]:
    """
    Evaluate PKG policy layer to produce proto_plan.
    
    Returns:
        Tuple of (proto_plan, is_pkg_escalated)
    """
    if (is_simple or _is_extremely_simple_task(ctx, raw_drift, drift_state)) and not pkg_mandatory:
        return {"metadata": {"evaluated": False, "pkg_skipped": True}}, False
    
    try:
        proto_plan = await _try_run_pkg_evaluation(
            ctx=ctx,
            cfg=route_cfg,
            raw_drift=raw_drift,
            drift_state=drift_state,
            embedding=embedding,
        )
        
        # Detect Empty PKG (Unknown Task)
        is_empty = _is_pkg_result_empty(proto_plan)
        
        # PKG is only "escalated" if it's empty AND we lack authority/grounding
        auth = _get_intent_authority(task)
        is_pkg_escalated = is_empty and not (
            auth in ("HIGH", "MEDIUM") and not requires_planning
        )
        
        return proto_plan, is_pkg_escalated
    except Exception as e:
        logger.debug(f"[Coordinator] PKG evaluation failed: {e}, using fallback")
        return {"metadata": {"evaluated": False}}, False


def _determine_decision_kind(
    task: TaskPayload,
    task_id: str,
    enrichment_auth: str,
    requires_planning: bool,
    has_conditions: bool,
    has_multiple_actions: bool,
    is_escalated_ocps: bool,
    is_escalated_surprise: bool,
    is_pkg_escalated: bool,
    *,
    pkg_mandatory: bool = False,
) -> str:
    """
    Determine the final routing decision kind based on all escalation signals.
    
    Architecture: Monotonic escalation - any escalation signal routes to cognitive.
    LOW authority cannot force FAST path.
    
    CRITICAL: Conditional OR multi-action tasks are HARD cognitive gates.
    Enrichment (System-1) cannot override System-2 requirements.
    
    CRITICAL: Action tasks with required_specialization are HARD fast-path gates.
    These tasks have explicit routing requirements and must route to fast path
    (unless blocked by conditional triggers or multiple actions).
    """
    # ARCHITECTURAL FIX: PKG-mandatory gate (no cognitive planning)
    # Action tasks with rich domain facts and no executor identity must be handled by PKG.
    # Decision is finalized only after PKG validation in execute_task.
    if pkg_mandatory:
        logger.info(
            f"[Coordinator] PKG-mandatory gate enforced for task {task_id}: "
            "action task with rich domain facts and no routing specialization. "
            "Deferring fast-path decision until PKG validation completes."
        )
        return "PKG_PENDING"

    # ARCHITECTURAL FIX: Hard fast-path gate for action tasks with required_specialization
    # These tasks have explicit routing requirements and should bypass enrichment/escalation
    # EXCEPT: Still respect hard cognitive gates (conditional triggers, multiple actions)
    routing = task.params.get("routing", {}) if task.params else {}
    has_required_specialization = bool(
        routing.get("required_specialization") or routing.get("specialization")
    )
    is_action_task = task.type == "action"
    
    if is_action_task and has_required_specialization:
        # Still respect hard cognitive gates
        if has_conditions or has_multiple_actions:
            logger.info(
                f"[Coordinator] Hard cognitive gate overrides fast-path for task {task_id}: "
                f"has_conditions={has_conditions}, has_multiple_actions={has_multiple_actions}. "
                f"Required_specialization cannot override System-2 requirement."
            )
            return DecisionKind.COGNITIVE.value
        
        # Action task with required_specialization -> fast path (hard constraint)
        logger.info(
            f"[Coordinator] Hard fast-path gate enforced for task {task_id}: "
            f"type=action, required_specialization={routing.get('required_specialization')}. "
            f"Routing directly to fast path, bypassing escalation signals."
        )
        return DecisionKind.FAST_PATH.value
    
    # ARCHITECTURAL FIX: Hard cognitive gate - non-negotiable
    # Conditional triggers or multiple actions MUST route to cognitive path
    # This cannot be overridden by enrichment, regardless of authority level
    if has_conditions or has_multiple_actions:
        logger.info(
            f"[Coordinator] Hard cognitive gate enforced for task {task_id}: "
            f"has_conditions={has_conditions}, has_multiple_actions={has_multiple_actions}. "
            f"Enrichment cannot override System-2 requirement."
        )
        return DecisionKind.COGNITIVE.value
    
    # Check enrichment decision (only if not blocked by hard gate)
    existing_cognitive = task.params.get("cognitive", {}) if task.params else {}
    enrichment_decision_kind = existing_cognitive.get("decision_kind")

    # Respect explicit caller cognitive intent (TaskPayload v2.5+ cognitive envelope).
    # If the caller requests planning (task_planning / planner), we must take the
    # cognitive path unless a hard fast-path gate already returned above.
    caller_requests_planning = (
        existing_cognitive.get("cog_type") == "task_planning"
        or existing_cognitive.get("decision_kind") in ("planner", "cognitive")
    )
    if caller_requests_planning:
        logger.info(
            f"[Coordinator] Caller requested planning for task {task_id} via params.cognitive "
            f"(cog_type={existing_cognitive.get('cog_type')}, "
            f"decision_kind={existing_cognitive.get('decision_kind')}) - routing to cognitive path"
        )
        return DecisionKind.COGNITIVE.value
    
    # If enrichment set FAST path, check if we can preserve it
    if enrichment_decision_kind == DecisionKind.FAST_PATH.value:
        if requires_planning:
            # Task is multi-step/complex - override FAST path to cognitive
            logger.info(
                f"[Coordinator] Overriding enrichment FAST path for task {task_id}: "
                f"task requires planning (multi-step/complex). Routing to cognitive path."
            )
            return DecisionKind.COGNITIVE.value
        elif enrichment_auth == "LOW":
            # LOW authority cannot force FAST path - defer to escalation logic
            logger.info(
                f"[Coordinator] Enrichment set FAST path with LOW authority for task {task_id}. "
                f"LOW authority cannot force FAST - deferring to escalation logic."
            )
            # Fall through to escalation check
        elif enrichment_auth in ("HIGH", "MEDIUM") and not (
            is_escalated_ocps or is_escalated_surprise or is_pkg_escalated
        ):
            # MEDIUM+ authority and no escalation - preserve FAST path
            logger.info(
                f"[Coordinator] Preserving enrichment FAST path decision for task {task_id} "
                f"(authority={enrichment_auth}, enrichment set decision_kind=fast)"
            )
            return DecisionKind.FAST_PATH.value
        else:
            # Authority is MEDIUM+ but escalation occurred - override
            logger.info(
                f"[Coordinator] Overriding enrichment FAST path for task {task_id}: "
                f"escalation occurred (OCPS={is_escalated_ocps}, surprise={is_escalated_surprise}, "
                f"PKG={is_pkg_escalated})"
            )
            return DecisionKind.COGNITIVE.value
    
    # Check for escalation signals (monotonic escalation)
    is_escalated = is_escalated_ocps or is_escalated_surprise or is_pkg_escalated
    
    if is_escalated or requires_planning:
        return DecisionKind.COGNITIVE.value
    
    # Final override: LOW authority cannot force FAST
    if enrichment_auth == "LOW":
        logger.info(
            f"[Coordinator] Overriding LOW authority FAST path for task {task_id}. "
            f"LOW authority cannot force FAST - routing to cognitive path."
        )
        return DecisionKind.COGNITIVE.value
    
    # Default to FAST path
    return DecisionKind.FAST_PATH.value


def _resolve_routing_intent(
    ctx: TaskContext,
    proto_plan: Dict[str, Any],
    task: TaskPayload,
    route_cfg: RouteConfig,
    *,
    is_cognitive_path: bool = False,
) -> RoutingIntent:
    """
    Resolve routing intent from PKG proto_plan, enrichment, or baseline synthesis.
    
    Architecture: Coordinator is a thin routing layer. It extracts routing hints from:
    1. PKG proto_plan (authoritative - contains DAG structure and routing hints)
    2. Enrichment routing (fallback - System-1 perception, ONLY for FAST path)
    3. Baseline synthesis (last resort - structurally neutral, ONLY for FAST path)
    
    CRITICAL: After System-2 (cognitive path) planning, enrichment fallback is FORBIDDEN.
    System-2 output must be machine-binding - if planner fails, execution fails.
    
    PKG's job: Policy validation, safety checks, tool authorization, domain constraints.
    PKG accepts cognitive DAGs as first-class input and validates them.
    
    Coordinator's job: Extract routing hints, bind routing envelopes, enforce deny-by-default.
    Coordinator does NOT: Decide intent, infer conditions, count verbs, parse semantics.
    
    Priority: proto_plan > enrichment routing (FAST only) > config resolver > minimal fallback (FAST only)
    """
    intent: Optional[RoutingIntent] = None

    # 0) HARD PRIORITY: Task instance routing inbox (TaskPayload v2.5+)
    # Per docs/references/task-payload-capabilities.md:
    # - params.routing.required_specialization is a HARD constraint and must be honored.
    # - Instance-level routing overrides all defaults (type-level, PKG suggestions, memory).
    existing_routing = task.params.get("routing", {}) if task.params else {}
    required_spec = existing_routing.get("required_specialization")
    if required_spec:
        intent = RoutingIntent(
            specialization=str(required_spec),
            skills=existing_routing.get("skills", {}) or {},
            source=IntentSource.TASK_PAYLOAD_ROUTING,  # hard constraint from caller
            confidence=IntentConfidence.HIGH,
            metadata={"hard_constraint": "required_specialization"},
        )
        logger.info(
            f"[Coordinator] Using TaskPayload routing hard constraint for task {ctx.task_id}: "
            f"required_specialization={required_spec} (source={intent.source.value})"
        )
        return intent
    
    # First: Extract from PKG proto_plan (authoritative)
    if proto_plan:
        intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)
        
        # Enrich intent with semantic context from Unified Memory (if available)
        if intent:
            semantic_context = (
                proto_plan.get("semantic_context")
                or proto_plan.get("metadata", {}).get("semantic_context")
            )
            if semantic_context:
                intent = IntentEnricher.enrich(intent, ctx, semantic_context=semantic_context)
        
        # Validate intent
        pkg_skipped = proto_plan.get("metadata", {}).get("pkg_skipped", False)
        validation_errors = IntentValidator.validate(intent, ctx)
        if validation_errors:
            if is_cognitive_path:
                # ARCHITECTURAL FIX: After System-2 planning, enrichment fallback is FORBIDDEN
                # If planner output is invalid, execution must fail - no fallback to System-1
                error_msg = (
                    f"[Coordinator] System-2 planner output invalid for task {ctx.task_id}: "
                    f"{'; '.join(validation_errors)}. "
                    f"Enrichment fallback forbidden after cognitive planning - planner contract violation."
                )
                logger.error(error_msg)
                # Return minimal intent that will cause execution to fail gracefully
                # The actual error should have been caught in _validate_planner_output
                intent = RoutingIntent(
                    specialization=Specialization.GENERALIST.value,
                    skills={},
                    source=IntentSource.FALLBACK_NEUTRAL,
                    confidence=IntentConfidence.MINIMAL,
                )
            elif not pkg_skipped:
                logger.warning(
                    f"[Coordinator] Intent validation errors for task {ctx.task_id}: "
                    f"{'; '.join(validation_errors)}. Falling back to enrichment intent."
                )
                intent = None
            else:
                logger.debug(
                    f"[Coordinator] PKG skipped for simple task {ctx.task_id}, "
                    "using enrichment intent (expected behavior)"
                )
                intent = None
    
    # Second: Extract from enrichment routing (ONLY for FAST path - forbidden after System-2)
    if not intent and not is_cognitive_path:
        existing_routing = task.params.get("routing", {}) if task.params else {}
        enrichment_specialization = (
            existing_routing.get("specialization")
            or existing_routing.get("required_specialization")
        )
        
        if enrichment_specialization:
            intent = RoutingIntent(
                specialization=enrichment_specialization,
                skills=existing_routing.get("skills", {}),
                source=IntentSource.COORDINATOR_BASELINE,
                confidence=IntentConfidence.MEDIUM,
            )
            logger.info(
                f"[Coordinator] Using enrichment routing intent for task {ctx.task_id}: "
                f"{intent.specialization} (source=enrichment, confidence={intent.confidence.value})"
            )
    
    # Third: Use config-driven resolver if provided (LEGACY - deprecated, FAST path only)
    if not intent and not is_cognitive_path and route_cfg.intent_resolver:
        logger.warning(
            f"[Coordinator] Using deprecated intent_resolver for task {ctx.task_id}. "
            "intent_resolver is legacy; PKG should supply routing hints via proto_plan. "
            "Consider migrating to PKG-based routing."
        )
        legacy_intent = route_cfg.intent_resolver(ctx)
        if legacy_intent:
            legacy_intent.source = IntentSource.LEGACY_RESOLVER
            legacy_intent.confidence = IntentConfidence.LOW
        intent = legacy_intent
    
    # Fourth: Coordinator baseline synthesis (ONLY for FAST path - forbidden after System-2)
    if not intent and not is_cognitive_path:
        intent = IntentEnricher.synthesize_baseline(ctx)
        logger.info(
            f"[Coordinator] Synthesized baseline intent for task {ctx.task_id} from Eventizer perception: "
            f"{intent.specialization} (source={intent.source.value}, confidence={intent.confidence.value})"
        )
    
    # ARCHITECTURAL FIX: After System-2, if no intent found, this is a contract violation
    if not intent and is_cognitive_path:
        error_msg = (
            f"[Coordinator] Routing hints missing after cognitive planning for task {ctx.task_id}. "
            f"PKG routing intent is required for execution; cannot proceed."
        )
        logger.error(error_msg)
        # Return minimal intent - execution will fail gracefully
        intent = RoutingIntent(
            specialization=Specialization.GENERALIST.value,
            skills={},
            source=IntentSource.FALLBACK_NEUTRAL,
            confidence=IntentConfidence.MINIMAL,
        )
    
    if intent.skills is None:
        intent.skills = {}
    
    return intent


def _build_routing_result(
    ctx: TaskContext,
    task: TaskPayload,
    intent: RoutingIntent,
    decision_kind: str,
    proto_plan: Dict[str, Any],
    raw_drift: float,
    drift_state: Any,
    surprise_result: Dict[str, Any],
    latency_ms: float,
    correlation_id: str | None,
) -> Any:
    """
    Finalizes the routing payload, attaches audit trails, and selects the result schema.
    """
    # 1. Prepare the Unified Signal Payload (Audit Trail)
    ocps_payload = {
        "drift": raw_drift,
        "cusum_score": getattr(drift_state, "score", None),
        "breached": getattr(drift_state, "is_breached", False),
        "severity": getattr(drift_state, "severity", None),
        "pkg_empty": _is_pkg_result_empty(proto_plan),
        "surprise_score": surprise_result.get("score", 0.0),
        "surprise_decision": surprise_result.get("result", {}).get("decision_kind") if surprise_result.get("result") else None,
    }
    
    # Add surprise features if available
    if surprise_result.get("result"):
        res = surprise_result["result"]
        ocps_payload["surprise_features"] = res.get("x", [])
        ocps_payload["surprise_weights"] = res.get("weights", [])
    
    # Include individual signal values for debugging
    signals_dict = ctx.signals or {}
    ocps_payload["signals"] = {
        "x1_cache_novelty": signals_dict.get("x1_cache_novelty", 0.0),
        "x2_semantic_drift": signals_dict.get("x2_semantic_drift", 0.0),
        "x3_multimodal_anomaly": signals_dict.get("x3_multimodal_anomaly", 0.0),
        "x4_graph_context_drift": signals_dict.get("x4_graph_context_drift", 0.0),
        "x5_logic_uncertainty": signals_dict.get("x5_logic_uncertainty", 0.0),
        "x6_cost_risk": signals_dict.get("x6_cost_risk", 0.0),
    }
    
    # Add PKG empty result information if detected
    if ocps_payload["pkg_empty"]:
        ocps_payload["pkg_empty_result"] = True
        ocps_payload["pkg_empty_reason"] = "unknown_task"
    
    # 2. Generate Human-Readable Insight (The "Cortex" Summary)
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
        logger.info(f"[Cortex Insight] Task {ctx.task_id}: {insight.summary}")
    except Exception as e:
        logger.debug(f"[Coordinator] Insight generation failed: {e}", exc_info=True)
    
    # 3. Build Common Payload Metadata
    payload_common = _create_payload_common(
        task_id=ctx.task_id,
        decision_kind=decision_kind,
        proto_plan=proto_plan,
        router_latency_ms=latency_ms,
        correlation_id=correlation_id,
        ocps_payload=ocps_payload,
    )
    
    if insight:
        payload_common["insight"] = insight.to_dict()
    
    # 4. Final Path Selection
    is_escalated = decision_kind in (
        DecisionKind.COGNITIVE.value,
        DecisionKind.ESCALATED.value,
    )
    
    if is_escalated:
        confidence_score = insight.confidence_score if insight else None
        return create_cognitive_path_result(
            confidence_score=confidence_score,
            **payload_common,
        )
    else:
        # Resolve target organ: PKG hint vs organism-level resolution
        target_organ = intent.organ_hint or "organism"
        
        # Pull interaction mode from task params or defaults
        interaction_mode = (
            task.interaction_mode
            or (task.params or {}).get("interaction", {}).get("mode")
            or "coordinator_routed"
        )
        
        return create_fast_path_result(
            target_organ_id=target_organ,
            routing_params=intent.to_routing_params(),
            interaction_mode=interaction_mode,
            processing_time_ms=latency_ms,
            **payload_common,
        )


async def _record_telemetry(
    exec_cfg: ExecutionConfig,
    task_id: str,
    task_result: Dict[str, Any],
) -> None:
    """Record router telemetry if configured."""
    if exec_cfg.record_router_telemetry_func:
        try:
            await exec_cfg.record_router_telemetry_func(
                exec_cfg.graph_task_repo, task_id, task_result
            )
        except Exception:
            logger.debug("record_router_telemetry_func failed (non-blocking)", exc_info=True)


async def _compute_routing_decision(
    *,
    task: TaskPayload,
    ctx: TaskContext,
    route_cfg: RouteConfig,
    exec_cfg: ExecutionConfig,
    correlation_id: str | None = None,
    embedding: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """
    Orchestrates the routing decision by evaluating drift, surprise, and policy.
    """
    t0 = time.perf_counter()
    
    # 1. Preliminary Assessment
    is_simple = _is_extremely_simple_query_precheck(ctx)
    requires_planning = _requires_planning(ctx.description, task.params)
    pkg_mandatory = _is_pkg_mandatory_action(task)
    if pkg_mandatory:
        logger.info(
            f"[Coordinator] PKG-mandatory action detected for task {ctx.task_id}: "
            "rich domain facts with no routing specialization or emission."
        )
    
    # ARCHITECTURAL FIX: Hard cognitive gate for conditional OR multi-action tasks
    # Enrichment (System-1) cannot override System-2 requirements
    has_conditions = _has_conditional_trigger(ctx.description, task.params)
    has_multiple_actions = _has_multiple_actions(ctx.description, task.params)
    
    # Log hard gate detection for observability
    if has_conditions or has_multiple_actions:
        gate_reasons = []
        if has_conditions:
            gate_reasons.append("conditional_trigger")
        if has_multiple_actions:
            gate_reasons.append("multiple_actions")
        logger.info(
            f"[Coordinator] Hard cognitive gate triggered for task {ctx.task_id}: "
            f"{', '.join(gate_reasons)}. Enrichment cannot override System-2 requirement."
        )
    
    # 2. Signal Processing (Drift & OCPS)
    raw_drift, drift_state = await _process_drift_signals(
        ctx, task, exec_cfg, route_cfg, is_simple
    )
    is_escalated_ocps = bool(getattr(drift_state, "is_breached", False))

    # 3. Uncertainty & Surprise Evaluation
    surprise_result = await _evaluate_surprise_signals(
        ctx, task, route_cfg, drift_state, raw_drift, is_simple, requires_planning
    )
    is_escalated_surprise = surprise_result["is_escalated"]

    # 4. Policy Layer (PKG) Evaluation
    proto_plan, is_pkg_escalated = await _evaluate_policy_layer(
        ctx,
        task,
        route_cfg,
        raw_drift,
        drift_state,
        embedding,
        is_simple,
        requires_planning,
        pkg_mandatory=pkg_mandatory,
    )
    
    # Handle PKG empty signal updates (boost uncertainty signals)
    is_pkg_empty = _is_pkg_result_empty(proto_plan)
    if is_pkg_empty and ctx.signals:
        # Boost x5_logic_uncertainty if PKG is empty (strong uncertainty signal)
        current_uncertainty = ctx.signals.get("x5_logic_uncertainty", 0.0)
        ctx.signals["x5_logic_uncertainty"] = max(current_uncertainty, 0.8)
        
        # Also boost x2_semantic_drift (novelty) if PKG is empty
        current_drift = ctx.signals.get("x2_semantic_drift", 0.0)
        ctx.signals["x2_semantic_drift"] = max(current_drift, 0.5)
    
    # 5. Final Decision Logic (Monotonic Escalation)
    # Authority check: LOW authority cannot force FAST path
    enrichment_auth = _get_intent_authority(task)
    decision_kind = _determine_decision_kind(
        task, ctx.task_id, enrichment_auth, requires_planning,
        has_conditions, has_multiple_actions,
        is_escalated_ocps, is_escalated_surprise, is_pkg_escalated,
        pkg_mandatory=pkg_mandatory,
    )
    
    # Log routing decision reason for observability
    is_escalated = decision_kind in (
        DecisionKind.COGNITIVE.value,
        DecisionKind.ESCALATED.value,
    )
    if decision_kind == "PKG_PENDING":
        logger.info(
            f"[Coordinator] PKG-mandatory decision pending for task {ctx.task_id}. "
            "Awaiting PKG validation before final routing decision."
        )
    elif is_escalated:
        escalation_reasons = []
        if is_escalated_ocps:
            escalation_reasons.append(f"OCPS_breached(drift={raw_drift:.3f})")
        if is_escalated_surprise:
            surprise_score = surprise_result.get("score", 0.0)
            surprise_decision = surprise_result.get("result", {}).get("decision_kind") if surprise_result.get("result") else None
            escalation_reasons.append(f"Surprise(S={surprise_score:.3f}, decision={surprise_decision})")
        if is_pkg_escalated:
            escalation_reasons.append(f"PKG_empty_result(unknown_task, authority={enrichment_auth})")
        if requires_planning:
            escalation_reasons.append("requires_planning(multi_step)")
        if has_conditions:
            escalation_reasons.append("hard_gate(conditional_trigger)")
        if has_multiple_actions:
            escalation_reasons.append("hard_gate(multiple_actions)")
        if enrichment_auth == "LOW" and decision_kind == DecisionKind.COGNITIVE.value:
            escalation_reasons.append("LOW_authority_cannot_force_fast")
        logger.info(
            f"[Coordinator] Routing task {ctx.task_id} to COGNITIVE path. "
            f"Reasons: {', '.join(escalation_reasons)}"
        )
    else:
        logger.info(
            f"[Coordinator] Routing task {ctx.task_id} to FAST path. "
            f"Authority={enrichment_auth}, PKG_empty={is_pkg_empty}, "
            f"requires_planning={requires_planning}"
        )

    # 6. Intent Synthesis
    # Pass is_cognitive_path flag to prevent enrichment fallback after System-2 planning
    is_cognitive = decision_kind in (
        DecisionKind.COGNITIVE.value,
        DecisionKind.ESCALATED.value,
    )
    intent = _resolve_routing_intent(ctx, proto_plan, task, route_cfg, is_cognitive_path=is_cognitive)
    
    # Log routing decision for observability
    if intent.specialization and not intent.organ_hint:
        logger.debug(
            f"[Coordinator] Routing task {ctx.task_id} to 'organism' with "
            f"specialization={intent.specialization} (organ_hint not set, "
            "delegating to Organism router for organ resolution)"
        )
    
    # 7. Finalization & Telemetry
    router_latency = round((time.perf_counter() - t0) * 1000.0, 3)
    task_result = _build_routing_result(
        ctx, task, intent, decision_kind, proto_plan,
        raw_drift, drift_state, surprise_result,
        router_latency, correlation_id
    )

    if exec_cfg.record_router_telemetry_func:
        await _record_telemetry(exec_cfg, ctx.task_id, task_result.model_dump())

    result_dict = task_result.model_dump()
    # Ensure proto_plan is accessible at top-level for downstream guards.
    if "proto_plan" not in result_dict:
        result_dict["proto_plan"] = proto_plan
    payload = result_dict.get("payload")
    if isinstance(payload, dict):
        meta = payload.setdefault("metadata", {})
        if isinstance(meta, dict) and "proto_plan" not in meta:
            meta["proto_plan"] = proto_plan
    return result_dict


async def _try_run_pkg_evaluation(
    *,
    ctx: TaskContext,
    cfg: RouteConfig,
    intent: Optional[RoutingIntent] = None,  # Optional - PKG doesn't need pre-computed intent
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
        if cfg.evaluate_pkg_func is None:
            logger.warning(
                "[Coordinator] PKG evaluation skipped: evaluate_pkg_func is None (task_id=%s)",
                ctx.task_id,
            )
            return proto_plan

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
            # Note: embedding_id, vector_dimension, embedding_model are metadata, not signals
            # They should not be included in signals dict (PKG validation requires dict[str, float])
        }

        # OPTIMIZATION: Skip signal enricher for extremely simple queries
        # Signal enricher calls energy metrics (~50-60ms) which isn't needed for trivial queries
        if cfg.signal_enricher and not _is_extremely_simple_query_precheck(ctx):
            try:
                # Signal enricher can use task context, not pre-computed intent
                extra = await cfg.signal_enricher.compute_contextual_signals(
                    intent, {"task_id": ctx.task_id, "params": ctx.params}
                )
                if isinstance(extra, dict):
                    pkg_signals.update(extra)
            except Exception:
                logger.debug("[Coordinator] SignalEnricher warning", exc_info=True)
        elif cfg.signal_enricher and _is_extremely_simple_query_precheck(ctx):
            # Use default signals for simple queries (skip energy metrics call)
            logger.debug(
                f"[Coordinator] Skipping signal enricher for simple query {ctx.task_id}"
            )
        
        # Sanitize signals: PKG validation requires dict[str, float]
        # Filter out None values, convert booleans to floats, remove non-numeric values
        sanitized_signals: Dict[str, float] = {}
        for key, value in pkg_signals.items():
            if value is None:
                continue  # Skip None values
            elif isinstance(value, bool):
                sanitized_signals[key] = 1.0 if value else 0.0
            elif isinstance(value, (int, float)):
                sanitized_signals[key] = float(value)
            # Skip string and other non-numeric types (e.g., embedding_id, embedding_model)
        
        pkg_signals = sanitized_signals

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
                # Preserve original params for PKG policies (e.g., params.pkg contract)
                "params": ctx.params or {},
                # Provide a minimal raw task payload for adapters/fallbacks
                "raw_task": {
                    "task_id": ctx.task_id,
                    "type": ctx.task_type,
                    "description": ctx.description,
                    "domain": ctx.domain,
                    "params": ctx.params or {},
                },
                # Note: We don't pass intent.specialization - PKG decides this
            },
            timeout_s=int(cfg.pkg_timeout_s or DEFAULT_PKG_TIMEOUT_S),
            embedding=embedding,  # Pass embedding for Unified Memory hydration
        )

        if not isinstance(pkg_res, dict):
            logger.warning(
                "[Coordinator] PKG evaluation returned non-dict result (task_id=%s, type=%s)",
                ctx.task_id,
                type(pkg_res).__name__,
            )
            proto_plan = {"metadata": {"evaluated": False}}
        else:
            proto_plan = pkg_res or {}
        # Embed evaluation metadata directly in proto_plan
        if not proto_plan.get("metadata"):
            proto_plan["metadata"] = {}
        proto_plan["metadata"]["evaluated"] = True
        logger.debug(
            "[Coordinator] PKG evaluation result (task_id=%s) keys=%s evaluated=%s",
            ctx.task_id,
            list(proto_plan.keys()),
            proto_plan.get("metadata", {}).get("evaluated"),
        )
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
            try:
                success = await execution_config.coordinator._enqueue_task_embedding_now(
                    task_id_str,
                    reason="consolidation_result"
                )
                
                if success:
                    logger.debug(f"[Memory] Consolidation enqueued for task {task_id_str}")
                else:
                    # If the queue is full or unavailable, the Outbox Reliability Layer will catch it later
                    # This is expected behavior under high load - not an error
                    logger.debug(
                        f"[Memory] Fast consolidation queue unavailable for task {task_id_str}; "
                        "Outbox will handle consolidation asynchronously."
                    )
            except Exception as e:
                # Non-fatal: consolidation failure should not break execution
                # Outbox Reliability Layer will catch this
                logger.debug(
                    f"[Memory] Fast consolidation enqueue failed for task {task_id_str}: {e}. "
                    "Outbox will handle consolidation asynchronously.",
                    exc_info=True
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
