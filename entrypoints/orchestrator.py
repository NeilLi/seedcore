import os, time, uuid, requests
import httpx
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, BackgroundTasks
from ray import serve
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

ORCHESTRATOR_TIMEOUT = float(os.getenv("ORCH_HTTP_TIMEOUT", "10"))

# Configuration for seedcore-api integration
SEEDCORE_API_URL = os.getenv("SEEDCORE_API_URL", "http://seedcore-api:8002")
SEEDCORE_API_TIMEOUT = float(os.getenv("SEEDCORE_API_TIMEOUT", "5.0"))

def _normalize_http(url_or_host: str, default_port: int = 8000) -> str:
    if "://" not in url_or_host:
        return f"http://{url_or_host}:{default_port}"
    # If someone set SERVE_GATEWAY with ray:// by mistake, coerce to http:// on same host:port
    parsed = urlparse(url_or_host)
    scheme = "http" if parsed.scheme in ("ray", "grpc", "grpcs") else parsed.scheme
    netloc = parsed.netloc or parsed.path
    return f"{scheme}://{netloc}"

def _derive_serve_gateway() -> str:
    # 1) Respect explicit SERVE_GATEWAY if provided
    sg = os.getenv("SERVE_GATEWAY")
    if sg:
        return _normalize_http(sg, 8000)

    # 2) Derive from RAY_ADDRESS (preferred for client pods like seedcore-api)
    ra = os.getenv("RAY_ADDRESS")
    if ra:
        # Strip ray:// if present and extract host
        hostport = ra.replace("ray://", "").split("/", 1)[0]
        host = hostport.split(":")[0]
        if host in ("127.0.0.1", "localhost"):
            # inside head pod, Serve proxy is local on 8000
            return "http://127.0.0.1:8000"
        # Map head svc → serve svc (stable service names)
        serve_host = host.replace("-head-svc", "-serve-svc")
        return f"http://{serve_host}:8000"

    # 3) Derive from RAY_HOST if set
    rh = os.getenv("RAY_HOST")
    if rh:
        serve_host = rh.replace("-head-svc", "-serve-svc")
        return f"http://{serve_host}:8000"

    # 4) Last-resort default (your user-managed stable Serve Service)
    return "http://seedcore-svc-stable-svc:8000"

GATEWAY = _derive_serve_gateway()
ML = f"{GATEWAY}/ml"
COG = f"{GATEWAY}/cognitive"

async def _create_task_via_api(task_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    """
    Create a task via seedcore-api HTTP call.
    
    Args:
        task_data: Task creation payload
        correlation_id: Optional correlation ID for tracing
        
    Returns:
        Task creation response from seedcore-api
        
    Raises:
        HTTPException: If task creation fails
    """
    try:
        correlation_id = correlation_id or str(uuid.uuid4())
        task_id = task_data.get('id', str(uuid.uuid4()))
        
        async with httpx.AsyncClient(timeout=SEEDCORE_API_TIMEOUT) as client:
            response = await client.post(
                f"{SEEDCORE_API_URL}/api/v1/tasks",
                json=task_data,
                headers={
                    "Content-Type": "application/json",
                    "X-Service": "orchestrator",
                    "X-Correlation-ID": correlation_id,
                    "X-Task-ID": task_id,
                    "X-Source-Service": "orchestrator",
                    "X-Target-Service": "seedcore-api"
                }
            )
            response.raise_for_status()
            
            # Add correlation info to response
            result = response.json()
            result["_correlation"] = {
                "correlation_id": correlation_id,
                "task_id": task_id,
                "source_service": "orchestrator",
                "target_service": "seedcore-api"
            }
            return result
    except httpx.TimeoutException:
        logger.error(f"Timeout creating task via seedcore-api after {SEEDCORE_API_TIMEOUT}s")
        raise HTTPException(
            status_code=504,
            detail=f"Task creation timeout after {SEEDCORE_API_TIMEOUT}s"
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error creating task via seedcore-api: {e.response.status_code} - {e.response.text}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Task creation failed: {e.response.text}"
        )
    except Exception as e:
        logger.error(f"Unexpected error creating task via seedcore-api: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Task creation failed: {str(e)}"
        )

orch_app = FastAPI()

# Task models
class TaskCreateRequest(BaseModel):
    type: str = Field(..., description="Task type")
    description: str = Field(..., description="Task description")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Task parameters")
    domain: Optional[str] = Field(None, description="Task domain")
    drift_score: Optional[float] = Field(0.0, description="Drift score for OCPS")
    constraints: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Task constraints")
    features: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Task features")
    history_ids: Optional[list] = Field(default_factory=list, description="History IDs for context")

class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: str
    created_at: float

def _post(url, json):
    r = requests.post(url, json=json, timeout=ORCHESTRATOR_TIMEOUT)
    if not r.ok:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()

@serve.deployment(
    name="OpsOrchestrator",
    num_replicas=int(os.getenv("ORCH_REPLICAS", "1")),
    max_ongoing_requests=16,
    ray_actor_options={
        "num_cpus": float(os.getenv("ORCH_NUM_CPUS", "0.2")),
    },
)
@serve.ingress(orch_app)
class OpsOrchestrator:
    """
    Endpoints that stitch /ml and /cognitive into one pipeline.
    """

    @orch_app.post("/pipeline/anomaly-triage")
    def anomaly_triage(self, payload: dict):
        """
        Input:
          {
            "agent_id": "agent-123",
            "series": [ ... metric values ... ],
            "context": { ... optional meta (service, region, model, etc.) ... }
          }
        """
        agent_id = payload.get("agent_id") or "agent-default"
        series = payload.get("series") or []
        context = payload.get("context") or {}

        # 1) Detect anomalies
        anomalies = _post(f"{ML}/detect/anomaly", {"data": series})

        # 2) Explain failure / reason about anomalies
        incident_context = {
            "time": time.time(),
            "series_len": len(series),
            "anomalies": anomalies.get("anomalies", []),
            "meta": context,
        }
        reason = _post(f"{COG}/reason-about-failure", {
            "agent_id": agent_id,
            "incident_context": incident_context
        })

        # 3) Decide next action
        decision = _post(f"{COG}/make-decision", {
            "agent_id": agent_id,
            "decision_context": {
                "anomaly_count": len(incident_context["anomalies"]),
                "severity_counts": {
                    "high": sum(a.get("severity") == "high" for a in incident_context["anomalies"])
                },
                "meta": context
            },
            "historical_data": {}
        })
        action = (decision.get("result") or {}).get("action", "hold")

        out = {
            "agent_id": agent_id,
            "anomalies": anomalies,
            "reason": reason,
            "decision": decision,
        }

        # 4) If tuning is recommended, submit a job & return job_id
        if action in ("tune", "retrain", "retune"):
            job_req = {
                # minimal defaults; pass through context knobs as needed
                "space_type": "basic",
                "config_type": "fast",
                "experiment_name": f"tune-{agent_id}-{uuid.uuid4().hex[:6]}",
            }
            job = _post(f"{ML}/xgboost/tune/submit", job_req)
            out["tuning_job"] = job  # {"status": "submitted", "job_id": ...}

        # 5) If promotion is recommended, call promote with decision-provided deltas
        if action == "promote":
            # Expect your decision policy to compute an energy delta (ΔE).
            delta_E = float((decision.get("result") or {}).get("delta_E", 0.0))
            candidate_uri = (decision.get("result") or {}).get("candidate_uri")
            if candidate_uri:
                promote = _post(f"{ML}/xgboost/promote", {
                    "candidate_uri": candidate_uri,
                    "delta_E": delta_E,
                    # optional observability fields:
                    "latency_ms": context.get("latency_ms"),
                    "beta_mem_new": context.get("beta_mem_new"),
                })
                out["promotion"] = promote

        # 6) Synthesize memory (optional; non-blocking)
        try:
            _post(f"{COG}/synthesize-memory", {
                "agent_id": agent_id,
                "memory_fragments": [
                    {"anomalies": anomalies.get("anomalies", [])},
                    {"reason": reason.get("result")},
                    {"decision": decision.get("result")}
                ],
                "synthesis_goal": "incident_triage_summary"
            })
        except Exception:
            pass  # memory synthesis is best-effort

        return out

    @orch_app.get("/pipeline/tune/status/{job_id}")
    def tune_status(self, job_id: str):
        return requests.get(f"{ML}/xgboost/tune/status/{job_id}", timeout=ORCHESTRATOR_TIMEOUT).json()

    @orch_app.post("/tasks", response_model=TaskResponse)
    async def create_task_deprecated(self, request: TaskCreateRequest, background_tasks: BackgroundTasks):
        """
        DEPRECATED: Task creation has moved to seedcore-api.
        
        This endpoint returns 410 Gone and redirects to the proper service.
        All task creation should now go through seedcore-api at /api/v1/tasks.
        """
        logger.warning(f"DEPRECATED: Task creation attempted on orchestrator. Redirecting to seedcore-api.")
        
        # Return 410 Gone with redirect information
        raise HTTPException(
            status_code=410,
            detail={
                "error": "Task creation endpoint has been moved",
                "message": "All task creation now goes through seedcore-api",
                "new_endpoint": "/api/v1/tasks",
                "service": "seedcore-api",
                "migration_date": "2024-12-19"
            },
            headers={
                "Location": "/api/v1/tasks",
                "X-Deprecated-Endpoint": "/tasks",
                "X-New-Service": "seedcore-api"
            }
        )

    @orch_app.post("/pipeline/create-task", response_model=TaskResponse)
    async def create_task_via_api(self, request: TaskCreateRequest, background_tasks: BackgroundTasks):
        """
        Create a new task via seedcore-api (proper service boundary).
        
        This endpoint:
        1. Calls seedcore-api to create the task record
        2. Returns the task ID from seedcore-api
        3. Maintains proper service boundaries
        """
        try:
            # Prepare task data for seedcore-api
            task_data = {
                "type": request.type,
                "description": request.description,
                "params": request.params,
                "domain": request.domain,
                "drift_score": request.drift_score,
                "constraints": request.constraints,
                "features": request.features,
                "history_ids": request.history_ids,
                "run_immediately": True  # Enqueue for processing
            }
            
            # Create task via seedcore-api
            api_response = await _create_task_via_api(task_data)
            
            logger.info(f"Created task {api_response.get('id')} via seedcore-api")
            
            return TaskResponse(
                task_id=str(api_response.get('id', '')),
                status=api_response.get('status', 'created'),
                message="Task created via seedcore-api and enqueued for processing",
                created_at=time.time()
            )
            
        except HTTPException:
            # Re-raise HTTP exceptions from _create_task_via_api
            raise
        except Exception as e:
            logger.error(f"Failed to create task via seedcore-api: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # --- Organism Control Endpoints (Ray Control Plane) ---
    
    @orch_app.get("/organism/health")
    async def organism_health(self):
        """Health check for organism service."""
        correlation_id = str(uuid.uuid4())
        try:
            # Call organism service health endpoint with correlation headers
            response = requests.get(
                f"{GATEWAY}/organism/health", 
                timeout=ORCHESTRATOR_TIMEOUT,
                headers={
                    "X-Correlation-ID": correlation_id,
                    "X-Source-Service": "orchestrator",
                    "X-Target-Service": "organism"
                }
            )
            response.raise_for_status()
            result = response.json()
            result["_correlation"] = {
                "correlation_id": correlation_id,
                "source_service": "orchestrator",
                "target_service": "organism"
            }
            return result
        except Exception as e:
            logger.error(f"Failed to get organism health: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "service": "organism",
                "_correlation": {
                    "correlation_id": correlation_id,
                    "source_service": "orchestrator",
                    "target_service": "organism"
                }
            }
    
    @orch_app.get("/organism/status")
    async def organism_status(self):
        """Get organism status."""
        try:
            response = requests.get(f"{GATEWAY}/organism/status", timeout=ORCHESTRATOR_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get organism status: {e}")
            return {
                "status": "error",
                "error": str(e),
                "service": "organism"
            }
    
    @orch_app.post("/organism/initialize")
    async def initialize_organism(self):
        """Initialize organism."""
        try:
            response = requests.post(f"{GATEWAY}/organism/initialize-organism", timeout=ORCHESTRATOR_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to initialize organism: {e}")
            return {
                "success": False,
                "error": str(e),
                "service": "organism"
            }
    
    @orch_app.post("/organism/shutdown")
    async def shutdown_organism(self):
        """Shutdown organism."""
        try:
            response = requests.post(f"{GATEWAY}/organism/shutdown-organism", timeout=ORCHESTRATOR_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to shutdown organism: {e}")
            return {
                "success": False,
                "error": str(e),
                "service": "organism"
            }

    @orch_app.get("/health")
    async def health_check(self):
        """Health check endpoint."""
        return {
            "status": "healthy",
            "service": "orchestrator",
            "timestamp": time.time(),
            "gateway": GATEWAY
        }

    @orch_app.get("/_env")
    async def _env(self):
        """Environment variables endpoint for verification."""
        keys = [
            "SEEDCORE_PG_DSN",
            "OCPS_DRIFT_THRESHOLD",
            "COGNITIVE_TIMEOUT_S",
            "COGNITIVE_MAX_INFLIGHT",
            "FAST_PATH_LATENCY_SLO_MS",
            "MAX_PLAN_STEPS",
        ]
        # mask secrets lightly
        out = {}
        for k in keys:
            v = os.environ.get(k, "")
            if k == "SEEDCORE_PG_DSN" and v:
                out[k] = v.split("@")[-1]  # show only host/db portion
            else:
                out[k] = v
        return out

    
def build_orchestrator(args: dict = None):
    """Builder for the OpsOrchestrator Serve app."""
    # Collect env vars from the *controller* process to inject into replicas
    env_vars = {
        "SEEDCORE_PG_DSN": os.getenv("SEEDCORE_PG_DSN", ""),
        "OCPS_DRIFT_THRESHOLD": os.getenv("OCPS_DRIFT_THRESHOLD", "0.5"),
        "COGNITIVE_TIMEOUT_S": os.getenv("COGNITIVE_TIMEOUT_S", "8.0"),
        "COGNITIVE_MAX_INFLIGHT": os.getenv("COGNITIVE_MAX_INFLIGHT", "64"),
        "FAST_PATH_LATENCY_SLO_MS": os.getenv("FAST_PATH_LATENCY_SLO_MS", "1000"),
        "MAX_PLAN_STEPS": os.getenv("MAX_PLAN_STEPS", "16"),
    }
    # Ensure all values are strings (runtime_env.env_vars requires str)
    env_vars = {k: ("" if v is None else str(v)) for k, v in env_vars.items()}

    return OpsOrchestrator.options(
        # Put runtime_env under ray_actor_options here
        ray_actor_options={
            "runtime_env": {
                "env_vars": env_vars
            }
        }
    ).bind()


