"""
Coordinator Service: Main entrypoint for routing, executing, and orchestrating
tasks across different execution paths (Fast, Planner, HGNN, and ERROR).
"""

# ---------------------------------------------------------------------------
# 1. Standard Library Imports
# ---------------------------------------------------------------------------
import asyncio
import inspect
import json
import logging
import os
import random
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence, Set
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

if TYPE_CHECKING:
    from collections.abc import Mapping as AbcMapping

# ---------------------------------------------------------------------------
# 2. Third-Party Imports
# ---------------------------------------------------------------------------
import httpx
import redis
from fastapi import FastAPI, HTTPException, Request
from ray import serve
from sqlalchemy import text

# ---------------------------------------------------------------------------
# 3. First-Party (Local) Imports
# ---------------------------------------------------------------------------

# Optional graph dependency
try:
    from ..graph.task_metadata_repository import TaskMetadataRepository  # type: ignore
except ImportError:  # pragma: no cover
    TaskMetadataRepository = None  # type: ignore

from ..coordinator.core.execute import (
    ExecutionConfig,
    HGNNConfig,
    RouteConfig,
    route_and_execute as execute_route_and_execute,
)
from ..coordinator.core.plan import persist_and_register_dependencies
from ..coordinator.core.policies import (
    OCPSValve,
    SurpriseComputer,
    compute_drift_score,
    create_ocps_valve,
    decide_route_with_hysteresis,
    generate_proto_subtasks,
    get_current_energy_state,
)
from ..coordinator.core.routing import (
    RouteCache,
    RouteEntry,
    bulk_resolve_routes_cached,
    resolve_route_cached_async,
    static_route_fallback,
)
from ..coordinator.dao import (
    MAX_PROTO_PLAN_BYTES,
    TaskOutboxDAO,
    TaskProtoPlanDAO,
    TaskRouterTelemetryDAO,
)
from ..coordinator.models import (
    AnomalyTriageRequest,
    AnomalyTriageResponse,
    TuneCallbackRequest,
)
from ..coordinator.utils import (
    # Task normalization
    convert_task_to_dict,
    normalize_task_dict,
    sync_task_identity,
    # Extraction
    extract_agent_id,
    extract_decision,
    extract_proto_plan,
    # Normalization
    normalize_domain,
    normalize_string,
    # Data processing
    redact_sensitive_data,
)
from ..predicates import PredicateRouter, load_predicates
from ..predicates.safe_metrics import create_safe_counter
from ..predicates.safe_storage import SafeStorage
from ..serve.cognitive_client import CognitiveServiceClient
from ..serve.ml_client import MLServiceClient
from ..serve.organism_client import OrganismServiceClient
from ..utils.ray_utils import COG, ML, ORG  # Used for constants
from ..database import get_async_pg_session_factory
from ..logging_setup import ensure_serve_logger
from ..models import Task, TaskPayload
from ..models.result_schema import ResultKind, create_error_result
from ..ops.eventizer.eventizer_features import (
    features_from_payload as default_features_from_payload,
)
from ..ops.eventizer.fact_dao import FactDAO
from ..ops.metrics import get_global_metrics_tracker
from ..ops.pkg.manager import get_global_pkg_manager


# ---------------------------------------------------------------------------
# 4. Constants
# ---------------------------------------------------------------------------
# NOTE: Default values here should match those defined in coordinator_entrypoint.py
# The entrypoint sets these environment variables before importing this module,
# but these defaults ensure consistent behavior if env vars are not set.

# --- Timeouts ---
ORCH_TIMEOUT = float(os.getenv("ORCH_HTTP_TIMEOUT", "10.0"))
ML_TIMEOUT = float(os.getenv("ML_SERVICE_TIMEOUT", "8.0"))
COG_TIMEOUT = float(os.getenv("COGNITIVE_SERVICE_TIMEOUT", "15.0"))
ORG_TIMEOUT = float(os.getenv("ORGANISM_SERVICE_TIMEOUT", "5.0"))
SEEDCORE_API_TIMEOUT = float(os.getenv("SEEDCORE_API_TIMEOUT", "5.0"))
CALL_TIMEOUT_S = int(os.getenv("SERVE_CALL_TIMEOUT_S", "120"))

# --- Service URLs ---
SEEDCORE_API_URL = os.getenv("SEEDCORE_API_URL", "http://seedcore-api:8002")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# --- Ray Gateway URLs (derived from imported constants) ---
ORG_URL = ORG    # Alias for clarity
ML_URL = ML  # Alias for clarity
COG_URL = COG  # Alias for clarity

# --- Feature & Tuning Configuration ---
# NOTE: Defaults should match coordinator_entrypoint.py env_vars dictionary
FAST_PATH_LATENCY_SLO_MS = float(os.getenv("FAST_PATH_LATENCY_SLO_MS", "1000"))
MAX_PLAN_STEPS = int(os.getenv("MAX_PLAN_STEPS", "16"))
COGNITIVE_MAX_INFLIGHT = int(os.getenv("COGNITIVE_MAX_INFLIGHT", "64"))
PREDICATES_CONFIG_PATH = os.getenv(
    "PREDICATES_CONFIG_PATH", "/app/config/predicates.yaml"
)
TUNE_SPACE_TYPE = os.getenv("TUNE_SPACE_TYPE", "basic")
TUNE_CONFIG_TYPE = os.getenv("TUNE_CONFIG_TYPE", "fast")
TUNE_EXPERIMENT_PREFIX = os.getenv("TUNE_EXPERIMENT_PREFIX", "coordinator-tune")

# ---------------------------------------------------------------------------
# 5. Service-Level Setup
# ---------------------------------------------------------------------------

logger = ensure_serve_logger("seedcore.coordinator", level="DEBUG")

# Log derived gateway URLs for debugging
logger.info("🔗 Coordinator using gateway URLs:")
logger.info(f"   ML_URL: {ML_URL}")
logger.info(f"   COG_URL: {COG_URL}")
logger.info(f"   ORG_URL: {ORG_URL}")

# ---------------------------------------------------------------------------
# 6. Helper Functions
# ---------------------------------------------------------------------------

def err(msg: str, error_type: str = "coordinator_error") -> dict:
    """Create a standardized error result."""
    return create_error_result(error=msg, error_type=error_type).model_dump()


async def _maybe_call(func: Callable[..., Any], *args, **kwargs):
    """Call sync/async functions, tolerating missing kwargs for legacy call sites."""
    def _is_kwarg_error(exc: TypeError) -> bool:
        msg = str(exc)
        return any(token in msg for token in ("unexpected", "positional", "keywords"))

    if kwargs:
        inspect_target = getattr(func, "side_effect", None) or getattr(func, "__wrapped__", func)
        try:
            inspect.signature(inspect_target).bind_partial(*args, **kwargs)
        except (TypeError, ValueError):
            kwargs = {}

    try:
        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
    except TypeError as exc:
        if not (kwargs and _is_kwarg_error(exc)):
            raise

    # Retry without kwargs
    result = func(*args)
    if inspect.isawaitable(result):
        return await result
    return result

def _corr_headers(target: str, cid: str) -> Dict[str, str]:
    """Create correlation headers for cross-service communication."""
    return {
        "Content-Type": "application/json",
        "X-Service": "coordinator",
        "X-Source-Service": "coordinator",
        "X-Target-Service": target,
        "X-Correlation-ID": cid,
    }

async def _apost(client: httpx.AsyncClient, url: str, payload: Dict[str, Any],
                 headers: Dict[str, str], timeout: float) -> Dict[str, Any]:
    r = await client.post(url, json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()

# Coordination primitives (OCPS, Surprise, drift, energy) are now imported from coordinator.core.policies
# Route cache structures are now imported from coordinator.core.routing


# ---------- Config Builders (for dependency injection) ----------
def build_route_config(
    router: "CoordinatorCore",
) -> RouteConfig:
    """Build RouteConfig from CoordinatorCore instance."""
    async def evaluate_pkg_func(
        tags: Sequence[str],
        signals: Mapping[str, Any],
        context: Mapping[str, Any] | None,
        timeout_s: int,
    ) -> dict[str, Any]:
        """PKG evaluation adapter."""
        pkg_mgr = get_global_pkg_manager()
        evaluator = pkg_mgr and pkg_mgr.get_active_evaluator()
        if not evaluator:
            raise RuntimeError("PKG evaluator not available")
        
        res = evaluator.evaluate({
            "tags": list(tags),
            "signals": signals,
            "context": context or {},
        })
        if not isinstance(res, dict):
            raise ValueError("Invalid PKG result type")
        
        return {
            "tasks": res.get("subtasks", []),
            "edges": res.get("dag", []),
            "version": res.get("snapshot") or evaluator.version,
        }
    
    return RouteConfig(
        surprise_computer=router.surprise,
        tau_fast_exit=router.tau_fast_exit,
        tau_plan_exit=router.tau_plan_exit,
        evaluate_pkg_func=evaluate_pkg_func,
        ood_to01=router.ood_to01,
        pkg_timeout_s=router.timeout_s,
    )


def build_execution_config(
    coordinator: "Coordinator",
    metrics: Any,
    cid: str,
) -> ExecutionConfig:
    """Build ExecutionConfig from Coordinator instance."""
    async def organism_execute(
        organ_id: str,
        task_dict: dict[str, Any],
        timeout: float,
        cid_local: str,
    ) -> dict[str, Any]:
        """Wrapper to call Coordinator's organism execution."""
        payload = {
            "organ_id": organ_id,
            "task": task_dict,
            "organ_timeout_s": timeout,
        }
        res = await _apost(
            coordinator.http,
            f"{ORG_URL}/execute-on-organ",
            payload,
            _corr_headers("organism", cid_local),
            timeout=ORG_TIMEOUT,
        )
        res["organ_id"] = organ_id
        return res
    
    return ExecutionConfig(
        normalize_task_dict=coordinator._normalize_task_dict,
        extract_agent_id=coordinator._extract_agent_id,
        compute_drift_score=coordinator._compute_drift_score,
        organism_execute=organism_execute,
        graph_task_repo=coordinator.graph_task_repo,
        ml_client=coordinator.ml_client,
        predicate_router=coordinator.predicate_router,
        metrics=metrics,
        cid=cid,
        resolve_route_cached=coordinator._resolve_route_cached,
        static_route_fallback=coordinator._static_route_fallback,
        normalize_type=coordinator._normalize,
        normalize_domain=coordinator._norm_domain,
    )


def build_hgnn_config(
    coordinator: "Coordinator",
) -> Optional[HGNNConfig]:
    """Build HGNNConfig from Coordinator instance if HGNN methods are available."""
    if not getattr(coordinator, "_hgnn_decompose", None):
        return None
    
    # Bind instance methods to create callables with correct signatures
    async def hgnn_decompose(task: Any) -> list[dict[str, Any]]:
        return await coordinator._hgnn_decompose(task)
    
    async def bulk_resolve_func(steps: list[dict[str, Any]], cid: str) -> dict[int, str]:
        return await coordinator._bulk_resolve_routes_cached(steps, cid)
    
    async def persist_plan_func(task: Any, plan: list[dict[str, Any]], root_db_id: Any | None) -> None:
        await coordinator._persist_plan_subtasks(task, plan, root_db_id=root_db_id)
    
    return HGNNConfig(
        hgnn_decompose=hgnn_decompose,
        bulk_resolve_func=bulk_resolve_func,
        persist_plan_func=persist_plan_func,
    )


# ---------- CoordinatorCore: unified route_and_execute ----------
class CoordinatorCore:
    """
    Hot-path router logic with Surprise Score S(T), PKG evaluation with timeouts,
    and unified result schema suitable for persistence into tasks.result.
    
    Routing Contract:
    - Computes 6-signal Surprise Score S(T) with OCPS-correct x₂ mapping
    - Evaluates PKG with strict timeout; falls back to deterministic rules
    - Returns unified result schema: {success, kind, payload}
    - Supports hysteresis to prevent decision flapping
    
    Environment Variables:
    - SURPRISE_WEIGHTS: Comma-separated weights for x1..x6 (default: 0.25,0.20,0.15,0.20,0.10,0.10)
    - SURPRISE_TAU_FAST: Fast path threshold (default: 0.35)
    - SURPRISE_TAU_PLAN: Planner threshold (default: 0.60)
    - SURPRISE_TAU_FAST_EXIT: Fast path exit threshold for hysteresis (default: 0.38)
    - SURPRISE_TAU_PLAN_EXIT: Planner exit threshold for hysteresis (default: 0.57)
    - SURPRISE_NORMALIZE_MODE: Feature normalization mode - "simple" (clamp) or "softmax" (probabilistic) (default: "simple")
    - SERVE_CALL_TIMEOUT_S: PKG evaluation timeout (default: 2)
    """
    def __init__(
        self,
        ood_to01: Optional[Callable[[float], float]] = None,
        surprise_weights: Optional[Sequence[float]] = None,
        tau_fast: Optional[float] = None,
        tau_plan: Optional[float] = None,
        call_timeout_s: int = 2,
        metrics_tracker: Optional["MetricsTracker"] = None,
    ):
        self.ood_to01 = ood_to01
        self.timeout_s = int(os.getenv("SERVE_CALL_TIMEOUT_S", str(call_timeout_s)))
        self.metrics = metrics_tracker
        
        # SurpriseComputer handles weight parsing internally from environment
        # Parse thresholds with safe defaults
        tau_fast_val = tau_fast or float(os.getenv("SURPRISE_TAU_FAST", "0.35"))
        tau_plan_val = tau_plan or float(os.getenv("SURPRISE_TAU_PLAN", "0.60"))
        
        # Parse hysteresis thresholds
        self.tau_fast_exit = float(os.getenv("SURPRISE_TAU_FAST_EXIT", str(tau_fast_val + 0.03)))
        self.tau_plan_exit = float(os.getenv("SURPRISE_TAU_PLAN_EXIT", str(tau_plan_val - 0.03)))
        
        self.surprise = SurpriseComputer(weights=surprise_weights, tau_fast=tau_fast_val, tau_plan=tau_plan_val)
        
        # PKG is now managed by the global PKGManager
        # No need for local initialization here

    async def route_and_execute(
        self,
        task: "TaskPayload",
        *,
        fact_dao: Optional[FactDAO] = None,
        eventizer_helper: Optional[Callable[[Any], Any]] = None,
        coordinator_instance: Any,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Adapter wrapper that wires coordinator dependencies into execute.py's
        unified route_and_execute() function.
        
        This method only handles dependency binding - all orchestration logic
        (routing decisions, PKG evaluation, execution flow) is handled by execute.py.
        """
        if not coordinator_instance:
            raise ValueError("coordinator_instance is required")
        
        # Generate correlation ID
        cid = correlation_id or str(uuid.uuid4())
        
        # Build configs using helper functions
        routing_config = build_route_config(self)
        execution_config = build_execution_config(coordinator_instance, self.metrics, cid)
        hgnn_config = build_hgnn_config(coordinator_instance)
        
        # Delegate everything to core execute.py
        return await execute_route_and_execute(
            task=task,
            fact_dao=fact_dao,
            eventizer_helper=eventizer_helper or default_features_from_payload,
            routing_config=routing_config,
            execution_config=execution_config,
            hgnn_config=hgnn_config,
        )

# ---------- FastAPI/Serve ----------
# Note: route_prefix is already set in rayservice.yaml as /pipeline
# So we use empty string here to avoid double prefixing
router_prefix = ""

class ASGIWrapper:
    """Minimal ASGI adapter compatible with older Ray Serve versions."""

    def __init__(self, app: FastAPI):
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Callable[[], Awaitable[Any]], send: Callable[[dict[str, Any]], Awaitable[None]]):
        if scope.get("type") != "http":
            raise RuntimeError(f"Unsupported scope type: {scope.get('type')}")
        await self.app(scope, receive, send)


@serve.deployment(
    name="Coordinator",
    num_replicas=int(os.getenv("COORDINATOR_REPLICAS", "1")),
    max_ongoing_requests=16,
    ray_actor_options={"num_cpus": float(os.getenv("COORDINATOR_NUM_CPUS", "0.2"))},
)
class Coordinator:
    def __init__(self):
        self.app = FastAPI(
            title="SeedCore Coordinator",
            version="1.0.0",
            docs_url="/docs",
            redoc_url="/redoc",
            openapi_url="/openapi.json",
        )

        # Initialize service clients with conservative circuit breakers
        self.ml_client = MLServiceClient(
            base_url=ML, 
            timeout=float(os.getenv("CB_ML_TIMEOUT_S", "5.0")),
            warmup_timeout=float(os.getenv("CB_ML_WARMUP_TIMEOUT_S", "30.0"))
        )
        
        self.cognitive_client = CognitiveServiceClient(
            base_url=COG, 
            timeout=float(os.getenv("CB_COG_TIMEOUT_S", "8.0"))
        )
        
        self.organism_client = OrganismServiceClient(
            base_url=ORG, 
            timeout=float(os.getenv("CB_ORG_TIMEOUT_S", "5.0"))
        )
        
        # Legacy HTTP client for backward compatibility
        self.http = httpx.AsyncClient(
            timeout=ORCH_TIMEOUT,
            limits=httpx.Limits(max_keepalive_connections=100, max_connections=200),
        )
        self.ocps = create_ocps_valve()
        self.metrics = get_global_metrics_tracker()

        try:
            self._session_factory = get_async_pg_session_factory()
        except Exception as exc:  # pragma: no cover - defensive log for misconfigured env
            logger.warning(f"Failed to initialize async session factory: {exc}")
            self._session_factory = None
        self.telemetry_dao = TaskRouterTelemetryDAO()
        self.outbox_dao = TaskOutboxDAO()
        self.proto_plan_dao = TaskProtoPlanDAO()

        # Tiny TTL route cache with single-flight
        self.route_cache = RouteCache(
            ttl_s=float(os.getenv("ROUTE_CACHE_TTL_S", "3.0")),
            jitter_s=float(os.getenv("ROUTE_CACHE_JITTER_S", "0.5"))
        )
        self._last_seen_epoch = None  # Track organism epoch for cache invalidation
        
        # Feature flag for safe rollout
        def _env_bool(name: str, default: bool = False) -> bool:
            """Robust environment variable parsing for boolean values."""
            val = os.getenv(name)
            if val is None:
                return default
            return val.lower() in ("1", "true", "yes", "y", "on")
        
        self.routing_remote_enabled = _env_bool("ROUTING_REMOTE", False)
        self.routing_remote_types = set(os.getenv("ROUTING_REMOTE_TYPES", "graph_embed,graph_rag_query,graph_fact_embed,graph_fact_query,nim_task_embed,graph_sync_nodes").split(","))

        self.graph_repository = None  # Lazily instantiated GraphTaskRepository
        self._graph_repo_checked = False
        self.graph_task_repo = self._get_graph_repository()  # Consistent attribute name

        
        # Initialize safe storage (Redis with in-memory fallback)
        try:
            redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            self.storage = SafeStorage(redis_client)
            logger.info(f"✅ Storage initialized: {self.storage.get_backend_type()}")
        except Exception as e:
            logger.warning(f"⚠️ Redis connection failed, using in-memory storage: {e}")
            self.storage = SafeStorage(None)

        # Maintain runtime context on the actor instance (not the FastAPI app)
        self.runtime_ctx = {
            "storage": self.storage,
            "metrics": self.metrics,
        }

        # Per-replica Prometheus counters (avoid module-level globals for Ray serialization)
        try:
            self.prom_outbox_flush_ok = create_safe_counter(
                "coord_outbox_flush_ok_total",
                "Number of successful outbox flush operations",
                labelnames=["event_type"],
            )
            self.prom_outbox_flush_retry = create_safe_counter(
                "coord_outbox_flush_retry_total",
                "Number of outbox flush retry operations",
                labelnames=["event_type"],
            )
            self.prom_outbox_insert_ok = create_safe_counter(
                "coord_outbox_insert_ok_total",
                "Number of successful outbox insert operations",
                labelnames=["event_type"],
            )
            self.prom_outbox_insert_dup = create_safe_counter(
                "coord_outbox_insert_dup_total",
                "Number of duplicate outbox insert operations",
                labelnames=["event_type"],
            )
            self.prom_outbox_insert_err = create_safe_counter(
                "coord_outbox_insert_err_total",
                "Number of failed outbox insert operations",
                labelnames=["event_type"],
            )
        except Exception:
            self.prom_outbox_flush_ok = None
            self.prom_outbox_flush_retry = None
            self.prom_outbox_insert_ok = None
            self.prom_outbox_insert_dup = None
            self.prom_outbox_insert_err = None
        
        # Initialize predicate system (will be loaded async in __post_init__)
        self.predicate_config = None
        self.predicate_router = None
        
        # Routing is now handled by OrganismManager via resolve-route endpoints
        # Old static routing rules are preserved in _static_route_fallback method
        
        # Escalation concurrency control
        self.escalation_max_inflight = COGNITIVE_MAX_INFLIGHT
        self.escalation_semaphore = asyncio.Semaphore(5)
        self._inflight_escalations = 0
        
        # Configuration
        self.fast_path_latency_slo_ms = FAST_PATH_LATENCY_SLO_MS
        self.max_plan_steps = MAX_PLAN_STEPS
        
        # Initialize predicate system synchronously first
        try:
            self.predicate_config = load_predicates(PREDICATES_CONFIG_PATH)
            self.predicate_router = PredicateRouter(self.predicate_config)
            logger.info("✅ Predicate system initialized")
        except Exception as e:
            logger.warning(f"⚠️ Failed to load predicate config, using fallback: {e}")
            # Create a minimal fallback configuration
            from ..predicates.loader import create_default_config
            self.predicate_config = create_default_config()
            self.predicate_router = PredicateRouter(self.predicate_config)
        
        # Background task state
        self._bg_started = False
        self._background_tasks_started = False
        self._warmup_started = False
        
        # Wire core router with configurable thresholds
        try:
            self.core = CoordinatorCore(metrics_tracker=self.metrics)
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize CoordinatorCore, using defaults: {e}")
            self.core = CoordinatorCore(metrics_tracker=self.metrics)

        self._register_routes()
        self.asgi_app = ASGIWrapper(self.app)
        logger.info("✅ Coordinator initialized")

    def _register_routes(self) -> None:
        self.app.add_api_route(
            f"{router_prefix}/route-and-execute",
            self.route_and_execute,
            methods=["POST"],
        )
        self.app.add_api_route(
            "/health",
            self.health,
            methods=["GET"],
        )
        self.app.add_api_route(
            f"{router_prefix}/metrics",
            self.get_metrics,
            methods=["GET"],
        )
        self.app.add_api_route(
            "/readyz",
            self.ready,
            methods=["GET"],
        )
        self.app.add_api_route(
            f"{router_prefix}/predicates/status",
            self.get_predicate_status,
            methods=["GET"],
        )
        self.app.add_api_route(
            f"{router_prefix}/predicates/config",
            self.get_predicate_config,
            methods=["GET"],
        )
        self.app.add_api_route(
            f"{router_prefix}/predicates/reload",
            self.reload_predicates,
            methods=["POST"],
        )
        self.app.add_api_route(
            f"{router_prefix}/ml/tune/callback",
            self.tune_callback,
            methods=["POST"],
        )
        self.app.add_api_route(
            f"{router_prefix}/anomaly-triage",
            self.anomaly_triage,
            methods=["POST"],
            response_model=AnomalyTriageResponse,
        )

    async def __call__(self, request: Request):
        send = getattr(request, "send", None) or getattr(request, "_send", None)
        if send is None:
            raise RuntimeError("Request object does not provide an ASGI send callable")
        return await self.asgi_app(request.scope, request.receive, send)

    async def _ensure_background_tasks_started(self):
        """Ensure background tasks are started (called on first request)."""
        if self._bg_started:
            return
            
        # Resolve Serve handles once and keep them
        try:
            self.ops = serve.get_deployment_handle("OpsGateway", app_name="ops")
            self.ml = serve.get_deployment_handle("MLService", app_name="ml_service")
            self.cog = serve.get_deployment_handle("CognitiveService", app_name="cognitive")
            self._bg_started = True
            logger.info("Coordinator wired → ops/ml/cognitive handles ready")
        except Exception as e:
            logger.warning(f"Failed to get some Serve handles: {e}")
            # Continue with partial handles - some services might not be available
            
        if not self._background_tasks_started:
            asyncio.create_task(self._start_background_tasks())
            self._background_tasks_started = True
            
        if not self._warmup_started:
            asyncio.create_task(self._warmup_drift_detector())
            self._warmup_started = True

    

    async def _start_background_tasks(self):
        """Start background maintenance tasks."""
        try:
            # Predicate router should already be initialized synchronously
            if self.predicate_router is not None:
                await self.predicate_router.start_background_tasks()
                logger.info("🚀 Started Coordinator background tasks")
            else:
                logger.warning("⚠️ Predicate router not initialized, skipping background tasks")
            # Start task outbox flusher loop
            asyncio.create_task(self._task_outbox_flusher_loop())
        except Exception as e:
            logger.error(f"❌ Failed to start background tasks: {e}")
    
    async def _warmup_drift_detector(self):
        """
        Warm up the drift detector to avoid cold start latency.
        
        Uses staggered warmup with jitter to prevent thundering herd when
        multiple replicas start simultaneously in a cluster.
        """
        try:
            # Staggered warmup with jitter to prevent thundering herd
            # Each replica waits a random amount of time before warming up
            import random
            base_delay = 2.0  # Base delay in seconds
            jitter = random.uniform(0, 3.0)  # Random jitter 0-3 seconds
            total_delay = base_delay + jitter
            
            logger.info(f"⏳ Staggered warmup: waiting {total_delay:.2f}s (base={base_delay}s, jitter={jitter:.2f}s)")
            await asyncio.sleep(total_delay)
            
            # Call ML service warmup endpoint
            warmup_request = {
                "sample_texts": [
                    "Test task for warmup",
                    "General query about system status", 
                    "Anomaly detection task with high priority",
                    "Execute complex workflow with multiple steps"
                ]
            }
            
            # First, check if ML service is healthy
            try:
                if not await self.ml_client.is_healthy():
                    logger.warning("⚠️ ML service health check failed, skipping warmup")
                    return
                logger.info("✅ ML service health check passed")
            except Exception as e:
                logger.warning(f"⚠️ ML service health check failed: {e}, skipping warmup")
                return
            
            logger.info(f"🔄 Calling ML service warmup at {self.ml_client.base_url}/drift/warmup")
            
            # Try warmup with retries
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = await self.ml_client.warmup_drift_detector(
                        sample_texts=warmup_request.get("sample_texts")
                    )
                    break  # Success, exit retry loop
                except Exception as e:
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt  # Exponential backoff
                        logger.warning(f"⚠️ ML service warmup attempt {attempt + 1} failed: {e}, retrying in {wait_time}s", exc_info=True)
                        await asyncio.sleep(wait_time)
                    else:
                        raise  # Re-raise on final attempt
            
            if response.get("status") == "success":
                warmup_time = response.get("warmup_time_ms", 0.0)
                logger.info(f"✅ Drift detector warmup completed in {warmup_time:.2f}ms (after {total_delay:.2f}s delay)")
                # Record circuit-breaker metrics for successful warmup
                self.predicate_router.metrics.record_circuit_breaker_event("ml_service", "warmup_success")
            else:
                logger.warning(f"⚠️ Drift detector warmup failed: {response.get('error', 'Unknown error')}")
                # Record circuit-breaker metrics for failed warmup
                self.predicate_router.metrics.record_circuit_breaker_event("ml_service", "warmup_failed")
                
        except Exception as e:
            logger.warning(f"⚠️ Drift detector warmup failed: {e}", exc_info=True)
            # Record circuit-breaker metrics for warmup exception
            self.predicate_router.metrics.record_circuit_breaker_event("ml_service", "warmup_exception")
            # Don't fail startup if warmup fails - drift detection will use fallback
            logger.info("ℹ️ Drift detection will use fallback mode until ML service is available")

    def _get_current_energy_state(self, agent_id: str) -> Optional[float]:
        """Get current energy state for an agent."""
        # Use the centralized energy state function from policies
        return get_current_energy_state(agent_id)

    async def _task_outbox_flusher_loop(self) -> None:
        """Periodically flush task_outbox nim_task_embed events to the LTM worker with backoff.
        
        Uses TaskOutboxDAO for all database operations to maintain separation of concerns.
        """
        try:
            session_factory = getattr(self, "_session_factory", None) or get_async_pg_session_factory()
            self._session_factory = session_factory
        except Exception as exc:
            logger.warning(f"[Coordinator] No session factory for outbox flusher: {exc}")
            return

        interval_s = float(os.getenv("TASK_OUTBOX_FLUSH_INTERVAL_S", "5"))
        batch_size = int(os.getenv("TASK_OUTBOX_FLUSH_BATCH", "100"))

        while True:
            try:
                async with session_factory() as s:
                    async with s.begin():
                        # Use DAO method for concurrent-safe event claiming
                        rows = await self.outbox_dao.claim_pending_nim_task_embeds(s, limit=batch_size)

                        if not rows:
                            await s.rollback()
                        for row in rows:
                            try:
                                data = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
                                task_id = data.get("task_id")
                                ok = await self._enqueue_task_embedding_now(task_id, reason="outbox")
                                if ok:
                                    await self.outbox_dao.delete(s, row["id"])
                                    if self.prom_outbox_flush_ok:
                                        try:
                                            self.prom_outbox_flush_ok.labels("nim_task_embed").inc()
                                        except Exception:
                                            pass
                                else:
                                    # Use DAO backoff method for retry logic
                                    await self.outbox_dao.backoff(s, row["id"])
                                    if self.prom_outbox_flush_retry:
                                        try:
                                            self.prom_outbox_flush_retry.labels("nim_task_embed").inc()
                                        except Exception:
                                            pass
                            except Exception as exc:
                                logger.warning(f"[Coordinator] Outbox item {row.get('id')} failed: {exc}")
                                # Use DAO backoff method for error handling
                                await self.outbox_dao.backoff(s, row["id"])
                                if self.prom_outbox_flush_retry:
                                    try:
                                        self.prom_outbox_flush_retry.labels("nim_task_embed").inc()
                                    except Exception:
                                        pass
            except Exception as exc:
                logger.debug(f"[Coordinator] Outbox flusher tick failed: {exc}")
            await asyncio.sleep(max(1.0, interval_s))
    
    async def _compute_drift_score(self, task: Dict[str, Any]) -> float:
        """
        Compute drift score using the ML service drift detector.
        
        Delegates to the centralized compute_drift_score function from policies module.
        
        Returns:
            Drift score suitable for OCPSValve integration
        """
        metrics = getattr(self, 'predicate_router', None)
        if metrics:
            metrics = metrics.metrics
        return await compute_drift_score(
            task=task,
            ml_client=self.ml_client,
            metrics=metrics,
        )
    
    # Helper methods now use utils functions
    def _normalize(self, x: Optional[str]) -> Optional[str]:
        """Normalize string for consistent matching."""
        return normalize_string(x)
    
    def _norm_domain(self, domain: Optional[str]) -> Optional[str]:
        """Normalize domain to standard taxonomy."""
        return normalize_domain(domain)

    def _static_route_fallback(self, task_type: str, domain: Optional[str]) -> str:
        """Fallback routing using static rules when organism is unavailable."""
        return static_route_fallback(task_type, domain)

    async def _resolve_route_cached(self, task_type: str, domain: Optional[str], *,
                                   preferred_logical_id: Optional[str] = None,
                                   cid: Optional[str] = None) -> str:
        """Resolve route with caching and single-flight."""
        logical_id = await resolve_route_cached_async(
            task_type=task_type,
            domain=domain,
            route_cache=self.route_cache,
            normalize_func=self._normalize,
            static_route_fallback_func=self._static_route_fallback,
            organism_client=self.organism_client,
            routing_remote_enabled=self.routing_remote_enabled,
            routing_remote_types=self.routing_remote_types,
            preferred_logical_id=preferred_logical_id,
            cid=cid,
            metrics=self.metrics,
            last_seen_epoch=self._last_seen_epoch,
        )
        # Update epoch if we got one from the response (handled internally in routing.py)
        # For now, we track it via the cache entry, but we could enhance resolve_route_cached_async
        # to return the epoch if needed
        return logical_id

    async def _bulk_resolve_routes_cached(self, steps: List[Dict[str, Any]], cid: str) -> Dict[int, str]:
        """
        Given HGNN steps (each has step['task'] with type/domain),
        return a mapping: { step_index -> logical_id }.
        De-duplicates (type, domain) pairs to minimize network calls.
        """
        mapping, new_epoch = await bulk_resolve_routes_cached(
            steps=steps,
            cid=cid,
            route_cache=self.route_cache,
            normalize_func=self._normalize,
            normalize_domain_func=self._norm_domain,
            static_route_fallback_func=self._static_route_fallback,
            organism_client=self.organism_client,
            metrics=self.metrics,
            last_seen_epoch=self._last_seen_epoch,
        )
        # Update epoch if we got a new one
        if new_epoch:
            self._last_seen_epoch = new_epoch
        return mapping

    def _persist_job_state(self, job_id: str, state: Dict[str, Any]):
        """Persist job state using safe storage."""
        success = self.storage.set(f"job:{job_id}", state, ttl=86400)  # 24h TTL
        if not success:
            logger.warning(f"Failed to persist job state for {job_id}")
    
    def _get_job_state(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve job state using safe storage."""
        return self.storage.get(f"job:{job_id}")

    async def _fire_and_forget_memory_synthesis(self, agent_id: str, anomalies: dict, 
                                               reason: dict, decision: dict, cid: str):
        """Fire-and-forget memory synthesis with proper error handling and metrics."""
        start_time = time.time()
        
        try:
            # Redact sensitive data
            redacted_anomalies = self._redact_sensitive_data(anomalies.get("anomalies", []))
            redacted_reason = self._redact_sensitive_data(reason.get("result") or reason)
            redacted_decision = self._redact_sensitive_data(decision.get("result") or decision)
            
            payload = {
                "agent_id": agent_id,
                "memory_fragments": [
                    {"anomalies": redacted_anomalies},
                    {"reason": redacted_reason},
                    {"decision": redacted_decision}
                ],
                "synthesis_goal": "incident_triage_summary"
            }
            
            await self.cognitive_client.post("/synthesize-memory",
                                           json=payload,
                                           headers=_corr_headers("cognitive", cid))
            
            duration = time.time() - start_time
            self.predicate_router.metrics.record_memory_synthesis("success", duration)
            logger.debug(f"[Coordinator] Memory synthesis completed for agent {agent_id} in {duration:.2f}s")
            
        except Exception as e:
            duration = time.time() - start_time
            self.predicate_router.metrics.record_memory_synthesis("failure", duration)
            logger.debug(f"[Coordinator] Memory synthesis failed (best-effort): {e}")
    
    # Helper methods now use utils functions
    def _redact_sensitive_data(self, data: Any) -> Any:
        """Redact sensitive data from memory synthesis payload."""
        return redact_sensitive_data(data)

    def _normalize_task_dict(self, task_like: Any) -> Tuple[Union[uuid.UUID, str], Dict[str, Any]]:
        return normalize_task_dict(task_like)

    def _sync_task_identity(self, task_like: Any, task_id: str) -> None:
        sync_task_identity(task_like, task_id)

    def _extract_agent_id(self, task_dict: Dict[str, Any]) -> Optional[str]:
        return extract_agent_id(task_dict)

    async def _hgnn_decompose(self, task: Task) -> List[Dict[str, Any]]:
        """
        HGNN-based task decomposition using CognitiveCore Serve deployment.
        
        Steps:
          1. Verifies cognitive client health
          2. Calls CognitiveCore (/solve-problem)
          3. Handles immediate minimal vs deep HGNN results
          4. Validates plan or falls back to simple routing
        """
        try:
            # --- Step 1: Cognitive service health check ---
            try:
                if not await self.cognitive_client.is_healthy():
                    logger.warning("[HGNN] Cognitive service unavailable, using fallback")
                    return self._fallback_plan(self._convert_task_to_dict(task))
            except Exception as e:
                logger.warning(f"[HGNN] Health check failed: {e}")
                return self._fallback_plan(self._convert_task_to_dict(task))

            # --- Step 2: Prepare Cognitive request ---
            req = {
                "agent_id": f"hgnn_planner_{task.id}",
                "problem_statement": task.description or str(task.model_dump()),
                "task_id": task.id,
                "constraints": {
                    "latency_ms": self.fast_path_latency_slo_ms,
                    "max_depth": getattr(task, "max_depth", 3),
                },
                "available_tools": getattr(task, "available_tools", {}),
                "meta": {
                    "origin": "coordinator_hgnn",
                    "has_context": bool(task.features),
                    "history_ids": task.history_ids,
                    "start_nodes": {
                        "facts": getattr(task, "start_fact_ids", []),
                        "artifacts": getattr(task, "start_artifact_ids", []),
                        "models": getattr(task, "start_model_ids", []),
                        "capabilities": getattr(task, "start_capability_ids", []),
                        "policies": getattr(task, "start_policy_ids", []),
                        "services": getattr(task, "start_service_ids", []),
                        "skills": getattr(task, "start_skill_ids", []),
                    },
                },
            }

            # --- Step 3: Call CognitiveCore ---
            plan = await _apost(
                self.http,
                f"{COG}/solve-problem",
                req,
                _corr_headers("cognitive", task.id),
                timeout=COG_TIMEOUT,
            )

            # --- Step 4: Handle Cognitive response ---
            result = plan.get("result", {}) if isinstance(plan, dict) else {}
            steps = result.get("solution_steps") or result.get("plan") or result.get("steps") or []
            meta = result.get("meta", {})

            # Distinguish immediate vs deep result
            immediate = meta.get("immediate", False)
            if immediate:
                logger.info(f"[HGNN] CognitiveCore returned immediate minimal plan for {task.id}")
            else:
                logger.info(f"[HGNN] Received deep HGNN decomposition: {len(steps)} steps")

            # --- Step 5: Handle Cognitive metadata ---
            if meta:
                escalate_hint = meta.get("escalate_hint")
                if escalate_hint and hasattr(self, "predicate_router") and self.predicate_router:
                    self.predicate_router.update_signals(escalate_hint=escalate_hint)
                
                confidence = meta.get("confidence")
                if confidence is not None:
                    logger.info(f"[HGNN] Cognitive plan confidence: {confidence:.2f}")

            # --- Step 6: Validate or fallback ---
            validated_plan = self._validate_or_fallback(steps, self._convert_task_to_dict(task))
            if validated_plan:
                return validated_plan

            logger.warning(f"[HGNN] Validation failed or empty plan; using fallback")
            return self._fallback_plan(self._convert_task_to_dict(task))

        except Exception as e:
            logger.warning(f"[HGNN] Decomposition failed: {e}", exc_info=True)
            return self._fallback_plan(self._convert_task_to_dict(task))

    def _convert_task_to_dict(self, task) -> Dict[str, Any]:
        """Convert task object to dictionary, handling TaskPayload and other types."""
        return convert_task_to_dict(task)

    def _fallback_plan(self, task: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create a minimal safe fallback plan when cognitive reasoning is unavailable."""
        ttype = (task.get("type") or task.get("task_type") or "").strip().lower()
        
        # Use static fallback routing (new routing is async)
        organ_id = self._static_route_fallback(ttype, task.get("domain"))
        
        return [{"organ_id": organ_id, "task": task}]

    def _validate_or_fallback(self, plan: List[Dict[str, Any]], task: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """Validate the plan from CognitiveCore and return fallback if invalid."""
        if not isinstance(plan, list) or len(plan) > self.max_plan_steps:
            logger.warning(f"Plan validation failed: invalid format or too many steps ({len(plan) if isinstance(plan, list) else 'not a list'})")
            return None

        for idx, step in enumerate(plan):
            if not isinstance(step, dict):
                logger.warning(f"Plan validation failed: step is not a dict: {step}")
                return None

            if "task" not in step or not isinstance(step["task"], dict):
                logger.warning(f"Plan validation failed: step missing 'task' dict: {step}")
                return None
            
            # Ensure stable IDs exist in plan for reliable edge creation
            if "id" not in step and "step_id" not in step:
                step["id"] = f"step_{idx}_{uuid.uuid4().hex[:8]}"
                step["step_id"] = step["id"]
            
            # Ensure task has stable ID
            if isinstance(step.get("task"), dict):
                task_data = step["task"]
                if "id" not in task_data and "task_id" not in task_data:
                    task_data["id"] = f"subtask_{idx}_{uuid.uuid4().hex[:8]}"
                    task_data["task_id"] = task_data["id"]

        return plan

    def _get_graph_repository(self):
        """Return a lazily-instantiated GraphTaskRepository if available."""
        if self.graph_repository is not None or self._graph_repo_checked:
            return self.graph_repository

        self._graph_repo_checked = True

        if TaskMetadataRepository is None:
            return None

        try:
            self.graph_repository = TaskMetadataRepository()
        except TypeError as exc:
            logger.debug(f"TaskMetadataRepository instantiation failed (signature mismatch): {exc}")
            self.graph_repository = None
        except Exception as exc:  # pragma: no cover - defensive logging for unexpected errors
            logger.warning(f"TaskMetadataRepository initialization failed: {exc}")
            self.graph_repository = None

        return self.graph_repository

    def _get_graph_sql_repository(self):
        """Legacy alias retained for compatibility with older coordinator tests."""
        return self._get_graph_repository()

    async def _dispatch_hgnn(self, payload: TaskPayload, proto_plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatch HGNN steps to the graph repository, recording partial failures.

        Returns metadata of successfully dispatched tasks. Unsupported steps are skipped.
        """
        repo = self._get_graph_sql_repository()
        dispatched: list[dict[str, Any]] = []
        status = "ok"

        if repo is None:
            if getattr(self.metrics, "record_dispatch", None):
                self.metrics.record_dispatch("hgnn", "err")
            return {"graph_dispatch": {"graph_tasks": dispatched}}

        steps = proto_plan.get("tasks", []) if isinstance(proto_plan, dict) else []
        supported_types = {
            "graph_embed",
            "graph_rag_query",
            "graph_fact_embed",
            "graph_fact_query",
            "graph_sync_nodes",
        }

        for step in steps:
            if not isinstance(step, dict):
                continue
            step_type = (step.get("type") or "").strip().lower()
            if step_type not in supported_types:
                continue

            params = step.get("params", {}) if isinstance(step.get("params"), dict) else {}
            try:
                task_id = await repo.create_task_async(payload, step_type, params)
                dispatched.append({
                    "type": step_type,
                    "task_id": str(task_id),
                })
            except Exception:
                status = "err"

        if getattr(self.metrics, "record_dispatch", None):
            self.metrics.record_dispatch("hgnn", status if dispatched else "err")

        return {"graph_dispatch": {"graph_tasks": dispatched}}

    async def _persist_plan_subtasks(
        self,
        task: Task,
        plan: List[Dict[str, Any]],
        *,
        root_db_id: Optional[uuid.UUID] = None,
    ):
        """Insert subtasks for the HGNN plan and register dependency edges.
        
        Delegates to persist_and_register_dependencies from coordinator.core.plan.
        """
        repo = self._get_graph_repository()
        if repo is None:
            return []
        
        return await persist_and_register_dependencies(
            plan=plan,
            repo=repo,
            task=task,
            root_db_id=root_db_id,
        )

    # Removed _execute_fast and _execute_hgnn - these are now handled by execute.py's route_and_execute
    # Removed _make_escalation_result - this is now in execute.py

    def _extract_proto_plan(self, route_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return extract_proto_plan(route_result)

    def _extract_decision(self, route_result: Dict[str, Any]) -> Optional[str]:
        return extract_decision(route_result)

    async def _persist_proto_plan(
        self,
        repo: Optional[Any],
        task_id: str,
        decision: Optional[str],
        proto_plan: Optional[Dict[str, Any]],
    ) -> None:
        if proto_plan is None:
            return
        dao = getattr(self, "proto_plan_dao", None)
        if dao is None:
            return
        session_factory = self._resolve_session_factory(repo)
        if session_factory is None:
            return
        metrics = getattr(self, "metrics", None)
        try:
            async with session_factory() as session:
                async with session.begin():
                    result = await dao.upsert(
                        session,
                        task_id=str(task_id),
                        route=decision or "unknown",
                        proto_plan=proto_plan,
                    )
            if metrics is not None:
                status = "truncated" if result.get("truncated") else "ok"
                metrics.record_proto_plan_upsert(status)
        except Exception as exc:
            logger.debug(
                "[Coordinator] Skipping proto-plan persistence for %s: %s",
                task_id,
                exc,
            )
            if metrics is not None:
                metrics.record_proto_plan_upsert("err")

    # Removed _dispatch_route_followup, _dispatch_planner, _dispatch_hgnn, and _get_graph_sql_repository
    # These are no longer needed - follow-up dispatch is handled by execute.py via HGNNConfig

    def _resolve_session_factory(self, repo: Optional[Any] = None):
        session_factory = getattr(self, "_session_factory", None)
        if session_factory is not None:
            return session_factory

        if repo is not None:
            session_factory = getattr(repo, "_session_factory", None)
            if session_factory is not None:
                self._session_factory = session_factory
                return session_factory

        try:
            session_factory = get_async_pg_session_factory()
            self._session_factory = session_factory
            return session_factory
        except Exception as exc:  # pragma: no cover - log and continue without telemetry persistence
            logger.warning(f"[Coordinator] Failed to obtain session factory for telemetry persistence: {exc}")
            return None

    async def _record_router_telemetry(
        self,
        repo: Optional[Any],
        task_id: str,
        route_result: Dict[str, Any],
    ) -> None:
        telemetry_dao = getattr(self, "telemetry_dao", None)
        outbox_dao = getattr(self, "outbox_dao", None)
        if telemetry_dao is None or outbox_dao is None:
            return

        if not isinstance(route_result, dict):
            return

        payload = route_result.get("payload") if isinstance(route_result.get("payload"), dict) else None
        if not payload:
            return

        surprise = payload.get("surprise") if isinstance(payload.get("surprise"), dict) else None
        decision = payload.get("decision")
        if surprise is None or decision is None:
            return

        try:
            surprise_score = float(surprise.get("S"))
        except (TypeError, ValueError):
            logger.debug("[Coordinator] Surprise score missing or invalid; skipping telemetry persistence")
            return

        x_vector = surprise.get("x")
        weights = surprise.get("weights")
        if x_vector is None or weights is None:
            logger.debug("[Coordinator] Surprise components missing; skipping telemetry persistence")
            return

        try:
            x_list = list(x_vector)
            weights_list = list(weights)
        except TypeError:
            logger.debug("[Coordinator] Surprise vectors not iterable; skipping telemetry persistence")
            return

        ocps_metadata = surprise.get("ocps") if isinstance(surprise.get("ocps"), dict) else {}

        session_factory = self._resolve_session_factory(repo)
        if session_factory is None:
            return

        dedupe_key = f"{task_id}:task.primary"
        metrics = getattr(self, "metrics", None)
        prom_insert_ok = getattr(self, "prom_outbox_insert_ok", None)
        prom_insert_dup = getattr(self, "prom_outbox_insert_dup", None)
        prom_insert_err = getattr(self, "prom_outbox_insert_err", None)

        enqueue_fn = getattr(outbox_dao, "enqueue_embed_task", None) or getattr(
            outbox_dao, "enqueue_nim_task_embed", None
        )
        if enqueue_fn is None:
            logger.debug("[Coordinator] Outbox DAO has no enqueue method; skipping telemetry")
            return

        try:
            async with session_factory() as session:
                use_tx = callable(getattr(session, "begin", None)) and not hasattr(session, "begin_calls")

                async def _run_ops() -> bool:
                    await session.execute(
                        text("SELECT ensure_task_node(CAST(:tid AS uuid))"),
                        {"tid": str(task_id)},
                    )
                    await telemetry_dao.insert(
                        session,
                        task_id=str(task_id),
                        surprise_score=surprise_score,
                        x_vector=x_list,
                        weights=weights_list,
                        ocps_metadata=ocps_metadata,
                        chosen_route=str(decision),
                    )
                    return await enqueue_fn(
                        session,
                        task_id=str(task_id),
                        reason="router",
                        dedupe_key=dedupe_key,
                    )

                if use_tx:
                    async with session.begin():
                        inserted = await _run_ops()
                else:
                    inserted = await _run_ops()

                if metrics is not None:
                    metrics.record_outbox_enqueue("ok" if inserted else "dup")
                if inserted and prom_insert_ok:
                    try:
                        prom_insert_ok.labels("nim_task_embed").inc()
                    except Exception:
                        pass
                elif not inserted and prom_insert_dup:
                    try:
                        prom_insert_dup.labels("nim_task_embed").inc()
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning(
                "[Coordinator] Failed to persist router telemetry/outbox for %s: %s",
                task_id,
                exc,
            )
            if metrics is not None:
                metrics.record_outbox_enqueue("err")
            if prom_insert_err:
                try:
                    prom_insert_err.labels("nim_task_embed").inc()
                except Exception:
                    pass
            raise

        await self._enqueue_task_embedding_now(task_id)

    async def _enqueue_task_embedding_now(self, task_id: str, reason: str = "router") -> bool:
        try:
            from seedcore.graph.task_embedding_worker import enqueue_task_embedding_job
        except Exception as exc:  # pragma: no cover - optional dependency missing
            logger.info(
                "[Coordinator] Embedding worker unavailable; task %s will remain in outbox: %s",
                task_id,
                exc,
            )
            return False

        last_exc: Optional[BaseException] = None
        for attempt in range(2):
            try:
                ctx = getattr(self, "runtime_ctx", {}) or {}
                return await asyncio.wait_for(
                    enqueue_task_embedding_job(ctx, task_id, reason=reason),
                    timeout=5.0,
                )
            except asyncio.TimeoutError as exc:
                last_exc = exc
                logger.warning(
                    "[Coordinator] Embedding worker timed out (attempt %s) while enqueuing task %s",
                    attempt + 1,
                    task_id,
                )
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "[Coordinator] Failed to hand task %s to embedding worker on attempt %s: %s",
                    task_id,
                    attempt + 1,
                    exc,
                )
            await asyncio.sleep(0)

        if last_exc is not None:
            logger.debug(
                "[Coordinator] Falling back to outbox for task %s after enqueue failures: %s",
                task_id,
                last_exc,
            )
        return False

    async def process_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Backward-compatible wrapper around route_and_execute."""
        return await self.route_and_execute(payload)

    async def route_and_execute(self, payload: Dict[str, Any]):
        """
        HTTP endpoint for route-and-execute. Wraps core.route_and_execute.
        Accepts flexible dict and ensures TaskPayload has a task_id.
        """
        await self._ensure_background_tasks_started()
        try:
            # Ensure task_id exists for correlation
            if isinstance(payload, dict) and "task_id" not in payload:
                # Allow using 'id' if provided by callers
                if "id" in payload:
                    payload["task_id"] = str(payload["id"])
                else:
                    payload["task_id"] = uuid.uuid4().hex

            task_obj = TaskPayload.model_validate(payload)
            task_dict = task_obj.model_dump()
            task_dict.setdefault("id", task_obj.task_id)

            # Extract correlation_id from request if present
            correlation_id = None
            if isinstance(payload, dict):
                correlation_id = payload.get("correlation_id") or task_dict.get("correlation_id")
            if not correlation_id and hasattr(task_obj, "correlation_id"):
                correlation_id = getattr(task_obj, "correlation_id", None)

            repo = self.graph_task_repo or self._get_graph_repository()
            self.graph_task_repo = repo

            if repo is None or not hasattr(repo, "create_task"):
                message = (
                    f"[Coordinator] Task repository unavailable; cannot persist task {task_obj.task_id}"
                )
                logger.warning(message)
                raise HTTPException(status_code=503, detail="Task metadata repository unavailable")
            
            logger.info(f"[Coordinator] Using repository: {type(repo)} for task {task_obj.task_id}")

            agent_id: Optional[str] = None
            params = task_dict.get("params")
            if isinstance(params, dict):
                agent_id = params.get("agent_id")

            try:
                # Get a database session for the repository
                session_factory = self._resolve_session_factory(repo)
                if session_factory is None:
                    raise RuntimeError("session factory unavailable")
                async with session_factory() as session:
                    async with session.begin():
                        await repo.create_task(session, task_dict, agent_id=agent_id)
            except Exception as persist_exc:
                logger.warning(
                    "[Coordinator] Failed to persist incoming task %s: %s",
                    task_obj.task_id,
                    persist_exc,
                )
                raise HTTPException(status_code=503, detail="Failed to persist task metadata") from persist_exc

            res = await _maybe_call(
                self.core.route_and_execute,
                task_obj,
                correlation_id=correlation_id,
                coordinator_instance=self,
            )
            
            # Persist proto-plan if present
            decision = self._extract_decision(res)
            proto_plan = self._extract_proto_plan(res)
            if proto_plan:
                try:
                    await self._persist_proto_plan(
                        repo,
                        task_obj.task_id,
                        decision,
                        proto_plan,
                    )
                except Exception as exc:
                    logger.warning(
                        "[Coordinator] Failed to persist proto-plan for %s: %s",
                        task_obj.task_id,
                        exc,
                    )
            
            try:
                await self._record_router_telemetry(repo, task_obj.task_id, res)
            except Exception as exc:  # pragma: no cover - defensive logging, main result already returned
                logger.warning(
                    "[Coordinator] Unexpected error while recording router telemetry for %s: %s",
                    task_obj.task_id,
                    exc,
                )
            return res
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"[Coordinator] route_and_execute failed: {e}")
            return err(str(e), "coordinator_error")

    async def health(self):
        """Health check endpoint with PKG status."""
        response = {
            "status": "healthy",
            "coordinator": True,
            "pkg": self.core.pkg_metadata if hasattr(self.core, 'pkg_metadata') else {"enabled": False}
        }
        return response
    
    async def get_metrics(self):
        """Get current task execution metrics."""
        # Ensure background tasks are started
        await self._ensure_background_tasks_started()
        return self.metrics.get_metrics()
    
    async def ready(self):
        """Readiness probe for k8s."""
        return {"ready": bool(getattr(self, "_bg_started", False))}
    
    async def get_predicate_status(self):
        """Get predicate system status and GPU guard information."""
        import hashlib
        import os
        
        # Get file modification time and hash
        config_path = Path(PREDICATES_CONFIG_PATH)
        loaded_at = None
        file_hash = None
        
        if config_path.exists():
            stat = config_path.stat()
            loaded_at = time.ctime(stat.st_mtime)
            
            # Calculate file hash
            with open(config_path, 'rb') as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()[:16]
        
        return {
            "predicate_config": {
                "version": self.predicate_config.metadata.version,
                "commit": self.predicate_config.metadata.commit,
                "loaded_at": loaded_at,
                "file_hash": file_hash,
                "routing_rules": len(self.predicate_config.routing),
                "mutation_rules": len(self.predicate_config.mutations),
                "routing_enabled": getattr(self.predicate_config, 'routing_enabled', True),
                "mutations_enabled": getattr(self.predicate_config, 'mutations_enabled', True),
                "gpu_guard_enabled": getattr(self.predicate_config, 'gpu_guard_enabled', False),
                "is_fallback": self.predicate_config.metadata.version == "fallback"
            },
            "gpu_guard": self.predicate_router.get_gpu_guard_status(),
            "signals": self.predicate_router._signal_cache,
            "escalation_ratio": self.predicate_router.metrics.get_escalation_ratio(),
            "circuit_breakers": {
                "ml_service": self.ml_client.get_metrics(),
                "cognitive_service": self.cognitive_client.get_metrics(),
                "organism_service": self.organism_client.get_metrics()
            },
            "storage": {
                "backend": self.storage.get_backend_type(),
                "redis_available": self.storage.get_backend_type() == "redis"
            }
        }
    
    async def get_predicate_config(self):
        """Get current predicate configuration."""
        return self.predicate_config.dict()
    
    async def reload_predicates(self):
        """Reload predicate configuration from file."""
        try:
            self.predicate_config = load_predicates(PREDICATES_CONFIG_PATH)
            self.predicate_router = PredicateRouter(self.predicate_config)
            logger.info("✅ Predicate configuration reloaded")
            return {"success": True, "message": "Configuration reloaded successfully"}
        except Exception as e:
            logger.error(f"❌ Failed to reload predicate config: {e}")
            return {"success": False, "error": str(e)}
    
    async def tune_callback(self, payload: TuneCallbackRequest):
        """Callback endpoint for ML tuning job completion."""
        try:
            job_id = payload.job_id
            logger.info(f"[Coordinator] Received tuning callback for job {job_id}: {payload.status}")
            
            # Get persisted job state
            job_state = self._get_job_state(job_id)
            if not job_state:
                logger.warning(f"No job state found for {job_id}")
                return {"success": False, "error": "Job state not found"}
            
            # Calculate ΔE_realized
            if payload.status == "completed" and payload.E_after is not None:
                E_before = job_state.get("E_before")
                if E_before is not None:
                    deltaE = payload.E_after - E_before
                    
                    # Record metrics
                    self.predicate_router.metrics.record_deltaE_realized(
                        deltaE=deltaE,
                        gpu_seconds=payload.gpu_seconds or 0.0
                    )
                    
                    # Update GPU job status
                    self.predicate_router.update_gpu_job_status(job_id, "completed", success=True)
                    
                    logger.info(f"[Coordinator] Job {job_id} completed: ΔE={deltaE:.4f}, GPU_seconds={payload.gpu_seconds}")
                else:
                    logger.warning(f"No E_before found for job {job_id}")
            else:
                # Job failed
                self.predicate_router.update_gpu_job_status(job_id, "failed", success=False)
                logger.warning(f"Job {job_id} failed: {payload.error}")
            
            # Clean up job state
            self.storage.delete(f"job:{job_id}")
            
            return {"success": True, "message": "Callback processed"}
            
        except Exception as e:
            logger.error(f"❌ Error processing tuning callback: {e}")
            return {"success": False, "error": str(e)}

    async def anomaly_triage(self, payload: AnomalyTriageRequest):
        """
        Anomaly triage pipeline:
          1) Detect anomalies (ML)
          2) If OCPS escalates → HGNN (multi-plan) via Cognitive
             Else → FAST path (no planner/HGNN)
          3) Predicate: possibly submit tuning/retrain
          4) Fire-and-forget memory synthesis
          5) Return aggregated response
        """
        cid = uuid.uuid4().hex
        agent_id = payload.agent_id
        series = payload.series or []
        context = payload.context or {}

        # Drift & OCPS gate (True now means HGNN escalation)
        task_data = {
            "id": f"anomaly_triage_{agent_id}",
            "type": "anomaly_triage",
            "description": f"Anomaly triage for agent {agent_id}",
            "priority": 7,
            "complexity": 0.8,
            "series_length": len(series),
            "context": context,
        }
        drift_score = await self._compute_drift_score(task_data)
        ocps = getattr(self, "ocps", None)
        hgnn_escalate = bool(ocps.update(drift_score)) if ocps else True

        logger.info(
            "[Coordinator] anomaly_triage start agent=%s drift=%.4f hgnn_escalate=%s cid=%s",
            agent_id, drift_score, hgnn_escalate, cid
        )

        # 1) Detect anomalies
        try:
            anomalies = await asyncio.wait_for(
                self.ml_client.detect_anomaly({"data": series}), timeout=10
            )
        except Exception as e:
            logger.exception("[Coordinator] anomaly detection failed: %s", e)
            # Error envelope via your response model (FAST fallback semantics)
            return AnomalyTriageResponse(
                agent_id=agent_id,
                anomalies={"error": str(e)},
                reason={"result": {"thought": "ml error"}},
                decision={"result": {"action": "hold"}},
                correlation_id=cid,
                p_fast=getattr(ocps, "p_fast", None),
                escalated=False,
                tuning_job={"skipped": True},
            )

        # FAST short-circuit: no anomalies
        if not anomalies.get("anomalies"):
            decision = {"result": {"action": "hold", "reason": "no anomalies"}}
            asyncio.create_task(self._fire_and_forget_memory_synthesis(agent_id, anomalies, {}, decision, cid))
            logger.info("[Coordinator] No anomalies; FAST path (hold). cid=%s", cid)
            return AnomalyTriageResponse(
                agent_id=agent_id,
                anomalies=anomalies,
                reason={},                 # no planner/hgnn reasoning
                decision=decision,
                correlation_id=cid,
                p_fast=getattr(ocps, "p_fast", None),
                escalated=False,           # FAST
                tuning_job=None,
            )

        # 2) Route: HGNN (escalated) vs FAST
        reason: dict = {}                       # keep field for schema continuity
        decision: dict = {"result": {"action": "hold"}}

        if hgnn_escalate:
            # ESCALATED == "hgnn": trigger multi-plan path
            logger.info("[Coordinator] OCPS escalated → HGNN path. cid=%s", cid)

            # Canonical HGNN endpoint for multi-plan decomposition
            path = "/solve-problem"
            body = {
                "agent_id": agent_id,
                "problem_statement": f"Anomaly triage HGNN plan (agent={agent_id})",
                "constraints": {"latency_ms": self.fast_path_latency_slo_ms},
                "available_tools": {},                # optional
                "context": {                          # router context passthrough
                    "anomalies": anomalies.get("anomalies", []),
                    "meta": context,
                    "task_id": task_data["id"],
                    "correlation_id": cid,
                },
            }

            try:
                hgnn_resp = await asyncio.wait_for(
                    self.cognitive_client.post(path, json=body, headers=_corr_headers("cognitive", cid)),
                    timeout=20,
                )
            except Exception as e:
                logger.warning("[Coordinator] HGNN /solve-problem call failed: %s; trying legacy fallback", e)
                hgnn_resp = {"success": False, "error": str(e), "result": {}}
                
                # Fallback to legacy /plan-with-deep for backward compatibility
                if not hgnn_resp.get("success"):
                    try:
                        legacy_body = {
                            "agent_id": agent_id,
                            "task_description": f"Anomaly triage HGNN plan (agent={agent_id})",
                            "current_capabilities": {},
                            "available_tools": {},
                            "context": {
                                "anomalies": anomalies.get("anomalies", []),
                                "meta": context,
                                "task_id": task_data["id"],
                                "correlation_id": cid,
                            },
                            "profile": "deep",
                            "caller": "coordinator",
                        }
                        hgnn_resp = await self.cognitive_client.post(
                            "/plan-with-deep", json=legacy_body, headers=_corr_headers("cognitive", cid)
                        )
                        logger.info("[Coordinator] Legacy /plan-with-deep fallback succeeded")
                    except Exception as legacy_e:
                        logger.warning("[Coordinator] Legacy fallback also failed: %s; staying HOLD", legacy_e)
                        hgnn_resp = {"success": False, "error": str(legacy_e), "result": {}}

            # Optionally extract a suggested action from HGNN meta/plan (if your cog returns it)
            suggested = (
                hgnn_resp.get("result", {}).get("meta", {}) or {}
            ).get("suggested_action")

            if suggested:
                decision = {"result": {"action": suggested, "source": "hgnn"}}
            else:
                decision = {"result": {"action": "hold", "source": "hgnn"}}

            # Keep some reasoning breadcrumbs (optional)
            reason = {"result": {"planner": "hgnn", "meta": hgnn_resp.get("result", {}).get("meta", {})}}

        else:
            # FAST: no planner, no hgnn
            logger.info("[Coordinator] OCPS gated HGNN; FAST path. cid=%s", cid)
            decision = {"result": {"action": "hold", "source": "fast"}}

        # 3) Predicate: tune / retrain
        tuning_job = None
        action = (decision.get("result") or {}).get("action", "hold")
        mutation_decision = self.predicate_router.evaluate_mutation(
            task={"type": "anomaly_triage", "domain": "anomaly", "priority": 7, "complexity": 0.8},
            decision=decision.get("result", {}),
        )

        if mutation_decision.action in {"submit_tuning", "submit_retrain"}:
            try:
                current_energy = self._get_current_energy_state(agent_id)
                tuning_job = await self.ml_client.submit_tuning_job({
                    "space_type": TUNE_SPACE_TYPE,
                    "config_type": TUNE_CONFIG_TYPE,
                    "experiment_name": f"{TUNE_EXPERIMENT_PREFIX}-{agent_id}-{cid}",
                    "callback_url": f"{SEEDCORE_API_URL}/pipeline/ml/tune/callback",
                })
                if tuning_job.get("job_id") and current_energy is not None:
                    self._persist_job_state(tuning_job["job_id"], {
                        "E_before": current_energy,
                        "agent_id": agent_id,
                        "submitted_at": time.time(),
                        "job_type": mutation_decision.action.replace("submit_", ""),
                    })
                    self.predicate_router.update_gpu_job_status(tuning_job["job_id"], "started")
                logger.info("[Coordinator] tuning job submitted: %s (%s)", tuning_job.get("job_id", "unknown"), mutation_decision.reason)
            except Exception as e:
                logger.warning("[Coordinator] tuning submission failed: %s", e)
                tuning_job = {"error": str(e)}
        else:
            logger.info("[Coordinator] mutation decision: %s (%s)", mutation_decision.action, mutation_decision.reason)

        # 4) Memory synthesis (best-effort)
        asyncio.create_task(self._fire_and_forget_memory_synthesis(agent_id, anomalies, reason, decision, cid))

        # 5) Build response
        logger.info(
            "[Coordinator] anomaly_triage done agent=%s action=%s hgnn_escalated=%s cid=%s",
            agent_id, action, hgnn_escalate, cid
        )
        return AnomalyTriageResponse(
            agent_id=agent_id,
            anomalies=anomalies,
            reason=reason,                 # may include minimal HGNN meta
            decision=decision,             # action from HGNN if available; else 'hold'
            correlation_id=cid,
            p_fast=getattr(ocps, "p_fast", None),
            escalated=hgnn_escalate,       # True → HGNN (ResultKind.ESCALATED), False → FAST
            tuning_job=tuning_job,
        )


# Bind the deployment
coordinator_deployment = Coordinator.bind()

