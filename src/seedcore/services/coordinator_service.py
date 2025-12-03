"""
Coordinator Service (Tier-0 Control Plane)

Responsibilities:
1. Ingestion & System of Record (Persist to DB).
2. Strategy & Routing (Surprise Score, PKG Policy).
3. Plan-Execute-Audit Loop (Orchestrating multi-step plans).
4. Anomaly Triage & Memory Consolidation.

This service is the "Cortex" of the organism. It decides WHAT to do,
but delegates HOW (Cognitive) and ACTION (Organism).
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import uuid
from enum import Enum
from typing import Any, Dict, Union

import yaml  # pyright: ignore[reportMissingModuleSource]

import redis  # pyright: ignore[reportMissingImports]
from fastapi import FastAPI, Request  # pyright: ignore[reportMissingImports]
from ray import serve  # pyright: ignore[reportMissingImports]

# --- Internal Imports ---
from ..logging_setup import ensure_serve_logger, setup_logging
from ..database import get_async_pg_session_factory
from ..utils.ray_utils import COG, ML, ORG

# Models
from ..models import TaskPayload
from ..models.cognitive import DecisionKind, CognitiveType
from ..models.result_schema import create_error_result
from ..coordinator.models import AnomalyTriageRequest, AnomalyTriageResponse, TuneCallbackRequest

# Core Logic
from ..coordinator.core.policies import (
    compute_drift_score, 
    SurpriseComputer,
)
from ..coordinator.core.ocps_valve import NeuralCUSUMValve
from ..coordinator.core.execute import (
    route_and_execute as core_route_and_execute,
    RouteConfig,
    ExecutionConfig
)
from ..coordinator.core.routing import (
    static_route_fallback,
)
from ..coordinator.utils import (
    coerce_task_payload,
    normalize_string,
    normalize_domain,
    normalize_task_dict,
    redact_sensitive_data
)

# DAOs
from ..coordinator.dao import TaskOutboxDAO, TaskProtoPlanDAO, TaskRouterTelemetryDAO
from ..graph.task_metadata_repository import TaskMetadataRepository

# Predicates (Policy)
from ..predicates.safe_storage import SafeStorage

# Operations
from ..ops.metrics import get_global_metrics_tracker
from ..ops.pkg.manager import get_global_pkg_manager

# Clients
from ..serve.cognitive_client import CognitiveServiceClient
from ..serve.ml_client import MLServiceClient
from ..serve.organism_client import OrganismServiceClient
# CHANGED: Import Client instead of Service
from ..serve.eventizer_client import EventizerServiceClient
from ..serve.state_client import StateServiceClient
from ..serve.energy_client import EnergyServiceClient
from ..coordinator.core.signals import SignalEnricher


setup_logging(app_name="seedcore.coordinator_service.driver")
logger = ensure_serve_logger("seedcore.coordinator_service", level="DEBUG")

# --- Constants ---
COORDINATOR_CONFIG_PATH = os.getenv("COORDINATOR_CONFIG_PATH", "/app/config/coordinator_config.yaml")
FAST_PATH_LATENCY_SLO_MS = float(os.getenv("FAST_PATH_LATENCY_SLO_MS", "1000"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
router_prefix = ""

class RetentionPolicy(Enum):
    """Memory retention strategy based on information entropy."""
    FULL_ARCHIVE = "full"       # High Entropy / Novelty
    SUMMARY_ONLY = "summary"    # Medium Entropy / Routine
    DROP = "drop"               # Low Entropy / Noise


@serve.deployment(name="Coordinator")
class Coordinator:
    def __init__(self):
        self.app = FastAPI(title="SeedCore Coordinator (Control Plane)")
        
        # 1. Service Mesh Clients
        self.ml_client = MLServiceClient(base_url=ML)
        self.cognitive_client = CognitiveServiceClient(base_url=COG)
        self.organism_client = OrganismServiceClient(base_url=ORG)
        
        # CHANGED: Initialize Remote Client for System 1 Perception
        # This connects to the Ops module where Eventizer is running
        self.eventizer = EventizerServiceClient()

        # Global SLO configuration
        self.fast_path_latency_slo_ms = FAST_PATH_LATENCY_SLO_MS

        # State/Energy clients for contextual signals
        self.state_client = StateServiceClient()
        self.energy_client = EnergyServiceClient()
        self.signal_enricher = SignalEnricher(
            state_client=self.state_client,
            energy_client=self.energy_client,
        )
        
        # 2. Infrastructure & DAOs
        self.metrics = get_global_metrics_tracker()
        self._session_factory = get_async_pg_session_factory()
        
        try:
            self.graph_task_repo = TaskMetadataRepository()
            logger.info("✅ Task Repository initialized")
        except Exception as e:
            logger.warning(f"⚠️ Task Repository init failed: {e}")
            self.graph_task_repo = None

        self.telemetry_dao = TaskRouterTelemetryDAO()
        self.outbox_dao = TaskOutboxDAO()
        self.proto_plan_dao = TaskProtoPlanDAO()
        
        # ------------------------------------------------------------------
        # 1. CENTRAL CONFIG LOADING
        # ------------------------------------------------------------------
        # Load once, use everywhere.
        full_cfg = self._load_cfg()
        coord_cfg = full_cfg.get("coordinator", {})
        
        # Extract sub-sections with safety defaults
        surprise_cfg = coord_cfg.get("surprise_logic", {})
        cusum_cfg = coord_cfg.get("ocps_cusum", {})
        timeout_cfg = coord_cfg.get("timeouts", {})

        # ------------------------------------------------------------------
        # 2. SURPRISE COMPUTER (System 2 Thresholds)
        # ------------------------------------------------------------------
        # Priority: Config YAML -> Env Var -> Default
        tau_fast = float(surprise_cfg.get("tau_fast") or os.getenv("SURPRISE_TAU_FAST", "0.35"))
        tau_plan = float(surprise_cfg.get("tau_plan") or os.getenv("SURPRISE_TAU_PLAN", "0.60"))
        
        self.surprise_computer = SurpriseComputer(tau_fast=tau_fast, tau_plan=tau_plan)

        # Hysteresis Thresholds (Derived or Configured)
        # Allows explicit override in YAML, otherwise calculates standard hysteresis
        self.tau_fast_exit = float(
            surprise_cfg.get("tau_fast_exit") 
            or os.getenv("SURPRISE_TAU_FAST_EXIT") 
            or (tau_fast + 0.03)
        )
        self.tau_plan_exit = float(
            surprise_cfg.get("tau_plan_exit") 
            or os.getenv("SURPRISE_TAU_PLAN_EXIT") 
            or (tau_plan - 0.03)
        )

        # ------------------------------------------------------------------
        # 3. OCPS VALVE (Drift Detection)
        # ------------------------------------------------------------------
        if not cusum_cfg:
            logger.warning("⚠️ OCPS config missing in YAML; using hardcoded defaults.")

        self.ocps_valve = NeuralCUSUMValve(
            expected_baseline=float(cusum_cfg.get("baseline_drift", 0.1)),
            min_detectable_change=float(cusum_cfg.get("min_change", 0.2)),
            threshold=float(cusum_cfg.get("threshold", 2.5)),
            sigma=float(cusum_cfg.get("sigma_noise", 0.15))
        )

        # ------------------------------------------------------------------
        # 4. SERVICE PARAMETERS
        # ------------------------------------------------------------------
        self.timeout_s = int(
            timeout_cfg.get("serve_call_s") 
            or os.getenv("SERVE_CALL_TIMEOUT_S", "2")
        )
        self.ood_to01 = None 

        logger.info(
            f"🧠 Coordinator Init: Tau[F={tau_fast}/P={tau_plan}], "
            f"OCPS[Th={self.ocps_valve.h}], Timeout={self.timeout_s}s"
        )

        # 5. Storage (Redis)
        try:
            redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            self.storage = SafeStorage(redis_client)
        except Exception:
            self.storage = SafeStorage(None)
            
        # Runtime Context for Workers
        self.runtime_ctx = {
            "storage": self.storage,
            "metrics": self.metrics
        }

        # State Flags
        self._bg_started = False
        self._background_tasks_started = False
        self._warmup_started = False
        self.routing_remote_enabled = False 
        self.routing_remote_types = set()

        self._register_routes()
        logger.info("✅ Coordinator (Tier-0) initialized")


    def _register_routes(self) -> None:
        """Unified Route Registration."""
        # Business Endpoint
        self.app.add_api_route(
            f"{router_prefix}/route-and-execute",
            self.route_and_execute,
            methods=["POST"],
            summary="Unified Entrypoint for Routing, Triage, and Execution",
            tags=["Execution"]
        )
        
        # Ops Endpoints
        self.app.add_api_route("/health", self.health, methods=["GET"], include_in_schema=False)
        self.app.add_api_route("/readyz", self.ready, methods=["GET"], include_in_schema=False)
        self.app.add_api_route(f"{router_prefix}/metrics", self.get_metrics, methods=["GET"], include_in_schema=False)

    async def __call__(self, request: Request):
        """Direct ASGI call for Ray Serve."""
        send = getattr(request, "send", None) or getattr(request, "_send", None)
        if send is None:
            raise RuntimeError("Request object does not provide an ASGI send callable")
        await self.app(request.scope, request.receive, send)

    # ------------------------------------------------------------------
    # 1. The Universal Router
    # ------------------------------------------------------------------
    async def route_and_execute(self, payload: Union[TaskPayload, Dict[str, Any]]) -> Dict[str, Any]:
        """
        The Main Loop of the Control Plane.
        """
        await self._ensure_background_tasks_started()
        
        try:
            # A. Ingest
            task_obj, task_dict = coerce_task_payload(payload)
            task_type = task_obj.type.lower()

            # B. Special Workflows
            if task_type == "anomaly_triage":
                req = AnomalyTriageRequest(**task_dict.get("params", {}))
                return await self._handle_anomaly_triage(req)
            
            if task_type == "ml_tune_callback":
                req = TuneCallbackRequest(**task_dict.get("params", {}))
                return await self._handle_tune_callback(req)

            # C. Core Pipeline
            # 1. Persist Inbox (System of Record)
            correlation_id = task_dict.get("correlation_id") or uuid.uuid4().hex
            if self.graph_task_repo and self._session_factory:
                async with self._session_factory() as session:
                    async with session.begin():
                        await self.graph_task_repo.create_task(
                            session, task_dict, agent_id=task_dict.get("params", {}).get("agent_id")
                        )

            # 2. Compute Strategy (Fast vs Deep)
            exec_config = self._build_execution_config(correlation_id)
            route_config = self._build_route_config()
            
            result = await core_route_and_execute(
                task=task_obj,
                routing_config=route_config,
                execution_config=exec_config,
                eventizer_helper=self._run_eventizer # <--- Wired here
            )

            return result

        except Exception as e:
            logger.exception(f"Coordinator Route/Execute Failed: {e}")
            return create_error_result(str(e), "coordinator_fatal").model_dump()



    # Assuming logger is defined and available in the CoordinatorService scope
    # Assuming COORDINATOR_CONFIG_PATH is globally defined/imported

    def _load_cfg(self) -> Dict[str, Any]:
        """
        Loads configuration settings from the YAML file specified by
        COORDINATOR_CONFIG_PATH environment variable.
        
        Returns:
            The loaded configuration dictionary.
        """
        config_path = COORDINATOR_CONFIG_PATH
        path = Path(config_path)

        if not path.exists():
            logger.critical(
                f"❌ [CoordinatorService] CRITICAL: Configuration file not found at {path}. "
                "Using empty configuration."
            )
            return {}
            
        try:
            with open(path, "r") as f:
                # Use safe_load to prevent arbitrary code execution from malicious YAML
                cfg = yaml.safe_load(f)
                logger.info(f"✅ [CoordinatorService] Loaded configuration from {path}.")
                
                # The configuration is nested under 'seedcore'. Return the relevant dictionary.
                return cfg.get("seedcore", {})
                
        except Exception as e:
            logger.error(
                f"❌ [CoordinatorService] Failed to parse configuration file at {path}: {e}", 
                exc_info=True
            )
            return {}

    # ------------------------------------------------------------------
    # 2. Adapters & Config Builders
    # ------------------------------------------------------------------

    async def _run_eventizer(self, task_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Adapter: Task Dict -> Eventizer Service (Ops Module) -> Feature Dict.
        This feeds the 'System 1' perception into the 'System 2' router.
        """
        text = task_dict.get("description") or ""
        if not text: return {}  # noqa: E701
        
        try:
            # Use the EventizerServiceClient
            payload = {
                "text": text,
                "domain": task_dict.get("domain"),
                "task_type": task_dict.get("type")
            }
            resp = await self.eventizer.process(payload)
            
            # Client already returns dict format, just extract relevant fields
            return {
                "event_tags": resp.get("event_tags", {}),
                "attributes": resp.get("attributes", {}),
                "confidence": resp.get("confidence", {}),
                "pii_redacted": resp.get("pii_redacted", False)
            }
        except Exception as e:
            logger.warning(f"Eventizer failed (non-blocking): {e}")
            return {}

    def _build_route_config(self) -> RouteConfig:
        """Builds routing policy config with global PKG manager."""
        async def evaluate_pkg_func(tags, signals, context, timeout_s):
            pkg_mgr = get_global_pkg_manager()
            evaluator = pkg_mgr and pkg_mgr.get_active_evaluator()
            if not evaluator:
                raise RuntimeError("PKG evaluator not available")
            
            res = evaluator.evaluate({
                "tags": list(tags),
                "signals": signals,
                "context": context or {},
            })
            return {
                "tasks": res.get("subtasks", []),
                "edges": res.get("dag", []),
                "version": res.get("snapshot") or evaluator.version,
            }

        return RouteConfig(
            surprise_computer=self.surprise_computer,
            tau_fast_exit=self.tau_fast_exit,
            tau_plan_exit=self.tau_plan_exit,
            ocps_valve=self.ocps_valve,
            signal_enricher=self.signal_enricher,
            evaluate_pkg_func=evaluate_pkg_func,
            ood_to01=self.ood_to01,
            pkg_timeout_s=self.timeout_s,
        )

    def _build_execution_config(self, cid: str) -> ExecutionConfig:
        """Builds execution dependency container."""
        
        def _corr_headers(target: str, c: str) -> Dict[str, str]:
            return {
                "Content-Type": "application/json",
                "X-Service": "coordinator",
                "X-Source-Service": "coordinator",
                "X-Target-Service": target,
                "X-Correlation-ID": c,
            }
        
        async def organism_execute(self, organ_id: str, task_dict: dict, timeout: int, cid_local: str) -> dict:
            """
            Executes a task on a specific Organism (via HTTP/RPC) using TaskPayload v2 semantics.
            """
            # 1. Prepare Payload (Shallow Copy to avoid mutation side-effects)
            payload = task_dict.copy()
            params = payload.setdefault("params", {})
            
            # 2. V2 Interaction Setup
            # Ensure the receiving Organism knows this was routed by Coordinator
            # and that it needs to perform internal agent selection.
            interaction = params.setdefault("interaction", {})
            if not interaction.get("mode"):
                interaction["mode"] = "coordinator_routed"

            # (Optional) If you map Organ IDs to Specializations, you could enforce it here:
            # params.setdefault("routing", {})["required_specialization"] = _map_organ_to_spec(organ_id)

            try:
                # 3. Call Unified Organism Endpoint
                # Note: The network routing to 'organ_id' happens here via the client
                res = await self.organism_client.post(
                    "/route-and-execute",
                    json={"task": payload},
                    headers=_corr_headers("organism", cid_local),
                    timeout=timeout
                )
                
                # 4. Handle Result & Back-fill V2 Metadata
                if isinstance(res, dict):
                    # STRATEGY: Look in V2 locations for the executing organ
                    # Priority A: result.meta.routing_decision.selected_organ_id (The official telemetry)
                    # Priority B: params._router.organ_id (The router's internal write-only record)
                    # Priority C: Fallback to the requested organ_id
                    
                    result_meta = res.get("result", {}).get("meta", {})
                    router_out = res.get("params", {}).get("_router", {})
                    
                    final_organ = (
                        result_meta.get("routing_decision", {}).get("selected_organ_id")
                        or router_out.get("organ_id")
                        or organ_id
                    )

                    # Ensure top-level consistency for the Coordinator's return
                    res["organ_id"] = final_organ
                    
                    # Ensure the result block also carries it (if needed for downstream)
                    if "result" in res and isinstance(res["result"], dict):
                        res["result"]["organ_id"] = final_organ
                        
                return res

            except Exception as e:
                logger.error(f"Organism execution failed for {organ_id}: {e}")
                # Return a structure that mimics a failed TaskPayload result
                return {
                    "success": False, 
                    "error": str(e), 
                    "organ_id": organ_id,
                    "task_id": payload.get("task_id")
                }

        async def persist_proto_plan_func(repo, tid, kind, plan):
            await self._persist_proto_plan(repo, tid, kind, plan)
            
        async def record_router_telemetry_func(repo, tid, res):
            await self._record_router_telemetry(repo, tid, res)

        def resolve_session_factory(repo=None):
            return self._session_factory

        return ExecutionConfig(
            normalize_task_dict=normalize_task_dict,
            compute_drift_score=self._compute_drift_score,
            organism_execute=organism_execute,
            graph_task_repo=self.graph_task_repo,
            ml_client=self.ml_client,
            metrics=self.metrics,
            cid=cid,
            normalize_domain=normalize_domain,
            cognitive_client=self.cognitive_client,
            persist_proto_plan_func=persist_proto_plan_func,
            record_router_telemetry_func=record_router_telemetry_func,
            resolve_session_factory_func=resolve_session_factory,
            fast_path_latency_slo_ms=self.fast_path_latency_slo_ms
        )

    # ------------------------------------------------------------------
    # 3. Workflows (Triage, Callbacks)
    # ------------------------------------------------------------------

    async def _handle_anomaly_triage(self, payload: AnomalyTriageRequest):
        cid = uuid.uuid4().hex
        agent_id = payload.agent_id
        
        task_data = {
            "id": f"triage_{agent_id}", 
            "type": "anomaly_triage",
            "description": f"Triage for {agent_id}",
            "context": payload.context
        }
        
        drift_score = await self._compute_drift_score(task_data)
        is_novel = drift_score > 0.7
        retention = RetentionPolicy.FULL_ARCHIVE if is_novel else RetentionPolicy.SUMMARY_ONLY
        should_escalate = self.ocps.update(drift_score)
        
        decision_kind = DecisionKind.COGNITIVE if should_escalate else DecisionKind.FAST_PATH
        reason = {"drift_score": drift_score, "is_novel": is_novel}
        
        if should_escalate:
            logger.info(f"[Triage] Escalating {agent_id} (Score: {drift_score:.2f})")
            try:
                cog_res = await self.cognitive_client.execute_async(
                    agent_id=agent_id,
                    cog_type=CognitiveType.PROBLEM_SOLVING,
                    decision_kind=DecisionKind.COGNITIVE,
                    task={"params": {"hgnn": {"embedding": payload.series}}}
                )
                reason = cog_res.get("result", {})
            except Exception as e:
                logger.warning(f"[Triage] Cognitive check failed: {e}")

        if retention != RetentionPolicy.DROP:
            asyncio.create_task(self._fire_and_forget_memory_synthesis(
                agent_id=agent_id,
                anomalies={"series": payload.series, "score": drift_score},
                reason=reason,
                decision_kind=decision_kind.value,
                cid=cid,
                retention_policy=retention
            ))

        return AnomalyTriageResponse(
            agent_id=agent_id,
            anomalies={},
            reason=reason,
            decision_kind={"result": {"action": "escalate" if should_escalate else "hold"}},
            correlation_id=cid,
            escalated=should_escalate
        )

    async def _handle_tune_callback(self, payload: TuneCallbackRequest):
        try:
            logger.info(f"[Coord] Tuning callback {payload.job_id}: {payload.status}")
            success = (payload.status == "completed")
            self.predicate_router.update_gpu_job_status(payload.job_id, payload.status, success=success)
            if success:
                logger.info(f"Job {payload.job_id} success. GPU Secs: {payload.gpu_seconds}")
            self.storage.delete(f"job:{payload.job_id}")
            return {"success": True}
        except Exception as e:
            logger.error(f"Callback processing failed: {e}")
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # 4. Internal Helpers
    # ------------------------------------------------------------------

    async def _compute_drift_score(self, task: Dict[str, Any]) -> float:
        return await compute_drift_score(
            task=task,
            ml_client=self.ml_client,
            metrics=self.metrics
        )

    async def _fire_and_forget_memory_synthesis(self, agent_id, anomalies, reason, decision_kind, cid, retention_policy):
        try:
            if retention_policy == RetentionPolicy.DROP:
                return

            if retention_policy == RetentionPolicy.SUMMARY_ONLY:
                anomalies = self._prune_heavy_content(anomalies)
                
            payload = {
                "agent_id": agent_id,
                "memory_fragments": [
                    {"anomalies": redact_sensitive_data(anomalies)},
                    {"reason": redact_sensitive_data(reason)},
                    {"decision": str(decision_kind)}
                ],
                "synthesis_goal": "incident_summary"
            }
            
            await self.cognitive_client.post(
                "/synthesize-memory", 
                json=payload, 
                headers={"X-Correlation-ID": cid}
            )
        except Exception as e:
            logger.warning(f"Memory synthesis failed: {e}")

    def _prune_heavy_content(self, data: Any) -> Any:
        HEAVY_KEYS = {"dom_tree", "screenshot_base64", "full_http_body", "series"}
        if isinstance(data, dict):
            return {k: (v if k not in HEAVY_KEYS else "<PRUNED>") for k, v in data.items()}
        return data

    async def _persist_proto_plan(self, repo, tid, kind, plan):
        try:
             async with self._session_factory() as session:
                async with session.begin():
                    await self.proto_plan_dao.upsert(session, str(tid), str(kind), plan)
        except Exception as e:
            logger.warning(f"Proto-plan persist failed: {e}")

    async def _record_router_telemetry(self, repo, tid, res):
        try:
             async with self._session_factory() as session:
                async with session.begin():
                    payload = res.get("payload", {})
                    surprise = payload.get("surprise", {})
                    await self.telemetry_dao.insert(
                        session,
                        task_id=str(tid),
                        surprise_score=float(surprise.get("S", 0.0)),
                        x_vector=list(surprise.get("x", [])),
                        weights=list(surprise.get("weights", [])),
                        chosen_route=str(res.get("decision_kind", "unknown")),
                        ocps_metadata=surprise.get("ocps", {})
                    )
        except Exception as e:
             logger.warning(f"Telemetry persist failed: {e}")

    async def _enqueue_task_embedding_now(self, task_id: str, reason: str = "router") -> bool:
        try:
            from ..graph.task_embedding_worker import enqueue_task_embedding_job
            for _ in range(2):
                try:
                    await asyncio.wait_for(
                        enqueue_task_embedding_job(self.runtime_ctx, task_id, reason=reason),
                        timeout=2.0
                    )
                    return True
                except Exception:
                    await asyncio.sleep(0.1)
            return False
        except ImportError:
            return False
        except Exception as e:
            logger.warning(f"Fast-embed failed: {e}")
            return False

    async def _task_outbox_flusher_loop(self):
        while True:
            try:
                if self._session_factory:
                    async with self._session_factory() as s:
                        async with s.begin():
                            rows = await self.outbox_dao.claim_pending_nim_task_embeds(s, limit=50)
                            for row in rows:
                                tid = json.loads(row["payload"])["task_id"]
                                if await self._enqueue_task_embedding_now(tid, "outbox"):
                                    await self.outbox_dao.delete(s, row["id"])
                                else:
                                    await self.outbox_dao.backoff(s, row["id"])
            except Exception as e:
                logger.debug(f"Outbox flush error: {e}")
            await asyncio.sleep(5.0)

    async def _start_background_tasks(self):
        # Removed local eventizer init since we use client now
        # But the client might have cache logic, usually no init needed for HTTP client
        asyncio.create_task(self._task_outbox_flusher_loop())
        asyncio.create_task(self._warmup_drift_detector())

    async def _warmup_drift_detector(self):
        import random
        await asyncio.sleep(random.uniform(2.0, 5.0))
        try:
            if await self.ml_client.is_healthy():
                await self.ml_client.warmup_drift_detector(["warmup"])
        except Exception:
            pass

    async def health(self): return {"status": "healthy", "tier": "0"}
    async def ready(self): return {"ready": self._bg_started}
    async def get_metrics(self): return self.metrics.get_metrics()
    async def get_predicate_status(self): return {"rules": len(self.predicate_config.routing)}
    async def get_predicate_config(self): return self.predicate_config.dict()

    def _normalize(self, x): return normalize_string(x)
    def _norm_domain(self, x): return normalize_domain(x)
    def _static_route_fallback(self, t, d): return static_route_fallback(t, d)
    def _get_job_state(self, jid): return self.storage.get(f"job:{jid}")

# Deployment Bind
coordinator_deployment = Coordinator.bind()