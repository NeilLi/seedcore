# coordinator_service.py
import os, time, uuid, httpx, asyncio
from fastapi import FastAPI, HTTPException
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse
from ray import serve
from pydantic import BaseModel, Field
import logging

# Import predicate system
from ..predicates import PredicateRouter, load_predicates, get_metrics
from ..predicates.metrics import update_ocps_signals, update_energy_signals, record_request, record_latency
from ..predicates.circuit_breaker import ServiceClient, CircuitBreaker, RetryConfig
from ..predicates.safe_storage import SafeStorage
import redis
import json

logger = logging.getLogger("seedcore.coordinator")

# ---------- Config ----------
ORCH_TIMEOUT = float(os.getenv("ORCH_HTTP_TIMEOUT", "10"))
ML_TIMEOUT = float(os.getenv("ML_SERVICE_TIMEOUT", "8"))
COG_TIMEOUT = float(os.getenv("COGNITIVE_SERVICE_TIMEOUT", "15"))
ORG_TIMEOUT = float(os.getenv("ORGANISM_SERVICE_TIMEOUT", "5"))

SEEDCORE_API_URL = os.getenv("SEEDCORE_API_URL", "http://seedcore-api:8002")
SEEDCORE_API_TIMEOUT = float(os.getenv("SEEDCORE_API_TIMEOUT", "5.0"))

SERVE_GATEWAY = os.getenv("SERVE_GATEWAY", "http://seedcore-svc-stable-svc:8000")
ML = f"{SERVE_GATEWAY}/ml"
COG = f"{SERVE_GATEWAY}/cognitive"
ORG = f"{SERVE_GATEWAY}/organism"

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
    def __init__(self, nu: float = 0.1, h: float = None):
        # h is your drift threshold (env OCPS_DRIFT_THRESHOLD)
        self.nu = nu
        self.h = float(os.getenv("OCPS_DRIFT_THRESHOLD", "0.5")) if h is None else h
        self.S = 0.0
        self.fast_hits = 0
        self.esc_hits = 0

    def update(self, drift: float) -> bool:
        self.S = max(0.0, self.S + drift - self.nu)
        esc = self.S > self.h
        if esc:
            self.esc_hits += 1
            self.S = 0.0
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
    drift_score: float = 0.0
    features: Dict[str, Any] = {}
    history_ids: List[str] = []
    # … add fields as needed

class AnomalyTriageRequest(BaseModel):
    agent_id: str
    series: List[float] = []
    context: Dict[str, Any] = {}
    drift_score: float = 0.0

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
            "ml_service", ML, timeout=float(os.getenv("CB_ML_TIMEOUT_S", "2.0")),
            circuit_breaker=CircuitBreaker(
                failure_threshold=int(os.getenv("CB_FAIL_THRESHOLD", "5")),
                recovery_timeout=float(os.getenv("CB_RESET_S", "30.0"))
            ),
            retry_config=RetryConfig(max_attempts=1, base_delay=1.0, max_delay=2.0)
        )
        
        self.cognitive_client = ServiceClient(
            "cognitive_service", COG, timeout=float(os.getenv("CB_COG_TIMEOUT_S", "4.0")),
            circuit_breaker=CircuitBreaker(
                failure_threshold=int(os.getenv("CB_FAIL_THRESHOLD", "5")),
                recovery_timeout=float(os.getenv("CB_RESET_S", "30.0"))
            ),
            retry_config=RetryConfig(max_attempts=0, base_delay=0.0)  # No retries for cognitive
        )
        
        self.organism_client = ServiceClient(
            "organism_service", ORG, timeout=float(os.getenv("CB_ORG_TIMEOUT_S", "5.0")),
            circuit_breaker=CircuitBreaker(
                failure_threshold=int(os.getenv("CB_FAIL_THRESHOLD", "5")),
                recovery_timeout=float(os.getenv("CB_RESET_S", "30.0"))
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
        
        # Initialize safe storage (Redis with in-memory fallback)
        try:
            redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            self.storage = SafeStorage(redis_client)
            logger.info(f"✅ Storage initialized: {self.storage.get_backend_type()}")
        except Exception as e:
            logger.warning(f"⚠️ Redis connection failed, using in-memory storage: {e}")
            self.storage = SafeStorage(None)
        
        # Initialize predicate system
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
        
        # sensible defaults (avoid cognitive for simple)
        self.routing.set_rule("general_query", "utility_organ_1")
        self.routing.set_rule("health_check", "utility_organ_1")
        self.routing.set_rule("execute", "actuator_organ_1")
        
        # Escalation concurrency control
        self.escalation_max_inflight = COGNITIVE_MAX_INFLIGHT
        self.escalation_semaphore = asyncio.Semaphore(5)
        self._inflight_escalations = 0
        
        # Configuration
        self.fast_path_latency_slo_ms = FAST_PATH_LATENCY_SLO_MS
        self.max_plan_steps = MAX_PLAN_STEPS
        
        # Start background tasks
        asyncio.create_task(self._start_background_tasks())

    async def _start_background_tasks(self):
        """Start background maintenance tasks."""
        try:
            await self.predicate_router.start_background_tasks()
            logger.info("🚀 Started Coordinator background tasks")
        except Exception as e:
            logger.error(f"❌ Failed to start background tasks: {e}")

    def _get_current_energy_state(self, agent_id: str) -> Optional[float]:
        """Get current energy state for an agent."""
        try:
            # This would typically call the energy service or get from agent state
            # For now, return a placeholder value
            return 0.5  # TODO: Implement actual energy state retrieval
        except Exception as e:
            logger.warning(f"Failed to get energy state for agent {agent_id}: {e}")
            return None
    
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
                    "drift_score": task.drift_score, 
                    "features": task.features, 
                    "history_ids": task.history_ids
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
            
            validated_plan = self._validate_or_fallback(steps, task.model_dump())
            
            if validated_plan:
                logger.info(f"[Coordinator] HGNN decomposition successful: {len(validated_plan)} steps")
                return validated_plan
            else:
                logger.warning(f"[Coordinator] HGNN plan validation failed, using fallback")
                return self._fallback_plan(task.model_dump())
                
        except Exception as e:
            logger.warning(f"[Coordinator] HGNN decomposition failed: {e}, using fallback")
            return self._fallback_plan(task.model_dump())

    def _fallback_plan(self, task: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create a minimal safe fallback plan when cognitive reasoning is unavailable."""
        ttype = (task.get("type") or task.get("task_type") or "").strip().lower()
        
        # Try to find an organ that supports this task type
        organ_id = self.routing.resolve(ttype, task.get("domain"))
        if organ_id:
            return [{"organ_id": organ_id, "task": task}]
        
        # Fallback: use first available organ (simple round-robin)
        # This would need to be populated from organism status in practice
        return [{"organ_id": "utility_organ_1", "task": task}]

    def _validate_or_fallback(self, plan: List[Dict[str, Any]], task: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """Validate the plan from CognitiveCore and return fallback if invalid."""
        if not isinstance(plan, list) or len(plan) > self.max_plan_steps:
            logger.warning(f"Plan validation failed: invalid format or too many steps ({len(plan) if isinstance(plan, list) else 'not a list'})")
            return None
            
        for step in plan:
            if not isinstance(step, dict):
                logger.warning(f"Plan validation failed: step is not a dict: {step}")
                return None
                
            if "organ_id" not in step or "task" not in step:
                logger.warning(f"Plan validation failed: step missing required fields: {step}")
                return None
                
        return plan

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
        payload = {
            "organ_id": organ_id,
            "task": task.model_dump(),
            "organ_timeout_s": float(task.params.get("organ_timeout_s", 30.0))
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
        
        try:
            # Get decomposition plan
            plan = await self._hgnn_decompose(task)
            
            if not plan:
                # Fallback to random organ execution
                rr = await _apost(self.http, f"{ORG}/execute-on-random",
                                  {"task": task.model_dump()}, _corr_headers("organism", cid), timeout=ORG_TIMEOUT)
                latency_ms = (time.time() - start_time) * 1000
                self.metrics.track_metrics("hgnn_fallback", rr.get("success", False), latency_ms)
                return {"success": rr.get("success", False), "result": rr, "path": "hgnn_fallback"}

            # Execute steps sequentially
            results = []
            for step in plan:
                organ_id = step.get("organ_id")
                subtask = step.get("task", task.model_dump())
                r = await _apost(self.http, f"{ORG}/execute-on-organ",
                                 {"organ_id": organ_id, "task": subtask},
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

        # Update OCPS and signals
        drift_score = getattr(task, 'drift_score', 0.0) if hasattr(task, 'drift_score') else task.get('drift_score', 0.0) if isinstance(task, dict) else 0.0
        escalate = self.ocps.update(drift_score)
        
        # Update predicate signals
        task_params = getattr(task, 'params', {}) if hasattr(task, 'params') else task.get('params', {}) if isinstance(task, dict) else {}
        self.predicate_router.update_signals(
            p_fast=self.ocps.p_fast,
            s_drift=drift_score,
            task_priority=task_params.get("priority", 5),
            task_complexity=task_params.get("complexity", 0.5),
            memory_utilization=0.5,  # TODO: Get from system metrics
            cpu_utilization=0.3,     # TODO: Get from system metrics
        )

        # Use predicate-based routing
        task_dict = task.model_dump() if hasattr(task, 'model_dump') else task.dict() if hasattr(task, 'dict') else task if isinstance(task, dict) else {}
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
        
        # Extract drift score for OCPS gating (optional)
        drift_score = payload.drift_score
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

