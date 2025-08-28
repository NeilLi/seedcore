import os, time, uuid, requests
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, BackgroundTasks
from ray import serve
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

ORCHESTRATOR_TIMEOUT = float(os.getenv("ORCH_HTTP_TIMEOUT", "10"))

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
    return "http://seedcore-svc-serve-svc:8000"

GATEWAY = _derive_serve_gateway()
ML = f"{GATEWAY}/ml"
COG = f"{GATEWAY}/cognitive"

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

@serve.deployment(num_replicas=1, ray_actor_options={"num_cpus": 0.2})
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
    async def create_task(self, request: TaskCreateRequest, background_tasks: BackgroundTasks):
        """
        Create a new task and enqueue it for processing.
        
        This endpoint:
        1. Creates a task record
        2. Enqueues it for processing by dispatchers
        3. Returns immediately with task ID
        """
        try:
            task_id = str(uuid.uuid4())
            created_at = time.time()
            
            # Create task payload for dispatchers
            task_payload = {
                "id": task_id,
                "type": request.type,
                "description": request.description,
                "params": request.params,
                "domain": request.domain,
                "drift_score": request.drift_score,
                "constraints": request.constraints,
                "features": request.features,
                "history_ids": request.history_ids,
                "correlation_id": str(uuid.uuid4()),
                "created_at": created_at
            }
            
            # In a real implementation, you would:
            # 1. Store the task in a database
            # 2. Enqueue it for processing by dispatchers
            # 3. Return the task ID immediately
            
            # For now, we'll simulate this by returning the task ID
            # TODO: Integrate with actual database and dispatcher queue
            
            logger.info(f"Created task {task_id} of type {request.type}")
            
            return TaskResponse(
                task_id=task_id,
                status="created",
                message="Task created and enqueued for processing",
                created_at=created_at
            )
            
        except Exception as e:
            logger.error(f"Failed to create task: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @orch_app.get("/health")
    async def health_check(self):
        """Health check endpoint."""
        return {
            "status": "healthy",
            "service": "orchestrator",
            "timestamp": time.time(),
            "gateway": GATEWAY
        }

    
def build_orchestrator(args: dict):
    # You can consume args if you want to pass runtime config
    return OpsOrchestrator.bind()

