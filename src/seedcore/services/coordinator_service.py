# coordinator_service.py
import os, time, uuid, httpx, asyncio, random, inspect
import math
from fastapi import FastAPI, HTTPException
from typing import Dict, Any, List, Optional, Iterable, Set, Tuple, NamedTuple, Sequence, Callable, Awaitable, Mapping, TYPE_CHECKING
from urllib.parse import urlparse
from pathlib import Path
from ray import serve
from pydantic import BaseModel, Field, field_validator
import logging

try:  # Optional dependency - repository may not exist in all deployments
    from ..graph.task_metadata_repository import TaskMetadataRepository  # type: ignore
except ImportError:  # pragma: no cover - keep coordinator resilient when module missing
    TaskMetadataRepository = None  # type: ignore

# Import predicate system
from ..predicates import PredicateRouter, load_predicates, load_predicates_async, get_metrics
from ..predicates.metrics import update_ocps_signals, update_energy_signals, record_request, record_latency
from ..predicates.circuit_breaker import CircuitBreaker, RetryConfig
from ..serve.ml_client import MLServiceClient
from ..serve.cognitive_client import CognitiveServiceClient
from ..serve.organism_client import OrganismServiceClient
from ..predicates.safe_storage import SafeStorage
import redis
import json
from sqlalchemy import text

from seedcore.database import get_async_pg_session_factory
from seedcore.ops.eventizer.fact_dao import FactDAO
from seedcore.ops.eventizer.eventizer_features import (
    features_from_payload as default_features_from_payload,
)
from seedcore.models import TaskPayload, Task
from ..coordinator.dao import TaskRouterTelemetryDAO, TaskOutboxDAO, TaskProtoPlanDAO
from ..coordinator.models import AnomalyTriageRequest, AnomalyTriageResponse, TuneCallbackRequest
from ..coordinator.core.routing import (
    RouteEntry,
    RouteCache,
    resolve_route_cached_async,
    bulk_resolve_routes_cached,
    static_route_fallback,
)
from ..coordinator.core.policies import (
    OCPSValve,
    SurpriseComputer,
    compute_drift_score,
    compute_fallback_drift_score,
    compute_surprise_score,
    decide_route_with_hysteresis,
    generate_proto_subtasks,
    get_current_energy_state,
    create_ocps_valve,
)
from ..coordinator.utils import (
    # Constants
    MAX_STRING_LENGTH,
    DEFAULT_RECURSION_DEPTH,
    # Task normalization and conversion
    normalize_task_dict,
    convert_task_to_dict,
    sync_task_identity,
    # Extraction utilities
    extract_agent_id,
    extract_proto_plan,
    extract_decision,
    extract_from_nested,
    extract_dependency_token,
    # Normalization utilities
    normalize_string,
    normalize_domain,
    canonicalize_identifier,
    # Data processing utilities
    redact_sensitive_data,
    # Dependency management utilities
    iter_dependency_entries,
    resolve_child_task_id,
    collect_record_aliases,
    collect_step_aliases,
    collect_aliases_from_mapping,
    collect_aliases_from_object,
)

from collections.abc import Mapping as _MappingABC

if TYPE_CHECKING:
    from collections.abc import Mapping


# PKG Manager - now uses centralized module
from ..ops.pkg.manager import get_global_pkg_manager

# Metrics tracking - now uses centralized module
from ..ops.metrics import get_global_metrics_tracker





from seedcore.logging_setup import ensure_serve_logger
from seedcore.models.result_schema import (
    create_fast_path_result, create_cognitive_result, create_escalated_result,
    create_error_result, ResultKind
)
from seedcore.graph.task_repository import GraphTaskSqlRepository

logger = ensure_serve_logger("seedcore.coordinator", level="DEBUG")

# ---------- TaskPayload Model (matches dispatcher) ----------
# TaskPayload is now imported from centralized models

# ---------- Result Helpers ----------
def ok_fast(payload: dict) -> dict:
    """Create a fast path result."""
    return create_fast_path_result(
        routed_to=payload.get("routed_to", "coordinator"),
        organ_id=payload.get("organ_id", "coordinator"),
        result=payload
    ).model_dump()

def err(msg: str, error_type: str = "coordinator_error") -> dict:
    """Create an error result."""
    return create_error_result(error=msg, error_type=error_type).model_dump()

def _normalize_result(res: Any) -> dict:
    """Normalize downstream results to unified schema."""
    try:
        # already unified?
        if isinstance(res, dict) and "success" in res and ("payload" in res or "error" in res):
            return res
        # pydantic
        if hasattr(res, "model_dump"):
            return ok_fast(res.model_dump())
        # generic object
        if hasattr(res, "__dict__"):
            return ok_fast(res.__dict__)
        # list-of-steps → escalated
        if isinstance(res, list):
            from seedcore.models.result_schema import TaskStep
            steps = []
            for step in res:
                steps.append(TaskStep(
                    organ_id="coordinator",
                    success=True,
                    metadata=step if isinstance(step, dict) else {"raw": str(step)}
                ))
            return create_escalated_result(solution_steps=steps, plan_source="coordinator_list").model_dump()
        # fallback
        return ok_fast({"result": res})
    except Exception as e:
        return err(f"normalize failed: {e}", "normalize_error")

# ---------- Config ----------
ORCH_TIMEOUT = float(os.getenv("ORCH_HTTP_TIMEOUT", "10"))
ML_TIMEOUT = float(os.getenv("ML_SERVICE_TIMEOUT", "8"))
COG_TIMEOUT = float(os.getenv("COGNITIVE_SERVICE_TIMEOUT", "15"))
ORG_TIMEOUT = float(os.getenv("ORGANISM_SERVICE_TIMEOUT", "5"))

# Serve call timeout for cross-deployment calls
CALL_TIMEOUT_S = int(os.getenv("SERVE_CALL_TIMEOUT_S", "120"))

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
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        if not isinstance(task, TaskPayload):
            task = TaskPayload.model_validate(task)

        tid = task.task_id
        helper = eventizer_helper or default_features_from_payload
        eventizer_data: Dict[str, Any] = {}
        if helper is not None:
            maybe_features = helper(task)
            if inspect.isawaitable(maybe_features):
                maybe_features = await maybe_features
            if isinstance(maybe_features, dict):
                eventizer_data = maybe_features

        params = task.params or {}

        def _coerce_uuid_list(values: Any) -> List[uuid.UUID]:
            if isinstance(values, (str, bytes)) or values is None:
                return []
            if not isinstance(values, Iterable):
                values = [values]
            normalized: List[uuid.UUID] = []
            seen = set()
            for value in values:
                try:
                    item = uuid.UUID(str(value))
                except (TypeError, ValueError):
                    continue
                if item in seen:
                    continue
                seen.add(item)
                normalized.append(item)
            return normalized

        tags: Set[str] = set()
        param_tags = params.get("event_tags") or []
        if isinstance(param_tags, Iterable) and not isinstance(param_tags, (str, bytes)):
            tags.update(str(tag) for tag in param_tags)
        eventizer_tags: Dict[str, Any] = {}
        if isinstance(eventizer_data.get("event_tags"), dict):
            eventizer_tags = eventizer_data["event_tags"]
            eventizer_types = eventizer_tags.get("event_types")
            if isinstance(eventizer_types, Iterable) and not isinstance(eventizer_types, (str, bytes)):
                tags.update(str(tag) for tag in eventizer_types)
            evt_domain = eventizer_tags.get("domain")
            if evt_domain and not task.domain:
                task.domain = str(evt_domain)

        attributes: Dict[str, Any] = {}
        if isinstance(eventizer_data.get("attributes"), dict):
            attributes.update(eventizer_data["attributes"])
        if isinstance(params.get("attributes"), dict):
            attributes.update(params["attributes"])

        conf: Dict[str, Any] = {}
        if isinstance(eventizer_data.get("confidence"), dict):
            conf.update(eventizer_data["confidence"])
        if isinstance(params.get("confidence"), dict):
            conf.update(params["confidence"])

        pii_redacted = bool(params.get("pii", {}).get("was_redacted", False))
        if "pii_redacted" in eventizer_data:
            pii_redacted = bool(eventizer_data.get("pii_redacted"))

        fact_reads: List[str] = []
        fact_produced: List[str] = []
        if fact_dao is not None:
            start_ids = _coerce_uuid_list(params.get("start_fact_ids") or [])
            if start_ids:
                facts = await fact_dao.get_for_task(start_ids, tid)
                fact_reads = [str(fact.id) for fact in facts]
            produced_candidates: List[uuid.UUID] = []
            for key in ("produced_fact_ids", "produce_fact_ids", "fact_output_ids"):
                produced_candidates.extend(_coerce_uuid_list(params.get(key) or []))
            if produced_candidates:
                for fact_id in produced_candidates:
                    await fact_dao.record_produced_fact(fact_id, tid)
                fact_produced = [str(fid) for fid in produced_candidates]

        # Infer domain from tags if not explicitly set
        if not task.domain:
            # Map domain-specific tags to domains
            if any(tag in tags for tag in ["vip", "allergen", "luggage_custody", "hvac_fault", "privacy"]):
                task.domain = "hotel_ops"
            elif any(tag in tags for tag in ["fraud", "chargeback", "payment"]):
                task.domain = "fintech"
            elif any(tag in tags for tag in ["healthcare", "medical", "allergy"]):
                task.domain = "healthcare"
            elif any(tag in tags for tag in ["robotics", "iot", "fault"]):
                task.domain = "robotics"

        mw_hit = params.get("cache", {}).get("mw_hit") if isinstance(params.get("cache"), dict) else None
        ocps = params.get("ocps") or {}
        drift_minmax: Optional[Tuple[float, float]] = None
        if "drift_p10" in params and "drift_p90" in params:
            try:
                drift_minmax = (float(params["drift_p10"]), float(params["drift_p90"]))
            except Exception:
                drift_minmax = None

        ood_dist = params.get("ood_dist")
        graph_delta = params.get("graph_delta")
        mu_delta = params.get("mu_delta")
        dep_probs = params.get("dependency_probs")
        est_runtime = params.get("est_runtime")
        SLO = params.get("slo")
        kappa = params.get("kappa", 0.8)
        criticality = params.get("criticality", 0.5)

        signals = {
            "mw_hit": mw_hit,
            "ocps": ocps,
            "drift_minmax": drift_minmax,
            "ood_dist": ood_dist,
            "ood_to01": self.ood_to01,
            "graph_delta": graph_delta,
            "mu_delta": mu_delta,
            "dep_probs": dep_probs,
            "est_runtime": est_runtime,
            "SLO": SLO,
            "kappa": kappa,
            "criticality": criticality,
        }

        s_out = self.surprise.compute(signals)
        S = s_out["S"]
        xs = s_out["x"]
        
        # Get last decision for hysteresis (from task params if available)
        last_decision = params.get("last_decision")
        decision = decide_route_with_hysteresis(
            S, last_decision, 
            self.surprise.tau_fast, self.tau_fast_exit,
            self.surprise.tau_plan, self.tau_plan_exit
        )

        proto_plan: Dict[str, Any] = {"tasks": [], "edges": []}
        proto_plan_hints = proto_plan.setdefault("hints", {})
        if fact_reads:
            proto_plan_hints["facts_read"] = fact_reads
        if fact_produced:
            proto_plan_hints["facts_produced"] = fact_produced
        if eventizer_data:
            proto_plan_hints.setdefault("event_tags", sorted(tags))
            if isinstance(eventizer_data.get("confidence"), dict):
                proto_plan_hints.setdefault("eventizer_confidence", eventizer_data["confidence"])
        pkg_meta = {"evaluated": False, "version": None, "error": None}

        # Use global PKG manager to get active evaluator
        pkg_manager = get_global_pkg_manager()
        used_fallback = False
        
        try:
            if pkg_manager is not None:
                evaluator = pkg_manager.get_active_evaluator()
                if evaluator is not None:
                    # Build task_facts dict for evaluator
                    task_facts = {
                        "tags": list(tags),
                        "signals": {
                            "S": S,
                            "x1": xs[0],
                            "x2": xs[1],
                            "x3": xs[2],
                            "x4": xs[3],
                            "x5": xs[4],
                            "x6": xs[5],
                            "ocps": s_out["ocps"],
                        },
                        "context": {
                            "domain": task.domain,
                            "type": task.type,
                            "task_id": tid,
                            "pii_redacted": pii_redacted
                        }
                    }
                    
                    # Evaluate using the active evaluator (synchronous call)
                    pkg_res = evaluator.evaluate(task_facts)
                    
                    # Convert evaluator output to expected format
                    # Evaluator returns: {"subtasks": ..., "dag": ..., "rules": ..., "snapshot": ...}
                    # We need: {"tasks": ..., "edges": ...}
                    if isinstance(pkg_res, dict):
                        # Map subtasks -> tasks, dag -> edges
                        proto_plan = {
                            "tasks": pkg_res.get("subtasks", []),
                            "edges": pkg_res.get("dag", [])
                        }
                        pkg_meta.update({
                            "evaluated": True,
                            "version": pkg_res.get("snapshot") or evaluator.version
                        })
                    else:
                        raise ValueError("PKG returned unexpected type")
                else:
                    raise RuntimeError("PKG evaluator not available (no active snapshot)")
            else:
                raise RuntimeError("PKG manager not initialized")
        except Exception as e:
            used_fallback = True
            pkg_meta["error"] = f"PKG unavailable or timed out: {e}"
            # Generate baseline tasks when:
            # 1. User explicitly requests decomposition (force_decomposition/force_hgnn flags)
            # 2. Natural HGNN routing (decision='hgnn' means S >= tau_plan, deserves decomposition)
            force_decomp = params.get("force_decomposition", False) or params.get("force_hgnn", False)
            should_decompose = force_decomp or (decision == "hgnn")
            proto_plan = generate_proto_subtasks(tags, xs[5], criticality, force=should_decompose)

        # Add provenance tracking
        proto_plan.setdefault("provenance", [])
        if used_fallback:
            proto_plan["provenance"].append("fallback:router_rules@1.0")
        else:
            proto_plan["provenance"].append(f"pkg:{pkg_meta.get('version', 'unknown')}")

        # Honor force_decomposition: promote fast→planner or planner→hgnn
        force_decomp = params.get("force_decomposition", False)
        force_hgnn = params.get("force_hgnn", False)
        
        original_decision = decision
        if force_hgnn and decision != "hgnn":
            logger.info(f"[Coordinator] force_hgnn=True: promoting {decision} → hgnn")
            decision = "hgnn"
        elif force_decomp and decision == "fast":
            logger.info(f"[Coordinator] force_decomposition=True: promoting fast → planner")
            decision = "planner"
        
        router_latency_ms = round((time.perf_counter()-t0)*1000.0, 3)

        eventizer_summary = None
        if eventizer_data:
            eventizer_summary = {
                "event_tags": eventizer_tags.get("event_types") if eventizer_tags else None,
                "attributes": eventizer_data.get("attributes"),
                "confidence": eventizer_data.get("confidence"),
                "patterns_applied": eventizer_data.get("patterns_applied"),
                "pii_redacted": eventizer_data.get("pii_redacted"),
            }

        payload_common = {
            "task_id": tid,
            "type": task.type,
            "domain": task.domain,
            "decision": decision,
            "last_decision": last_decision,  # For hysteresis tracking
            "original_decision": original_decision if decision != original_decision else None,
            "surprise": {
                "S": S,
                "x": list(xs),
                "weights": list(self.surprise.w_hat),
                "tau_fast": self.surprise.tau_fast,
                "tau_plan": self.surprise.tau_plan,
                "tau_fast_exit": self.tau_fast_exit,
                "tau_plan_exit": self.tau_plan_exit,
                "ocps": s_out["ocps"],
                "version": "surprise/1.2.0",
            },
            "signals_present": sorted([k for k,v in signals.items() if v is not None]),
            "pkg": {"used": not used_fallback, "version": pkg_meta["version"], "error": pkg_meta["error"]},
            "proto_plan": proto_plan,
            "event_tags": sorted(list(tags)),
            "attributes": attributes,
            "confidence": conf,
            "pii_redacted": pii_redacted,
            "router_latency_ms": router_latency_ms,
            "payload_version": "router/1.2.0",
        }
        if eventizer_summary is not None:
            payload_common["eventizer"] = eventizer_summary

        # Structured logging for observability
        ocps_meta = s_out["ocps"]
        logger.info(
            f"[Coordinator] task_id={tid} S={S:.3f} x2_meta(S_t={ocps_meta.get('S_t', 'N/A')},h={ocps_meta.get('h', 'N/A')},h_clr={ocps_meta.get('h_clr', 'N/A')},flag_on={ocps_meta.get('flag_on', 'N/A')}) decision={decision} pkg_used={not used_fallback} latency_ms={router_latency_ms:.1f}"
        )

        # Create routing metadata result (always non-null)
        # This ensures the task always has a result even if execution fails
        # Keep existing top-level payload fields, but also provide a nested payload.metadata
        if decision == "fast":
            # Direct / low-surprise: fast path execution.
            res = create_fast_path_result(
                routed_to="fast",
                organ_id="coordinator",  # coordinator is delegating fast path downstream
                result={"status": "routed"},
                # This ends up inside FastPathResult.metadata
                metadata={"routing": "completed", "executed": False, **payload_common},
            ).model_dump()
        
        elif decision == "planner":
            # Medium surprise: requires cognitive planning, not direct execution.
            #
            # IMPORTANT:
            # We now emit kind == ResultKind.COGNITIVE ("cognitive")
            # so that CoordinatorHttpRouter will escalate to CognitiveRouter.
            #
            # We treat coordinator as the "routing agent" here.
            agent_id_for_planner = params.get("agent_id", "planner")
            
            # Create cognitive result with "planner" as routing decision.
            # Profile="deep" is passed as metadata (via profile in task_data) for LLM selection,
            # but routing telemetry tracks "planner" only.
            res = create_cognitive_result(
                agent_id=agent_id_for_planner,
                task_type="planner",  # Routing decision: "planner" (not "deep")
                # CognitiveRouter will receive this in execute_result; giving it our proto_plan
                # seeds the planner with what we already inferred (tasks/edges, provenance, etc.).
                result={"proto_plan": proto_plan},
                # We could optionally surface an overall confidence score. For now we omit or
                # pull something from `conf`.
                confidence_score=None,
                # This lands in CognitiveResult.metadata
                # Note: profile="deep" may be in task_data but is metadata, not routing
                **payload_common,
            ).model_dump()
        
        else:
            # High surprise / critical / incident / multi-step HGNN path.
            # This is escalated decomposition, not just "please think".
            # We KEEP this as ResultKind.ESCALATED ("escalated").
            #
            # Note: solution_steps is currently [] because we haven't executed or
            # materialized them yet; downstream systems can extend this.
            res = create_escalated_result(
                solution_steps=[],
                plan_source="router_hgnn",
                # This lands in EscalatedResult.metadata
                **payload_common,
            ).model_dump()

        # Ensure payload.metadata exists with decision/surprise/proto_plan for downstream consumers
        try:
            if isinstance(res, dict):
                payload_dict = res.setdefault("payload", {}) if isinstance(res.get("payload"), dict) else res.get("payload")
                if not isinstance(payload_dict, dict):
                    res["payload"] = payload_dict = {}
                meta = payload_dict.setdefault("metadata", {}) if isinstance(payload_dict.get("metadata"), dict) else payload_dict.get("metadata")
                if not isinstance(meta, dict):
                    payload_dict["metadata"] = meta = {}

                # Populate commonly-read fields for verifiers/consumers
                if "decision" in payload_common:
                    meta.setdefault("decision", payload_common.get("decision"))
                if "original_decision" in payload_common and payload_common.get("original_decision") is not None:
                    meta.setdefault("original_decision", payload_common.get("original_decision"))
                if "surprise" in payload_common and isinstance(payload_common.get("surprise"), dict):
                    meta.setdefault("surprise", payload_common.get("surprise"))
                if "proto_plan" in payload_common and isinstance(payload_common.get("proto_plan"), dict):
                    meta.setdefault("proto_plan", payload_common.get("proto_plan"))
                # Optional pass-throughs
                if "event_tags" in payload_common:
                    meta.setdefault("event_tags", payload_common.get("event_tags"))
                if "attributes" in payload_common and isinstance(payload_common.get("attributes"), dict):
                    meta.setdefault("attributes", payload_common.get("attributes"))
                if "confidence" in payload_common and isinstance(payload_common.get("confidence"), dict):
                    meta.setdefault("confidence", payload_common.get("confidence"))
        except Exception:
            # Best-effort; do not fail routing on formatting issues
            pass

        # Track routing decision metrics (separate from execution)
        if self.metrics:
            has_plan = bool(proto_plan.get("tasks"))
            self.metrics.track_routing_decision(decision, has_plan=has_plan)
        
        return res

# ---------- FastAPI/Serve ----------
app = FastAPI(
    title="SeedCore Coordinator",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Note: route_prefix is already set in rayservice.yaml as /pipeline
# So we use empty string here to avoid double prefixing
router_prefix = ""

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
        self.routing_remote_types = set(os.getenv("ROUTING_REMOTE_TYPES", "graph_embed,graph_rag_query,graph_embed_v2,graph_rag_query_v2").split(","))

        self.graph_repository = None  # Lazily instantiated GraphTaskRepository
        self._graph_repo_checked = False
        self.graph_task_repo = self._get_graph_repository()  # Consistent attribute name
        self._graph_sql_repo = None
        self._graph_sql_repo_checked = False

        
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
        
        # Routing is now handled by OrganismManager via resolve-route endpoints
        # Old static routing rules are preserved in _static_route_fallback method
        
        # Escalation concurrency control
        self.escalation_max_inflight = COGNITIVE_MAX_INFLIGHT
        self.escalation_semaphore = asyncio.Semaphore(5)
        self._inflight_escalations = 0
        
        # Configuration
        self.fast_path_latency_slo_ms = FAST_PATH_LATENCY_SLO_MS
        self.max_plan_steps = MAX_PLAN_STEPS

        # Downstream clients (optional; may be injected by environment/tests)
        self.planner_client = None
        
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

        logger.info("✅ Coordinator initialized")

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
        """Periodically flush task_outbox nim_task_embed events to the LTM worker with backoff."""
        try:
            session_factory = getattr(self, "_session_factory", None) or get_async_pg_session_factory()
            self._session_factory = session_factory
        except Exception as exc:
            logger.warning(f"[Coordinator] No session factory for outbox flusher: {exc}")
            return

        interval_s = float(os.getenv("TASK_OUTBOX_FLUSH_INTERVAL_S", "5"))
        batch_size = int(os.getenv("TASK_OUTBOX_FLUSH_BATCH", "100"))

        from sqlalchemy import text as sa_text

        while True:
            try:
                async with session_factory() as s:
                    async with s.begin():
                        rows = (
                            await s.execute(
                                sa_text(
                                    """
                                    WITH cte AS (
                                      SELECT id, payload
                                        FROM task_outbox
                                       WHERE event_type='nim_task_embed'
                                    ORDER BY id
                                       FOR UPDATE SKIP LOCKED
                                       LIMIT :n
                                    )
                                    SELECT id, payload FROM cte
                                    """
                                ),
                                {"n": batch_size},
                            )
                        ).mappings().all()

                        if not rows:
                            await s.rollback()
                        for r in rows:
                            try:
                                data = json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
                                task_id = data.get("task_id")
                                ok = await self._enqueue_task_embedding_now(task_id, reason="outbox")
                                if ok:
                                    await s.execute(sa_text("DELETE FROM task_outbox WHERE id=:id"), {"id": r["id"]})
                                    try:
                                        COORD_OUTBOX_FLUSH_OK.labels("nim_task_embed").inc()
                                    except Exception:
                                        pass
                                else:
                                    await s.execute(
                                        sa_text(
                                            """
                                            UPDATE task_outbox
                                               SET attempts = COALESCE(attempts,0)+1,
                                                   available_at = NOW() + (LEAST(COALESCE(attempts,0)+1,5) * INTERVAL '30 seconds')
                                             WHERE id = :id
                                            """
                                        ),
                                        {"id": r["id"]},
                                    )
                                    try:
                                        COORD_OUTBOX_FLUSH_RETRY.labels("nim_task_embed").inc()
                                    except Exception:
                                        pass
                            except Exception as exc:
                                logger.warning(f"[Coordinator] Outbox item {r.get('id')} failed: {exc}")
                                await s.execute(
                                    sa_text(
                                        """
                                        UPDATE task_outbox
                                           SET attempts = COALESCE(attempts,0)+1,
                                               available_at = NOW() + INTERVAL '60 seconds'
                                         WHERE id = :id
                                        """
                                    ),
                                    {"id": r["id"]},
                                )
                                try:
                                    COORD_OUTBOX_FLUSH_RETRY.labels("nim_task_embed").inc()
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

    def _fallback_drift_score(self, task: Dict[str, Any]) -> float:
        """
        Fallback drift score computation when ML service is unavailable.
        
        Delegates to the centralized compute_fallback_drift_score function from policies module.
        """
        return compute_fallback_drift_score(task)
    
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

    def _normalize_task_dict(self, task_like: Any) -> Tuple[uuid.UUID, Dict[str, Any]]:
        return normalize_task_dict(task_like)

    def _sync_task_identity(self, task_like: Any, task_id: str) -> None:
        sync_task_identity(task_like, task_id)

    def _extract_agent_id(self, task_dict: Dict[str, Any]) -> Optional[str]:
        return extract_agent_id(task_dict)

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
            meta = {}
            if plan.get("success") and plan.get("result"):
                # The cognitive service returns {success, agent_id, result, error}
                # We need to extract the solution steps from the result
                result = plan.get("result", {})
                steps = result.get("solution_steps", [])
                meta = result.get("meta", {})
                if not steps:
                    # If no solution_steps, try to extract from other fields
                    steps = result.get("plan", []) or result.get("steps", [])
            
            # Ingest Cognitive meta data
            if meta:
                # Feed escalate_hint into predicate signals
                escalate_hint = meta.get("escalate_hint", False)
                if escalate_hint and hasattr(self, 'predicate_router') and self.predicate_router:
                    # Update predicate signals with escalation hint
                    self.predicate_router.update_signals(escalate_hint=escalate_hint)
                
                # Add planner timings to metrics if available
                planner_timings = meta.get("planner_timings_ms", {})
                if planner_timings:
                    logger.info(f"[Coordinator] Cognitive planner timings: {planner_timings}")
                    # Could add to metrics here if needed
                
                # Log confidence score if available
                confidence = meta.get("confidence")
                if confidence is not None:
                    logger.info(f"[Coordinator] Cognitive plan confidence: {confidence}")
            
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

    # Dependency helper methods now use utils functions
    def _iter_dependency_entries(self, dependencies: Any) -> Iterable[Any]:
        return iter_dependency_entries(dependencies)

    def _resolve_child_task_id(self, record: Any, fallback_step: Any) -> Any:
        """Extract the task identifier for a persisted subtask."""
        return resolve_child_task_id(record, fallback_step)

    def _collect_record_aliases(self, record: Any) -> Set[str]:
        return collect_record_aliases(record)

    def _collect_step_aliases(self, step: Any) -> Set[str]:
        return collect_step_aliases(step)

    def _collect_aliases_from_mapping(self, mapping: Dict[str, Any]) -> Set[str]:
        return collect_aliases_from_mapping(mapping)

    def _collect_aliases_from_object(self, obj: Any) -> Set[str]:
        return collect_aliases_from_object(obj)

    def _extract_dependency_token(self, ref: Any) -> Any:
        return extract_dependency_token(ref)

    def _canonicalize_identifier(self, value: Any) -> str:
        return canonicalize_identifier(value)

    def _make_escalation_result(self, results: List[Dict[str, Any]], plan: List[Dict[str, Any]], success: bool) -> Dict[str, Any]:
        """Create a properly formatted escalation result."""
        return {
            "success": success,
            "escalated": True,
            "plan_source": "cognitive_service",
            "plan": plan,
            "results": results,
            "path": "hgnn"
        }

    async def _execute_fast(self, task: Task, cid: str) -> Dict[str, Any]:
        _, task_dict = self._normalize_task_dict(task)
        agent_id = self._extract_agent_id(task_dict)
        
        # Resolve route via TTL cache + Organism
        organ_id = None
        try:
            # Optional: preferred hint from predicates
            preferred = getattr(self.predicate_router, "preferred_logical_id", lambda *_: None)(task_dict)
            route = await self._resolve_route_cached(
                task_dict.get("type", ""), 
                task_dict.get("domain"), 
                preferred_logical_id=preferred,
                cid=cid
            )
            organ_id = route
        except Exception as e:
            logger.warning(f"resolve-route failed ({e}); using static fallback")
            organ_id = self._static_route_fallback(
                self._normalize(task_dict.get("type")),
                self._norm_domain(task_dict.get("domain"))
            )

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
        result = await _apost(
            self.http, f"{ORG}/execute-on-organ", payload,
            _corr_headers("organism", cid), timeout=ORG_TIMEOUT
        )
        # Include organ_id in the response for tracking
        result["organ_id"] = organ_id
        return result

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


            # Bulk resolve routes for all steps in the plan
            try:
                idx_to_logical = await self._bulk_resolve_routes_cached(plan, cid)
                # Stamp resolved organ_ids into each step
                for idx, step in enumerate(plan):
                    if "organ_id" not in step or not step["organ_id"]:
                        step["organ_id"] = idx_to_logical.get(idx) or self._static_route_fallback(
                            self._normalize(step.get("task", {}).get("type")),
                            self._normalize(step.get("task", {}).get("domain"))
                        )
            except Exception as e:
                logger.warning(f"[Coordinator] Bulk route resolution failed, using fallback: {e}")
                # Fallback: use static routing for each step
                for idx, step in enumerate(plan):
                    if "organ_id" not in step or not step["organ_id"]:
                        step["organ_id"] = self._static_route_fallback(
                            self._normalize(step.get("task", {}).get("type")),
                            self._normalize(step.get("task", {}).get("domain"))
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

    async def route_and_execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Serve deployment method for Ray remote calls.
        Delegates to core router with unified result schema.
        """
        await self._ensure_background_tasks_started()
        start_time = time.perf_counter()
        try:
            # Convert dict to TaskPayload if needed
            if not isinstance(payload, TaskPayload):
                payload = TaskPayload.model_validate(payload)

            session_factory = self._resolve_session_factory(self.graph_task_repo)
            if session_factory is None:
                res = await self.core.route_and_execute(
                    payload,
                    eventizer_helper=default_features_from_payload,
                )
            else:
                async with session_factory() as session:
                    async with session.begin():
                        dao = FactDAO(session)
                        res = await self.core.route_and_execute(
                            payload,
                            fact_dao=dao,
                            eventizer_helper=default_features_from_payload,
                        )

            decision = self._extract_decision(res)
            proto_plan = self._extract_proto_plan(res)

            if proto_plan:
                try:
                    await self._persist_proto_plan(
                        self.graph_task_repo,
                        payload.task_id,
                        decision,
                        proto_plan,
                    )
                except Exception as exc:
                    logger.warning(
                        "[Coordinator] Failed to persist proto-plan for %s: %s",
                        payload.task_id,
                        exc,
                    )

            followup_metadata: Optional[Dict[str, Any]] = None
            if decision in {"planner", "hgnn"}:
                try:
                    followup_metadata = await self._dispatch_route_followup(
                        decision,
                        payload,
                        proto_plan,
                    )
                except Exception as exc:
                    logger.warning(
                        "[Coordinator] Post-route dispatch failed for %s (%s): %s",
                        payload.task_id,
                        decision,
                        exc,
                    )

            if followup_metadata:
                res.setdefault("payload", {}).setdefault("metadata", {}).update(followup_metadata)

            # Track metrics
            latency_ms = (time.perf_counter() - start_time) * 1000
            decision = self._extract_decision(res) or "unknown"
            self.metrics.record_route_latency(latency_ms)
            self.metrics.track_metrics(decision, res.get("success", False), latency_ms)

            return res
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            self.metrics.record_route_latency(latency_ms)
            self.metrics.track_metrics("error", False, latency_ms)
            logger.exception(f"[Coordinator] route_and_execute failed: {e}")
            return err(str(e), "coordinator_error")

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

    async def _dispatch_route_followup(
        self,
        decision: str,
        task: "TaskPayload",
        proto_plan: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if decision == "planner":
            return await self._dispatch_planner(task, proto_plan)
        if decision == "hgnn":
            return await self._dispatch_hgnn(task, proto_plan)
        return None

    async def _dispatch_planner(
        self,
        task: "TaskPayload",
        proto_plan: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        planner = getattr(self, "planner_client", None)
        if planner is None or not hasattr(planner, "execute_plan"):
            logger.debug("[Coordinator] Planner client unavailable; skipping planner dispatch")
            return None
        try:
            planner_result = await _maybe_call(
                planner.execute_plan,
                task=task.model_dump(),
                proto_plan=proto_plan,
            )
            metrics = getattr(self, "metrics", None)
            if metrics is not None:
                metrics.record_dispatch("planner", "ok")
        except Exception as exc:
            logger.warning(
                "[Coordinator] Planner dispatch failed for %s: %s",
                task.task_id,
                exc,
            )
            metrics = getattr(self, "metrics", None)
            if metrics is not None:
                metrics.record_dispatch("planner", "err")
            return {"planner_error": str(exc)}
        return {"planner_response": planner_result}

    async def _dispatch_hgnn(
        self,
        task: "TaskPayload",
        proto_plan: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if proto_plan is None:
            return None
        repo = self._get_graph_sql_repository()
        if repo is None or not hasattr(repo, "create_task_async"):
            logger.debug("[Coordinator] Graph SQL repository unavailable; skipping HGNN dispatch")
            return None

        tasks = proto_plan.get("tasks") if isinstance(proto_plan, dict) else None
        if not isinstance(tasks, Iterable):
            return None

        agent_id = None
        try:
            agent_id = task.params.get("agent_id") if isinstance(task.params, dict) else None
        except Exception:
            agent_id = None

        created: List[Dict[str, Any]] = []
        had_error = False
        allowed_types = {
            "graph_embed": "graph_embed",
            "graph_rag_query": "graph_rag_query",
            "graph_rag_seed": "graph_rag_query",
        }
        for entry in tasks:
            if not isinstance(entry, dict):
                continue
            task_type = (entry.get("type") or "").strip().lower()
            if task_type not in allowed_types:
                logger.debug(
                    "[Coordinator] Skipping unsupported HGNN task type '%s' for %s",
                    task_type,
                    task.task_id,
                )
                continue

            raw_params = entry.get("params")
            if isinstance(raw_params, _MappingABC):
                params = dict(raw_params)
            elif isinstance(raw_params, Mapping):
                params = dict(raw_params)  # type: ignore[arg-type]
            else:
                params = {}
            description = entry.get("description")
            if not isinstance(description, str):
                description = None

            target_type = allowed_types[task_type]

            if task_type == "graph_embed":
                try:
                    graph_task_id = await repo.create_task_async(
                        target_type,
                        params,
                        description,
                        agent_id=agent_id,
                        organ_id=params.get("organ_id"),
                    )
                    created.append({
                        "type": target_type,
                        "task_id": str(graph_task_id),
                    })
                except Exception as exc:
                    logger.warning(
                        "[Coordinator] Failed to create graph_embed task for %s: %s",
                        task.task_id,
                        exc,
                    )
                    had_error = True
            elif task_type in {"graph_rag_query", "graph_rag_seed"}:
                try:
                    graph_task_id = await repo.create_task_async(
                        target_type,
                        params,
                        description,
                        agent_id=agent_id,
                        organ_id=params.get("organ_id"),
                    )
                    created.append({
                        "type": target_type,
                        "task_id": str(graph_task_id),
                    })
                except Exception as exc:
                    logger.warning(
                        "[Coordinator] Failed to create graph_rag task for %s: %s",
                        task.task_id,
                        exc,
                    )
                    had_error = True

        metrics = getattr(self, "metrics", None)
        if not created:
            if metrics is not None:
                metrics.record_dispatch("hgnn", "err" if had_error else "ok")
            return None
        if metrics is not None:
            metrics.record_dispatch("hgnn", "ok" if not had_error else "err")
        return {"graph_dispatch": {"graph_tasks": created}}

    def _get_graph_sql_repository(self) -> Optional[GraphTaskSqlRepository]:
        if getattr(self, "_graph_sql_repo", None) is not None:
            return self._graph_sql_repo
        if getattr(self, "_graph_sql_repo_checked", False):
            return None
        self._graph_sql_repo_checked = True
        try:
            self._graph_sql_repo = GraphTaskSqlRepository()
        except Exception as exc:
            logger.debug(f"[Coordinator] GraphTaskSqlRepository unavailable: {exc}")
            self._graph_sql_repo = None
        return self._graph_sql_repo

    @app.post(f"{router_prefix}/route-and-execute")
    async def route_and_execute_http(self, task: TaskPayload):
        """
        HTTP endpoint for route-and-execute.
        """
        return await self.route_and_execute(task.model_dump())

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
        try:
            async with session_factory() as session:
                async with session.begin():
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
                    inserted = await outbox_dao.enqueue_nim_task_embed(
                        session,
                        task_id=str(task_id),
                        reason="router",
                        dedupe_key=dedupe_key,
                    )
                    if metrics is not None:
                        metrics.record_outbox_enqueue("ok" if inserted else "dup")
                    try:
                        (COORD_OUTBOX_INSERT_OK if inserted else COORD_OUTBOX_INSERT_DUP).labels("nim_task_embed").inc()
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
            try:
                COORD_OUTBOX_INSERT_ERR.labels("nim_task_embed").inc()
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
                return await asyncio.wait_for(
                    enqueue_task_embedding_job(app.state, task_id, reason=reason),
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

    @app.post(f"{router_prefix}/process-task")
    async def process_task(self, payload: Dict[str, Any]):
        """
        HTTP client entry to match CoordinatorServiceClient; wraps route_and_execute.
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
                from seedcore.database import get_async_pg_session_factory
                session_factory = get_async_pg_session_factory()
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

            res = await self.core.route_and_execute(task_obj)
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
            logger.exception(f"[Coordinator] process_task failed: {e}")
            return err(str(e), "coordinator_error")

    @app.get("/health")
    async def health(self):
        """Health check endpoint with PKG status."""
        response = {
            "status": "healthy",
            "coordinator": True,
            "pkg": self.core.pkg_metadata if hasattr(self.core, 'pkg_metadata') else {"enabled": False}
        }
        return response
    
    @app.get(f"{router_prefix}/metrics")
    async def get_metrics(self):
        """Get current task execution metrics."""
        # Ensure background tasks are started
        await self._ensure_background_tasks_started()
        return self.metrics.get_metrics()
    
    @app.get("/readyz")
    async def ready(self):
        """Readiness probe for k8s."""
        return {"ready": bool(getattr(self, "_bg_started", False))}
    
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
        anomalies = await self.ml_client.detect_anomaly({"data": series})

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
                
                tuning_job = await self.ml_client.submit_tuning_job({
                    "space_type": TUNE_SPACE_TYPE,
                    "config_type": TUNE_CONFIG_TYPE,
                    "experiment_name": f"{TUNE_EXPERIMENT_PREFIX}-{agent_id}-{cid}",
                    "callback_url": f"{SEEDCORE_API_URL}/pipeline/ml/tune/callback"
                })
                
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

