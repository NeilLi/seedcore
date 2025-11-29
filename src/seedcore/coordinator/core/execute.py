"""
Core execution orchestration for:
- Fast path (direct organism delegation)
- Planner path (cognitive service delegation + step execution)
- Routing decisions (Surprise Score + PKG evaluation)

This module focuses purely on Routing Policy computation and Orchestration.
It allows the Coordinator Service (Tier-0) to drive the Execution Plane (Tier-1).
"""

from __future__ import annotations

import inspect
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Callable, Awaitable, Sequence, Mapping, Optional

from seedcore.models.cognitive import CognitiveType, DecisionKind
from seedcore.models.task_payload import TaskPayload
from seedcore.models.result_schema import (
    create_cognitive_result,
    create_error_result,
    create_fast_path_result,
)
from ..utils import extract_from_nested

from .policies import (
    SurpriseComputer,
    decide_route_with_hysteresis,
)

logger = logging.getLogger(__name__)

# Tunables
DEFAULT_ORGAN_TIMEOUT_S = 30.0
MIN_ORGAN_TIMEOUT_S = 1.0
MAX_ORGAN_TIMEOUT_S = 300.0


# ---------------------------------------------------------------------------
# Configuration Objects
# ---------------------------------------------------------------------------

PkgEvalFn = Callable[
    [Sequence[str], Mapping[str, Any], Mapping[str, Any] | None, int],
    Awaitable[dict[str, Any]],
]


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
    """Routing decision_kind configuration."""

    surprise_computer: SurpriseComputer
    tau_fast_exit: float
    tau_plan_exit: float
    evaluate_pkg_func: PkgEvalFn
    ood_to01: Callable[[float], float] | None = None
    pkg_timeout_s: int = 2


@dataclass(frozen=True)
class ExecutionConfig:
    """Configuration for task execution dependencies."""

    compute_drift_score: Callable[[dict[str, Any], Any, Any], Awaitable[float]]
    organism_execute: Callable[
        [str, dict[str, Any], float, str], Awaitable[dict[str, Any]]
    ]
    graph_task_repo: Any
    ml_client: Any
    predicate_router: Any
    metrics: Any
    cid: str
    resolve_route_cached: Callable[
        [str, str | None, str | None, str], Awaitable[str | None]
    ]
    static_route_fallback: Callable[[str, str | None], str]
    normalize_type: Callable[[str | None], str]
    normalize_domain: Callable[[str | None], str | None]

    # Dependencies for Cognitive Execution Loop
    cognitive_client: Any | None = None
    persist_proto_plan_func: (
        Callable[[Any, str, str, dict[str, Any]], Awaitable[None]] | None
    ) = None
    record_router_telemetry_func: (
        Callable[[Any, str, dict[str, Any]], Awaitable[None]] | None
    ) = None
    resolve_session_factory_func: Callable[[Any], Any] | None = None
    fast_path_latency_slo_ms: float = 5000.0
    tunnel_lookup: Callable[[str], Awaitable[dict[str, Any] | None]] | None = None
    tunnel_store: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None


# ---------------------------------------------------------------------------
# Internal Helpers (Extraction)
# ---------------------------------------------------------------------------

def _extract_decision(route_result: Dict[str, Any]) -> Optional[str]:
    """
    Extract 'decision' from a route result dict using robust nested lookup.
    """
    return extract_from_nested(
        route_result,
        key_paths=[
            ("decision_kind",),                 # Primary
            ("decision",),                      # Fallback
            ("payload", "metadata", "decision"), # Legacy
            ("payload", "decision"),            # Legacy
        ],
        value_type=str
    )


def _extract_proto_plan(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract 'proto_plan' from a cognitive result.
    """
    return extract_from_nested(
        payload,
        key_paths=[
            ("result", "proto_plan"),  # Standard Cognitive Result wrapper
            ("proto_plan",),           # Direct return
            ("metadata", "proto_plan"),
        ],
        value_type=dict
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def route_and_execute(
    *,
    task: TaskPayload,
    eventizer_helper: Callable[[Any], Any] | None = None,
    routing_config: RouteConfig,
    execution_config: ExecutionConfig,
) -> Dict[str, Any]:
    """
    Unified route and execute: computes routing decision and executes accordingly.
    
    Args:
        task: Strongly typed TaskPayload (already normalized by upstream service).
    """
    # 0. Tunnel Fast-Path (conversation affinity override)
    correlation_id = execution_config.cid
    conversation_id = task.conversation_id

    if conversation_id and execution_config.tunnel_lookup:
        tunnel = await execution_config.tunnel_lookup(conversation_id)
        if tunnel:
            
            # 🚇 Force routing: Use tunnel's agent & organ directly
            organ_id = tunnel["organ_id"]
            agent_id = tunnel["agent_id"]
            logger.info(f"[Coordinator] 🚇 Tunnel hit: {conversation_id} → {agent_id} in {organ_id}")

            # Execute directly via Organism
            task_dict = task.model_dump()
            execution_response = await execution_config.organism_execute(
                organ_id=organ_id,
                task_dict=task_dict,
                timeout=execution_config.fast_path_latency_slo_ms / 1000.0 * 2,
                cid_local=conversation_id,
            )

            # If Organism returns updated tunnel info, store it
            if execution_response.get("tunnel_active"):
                if execution_config.tunnel_store:
                    await execution_config.tunnel_store(conversation_id, execution_response)

            return execution_response

    # 1. Context Processing
    # We generate the dict representation once for Eventizer/Helpers
    task_dict = task.model_dump()

    task_ctx_data = await _process_task_input(
        payload=task,
        merged_dict=task_dict,
        eventizer_helper=eventizer_helper,
    )
    ctx = TaskContext.from_dict(task_ctx_data)

    # 2. Compute Routing Decision (System 2)
    routing_result = await _compute_routing_decision(
        ctx=ctx,
        cfg=routing_config,
        correlation_id=correlation_id,
    )

    decision = _extract_decision(routing_result)
    if not decision:
        decision = routing_result.get("decision_kind", DecisionKind.ERROR.value)

    # Extract agent_id for cognitive calls
    agent_id = task.params.get("cognitive", {}).get("agent_id") or \
               task.params.get("agent_id", "unknown")

    # 3. Handle Decision Execution

    # --- PATH A: Cognitive / Escalated Path ---
    if decision in [DecisionKind.COGNITIVE.value, DecisionKind.ESCALATED.value]:
        if not execution_config.cognitive_client:
            logger.error("[route] Cognitive client not available.")
            return routing_result["result"]

        try:
            # A1. THINK (Call Cognitive Service)
            decision_enum = DecisionKind(decision)
            cog_type = CognitiveType.TASK_PLANNING
            if decision == DecisionKind.ESCALATED.value:
                # Escalated means we need deep problem solving/HGNN
                cog_type = CognitiveType.PROBLEM_SOLVING

            # Pass the strongly typed TaskPayload object
            plan_res = await execution_config.cognitive_client.execute_async(
                agent_id=agent_id,
                cog_type=cog_type,
                decision_kind=decision_enum,
                task=task,
            )

            # A2. PERSIST (Save Proto-Plan)
            proto_plan = _extract_proto_plan(plan_res)
            if proto_plan and execution_config.persist_proto_plan_func:
                try:
                    await execution_config.persist_proto_plan_func(
                        execution_config.graph_task_repo,
                        task.task_id,
                        decision,
                        proto_plan,
                    )
                except Exception as exc:
                    logger.warning(f"[route] Failed to persist proto-plan: {exc}")

            # A3. ACT (Execute Steps)
            solution_steps = _extract_solution_steps(plan_res)

            if solution_steps:
                logger.info(
                    f"[route] Executing {len(solution_steps)} steps for {task.task_id}"
                )
                step_results = []

                for i, step in enumerate(solution_steps):
                    try:
                        # Prepare Sub-Task with Inheritance
                        step_task, organ_hint = _prepare_step_task_payload(
                            parent_task=task, 
                            step=step, 
                            index=i, 
                            cid=correlation_id
                        )

                        # Execute via Organism (Fast Path)
                        timeout = execution_config.fast_path_latency_slo_ms / 1000.0 * 2

                        step_result = await execution_config.organism_execute(
                            organ_id=organ_hint,
                            task_dict=step_task,
                            timeout=timeout,
                            cid_local=correlation_id or str(uuid.uuid4()),
                        )

                        step_results.append(
                            {"step_index": i, "step": step, "result": step_result}
                        )

                        # Stop on failure (Strict consistency)
                        if not step_result.get("success", False):
                            logger.error(f"[route] Step {i} failed. Aborting plan.")
                            break

                    except Exception as step_exc:
                        logger.error(f"[route] Step {i} exception: {step_exc}")
                        step_results.append({"step_index": i, "error": str(step_exc)})
                        break

                # Aggregate Final Result
                planner_meta = (
                    plan_res.get("metadata", {}) if isinstance(plan_res, dict) else {}
                )
                res = _aggregate_execution_results(
                    parent_task_id=task.task_id,
                    solution_steps=solution_steps,
                    step_results=step_results,
                    decision_kind=decision,
                    original_meta=planner_meta,
                )

                # 🚇 Check for tunnel activation
                if conversation_id and res.get("tunnel_active"):
                    if execution_config.tunnel_store:
                        await execution_config.tunnel_store(conversation_id, res)

                return res

            # If no steps, just return the plan (Thought without Action)
            plan_res_final = plan_res
            
            # 🚇 Check for tunnel activation
            if conversation_id and plan_res_final.get("tunnel_active"):
                if execution_config.tunnel_store:
                    await execution_config.tunnel_store(conversation_id, plan_res_final)
            
            return plan_res_final

        except Exception as exc:
            logger.error(f"[route] Cognitive path failed: {exc}", exc_info=True)
            return routing_result["result"]

    # --- PATH B: Fast Path (Reflex) ---
    if decision == DecisionKind.FAST_PATH.value:
        result_data = routing_result.get("result", {})
        target_organ = (
            result_data.get("organ_id") or routing_result.get("organ_id") or "organism"
        )

        try:
            # Inject hint if specific organ was resolved
            # We use task_dict (dict form) for the organism call
            task_dict_copy = dict(task_dict)
            if target_organ and target_organ not in ("organism", "random"):
                task_dict_copy.setdefault("params", {})
                task_dict_copy["params"].setdefault("routing", {})
                task_dict_copy["params"]["routing"]["target_organ_hint"] = target_organ

            timeout = execution_config.fast_path_latency_slo_ms / 1000.0 * 2

            # Execute via Organism
            execution_response = await execution_config.organism_execute(
                organ_id=target_organ,
                task_dict=task_dict_copy,
                timeout=timeout,
                cid_local=correlation_id or str(uuid.uuid4()),
            )
            final_result = execution_response

            # 🚇 Check for tunnel activation
            if conversation_id and execution_response.get("tunnel_active"):
                if execution_config.tunnel_store:
                    await execution_config.tunnel_store(conversation_id, execution_response)

        except Exception as e:
            logger.error(f"[route] Fast path execution failed: {e}")
            final_result = create_error_result(
                f"Execution failed: {str(e)}", "execution_error"
            ).model_dump()

        # Persist Telemetry (Routing Decision vs Execution Result)
        if execution_config.record_router_telemetry_func:
            try:
                await execution_config.record_router_telemetry_func(
                    execution_config.graph_task_repo, task.task_id, routing_result
                )
            except Exception as exc:
                logger.warning(f"[route] Telemetry failed: {exc}")

        return final_result

    # --- PATH C: Fallback ---
    return routing_result["result"]


# ---------------------------------------------------------------------------
# Helper Functions (Data Processing)
# ---------------------------------------------------------------------------


def _extract_solution_steps(plan_res: Any) -> List[Dict[str, Any]]:
    """Safely extract solution steps from a cognitive planning result."""
    if not isinstance(plan_res, dict):
        return []
    result_data = plan_res.get("result", {})
    if not isinstance(result_data, dict):
        # Handle cases where plan_res IS the result data
        result_data = plan_res 
        
    steps = result_data.get("solution_steps") or result_data.get("steps")
    return steps if isinstance(steps, list) else []


def _prepare_step_task_payload(
    parent_task: TaskPayload, step: Dict[str, Any], index: int, cid: str | None
) -> Tuple[Dict[str, Any], str]:
    """Prepares a single sub-task payload with full context inheritance."""

    # 1. Unwrap Step
    raw_task = step.get("task", step)
    step_task = dict(raw_task)
    if "params" not in step_task:
        step_task["params"] = {}

    # 2. Resolve Parent Context
    parent_params = parent_task.params
    parent_id = parent_task.task_id

    # 3. Inherit Routing (Policy)
    parent_routing = parent_params.get("routing", {})
    child_routing = step_task["params"].get("routing", {})
    step_task["params"]["routing"] = {**parent_routing, **child_routing}

    # 4. Inherit Interaction (Sticky Sessions)
    parent_interaction = parent_params.get("interaction", {})
    child_interaction = step_task["params"].get("interaction", {})
    step_task["params"]["interaction"] = {**parent_interaction, **child_interaction}

    # 5. Context
    step_task["params"]["parent_task_id"] = parent_id
    step_task["params"]["step_index"] = index
    if cid:
        step_task.setdefault("correlation_id", cid)
        
    # Ensure type is set
    if "type" not in step_task and "task_type" not in step_task:
        step_task["type"] = "action"

    # 6. Target
    organ_hint = (
        step.get("organ_id")
        or step_task["params"]["routing"].get("target_organ_hint")
        or "organism"
    )

    return step_task, organ_hint


def _aggregate_execution_results(
    parent_task_id: str,
    solution_steps: List,
    step_results: List,
    decision_kind: str,
    original_meta: Dict = None,
) -> Dict[str, Any]:
    """Formats the final aggregated result."""
    # Check top level success or nested result.success
    all_succeeded = all(r.get("success", False) for r in step_results)

    aggregated = {
        "success": all_succeeded,
        "result": {
            "plan": {
                "parent_task_id": parent_task_id,
                "total_steps": len(solution_steps),
                "completed_steps": len(step_results),
                "steps": step_results,
            },
        },
        "metadata": {
            "decomposition": True,
            "decision_kind": decision_kind,
        },
    }
    if original_meta:
        aggregated["metadata"].update(original_meta)
    return aggregated


# ---------------------------------------------------------------------------
# Internal Logic (Surprise / PKG)
# ---------------------------------------------------------------------------


async def _compute_routing_decision(
    *,
    ctx: TaskContext,
    cfg: RouteConfig,
    correlation_id: str | None = None,
) -> Dict[str, Any]:
    """
    Compute routing decision using surprise score, PKG evaluation, and hysteresis.
    """
    t0 = time.perf_counter()
    params = ctx.params

    # 1. Extract Signals
    signals = {
        "mw_hit": params.get("cache", {}).get("mw_hit"),
        "ocps": params.get("ocps", {}),
        "ood_dist": params.get("ood_dist"),
        "ood_to01": cfg.ood_to01,
        "graph_delta": params.get("graph_delta"),
        "mu_delta": params.get("mu_delta"),
        "dep_probs": params.get("dependency_probs"),
        "est_runtime": params.get("est_runtime"),
        "SLO": params.get("slo"),
        "kappa": params.get("kappa"),
        "criticality": params.get("criticality"),
        # Pass EventTags for Semantic Urgency (x6)
        "event_tags": {
            "event_types": list(ctx.eventizer_tags.get("event_types", [])),
            "priority": ctx.eventizer_tags.get("priority", 0),
            "urgency": ctx.eventizer_tags.get("urgency", "normal"),
        },
    }

    # 2. Compute Surprise (S)
    s_out = cfg.surprise_computer.compute(signals)
    S = s_out["S"]

    # 3. Decide Route (Hysteresis)
    last_decision = params.get("last_decision")
    decision_kind = decide_route_with_hysteresis(
        S,
        last_decision,
        cfg.surprise_computer.tau_fast,
        cfg.tau_fast_exit,
        cfg.surprise_computer.tau_plan,
        cfg.tau_plan_exit,
    )

    # 4. PKG Evaluation
    pkg_meta = {"evaluated": False}
    proto_plan = {}

    try:
        task_facts_context = {
            "domain": ctx.domain,
            "type": ctx.task_type,
            "task_id": ctx.task_id,
        }
        # Run PKG
        pkg_res = await cfg.evaluate_pkg_func(
            tags=list(ctx.tags),
            signals=s_out["x"],  # Pass raw features
            context=task_facts_context,
            timeout_s=cfg.pkg_timeout_s,
        )
        proto_plan = pkg_res
        pkg_meta["evaluated"] = True
    except Exception as e:
        logger.debug(f"PKG evaluation skipped: {e}")

    # 5. Payload Construction
    router_latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    payload_common = _create_payload_common(
        task_id=ctx.task_id,
        decision_kind=decision_kind,
        surprise_data=s_out,
        pkg_meta=pkg_meta,
        proto_plan=proto_plan,
        router_latency_ms=router_latency_ms,
        correlation_id=correlation_id,
    )

    # 6. Result
    if decision_kind == DecisionKind.FAST_PATH.value:
        res = create_fast_path_result(
            routed_to="organism",
            organ_id="organism",
            result={"status": "routed"},
            metadata=payload_common,
        ).model_dump()
    else:
        # Cognitive / Escalated
        res = create_cognitive_result(
            agent_id="planner",
            task_type=ctx.task_type,
            result={"proto_plan": proto_plan},
            **payload_common,
        ).model_dump()

    return {
        "decision_kind": decision_kind,
        "result": res,
        "organ_id": "organism",  # Default target
    }


async def _process_task_input(
    *,
    payload: TaskPayload,
    merged_dict: Dict[str, Any],
    eventizer_helper: Callable[[Any], Any] | None = None,
) -> Dict[str, Any]:
    """Extracts context, running Eventizer via helper if needed."""
    
    # Run Eventizer (System 1)
    eventizer_data = {}
    if eventizer_helper:
        try:
            res = eventizer_helper(merged_dict)
            if inspect.isawaitable(res):
                res = await res
            eventizer_data = res or {}
        except Exception:
            pass

    # Extract Tags
    tags = set(eventizer_data.get("event_tags", {}).get("event_types", []))

    return {
        "task_id": payload.task_id,
        "task_type": payload.type,
        "domain": payload.domain,
        "params": merged_dict.get("params", {}),
        "eventizer_data": eventizer_data,
        "eventizer_tags": eventizer_data.get("event_tags", {}),
        "tags": tags,
        "attributes": eventizer_data.get("attributes", {}),
        "confidence": eventizer_data.get("confidence", {}),
        "pii_redacted": eventizer_data.get("pii_redacted", False),
        "fact_reads": [],
        "fact_produced": [],
    }


def _create_payload_common(**kwargs):
    """Simple wrapper to standardize metadata output."""
    return kwargs