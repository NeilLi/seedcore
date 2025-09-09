# coordinator_service.py
import os, time, uuid, httpx, asyncio
from fastapi import FastAPI, HTTPException
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse
from ray import serve
from pydantic import BaseModel, Field
import logging

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
        self.http = httpx.AsyncClient(
            timeout=ORCH_TIMEOUT,
            limits=httpx.Limits(max_keepalive_connections=100, max_connections=200),
        )
        self.ocps = OCPSValve()
        self.routing = RoutingDirectory()
        self.metrics = MetricsTracker()
        
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
    async def route_and_execute(self, task: Task):
        """
        Global entrypoint (paper §6): OCPS fast router + HGNN escalation.
        """
        cid = uuid.uuid4().hex
        start_time = time.time()
        
        # normalize
        task.type = (task.type or "").strip().lower()

        # Prefetch context if available
        self.prefetch_context(task.model_dump())

        # Resolve fast-path organ
        organ_id = self.routing.resolve(task.type, task.domain)
        escalate = self.ocps.update(task.drift_score)

        if organ_id and not escalate:
            try:
                resp = await self._execute_fast(task, organ_id, cid)
                latency_ms = (time.time() - start_time) * 1000
                self.metrics.track_metrics("fast", resp.get("success", False), latency_ms)
                return {
                    "success": resp.get("success", False), "result": resp,
                    "path": "fast", "p_fast": self.ocps.p_fast, "organ_id": organ_id, "correlation_id": cid
                }
            except Exception as e:
                logger.warning(f"Fast path failed; escalating. err={e}")

        # Escalation with concurrency control
        if self._inflight_escalations >= self.escalation_max_inflight:
            latency_ms = (time.time() - start_time) * 1000
            self.metrics.track_metrics("escalation_failure", False, latency_ms)
            return {"success": False, "error": "Too many concurrent escalations", "path": "escalation_failure", "p_fast": self.ocps.p_fast, "correlation_id": cid}

        async with self.escalation_semaphore:
            self._inflight_escalations += 1
            try:
                resp = await self._execute_hgnn(task, cid)
                resp.update({"p_fast": self.ocps.p_fast, "correlation_id": cid})
                return resp
            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                self.metrics.track_metrics("escalation_failure", False, latency_ms)
                return {"success": False, "error": str(e), "path": "hgnn", "p_fast": self.ocps.p_fast, "correlation_id": cid}
            finally:
                self._inflight_escalations -= 1

    @app.get(f"{router_prefix}/metrics")
    async def get_metrics(self):
        """Get current task execution metrics."""
        return self.metrics.get_metrics()

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
        anomalies = await _apost(self.http, f"{ML}/detect/anomaly",
                                 {"data": series}, _corr_headers("ml_service", cid), timeout=ML_TIMEOUT)

        # 2. Reason about failure (only if escalating or no OCPS gating)
        reason = {}
        decision = {"result": {"action": "hold"}}
        
        if escalate or not hasattr(self, 'ocps'):  # Always reason if no OCPS or escalating
            try:
                reason = await _apost(self.http, f"{COG}/reason-about-failure",
                                      {"incident_context": {"anomalies": anomalies.get("anomalies", []), "meta": context}},
                                      _corr_headers("cognitive", cid), timeout=COG_TIMEOUT)
            except Exception as e:
                logger.warning(f"[Coordinator] Reasoning failed: {e}")
                reason = {"result": {"thought": "cognitive error", "proposed_solution": "retry"}, "error": str(e)}

            # 3. Make decision
            try:
                decision = await _apost(self.http, f"{COG}/make-decision",
                                        {"decision_context": {"anomaly_count": len(anomalies.get("anomalies", [])),
                                                              "reason": reason.get("result", {})}},
                                        _corr_headers("cognitive", cid), timeout=COG_TIMEOUT)
            except Exception as e:
                logger.warning(f"[Coordinator] Decision making failed: {e}")
                decision = {"result": {"action": "hold"}, "error": str(e)}
        else:
            logger.info(f"[Coordinator] Skipping cognitive calls due to OCPS gating (low drift)")

        # 4. Conditional tune/retrain based on decision
        tuning_job = None
        action = (decision.get("result") or {}).get("action", "hold")
        
        if action in ["tune", "retrain"]:
            try:
                tuning_job = await _apost(self.http, f"{ML}/xgboost/tune/submit",
                                          {"space_type": TUNE_SPACE_TYPE,
                                           "config_type": TUNE_CONFIG_TYPE,
                                           "experiment_name": f"{TUNE_EXPERIMENT_PREFIX}-{agent_id}-{cid}"},
                                          _corr_headers("ml_service", cid), timeout=ML_TIMEOUT)
                logger.info(f"[Coordinator] Tuning job submitted: {tuning_job.get('job_id', 'unknown')}")
            except Exception as e:
                logger.warning(f"[Coordinator] Tuning submission failed: {e}")
                tuning_job = {"error": str(e)}

        # 5. Best-effort memory synthesis (fire-and-forget)
        try:
            await _apost(self.http, f"{COG}/synthesize-memory",
                         {"agent_id": agent_id,
                          "memory_fragments": [
                              {"anomalies": anomalies.get("anomalies", [])},
                              {"reason": reason.get("result") or reason},
                              {"decision": decision.get("result") or decision}
                          ],
                          "synthesis_goal": "incident_triage_summary"},
                         _corr_headers("cognitive", cid), timeout=COG_TIMEOUT)
            logger.debug(f"[Coordinator] Memory synthesis completed for agent {agent_id}")
        except Exception as e:
            logger.debug(f"[Coordinator] Memory synthesis failed (best-effort): {e}")

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

