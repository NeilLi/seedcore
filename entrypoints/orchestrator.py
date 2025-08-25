import os, time, uuid, requests
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException
from ray import serve

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

    
def build_orchestrator(args: dict):
    # You can consume args if you want to pass runtime config
    return OpsOrchestrator.bind()

