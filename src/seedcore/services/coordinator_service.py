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
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

import yaml  # pyright: ignore[reportMissingModuleSource]
from pydantic import BaseModel, Field  # pyright: ignore[reportMissingImports]

from fastapi import FastAPI, Request, Body  # pyright: ignore[reportMissingImports]
from ray import serve  # pyright: ignore[reportMissingImports]

# --- Internal Imports ---
from ..logging_setup import ensure_serve_logger, setup_logging
from ..database import get_async_pg_session_factory, get_redis_client
from ..utils.ray_utils import COG, ML, ORG

# Models
from ..models.cognitive import DecisionKind, CognitiveType
from ..models.result_schema import create_error_result
from ..coordinator.models import (
    AnomalyTriageRequest,
    AnomalyTriageResponse,
    TuneCallbackRequest,
)

# Core Logic
from ..coordinator.core.policies import (
    compute_drift_score,
    SurpriseComputer,
)
from ..coordinator.core.ocps_valve import NeuralCUSUMValve
from ..coordinator.core.execute import (
    execute_task as execute_task,
    RouteConfig,
    ExecutionConfig,
)
from ..coordinator.core.routing import (
    static_route_fallback,
)
from ..coordinator.utils import (
    coerce_task_payload,
    normalize_string,
    normalize_domain,
    redact_sensitive_data,
)

# DAOs
from ..coordinator.dao import TaskOutboxDAO, TaskProtoPlanDAO, TaskRouterTelemetryDAO
from ..graph.task_metadata_repository import TaskMetadataRepository

# Predicates (Policy)
from ..predicates.safe_storage import SafeStorage

# Operations
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
from ..coordinator.metrics.registry import get_global_metrics_tracker


setup_logging(app_name="seedcore.coordinator_service.driver")
logger = ensure_serve_logger("seedcore.coordinator_service", level="DEBUG")

# --- Constants & Configuration Models ---
CONFIG_PATH = os.getenv(
    "COORDINATOR_CONFIG_PATH", "/app/config/coordinator_config.yaml"
)
FAST_PATH_LATENCY_SLO_MS = float(os.getenv("FAST_PATH_LATENCY_SLO_MS", "1000"))
router_prefix = ""


class RetentionPolicy(Enum):
    """Memory retention strategy based on information entropy."""

    FULL_ARCHIVE = "full"  # High Entropy / Novelty
    SUMMARY_ONLY = "summary"  # Medium Entropy / Routine
    DROP = "drop"  # Low Entropy / Noise


class SurpriseConfig(BaseModel):
    """Configuration for surprise thresholds and hysteresis."""

    tau_fast: float = Field(
        default_factory=lambda: float(os.getenv("SURPRISE_TAU_FAST", "0.35"))
    )
    tau_plan: float = Field(
        default_factory=lambda: float(os.getenv("SURPRISE_TAU_PLAN", "0.60"))
    )
    # Optional overrides loaded from YAML/env
    tau_fast_exit_override: Optional[float] = None
    tau_plan_exit_override: Optional[float] = None

    @property
    def tau_fast_exit(self) -> float:
        """Encapsulates hysteresis logic for fast-path exit."""
        return self.tau_fast_exit_override or (self.tau_fast + 0.03)

    @property
    def tau_plan_exit(self) -> float:
        """Encapsulates hysteresis logic for planner exit."""
        return self.tau_plan_exit_override or (self.tau_plan - 0.03)

    @classmethod
    def from_yaml(cls, data: Dict[str, Any]) -> "SurpriseConfig":
        """
        Build SurpriseConfig from a YAML section while preserving env
        precedence semantics used previously:

        Priority: YAML value -> Env Var -> Default.
        """
        # Start with env/default-backed instance
        base = cls()
        payload: Dict[str, Any] = base.model_dump()

        if "tau_fast" in data and data["tau_fast"] is not None:
            payload["tau_fast"] = float(data["tau_fast"])
        if "tau_plan" in data and data["tau_plan"] is not None:
            payload["tau_plan"] = float(data["tau_plan"])

        # YAML overrides for exit thresholds map into the *_override fields
        if "tau_fast_exit" in data and data["tau_fast_exit"] is not None:
            payload["tau_fast_exit_override"] = float(data["tau_fast_exit"])
        if "tau_plan_exit" in data and data["tau_plan_exit"] is not None:
            payload["tau_plan_exit_override"] = float(data["tau_plan_exit"])

        return cls(**payload)


class OCPSConfig(BaseModel):
    """Configuration for OCPS (drift detection) valve."""

    baseline_drift: float = 0.1
    min_change: float = 0.2
    threshold: float = 2.5
    sigma_noise: float = 0.15

    @classmethod
    def from_yaml(cls, data: Dict[str, Any]) -> "OCPSConfig":
        if not data:
            return cls()
        return cls(
            baseline_drift=float(data.get("baseline_drift", 0.1)),
            min_change=float(data.get("min_change", 0.2)),
            threshold=float(data.get("threshold", 2.5)),
            sigma_noise=float(data.get("sigma_noise", 0.15)),
        )


class TimeoutConfig(BaseModel):
    """Service timeout configuration."""

    serve_call_s: int = Field(
        default_factory=lambda: int(os.getenv("SERVE_CALL_TIMEOUT_S", "2"))
    )

    @classmethod
    def from_yaml(cls, data: Dict[str, Any]) -> "TimeoutConfig":
        payload: Dict[str, Any] = {}
        if "serve_call_s" in data and data["serve_call_s"] is not None:
            payload["serve_call_s"] = int(data["serve_call_s"])
        # Env/defaults are handled via the default_factory when field is missing
        return cls(**payload)


class CoordinatorConfig(BaseModel):
    """
    Central, typed configuration object for Coordinator.

    This merges:
    - YAML configuration (if present)
    - Environment-variable overrides
    - Sensible defaults
    """

    surprise: SurpriseConfig = Field(default_factory=SurpriseConfig)
    ocps: OCPSConfig = Field(default_factory=OCPSConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)

    @classmethod
    def load_from_yaml(cls, yaml_path: str = CONFIG_PATH) -> "CoordinatorConfig":
        path = Path(yaml_path)
        if not path.exists():
            logger.critical(
                f"❌ [CoordinatorConfig] Configuration file not found at {path}. "
                "Using environment/default-backed configuration."
            )
            return cls()

        try:
            with open(path, "r") as f:
                raw_cfg = yaml.safe_load(f) or {}

            seedcore_cfg = raw_cfg.get("seedcore", {}) or {}
            coord_cfg = seedcore_cfg.get("coordinator", {}) or {}

            surprise_cfg = coord_cfg.get("surprise_logic", {}) or {}
            ocps_cfg = coord_cfg.get("ocps_cusum", {}) or {}
            timeout_cfg = coord_cfg.get("timeouts", {}) or {}

            if not ocps_cfg:
                logger.warning(
                    "⚠️ [CoordinatorConfig] OCPS config missing in YAML; using defaults."
                )

            return cls(
                surprise=SurpriseConfig.from_yaml(surprise_cfg),
                ocps=OCPSConfig.from_yaml(ocps_cfg),
                timeouts=TimeoutConfig.from_yaml(timeout_cfg),
            )
        except Exception as e:
            logger.error(
                f"❌ [CoordinatorConfig] Failed to parse configuration at {path}: {e}",
                exc_info=True,
            )
            # Fall back to env/default-driven configuration
            return cls()


@dataclass
class ServiceMesh:
    """Grouped external service clients for the Coordinator."""

    ml: MLServiceClient
    cognitive: CognitiveServiceClient
    organism: OrganismServiceClient
    eventizer: EventizerServiceClient
    state: StateServiceClient
    energy: EnergyServiceClient

    @classmethod
    def connect(cls) -> "ServiceMesh":
        """
        Instantiate all service clients used by the Coordinator.

        This keeps the Coordinator constructor free from low-level
        networking and base_url wiring.
        """
        return cls(
            ml=MLServiceClient(base_url=ML),
            cognitive=CognitiveServiceClient(base_url=COG),
            organism=OrganismServiceClient(base_url=ORG),
            eventizer=EventizerServiceClient(),
            state=StateServiceClient(),
            energy=EnergyServiceClient(),
        )


@dataclass
class Infrastructure:
    """Aggregates infrastructure dependencies (DB, metrics, DAOs)."""

    metrics: Any
    session_factory: Any
    graph_repo: Optional[TaskMetadataRepository]
    telemetry_dao: TaskRouterTelemetryDAO
    outbox_dao: TaskOutboxDAO
    proto_plan_dao: TaskProtoPlanDAO

    @classmethod
    def setup(cls) -> "Infrastructure":
        metrics = get_global_metrics_tracker()
        session_factory = get_async_pg_session_factory()

        try:
            graph_repo = TaskMetadataRepository()
            logger.info("✅ Task Repository initialized")
        except Exception as e:
            logger.warning(f"⚠️ Task Repository init failed: {e}")
            graph_repo = None

        telemetry_dao = TaskRouterTelemetryDAO()
        outbox_dao = TaskOutboxDAO()
        proto_plan_dao = TaskProtoPlanDAO()

        return cls(
            metrics=metrics,
            session_factory=session_factory,
            graph_repo=graph_repo,
            telemetry_dao=telemetry_dao,
            outbox_dao=outbox_dao,
            proto_plan_dao=proto_plan_dao,
        )


@serve.deployment(name="Coordinator")
class Coordinator:
    def __init__(self):
        # 1. Load configuration (Brain)
        self.cfg = CoordinatorConfig.load_from_yaml()

        # 2. Initialize service mesh (External Comms)
        self.services = ServiceMesh.connect()

        # 3. Initialize infrastructure (Persistence, metrics)
        self.infra = Infrastructure.setup()

        # 4. Initialize core logic engines (Strategy)
        self._init_core_logic()

        # 5. Initialize API & runtime
        self._init_runtime()

        logger.info(
            f"🧠 Coordinator Init: Tau[F={self.cfg.surprise.tau_fast}/"
            f"P={self.cfg.surprise.tau_plan}], "
            f"OCPS[Th={self.ocps_valve.h}], Timeout={self.timeout_s}s"
        )

    def _init_core_logic(self) -> None:
        """Constructs complex logic engines based on typed configuration."""
        # Surprise computer with thresholds from config
        self.surprise_computer = SurpriseComputer(
            tau_fast=self.cfg.surprise.tau_fast,
            tau_plan=self.cfg.surprise.tau_plan,
        )

        # Hysteresis thresholds derived via config properties
        self.tau_fast_exit = self.cfg.surprise.tau_fast_exit
        self.tau_plan_exit = self.cfg.surprise.tau_plan_exit

        # OCPS valve configuration
        self.ocps_valve = NeuralCUSUMValve(
            expected_baseline=self.cfg.ocps.baseline_drift,
            min_detectable_change=self.cfg.ocps.min_change,
            threshold=self.cfg.ocps.threshold,
            sigma=self.cfg.ocps.sigma_noise,
        )

        # Service parameters
        self.timeout_s = self.cfg.timeouts.serve_call_s
        self.fast_path_latency_slo_ms = FAST_PATH_LATENCY_SLO_MS
        self.ood_to01: Optional[Any] = None

        # Signal enricher uses grouped services
        self.signal_enricher = SignalEnricher(
            state_client=self.services.state,
            energy_client=self.services.energy,
        )

        # Shortcuts for widely used dependencies to keep callsites stable
        self.ml_client = self.services.ml
        self.cognitive_client = self.services.cognitive
        self.organism_client = self.services.organism
        self.eventizer = self.services.eventizer

        self.metrics = self.infra.metrics
        self._session_factory = self.infra.session_factory
        self.graph_task_repo = self.infra.graph_repo
        self.telemetry_dao = self.infra.telemetry_dao
        self.outbox_dao = self.infra.outbox_dao
        self.proto_plan_dao = self.infra.proto_plan_dao

    def _init_runtime(self) -> None:
        """Setup web server, storage, runtime context, and routes."""
        self.app = FastAPI(title="SeedCore Coordinator (Control Plane)")

        # Storage (Redis) - Optional, falls back to in-memory if unavailable
        # Use centralized factory from database.py to respect REDIS_HOST env var
        redis_client = get_redis_client()
        # Note: SafeStorage will test the connection with ping()
        # and fall back to in-memory if it fails
        self.storage = SafeStorage(redis_client)

        # Runtime Context for Workers
        self.runtime_ctx = {"storage": self.storage, "metrics": self.metrics}

        # State Flags
        self._bg_started = False
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
            tags=["Execution"],
        )

        # Ops Endpoints
        self.app.add_api_route(
            "/health", self.health, methods=["GET"], include_in_schema=False
        )
        self.app.add_api_route(
            "/readyz", self.ready, methods=["GET"], include_in_schema=False
        )
        self.app.add_api_route(
            f"{router_prefix}/metrics",
            self.get_metrics,
            methods=["GET"],
            include_in_schema=False,
        )

    async def __call__(self, request: Request):
        """Direct ASGI call for Ray Serve."""
        send = getattr(request, "send", None) or getattr(request, "_send", None)
        if send is None:
            raise RuntimeError("Request object does not provide an ASGI send callable")
        await self.app(request.scope, request.receive, send)

    # ------------------------------------------------------------------
    # 1. The Universal Router
    # ------------------------------------------------------------------
    async def route_and_execute(
        self, payload: Dict[str, Any] = Body(...)
    ) -> Dict[str, Any]:
        """
        The Main Loop of the Control Plane.
        
        Accepts POST requests with JSON body containing the task payload.
        """
        await self._ensure_background_tasks_started()

        try:
            # A. Ingest - Handle different body formats:
            # 1. Direct dict (most common)
            # 2. Wrapped in {"payload": {...}}
            # 3. Wrapped in {"task": {...}} (for consistency with OrganismRouter)
            if isinstance(payload, dict):
                task_data = payload.get("payload") or payload.get("task") or payload
            else:
                task_data = payload
            
            # Coerce to TaskPayload
            task_obj, task_dict = coerce_task_payload(task_data)
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
                            session,
                            task_dict,
                            agent_id=task_dict.get("params", {}).get("agent_id"),
                        )

            # 2. Compute Strategy (Fast vs Deep)
            exec_config = self._build_execution_config(correlation_id)
            route_config = self._build_route_config()

            result = await execute_task(
                task=task_obj,
                route_config=route_config,
                execution_config=exec_config,
            )

            # CRITICAL: Normalize result to dispatcher-compatible format
            # Dispatcher expects: {success: bool, error: Optional[str], ...}
            # Coordinator must always return this format, never raw domain objects
            task_id = task_dict.get("task_id") or task_obj.task_id
            
            if not isinstance(result, dict):
                logger.error(
                    f"Coordinator returned non-dict result (type={type(result).__name__}) for task {task_id}"
                )
                result = {
                    "success": False,
                    "error": f"Invalid result type: {type(result).__name__}",
                    "kind": "error",
                    "path": "coordinator_type_error"
                }
            else:
                # Normalize success field - handle different result formats
                if "success" not in result:
                    # Case 1: TaskResult format: {kind: "error", payload: {error: ...}}
                    result_kind = result.get("kind")
                    if result_kind == "error" or result_kind == DecisionKind.ERROR.value:
                        # TaskResult error format - extract error from payload
                        payload = result.get("payload", {})
                        if isinstance(payload, dict):
                            result["success"] = False
                            # Extract error message from payload if not at top level
                            if "error" not in result and "error" in payload:
                                result["error"] = payload.get("error")
                            elif "error_type" in payload:
                                result["error"] = payload.get("error_type", "unknown_error")
                        else:
                            result["success"] = False
                            result["error"] = result.get("error") or "TaskResult error without payload"
                    
                    # Case 2: OrganismResponse format: {success: bool, result: {...}, error: ...}
                    # Note: OrganismResponse should already have success, but handle edge cases
                    elif "result" in result:
                        # This looks like OrganismResponse - it should have success, but if missing, infer it
                        if "success" not in result:
                            # Infer from error field (OrganismResponse.success = not bool(error))
                            result["success"] = not bool(result.get("error"))
                            logger.debug(
                                f"Coordinator inferred success from OrganismResponse format "
                                f"for task {task_id}: success={result['success']}"
                            )
                    
                    # Case 3: Raw domain object (no success/error fields)
                    else:
                        # Check if it looks like an error (has 'error' field)
                        has_error = bool(result.get("error"))
                        if has_error:
                            result["success"] = False
                        else:
                            # Assume success for raw domain objects (they're usually results)
                            result["success"] = True
                            logger.debug(
                                f"Coordinator inferred success=True for raw domain object "
                                f"(task {task_id}, keys: {list(result.keys())[:5]})"
                            )
                    
                    logger.debug(
                        f"Coordinator normalized result for task {task_id}: "
                        f"success={result.get('success')}, kind={result.get('kind')}, "
                        f"has_error={bool(result.get('error'))}, keys={list(result.keys())[:10]}"
                    )
                
                # Ensure 'error' field exists for consistency (even if None)
                if "error" not in result:
                    result["error"] = None
                
                # Ensure 'kind' field for consistency
                if "kind" not in result:
                    result["kind"] = task_type
                
                # Ensure 'path' field for traceability
                if "path" not in result:
                    result["path"] = "coordinator"
                
                # Log final normalized result structure
                logger.debug(
                    f"Coordinator final result for task {task_id}: "
                    f"success={result.get('success')}, error={result.get('error')}, "
                    f"kind={result.get('kind')}, path={result.get('path')}"
                )

            return result

        except Exception as e:
            logger.exception(f"Coordinator Route/Execute Failed: {e}")
            return create_error_result(str(e), "coordinator_fatal").model_dump()

    # Configuration loading is now handled by CoordinatorConfig

    # ------------------------------------------------------------------
    # 2. Adapters & Config Builders
    # ------------------------------------------------------------------

    async def _run_eventizer(self, task_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Adapter: Task Dict -> Eventizer Service (Ops Module) -> Feature Dict.
        This feeds the 'System 1' perception into the 'System 2' router.
        """
        text = task_dict.get("description") or ""
        if not text:
            return {}  # noqa: E701

        try:
            # Use the EventizerServiceClient
            payload = {
                "text": text,
                "domain": task_dict.get("domain"),
                "task_type": task_dict.get("type"),
            }
            resp = await self.eventizer.process(payload)

            # Client already returns dict format, just extract relevant fields
            return {
                "event_tags": resp.get("event_tags", {}),
                "attributes": resp.get("attributes", {}),
                "confidence": resp.get("confidence", {}),
                "pii_redacted": resp.get("pii_redacted", False),
            }
        except Exception as e:
            logger.warning(f"Eventizer failed (non-blocking): {e}")
            return {}

    def _build_route_config(self) -> RouteConfig:
        """
        Build routing policy config with global PKG manager (PKG-first architecture).
        
        Architecture: PKG is the authoritative source of routing hints.
        This adapter normalizes PKG output to proto_plan contract expected by core.execute.
        """

        async def evaluate_pkg_func(tags, signals, context, timeout_s):
            """
            PKG evaluation adapter that returns proto_plan contract.
            
            Returns proto_plan structure compatible with core.execute._extract_routing_intent_from_proto_plan():
            - proto_plan["routing"] (top-level routing hints)
            - proto_plan["steps"] (list of step dicts with task.params.routing)
            """
            pkg_mgr = get_global_pkg_manager()
            evaluator = pkg_mgr and pkg_mgr.get_active_evaluator()
            if not evaluator:
                raise RuntimeError("PKG evaluator not available")

            payload = {
                "tags": list(tags or []),
                "signals": signals or {},
                "context": context or {},
            }

            # evaluator.evaluate(...) is often sync; run it in a thread w/ timeout
            async def _run_eval():
                return await asyncio.to_thread(evaluator.evaluate, payload)

            res = await asyncio.wait_for(_run_eval(), timeout=float(timeout_s or 2))

            # ---- Normalize to proto_plan contract expected by core.execute ----
            subtasks = res.get("subtasks", []) or res.get("tasks", []) or []
            dag = res.get("dag", []) or res.get("edges", []) or []
            version = res.get("snapshot") or res.get("version") or getattr(evaluator, "version", None)

            # IMPORTANT: "steps" is the canonical field expected downstream.
            # Each step should be a dict with at minimum {"task": {...}}.
            steps = []
            for st in subtasks:
                if isinstance(st, dict):
                    # allow either {"task": {...}} or raw task dict
                    if "task" in st and isinstance(st["task"], dict):
                        steps.append(st)
                    else:
                        steps.append({"task": st})
                else:
                    # object-like fallback
                    steps.append({"task": getattr(st, "task", st)})

            proto_plan = {
                "version": version,
                "steps": steps,
                "edges": dag,
            }

            # If PKG provides explicit routing intent, pass through.
            # (Preferred: proto_plan["routing"]["required_specialization"])
            if isinstance(res.get("routing"), dict):
                proto_plan["routing"] = res["routing"]

            return proto_plan

        # NOTE: pkg_timeout_s should be a *PKG timeout*, not serve_call_s.
        pkg_timeout = int(os.getenv("PKG_TIMEOUT_S", str(min(5, self.timeout_s or 2))))

        return RouteConfig(
            surprise_computer=self.surprise_computer,
            tau_fast_exit=self.tau_fast_exit,
            tau_plan_exit=self.tau_plan_exit,
            ocps_valve=self.ocps_valve,
            signal_enricher=self.signal_enricher,
            evaluate_pkg_func=evaluate_pkg_func,
            ood_to01=self.ood_to01,
            pkg_timeout_s=pkg_timeout,
            # Keep intent_resolver unset to discourage non-PKG routing
            intent_resolver=None,
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

        async def organism_execute(
            organ_id: str, task_dict: dict, timeout: float, cid_local: str
        ) -> dict:
            """
            Executes a task on a specific Organism (via HTTP/RPC) using TaskPayload v2 semantics.
            
            Architecture: Coordinator delegates execution to Organism with routing hints
            already embedded in the payload. Organism resolves HOW to execute.
            
            Note: This is a nested function that captures 'self' from the closure.
            """
            # 1. Prepare Payload (Shallow Copy to avoid mutation side-effects)
            payload = task_dict.copy()
            params = payload.setdefault("params", {})

            # Ensure correlation_id is set for cross-service tracing
            payload.setdefault("correlation_id", cid_local)

            # 2. V2 Interaction Setup
            # Ensure the receiving Organism knows this was routed by Coordinator
            # and that it needs to perform internal agent selection.
            interaction = params.setdefault("interaction", {})
            if not interaction.get("mode"):
                interaction["mode"] = "coordinator_routed"

            # (Optional) If you map Organ IDs to Specializations, you could enforce it here:
            # params.setdefault("routing", {})["required_specialization"] = _map_organ_to_spec(organ_id)

            # 3. Build headers with correlation + task ID for tracing
            headers = _corr_headers("organism", cid_local)
            if payload.get("task_id"):
                headers["X-Task-ID"] = str(payload["task_id"])

            try:
                # 4. Call Unified Organism Endpoint
                # Note: The network routing to 'organ_id' happens here via the client
                # 'self' is captured from the closure (outer scope)
                res = await self.organism_client.post(
                    "/route-and-execute",
                    json={"task": payload},
                    headers=headers,
                    timeout=float(timeout),
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
                    "task_id": payload.get("task_id"),
                }

        async def persist_proto_plan_func(repo, tid, kind, plan):
            await self._persist_proto_plan(repo, tid, kind, plan)

        async def record_router_telemetry_func(repo, tid, res):
            await self._record_router_telemetry(repo, tid, res)

        def resolve_session_factory(repo=None):
            return self._session_factory

        return ExecutionConfig(
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
            fast_path_latency_slo_ms=self.fast_path_latency_slo_ms,
            eventizer_helper=self._run_eventizer,
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
            "context": payload.context,
        }

        drift_score = await self._compute_drift_score(
            task_data,
            text_payload={"text": task_data.get("description", "")},
        )
        is_novel = drift_score > 0.7
        retention = (
            RetentionPolicy.FULL_ARCHIVE if is_novel else RetentionPolicy.SUMMARY_ONLY
        )
        
        # Use correct OCPS valve name (ocps_valve, not ocps)
        drift_state = self.ocps_valve.update(drift_score)
        should_escalate = bool(getattr(drift_state, "is_breached", False))

        decision_kind = (
            DecisionKind.COGNITIVE if should_escalate else DecisionKind.FAST_PATH
        )
        reason = {"drift_score": drift_score, "is_novel": is_novel}

        if should_escalate:
            logger.info(f"[Triage] Escalating {agent_id} (Score: {drift_score:.2f})")
            try:
                cog_res = await self.cognitive_client.execute_async(
                    agent_id=agent_id,
                    cog_type=CognitiveType.PROBLEM_SOLVING,
                    decision_kind=DecisionKind.COGNITIVE,
                    task={"params": {"hgnn": {"embedding": payload.series}}},
                )
                reason = cog_res.get("result", {})
            except Exception as e:
                logger.warning(f"[Triage] Cognitive check failed: {e}")

        if retention != RetentionPolicy.DROP:
            asyncio.create_task(
                self._fire_and_forget_memory_synthesis(
                    agent_id=agent_id,
                    anomalies={"series": payload.series, "score": drift_score},
                    reason=reason,
                    decision_kind=decision_kind.value,
                    cid=cid,
                    retention_policy=retention,
                )
            )

        return AnomalyTriageResponse(
            agent_id=agent_id,
            anomalies={},
            reason=reason,
            decision_kind={
                "result": {"action": "escalate" if should_escalate else "hold"}
            },
            correlation_id=cid,
            escalated=should_escalate,
        )

    async def _handle_tune_callback(self, payload: TuneCallbackRequest):
        """
        Handle ML tuning callback.
        
        Note: predicate_router is not part of the current architecture.
        This endpoint is kept for backward compatibility but does not update
        predicate router state.
        """
        try:
            logger.info(f"[Coord] Tuning callback {payload.job_id}: {payload.status}")
            success = payload.status == "completed"
            
            # NOTE: predicate_router is not initialized in current architecture
            # If you need GPU job status tracking, initialize it in _init_core_logic()
            # or remove this functionality.
            # self.predicate_router.update_gpu_job_status(
            #     payload.job_id, payload.status, success=success
            # )
            
            if success:
                logger.info(
                    f"Job {payload.job_id} success. GPU Secs: {payload.gpu_seconds}"
                )
            self.storage.delete(f"job:{payload.job_id}")
            return {"success": True}
        except Exception as e:
            logger.error(f"Callback processing failed: {e}")
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # 4. Internal Helpers
    # ------------------------------------------------------------------

    async def _compute_drift_score(
        self,
        task: Dict[str, Any],
        text_payload: Dict[str, Any],
        ml_client: Any = None,
        metrics: Any = None,
        **_: Any,
    ) -> float:
        """
        Compute drift score with signature-tolerant wrapper.
        
        Architecture: Matches core.execute._call_compute_drift_score() signature
        to avoid signature mismatch issues. Accepts extra kwargs for future-proofing.
        """
        return await compute_drift_score(
            task=task,
            text_payload=text_payload,
            ml_client=ml_client or self.ml_client,
            metrics=metrics or self.metrics,
        )

    async def _fire_and_forget_memory_synthesis(
        self, agent_id, anomalies, reason, decision_kind, cid, retention_policy
    ):
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
                    {"decision": str(decision_kind)},
                ],
                "synthesis_goal": "incident_summary",
            }

            await self.cognitive_client.post(
                "/synthesize-memory", json=payload, headers={"X-Correlation-ID": cid}
            )
        except Exception as e:
            logger.warning(f"Memory synthesis failed: {e}")

    def _prune_heavy_content(self, data: Any) -> Any:
        HEAVY_KEYS = {"dom_tree", "screenshot_base64", "full_http_body", "series"}
        if isinstance(data, dict):
            return {
                k: (v if k not in HEAVY_KEYS else "<PRUNED>") for k, v in data.items()
            }
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
                        ocps_metadata=surprise.get("ocps", {}),
                    )
        except Exception as e:
            logger.warning(f"Telemetry persist failed: {e}")

    async def _enqueue_task_embedding_now(
        self, task_id: str, reason: str = "router"
    ) -> bool:
        try:
            from ..graph.task_embedding_worker import enqueue_task_embedding_job

            for _ in range(2):
                try:
                    await asyncio.wait_for(
                        enqueue_task_embedding_job(
                            self.runtime_ctx, task_id, reason=reason
                        ),
                        timeout=2.0,
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
                            rows = await self.outbox_dao.claim_pending_nim_task_embeds(
                                s, limit=50
                            )
                            for row in rows:
                                tid = json.loads(row["payload"])["task_id"]
                                if await self._enqueue_task_embedding_now(
                                    tid, "outbox"
                                ):
                                    await self.outbox_dao.delete(s, row["id"])
                                else:
                                    await self.outbox_dao.backoff(s, row["id"])
            except Exception as e:
                logger.debug(f"Outbox flush error: {e}")
            await asyncio.sleep(5.0)

    async def _start_background_tasks(self):
        # But the client might have cache logic, usually no init needed for HTTP client
        self._bg_tasks = []
        self._bg_tasks.append(asyncio.create_task(self._task_outbox_flusher_loop()))
        self._bg_tasks.append(asyncio.create_task(self._warmup_drift_detector()))

    async def _ensure_background_tasks_started(self):
        """
        Idempotent starter. Handles both infinite loops (Outbox)
        and one-off warmups (Drift Detector).
        """
        # 1. Idempotency Check: Unified Flag
        # We only need one flag to know if we've pulled the trigger.
        if self._bg_started:
            return

        logger.info("🚀 Coordinator: Triggering background protocols & warmup...")

        # 2. Lock the flag immediately
        self._bg_started = True

        # 3. Initialize the task container if not exists
        if not hasattr(self, "_bg_tasks"):
            self._bg_tasks = []

        # 4. Launch The Infinite Loop (Maintenance)
        # This runs forever to flush the outbox
        t_outbox = asyncio.create_task(
            self._task_outbox_flusher_loop(), name="loop_outbox"
        )
        self._bg_tasks.append(t_outbox)

        # 5. Launch The One-Off Warmup (Optimization)
        # This runs once to load heavy math/matrices so the first API call isn't slow.
        if not self._warmup_started:
            t_warmup = asyncio.create_task(
                self._warmup_drift_detector(), name="task_warmup"
            )
            self._bg_tasks.append(t_warmup)
            # Note: The warmup method itself should set self._warmup_started = True
            # when it finishes, or we can set it here if we just mean "started".

    async def _warmup_drift_detector(self):
        import random

        await asyncio.sleep(random.uniform(2.0, 5.0))
        try:
            if await self.ml_client.is_healthy():
                await self.ml_client.warmup_drift_detector(["warmup"])
        except Exception:
            pass

    async def health(self):
        return {"status": "healthy", "tier": "0"}

    async def ready(self):
        return {"ready": self._bg_started}

    async def get_metrics(self):
        return self.metrics.get_metrics()

    async def get_predicate_status(self):
        """
        Get predicate router status.
        
        Note: predicate_config is not part of the current PKG-first architecture.
        PKG policy evaluation replaces predicate-based routing.
        """
        return {
            "rules": 0,
            "note": "predicate_config not enabled in PKG-first architecture. "
                    "PKG policy evaluation handles routing decisions."
        }

    async def get_predicate_config(self):
        """
        Get predicate router configuration.
        
        Note: predicate_config is not part of the current PKG-first architecture.
        PKG policy evaluation replaces predicate-based routing.
        """
        return {
            "routing": [],
            "note": "predicate_config not enabled in PKG-first architecture. "
                    "PKG policy evaluation handles routing decisions."
        }

    def _normalize(self, x):
        return normalize_string(x)

    def _norm_domain(self, x):
        return normalize_domain(x)

    def _static_route_fallback(self, t, d):
        return static_route_fallback(t, d)

    def _get_job_state(self, jid):
        return self.storage.get(f"job:{jid}")


# Deployment Bind
coordinator_deployment = Coordinator.bind()
