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
)

from seedcore.agents.roles import Specialization
from seedcore.coordinator.core.ocps_valve import NeuralCUSUMValve
from seedcore.models.cognitive import CognitiveType, DecisionKind
from seedcore.models.task import TaskType
from seedcore.models.task_payload import TaskPayload
from seedcore.models.result_schema import (
    create_cognitive_path_result,
    create_error_result,
    create_fast_path_result,
)
from ..utils import extract_from_nested

from .policies import (
    SurpriseComputer,
)
from .signals import SignalEnricher

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
    ocps_valve: NeuralCUSUMValve
    tau_fast_exit: float
    tau_plan_exit: float
    signal_enricher: SignalEnricher | None = None
    evaluate_pkg_func: PkgEvalFn | None = None
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
    metrics: Any
    cid: str
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
    eventizer_helper: Callable[[Any], Any] | None = None


@dataclass
class RoutingIntent:
    """Internal DTO to hold the derived routing instructions."""

    specialization: Optional[str] = None  # The V2 'required_specialization'
    organ_hint: Optional[str] = None  # Optional 'target_organ_id'
    skills: Dict[str, float] = None  # V2 'skills'


def _derive_routing_intent(ctx: TaskContext) -> RoutingIntent:
    """
    Static Rule Engine: Maps Task Context -> Specialization/Skills.

    This replaces the complex PredicateRouter. It aligns with OrganismRouter's
    expectation for 'required_specialization' or 'specialization' keys.
    """
    tt = str(ctx.task_type).lower()
    domain = str(ctx.domain).lower() if ctx.domain else ""
    intent = RoutingIntent(skills={})

    # =========================================================
    # 1. CHAT / INTERACTION (User Experience)
    # =========================================================
    if tt == TaskType.CHAT.value:
        # Default: The User Liaison handles chat
        intent.specialization = Specialization.USER_LIAISON.value
        intent.skills = {"dialogue": 1.0, "empathy": 0.9}

        # Nuance: If domain is purely scheduling
        if "calendar" in domain or "schedule" in domain:
            intent.specialization = Specialization.SCHEDULE_ORACLE.value

    # =========================================================
    # 2. ACTION / EXECUTION (Orchestration & Robots)
    # =========================================================
    elif tt == TaskType.ACTION.value:
        if "iot" in domain or "device" in domain:
            intent.specialization = Specialization.DEVICE_ORCHESTRATOR.value
            intent.skills = {"iot_control": 1.0}
        elif "robot" in domain:
            intent.specialization = Specialization.ROBOT_COORDINATOR.value
        else:
            # Generic actions fall to the Device Orchestrator or Generalist
            intent.specialization = Specialization.DEVICE_ORCHESTRATOR.value

    # =========================================================
    # 3. GRAPH / SENSING (Environment)
    # =========================================================
    elif tt == TaskType.GRAPH.value:
        # If it's about the physical environment state
        if "sensor" in domain or "env" in domain:
            intent.specialization = Specialization.ENVIRONMENT_MODEL.value
        # If it's anomaly detection
        elif "anomaly" in domain or "security" in domain:
            intent.specialization = Specialization.ANOMALY_DETECTOR.value
        # General Knowledge Graph ops
        else:
            # Fallback to Generalist or a dedicated Knowledge Agent if you have one
            intent.specialization = Specialization.GENERALIST.value

    # =========================================================
    # 4. MAINTENANCE (System)
    # =========================================================
    elif tt == TaskType.MAINTENANCE.value:
        intent.specialization = Specialization.UTILITY.value  # or OBSERVER

    # =========================================================
    # 5. FALLBACK
    # =========================================================
    else:
        # Unknown types go to Generalist
        intent.specialization = Specialization.GENERALIST.value

    return intent


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
            ("decision_kind",),  # Primary
            ("decision",),  # Fallback
            ("payload", "metadata", "decision"),  # Legacy
            ("payload", "decision"),  # Legacy
        ],
        value_type=str,
    )


def _extract_proto_plan(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract 'proto_plan' from a cognitive result.
    """
    return extract_from_nested(
        payload,
        key_paths=[
            ("result", "proto_plan"),  # Standard Cognitive Result wrapper
            ("proto_plan",),  # Direct return
            ("metadata", "proto_plan"),
        ],
        value_type=dict,
    )


async def execute_task(
    task: TaskPayload, route_config: RouteConfig, execution_config: ExecutionConfig, 
) -> Dict[str, Any]:

    task_context = await _process_task_input(
        payload=task, 
        merged_dict=task.model_dump(),
        eventizer_helper=execution_config.eventizer_helper
    )
    # ---------------------------------------------------------
    # 1. COMPUTE DECISION (System 1 vs 2)
    # ---------------------------------------------------------
    routing_dec = await _compute_routing_decision(
        ctx=TaskContext.from_dict(task_context), cfg=route_config
    )

    decision_kind = routing_dec["decision_kind"]

    # The router already called .model_dump(), so this is a dict
    router_result_payload = routing_dec["result"]

    # ---------------------------------------------------------
    # 2. EXECUTE (Delegated)
    # ---------------------------------------------------------

    # --- PATH A: Fast Path (System 1) ---
    if decision_kind == DecisionKind.FAST_PATH.value:
        return await _handle_fast_path(
            task=task,
            routing_hints=router_result_payload.get("metadata", {}).get(
                "routing_params"
            ),
            config=execution_config,
        )

    # --- PATH B: Cognitive Path (System 2) ---
    elif decision_kind == DecisionKind.COGNITIVE.value:
        # Note: We likely pass the router_result_payload here too if the
        # cognitive handler needs the "Analysis/Plan" generated by the router.
        return await _handle_cognitive_path(
            task=task, 
            decision_payload=router_result_payload, 
            decision_kind=DecisionKind(decision_kind),
            config=execution_config
        )

    # --- PATH C: Fallback / Error (Defensive) ---
    else:
        # If the router explicitly returned an error kind, or an unknown kind.
        logger.warning(
            f"[Coordinator] Routing decision '{decision_kind}' not handled. "
            f"Returning raw router result."
        )

        # Directly return the dict. Do not call .model_dump() again.
        return router_result_payload


# =========================================================================
# HELPER: FAST PATH (System 1)
# =========================================================================


async def _handle_fast_path(
    task: TaskPayload,
    routing_hints: Dict[str, Any],
    config: ExecutionConfig,
) -> Dict[str, Any]:
    """
    Coordinator delegation:
    Forwards task to the Organism Service. The Organism (Execution Plane)
    is responsible for checking Tunnels (sticky sessions) or Routing (OCPS/Skills).
    """

    # 1. Prepare Payload
    # Convert Pydantic model to dict
    task_payload_dict = task.model_dump()

    # Inject routing hints into params.routing
    # The Organism Router will use these if no sticky tunnel exists.
    if routing_hints:
        params = task_payload_dict.setdefault("params", {})
        params["routing"] = routing_hints

    # 2. Execute via Organism Interface
    try:
        # Use a calculated timeout (SLO * buffer)
        timeout = config.fast_path_latency_slo_ms / 1000.0 * 2.0

        # We pass "organism" as the ID. The RPC layer must recognize this
        # as a request to the Load Balancer/Router, not a specific organ.
        response = await config.organism_execute(
            organ_id="organism",  # <--- Virtual ID for "Gateway"
            task_dict=task_payload_dict,  # <--- FIX: Renamed from 'payload' to match typical client sig
            timeout=timeout,
            cid_local=config.cid,
        )

        return response

    except Exception as e:
        logger.error(f"[Coordinator] Fast Path delegation failed: {e}")
        return create_error_result(str(e), "execution_error").model_dump()


# =========================================================================
# HELPER: COGNITIVE PATH (System 2)
# =========================================================================


async def _handle_cognitive_path(
    task: TaskPayload,
    decision_payload: Dict[str, Any],
    decision_kind: DecisionKind,
    config: ExecutionConfig,
) -> Dict[str, Any]:
    """
    Orchestrates the Cognitive Loop: Plan -> Persist -> Execute Subtasks.

    decision_payload is the CognitiveResult payload produced by the router, and
    is expected to contain:
      - "proto_plan": PKG-generated DAG (if any)
      - "pkg_meta": metadata about PKG evaluation (version, etc.)
      - "ocps": OCPS valve payload (drift, severity, etc.)
      - plus whatever else create_cognitive_result included.
    """
    if not config.cognitive_client:
        logger.error("[Coordinator] Cognitive Client missing.")
        return create_error_result("System 2 unavailable", "config_error").model_dump()

    try:
        # Extract router-provided meta
        proto_plan_from_router = decision_payload.get("proto_plan") or {}
        pkg_meta = decision_payload.get("pkg_meta") or {}
        ocps_payload = decision_payload.get("ocps") or decision_payload.get(
            "ocps_payload", {}
        )

        # 1. Call Cognitive Service (The "Think" Step)
        # ---------------------------------------------
        # We forward the PKG proto-plan + OCPS so the cognitive service
        # can refine or expand it instead of planning from scratch.
        plan_res = await config.cognitive_client.execute_async(
            agent_id="system_2_core",  # Virtual ID
            cog_type=CognitiveType.TASK_PLANNING,
            decision_kind=decision_kind,
            task=task,
            proto_plan=proto_plan_from_router or None,
            pkg_meta=pkg_meta or None,
            ocps=ocps_payload or None,
        )

        # 2. Persist Proto-Plan (PKG-first, fallback to Cognitive plan)
        # ---------------------------------------------
        proto_plan_to_persist = (
            proto_plan_from_router
            if proto_plan_from_router
            else _extract_proto_plan(plan_res)
        )

        if proto_plan_to_persist and config.persist_proto_plan_func:
            await config.persist_proto_plan_func(
                config.graph_task_repo,
                task.task_id,
                decision_kind,
                proto_plan_to_persist,
            )

        # 3. Execute Solution Steps (The "Act" Step)
        # ---------------------------------------------
        solution_steps = _extract_solution_steps(plan_res)

        if not solution_steps:
            # No executable steps (maybe cognitive agent returned a direct answer)
            return plan_res

        logger.info(
            f"[Coordinator] System 2 executing {len(solution_steps)} steps for task {task.task_id}."
        )
        step_results = []

        for i, step in enumerate(solution_steps):
            # Convert step -> child task payload
            step_task_dict, organ_hint = _prepare_step_task_payload(
                parent_task=task, step=step, index=i, cid=config.cid
            )

            step_res = await config.organism_execute(
                organ_id=organ_hint or "organism",
                task_dict=step_task_dict,
                timeout=config.fast_path_latency_slo_ms / 1000.0 * 2.0,
                cid_local=config.cid,
            )

            step_results.append({"step": i, "result": step_res})

            if not step_res.get("success"):
                logger.error(
                    f"[Coordinator] Step {i} failed for task {task.task_id}. Stopping plan."
                )
                break

        # 4. Aggregate & Return
        # ---------------------------------------------
        final_res = _aggregate_execution_results(
            parent_task_id=task.task_id,
            solution_steps=solution_steps,
            step_results=step_results,
            decision_kind=decision_kind,
        )

        return final_res

    except Exception as e:
        logger.error(f"[Coordinator] Cognitive Path failed: {e}", exc_info=True)
        return create_error_result(str(e), "cognitive_error").model_dump()


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


def _prepare_step_task_payload(
    parent_task: TaskPayload, step: Dict[str, Any], index: int, cid: str | None
) -> Tuple[Dict[str, Any], str]:
    """Prepares a single sub-task payload (DICT) with full context inheritance."""

    # 1. Unwrap Step (Child is always a dict from JSON)
    raw_task = step.get("task", step)
    step_task = dict(raw_task)

    # Ensure params exists in child
    if "params" not in step_task:
        step_task["params"] = {}

    # 2. Resolve Parent Context (Parent is TaskPayload Object)
    # We must dump the parent params to a dict to merge them safely
    parent_params = dict(parent_task.params or {})
    parent_id = parent_task.task_id

    # 3. Inherit Routing (Policy)
    parent_routing = dict(parent_params.get("routing", {}))
    child_routing = step_task["params"].get("routing", {})
    # Child routing overrides parent routing
    step_task["params"]["routing"] = {**parent_routing, **child_routing}

    # 4. Inherit Interaction (Sticky Sessions)
    parent_interaction = dict(parent_params.get("interaction", {}))
    child_interaction = step_task["params"].get("interaction", {})
    step_task["params"]["interaction"] = {**parent_interaction, **child_interaction}

    # 5. Context Injection
    step_task["params"]["parent_task_id"] = parent_id
    step_task["params"]["step_index"] = index
    if cid:
        step_task.setdefault("correlation_id", cid)

    # Ensure type is set (default to action if missing)
    if "type" not in step_task and "task_type" not in step_task:
        step_task["type"] = "action"

    # 6. Target Resolution
    # Priority: Step explicit organ -> Routing hint -> Fallback
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
    Compute routing decision (System 1 vs System 2).
    """
    t0 = time.perf_counter()
    params = ctx.params or {}

    # ------------------------------------------------------------------
    # 1. OCPS Valve Update (Drift Detection)
    # ------------------------------------------------------------------
    raw_drift = float(params.get("ocps", {}).get("uncertainty_score", 0.0))
    drift_state = cfg.ocps_valve.update(raw_drift)
    is_escalated = drift_state.is_breached

    # Determine kind
    decision_kind = (
        DecisionKind.COGNITIVE.value if is_escalated else DecisionKind.FAST_PATH.value
    )
    path_label = "system_2_escalation" if is_escalated else "system_1_reflex"

    # ------------------------------------------------------------------
    # 2. Intent Resolution
    # ------------------------------------------------------------------
    intent = _derive_routing_intent(ctx)
    target_organ = intent.organ_hint or "organism"

    # ------------------------------------------------------------------
    # 3. System 2 Conditional Execution (PKG)
    # ------------------------------------------------------------------
    # Initialize defaults (as if Fast Path)
    pkg_meta = {"evaluated": False}
    proto_plan = {}

    # Only run PKG logic if escalated
    if is_escalated:
        pkg_meta, proto_plan = await _try_run_pkg_evaluation(
            ctx, cfg, intent, raw_drift, drift_state
        )

    # ------------------------------------------------------------------
    # 4. Unified Payload Construction
    # ------------------------------------------------------------------
    router_latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    # Common metadata shared by both result types
    payload_common = _create_payload_common(
        task_id=ctx.task_id,
        decision_kind=decision_kind,
        path_label=path_label,
        pkg_meta=pkg_meta,
        proto_plan=proto_plan,
        router_latency_ms=router_latency_ms,
        correlation_id=correlation_id,
        ocps_payload={
            "drift": raw_drift,
            "cusum_score": drift_state.score,
            "breached": drift_state.is_breached,
            "severity": drift_state.severity,
        },
    )

    # ------------------------------------------------------------------
    # 5. Result Factory (Polymorphic)
    # ------------------------------------------------------------------
    if is_escalated:
        # System 2: Cognitive Result
        task_result = create_cognitive_path_result(
            task_type=ctx.task_type,
            result={
                "status": "escalated_by_ocps",
                "drift_severity": drift_state.severity,
                "intended_specialization": intent.specialization,
            },
            **payload_common,
        )
    else:
        # System 1: Fast Path Result
        task_result = create_fast_path_result(
            target_organ_id=target_organ,
            routing_params={
                "required_specialization": intent.specialization,
                "skills": intent.skills or {},
            },
            interaction_mode="coordinator_routed",
            processing_time_ms=router_latency_ms,
            **payload_common,
        )

    return {
        "decision_kind": decision_kind,
        "result": task_result.model_dump(),
        "organ_id": target_organ,
    }


# ------------------------------------------------------------------
# Helper to isolate the messy PKG signal extraction
# ------------------------------------------------------------------
async def _try_run_pkg_evaluation(
    ctx: TaskContext, cfg: RouteConfig, intent: Any, raw_drift: float, drift_state: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Safely executes PKG evaluation. Returns (pkg_meta, proto_plan).
    """
    pkg_meta = {"evaluated": False}
    proto_plan = {}

    try:
        # 1. Base Signals
        pkg_signals = {
            "ocps_drift": raw_drift,
            "ocps_cusum": drift_state.score,
            "ocps_breached": drift_state.is_breached,
            "ocps_severity": drift_state.severity,
        }

        # 2. Enrich Signals (Optional)
        signal_enricher = getattr(cfg, "signal_enricher", None)
        if signal_enricher:
            try:
                task_obj = getattr(ctx, "task_payload", ctx)
                extra = await signal_enricher.compute_contextual_signals(
                    intent, task_obj
                )
                if isinstance(extra, dict):
                    pkg_signals.update(extra)
            except Exception as se:
                logger.debug(f"[Router] SignalEnricher warning: {se}")

        # 3. Evaluate PKG
        pkg_res = await cfg.evaluate_pkg_func(
            tags=list(ctx.tags),
            signals=pkg_signals,
            context={
                "domain": ctx.domain,
                "type": ctx.task_type,
                "task_id": ctx.task_id,
                "intended_specialization": intent.specialization,
                "organ_hint": intent.organ_hint,
            },
            timeout_s=cfg.pkg_timeout_s,
        )

        proto_plan = pkg_res or {}
        pkg_meta = {"evaluated": True, "version": proto_plan.get("version")}

    except Exception as e:
        logger.debug(f"[Router] PKG evaluation skipped: {e}")

    return pkg_meta, proto_plan


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
