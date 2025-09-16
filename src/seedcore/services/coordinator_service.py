# coordinator_service.py
import os, time, uuid, httpx, asyncio
from fastapi import FastAPI, HTTPException
from typing import Dict, Any, List, Optional, Iterable, Set, Tuple
from urllib.parse import urlparse
from pathlib import Path
from ray import serve
from pydantic import BaseModel, Field
import logging

try:  # Optional dependency - repository may not exist in all deployments
    from ..graph.graph_task_repository import GraphTaskRepository  # type: ignore
except ImportError:  # pragma: no cover - keep coordinator resilient when module missing
    GraphTaskRepository = None  # type: ignore

# Import predicate system
from ..predicates import PredicateRouter, load_predicates, load_predicates_async, get_metrics
from ..predicates.metrics import update_ocps_signals, update_energy_signals, record_request, record_latency
from ..predicates.circuit_breaker import ServiceClient, CircuitBreaker, RetryConfig
from ..predicates.safe_storage import SafeStorage
import redis
import json


from seedcore.logging_setup import ensure_serve_logger

logger = ensure_serve_logger("seedcore.coordinator", level="DEBUG")

# ---------- Config ----------
ORCH_TIMEOUT = float(os.getenv("ORCH_HTTP_TIMEOUT", "10"))
ML_TIMEOUT = float(os.getenv("ML_SERVICE_TIMEOUT", "8"))
COG_TIMEOUT = float(os.getenv("COGNITIVE_SERVICE_TIMEOUT", "15"))
ORG_TIMEOUT = float(os.getenv("ORGANISM_SERVICE_TIMEOUT", "5"))

SEEDCORE_API_URL = os.getenv("SEEDCORE_API_URL", "http://seedcore-api:8002")
SEEDCORE_API_TIMEOUT = float(os.getenv("SEEDCORE_API_TIMEOUT", "5.0"))

# Use Ray utilities to properly derive gateway URLs
from ..utils.ray_utils import SERVE_GATEWAY, ML, COG
ORG = f"{SERVE_GATEWAY}/organism"

# Log the derived gateway URLs for debugging
logger.info(f"🔗 Coordinator using gateway URLs:")
logger.info(f"   SERVE_GATEWAY: {SERVE_GATEWAY}")
logger.info(f"   ML: {ML}")
logger.info(f"   COG: {COG}")
logger.info(f"   ORG: {ORG}")

# Additional configuration for Coordinator
FAST_PATH_LATENCY_SLO_MS = float(os.getenv("FAST_PATH_LATENCY_SLO_MS", "1000"))
MAX_PLAN_STEPS = int(os.getenv("MAX_PLAN_STEPS", "16"))
COGNITIVE_MAX_INFLIGHT = int(os.getenv("COGNITIVE_MAX_INFLIGHT", "64"))

# Predicate system configuration
PREDICATES_CONFIG_PATH = os.getenv("PREDICATES_CONFIG_PATH", "/app/config/predicates.yaml")

# Redis configuration for job state persistence
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Tuning configuration
TUNE_SPACE_TYPE = os.getenv("TUNE_SPACE_TYPE", "basic")
TUNE_CONFIG_TYPE = os.getenv("TUNE_CONFIG_TYPE", "fast")
TUNE_EXPERIMENT_PREFIX = os.getenv("TUNE_EXPERIMENT_PREFIX", "coordinator-tune")

# ---------- Small helpers ----------
import inspect

async def _maybe_call(func, *a, **kw):
    """Helper to safely call either sync or async functions."""
    r = func(*a, **kw)
    return await r if inspect.isawaitable(r) else r

def _corr_headers(target: str, cid: str) -> Dict[str, str]:
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

# ---------- Coordination primitives ----------
class OCPSValve:
    """
    Neural-CUSUM accumulator for drift detection and escalation control.
    
    This implements the CUSUM algorithm: S_t = max(0, S_{t-1} + drift - nu)
    where:
    - S_t is the current CUSUM statistic
    - drift is the drift score from the ML service
    - nu is the drift threshold (typically 0.1)
    - h is the escalation threshold (from OCPS_DRIFT_THRESHOLD env var)
    
    RESET SEMANTICS:
    - Reset (S = 0) occurs ONLY on escalation (S > h)
    - This prevents under-escalation and spam escalations
    - The accumulator builds up drift evidence over time
    - Once threshold is exceeded, it resets to start fresh
    """
    def __init__(self, nu: float = 0.1, h: float = None):
        # h is your drift threshold (env OCPS_DRIFT_THRESHOLD)
        self.nu = nu
        self.h = float(os.getenv("OCPS_DRIFT_THRESHOLD", "0.5")) if h is None else h
        self.S = 0.0
        self.fast_hits = 0
        self.esc_hits = 0

    def update(self, drift: float) -> bool:
        """
        Update CUSUM statistic with new drift score.
        
        Args:
            drift: Drift score from ML service (s_t)
            
        Returns:
            bool: True if escalation triggered, False otherwise
            
        Note:
            Reset occurs ONLY on escalation to prevent under-escalation.
            This ensures the accumulator builds evidence over time before
            triggering escalation, preventing false positives.
        """
        self.S = max(0.0, self.S + drift - self.nu)
        esc = self.S > self.h
        if esc:
            self.esc_hits += 1
            self.S = 0.0  # Reset ONLY on escalation
        else:
            self.fast_hits += 1
        return esc

    @property
    def p_fast(self) -> float:
        tot = self.fast_hits + self.esc_hits
        return (self.fast_hits / tot) if tot else 1.0

class RoutingDirectory:
    """
    Minimal routing: map task_type[/domain] -> organ_id.
    The Coordinator owns this (global), but can refresh from Organism status if desired.
    """
    def __init__(self):
        self.by_task: Dict[str, str] = {}
        self.by_domain: Dict[tuple, str] = {}

    @staticmethod
    def _norm(x: Optional[str]) -> Optional[str]:
        return str(x).strip().lower() if x is not None else None

    def set_rule(self, task_type: str, organ_id: str, domain: Optional[str] = None):
        tt = self._norm(task_type); dm = self._norm(domain)
        if tt is None: return
        if dm: self.by_domain[(tt, dm)] = organ_id
        else:  self.by_task[tt] = organ_id

    def resolve(self, task_type: Optional[str], domain: Optional[str]) -> Optional[str]:
        tt = self._norm(task_type); dm = self._norm(domain)
        if not tt: return None
        if (tt, dm) in self.by_domain: return self.by_domain[(tt, dm)]
        return self.by_task.get(tt)

# ---------- Metrics tracking ----------
class MetricsTracker:
    """Track task execution metrics for monitoring and optimization."""
    def __init__(self):
        self._task_metrics = {
            "total_tasks": 0,
            "successful_tasks": 0,
            "failed_tasks": 0,
            "fast_path_tasks": 0,
            "hgnn_tasks": 0,
            "escalation_failures": 0,
            "fast_path_latency_ms": [],
            "hgnn_latency_ms": [],
            "escalation_latency_ms": []
        }
    
    def track_metrics(self, path: str, success: bool, latency_ms: float):
        """Track task execution metrics."""
        self._task_metrics["total_tasks"] += 1
        if success:
            self._task_metrics["successful_tasks"] += 1
        else:
            self._task_metrics["failed_tasks"] += 1
            
        if path == "fast":
            self._task_metrics["fast_path_tasks"] += 1
            self._task_metrics["fast_path_latency_ms"].append(latency_ms)
        elif path in ["hgnn", "hgnn_fallback"]:
            self._task_metrics["hgnn_tasks"] += 1
            self._task_metrics["hgnn_latency_ms"].append(latency_ms)
        elif path == "escalation_failure":
            self._task_metrics["escalation_failures"] += 1
            self._task_metrics["escalation_latency_ms"].append(latency_ms)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current task execution metrics."""
        metrics = self._task_metrics.copy()
        
        # Calculate averages
        if metrics.get("fast_path_latency_ms"):
            metrics["fast_path_latency_avg_ms"] = sum(metrics["fast_path_latency_ms"]) / len(metrics["fast_path_latency_ms"])
        if metrics.get("hgnn_latency_ms"):
            metrics["hgnn_latency_avg_ms"] = sum(metrics["hgnn_latency_ms"]) / len(metrics["hgnn_latency_ms"])
        if metrics.get("escalation_latency_ms"):
            metrics["escalation_latency_avg_ms"] = sum(metrics["escalation_latency_ms"]) / len(metrics["escalation_latency_ms"])
        
        # Calculate success rates
        if metrics["total_tasks"] > 0:
            metrics["success_rate"] = metrics["successful_tasks"] / metrics["total_tasks"]
            metrics["fast_path_rate"] = metrics["fast_path_tasks"] / metrics["total_tasks"]
            metrics["hgnn_rate"] = metrics["hgnn_tasks"] / metrics["total_tasks"]
        
        return metrics

# ---------- API models ----------
class Task(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: str
    description: Optional[str] = ""
    params: Dict[str, Any] = {}
    domain: Optional[str] = None
    features: Dict[str, Any] = {}
    history_ids: List[str] = []
    # Note: drift_score is now computed dynamically via ML service
    # … add fields as needed

class AnomalyTriageRequest(BaseModel):
    agent_id: str
    series: List[float] = []
    context: Dict[str, Any] = {}
    # Note: drift_score is now computed dynamically via ML service

class AnomalyTriageResponse(BaseModel):
    agent_id: str
    anomalies: Dict[str, Any]
    reason: Dict[str, Any]
    decision: Dict[str, Any]
    correlation_id: str
    p_fast: float
    escalated: bool
    tuning_job: Optional[Dict[str, Any]] = None

class TuneCallbackRequest(BaseModel):
    job_id: str
    E_before: Optional[float] = None
    E_after: Optional[float] = None
    gpu_seconds: Optional[float] = None
    status: str = "completed"  # completed, failed
    error: Optional[str] = None

# ---------- FastAPI/Serve ----------
app = FastAPI(title="SeedCore Coordinator")
router_prefix = "/pipeline"

@serve.deployment(
    name="Coordinator",
    num_replicas=int(os.getenv("COORDINATOR_REPLICAS", "1")),
    max_ongoing_requests=16,
    ray_actor_options={"num_cpus": float(os.getenv("COORDINATOR_NUM_CPUS", "0.2"))},
)
@serve.ingress(app)
class Coordinator:
    def __init__(self):
        # Initialize service clients with conservative circuit breakers
        self.ml_client = ServiceClient(
            "ml_service", ML, timeout=float(os.getenv("CB_ML_TIMEOUT_S", "5.0")),
            circuit_breaker=CircuitBreaker(
                failure_threshold=int(os.getenv("CB_FAIL_THRESHOLD", "5")),
                recovery_timeout=float(os.getenv("CB_RESET_S", "30.0")),
                expected_exception=(httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TimeoutException)
            ),
            retry_config=RetryConfig(max_attempts=1, base_delay=1.0, max_delay=2.0)
        )
        
        self.cognitive_client = ServiceClient(
            "cognitive_service", COG, timeout=float(os.getenv("CB_COG_TIMEOUT_S", "8.0")),
            circuit_breaker=CircuitBreaker(
                failure_threshold=int(os.getenv("CB_FAIL_THRESHOLD", "5")),
                recovery_timeout=float(os.getenv("CB_RESET_S", "30.0")),
                expected_exception=(httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TimeoutException)
            ),
            retry_config=RetryConfig(max_attempts=1, base_delay=1.0, max_delay=2.0)  # Allow 1 retry for cognitive
        )
        
        self.organism_client = ServiceClient(
            "organism_service", ORG, timeout=float(os.getenv("CB_ORG_TIMEOUT_S", "5.0")),
            circuit_breaker=CircuitBreaker(
                failure_threshold=int(os.getenv("CB_FAIL_THRESHOLD", "5")),
                recovery_timeout=float(os.getenv("CB_RESET_S", "30.0")),
                expected_exception=(httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TimeoutException)
            ),
            retry_config=RetryConfig(max_attempts=0, base_delay=0.0)  # No retries for organism
        )
        
        # Legacy HTTP client for backward compatibility
        self.http = httpx.AsyncClient(
            timeout=ORCH_TIMEOUT,
            limits=httpx.Limits(max_keepalive_connections=100, max_connections=200),
        )
        self.ocps = OCPSValve()
        self.routing = RoutingDirectory()
        self.metrics = MetricsTracker()

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
        
        # Initialize predicate system (will be loaded async in __post_init__)
        self.predicate_config = None
        self.predicate_router = None
        
        # sensible defaults (avoid cognitive for simple)
        self.routing.set_rule("general_query", "utility_organ_1")
        self.routing.set_rule("health_check", "utility_organ_1")
        self.routing.set_rule("execute", "actuator_organ_1")
        
        # Graph task routing (Migration 007+)
        self.routing.set_rule("graph_embed", "graph_dispatcher")
        self.routing.set_rule("graph_rag_query", "graph_dispatcher")
        self.routing.set_rule("graph_embed_v2", "graph_dispatcher")
        self.routing.set_rule("graph_rag_query_v2", "graph_dispatcher")
        self.routing.set_rule("graph_sync_nodes", "graph_dispatcher")
        
        # Facts system routing (Migration 009)
        self.routing.set_rule("graph_fact_embed", "graph_dispatcher")
        self.routing.set_rule("graph_fact_query", "graph_dispatcher")
        self.routing.set_rule("fact_search", "utility_organ_1")
        self.routing.set_rule("fact_store", "utility_organ_1")
        
        # Resource management routing (Migration 007)
        self.routing.set_rule("artifact_manage", "utility_organ_1")
        self.routing.set_rule("capability_manage", "utility_organ_1")
        self.routing.set_rule("memory_cell_manage", "utility_organ_1")
        
        # Agent layer routing (Migration 008)
        self.routing.set_rule("model_manage", "utility_organ_1")
        self.routing.set_rule("policy_manage", "utility_organ_1")
        self.routing.set_rule("service_manage", "utility_organ_1")
        self.routing.set_rule("skill_manage", "utility_organ_1")
        
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
        
        # Start background tasks (will be called after initialization)
        self._background_tasks_started = False
        self._warmup_started = False
        
        logger.info("✅ Coordinator initialized")

    async def _ensure_background_tasks_started(self):
        """Ensure background tasks are started (called on first request)."""
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
            
            # First, check if ML service is healthy with circuit-breaker metrics
            try:
                health_response = await self.ml_client.get("/health")
                if health_response.get("status") != "healthy":
                    logger.warning(f"⚠️ ML service health check failed: {health_response}")
                    # Record circuit-breaker metrics for failed health check
                    self.predicate_router.metrics.record_circuit_breaker_event("ml_service", "health_check_failed")
                    return
                logger.info("✅ ML service health check passed")
                # Record circuit-breaker metrics for successful health check
                self.predicate_router.metrics.record_circuit_breaker_event("ml_service", "health_check_success")
            except Exception as e:
                logger.warning(f"⚠️ ML service health check failed: {e}, skipping warmup")
                # Record circuit-breaker metrics for health check exception
                self.predicate_router.metrics.record_circuit_breaker_event("ml_service", "health_check_exception")
                return
            
            logger.info(f"🔄 Calling ML service warmup at {self.ml_client.base_url}/drift/warmup")
            
            # Try warmup with retries
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = await self.ml_client.post(
                        "/drift/warmup",
                        json=warmup_request,
                        headers=_corr_headers("ml_service", "coordinator_warmup")
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
        try:
            # This would typically call the energy service or get from agent state
            # For now, return a placeholder value
            return 0.5  # TODO: Implement actual energy state retrieval
        except Exception as e:
            logger.warning(f"Failed to get energy state for agent {agent_id}: {e}")
            return None
    
    async def _compute_drift_score(self, task: Dict[str, Any]) -> float:
        """
        Compute drift score using the ML service drift detector.
        
        This method:
        1. Calls the ML service /drift/score endpoint
        2. Extracts drift score from the response
        3. Falls back to a default value if the service is unavailable
        4. Tracks performance and error metrics for monitoring
        
        Returns:
            Drift score suitable for OCPSValve integration
        """
        start_time = time.time()
        task_id = task.get("id", "unknown")
        
        try:
            # Build comprehensive text payload for drift detection
            # Combine description, domain, params, and type for better featurization
            description = task.get("description", "")
            domain = task.get("domain", "")
            task_type = task.get("type", "unknown")
            params = task.get("params", {})
            
            # Build rich text context for drift detection
            text_parts = []
            if description:
                text_parts.append(f"Description: {description}")
            if domain:
                text_parts.append(f"Domain: {domain}")
            if task_type:
                text_parts.append(f"Type: {task_type}")
            if params:
                # Convert params to readable text
                param_text = ", ".join([f"{k}={v}" for k, v in params.items()])
                text_parts.append(f"Parameters: {param_text}")
            
            # Fallback to task type if no other text available
            text_payload = " ".join(text_parts) if text_parts else f"Task type: {task_type}"
            
            # Log the text payload for debugging
            logger.info(f"[DriftDetector] Task {task_id}: Text payload: '{text_payload[:100]}{'...' if len(text_payload) > 100 else ''}'")
            
            # Prepare request for drift scoring
            drift_request = {
                "task": task,
                "text": text_payload
            }
            
            logger.debug(f"[DriftDetector] Task {task_id}: Calling ML service at {self.ml_client.base_url}/drift/score")
            logger.debug(f"[DriftDetector] Task {task_id}: Request payload: {drift_request}")
            
            # Call ML service drift detector with timeout
            response = await self.ml_client.post(
                "/drift/score",
                json=drift_request,
                headers=_corr_headers("ml_service", task_id)
            )
            
            logger.debug(f"[DriftDetector] Task {task_id}: ML service response: {response}")
            
            processing_time = (time.time() - start_time) * 1000
            
            if response.get("status") == "success":
                drift_score = response.get("drift_score", 0.0)
                ml_processing_time = response.get("processing_time_ms", 0.0)
                
                # Log performance metrics
                logger.debug(f"[DriftDetector] Task {task_id}: score={drift_score:.4f}, "
                           f"total_time={processing_time:.2f}ms, ml_time={ml_processing_time:.2f}ms")
                
                # Track metrics for monitoring
                drift_mode = response.get('drift_mode', 'unknown')
                self.predicate_router.metrics.record_drift_computation("success", drift_mode, processing_time / 1000.0, drift_score)
                
                return drift_score
            else:
                error_msg = response.get('error', 'Unknown error')
                logger.warning(f"[DriftDetector] Task {task_id}: ML service returned error: {error_msg}")
                self.predicate_router.metrics.record_drift_computation("ml_error", "unknown", processing_time / 1000.0, 0.0)
                return 0.0
                
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TimeoutException) as e:
            processing_time = (time.time() - start_time) * 1000
            error_msg = str(e) if str(e) else f"{type(e).__name__}"
            logger.warning(f"[DriftDetector] Task {task_id}: ML service timeout after {processing_time:.2f}ms: {error_msg}, using fallback")
            
            # Track timeout metrics
            self.predicate_router.metrics.record_drift_computation("timeout", "unknown", processing_time / 1000.0, 0.0)
            
            # Fallback: use a simple heuristic based on task properties
            fallback_score = self._fallback_drift_score(task)
            logger.info(f"[DriftDetector] Task {task_id}: Using fallback score {fallback_score:.4f}")
            return fallback_score
            
        except Exception as e:
            processing_time = (time.time() - start_time) * 1000
            error_msg = str(e) if str(e) else f"{type(e).__name__}"
            logger.warning(f"[DriftDetector] Task {task_id}: Failed to compute drift score: {error_msg}, using fallback")
            logger.debug(f"[DriftDetector] Task {task_id}: Exception details: {type(e).__name__}: {error_msg}")
            import traceback
            logger.debug(f"[DriftDetector] Task {task_id}: Traceback: {traceback.format_exc()}")
            
            # Track error metrics
            self.predicate_router.metrics.record_drift_computation("error", "unknown", processing_time / 1000.0, 0.0)
            
            # Fallback: use a simple heuristic based on task properties
            fallback_score = self._fallback_drift_score(task)
            logger.info(f"[DriftDetector] Task {task_id}: Using fallback score {fallback_score:.4f}")
            return fallback_score
    
    def _fallback_drift_score(self, task: Dict[str, Any]) -> float:
        """
        Fallback drift score computation when ML service is unavailable.
        
        Uses simple heuristics based on task properties.
        """
        try:
            # Base score
            score = 0.0
            
            # Task type influence
            task_type = str(task.get("type", "unknown")).lower()
            if task_type == "anomaly_triage":
                score += 0.3  # Anomaly triage tasks are more likely to indicate drift
            elif task_type == "execute":
                score += 0.1  # Execute tasks have moderate drift potential
            elif task_type in ("graph_fact_embed", "graph_fact_query"):
                score += 0.2  # Fact operations have moderate drift potential
            elif task_type in ("graph_embed", "graph_rag_query", "graph_embed_v2", "graph_rag_query_v2"):
                score += 0.15  # Graph operations have moderate drift potential
            elif task_type in ("artifact_manage", "capability_manage", "memory_cell_manage"):
                score += 0.1  # Resource management has low drift potential
            elif task_type in ("model_manage", "policy_manage", "service_manage", "skill_manage"):
                score += 0.05  # Agent layer management has very low drift potential
            
            # Priority influence
            priority = float(task.get("priority", 5))
            if priority >= 8:
                score += 0.2  # High priority tasks may indicate system stress
            elif priority <= 3:
                score += 0.1  # Low priority tasks might indicate system changes
            
            # Complexity influence
            complexity = float(task.get("complexity", 0.5))
            score += complexity * 0.2  # More complex tasks have higher drift potential
            
            # History influence
            history_ids = task.get("history_ids", [])
            if len(history_ids) == 0:
                score += 0.1  # New tasks without history might indicate drift
            
            # Ensure score is in reasonable range
            return max(0.0, min(1.0, score))
            
        except Exception as e:
            logger.warning(f"Fallback drift score computation failed: {e}")
            return 0.5  # Neutral fallback
    
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
    
    def _redact_sensitive_data(self, data: Any) -> Any:
        """Redact sensitive data from memory synthesis payload."""
        if isinstance(data, dict):
            redacted = {}
            for key, value in data.items():
                if any(sensitive in key.lower() for sensitive in ['password', 'token', 'key', 'secret', 'auth']):
                    redacted[key] = "[REDACTED]"
                else:
                    redacted[key] = self._redact_sensitive_data(value)
            return redacted
        elif isinstance(data, list):
            return [self._redact_sensitive_data(item) for item in data]
        elif isinstance(data, str) and len(data) > 1000:
            return data[:1000] + "... [TRUNCATED]"
        else:
            return data

    def _normalize_task_dict(self, task_like: Any) -> Tuple[uuid.UUID, Dict[str, Any]]:
        task_dict = self._convert_task_to_dict(task_like) or {}
        raw_id = task_dict.get("id") or task_dict.get("task_id")
        try:
            task_uuid = uuid.UUID(str(raw_id)) if raw_id else uuid.uuid4()
        except (ValueError, TypeError):
            task_uuid = uuid.uuid4()
        task_id_str = str(task_uuid)
        task_dict["id"] = task_id_str
        self._sync_task_identity(task_like, task_id_str)
        return task_uuid, task_dict

    def _sync_task_identity(self, task_like: Any, task_id: str) -> None:
        if isinstance(task_like, dict):
            task_like["id"] = task_id
            return
        for attr in ("id", "task_id"):
            if hasattr(task_like, attr):
                try:
                    setattr(task_like, attr, task_id)
                except Exception:
                    continue

    def _extract_agent_id(self, task_dict: Dict[str, Any]) -> Optional[str]:
        if not isinstance(task_dict, dict):
            return None
        candidate = task_dict.get("agent_id") or task_dict.get("agent")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

        params = task_dict.get("params")
        if isinstance(params, dict):
            for key in ("agent_id", "agent", "owner_agent_id"):
                value = params.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        metadata = task_dict.get("metadata")
        if isinstance(metadata, dict):
            for key in ("agent_id", "agent"):
                value = metadata.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    def prefetch_context(self, task: Dict[str, Any]) -> None:
        """Hook for Mw/Mlt prefetch as per §8.6 Unified RAG Operations. No-op until memory wired."""
        pass

    async def _hgnn_decompose(self, task: Task) -> List[Dict[str, Any]]:
        """
        Enhanced HGNN-based decomposition using CognitiveCore Serve deployment.
        
        This method:
        1. Checks if cognitive client is available and healthy
        2. Calls CognitiveCore for intelligent task decomposition
        3. Validates the returned plan
        4. Falls back to simple routing if cognitive reasoning fails
        """
        try:
            # Prepare request for cognitive service
            req = {
                "agent_id": f"hgnn_planner_{task.id}",
                "problem_statement": task.description or str(task.model_dump()),
                "task_id": task.id,
                "type": task.type,
                "constraints": {"latency_ms": self.fast_path_latency_slo_ms},
                "context": {
                    "features": task.features, 
                    "history_ids": task.history_ids,
                    # Add support for new node types (Migration 007+)
                    "start_fact_ids": getattr(task, 'start_fact_ids', []),
                    "start_artifact_ids": getattr(task, 'start_artifact_ids', []),
                    "start_capability_ids": getattr(task, 'start_capability_ids', []),
                    "start_memory_cell_ids": getattr(task, 'start_memory_cell_ids', []),
                    "start_model_ids": getattr(task, 'start_model_ids', []),
                    "start_policy_ids": getattr(task, 'start_policy_ids', []),
                    "start_service_ids": getattr(task, 'start_service_ids', []),
                    "start_skill_ids": getattr(task, 'start_skill_ids', []),
                },
                "available_organs": [],  # Could be populated from organism status
            }
            
            # Call cognitive service
            plan = await _apost(
                self.http, f"{COG}/plan-task", req, 
                _corr_headers("cognitive", task.id), timeout=COG_TIMEOUT
            )
            
            # Extract solution steps from cognitive response
            steps = []
            if plan.get("success") and plan.get("result"):
                # The cognitive service returns {success, agent_id, result, error}
                # We need to extract the solution steps from the result
                result = plan.get("result", {})
                steps = result.get("solution_steps", [])
                if not steps:
                    # If no solution_steps, try to extract from other fields
                    steps = result.get("plan", []) or result.get("steps", [])
            
            validated_plan = self._validate_or_fallback(steps, self._convert_task_to_dict(task))
            
            if validated_plan:
                logger.info(f"[Coordinator] HGNN decomposition successful: {len(validated_plan)} steps")
                return validated_plan
            else:
                logger.warning(f"[Coordinator] HGNN plan validation failed, using fallback")
                return self._fallback_plan(self._convert_task_to_dict(task))
                
        except Exception as e:
            logger.warning(f"[Coordinator] HGNN decomposition failed: {e}, using fallback")
            return self._fallback_plan(self._convert_task_to_dict(task))

    def _convert_task_to_dict(self, task) -> Dict[str, Any]:
        """Convert task object to dictionary, handling TaskPayload and other types."""
        if isinstance(task, dict):
            return task
        elif hasattr(task, 'model_dump'):
            task_dict = task.model_dump()
            # Handle TaskPayload which has 'task_id' instead of 'id'
            if hasattr(task, 'task_id') and 'id' not in task_dict:
                task_dict['id'] = task.task_id
            return task_dict
        elif hasattr(task, 'dict'):
            task_dict = task.dict()
            # Handle TaskPayload which has 'task_id' instead of 'id'
            if hasattr(task, 'task_id') and 'id' not in task_dict:
                task_dict['id'] = task.task_id
            return task_dict
        else:
            logger.warning(f"[Coordinator] Cannot convert task to dict: {type(task)}")
            return {}

    def _fallback_plan(self, task: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create a minimal safe fallback plan when cognitive reasoning is unavailable."""
        ttype = (task.get("type") or task.get("task_type") or "").strip().lower()
        
        # Try to find an organ that supports this task type
        organ_id = self.routing.resolve(ttype, task.get("domain"))
        if organ_id:
            return [{"organ_id": organ_id, "task": task}]
        
        # Special handling for graph tasks (Migration 007+)
        if ttype in ("graph_embed", "graph_rag_query", "graph_embed_v2", "graph_rag_query_v2", 
                     "graph_fact_embed", "graph_fact_query", "graph_sync_nodes"):
            return [{"organ_id": "graph_dispatcher", "task": task}]
        
        # Special handling for fact operations (Migration 009)
        if ttype in ("fact_search", "fact_store"):
            return [{"organ_id": "utility_organ_1", "task": task}]
        
        # Special handling for resource management (Migration 007)
        if ttype in ("artifact_manage", "capability_manage", "memory_cell_manage"):
            return [{"organ_id": "utility_organ_1", "task": task}]
        
        # Special handling for agent layer management (Migration 008)
        if ttype in ("model_manage", "policy_manage", "service_manage", "skill_manage"):
            return [{"organ_id": "utility_organ_1", "task": task}]
        
        # Fallback: use first available organ (simple round-robin)
        # This would need to be populated from organism status in practice
        return [{"organ_id": "utility_organ_1", "task": task}]

    def _validate_or_fallback(self, plan: List[Dict[str, Any]], task: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """Validate the plan from CognitiveCore and return fallback if invalid."""
        if not isinstance(plan, list) or len(plan) > self.max_plan_steps:
            logger.warning(f"Plan validation failed: invalid format or too many steps ({len(plan) if isinstance(plan, list) else 'not a list'})")
            return None

        for idx, step in enumerate(plan):
            if not isinstance(step, dict):
                logger.warning(f"Plan validation failed: step is not a dict: {step}")
                return None

            if "organ_id" not in step or "task" not in step:
                logger.warning(f"Plan validation failed: step missing required fields: {step}")
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

        if GraphTaskRepository is None:
            return None

        try:
            self.graph_repository = GraphTaskRepository()
        except TypeError as exc:
            logger.debug(f"GraphTaskRepository instantiation failed (signature mismatch): {exc}")
            self.graph_repository = None
        except Exception as exc:  # pragma: no cover - defensive logging for unexpected errors
            logger.warning(f"GraphTaskRepository initialization failed: {exc}")
            self.graph_repository = None

        return self.graph_repository

    async def _persist_plan_subtasks(
        self,
        task: Task,
        plan: List[Dict[str, Any]],
        *,
        root_db_id: Optional[uuid.UUID] = None,
    ):
        """Insert subtasks for the HGNN plan and register dependency edges."""
        if not plan:
            return []

        repo = self._get_graph_repository()
        if repo is None:
            return []

        if not hasattr(repo, "insert_subtasks"):
            logger.debug("GraphTaskRepository missing insert_subtasks; skipping subtask persistence")
            return []

        try:
            inserted = await _maybe_call(repo.insert_subtasks, task.id, plan)
        except Exception as exc:
            logger.warning(
                "[Coordinator] insert_subtasks failed for task %s: %s",
                getattr(task, "id", "unknown"),
                exc,
            )
            return []

        if root_db_id is not None and hasattr(repo, "add_dependency"):
            try:
                for idx, record in enumerate(inserted or []):
                    fallback_step = plan[idx] if idx < len(plan) else None
                    child_value = self._resolve_child_task_id(record, fallback_step)
                    if child_value is None:
                        continue
                    try:
                        await _maybe_call(repo.add_dependency, root_db_id, child_value)
                    except Exception as exc:
                        logger.error(
                            f"[Coordinator] Failed to add root dependency {root_db_id} -> {child_value}: {exc}"
                        )
            except Exception as exc:
                logger.error(
                    "[Coordinator] Failed to register root dependency edges for %s: %s",
                    getattr(task, "id", "unknown"),
                    exc,
                )

        try:
            await self._register_task_dependencies(plan, inserted)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(
                "[Coordinator] Failed to register task dependencies for %s: %s",
                getattr(task, "id", "unknown"),
                exc,
            )

        return inserted

    async def _register_task_dependencies(self, plan: List[Dict[str, Any]], inserted_subtasks: Any) -> None:
        """Record dependency edges (parent → child) for inserted subtasks."""
        repo = self._get_graph_repository()
        if repo is None or not hasattr(repo, "add_dependency"):
            return

        plan_steps = list(plan or [])
        inserted = list(inserted_subtasks or [])

        if not plan_steps or not inserted:
            return

        alias_to_child: Dict[str, Any] = {}
        index_to_child: Dict[int, Any] = {}
        known_child_keys: Set[str] = set()

        for idx, record in enumerate(inserted):
            fallback_step = plan_steps[idx] if idx < len(plan_steps) else None
            child_value = self._resolve_child_task_id(record, fallback_step)
            if child_value is None:
                continue

            child_key = self._canonicalize_identifier(child_value)
            if not child_key:
                continue

            index_to_child[idx] = child_value
            known_child_keys.add(child_key)
            alias_to_child[child_key] = child_value

            for alias in self._collect_record_aliases(record):
                alias_to_child[alias] = child_value

            if fallback_step is not None:
                for alias in self._collect_step_aliases(fallback_step):
                    alias_to_child[alias] = child_value

        if not index_to_child:
            logger.debug("No subtask identifiers resolved; skipping dependency registration")
            return

        invalid_refs: Set[str] = set()
        edges_added: Set[Tuple[str, str]] = set()

        for idx, step in enumerate(plan_steps):
            dependencies = step.get("depends_on") if isinstance(step, dict) else getattr(step, "depends_on", None)
            if not dependencies:
                continue

            child_value = index_to_child.get(idx)
            if child_value is None:
                for alias in self._collect_step_aliases(step):
                    child_value = alias_to_child.get(alias)
                    if child_value is not None:
                        break

            if child_value is None:
                logger.warning(f"[Coordinator] Skipping dependency recording for step {idx}: missing child task ID")
                continue

            child_key = self._canonicalize_identifier(child_value)

            for dep_entry in self._iter_dependency_entries(dependencies):
                dep_token = self._extract_dependency_token(dep_entry)
                if dep_token is None:
                    dep_repr = repr(dep_entry)
                    if dep_repr not in invalid_refs:
                        logger.warning(f"[Coordinator] Ignoring invalid dependency reference {dep_repr} for child {child_key}")
                        invalid_refs.add(dep_repr)
                    continue

                parent_value = None
                if isinstance(dep_token, int):
                    parent_value = index_to_child.get(dep_token)
                else:
                    parent_key = self._canonicalize_identifier(dep_token)
                    parent_value = alias_to_child.get(parent_key)
                    if parent_value is None and parent_key.isdigit():
                        parent_value = index_to_child.get(int(parent_key))

                if parent_value is None:
                    dep_key = self._canonicalize_identifier(dep_token)
                    if dep_key not in invalid_refs:
                        logger.warning(
                            f"[Coordinator] Dependency reference {dep_entry!r} for child {child_key} does not match any known subtask"
                        )
                        invalid_refs.add(dep_key)
                    continue

                parent_key = self._canonicalize_identifier(parent_value)

                if parent_key not in known_child_keys:
                    if parent_key not in invalid_refs:
                        logger.warning(
                            f"[Coordinator] Dependency parent {parent_key} for child {child_key} is unknown; skipping"
                        )
                        invalid_refs.add(parent_key)
                    continue

                if parent_key == child_key:
                    logger.warning(f"[Coordinator] Skipping self-dependency for task {child_key}")
                    continue

                edge_key = (parent_key, child_key)
                if edge_key in edges_added:
                    continue

                try:
                    await _maybe_call(repo.add_dependency, parent_value, child_value)
                except Exception as exc:  # pragma: no cover - repository errors should not crash coordinator
                    logger.error(
                        f"[Coordinator] Failed to add dependency {parent_key} -> {child_key}: {exc}"
                    )
                else:
                    edges_added.add(edge_key)

    def _iter_dependency_entries(self, dependencies: Any) -> Iterable[Any]:
        if dependencies is None:
            return []

        if isinstance(dependencies, (list, tuple, set)):
            for item in dependencies:
                if isinstance(item, (list, tuple, set)):
                    for nested in self._iter_dependency_entries(item):
                        yield nested
                else:
                    yield item
        else:
            yield dependencies

    def _resolve_child_task_id(self, record: Any, fallback_step: Any) -> Any:
        """Extract the task identifier for a persisted subtask."""
        if record is not None:
            if isinstance(record, dict):
                for key in ("task_id", "id", "child_task_id", "subtask_id"):
                    if key in record:
                        token = self._extract_dependency_token(record[key])
                        if token is not None:
                            return token
                if "task" in record:
                    token = self._extract_dependency_token(record["task"])
                    if token is not None:
                        return token
            else:
                for attr in ("task_id", "id", "child_task_id", "subtask_id"):
                    if hasattr(record, attr):
                        token = self._extract_dependency_token(getattr(record, attr))
                        if token is not None:
                            return token
                if hasattr(record, "task"):
                    token = self._extract_dependency_token(getattr(record, "task"))
                    if token is not None:
                        return token

        if fallback_step is not None:
            if isinstance(fallback_step, dict):
                for key in ("task_id", "id", "step_id"):
                    if key in fallback_step:
                        token = self._extract_dependency_token(fallback_step[key])
                        if token is not None:
                            return token
                if "task" in fallback_step:
                    token = self._extract_dependency_token(fallback_step["task"])
                    if token is not None:
                        return token
            else:
                for attr in ("task_id", "id", "step_id"):
                    if hasattr(fallback_step, attr):
                        token = self._extract_dependency_token(getattr(fallback_step, attr))
                        if token is not None:
                            return token
                if hasattr(fallback_step, "task"):
                    token = self._extract_dependency_token(getattr(fallback_step, "task"))
                    if token is not None:
                        return token

        return None

    def _collect_record_aliases(self, record: Any) -> Set[str]:
        aliases: Set[str] = set()

        if isinstance(record, dict):
            aliases.update(self._collect_aliases_from_mapping(record))
            maybe_task = record.get("task")
            if isinstance(maybe_task, dict):
                aliases.update(self._collect_aliases_from_mapping(maybe_task))
            maybe_meta = record.get("metadata")
            if isinstance(maybe_meta, dict):
                aliases.update(self._collect_aliases_from_mapping(maybe_meta))
        else:
            aliases.update(self._collect_aliases_from_object(record))

        return aliases

    def _collect_step_aliases(self, step: Any) -> Set[str]:
        aliases: Set[str] = set()

        if isinstance(step, dict):
            aliases.update(self._collect_aliases_from_mapping(step))
            maybe_task = step.get("task")
            if isinstance(maybe_task, dict):
                aliases.update(self._collect_aliases_from_mapping(maybe_task))
            maybe_meta = step.get("metadata")
            if isinstance(maybe_meta, dict):
                aliases.update(self._collect_aliases_from_mapping(maybe_meta))
        else:
            aliases.update(self._collect_aliases_from_object(step))

        return aliases

    def _collect_aliases_from_mapping(self, mapping: Dict[str, Any]) -> Set[str]:
        aliases: Set[str] = set()
        alias_keys = {"task_id", "id", "step_id", "original_task_id", "child_task_id", "source_task_id", "parent_task_id"}

        for key in alias_keys:
            if key in mapping:
                token = self._extract_dependency_token(mapping[key])
                if token is not None:
                    aliases.add(self._canonicalize_identifier(token))

        for value in mapping.values():
            if isinstance(value, dict):
                aliases.update(self._collect_aliases_from_mapping(value))

        return aliases

    def _collect_aliases_from_object(self, obj: Any) -> Set[str]:
        aliases: Set[str] = set()
        alias_keys = ("task_id", "id", "step_id", "original_task_id", "child_task_id", "source_task_id", "parent_task_id")

        for key in alias_keys:
            if hasattr(obj, key):
                token = self._extract_dependency_token(getattr(obj, key))
                if token is not None:
                    aliases.add(self._canonicalize_identifier(token))

        for attr in ("task", "metadata"):
            if hasattr(obj, attr):
                value = getattr(obj, attr)
                if isinstance(value, dict):
                    aliases.update(self._collect_aliases_from_mapping(value))

        return aliases

    def _extract_dependency_token(self, ref: Any) -> Any:
        if ref is None:
            return None

        if isinstance(ref, (list, tuple, set)):
            for item in ref:
                token = self._extract_dependency_token(item)
                if token is not None:
                    return token
            return None

        if isinstance(ref, dict):
            for key in ("task_id", "id", "parent_task_id", "source_task_id", "step_id", "child_task_id", "task"):
                if key in ref:
                    token = self._extract_dependency_token(ref[key])
                    if token is not None:
                        return token
            return None

        for attr in ("task_id", "id", "parent_task_id", "source_task_id", "step_id", "child_task_id"):
            if hasattr(ref, attr):
                token = self._extract_dependency_token(getattr(ref, attr))
                if token is not None:
                    return token

        if isinstance(ref, float) and ref.is_integer():
            return int(ref)

        return ref

    def _canonicalize_identifier(self, value: Any) -> str:
        if value is None:
            return ""

        if isinstance(value, uuid.UUID):
            return str(value)

        if isinstance(value, bool):
            return "1" if value else "0"

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if isinstance(value, float):
                if value.is_integer():
                    value = int(value)
                else:
                    return str(value)
            return str(value)

        return str(value)

    def _make_escalation_result(self, results: List[Dict[str, Any]], plan: List[Dict[str, Any]], success: bool) -> Dict[str, Any]:
        """Create a properly formatted escalation result."""
        return {
            "success": success,
            "escalated": True,
            "plan_source": "cognitive_core",
            "plan": plan,
            "results": results,
            "path": "hgnn"
        }

    async def _execute_fast(self, task: Task, organ_id: str, cid: str) -> Dict[str, Any]:
        _, task_dict = self._normalize_task_dict(task)
        agent_id = self._extract_agent_id(task_dict)

        params = task_dict.get("params") if isinstance(task_dict.get("params"), dict) else {}
        organ_timeout = params.get("organ_timeout_s", 30.0)
        try:
            organ_timeout = float(organ_timeout)
            # Clamp organ_timeout to reasonable bounds (1s to 300s)
            organ_timeout = max(1.0, min(300.0, organ_timeout))
        except (TypeError, ValueError):
            organ_timeout = 30.0

        # Inject computed drift_score and energy budgets before persisting
        task_dict["drift_score"] = await self._compute_drift_score(task_dict)
        
        # Ensure params has token/energy settings if present in predicates
        if "params" not in task_dict:
            task_dict["params"] = {}
        
        # Add energy budget information if available
        if hasattr(self, 'predicate_router') and self.predicate_router:
            energy_budget = getattr(self.predicate_router, 'get_energy_budget', lambda: None)()
            if energy_budget is not None:
                task_dict["params"]["energy_budget"] = energy_budget
        
        try:
            await self.graph_task_repo.create_task(task_dict, agent_id=agent_id, organ_id=organ_id)
        except Exception as e:
            logger.warning(
                f"[Coordinator] Failed to persist fast path task {task_dict.get('id')}: {e}"
            )

        payload = {
            "organ_id": organ_id,
            "task": task_dict,
            "organ_timeout_s": organ_timeout,
        }
        return await _apost(
            self.http, f"{ORG}/execute-on-organ", payload,
            _corr_headers("organism", cid), timeout=ORG_TIMEOUT
        )

    async def _execute_hgnn(self, task: Task, cid: str) -> Dict[str, Any]:
        """
        Ask Cognitive to decompose → then call Organism step-by-step.
        Falls back to round-robin if Cognitive fails.
        """
        start_time = time.time()
        _, root_task_dict = self._normalize_task_dict(task)
        root_agent_id = self._extract_agent_id(root_task_dict)

        try:
            # Get decomposition plan
            plan = await self._hgnn_decompose(task)

            if not plan:
                # Fallback to random organ execution
                rr = await _apost(self.http, f"{ORG}/execute-on-random",
                                  {"task": root_task_dict}, _corr_headers("organism", cid), timeout=ORG_TIMEOUT)
                latency_ms = (time.time() - start_time) * 1000
                self.metrics.track_metrics("hgnn_fallback", rr.get("success", False), latency_ms)
                return {"success": rr.get("success", False), "result": rr, "path": "hgnn_fallback"}

            root_task_dict = self._convert_task_to_dict(task)
            root_agent_id = None
            if isinstance(getattr(task, "params", None), dict):
                root_agent_id = task.params.get("agent_id")

            # Inject computed drift_score and energy budgets for root task
            root_task_dict["drift_score"] = await self._compute_drift_score(root_task_dict)
            
            # Ensure params has token/energy settings if present in predicates
            if "params" not in root_task_dict:
                root_task_dict["params"] = {}
            
            # Add energy budget information if available
            if hasattr(self, 'predicate_router') and self.predicate_router:
                energy_budget = getattr(self.predicate_router, 'get_energy_budget', lambda: None)()
                if energy_budget is not None:
                    root_task_dict["params"]["energy_budget"] = energy_budget

            root_db_id: Optional[uuid.UUID] = None
            repo = self._get_graph_repository()
            if repo is not None and hasattr(repo, "create_task"):
                try:
                    root_db_id = await repo.create_task(
                        root_task_dict,
                        agent_id=root_agent_id,
                    )
                except Exception as e:
                    logger.warning(
                        "[Coordinator] Failed to persist root HGNN task %s: %s",
                        root_task_dict.get("id"),
                        e,
                    )
                    root_db_id = None
            else:
                logger.debug(
                    "[Coordinator] graph_task_repo not configured; skipping root task persistence"
                )

            try:
                await self._persist_plan_subtasks(task, plan, root_db_id=root_db_id)
            except Exception as persist_exc:
                logger.warning(
                    "[Coordinator] Failed to persist HGNN subtasks for task %s: %s",
                    getattr(task, "id", "unknown"),
                    persist_exc,
                )


            # Execute steps sequentially
            results = []
            for idx, step in enumerate(plan):
                organ_id = step.get("organ_id")
                raw_subtask = step.get("task")
                if isinstance(raw_subtask, dict):
                    subtask_payload = raw_subtask
                else:
                    subtask_payload = dict(self._convert_task_to_dict(task))

                _, subtask_dict = self._normalize_task_dict(subtask_payload)
                step["task"] = subtask_dict

                sub_agent_id = self._extract_agent_id(subtask_dict) or root_agent_id

                # Inject computed drift_score and energy budgets for subtask
                subtask_dict["drift_score"] = await self._compute_drift_score(subtask_dict)
                
                # Ensure params has token/energy settings if present in predicates
                if "params" not in subtask_dict:
                    subtask_dict["params"] = {}
                
                # Add energy budget information if available
                if hasattr(self, 'predicate_router') and self.predicate_router:
                    energy_budget = getattr(self.predicate_router, 'get_energy_budget', lambda: None)()
                    if energy_budget is not None:
                        subtask_dict["params"]["energy_budget"] = energy_budget

                try:
                    child_db_id = await self.graph_task_repo.create_task(
                        subtask_dict,
                        agent_id=sub_agent_id,
                        organ_id=organ_id,
                    )
                    if root_db_id:
                        await self.graph_task_repo.add_dependency(root_db_id, child_db_id)
                except Exception as e:
                    logger.warning(
                        f"[Coordinator] Failed to persist HGNN subtask {subtask_dict.get('id')} (step {idx + 1}): {e}"
                    )

                r = await _apost(self.http, f"{ORG}/execute-on-organ",
                                 {"organ_id": organ_id, "task": subtask_dict},
                                 _corr_headers("organism", cid), timeout=ORG_TIMEOUT)
                results.append({"organ_id": organ_id, **r})
            
            success = all(x.get("success") for x in results)
            latency_ms = (time.time() - start_time) * 1000
            self.metrics.track_metrics("hgnn", success, latency_ms)
            
            return self._make_escalation_result(results, plan, success)
            
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            self.metrics.track_metrics("escalation_failure", False, latency_ms)
            logger.error(f"[Coordinator] HGNN execution failed: {e}")
            return {"success": False, "error": str(e), "path": "hgnn"}

    @app.post(f"{router_prefix}/route-and-execute")
    async def route_and_execute(self, task):
        """
        Global entrypoint (paper §6): Predicate-based routing + HGNN escalation.
        """
        # Ensure background tasks are started
        await self._ensure_background_tasks_started()
        
        cid = uuid.uuid4().hex
        start_time = time.time()
        
        try:
            # Log received task for debugging
            logger.info(f"[Coordinator] Received task request: {task}")
            logger.info(f"[Coordinator] Task object type: {type(task)}")
            
            # Validate task object
            if task is None:
                logger.error(f"[Coordinator] Task object is None")
                raise HTTPException(status_code=400, detail="Task object is required")
            
            # Handle both Task and TaskPayload objects
            if hasattr(task, 'type'):
                # Task or TaskPayload object
                if task.type is None:
                    logger.error(f"[Coordinator] Task type is None. Task: {task}")
                    raise HTTPException(status_code=400, detail="Task type is required")
                task_type = (task.type or "").strip().lower()
            elif isinstance(task, dict) and 'type' in task:
                # Dictionary with type field
                task_type = (task.get('type') or "").strip().lower()
            else:
                logger.error(f"[Coordinator] Task type is missing. Task: {task}")
                raise HTTPException(status_code=400, detail="Task type is required")
            
            # Normalize task type
            if hasattr(task, 'type'):
                task.type = task_type
            elif isinstance(task, dict):
                task['type'] = task_type
                
        except AttributeError as e:
            logger.error(f"[Coordinator] AttributeError in route_and_execute: {e}")
            logger.error(f"[Coordinator] Task object type: {type(task)}")
            logger.error(f"[Coordinator] Task object attributes: {dir(task) if hasattr(task, '__dict__') else 'No __dict__'}")
            raise HTTPException(status_code=400, detail=f"Invalid task object: {str(e)}")
        except Exception as e:
            logger.error(f"[Coordinator] Unexpected error in route_and_execute: {e}")
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

        # Prefetch context if available
        if hasattr(task, 'model_dump'):
            self.prefetch_context(task.model_dump())
        elif hasattr(task, 'dict'):
            self.prefetch_context(task.dict())
        elif isinstance(task, dict):
            self.prefetch_context(task)
        else:
            logger.warning(f"[Coordinator] Cannot convert task to dict for prefetch_context: {type(task)}")

        # Compute drift score using ML service
        task_dict = self._convert_task_to_dict(task)
        drift_score = await self._compute_drift_score(task_dict)
        escalate = self.ocps.update(drift_score)
        
        # Update predicate signals
        task_params = getattr(task, 'params', {}) if hasattr(task, 'params') else task.get('params', {}) if isinstance(task, dict) else {}
        
        # Convert string priority to integer
        priority = task_params.get("priority", 5)
        if isinstance(priority, str):
            priority_map = {"low": 2, "medium": 5, "high": 8, "critical": 10}
            priority = priority_map.get(priority.lower(), 5)
        elif not isinstance(priority, int):
            priority = 5  # Default fallback
        
        # Add missing signals for predicate evaluation
        self.predicate_router.update_signals(
            p_fast=self.ocps.p_fast,
            s_drift=drift_score,
            task_priority=priority,
            task_complexity=task_params.get("complexity", 0.5),
            memory_utilization=0.5,  # TODO: Get from system metrics
            cpu_utilization=0.3,     # TODO: Get from system metrics
            fast_path_latency_ms=50.0,  # TODO: Get from actual metrics
            hgnn_latency_ms=200.0,      # TODO: Get from actual metrics
            success_rate=0.95,          # TODO: Get from actual metrics
        )

        # Use predicate-based routing
        routing_decision = self.predicate_router.route_task(task_dict)
        
        # Execute based on routing decision
        if routing_decision.action == "fast_path" and routing_decision.organ_id:
            try:
                resp = await self._execute_fast(task, routing_decision.organ_id, cid)
                latency_ms = (time.time() - start_time) * 1000
                self.metrics.track_metrics("fast", resp.get("success", False), latency_ms)
                record_request("fast", resp.get("success", False))
                record_latency("e2e", latency_ms)
                return {
                    "success": resp.get("success", False), "result": resp,
                    "path": "fast", "p_fast": self.ocps.p_fast, "organ_id": routing_decision.organ_id, 
                    "correlation_id": cid, "routing_reason": routing_decision.reason
                }
            except Exception as e:
                logger.warning(f"Fast path failed; escalating. err={e}")

        # Escalation with concurrency control
        if self._inflight_escalations >= self.escalation_max_inflight:
            latency_ms = (time.time() - start_time) * 1000
            self.metrics.track_metrics("escalation_failure", False, latency_ms)
            record_request("escalation_failure", False)
            record_latency("e2e", latency_ms)
            return {"success": False, "error": "Too many concurrent escalations", "path": "escalation_failure", "p_fast": self.ocps.p_fast, "correlation_id": cid}

        async with self.escalation_semaphore:
            self._inflight_escalations += 1
            try:
                resp = await self._execute_hgnn(task, cid)
                resp.update({
                    "p_fast": self.ocps.p_fast, 
                    "correlation_id": cid,
                    "routing_reason": routing_decision.reason
                })
                record_request("hgnn", resp.get("success", False))
                record_latency("e2e", (time.time() - start_time) * 1000)
                return resp
            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                self.metrics.track_metrics("escalation_failure", False, latency_ms)
                record_request("escalation_failure", False)
                record_latency("e2e", latency_ms)
                return {"success": False, "error": str(e), "path": "hgnn", "p_fast": self.ocps.p_fast, "correlation_id": cid}
            finally:
                self._inflight_escalations -= 1

    @app.get(f"{router_prefix}/metrics")
    async def get_metrics(self):
        """Get current task execution metrics."""
        # Ensure background tasks are started
        await self._ensure_background_tasks_started()
        return self.metrics.get_metrics()
    
    @app.get(f"{router_prefix}/predicates/status")
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
    
    @app.get(f"{router_prefix}/predicates/config")
    async def get_predicate_config(self):
        """Get current predicate configuration."""
        return self.predicate_config.dict()
    
    @app.post(f"{router_prefix}/predicates/reload")
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
    
    @app.post(f"{router_prefix}/ml/tune/callback")
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

    # Enhanced anomaly triage pipeline matching the sequence diagram
    @app.post(f"{router_prefix}/anomaly-triage", response_model=AnomalyTriageResponse)
    async def anomaly_triage(self, payload: AnomalyTriageRequest):
        """
        Anomaly triage pipeline that follows the sequence diagram:
        1. Detect anomalies via ML service
        2. Reason about failure via Cognitive service  
        3. Make decision via Cognitive service
        4. Conditionally submit tune/retrain job if action requires it
        5. Best-effort memory synthesis
        6. Return aggregated response
        """
        cid = uuid.uuid4().hex
        agent_id = payload.agent_id
        series = payload.series
        context = payload.context
        
        # Compute drift score using ML service
        task_data = {
            "id": f"anomaly_triage_{agent_id}",
            "type": "anomaly_triage",
            "description": f"Anomaly triage for agent {agent_id}",
            "priority": 7,
            "complexity": 0.8,
            "series_length": len(series),
            "context": context
        }
        drift_score = await self._compute_drift_score(task_data)
        escalate = self.ocps.update(drift_score)
        
        logger.info(f"[Coordinator] Anomaly triage started for agent {agent_id}, drift={drift_score}, escalate={escalate}, cid={cid}")

        # 1. Detect anomalies via ML service
        anomalies = await self.ml_client.post("/detect/anomaly", 
                                             json={"data": series}, 
                                             headers=_corr_headers("ml_service", cid))

        # 2. Reason about failure (only if escalating or no OCPS gating)
        reason = {}
        decision = {"result": {"action": "hold"}}
        
        if escalate or not hasattr(self, 'ocps'):  # Always reason if no OCPS or escalating
            try:
                reason = await self.cognitive_client.post("/reason-about-failure",
                                                         json={"incident_context": {"anomalies": anomalies.get("anomalies", []), "meta": context}},
                                                         headers=_corr_headers("cognitive", cid))
            except Exception as e:
                logger.warning(f"[Coordinator] Reasoning failed: {e}")
                reason = {"result": {"thought": "cognitive error", "proposed_solution": "retry"}, "error": str(e)}

            # 3. Make decision
            try:
                decision = await self.cognitive_client.post("/make-decision",
                                                           json={"decision_context": {"anomaly_count": len(anomalies.get("anomalies", [])),
                                                                                     "reason": reason.get("result", {})}},
                                                           headers=_corr_headers("cognitive", cid))
            except Exception as e:
                logger.warning(f"[Coordinator] Decision making failed: {e}")
                decision = {"result": {"action": "hold"}, "error": str(e)}
        else:
            logger.info(f"[Coordinator] Skipping cognitive calls due to OCPS gating (low drift)")

        # 4. Conditional tune/retrain based on predicate evaluation
        tuning_job = None
        action = (decision.get("result") or {}).get("action", "hold")
        
        # Use predicate system to evaluate mutation decision
        mutation_decision = self.predicate_router.evaluate_mutation(
            task={"type": "anomaly_triage", "domain": "anomaly", "priority": 7, "complexity": 0.8},
            decision=decision.get("result", {})
        )
        
        if mutation_decision.action in ["submit_tuning", "submit_retrain"]:
            try:
                # Get current energy state for E_before
                current_energy = self._get_current_energy_state(agent_id)
                
                tuning_job = await self.ml_client.post("/xgboost/tune/submit",
                                                       json={"space_type": TUNE_SPACE_TYPE,
                                                             "config_type": TUNE_CONFIG_TYPE,
                                                             "experiment_name": f"{TUNE_EXPERIMENT_PREFIX}-{agent_id}-{cid}",
                                                             "callback_url": f"{SEEDCORE_API_URL}/pipeline/ml/tune/callback"},
                                                       headers=_corr_headers("ml_service", cid))
                
                # Persist E_before for later ΔE calculation
                if tuning_job.get("job_id") and current_energy is not None:
                    self._persist_job_state(tuning_job["job_id"], {
                        "E_before": current_energy,
                        "agent_id": agent_id,
                        "submitted_at": time.time(),
                        "job_type": mutation_decision.action.replace("submit_", "")
                    })
                    self.predicate_router.update_gpu_job_status(tuning_job["job_id"], "started")
                
                logger.info(f"[Coordinator] Tuning job submitted: {tuning_job.get('job_id', 'unknown')} (reason: {mutation_decision.reason})")
            except Exception as e:
                logger.warning(f"[Coordinator] Tuning submission failed: {e}")
                tuning_job = {"error": str(e)}
        else:
            logger.info(f"[Coordinator] Mutation decision: {mutation_decision.action} (reason: {mutation_decision.reason})")

        # 5. Best-effort memory synthesis (fire-and-forget)
        asyncio.create_task(self._fire_and_forget_memory_synthesis(
            agent_id, anomalies, reason, decision, cid
        ))

        # 6. Build response
        response = AnomalyTriageResponse(
            agent_id=agent_id,
            anomalies=anomalies,
            reason=reason,
            decision=decision,
            correlation_id=cid,
            p_fast=self.ocps.p_fast,
            escalated=escalate,
            tuning_job=tuning_job
        )
            
        logger.info(f"[Coordinator] Anomaly triage completed for agent {agent_id}, action={action}, cid={cid}")
        return response

# Bind the deployment
coordinator_deployment = Coordinator.bind()

