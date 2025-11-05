"""Core execution orchestration for fast path, HGNN, and route-and-execute."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any, Dict, List, Optional, Callable, Awaitable, Tuple, Sequence, Mapping, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper to support sync/async dependencies uniformly
# ---------------------------------------------------------------------------
async def _maybe_call(fn: Callable[..., Any], *args, **kwargs):
    r = fn(*args, **kwargs)
    if asyncio.iscoroutine(r):
        return await r
    return r


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------
def make_escalation_result(results: List[Dict[str, Any]], plan: List[Dict[str, Any]], success: bool) -> Dict[str, Any]:
    return {
        "success": success,
        "escalated": True,
        "plan_source": "cognitive_service",
        "plan": plan,
        "results": results,
        "path": "hgnn",
    }


# ---------------------------------------------------------------------------
# Fast path
# ---------------------------------------------------------------------------
async def execute_fast(
    *,
    task: Dict[str, Any],
    normalize_task_dict: Callable[[Any], Tuple[Dict[str, Any], Dict[str, Any]]],
    extract_agent_id: Callable[[Dict[str, Any]], Optional[str]],
    compute_drift_score: Callable[[Dict[str, Any], Any, Any], Awaitable[float]],
    resolve_route_cached: Callable[[str, Optional[str], Optional[str], str], Awaitable[Optional[str]]],
    static_route_fallback: Callable[[str, Optional[str]], str],
    normalize_type: Callable[[Optional[str]], str],
    normalize_domain: Callable[[Optional[str]], Optional[str]],
    organism_execute: Callable[[str, Dict[str, Any], float, str], Awaitable[Dict[str, Any]]],
    graph_task_repo: Any,
    ml_client: Any,
    predicate_router: Any,
    cid: str,
) -> Dict[str, Any]:
    """
    Fast path execution with minimal overhead.
    """
    t0 = time.time()

    # Normalize and extract basics
    task_dict, meta = normalize_task_dict(task)
    task_id = str(task_dict.get("id") or meta.get("task_id") or "unknown")

    agent_id = extract_agent_id(task_dict)
    if not agent_id:
        logger.warning("[Fast] No agent ID found for task %s", task_id)
        # If strict policy, return early; otherwise continue without agent_id.
        # return {"success": False, "error": "No agent ID", "task_id": task_id}

    # Drift + energy
    try:
        task_dict["drift_score"] = await compute_drift_score(task_dict, ml_client, predicate_router)
    except Exception as e:
        logger.debug("drift_score computation failed for %s: %s", task_id, e)

    task_dict.setdefault("params", {})
    if hasattr(predicate_router, "get_energy_budget"):
        try:
            eb = predicate_router.get_energy_budget()
            if eb is not None:
                task_dict["params"]["energy_budget"] = eb
        except Exception:
            pass

    # Resolve route (cached → fallback)
    task_type = normalize_type(task_dict.get("type"))
    domain = normalize_domain(task_dict.get("domain"))
    preferred = None
    if hasattr(predicate_router, "preferred_logical_id"):
        try:
            preferred = predicate_router.preferred_logical_id(task_dict)
        except Exception:
            preferred = None

    route = await _maybe_call(resolve_route_cached, task_type, domain, preferred, cid)
    if not route:
        route = static_route_fallback(task_type, domain)
        logger.info("[Fast] Using static fallback route %s for %s/%s", route, task_type, domain)

    # Timeout (bounded)
    params = task_dict.get("params") if isinstance(task_dict.get("params"), dict) else {}
    organ_timeout = params.get("organ_timeout_s", 30.0)
    try:
        organ_timeout = float(organ_timeout)
        organ_timeout = max(1.0, min(300.0, organ_timeout))
    except (TypeError, ValueError):
        organ_timeout = 30.0

    # Persist (best-effort)
    if hasattr(graph_task_repo, "create_task"):
        try:
            await _maybe_call(graph_task_repo.create_task, task_dict, agent_id=agent_id, organ_id=route)
        except Exception as e:
            logger.warning("[Fast] Persist failed for %s: %s", task_id, e)

    # Execute remotely
    result = await organism_execute(route, task_dict, organ_timeout, cid)
    result["organ_id"] = route

    latency_ms = (time.time() - t0) * 1000.0
    result.setdefault("metrics", {})["fast_latency_ms"] = latency_ms
    return result


# ---------------------------------------------------------------------------
# HGNN path
# ---------------------------------------------------------------------------
async def execute_hgnn(
    *,
    task: Dict[str, Any],
    normalize_task_dict: Callable[[Any], Tuple[Dict[str, Any], Dict[str, Any]]],
    extract_agent_id: Callable[[Dict[str, Any]], Optional[str]],
    compute_drift_score: Callable[[Dict[str, Any], Any, Any], Awaitable[float]],
    hgnn_decompose: Callable[[Any], Awaitable[List[Dict[str, Any]]]],
    bulk_resolve_func: Callable[[List[Dict[str, Any]], str], Awaitable[Dict[int, str]]],
    persist_plan_func: Callable[[Any, List[Dict[str, Any]], Optional[Any]], Awaitable[None]],
    static_route_fallback: Callable[[str, Optional[str]], str],
    normalize_type: Callable[[Optional[str]], str],
    normalize_domain: Callable[[Optional[str]], Optional[str]],
    organism_execute: Callable[[str, Dict[str, Any], float, str], Awaitable[Dict[str, Any]]],
    graph_task_repo: Any,
    ml_client: Any,
    predicate_router: Any,
    metrics: Any,
    cid: str,
) -> Dict[str, Any]:
    """
    HGNN path execution with decomposition and planning.
    """
    t0 = time.time()

    root_task_dict, meta = normalize_task_dict(task)
    task_id = str(root_task_dict.get("id") or meta.get("task_id") or "unknown")
    root_agent_id = extract_agent_id(root_task_dict)

    try:
        plan = await hgnn_decompose(task)
        if not plan:
            rr = await organism_execute("random", root_task_dict, 5.0, cid)
            latency_ms = (time.time() - t0) * 1000.0
            if hasattr(metrics, "track_metrics"):
                metrics.track_metrics("hgnn_fallback", rr.get("success", False), latency_ms)
            return {"success": rr.get("success", False), "result": rr, "path": "hgnn_fallback"}

        # Drift + energy on root
        try:
            root_task_dict["drift_score"] = await compute_drift_score(root_task_dict, ml_client, predicate_router)
        except Exception:
            pass
        root_task_dict.setdefault("params", {})
        if hasattr(predicate_router, "get_energy_budget"):
            try:
                eb = predicate_router.get_energy_budget()
                if eb is not None:
                    root_task_dict["params"]["energy_budget"] = eb
            except Exception:
                pass

        # Persist root (best-effort)
        root_db_id = None
        if hasattr(graph_task_repo, "create_task"):
            try:
                root_db_id = await _maybe_call(graph_task_repo.create_task, root_task_dict, agent_id=root_agent_id)
            except Exception as e:
                logger.warning("[HGNN] Persist root failed for %s: %s", task_id, e)

        # Persist plan metadata (best-effort)
        try:
            await persist_plan_func(task, plan, root_db_id)
        except Exception as e:
            logger.warning("[HGNN] Persist plan failed for %s: %s", task_id, e)

        # Resolve routes in bulk
        try:
            idx_to_logical = await bulk_resolve_func(plan, cid)
        except Exception as e:
            logger.warning("[HGNN] Bulk resolve failed, will fallback: %s", e)
            idx_to_logical = {}

        # Fill organ_id for each step
        for idx, step in enumerate(plan):
            if not isinstance(step, dict):
                continue
            if not step.get("organ_id"):
                step["organ_id"] = idx_to_logical.get(idx) or static_route_fallback(
                    normalize_type(step.get("task", {}).get("type")),
                    normalize_domain(step.get("task", {}).get("domain")),
                )

        # Execute steps sequentially
        results: List[Dict[str, Any]] = []
        for idx, step in enumerate(plan):
            organ_id = step.get("organ_id")
            raw_subtask = step.get("task")
            subtask_dict = dict(raw_subtask) if isinstance(raw_subtask, dict) else dict(root_task_dict)

            # Inject drift + energy
            try:
                subtask_dict["drift_score"] = await compute_drift_score(subtask_dict, ml_client, predicate_router)
            except Exception:
                pass
            subtask_dict.setdefault("params", {})
            if hasattr(predicate_router, "get_energy_budget"):
                try:
                    eb = predicate_router.get_energy_budget()
                    if eb is not None:
                        subtask_dict["params"]["energy_budget"] = eb
                except Exception:
                    pass

            # Persist child + dependency (best-effort)
            try:
                if hasattr(graph_task_repo, "create_task"):
                    sub_agent_id = extract_agent_id(subtask_dict) or root_agent_id
                    child_db_id = await _maybe_call(
                        graph_task_repo.create_task, subtask_dict, agent_id=sub_agent_id, organ_id=organ_id
                    )
                    if root_db_id and hasattr(graph_task_repo, "add_dependency") and child_db_id:
                        await _maybe_call(graph_task_repo.add_dependency, root_db_id, child_db_id)
            except Exception as e:
                logger.warning("[HGNN] Persist subtask idx=%d failed: %s", idx, e)

            # Execute
            r = await organism_execute(organ_id, subtask_dict, 5.0, cid)
            results.append({"organ_id": organ_id, **r})

        success = all(x.get("success") for x in results)
        latency_ms = (time.time() - t0) * 1000.0
        if hasattr(metrics, "track_metrics"):
            metrics.track_metrics("hgnn", success, latency_ms)

        return make_escalation_result(results, plan, success)

    except Exception as e:
        latency_ms = (time.time() - t0) * 1000.0
        if hasattr(metrics, "track_metrics"):
            metrics.track_metrics("escalation_failure", False, latency_ms)
        logger.exception("[HGNN] execution failed: %s", e)
        return {"success": False, "error": str(e), "path": "hgnn"}


# ---------------------------------------------------------------------------
# Route & Execute (orchestrator)
# ---------------------------------------------------------------------------
async def route_and_execute(
    *,
    task: Any,
    # decision
    normalize_task_dict: Callable[[Any], Tuple[Dict[str, Any], Dict[str, Any]]],
    decide_execution_path: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]],
    # common deps
    extract_agent_id: Callable[[Dict[str, Any]], Optional[str]],
    compute_drift_score: Callable[[Dict[str, Any], Any, Any], Awaitable[float]],
    organism_execute: Callable[[str, Dict[str, Any], float, str], Awaitable[Dict[str, Any]]],
    graph_task_repo: Any,
    ml_client: Any,
    predicate_router: Any,
    metrics: Any,
    cid: str,
    # routing utils
    resolve_route_cached: Callable[[str, Optional[str], Optional[str], str], Awaitable[Optional[str]]],
    static_route_fallback: Callable[[str, Optional[str]], str],
    normalize_type: Callable[[Optional[str]], str],
    normalize_domain: Callable[[Optional[str]], Optional[str]],
    # HGNN/planner deps (optional; only used if decision selects them)
    hgnn_decompose: Optional[Callable[[Any], Awaitable[List[Dict[str, Any]]]]] = None,
    bulk_resolve_func: Optional[Callable[[List[Dict[str, Any]], str], Awaitable[Dict[int, str]]]] = None,
    persist_plan_func: Optional[Callable[[Any, List[Dict[str, Any]], Optional[Any]], Awaitable[None]]] = None,
    planner_client: Optional[Any] = None,
    graph_sql_repo: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Decide execution path (fast / hgnn / planner) and delegate.

    `decide_execution_path(task_dict)` must return a dict like:
      {"decision": "fast" | "hgnn" | "planner", "proto_plan": <optional dict>}
    """
    task_dict, _meta = normalize_task_dict(task)
    decision_blob = await _maybe_call(decide_execution_path, task_dict) or {}
    decision = (decision_blob.get("decision") or "fast").lower()
    proto_plan = decision_blob.get("proto_plan")

    # --- HGNN path ------------------------------------------------------
    if decision == "hgnn":
        if not (hgnn_decompose and bulk_resolve_func and persist_plan_func):
            # fall back if HGNN deps are not wired
            decision = "fast"
        else:
            return await execute_hgnn(
                task=task,
                normalize_task_dict=normalize_task_dict,
                extract_agent_id=extract_agent_id,
                compute_drift_score=compute_drift_score,
                hgnn_decompose=hgnn_decompose,
                bulk_resolve_func=bulk_resolve_func,
                persist_plan_func=persist_plan_func,
                static_route_fallback=static_route_fallback,
                normalize_type=normalize_type,
                normalize_domain=normalize_domain,
                organism_execute=organism_execute,
                graph_task_repo=graph_task_repo,
                ml_client=ml_client,
                predicate_router=predicate_router,
                metrics=metrics,
                cid=cid,
            )

    # --- Planner-only follow-up (no immediate organ exec) ----------------
    if decision == "planner":
        followup = await dispatch_planner(task=task, proto_plan=proto_plan, planner_client=planner_client)
        return {
            "success": followup is not None,
            "path": "planner",
            **(followup or {}),
        }

    # --- Fast path (default) --------------------------------------------
    result = await execute_fast(
        task=task,
        normalize_task_dict=normalize_task_dict,
        extract_agent_id=extract_agent_id,
        compute_drift_score=compute_drift_score,
        resolve_route_cached=resolve_route_cached,
        static_route_fallback=static_route_fallback,
        normalize_type=normalize_type,
        normalize_domain=normalize_domain,
        organism_execute=organism_execute,
        graph_task_repo=graph_task_repo,
        ml_client=ml_client,
        predicate_router=predicate_router,
        cid=cid,
    )

    # Optional follow-up based on decision payload (e.g., planner/HGNN hints)
    if decision in ("planner", "hgnn"):
        follow = await dispatch_route_followup(
            decision=decision,
            task_payload=task,
            proto_plan=proto_plan,
            planner_client=planner_client,
            graph_sql_repo=graph_sql_repo,
        )
        if follow:
            result.setdefault("followup", follow)

    result.setdefault("path", "fast")
    return result


# ---------------------------------------------------------------------------
# Follow-ups (optional utilities)
# ---------------------------------------------------------------------------
async def dispatch_route_followup(
    *,
    decision: str,
    task_payload: Any,
    proto_plan: Optional[Dict[str, Any]],
    planner_client: Optional[Any] = None,
    graph_sql_repo: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    if decision == "planner":
        return await dispatch_planner(task=task_payload, proto_plan=proto_plan, planner_client=planner_client)
    if decision == "hgnn":
        return await dispatch_hgnn(task=task_payload, proto_plan=proto_plan, graph_sql_repo=graph_sql_repo)
    return None


async def dispatch_planner(
    *,
    task: Any,
    proto_plan: Optional[Dict[str, Any]],
    planner_client: Optional[Any],
) -> Optional[Dict[str, Any]]:
    if planner_client is None or not hasattr(planner_client, "execute_plan"):
        logger.debug("[Coordinator] Planner client unavailable; skipping planner dispatch")
        return None
    try:
        planner_result = await _maybe_call(
            planner_client.execute_plan,
            task=getattr(task, "model_dump", lambda: task)(),
            proto_plan=proto_plan,
        )
    except Exception as exc:
        logger.warning("[Coordinator] Planner dispatch failed for %s: %s", getattr(task, "task_id", "unknown"), exc)
        return {"planner_error": str(exc)}
    return {"planner_response": planner_result}


async def dispatch_hgnn(
    *,
    task: Any,
    proto_plan: Optional[Dict[str, Any]],
    graph_sql_repo: Optional[Any],
) -> Optional[Dict[str, Any]]:
    if proto_plan is None:
        return None
    if graph_sql_repo is None or not hasattr(graph_sql_repo, "create_task_async"):
        logger.debug("[Coordinator] Graph SQL repository unavailable; skipping HGNN dispatch")
        return None

    tasks = proto_plan.get("tasks") if isinstance(proto_plan, dict) else None
    if not isinstance(tasks, list):
        return None

    agent_id = None
    try:
        agent_id = task.params.get("agent_id") if hasattr(task, "params") and isinstance(task.params, dict) else None
    except Exception:
        agent_id = None

    created: List[Dict[str, Any]] = []
    allowed_types = {
        "graph_embed": "graph_embed",
        "graph_rag_query": "graph_rag_query",
        "graph_rag_seed": "graph_rag_query",
    }

    for entry in tasks:
        if not isinstance(entry, dict):
            continue
        task_type = (entry.get("type") or "").strip().lower()
        if task_type not in allowed_types:
            logger.debug("[Coordinator] Skipping unsupported HGNN task type '%s' for %s", task_type, getattr(task, "task_id", "unknown"))
            continue

        params = dict(entry.get("params") or {})
        description = entry.get("description") if isinstance(entry.get("description"), str) else None
        target_type = allowed_types[task_type]

        try:
            graph_task_id = await _maybe_call(
                graph_sql_repo.create_task_async,
                target_type,
                params,
                description,
                agent_id=agent_id,
                organ_id=params.get("organ_id"),
            )
            created.append({"type": target_type, "task_id": str(graph_task_id)})
        except Exception as exc:
            logger.warning("[Coordinator] Failed to create graph task for %s: %s", getattr(task, "task_id", "unknown"), exc)

    if not created:
        return None
    return {"graph_dispatch": {"graph_tasks": created}}


# ============================================================================
# PKG (Policy Graph Kernel) Evaluation
# ============================================================================

async def evaluate_pkg_plan(
    *,
    tags: Sequence[str],
    signals: Mapping[str, Any],
    context: Optional[Mapping[str, Any]] = None,
    timeout_s: int,
    log: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """Execute PKG evaluation using the global PKG manager and return its response.

    Args:
        tags: Collection of event tags associated with the task.
        signals: Numeric routing signals forwarded to the evaluator.
        context: Optional context dictionary supplied to the evaluator.
        timeout_s: Maximum time in seconds to wait for the evaluation (for compatibility, actual evaluation is synchronous).
        log: Logger used for debug information.
    """
    from .utils import _normalise_sequence_length, _coerce_pkg_result
    from ...ops.pkg.manager import get_global_pkg_manager
    
    logger = log or logger

    # Get the global PKG manager
    pkg_manager = get_global_pkg_manager()
    if pkg_manager is None:
        raise RuntimeError("PKG manager not initialized")

    # Get the active evaluator
    evaluator = pkg_manager.get_active_evaluator()
    if evaluator is None:
        raise RuntimeError("PKG evaluator not available (no active snapshot)")

    # Build task_facts dict for evaluator
    task_facts: Dict[str, Any] = {
        "tags": list(tags),
        "signals": dict(signals),
    }
    if context is not None:
        task_facts["context"] = dict(context)

    # Evaluate using the active evaluator (synchronous call)
    # Wrap in async for timeout compatibility
    async def _invoke() -> Mapping[str, Any]:
        return evaluator.evaluate(task_facts)

    pkg_res = await asyncio.wait_for(_invoke(), timeout=timeout_s)

    if not isinstance(pkg_res, Mapping):
        raise ValueError("PKG returned unexpected type")
    
    # Convert evaluator output format (subtasks/dag) to expected format (tasks/edges)
    if "subtasks" in pkg_res or "dag" in pkg_res:
        # Map subtasks -> tasks, dag -> edges
        pkg_res = {
            "tasks": pkg_res.get("subtasks", []),
            "edges": pkg_res.get("dag", []),
            "version": pkg_res.get("snapshot", evaluator.version)
        }
    
    if "tasks" not in pkg_res or "edges" not in pkg_res:
        raise ValueError("PKG returned unexpected shape")

    tasks_len = _normalise_sequence_length(pkg_res["tasks"])
    edges_len = _normalise_sequence_length(pkg_res["edges"])
    logger.debug(
        "PKG evaluation succeeded (tasks=%s, edges=%s)",
        tasks_len if tasks_len is not None else "?",
        edges_len if edges_len is not None else "?",
    )

    return _coerce_pkg_result(pkg_res)


# ============================================================================
# Forced Promotion Logic
# ============================================================================

def apply_forced_promotions(
    decision: str,
    params: Dict[str, Any]
) -> Tuple[str, Optional[str]]:
    """
    Applies operator overrides (forced promotions) to a routing decision.
    
    This logic handles force_hgnn and force_decomposition flags from task parameters.
    
    Args:
        decision: The original routing decision ('fast', 'planner', or 'hgnn').
        params: The task parameters, checked for 'force_hgnn'
                and 'force_decomposition' flags.

    Returns:
        A tuple of (final_decision, original_decision_if_changed).
        The second element is None if no promotion occurred.
    """
    
    # Honor force_decomposition: promote fast→planner or planner→hgnn
    force_decomp = params.get("force_decomposition", False)
    force_hgnn = params.get("force_hgnn", False)
    
    original_decision = decision
    
    if force_hgnn and decision != "hgnn":
        logger.info(f"[Coordinator] force_hgnn=True: promoting {decision} → hgnn")
        decision = "hgnn"
    elif force_decomp and decision == "fast":
        logger.info(f"[Coordinator] force_decomposition=True: promoting fast → planner")
        decision = "planner"
    
    # Determine if the decision was changed for reporting
    original_decision_if_changed = None
    if decision != original_decision:
        original_decision_if_changed = original_decision

    return (decision, original_decision_if_changed)


# ============================================================================
# Eventizer Summary and Payload Contract
# ============================================================================

def create_eventizer_summary(
    eventizer_data: Dict[str, Any],
    eventizer_tags: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Create a concise eventizer summary from eventizer data and tags.
    
    This avoids adding the full eventizer_data blob to the payload.
    
    Args:
        eventizer_data: Full eventizer processing results
        eventizer_tags: Extracted eventizer tags
        
    Returns:
        Compact eventizer summary dict or None if no eventizer data
    """
    if not eventizer_data:
        return None
        
    return {
        "event_tags": eventizer_tags.get("event_types") if eventizer_tags else None,
        "attributes": eventizer_data.get("attributes"),
        "confidence": eventizer_data.get("confidence"),
        "patterns_applied": eventizer_data.get("patterns_applied"),
        "pii_redacted": eventizer_data.get("pii_redacted"),
    }


def create_payload_common(
    *,
    task_id: str,
    task_type: str,
    domain: Optional[str],
    decision: str,
    last_decision: Optional[str],
    original_decision: Optional[str],
    surprise_data: Dict[str, Any],
    signals_present: List[str],
    pkg_meta: Dict[str, Any],
    used_fallback: bool,
    proto_plan: Optional[Dict[str, Any]],
    event_tags: Set[str],
    attributes: Dict[str, Any],
    confidence: Dict[str, Any],
    pii_redacted: bool,
    router_latency_ms: float,
    eventizer_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create the common payload structure used across all execution paths.
    
    This ensures consistent payload shape and mitigates nesting risks.
    
    Args:
        task_id: Task identifier
        task_type: Normalized task type
        domain: Task domain (may be None)
        decision: Final routing decision
        last_decision: Previous decision for hysteresis tracking
        original_decision: Original decision before forced promotions
        surprise_data: Complete surprise scoring data
        signals_present: List of present signal keys
        pkg_meta: PKG metadata
        used_fallback: Whether PKG fallback was used
        proto_plan: Optional proto plan
        event_tags: Set of event tags
        attributes: Merged attributes
        confidence: Merged confidence data
        pii_redacted: PII redaction flag
        router_latency_ms: Router processing latency
        eventizer_summary: Optional eventizer summary
        
    Returns:
        Common payload dictionary
    """
    payload_common = {
        "task_id": task_id,
        "type": task_type,
        "domain": domain,
        "decision": decision,
        "last_decision": last_decision,
        "original_decision": original_decision if decision != original_decision else None,
        "surprise": surprise_data,
        "signals_present": sorted(signals_present),
        "pkg": {
            "used": not used_fallback,
            "version": pkg_meta.get("version"),
            "error": pkg_meta.get("error")
        },
        "proto_plan": proto_plan,
        "event_tags": sorted(list(event_tags)),
        "attributes": attributes,
        "confidence": confidence,
        "pii_redacted": pii_redacted,
        "router_latency_ms": router_latency_ms,
        "payload_version": "router/1.2.0",
    }
    
    # Add eventizer summary if available
    if eventizer_summary is not None:
        payload_common["eventizer"] = eventizer_summary
        
    return payload_common


def create_fast_path_result(
    *,
    routed_to: str,
    organ_id: str,
    result: Dict[str, Any],
    metadata: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Create fast path result with payload_common nested in metadata.
    
    This maintains the expected nesting structure for fast path results.
    """
    return {
        "success": True,
        "path": "fast",
        "routed_to": routed_to,
        "organ_id": organ_id,
        "result": result,
        "metadata": metadata
    }


def create_escalated_result(
    *,
    solution_steps: List[Dict[str, Any]],
    plan_source: str,
    **payload_common
) -> Dict[str, Any]:
    """
    Create escalated result (planner/hgnn) with payload_common spread as kwargs.
    
    This avoids metadata nesting by spreading payload_common fields directly.
    """
    return {
        "success": True,
        "path": plan_source.split("_")[-1],  # Extract "planner" or "hgnn"
        "solution_steps": solution_steps,
        "plan_source": plan_source,
        **payload_common  # Spread to avoid nesting
    }
