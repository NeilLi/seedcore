# seedcore_consolidated_client.py
from __future__ import annotations
import os
import json
from typing import Any, Dict, List, Optional, Tuple
import httpx

DEFAULT_DASHBOARD = os.getenv("RAY_DASHBOARD", "http://127.0.0.1:8265")
DEFAULT_GATEWAY   = os.getenv("SEEDCORE_GATEWAY", "http://127.0.0.1:8000")
DEFAULT_API       = os.getenv("SEEDCORE_API_BASE", "http://127.0.0.1:8002")
TIMEOUT_S         = float(os.getenv("SEEDCORE_HTTP_TIMEOUT", "15"))

class HTTP:
    def __init__(self, base: str, timeout: float = TIMEOUT_S):
        self.base = base.rstrip("/")
        self.client = httpx.Client(timeout=timeout)

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return self.base + path

    def get(self, path: str, **kw) -> dict:
        r = self.client.get(self._url(path), **kw)
        _raise_for_json(r)
        return r.json()

    def post(self, path: str, json: Any = None, **kw) -> dict:
        r = self.client.post(self._url(path), json=json, **kw)
        _raise_for_json(r)
        return r.json()

    def close(self):
        self.client.close()

def _raise_for_json(r: httpx.Response):
    if not r.is_success:
        detail = r.text.strip()
        try:
            detail = json.dumps(r.json(), indent=2)
        except Exception:
            pass
        raise RuntimeError(f"{r.request.method} {r.request.url} -> {r.status_code}\n{detail}")

# ---------- Ray Serve Admin (dashboard:8265) ----------
class RayServeAdmin:
    def __init__(self, dashboard: str = DEFAULT_DASHBOARD):
        self.http = HTTP(dashboard)

    def list_applications(self) -> dict:
        # Correct endpoint for modern Ray
        return self.http.get("/api/serve/applications/")

    def route_prefixes(self) -> Dict[str, Dict[str, str]]:
        """
        Returns: { app_name: {"route_prefix": str, "docs_path": str|None} }
        """
        apps = self.list_applications()
        out: Dict[str, Dict[str, str]] = {}
        for name, meta in apps.items():
            rp = (meta or {}).get("route_prefix") or (meta or {}).get("routePrefix") or ""
            docs = (meta or {}).get("docs_path") or (meta or {}).get("docsPath") or ""
            out[name] = {"route_prefix": rp, "docs_path": docs}
        return out

    def close(self):
        self.http.close()

# ---------- ML Serve (gateway:8000) ----------
class MLServeClient:
    def __init__(self, gateway: str, route_prefix: str = "/ml"):
        self.http = HTTP(gateway)
        self.rp = route_prefix.rstrip("/")

    # General ML
    def detect_anomaly(self, series: List[float]) -> dict:
        return self.http.post(f"{self.rp}/detect/anomaly", json={"data": series})

    def score_salience(self, features: List[dict]) -> dict:
        return self.http.post(f"{self.rp}/score/salience", json=features)

    # XGBoost lifecycle
    def tune_submit(self, space_type="basic", config_type="fast", experiment_name="tune-job") -> dict:
        body = {"space_type": space_type, "config_type": config_type, "experiment_name": experiment_name}
        return self.http.post(f"{self.rp}/xgboost/tune/submit", json=body)

    def tune_status(self, job_id: str) -> dict:
        return self.http.get(f"{self.rp}/xgboost/tune/status/{job_id}")

    def promote(self, candidate_uri: str, delta_E: float, **extras) -> dict:
        body = {"candidate_uri": candidate_uri, "delta_E": float(delta_E), **extras}
        return self.http.post(f"{self.rp}/xgboost/promote", json=body)

    def openapi(self) -> dict:
        return self.http.get(f"{self.rp}/openapi.json")

# ---------- Cognitive Serve (gateway:8000) ----------
class CognitiveServeClient:
    def __init__(self, gateway: str, route_prefix: str = "/cognitive"):
        self.http = HTTP(gateway)
        self.rp = route_prefix.rstrip("/")

    def reason_about_failure(self, agent_id: str, incident_context: dict) -> dict:
        body = {"agent_id": agent_id, "incident_context": incident_context}
        return self.http.post(f"{self.rp}/reason-about-failure", json=body)

    def make_decision(self, agent_id: str, decision_context: dict, historical_data: dict | None = None) -> dict:
        body = {"agent_id": agent_id, "decision_context": decision_context, "historical_data": historical_data or {}}
        return self.http.post(f"{self.rp}/make-decision", json=body)

    def plan_task(self, agent_id: str, task_description: str, **kwargs) -> dict:
        body = {"agent_id": agent_id, "task_description": task_description, **kwargs}
        return self.http.post(f"{self.rp}/plan-task", json=body)

    def synthesize_memory(self, agent_id: str, fragments: List[dict], goal: str) -> dict:
        body = {"agent_id": agent_id, "memory_fragments": fragments, "synthesis_goal": goal}
        return self.http.post(f"{self.rp}/synthesize-memory", json=body)

    def openapi(self) -> dict:
        return self.http.get(f"{self.rp}/openapi.json")

# ---------- Orchestrator (optional, gateway:8000) ----------
class OrchestratorClient:
    def __init__(self, gateway: str, route_prefix: str = "/orchestrator"):
        self.http = HTTP(gateway)
        self.rp = route_prefix.rstrip("/")

    def anomaly_triage(self, agent_id: str, series: List[float], context: dict | None = None) -> dict:
        body = {"agent_id": agent_id, "series": series, "context": context or {}}
        return self.http.post(f"{self.rp}/pipeline/anomaly-triage", json=body)

    def tune_status(self, job_id: str) -> dict:
        return self.http.get(f"{self.rp}/pipeline/tune/status/{job_id}")

# ---------- SeedCore API (api:8002) ----------
class SeedcoreAPI:
    def __init__(self, base: str = DEFAULT_API):
        self.http = HTTP(base)

    # quick health / ray
    def health(self) -> dict:      return self.http.get("/health")
    def readyz(self) -> dict:      return self.http.get("/readyz")
    def ray_status(self) -> dict:  return self.http.get("/ray/status")

    # flashbulb incidents (mfb)
    def mfb_log_incident(self, event_data: dict, salience_score: float) -> dict:
        return self.http.post("/mfb/incidents", json=event_data, params={"salience_score": salience_score})

    def mfb_get_incidents(self, **filters) -> dict:
        return self.http.get("/mfb/incidents", params=filters)

    # salience proxy
    def salience_score(self, features: List[dict]) -> dict:
        return self.http.post("/salience/score", json=features)

    # energy (now under /ops)
    def energy_meta(self) -> dict:     return self.http.get("/ops/energy/meta")
    def energy_gradient(self) -> dict: return self.http.get("/ops/energy/gradient")
    def energy_monitor(self) -> dict:  return self.http.get("/ops/energy/monitor")
    def energy_logs(self, limit: int = 100) -> dict:
        return self.http.get("/ops/energy/logs", params={"limit": limit})

    # tier0
    def agents_state(self) -> dict:    return self.http.get("/tier0/agents/state")

    # dspy cognitive proxies (fallback path if Serve unavailable)
    def dspy_reason(self, incident_id: str, agent_id: Optional[str] = None) -> dict:
        return self.http.post("/dspy/reason-about-failure", params={"incident_id": incident_id, "agent_id": agent_id})

    def dspy_make_decision(self, decision_ctx: dict, agent_id: Optional[str] = None, historical: dict | None = None) -> dict:
        body = {"decision_context": decision_ctx, "historical_data": historical or {}}
        return self.http.post("/dspy/make-decision", json=body, params={"agent_id": agent_id})

# ---------- Consolidated facade ----------
class SeedcoreConsolidated:
    """
    One object to discover routes and call everything consistently.
    """
    def __init__(
        self,
        dashboard: str = DEFAULT_DASHBOARD,
        gateway: str   = DEFAULT_GATEWAY,
        api_base: str  = DEFAULT_API,
    ):
        self.dashboard = dashboard
        self.gateway = gateway
        self.api = SeedcoreAPI(api_base)

        # Discover Serve applications & route prefixes
        self.ml_route, self.cog_route, self.orch_route = self._discover_routes()

        # Initialize sub-clients
        self.ml  = MLServeClient(gateway, self.ml_route)
        self.cog = CognitiveServeClient(gateway, self.cog_route) if self.cog_route else None
        self.orch = OrchestratorClient(gateway, self.orch_route) if self.orch_route else None

    def _discover_routes(self) -> Tuple[str, Optional[str], Optional[str]]:
        ml_route = "/ml"              # sensible default
        cog_route = "/cognitive"      # sensible default
        orch_route = None

        try:
            admin = RayServeAdmin(self.dashboard)
            apps = admin.route_prefixes()
            # Try common app names; fall back to first hit of certain heuristics
            for name, meta in apps.items():
                rp = meta.get("route_prefix") or ""
                if not rp:
                    continue
                if name in ("ml_serve", "ml", "ml-service"):
                    ml_route = rp
                elif name in ("cognitive", "cog", "cognitive-service"):
                    cog_route = rp
                elif name in ("orchestrator", "ops_orchestrator", "ops-orchestrator"):
                    orch_route = rp

            admin.close()
        except Exception:
            # Discovery failures are non-fatal; keep defaults
            pass

        return ml_route, cog_route, orch_route

    # -------- High-level pipeline (robust fallbacks) --------
    def pipeline_anomaly_triage(
        self,
        agent_id: str,
        series: List[float],
        context: Optional[dict] = None,
    ) -> dict:
        """
        Preferred path:
          Orchestrator → (ML.detect) → (Cognitive.reason/decide) → optional tune/promote
        Fallback path:
          Direct ML + Cognitive calls (Serve gateway)
        Last resort:
          Direct ML + DSPy proxies on Seedcore API (:8002)
        """
        context = context or {}

        # 1) Orchestrator if present
        if self.orch:
            try:
                return self.orch.anomaly_triage(agent_id, series, context)
            except Exception:
                pass  # fall through

        # 2) Direct Serve calls if CognitiveServe present
        try:
            anomalies = self.ml.detect_anomaly(series)
        except Exception as e:
            anomalies = {"error": f"ML detect_anomaly failed: {e}", "anomalies": []}

        # Try Cognitive on Serve
        reason = {}
        decision = {}
        used_dspy_proxy = False

        incident_context = {
            "time": _now(),
            "series_len": len(series),
            "anomalies": anomalies.get("anomalies", []),
            "meta": context,
        }

        if self.cog:
            try:
                reason = self.cog.reason_about_failure(agent_id, incident_context)
                decision = self.cog.make_decision(
                    agent_id,
                    {
                        "anomaly_count": len(incident_context["anomalies"]),
                        "severity_counts": {
                            "high": sum(a.get("severity") == "high" for a in incident_context["anomalies"])
                        },
                        "meta": context,
                    },
                    {},
                )
            except Exception:
                # fallback to API DSPy proxy
                used_dspy_proxy = True

        if not reason or not decision:
            # 3) Final fallback via Seedcore API proxies (/dspy/*)
            reason = self.api.dspy_reason(incident_id="auto-" + agent_id, agent_id=agent_id)
            decision = self.api.dspy_make_decision(
                {
                    "anomaly_count": len(incident_context["anomalies"]),
                    "severity_counts": {
                        "high": sum(a.get("severity") == "high" for a in incident_context["anomalies"])
                    },
                    "meta": context,
                },
                agent_id=agent_id,
                historical={},
            )
            used_dspy_proxy = True

        out = {
            "agent_id": agent_id,
            "anomalies": anomalies,
            "reason": reason,
            "decision": decision,
            "used_dspy_proxy": used_dspy_proxy,
        }

        # Optionally kick off a tune/promote based on decision
        action = _dig(decision, "result", "action") or _dig(decision, "action") or "hold"
        if action in ("tune", "retrain", "retune"):
            job = self.ml.tune_submit(experiment_name=f"tune-{agent_id}")
            out["tuning_job"] = job
        elif action == "promote":
            cand = _dig(decision, "result", "candidate_uri")
            dE   = float(_dig(decision, "result", "delta_E") or 0.0)
            if cand:
                out["promotion"] = self.ml.promote(cand, dE, **{
                    "latency_ms": context.get("latency_ms"),
                    "beta_mem_new": context.get("beta_mem_new"),
                })

        # Best-effort memory synthesis (Serve cog if available)
        try:
            if self.cog:
                self.cog.synthesize_memory(
                    agent_id,
                    [{"anomalies": anomalies.get("anomalies", [])},
                     {"reason": _dig(reason, "result") or reason},
                     {"decision": _dig(decision, "result") or decision}],
                    "incident_triage_summary",
                )
        except Exception:
            pass

        return out

    # Utilities
    def serve_apps(self) -> dict:
        admin = RayServeAdmin(self.dashboard)
        try:
            return admin.list_applications()
        finally:
            admin.close()

    def ml_openapi(self) -> dict:
        return self.ml.openapi()

    def cognitive_openapi(self) -> dict:
        if not self.cog:
            raise RuntimeError("Cognitive route not discovered")
        return self.cog.openapi()

def _now() -> float:
    import time
    return time.time()

def _dig(d: Any, *path: str) -> Any:
    cur = d
    for p in path:
        if not isinstance(cur, dict): return None
        cur = cur.get(p)
    return cur

# ---------- Example CLI usage ----------
if __name__ == "__main__":
    import argparse, pprint
    pp = pprint.PrettyPrinter(indent=2)

    ap = argparse.ArgumentParser(description="SeedCore Consolidated Client")
    ap.add_argument("--dashboard", default=DEFAULT_DASHBOARD)
    ap.add_argument("--gateway", default=DEFAULT_GATEWAY)
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--cmd", choices=[
        "apps", "ml-openapi", "cog-openapi", "triage", "health"
    ], default="apps")
    ap.add_argument("--agent", default="agent-123")
    ap.add_argument("--series", default="0.2,0.9,0.1,0.95,0.4")
    args = ap.parse_args()

    client = SeedcoreConsolidated(args.dashboard, args.gateway, args.api)

    if args.cmd == "apps":
        pp.pprint(client.serve_apps())
    elif args.cmd == "ml-openapi":
        pp.pprint(client.ml_openapi())
    elif args.cmd == "cog-openapi":
        pp.pprint(client.cognitive_openapi())
    elif args.cmd == "health":
        print("readyz:", client.api.readyz())
        print("ray:", client.api.ray_status())
        print("health:", client.api.health())
    elif args.cmd == "triage":
        series = [float(x) for x in args.series.split(",")]
        pp.pprint(client.pipeline_anomaly_triage(args.agent, series, {"service": "checkout", "region": "us-east"}))

