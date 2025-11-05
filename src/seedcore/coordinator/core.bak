"""
CoordinatorCore façade

This module provides a thin, stable orchestration layer that delegates
all business logic to submodules in `coordinator.core`:

- utils.py         : normalization, redaction, identifier helpers
- policies.py      : drift/energy scoring policies
- routing.py       : route resolution with cache support
- plan.py          : plan persistence & dependency registration
- execute.py       : execution orchestration (fast/HGNN/route-and-execute)
- telemetry.py     : telemetry recording & embedding enqueue glue
- storage.py       : job state helpers backed by pluggable storage

The goal is to keep the service (Ray/FastAPI adapters) very thin while
exposing a single class with a cohesive API for dependency injection.

Notes:
- No direct HTTP/DB calls live here; those are injected callables/DAOs.
- The façade offers sync wrappers that await async submodule functions
  when needed (see `_maybe_call`).
- Avoids importing server frameworks to prevent circular imports.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union, Set
import inspect
import logging

logger = logging.getLogger(__name__)

# Submodule imports (all logic resides here)
from .core import (
    utils as core_utils,
    policies as core_policies,
    routing as core_routing,
    plan as core_plan,
    execute as core_execute,
    telemetry as core_telemetry,
    storage as core_storage,
)

# Import models for type hints and validation
from .models import AnomalyTriageRequest, AnomalyTriageResponse, TuneCallbackRequest
from seedcore.models import TaskPayload, Task

# Import routing cache from routing module
from .core.routing import RouteCache, RouteEntry


CallableOrAwaitable = Union[Callable[..., Any], Awaitable[Any]]


def _is_coro(obj: Any) -> bool:
    return inspect.isawaitable(obj) or inspect.iscoroutinefunction(obj)


async def _maybe_call(fn: CallableOrAwaitable, *args, **kwargs):
    """Call a function that may be sync or async, awaiting if needed."""
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    res = fn(*args, **kwargs)
    if inspect.isawaitable(res):
        return await res
    return res


class CoordinatorCore:
    """Thin façade that composes `coordinator.core` submodules.

    All heavy logic lives in the submodules; this class wires them and
    exposes a compact API expected by the service.
    """

    # -------- Utils -----------------------------------------------------
    def normalize_task_dict(self, task: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        return core_utils.normalize_task_dict(task)

    def canonicalize_identifier(self, x: Any) -> str:
        return core_utils.canonicalize_identifier(x)

    def redact_sensitive(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return core_utils.redact_sensitive_data(data)

    def extract_proto_plan(self, response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return core_utils.extract_proto_plan(response)

    def extract_decision(self, response: Dict[str, Any]) -> Optional[str]:
        return core_utils.extract_decision(response)

    # -------- Model utilities ------------------------------------------------
    def create_task_payload(self, task_type: str, params: Dict[str, Any], 
                          description: str = "", domain: Optional[str] = None, 
                          drift_score: float = 0.0, task_id: Optional[str] = None) -> TaskPayload:
        """Create a TaskPayload from individual parameters."""
        if task_id is None:
            import uuid
            task_id = str(uuid.uuid4())
        return TaskPayload(
            type=task_type,
            params=params,
            description=description,
            domain=domain,
            drift_score=drift_score,
            task_id=task_id
        )

    def create_task(self, task_type: str, params: Dict[str, Any], 
                   description: str = "", domain: Optional[str] = None,
                   features: Dict[str, Any] = None, history_ids: List[str] = None) -> Task:
        """Create a Task from individual parameters."""
        return Task(
            type=task_type,
            description=description,
            params=params,
            domain=domain,
            features=features or {},
            history_ids=history_ids or []
        )

    def validate_task_payload(self, payload: Dict[str, Any]) -> TaskPayload:
        """Validate and convert dict to TaskPayload."""
        return TaskPayload(**payload)

    def validate_task(self, task_data: Dict[str, Any]) -> Task:
        """Validate and convert dict to Task."""
        return Task(**task_data)

    # -------- Policies --------------------------------------------------
    def compute_fallback_drift_score(self, task: Dict[str, Any]) -> float:
        return core_policies.compute_fallback_drift_score(task)

    def get_current_energy_state(
        self,
        agent_id: str,
        provider: Optional[Callable[..., Optional[float]]] = None,
    ) -> Optional[float]:
        return core_policies.get_current_energy_state(agent_id, provider)

    def compute_surprise_score(self, signals: Dict[str, Any]) -> Dict[str, Any]:
        """Compute surprise score for routing decisions."""
        return core_policies.compute_surprise_score(signals)

    def create_ocps_valve(self, nu: float = 0.1, h: Optional[float] = None) -> Any:
        """Create OCPS valve for drift detection."""
        return core_policies.create_ocps_valve(nu, h)

    def decide_route_with_hysteresis(
        self,
        surprise_score: float,
        last_decision: Optional[str] = None,
        fast_enter: float = 0.35,
        fast_exit: float = 0.38,
        plan_enter: float = 0.60,
        plan_exit: float = 0.57
    ) -> str:
        """Make routing decision with hysteresis."""
        return core_policies.decide_route_with_hysteresis(
            surprise_score, last_decision, fast_enter, fast_exit, plan_enter, plan_exit
        )

    def generate_proto_subtasks(
        self,
        tags: Set[str],
        x6: float,
        criticality: float,
        force: bool = False
    ) -> Dict[str, Any]:
        """Generate proto subtasks based on domain tags."""
        return core_policies.generate_proto_subtasks(tags, x6, criticality, force)

    # -------- Routing ---------------------------------------------------
    async def bulk_resolve_routes_cached(
        self,
        steps: List[Dict[str, Any]],
        correlation_id: str,
        route_cache: Any,
        resolve_func: Callable[[List[Dict[str, Any]]], Awaitable[Dict[str, Any]]],
    ) -> Dict[int, str]:
        return await core_routing.bulk_resolve_routes_cached(
            steps, correlation_id, route_cache, resolve_func, None, None
        )

    # -------- Plan persistence & dependencies --------------------------
    async def persist_and_register_dependencies(
        self,
        plan: List[Dict[str, Any]],
        repo: Any,  # abstract GraphTaskRepository (sync or async)
    ) -> List[Dict[str, Any]]:
        return await core_plan.persist_and_register_dependencies(plan, repo, None, None)

    # -------- Execution orchestration ----------------------------------
    async def execute_fast(self, *args, **kwargs) -> Dict[str, Any]:
        return await core_execute.execute_fast(*args, **kwargs)

    async def execute_hgnn(self, *args, **kwargs) -> Dict[str, Any]:
        return await core_execute.execute_hgnn(*args, **kwargs)

    async def route_and_execute(self, *args, **kwargs) -> Dict[str, Any]:
        """Primary high-level entry point used by the service."""
        return await core_execute.route_and_execute(*args, **kwargs)

    async def dispatch_route_followup(self, *args, **kwargs) -> Optional[Dict[str, Any]]:
        return await core_execute.dispatch_route_followup(*args, **kwargs)

    async def dispatch_planner(self, *args, **kwargs) -> Dict[str, Any]:
        return await core_execute.dispatch_planner(*args, **kwargs)

    async def dispatch_hgnn(self, *args, **kwargs) -> Dict[str, Any]:
        return await core_execute.dispatch_hgnn(*args, **kwargs)

    # -------- Telemetry & embedding enqueue ----------------------------
    async def record_router_telemetry(self, telemetry_dao: Any, outbox_dao: Any, route_result: Dict[str, Any]) -> None:
        return await core_telemetry.record_router_telemetry(telemetry_dao, outbox_dao, route_result, "unknown", None, None)

    async def enqueue_embedding(
        self,
        task_id: str,
        reason: str,
        worker_func: Callable[[str, str], Awaitable[bool]],
        timeout_s: float = 5.0,
    ) -> bool:
        return await core_telemetry.enqueue_embedding(task_id, reason, worker_func, timeout_s=timeout_s)

    def create_metrics_tracker(self) -> Any:
        """Create a metrics tracker instance."""
        return core_telemetry.create_metrics_tracker()

    def track_routing_decision(self, metrics_tracker: Any, decision: str, has_plan: bool = False) -> None:
        """Track routing decision metrics."""
        core_telemetry.track_routing_decision(metrics_tracker, decision, has_plan)

    def track_execution_metrics(self, metrics_tracker: Any, path: str, success: bool, latency_ms: float) -> None:
        """Track execution path metrics."""
        core_telemetry.track_execution_metrics(metrics_tracker, path, success, latency_ms)

    def record_proto_plan_upsert(self, metrics_tracker: Any, status: str) -> None:
        """Record proto plan upsert metrics."""
        core_telemetry.record_proto_plan_upsert(metrics_tracker, status)

    def record_outbox_enqueue(self, metrics_tracker: Any, status: str) -> None:
        """Record outbox enqueue metrics."""
        core_telemetry.record_outbox_enqueue(metrics_tracker, status)

    def record_dispatch_metrics(self, metrics_tracker: Any, route: str, status: str) -> None:
        """Record dispatch metrics."""
        core_telemetry.record_dispatch_metrics(metrics_tracker, route, status)

    def record_route_latency(self, metrics_tracker: Any, latency_ms: float) -> None:
        """Record route and execute latency."""
        core_telemetry.record_route_latency(metrics_tracker, latency_ms)

    def get_metrics_summary(self, metrics_tracker: Any) -> Dict[str, Any]:
        """Get comprehensive metrics summary."""
        return core_telemetry.get_metrics_summary(metrics_tracker)

    # -------- Storage ---------------------------------------------------
    def persist_job_state(self, storage: Any, job_id: str, state: Dict[str, Any], ttl_s: int = 86400) -> bool:
        return core_storage.persist_job_state(storage, job_id, state, ttl_s)

    def get_job_state(self, storage: Any, job_id: str) -> Optional[Dict[str, Any]]:
        return core_storage.get_job_state(storage, job_id)


# Convenience factory -------------------------------------------------------

def build_default_core() -> CoordinatorCore:
    """Return a default façade instance.

    Submodules are function-based, so the façade has no state beyond the
    methods that delegate to them. This helper mirrors previous call sites
    that expected to construct a `CoordinatorCore()` object.
    """
    # Initialize PKG metadata at startup
    from . import policies as core_policies
    pkg_metadata = core_policies.initialize_pkg_metadata()
    if pkg_metadata.get("enabled") and pkg_metadata.get("loaded"):
        logger.info("PKG policy evaluation enabled: %s", pkg_metadata.get("version"))
    elif pkg_metadata.get("enabled"):
        logger.warning("PKG enabled but not loaded: %s", pkg_metadata.get("error"))
    
    return CoordinatorCore()