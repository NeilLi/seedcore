"""
Core execution orchestration for:
- Fast path (organs)
- Routing decisions (Surprise Score + PKG evaluation)
- Route-and-execute coordinator

This module focuses purely on Routing Policy computation. It does NOT execute
Cognitive/Planner logic - that is handled by the Service layer (coordinator_service.py).

This module exposes a framework-free orchestration layer with a stable public API.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from collections.abc import (
    Awaitable,
    Callable,
    Iterable as IterableABC,
    Mapping,
    Sequence,
)
from dataclasses import dataclass
from typing import Any

from ...models.cognitive import CognitiveType, DecisionKind
from ...models.result_schema import (
    create_cognitive_result,
    create_escalated_result,
    create_error_result,
    create_fast_path_result,
)
from ..utils import extract_decision, extract_proto_plan
from ..core.policies import (
    SurpriseComputer,
    decide_route_with_hysteresis,
    generate_proto_subtasks,
)
from ..utils import coerce_task_payload

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# Tunables / sane defaults
DEFAULT_ORGAN_TIMEOUT_S = 30.0
MIN_ORGAN_TIMEOUT_S = 1.0
MAX_ORGAN_TIMEOUT_S = 300.0


# ---------------------------------------------------------------------------
# Type Aliases
# ---------------------------------------------------------------------------

# Type alias for PKG evaluation function
PkgEvalFn = Callable[
    [Sequence[str], Mapping[str, Any], Mapping[str, Any] | None, int],
    Awaitable[dict[str, Any]],
]


# ---------------------------------------------------------------------------
# Helper Functions for Subtask Decomposition
# ---------------------------------------------------------------------------

def _extract_solution_steps(plan_res: Any) -> list[dict[str, Any]]:
    """Safely extract solution steps from a cognitive planning result."""
    if not isinstance(plan_res, dict):
        return []
    
    result_data = plan_res.get("result", {})
    if not isinstance(result_data, dict):
        return []
        
    steps = result_data.get("solution_steps") or result_data.get("steps")
    if isinstance(steps, list):
        return steps
    return []


def _prepare_step_task_payload(
    parent_task: Any, 
    step: dict[str, Any], 
    index: int, 
    cid: str | None
) -> tuple[dict[str, Any], str]:
    """
    Prepares a single sub-task payload by inheriting context from the parent.
    
    Returns: (prepared_task_dict, target_organ_hint)
    """
    # 1. Unwrap and Copy
    # Steps from planner might be { "task": {...}, "organ_id": ... }
    raw_task = step.get("task", step)
    if not isinstance(raw_task, dict):
        raise ValueError(f"Step {index} has invalid task structure")
    
    step_task = dict(raw_task)  # Defensive copy
    if "params" not in step_task:
        step_task["params"] = {}

    # 2. Resolve Parent Params (Handle TaskPayload object vs Dict)
    if hasattr(parent_task, "params"):
        parent_params = parent_task.params
        parent_id = parent_task.task_id
    elif isinstance(parent_task, dict):
        parent_params = parent_task.get("params", {})
        parent_id = parent_task.get("task_id", "unknown")
    else:
        parent_params = {}
        parent_id = "unknown"

    # 3. Routing Inheritance Logic
    parent_routing = parent_params.get("routing", {}) if isinstance(parent_params, dict) else {}
    child_routing = step_task["params"].get("routing", {})
    
    # Merge: Parent Defaults -> Child Overrides
    merged_routing = {**parent_routing, **child_routing}
    step_task["params"]["routing"] = merged_routing
    
    # 3b. Interaction Inheritance (for conversation context)
    parent_interaction = parent_params.get("interaction", {}) if isinstance(parent_params, dict) else {}
    child_interaction = step_task["params"].get("interaction", {})
    
    # Merge interaction params (preserve conversation_id and assigned_agent_id from parent)
    # This ensures subtasks inherit conversation context for sticky routing
    merged_interaction = {**parent_interaction, **child_interaction}
    step_task["params"]["interaction"] = merged_interaction

    # 4. Context Inheritance
    step_task["params"]["parent_task_id"] = parent_id
    step_task["params"]["step_index"] = index
    
    if cid:
        step_task.setdefault("correlation_id", cid)
    
    # Note: Sticky routing (agent affinity) is handled by Organism Router (Tier-1)
    # The interaction params are inherited above, so the Organism Router will handle
    # sticky routing when it processes the subtask

    # 6. Determine Target Organ
    # Priority: Explicit Step Organ > Merged Routing Hint > Default
    organ_hint = step.get("organ_id") or merged_routing.get("target_organ_hint") or "organism"

    return step_task, organ_hint


def _aggregate_execution_results(
    parent_task_id: str,
    solution_steps: list[Any],
    step_results: list[dict[str, Any]],
    decision_kind: str,
    original_meta: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Formats the final result of a decomposed execution plan."""
    
    all_succeeded = all(r.get("result", {}).get("success", False) for r in step_results)
    partial_success = any(r.get("result", {}).get("success", False) for r in step_results)

    aggregated = {
        "success": all_succeeded,
        "result": {
            "plan": {
                "parent_task_id": parent_task_id,
                "total_steps": len(solution_steps),
                "completed_steps": len(step_results),
                "steps": step_results,
            },
            "aggregated": {
                "all_succeeded": all_succeeded,
                "partial_success": partial_success,
            },
        },
        "metadata": {
            "decomposition": True,
            "decision_kind": decision_kind,
            "parent_task_id": parent_task_id,
        },
    }

    # Preserve original planner metadata
    if original_meta:
        aggregated["metadata"].update(original_meta)

    return aggregated


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def route_and_execute(
    *,
    task: Any,
    # Primary interface
    fact_dao: Any | None = None,
    eventizer_helper: Callable[[Any], Any] | None = None,
    # Configuration objects
    routing_config: RouteConfig,
    execution_config: ExecutionConfig,
) -> dict[str, Any]:
    """
    Unified route and execute: computes routing decision and executes accordingly.

    This function handles:
    - Routing Policy computation (Surprise Score + PKG evaluation)
    - Fast Path execution via Organism Service
    - Cognitive/Escalated Path delegation to Cognitive Service
    - Audit trail persistence (proto-plans and telemetry)

    Returns:
        - Fast Path: Returns execution result from Organism Service
        - Cognitive/Escalated Path: Returns planning result from Cognitive Service
        - Error: Returns error result with routing metadata
    """
    # 1. Context Processing
    task_data = await _process_task_input(
        task=task,
        eventizer_helper=eventizer_helper,
        fact_dao=fact_dao,
    )
    ctx = TaskContext.from_dict(task_data)

    # 2. Compute Routing Decision (The "Brain" of the Coordinator)
    cid = execution_config.cid if hasattr(execution_config, 'cid') else None
    routing_result = await _compute_routing_decision(
        ctx=ctx,
        cfg=routing_config,
        correlation_id=cid,
    )

    decision = extract_decision(routing_result)
    if not decision:
        decision = routing_result.get("decision_kind", DecisionKind.ERROR.value)
    
    # Convert task to TaskPayload if needed for downstream processing
    task_obj, task_dict = coerce_task_payload(task)
    
    # Extract agent_id for cognitive calls
    agent_id = (
        task_dict.get("params", {}).get("agent_id")
        or getattr(task_obj, "params", {}).get("agent_id", "unknown")
        if hasattr(task_obj, "params")
        else "unknown"
    )

    # 3. Handle Decision Execution
    # --- PATH A: Cognitive / Escalated Path ---
    if decision in [DecisionKind.COGNITIVE.value, DecisionKind.ESCALATED.value]:
        if not execution_config.cognitive_client:
            logger.error("[route] Cognitive client not available, cannot handle %s decision", decision)
            return routing_result["result"]
        
        try:
            decision_kind_enum = DecisionKind(decision)
            # Determine cog_type based on decision
            cog_type = CognitiveType.TASK_PLANNING  # Default for planning
            if decision == DecisionKind.ESCALATED.value:
                cog_type = CognitiveType.PROBLEM_SOLVING  # Use problem solving for escalated
            
            plan_res = await execution_config.cognitive_client.execute_async(
                agent_id=agent_id,
                cog_type=cog_type,
                decision_kind=decision_kind_enum,
                task=task_obj  # The client will serialize this
            )
            
            # Persist proto-plan if present in cognitive response
            proto_plan = extract_proto_plan(plan_res)
            if proto_plan and execution_config.persist_proto_plan_func:
                try:
                    await execution_config.persist_proto_plan_func(
                        execution_config.graph_task_repo,
                        task_obj.task_id,
                        decision,
                        proto_plan,
                    )
                except Exception as exc:
                    logger.warning(
                        "[route] Failed to persist proto-plan for %s: %s",
                        task_obj.task_id,
                        exc,
                    )
            
            # 1. Extract Steps
            solution_steps = _extract_solution_steps(plan_res)
            
            # 2. Execute Decomposition Loop
            if solution_steps:
                task_id = getattr(task_obj, "task_id", task_obj.get("task_id", "unknown") if isinstance(task_obj, dict) else "unknown")
                logger.info("[route] Decomposing %d steps for task %s", len(solution_steps), task_id)
                
                step_results = []
                
                for i, step in enumerate(solution_steps):
                    try:
                        # A. Prepare (Logic extracted)
                        step_task, organ_hint = _prepare_step_task_payload(
                            parent_task=task_obj,
                            step=step,
                            index=i,
                            cid=cid
                        )
                        
                        # B. Execute (Network Call)
                        logger.debug(
                            "[route] Executing step %d/%d (organ_hint=%s)", 
                            i + 1, len(solution_steps), organ_hint
                        )
                        
                        # Calculate safe timeout based on SLO
                        timeout = execution_config.fast_path_latency_slo_ms / 1000.0 * 2
                        
                        step_result = await execution_config.organism_execute(
                            organ_id=organ_hint,
                            task_dict=step_task,
                            timeout=timeout,
                            cid_local=cid or str(uuid.uuid4()),
                        )
                        
                        step_results.append({
                            "step_index": i,
                            "step": step,
                            "result": step_result,
                        })

                    except Exception as step_exc:
                        logger.error(
                            "[route] Step %d failed for %s: %s", i, task_id, step_exc, exc_info=True
                        )
                        step_results.append({
                            "step_index": i,
                            "step": step,
                            "result": create_error_result(
                                f"Step execution failed: {str(step_exc)}", 
                                "step_execution_error"
                            ).model_dump(),
                        })
                        # Optional: Break on failure here if strict consistency is required
                
                # C. Aggregate (Logic extracted)
                planner_meta = plan_res.get("metadata") if isinstance(plan_res, dict) else {}
                
                return _aggregate_execution_results(
                    parent_task_id=task_id,
                    solution_steps=solution_steps,
                    step_results=step_results,
                    decision_kind=decision,
                    original_meta=planner_meta
                )
            
            # If no steps, just return the plan (Thought without Action)
            return plan_res
            
        except Exception as exc:
            logger.error(
                "[route] Cognitive service delegation failed for %s: %s",
                task_obj.task_id,
                exc,
                exc_info=True
            )
            # Fall through to return routing_result as fallback
            return routing_result["result"]

    # --- PATH B: Fast Path (Reflex) ---
    # Only execute if decision is actually FAST_PATH
    if decision == DecisionKind.FAST_PATH.value:
        # The Core gave us a route (organ_id), now we must DRIVE it.
        
        # 1. Extract the Target
        result_data = routing_result.get("result", {})
        target_organ = (
            result_data.get("organ_id")
            or result_data.get("routed_to")
            or routing_result.get("organ_id")
            or routing_result.get("routed_to")
            or "organism"
        )
        
        # 2. EXECUTE (The Missing Link)
        # We call the Organism Service's unified endpoint.
        def _corr_headers(target: str, cid: str) -> dict[str, str]:
            """Create correlation headers for cross-service communication."""
            return {
                "Content-Type": "application/json",
                "X-Service": "coordinator",
                "X-Source-Service": "coordinator",
                "X-Target-Service": target,
                "X-Correlation-ID": cid,
            }
        
        try:
            # Inject hint if specific organ was resolved
            task_dict_copy = dict(task_dict)
            if target_organ and target_organ not in ("organism", "random"):
                task_dict_copy.setdefault("params", {})
                task_dict_copy["params"].setdefault("routing", {})
                task_dict_copy["params"]["routing"]["target_organ_hint"] = target_organ
            
            # Note: Sticky routing (agent affinity) is handled by Organism Router (Tier-1)
            # The Coordinator (Tier-0) only handles high-level routing decisions

            timeout = execution_config.fast_path_latency_slo_ms / 1000.0 * 2  # Give some buffer
            execution_response = await execution_config.organism_execute(
                organ_id=target_organ,
                task_dict=task_dict_copy,
                timeout=timeout,
                cid_local=cid or str(uuid.uuid4()),
            )
            
            # Merge the Execution Result into our Return Value
            # We prefer the execution result, but keep routing metadata if needed
            final_result = execution_response

        except Exception as e:
            logger.error(f"[route] Fast path execution failed: {e}")
            final_result = create_error_result(f"Execution failed: {str(e)}", "execution_error").model_dump()

        # 3. PERSISTENCE (Audit Trail)
        # We persist the 'proto-plan' (routing decision) and telemetry
        # regardless of execution success/failure.
        
        # A. Proto-Plan Persistence
        proto_plan = extract_proto_plan(routing_result)
        if proto_plan and execution_config.persist_proto_plan_func:
            try:
                # The persistence function handles its own session management
                await execution_config.persist_proto_plan_func(
                    execution_config.graph_task_repo,
                    task_obj.task_id,
                    decision,
                    proto_plan,
                )
            except Exception as exc:
                logger.warning(f"[route] Failed to persist proto-plan: {exc}")

        # B. Telemetry Persistence
        if execution_config.record_router_telemetry_func:
            try:
                # The telemetry function handles its own session management
                await execution_config.record_router_telemetry_func(
                    execution_config.graph_task_repo,
                    task_obj.task_id,
                    routing_result  # The routing data, not the execution result
                )
            except Exception as exc:
                logger.warning(f"[route] Telemetry failed: {exc}")

        return final_result
    
    # --- PATH C: Fallback/Error Path ---
    # If decision is not FAST_PATH, COGNITIVE, or ESCALATED, return routing result
    logger.warning(f"[route] Unhandled decision kind: {decision}, returning routing result")
    return routing_result["result"]


async def resolve_fast_route(
    *,
    task: dict[str, Any],
    normalize_task_dict: Callable[[Any], tuple[dict[str, Any], dict[str, Any]]],
    compute_drift_score: Callable[[dict[str, Any], Any, Any], Awaitable[float]],
    resolve_route_cached: Callable[[str, str | None, str | None, str], Awaitable[str | None]],
    static_route_fallback: Callable[[str, str | None], str],
    normalize_type: Callable[[str | None], str],
    normalize_domain: Callable[[str | None], str | None],
    graph_task_repo: Any,
    ml_client: Any,
    predicate_router: Any,
    cid: str,
    persist: bool = True,
) -> dict[str, Any]:
    """
    Resolve organ for a fast-path task and return a FastPathResult with executed=False.
    No remote execution is performed here.
    """
    t0 = time.time()

    task_dict, meta = normalize_task_dict(task)
    task_id = str(task_dict.get("id") or meta.get("task_id") or "unknown")

    # Signals: drift & energy (best-effort)
    await _inject_drift_and_energy(
        task_dict,
        compute_drift_score=compute_drift_score,
        ml_client=ml_client,
        predicate_router=predicate_router,
    )

    # Resolve route (cached → fallback)
    ttype = normalize_type(task_dict.get("type"))
    domain = normalize_domain(task_dict.get("domain"))
    preferred = None
    if hasattr(predicate_router, "preferred_logical_id"):
        try:
            preferred = predicate_router.preferred_logical_id(task_dict)
        except Exception:
            preferred = None

    route = await _maybe_call(resolve_route_cached, ttype, domain, preferred, cid)
    if not route:
        route = static_route_fallback(ttype, domain)
        logger.info("[fast] Using static fallback route %s for %s/%s", route, ttype, domain)

    # Persist (best-effort)
    if persist:
        await _persist_task_best_effort(graph_task_repo, task_dict, agent_id=None, organ_id=route)

    latency_ms = (time.time() - t0) * 1000.0

    # Return a FastPathResult (executed=False). CoordinatorHttpRouter will delegate.
    return create_fast_path_result(
        routed_to=route,
        organ_id=route,
        result={"status": "routed"},
        metadata={
            "routing": "completed",
            "executed": False,
            "fast_latency_ms": latency_ms,
            "task_id": task_id,
            "type": ttype,
            "domain": domain,
            "cid": cid,
        },
    ).model_dump()


# ---------------------------------------------------------------------------
# Core Logic (Internal)
# ---------------------------------------------------------------------------

async def _compute_routing_decision(
    *,
    ctx: TaskContext,
    cfg: RouteConfig,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """
    Compute routing decision_kind using surprise score, PKG evaluation, and hysteresis.
    """
    t0 = time.perf_counter()

    # 1. Extract signals
    params = ctx.params
    mw_hit = params.get("cache", {}).get("mw_hit") if isinstance(params.get("cache"), dict) else None
    ocps = params.get("ocps") or {}
    drift_minmax: tuple[float, float] | None = None
    if "drift_p10" in params and "drift_p90" in params:
        try:
            drift_minmax = (float(params["drift_p10"]), float(params["drift_p90"]))
        except Exception:
            drift_minmax = None

    signals = {
        "mw_hit": mw_hit,
        "ocps": ocps,
        "drift_minmax": drift_minmax,
        "ood_dist": params.get("ood_dist"),
        "ood_to01": cfg.ood_to01,
        "graph_delta": params.get("graph_delta"),
        "mu_delta": params.get("mu_delta"),
        "dep_probs": params.get("dependency_probs"),
        "est_runtime": params.get("est_runtime"),
        "SLO": params.get("slo"),
        "kappa": params.get("kappa", 0.8),
        "criticality": params.get("criticality", 0.5),
    }

    # 2. Compute surprise
    s_out = cfg.surprise_computer.compute(signals)
    S = s_out["S"]
    xs = s_out["x"]

    # ---- 2. Decide route kind -----------------------------------------------
    last_decision = params.get("last_decision")
    decision_str = decide_route_with_hysteresis(
        S,
        last_decision,
        cfg.surprise_computer.tau_fast,
        cfg.tau_fast_exit,
        cfg.surprise_computer.tau_plan,
        cfg.tau_plan_exit,
    )
    
    # Keep decision_str for backward compatibility in logging and metadata
    decision_kind = decision_str

    # 4. Proto plan scaffold
    proto_plan: dict[str, Any] = {"tasks": [], "edges": [], "hints": {}}
    hints = proto_plan["hints"]
    if ctx.fact_reads:
        hints["facts_read"] = ctx.fact_reads
    if ctx.fact_produced:
        hints["facts_produced"] = ctx.fact_produced
    if ctx.eventizer_data:
        hints.setdefault("event_tags", sorted(ctx.tags))
        if isinstance(ctx.eventizer_data.get("confidence"), dict):
            hints.setdefault("eventizer_confidence", ctx.eventizer_data["confidence"])

    # 5. PKG evaluation (with fallback)
    pkg_meta = {"evaluated": False, "version": None, "error": None}
    used_fallback = False
    try:
        if cfg.evaluate_pkg_func is None:
            raise RuntimeError("PKG evaluation function not provided in RouteConfig")

        task_facts_context = {
            "domain": ctx.domain,
            "type": ctx.task_type,
            "task_id": ctx.task_id,
            "pii_redacted": ctx.pii_redacted
        }
        task_facts_signals = {
            "S": S,
            "x1": xs[0],
            "x2": xs[1],
            "x3": xs[2],
            "x4": xs[3],
            "x5": xs[4],
            "x6": xs[5],
            "ocps": s_out["ocps"],
        }

        pkg_res = await cfg.evaluate_pkg_func(
            tags=list(ctx.tags),
            signals=task_facts_signals,
            context=task_facts_context,
            timeout_s=cfg.pkg_timeout_s,
        )

        if not isinstance(pkg_res, dict):
            raise ValueError("PKG returned unexpected type")

        proto_plan.update({"tasks": pkg_res.get("tasks", []), "edges": pkg_res.get("edges", [])})
        pkg_meta.update({"evaluated": True, "version": pkg_res.get("version")})

    except Exception as e:
        used_fallback = True
        pkg_meta["error"] = f"PKG unavailable or timed out: {e}"
        force_decomp = bool(params.get("force_decomposition", False) or params.get("force_hgnn", False))
        should_decompose = force_decomp or (decision_kind == DecisionKind.ESCALATED)
        proto_plan = generate_proto_subtasks(ctx.tags, xs[5], signals["criticality"], force=should_decompose)

    proto_plan.setdefault("provenance", [])
    proto_plan["provenance"].append("fallback:router_rules@1.0" if used_fallback else f"pkg:{pkg_meta.get('version', 'unknown')}")

    # 6. Apply operator overrides
    decision_kind, original_decision = _apply_forced_promotions(decision_kind, params)

    # 7. Create payloads
    router_latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    eventizer_summary = _create_eventizer_summary(ctx.eventizer_data, ctx.eventizer_tags)

    surprise_payload = {
        "S": S,
        "x": list(xs),
        "weights": list(cfg.surprise_computer.w_hat),
        "tau_fast": cfg.surprise_computer.tau_fast,
        "tau_plan": cfg.surprise_computer.tau_plan,
        "tau_fast_exit": cfg.tau_fast_exit,
        "tau_plan_exit": cfg.tau_plan_exit,
        "ocps": s_out["ocps"],
        "version": "surprise/1.2.0",
    }

    payload_common = _create_payload_common(
        task_id=ctx.task_id,
        task_type=ctx.task_type,
        domain=ctx.domain,
        decision_kind=decision_kind,
        last_decision=last_decision,
        original_decision=original_decision,
        surprise_data=surprise_payload,
        signals_present=sorted([k for k, v in signals.items() if v is not None]),
        pkg_meta=pkg_meta,
        used_fallback=used_fallback,
        proto_plan=proto_plan,
        event_tags=ctx.tags,
        attributes=ctx.attributes,
        confidence=ctx.confidence,
        pii_redacted=ctx.pii_redacted,
        router_latency_ms=router_latency_ms,
        eventizer_summary=eventizer_summary,
        correlation_id=correlation_id,
    )

    # 8. Log
    ocps_meta = s_out["ocps"]
    logger.info(
        "[route] task_id=%s S=%.3f x2_meta(S_t=%s,h=%s,h_clr=%s,flag_on=%s) decision_kind=%s pkg_used=%s latency_ms=%.1f",
        ctx.task_id,
        S,
        ocps_meta.get("S_t", "N/A"),
        ocps_meta.get("h", "N/A"),
        ocps_meta.get("h_clr", "N/A"),
        ocps_meta.get("flag_on", "N/A"),
        decision_kind,
        not used_fallback,
        router_latency_ms,
    )

    # 9. Emit result schema
    if decision_kind == DecisionKind.FAST_PATH:
        # Note: organ_id is set to "organism" as a placeholder since actual routing
        # happens downstream in OrganismRouter. CoordinatorHttpRouter delegates task_data
        # to OrganismRouter which resolves the organ_id itself.
        res = create_fast_path_result(
            routed_to="organism",  # Placeholder; actual organ resolved by OrganismRouter
            organ_id="organism",  # Placeholder; actual organ resolved by OrganismRouter
            result={"status": "routed"},
            metadata={"routing": "completed", "executed": False, **payload_common},
        ).model_dump()
    elif decision_kind == DecisionKind.COGNITIVE:
        # Extract agent_id from task params for cognitive planning
        agent_id_for_planner = ctx.params.get("agent_id", "planner")
        # proto_plan is placed in result field for CognitiveRouter extraction:
        # CognitiveRouter._extract_proto_plan checks prior_result["payload"]["result"]["proto_plan"]
        # task_type should be the actual task type (e.g., "ping", "general_query", "execute"),
        # not routing metadata like "planner"
        res = create_cognitive_result(
            agent_id=agent_id_for_planner,
            task_type=ctx.task_type or "unknown",
            result={"proto_plan": proto_plan},
            confidence_score=None,
            **payload_common,
        ).model_dump()
    elif decision_kind == DecisionKind.ESCALATED:
        res = create_escalated_result(
            solution_steps=[],
            plan_source="hgnn",
            **payload_common,
        ).model_dump()
    else:
        res = create_error_result(
            error="unrecognized decision_kind",
            error_type="router_unrecognized_decision",
            original_type="routing",
            **payload_common,
        ).model_dump()

    # 10. Ensure payload.metadata contains critical fields for untyped consumers
    try:
        payload = res.setdefault("payload", {})
        meta = payload.setdefault("metadata", {})
        meta.update({
            "decision_kind": payload_common.get("decision_kind"),
            "original_decision": payload_common.get("original_decision"),
            "surprise": payload_common.get("surprise"),
            "proto_plan": payload_common.get("proto_plan"),
            "event_tags": payload_common.get("event_tags", []),
            "attributes": payload_common.get("attributes", {}),
            "confidence": payload_common.get("confidence", {}),
        })
        # Include correlation_id in metadata if present (for trace propagation)
        if correlation_id:
            meta["correlation_id"] = correlation_id
    except Exception as e:
        logger.debug("payload normalization best-effort failed: %s", e)

    return {
        "decision_kind": decision_kind,
        "original_decision": original_decision,
        "last_decision": last_decision,
        "surprise": surprise_payload,
        "proto_plan": proto_plan,
        "pkg_meta": pkg_meta,
        "payload_common": payload_common,
        "result": res,
    }


async def _process_task_input(
    *,
    task: Any,
    eventizer_helper: Callable[[Any], Any] | None = None,
    fact_dao: Any | None = None,
) -> dict[str, Any]:
    """
    Process task input to extract eventizer data, tags, facts, and other metadata.
    """
    payload, merged = coerce_task_payload(task)

    # Basic fields from normalized payload
    task_id = payload.task_id
    task_type = payload.type
    domain = payload.domain
    params = dict(merged.get("params") or {})
    if not domain:
        domain = merged.get("domain")

    # Eventizer
    eventizer_data: dict[str, Any] = {}
    if eventizer_helper is not None:
        features = eventizer_helper(merged)
        if inspect.isawaitable(features):
            features = await features
        if isinstance(features, dict):
            eventizer_data = features

    # Tags
    tags: set[str] = set()
    routing_envelope = params.get("routing") if isinstance(params.get("routing"), dict) else {}
    param_tags = params.get("event_tags") or routing_envelope.get("event_tags") or []
    if isinstance(param_tags, IterableABC) and not isinstance(param_tags, (str, bytes)):
        tags.update(str(t) for t in param_tags)

    eventizer_tags: dict[str, Any] = {}
    if isinstance(eventizer_data.get("event_tags"), dict):
        eventizer_tags = eventizer_data["event_tags"]
        evt_types = eventizer_tags.get("event_types")
        if isinstance(evt_types, IterableABC) and not isinstance(evt_types, (str, bytes)):
            tags.update(str(t) for t in evt_types)
        evt_domain = eventizer_tags.get("domain")
        if evt_domain and not domain:
            domain = str(evt_domain)

    # Attributes / confidence
    attributes: dict[str, Any] = {}
    if isinstance(eventizer_data.get("attributes"), dict):
        attributes.update(eventizer_data["attributes"])
    if isinstance(params.get("attributes"), dict):
        attributes.update(params["attributes"])

    confidence: dict[str, Any] = {}
    if isinstance(eventizer_data.get("confidence"), dict):
        confidence.update(eventizer_data["confidence"])
    if isinstance(params.get("confidence"), dict):
        confidence.update(params["confidence"])

    # PII flag
    pii_redacted = bool(params.get("pii", {}).get("was_redacted", False))
    if "pii_redacted" in eventizer_data:
        pii_redacted = bool(eventizer_data.get("pii_redacted"))

    # Facts I/O
    fact_reads: list[str] = []
    fact_produced: list[str] = []
    if fact_dao is not None:
        start_ids = _coerce_uuid_list(params.get("start_fact_ids") or [])
        if start_ids:
            try:
                facts = await _maybe_call(fact_dao.get_for_task, start_ids, task_id)
                fact_reads = [str(f.id) for f in facts]
            except Exception as e:
                logger.debug("fact_dao.get_for_task failed: %s", e)

        produced_candidates: list[uuid.UUID] = []
        for key in ("produced_fact_ids", "produce_fact_ids", "fact_output_ids"):
            produced_candidates.extend(_coerce_uuid_list(params.get(key) or []))
        if produced_candidates:
            for fid in produced_candidates:
                try:
                    await _maybe_call(fact_dao.record_produced_fact, fid, task_id)
                except Exception as e:
                    logger.debug("record_produced_fact failed for %s: %s", fid, e)
            fact_produced = [str(fid) for fid in produced_candidates]

    # Basic domain inference if missing
    if not domain:
        if any(t in tags for t in ["vip", "allergen", "luggage_custody", "hvac_fault", "privacy"]):
            domain = "hotel_ops"
        elif any(t in tags for t in ["fraud", "chargeback", "payment"]):
            domain = "fintech"
        elif any(t in tags for t in ["healthcare", "medical", "allergy"]):
            domain = "healthcare"
        elif any(t in tags for t in ["robotics", "iot", "fault"]):
            domain = "robotics"

    return {
        "task_id": task_id,
        "task_type": task_type,
        "domain": domain,
        "params": params,
        "eventizer_data": eventizer_data,
        "eventizer_tags": eventizer_tags,
        "tags": tags,
        "attributes": attributes,
        "confidence": confidence,
        "pii_redacted": pii_redacted,
        "fact_reads": fact_reads,
        "fact_produced": fact_produced,
    }




# ---------------------------------------------------------------------------
# Routing Helpers (Internal)
# ---------------------------------------------------------------------------

def _apply_forced_promotions(decision_kind: str, params: dict[str, Any]) -> tuple[str, str | None]:
    """
    Apply operator overrides to a routing decision_kind.
    Returns (final_decision, original_if_changed).
    """
    force_decomp = bool(params.get("force_decomposition", False))
    force_hgnn = bool(params.get("force_hgnn", False))
    original = decision_kind

    if force_hgnn and decision_kind != "hgnn":
        logger.info("[route] force_hgnn=True: promoting %s → hgnn", decision_kind)
        decision_kind = "hgnn"
    elif force_decomp and decision_kind == "fast":
        logger.info("[route] force_decomposition=True: promoting fast → planner")
        decision_kind = "planner"

    return decision_kind, (original if decision_kind != original else None)


def _create_eventizer_summary(
    eventizer_data: dict[str, Any],
    eventizer_tags: dict[str, Any]
) -> dict[str, Any] | None:
    """Compact summary to avoid shipping full eventizer blob."""
    if not eventizer_data:
        return None
    return {
        "event_tags": eventizer_tags.get("event_types") if eventizer_tags else None,
        "attributes": eventizer_data.get("attributes"),
        "confidence": eventizer_data.get("confidence"),
        "patterns_applied": eventizer_data.get("patterns_applied"),
        "pii_redacted": eventizer_data.get("pii_redacted"),
    }


def _create_payload_common(
    *,
    task_id: str,
    task_type: str,
    domain: str | None,
    decision_kind: str,
    last_decision: str | None,
    original_decision: str | None,
    surprise_data: dict[str, Any],
    signals_present: list[str],
    pkg_meta: dict[str, Any],
    used_fallback: bool,
    proto_plan: dict[str, Any] | None,
    event_tags: set[str],
    attributes: dict[str, Any],
    confidence: dict[str, Any],
    pii_redacted: bool,
    router_latency_ms: float,
    eventizer_summary: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """
    Create consistent payload metadata shared by all execution paths.
    """
    payload_common = {
        "task_id": task_id,
        "type": task_type,
        "domain": domain,
        "decision_kind": decision_kind,
        "last_decision": last_decision,
        "original_decision": original_decision if decision_kind != original_decision else None,
        "surprise": surprise_data,
        "signals_present": sorted(signals_present),
        "pkg": {"used": not used_fallback, "version": pkg_meta.get("version"), "error": pkg_meta.get("error")},
        "proto_plan": proto_plan,
        "event_tags": sorted(list(event_tags)),
        "attributes": attributes,
        "confidence": confidence,
        "pii_redacted": pii_redacted,
        "router_latency_ms": router_latency_ms,
        "payload_version": "router/1.2.0",
    }
    if correlation_id:
        payload_common["correlation_id"] = correlation_id
    if eventizer_summary is not None:
        payload_common["eventizer"] = eventizer_summary
    return payload_common


# ---------------------------------------------------------------------------
# Generic Helpers (Internal)
# ---------------------------------------------------------------------------

async def _maybe_call(fn: Callable[..., Any] | None, *args, **kwargs) -> Any:
    """Call sync/async function uniformly."""
    if fn is None:
        return None
    out = fn(*args, **kwargs)
    return await out if asyncio.iscoroutine(out) else out


def _bound_timeout(value: Any, default: float = DEFAULT_ORGAN_TIMEOUT_S) -> float:
    """Coerce & clamp timeout to safe range."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = default
    return max(MIN_ORGAN_TIMEOUT_S, min(MAX_ORGAN_TIMEOUT_S, v))


def _coerce_uuid_list(values: Any) -> list[uuid.UUID]:
    """Safely convert an unknown input into a list of unique UUIDs."""
    if isinstance(values, (str, bytes)) or values is None:
        return []
    if not isinstance(values, IterableABC):
        values = [values]

    out: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for v in values:
        try:
            u = uuid.UUID(str(v))
        except (TypeError, ValueError):
            continue
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


async def _inject_drift_and_energy(
    task_dict: dict[str, Any],
    *,
    compute_drift_score: Callable[[dict[str, Any], Any, Any], Awaitable[float]],
    ml_client: Any,
    predicate_router: Any,
) -> None:
    """Add drift_score and energy_budget (best-effort)."""
    try:
        task_dict["drift_score"] = await compute_drift_score(task_dict, ml_client, predicate_router)
    except Exception as e:
        logger.debug("drift_score computation failed for task %s: %s", task_dict.get("id") or "unknown", e)

    task_dict.setdefault("params", {})
    if hasattr(predicate_router, "get_energy_budget"):
        try:
            eb = predicate_router.get_energy_budget()
            if eb is not None:
                task_dict["params"]["energy_budget"] = eb
        except Exception as e:
            logger.debug("energy_budget retrieval failed: %s", e)


async def _persist_task_best_effort(
    repo: Any,
    task_dict: dict[str, Any],
    *,
    agent_id: str | None = None,
    organ_id: str | None = None,
) -> Any | None:
    """Persist a task if repository supports it; swallow errors."""
    if hasattr(repo, "create_task"):
        try:
            return await _maybe_call(repo.create_task, task_dict, agent_id=agent_id, organ_id=organ_id)
        except Exception as e:
            logger.warning("Persist task failed for %s: %s", task_dict.get("id") or "unknown", e)
    return None


async def _persist_dependency_best_effort(repo: Any, parent_id: Any, child_id: Any) -> None:
    if parent_id and child_id and hasattr(repo, "add_dependency"):
        try:
            await _maybe_call(repo.add_dependency, parent_id, child_id)
        except Exception as e:
            logger.warning("Persist dependency failed: %s", e)


# ---------------------------------------------------------------------------
# Configuration Objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TaskContext:
    """Task-derived context: everything extracted from task/eventizer/facts."""
    task_id: str
    task_type: str
    domain: str | None
    params: dict[str, Any]
    eventizer_data: dict[str, Any]
    eventizer_tags: dict[str, Any]
    tags: set[str]
    attributes: dict[str, Any]
    confidence: dict[str, Any]
    pii_redacted: bool
    fact_reads: list[str]
    fact_produced: list[str]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TaskContext:
        """Create TaskContext from _process_task_input output."""
        return cls(
            task_id=d["task_id"],
            task_type=d["task_type"],
            domain=d["domain"],
            params=d["params"],
            eventizer_data=d["eventizer_data"],
            eventizer_tags=d["eventizer_tags"],
            tags=set(d["tags"]),
            attributes=d["attributes"],
            confidence=d["confidence"],
            pii_redacted=d["pii_redacted"],
            fact_reads=list(d["fact_reads"]),
            fact_produced=list(d["fact_produced"]),
        )


@dataclass(frozen=True)
class RouteConfig:
    """Routing decision_kind configuration: thresholds, evaluators, timeouts."""
    surprise_computer: SurpriseComputer
    tau_fast_exit: float
    tau_plan_exit: float
    evaluate_pkg_func: PkgEvalFn
    ood_to01: Callable[[float], float] | None = None
    pkg_timeout_s: int = 2


@dataclass(frozen=True)
class ExecutionConfig:
    """Configuration for task execution dependencies."""
    normalize_task_dict: Callable[[Any], tuple[dict[str, Any], dict[str, Any]]]
    compute_drift_score: Callable[[dict[str, Any], Any, Any], Awaitable[float]]
    organism_execute: Callable[[str, dict[str, Any], float, str], Awaitable[dict[str, Any]]]
    graph_task_repo: Any
    ml_client: Any
    predicate_router: Any
    metrics: Any
    cid: str
    resolve_route_cached: Callable[[str, str | None, str | None, str], Awaitable[str | None]]
    static_route_fallback: Callable[[str, str | None], str]
    normalize_type: Callable[[str | None], str]
    normalize_domain: Callable[[str | None], str | None]
    # New dependencies for decision execution
    cognitive_client: Any | None = None
    persist_proto_plan_func: Callable[[Any, str, str, dict[str, Any]], Awaitable[None]] | None = None
    record_router_telemetry_func: Callable[[Any, str, dict[str, Any]], Awaitable[None]] | None = None
    resolve_session_factory_func: Callable[[Any], Any] | None = None
    fast_path_latency_slo_ms: float = 5000.0  # Default 5 seconds

