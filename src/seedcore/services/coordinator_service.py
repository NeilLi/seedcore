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
from sqlalchemy import text  # pyright: ignore[reportMissingImports]

# --- Internal Imports ---
from ..logging_setup import ensure_serve_logger, setup_logging
from ..database import get_async_pg_session_factory, get_redis_client
from ..utils.ray_utils import COG, ML, ORG

# Models
from ..models.cognitive import DecisionKind, CognitiveType
from ..models.result_schema import (
    make_envelope,
    normalize_envelope,
)
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
from ..ops.pkg.capability_monitor import CapabilityMonitor
from ..ops.pkg.capability_registry import CapabilityRegistry
from ..ops.pkg.client import PKGClient

# Clients
from ..serve.cognitive_client import CognitiveServiceClient
from ..serve.ml_client import MLServiceClient
from ..serve.organism_client import OrganismServiceClient

# CHANGED: Import Client instead of Service
from ..serve.eventizer_client import EventizerServiceClient
from ..serve.state_client import StateServiceClient
from ..serve.energy_client import EnergyServiceClient

# FastEventizer for dual-stage perception (local reflex before remote brain)
from ..ops.eventizer.fast_eventizer import get_fast_eventizer
# Text normalization (before FastEventizer)
from ..ops.eventizer.utils.text_normalizer import TextNormalizer, NormalizationTier

# Multimodal Context Refinement (bridges perception to Unified Memory)
from ..ops.eventizer.utils.context_refiner import MultimodalContextRefiner

from ..coordinator.core.signals import SignalEnricher
from ..coordinator.metrics.registry import get_global_metrics_tracker


setup_logging(app_name="seedcore.coordinator_service.driver")
logger = ensure_serve_logger("seedcore.coordinator_service", level="DEBUG")

# --- Constants & Configuration Models ---
CONFIG_PATH = os.getenv(
    "COORDINATOR_CONFIG_PATH", "/app/config/coordinator_config.yaml"
)
FAST_EVENTIZER_PATTERNS_PATH = os.getenv(
    "FAST_EVENTIZER_PATTERNS_PATH", "/app/config/fast_eventizer_patterns.json"
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
        default_factory=lambda: int(os.getenv("SERVE_CALL_TIMEOUT_S", "5"))
    )
    organism_timeout_s: int = Field(
        default_factory=lambda: int(os.getenv("ORGANISM_TIMEOUT_S", "20"))
    )

    @classmethod
    def from_yaml(cls, data: Dict[str, Any]) -> "TimeoutConfig":
        payload: Dict[str, Any] = {}
        if "serve_call_s" in data and data["serve_call_s"] is not None:
            payload["serve_call_s"] = int(data["serve_call_s"])
        if "organism_timeout_s" in data and data["organism_timeout_s"] is not None:
            payload["organism_timeout_s"] = int(data["organism_timeout_s"])
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
            f"OCPS[Th={self.ocps_valve.h}], Timeout={self.timeout_s}s, "
            f"OrganismTimeout={self.organism_timeout_s}s"
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
        self.organism_timeout_s = self.cfg.timeouts.organism_timeout_s
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
        # Initialize task embedding queue infrastructure for 1024d worker
        # This implements the Transactional Outbox Pattern for reliable embedding delivery
        self.runtime_ctx = {
            "storage": self.storage,
            "metrics": self.metrics,
            "task_embedding_queue": asyncio.Queue(maxsize=2000),
            "task_embedding_pending": set(),
            "task_embedding_pending_lock": asyncio.Lock(),
        }

        # State Flags
        self._bg_started = False
        self._warmup_started = False
        self.routing_remote_enabled = False
        self.routing_remote_types = set()

        # Capability Monitor (initialized lazily on startup)
        self._capability_monitor: Optional[CapabilityMonitor] = None
        self._capability_monitor_task: Optional[asyncio.Task] = None

        self._register_routes()
        
        # Start capability monitor in background (non-blocking)
        # Use asyncio.create_task if we're in an async context, otherwise defer
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._start_capability_monitor())
        except RuntimeError:
            # No running loop - will start on first request or via endpoint
            pass
        
        logger.info("✅ Coordinator (Tier-0) initialized")

    async def _ensure_capability_monitor(self) -> Optional[CapabilityMonitor]:
        """
        Lazy initialization of CapabilityMonitor.
        Starts monitoring pkg_subtask_types changes and notifies OrganismService.
        """
        if self._capability_monitor is not None:
            return self._capability_monitor

        try:
            # Initialize PKG components
            session_factory = get_async_pg_session_factory()
            pkg_client = PKGClient(session_factory)
            capability_registry = CapabilityRegistry(pkg_client)

            # Initial refresh
            active_snapshot = await pkg_client.get_active_snapshot()
            if active_snapshot:
                await capability_registry.refresh(
                    active_snapshot.id,
                    register_dynamic_specs=True,
                )
                logger.info(
                    f"✅ CapabilityRegistry initialized with snapshot {active_snapshot.id}"
                )

            # Create callback to notify OrganismService
            async def on_capability_changes(changes: list) -> None:
                """Callback when capability changes are detected."""
                if not changes:
                    return
                
                logger.info(
                    f"📢 Notifying OrganismService of {len(changes)} capability changes"
                )
                try:
                    # Notify OrganismService via RPC
                    # Convert CapabilityChange objects to dicts for serialization
                    # Include snapshot_id for version consistency validation
                    # Include new_capability data so OrganismCore can rebuild role profiles
                    # **PRIORITY: This ensures pkg_subtask_types data overrides static YAML configs**
                    changes_dict = [{
                        "capability_name": c.capability_name,
                        "change_type": c.change_type,
                        "specialization": c.specialization,
                        "snapshot_id": c.snapshot_id,
                        "new_capability": c.new_capability,  # Include full capability data for role profile rebuild
                    } for c in changes]
                    
                    # Use Ray remote call if available, otherwise HTTP
                    if hasattr(self.organism_client, "rpc_notify_capability_changes"):
                        await self.organism_client.rpc_notify_capability_changes.remote(
                            changes=changes_dict
                        )
                    else:
                        # Fallback to HTTP POST if RPC not available
                        await self.organism_client.post(
                            "/capability-changes",
                            json={"changes": changes_dict}
                        )
                except Exception as e:
                    logger.warning(
                        f"Failed to notify OrganismService of capability changes: {e}",
                        exc_info=True
                    )

            # Create monitor (without organism_core - we notify via RPC instead)
            monitor = CapabilityMonitor(
                pkg_client=pkg_client,
                capability_registry=capability_registry,
                organism_core=None,  # We notify via RPC instead
                poll_interval=float(os.getenv("CAPABILITY_MONITOR_POLL_INTERVAL", "30.0")),
                auto_register_specs=True,
                auto_manage_agents=False,  # OrganismService handles agent management
                on_changes_callback=on_capability_changes,
            )

            # Start monitoring
            await monitor.start()
            self._capability_monitor = monitor

            logger.info("✅ CapabilityMonitor started in CoordinatorService")
            return monitor

        except Exception as e:
            logger.error(f"Failed to initialize CapabilityMonitor: {e}", exc_info=True)
            return None

    async def _start_capability_monitor(self) -> None:
        """Start capability monitor in background."""
        if self._capability_monitor_task is not None:
            return

        async def _init_and_start():
            try:
                monitor = await self._ensure_capability_monitor()
                if monitor:
                    logger.info("✅ CapabilityMonitor started successfully")
            except Exception as e:
                logger.error(f"CapabilityMonitor startup failed: {e}", exc_info=True)

        # Start in background (use get_event_loop for compatibility)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
        self._capability_monitor_task = loop.create_task(_init_and_start())

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
        self.app.add_api_route(
            f"{router_prefix}/capability-monitor/status",
            self.capability_monitor_status,
            methods=["GET"],
        )
        self.app.add_api_route(
            f"{router_prefix}/capability-monitor/start",
            self.start_capability_monitor_endpoint,
            methods=["POST"],
        )
        self.app.add_api_route(
            f"{router_prefix}/pkg-status",
            self.get_pkg_status,
            methods=["GET"],
            summary="Get PKG evaluator status",
            tags=["Ops"],
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

            # B. Special Workflows
            # Extract workflow from TaskPayload structure:
            # 1. Top-level field (task_obj.workflow)
            # 2. Dict top-level (task_dict.get("workflow"))
            # 3. params.cognitive.workflow (where it's stored in JSONB)
            workflow = (
                task_obj.workflow
                or task_dict.get("workflow")
                or task_dict.get("params", {}).get("cognitive", {}).get("workflow")
                or None
            )
            
            if workflow == "anomaly_triage":
                req = AnomalyTriageRequest(**task_dict.get("params", {}))
                return await self._handle_anomaly_triage(req)

            if workflow == "ml_tune_callback":
                req = TuneCallbackRequest(**task_dict.get("params", {}))
                return await self._handle_tune_callback(req)

            # C. Core Pipeline
            # 1. Persist Inbox (System of Record)
            correlation_id = task_dict.get("correlation_id") or uuid.uuid4().hex
            
            # Server-side snapshot_id enforcement: Ensure task has snapshot_id
            # This is done at the Coordinator level (server-side) to enforce snapshot scoping
            if task_dict.get("snapshot_id") is None:
                try:
                    async with self._session_factory() as session:
                        result = await session.execute(text("SELECT pkg_active_snapshot_id('prod')"))
                        active_snapshot_id = result.scalar_one_or_none()
                        if active_snapshot_id is not None:
                            task_dict["snapshot_id"] = active_snapshot_id
                            logger.debug(
                                "Coordinator: Set snapshot_id=%d for task %s",
                                active_snapshot_id,
                                task_dict.get("task_id") or task_dict.get("id")
                            )
                except Exception as e:
                    logger.warning(
                        "Coordinator: Could not get active snapshot_id: %s (non-fatal)",
                        e
                    )
            
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

            # Normalize result to canonical envelope format
            task_id = task_dict.get("task_id") or task_obj.task_id
            return normalize_envelope(result, task_id=task_id, path="coordinator")

        except Exception as e:
            logger.exception(f"Coordinator Route/Execute Failed: {e}")
            # Get task_id safely (might not be defined if exception occurs early)
            task_id = (
                task_dict.get("task_id") if "task_dict" in locals() 
                else task_obj.task_id if "task_obj" in locals()
                else "unknown"
            )
            return make_envelope(
                task_id=task_id,
                success=False,
                error=str(e),
                error_type="coordinator_fatal",
                decision_kind=DecisionKind.ERROR.value,
                path="coordinator",
            )

    # Configuration loading is now handled by CoordinatorConfig

    # ------------------------------------------------------------------
    # 2. Adapters & Config Builders
    # ------------------------------------------------------------------

    async def _run_eventizer(self, task_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dual-Stage Orchestrator for SeedCore Perception.
        """
        text = task_dict.get("description") or ""
        params = task_dict.get("params", {}) or {}
        multimodal_ctx = params.get("multimodal") or {}

        if not text and not multimodal_ctx:
            return {}

        # Stage 1: Local Reflex (Deterministic Regex & PII)
        resp_obj = self._run_fast_reflex(text, task_dict)

        # Stage 2: Multimodal Refinement (Semantic Grounding & Vision Narrative)
        refinement = self._refine_multimodal_context(text, task_dict, multimodal_ctx)

        # Decision: Skip remote if it's an emergency or high-confidence routine
        from seedcore.models.eventizer import EventType

        is_emergency = EventType.EMERGENCY in resp_obj.event_tags.hard_tags
        is_confident = resp_obj.confidence.overall_confidence >= 0.9
        needs_deep_reasoning = resp_obj.confidence.needs_ml_fallback

        if is_emergency or (is_confident and not needs_deep_reasoning):
            return self._format_eventizer_output(
                self._merge_refinement(resp_obj.model_dump(), refinement)
            )

        # Stage 3: Remote Brain (Deep Semantic Reasoning)
        # Pass FastEventizer output for refinement (complementary mode)
        try:
            # Convert resp_obj to dict if it's a Pydantic model
            fast_output = (
                resp_obj.model_dump() if hasattr(resp_obj, "model_dump") 
                else resp_obj if isinstance(resp_obj, dict)
                else resp_obj.dict() if hasattr(resp_obj, "dict")
                else {}
            )
            
            remote_data = await self._call_remote_eventizer(
                text, task_dict, multimodal_ctx, refinement, fast_eventizer_output=fast_output
            )
            return self._format_eventizer_output(remote_data)
        except Exception as e:
            logger.warning(f"Remote Eventizer failed, using refined Fast-Path: {e}")
            return self._format_eventizer_output(
                self._merge_refinement(resp_obj.model_dump() if hasattr(resp_obj, "model_dump") else resp_obj, refinement)
            )

    def _run_fast_reflex(self, text: str, task_dict: Dict[str, Any]):
        """
        Run FastEventizer for local deterministic perception (regex, PII detection, emergency detection).
        
        Architecture: Normalization happens BEFORE FastEventizer (reflex sensor).
        This ensures single normalization point and consistent pattern matching.
        """
        # Step 1: Normalize text (AGGRESSIVE tier for fast, deterministic matching)
        # This happens BEFORE FastEventizer to ensure single normalization point
        normalizer = TextNormalizer(
            tier=NormalizationTier.AGGRESSIVE,
            case="lower",
            fold_accents=False,
            standardize_units=True,  # Essential for unit grounding ("6 PM" -> "18:00")
            strip_audio_tags=True,  # Essential for voice-to-text transcripts
            join_split_tokens=True,  # De-obfuscation for security bypass prevention
        )
        normalized_text, _ = normalizer.normalize(text, build_map=True)
        
        # Step 2: FastEventizer (reflex sensor) receives pre-normalized text
        fast_ev = get_fast_eventizer(FAST_EVENTIZER_PATTERNS_PATH)
        task_id = task_dict.get("task_id") or task_dict.get("id")
        # FastEventizer returns EventizerResponse directly (no conversion needed)
        return fast_ev.process_text(
            normalized_text=normalized_text,
            original_text=text,
            task_type=task_dict.get("type", ""),
            domain=task_dict.get("domain", ""),
            task_id=task_id,
        )

    def _refine_multimodal_context(
        self, text: str, task_dict: Dict[str, Any], multimodal_ctx: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Refines multimodal context: temporal grounding and vision narrative synthesis.

        Returns a refinement dict with:
        - refined_text: cleaned and temporally grounded text
        - has_temporal_intent: whether temporal grounding was applied
        - grounded_timestamp: ISO timestamp if temporal intent found
        - vision_narrative: synthesized narrative for vision tasks
        """
        refinement = {
            "refined_text": text,
            "has_temporal_intent": False,
            "grounded_timestamp": None,
            "vision_narrative": None,
        }

        # 1. Temporal Grounding (voice/text transcripts)
        if text:
            try:
                from datetime import datetime

                # Extract context time from task_dict (supports now_utc, timestamp, etc.)
                context_time = None
                now_str = task_dict.get("now_utc") or task_dict.get("timestamp")
                if now_str:
                    try:
                        if isinstance(now_str, str):
                            # Handle ISO format with or without Z suffix
                            context_time = datetime.fromisoformat(
                                now_str.replace("Z", "+00:00")
                            )
                        elif isinstance(now_str, datetime):
                            context_time = now_str
                    except (ValueError, AttributeError) as e:
                        logger.debug(f"Failed to parse context time '{now_str}': {e}")

                refined_data = MultimodalContextRefiner.refine_voice_transcript(
                    text, context_time=context_time
                )
                refinement.update(refined_data)

                logger.debug(
                    f"[Eventizer] Refined text for task {task_dict.get('task_id') or task_dict.get('id')}: "
                    f"has_temporal_intent={refinement.get('has_temporal_intent')}"
                )
            except Exception as e:
                logger.debug(f"[Eventizer] Text refinement failed (non-fatal): {e}")

        # 2. Vision Narrative Synthesis
        if multimodal_ctx and multimodal_ctx.get("modality") == "vision":
            try:
                detections = multimodal_ctx.get("detections", [])
                camera_id = multimodal_ctx.get("camera_id", "unknown")

                # Ensure detections is a list
                if not isinstance(detections, list):
                    detections = []

                vision_narrative = MultimodalContextRefiner.synthesize_vision_event(
                    detections, camera_id
                )
                refinement["vision_narrative"] = vision_narrative

                logger.debug(
                    f"[Eventizer] Synthesized vision narrative for task {task_dict.get('task_id') or task_dict.get('id')}"
                )
            except Exception as e:
                logger.debug(
                    f"[Eventizer] Vision narrative synthesis failed (non-fatal): {e}"
                )

        return refinement

    async def _call_remote_eventizer(
        self,
        text: str,
        task_dict: Dict[str, Any],
        multimodal_ctx: dict,
        refinement: dict,
        fast_eventizer_output: Optional[Dict[str, Any]] = None,
    ):
        """
        Call remote EventizerService with refined text and multimodal context.

        Architecture: This stage only runs if FastEventizer is uncertain or needs
        deep reasoning. The service refines FastEventizer output rather than redoing
        all processing, ensuring complementary operation.

        Args:
            text: Original text
            task_dict: Task dictionary
            multimodal_ctx: Multimodal context
            refinement: Multimodal refinement data
            fast_eventizer_output: Optional FastEventizer output for refinement mode
        """
        # Determine normalization tier based on task type
        # COGNITIVE preserves sentiment for CHAT tasks (guest interactions)
        # AGGRESSIVE normalizes units/time for MAINTENANCE/IOT (system signals)
        task_type_str = (task_dict.get("type") or "").lower()
        tier = "cognitive" if task_type_str == "chat" else "aggressive"

        # Combine refined text with vision narrative for the LLM
        final_text = refinement.get("refined_text") or text
        vision_narrative = refinement.get("vision_narrative")
        if vision_narrative:
            final_text = f"{vision_narrative} | {final_text}"

        # Build payload - if FastEventizer output is provided, use it for refinement
        if fast_eventizer_output:
            # Refinement mode: Pass FastEventizer output to EventizerService
            # EventizerService will skip redundant normalization/PII and refine instead
            payload = {
                "text": final_text,  # Use REFINED text (cleaned + temporally grounded)
                "domain": task_dict.get("domain"),
                "task_type": task_dict.get("type"),  # Preserve original case
                "media_context": multimodal_ctx,  # Essential for v2.5 multimodal caching
                "include_pkg_hint": tier == "cognitive",  # Hint for TextNormalizer tier selection
                # Pass FastEventizer output for refinement
                "processed_text": fast_eventizer_output.get("processed_text") or final_text,
                "normalized_text": fast_eventizer_output.get("normalized_text") or final_text,
                "_fast_eventizer_processed": True,
                "_fast_eventizer_pii_redacted": fast_eventizer_output.get("pii_redacted", False),
                "_fast_eventizer_normalized": True,
            }
            logger.debug("EventizerService: Refining FastEventizer output (complementary mode)")
        else:
            # Full processing mode (no FastEventizer preprocessing)
            payload = {
                "text": final_text,  # Use REFINED text (cleaned + temporally grounded)
                "domain": task_dict.get("domain"),
                "task_type": task_dict.get("type"),  # Preserve original case
                "media_context": multimodal_ctx,  # Essential for v2.5 multimodal caching
                "include_pkg_hint": tier == "cognitive",  # Hint for TextNormalizer tier selection
            }

        remote_resp = await self.eventizer.process(payload)

        # Ensure Pydantic is converted to dict for merging
        data = (
            remote_resp.model_dump()
            if hasattr(remote_resp, "model_dump")
            else remote_resp
        )
        return self._merge_refinement(data, refinement)

    def _merge_refinement(
        self, base_data: Dict[str, Any], refinement: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merges semantic refinement signals into the perception result.

        This ensures that grounded timestamps and synthesized vision narratives
        are persisted into the 'task_multimodal_embeddings' table.
        """
        # 1. Update processed text with the grounded version
        refined_text = refinement.get("refined_text")
        vision_narrative = refinement.get("vision_narrative")

        current_text = (
            base_data.get("processed_text") or base_data.get("normalized_text") or ""
        )

        # If we have a vision narrative, prepend it to provide spatial context
        if vision_narrative:
            current_text = f"{vision_narrative} | {current_text}".strip(" |")

        # If the refiner cleaned up audio artifacts, prioritize that text
        if refined_text and len(refined_text) < len(current_text):
            base_data["processed_text"] = refined_text
        else:
            base_data["processed_text"] = current_text

        # 2. Inject Grounded Signals into Attributes
        # This is what the PKG uses for logical branching (e.g. scheduling)
        if refinement.get("has_temporal_intent"):
            attrs = base_data.setdefault("attributes", {})
            # Ensure it's a dict (in case it came back as a Pydantic object)
            if hasattr(attrs, "model_dump"):
                attrs = attrs.model_dump()

            attrs["grounded_time"] = refinement.get("grounded_timestamp")
            base_data["attributes"] = attrs

        # 3. Populate Surprise Signals (Bridge to SurpriseComputer)
        signals = base_data.setdefault("signals", {})
        if refinement.get("has_temporal_intent"):
            # Flag that logic might be complex due to temporal constraints
            signals["x5_logic_uncertainty"] = 0.3

        if vision_narrative:
            # Flag multimodal contribution
            signals["x3_multimodal_anomaly"] = signals.get("x3_multimodal_anomaly", 0.1)

        return base_data

    def _format_eventizer_output(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Standardizes the output for TaskContext ingestion.

        Handles both FastEventizer and RemoteEventizer output formats,
        ensuring consistent structure for downstream processing.
        """
        # Handle both dict and Pydantic model_dump formats
        if isinstance(data, dict):
            event_tags = data.get("event_tags", {})
            # Convert EventTags Pydantic model to dict if needed
            if hasattr(event_tags, "model_dump"):
                event_tags = event_tags.model_dump()
            elif hasattr(event_tags, "dict"):
                event_tags = event_tags.dict()

            return {
                "event_tags": event_tags,
                "attributes": (
                    data.get("attributes", {}).model_dump()
                    if hasattr(data.get("attributes", {}), "model_dump")
                    else data.get("attributes", {})
                ),
                "confidence": (
                    data.get("confidence", {}).model_dump()
                    if hasattr(data.get("confidence", {}), "model_dump")
                    else data.get("confidence", {})
                ),
                "signals": (
                    data.get("signals", {}).model_dump()
                    if hasattr(data.get("signals", {}), "model_dump")
                    else data.get("signals", {})
                ),
                "pii_redacted": data.get("pii_redacted", False),
                "processed_text": data.get("processed_text")
                or data.get("normalized_text")
                or "",
                "normalized_text": data.get("normalized_text")
                or data.get("processed_text")
                or "",
                "multimodal": (
                    data.get("multimodal", {}).model_dump()
                    if hasattr(data.get("multimodal"), "model_dump")
                    else data.get("multimodal")
                )
                if data.get("multimodal")
                else None,
            }
        else:
            # Fallback for unexpected types
            logger.warning(f"Unexpected Eventizer output type: {type(data)}")
            return {}

    def _build_route_config(self) -> RouteConfig:
        """
        Build routing policy config with global PKG manager (PKG-first architecture).

        Architecture: PKG is the authoritative source of routing hints.
        This adapter normalizes PKG output to proto_plan contract expected by core.execute.
        
        NOTE: RouteConfig is cached per-instance to avoid rebuilding on every request.
        """
        # Cache RouteConfig to avoid rebuilding on every request
        if not hasattr(self, '_cached_route_config'):
            self._cached_route_config = None
        
        # Cache pkg_timeout value to avoid env var lookup on every request
        # NOTE: pkg_timeout_s should be a *PKG timeout*, not serve_call_s.
        if not hasattr(self, '_cached_pkg_timeout'):
            self._cached_pkg_timeout = int(os.getenv("PKG_TIMEOUT_S", str(min(5, self.timeout_s or 2))))
        pkg_timeout = self._cached_pkg_timeout

        async def evaluate_pkg_func(tags, signals, context, timeout_s, embedding=None):
            """
            PKG evaluation adapter that returns proto_plan contract.

            Returns proto_plan structure compatible with coordinator.core.intent.PKGPlanIntentExtractor:
            - proto_plan["routing"] (top-level routing hints)
            - proto_plan["steps"] (list of step dicts with task.params.routing)

            Architecture: Option A (Quickest) - Adapts PKG output to proto_plan shape.
            Extracts routing hints from subtask params and embeds them into proto_plan structure.
            
            ENHANCEMENT: Now supports semantic context hydration via embedding parameter.
            Uses PKGManager.evaluate_task() for async hydration -> evaluation pipeline.
            """
            pkg_mgr = get_global_pkg_manager()
            if not pkg_mgr:
                logger.warning("[PKG] PKG manager not available - degrading to fallback routing")
                # Return minimal proto_plan instead of raising (graceful degradation)
                return {
                    "version": None,
                    "steps": [{"task": context.get("raw_task", {})}] if context else [],
                    "edges": [],
                    "routing": {},
                }

            evaluator = pkg_mgr.get_active_evaluator()
            if not evaluator:
                logger.warning(
                    "[PKG] Evaluator not available - degrading to fallback routing"
                )
                # Return minimal proto_plan instead of raising (graceful degradation)
                return {
                    "version": None,
                    "steps": [{"task": context.get("raw_task", {})}] if context else [],
                    "edges": [],
                    "routing": {},
                }

            logger.debug(
                f"[PKG] Evaluator active: version={getattr(evaluator, 'version', 'unknown')}, "
                f"engine={getattr(evaluator, 'engine_type', 'unknown')}, "
                f"embedding_provided={embedding is not None}"
            )

            # Build task_facts payload for PKG evaluation
            # Include stable identifiers for task correlation and debugging
            task_facts = {
                "tags": list(tags or []),
                "signals": signals or {},
                "context": {
                    **(context or {}),
                    # Ensure stable identifiers are always present
                    "task_id": context.get("task_id"),
                    "domain": context.get("domain"),
                    "type": context.get("type"),
                    "workflow": context.get("workflow"),
                    "correlation_id": context.get("correlation_id"),
                },
            }

            # Use PKGManager's evaluate_task for async hydration -> evaluation pipeline
            # This performs: Hydration (if embedding provided) -> Injection -> Execution
            # Use RouteConfig.pkg_timeout_s consistently (ignore passed timeout_s parameter)
            pkg_timeout_actual = float(pkg_timeout or 2)
            try:
                res = await asyncio.wait_for(
                    pkg_mgr.evaluate_task(task_facts, embedding=embedding),
                    timeout=pkg_timeout_actual
                )
            except asyncio.TimeoutError:
                logger.warning(f"[PKG] Evaluation timed out after {pkg_timeout_actual}s - degrading to fallback routing")
                # Return minimal proto_plan instead of raising (graceful degradation)
                return {
                    "version": None,
                    "steps": [{"task": context.get("raw_task", {})}] if context else [],
                    "edges": [],
                    "routing": {},
                }
            except Exception as e:
                logger.warning(f"[PKG] Evaluation failed: {e} - degrading to fallback routing", exc_info=True)
                # Return minimal proto_plan instead of raising (graceful degradation)
                return {
                    "version": None,
                    "steps": [{"task": context.get("raw_task", {})}] if context else [],
                    "edges": [],
                    "routing": {},
                }

            # Verification: Log PKG output structure
            logger.debug(
                f"[PKG] Evaluation result keys: {list(res.keys())}, "
                f"subtasks_count={len(res.get('subtasks', []))}, "
                f"has_routing={bool(res.get('routing'))}"
            )

            # ---- Normalize to proto_plan contract expected by core.execute ----
            subtasks = res.get("subtasks", []) or res.get("tasks", []) or []
            dag = res.get("dag", []) or res.get("edges", []) or []
            version = (
                res.get("snapshot")
                or res.get("version")
                or getattr(evaluator, "version", None)
            )

            # ---- Capability enrichment (DNA registry -> executor hints) ----
            # The PKG emits subtasks with `type=<pkg_subtask_types.name>`.
            # We convert them into executable step tasks by:
            # - looking up default_params in `pkg_subtask_types`
            # - merging default_params with emission params (emission wins)
            # - stamping params.capability / params.executor / params.routing (if provided)
            #
            # This keeps SeedCore core abstract: the mapping lives in DB JSON.
            try:
                cap_registry = getattr(pkg_mgr, "capabilities", None)
            except Exception:
                cap_registry = None

            # Extract routing hints from PKG output (Option A: adapt wrapper)
            # Strategy: Check top-level routing first, then extract from subtask params
            extracted_routing = {}

            # 1. Check for top-level routing in PKG output
            if isinstance(res.get("routing"), dict):
                extracted_routing = dict(res["routing"])
                logger.debug(
                    f"[PKG] Found top-level routing: {list(extracted_routing.keys())}"
                )

            # 2. Extract routing hints from subtask params (if PKG embeds them there)
            # Strategy: Top-level routing wins, then aggregate from subtasks
            # For specialization: prefer first non-empty (not accumulation)
            # For skills: merge with max intensity (accumulation is intentional)
            for st in subtasks:
                if isinstance(st, dict):
                    subtask_params = st.get("params", {})
                    if isinstance(subtask_params, dict):
                        subtask_routing = subtask_params.get("routing", {})
                        if isinstance(subtask_routing, dict):
                            # Specialization: prefer first non-empty (don't overwrite if already set)
                            if subtask_routing.get(
                                "required_specialization"
                            ) and not extracted_routing.get("required_specialization"):
                                extracted_routing["required_specialization"] = (
                                    subtask_routing["required_specialization"]
                                )
                            if subtask_routing.get(
                                "specialization"
                            ) and not extracted_routing.get("specialization"):
                                extracted_routing["specialization"] = subtask_routing[
                                    "specialization"
                                ]
                            # Skills: merge with max intensity (accumulation is intentional)
                            if subtask_routing.get("skills"):
                                existing_skills = extracted_routing.get("skills", {})
                                merged_skills = {}
                                for skill, val in {**existing_skills, **(subtask_routing["skills"] or {})}.items():
                                    merged_skills[skill] = max(
                                        existing_skills.get(skill, 0.0),
                                        float(subtask_routing["skills"].get(skill, 0.0))
                                    )
                                extracted_routing["skills"] = merged_skills

            # IMPORTANT: "steps" is the canonical field expected downstream.
            # Each step should be a dict with at minimum {"task": {...}}.
            # Embed routing hints into each step's task.params.routing
            steps = []
            for st in subtasks:
                if isinstance(st, dict):
                    # Convert PKG subtask -> executable task dict.
                    # If capabilities registry is available, use it; otherwise fall back
                    # to passing the raw subtask through (legacy behavior).
                    if cap_registry and hasattr(cap_registry, "build_step_task_from_subtask"):
                        try:
                            step_task = cap_registry.build_step_task_from_subtask(st)
                        except Exception:
                            step_task = st
                    else:
                        step_task = st

                    # Ensure step has proper structure: {"task": {...}}
                    step = {"task": dict(step_task)}

                    # Ensure task has params dict
                    task_params = step["task"].setdefault("params", {})

                    # CRITICAL: Preserve params.executor from capability registry (for JIT agent spawning)
                    # CapabilityRegistry.build_step_task_from_subtask() creates params.executor with:
                    # - executor.specialization
                    # - executor.behaviors (for Behavior Plugin System)
                    # - executor.behavior_config (for Behavior Plugin System)
                    # This must be preserved for OrganismCore._ensure_agent_handle() to extract behaviors
                    step_executor = step_task.get("params", {}).get("executor")
                    if isinstance(step_executor, dict) and step_executor:
                        task_params["executor"] = dict(step_executor)  # Preserve executor hints

                    # Embed routing hints into step.task.params.routing
                    # Merge strategy: PKG-extracted routing takes precedence over subtask routing
                    step_routing = task_params.setdefault("routing", {})
                    
                    # First: Apply any existing routing from the subtask (lower precedence)
                    if isinstance(step_task.get("params", {}).get("routing"), dict):
                        step_routing.update(step_task["params"]["routing"])
                    
                    # Second: Apply extracted routing from PKG (higher precedence - overwrites subtask)
                    if extracted_routing:
                        step_routing.update(extracted_routing)
                    
                    task_params["routing"] = step_routing

                    steps.append(step)
                else:
                    # object-like fallback
                    steps.append({"task": getattr(st, "task", st)})

            # Always include routing key (even if empty) for downstream consistency
            # Preserve metadata and semantic_context from PKG output for enrichment
            proto_plan = {
                "version": version,
                "steps": steps,
                "edges": dag,
                "routing": extracted_routing or {},  # Always present, even if empty
                "metadata": res.get("metadata", {}) or {},  # Preserve PKG metadata
            }
            
            # Preserve semantic_context if PKG provides it (for Unified Memory enrichment)
            if "semantic_context" in res:
                proto_plan["semantic_context"] = res["semantic_context"]

            # Log routing status
            if extracted_routing:
                required_spec = extracted_routing.get("required_specialization")
                specialization = extracted_routing.get("specialization")

                # Positive confirmation signal: INFO log when PKG is active and routing is found
                logger.info(
                    "[PKG] Active policy snapshot=%s, routing=%s",
                    version or "unknown",
                    required_spec or specialization or "none",
                )

                logger.debug(
                    f"[PKG] Embedded routing into proto_plan: "
                    f"required_specialization={required_spec}, "
                    f"specialization={specialization}"
                )
            else:
                logger.debug(
                    "[PKG] No routing hints found in PKG output. "
                    "Downstream routing extraction will fall back to baseline intent."
                )

            # Verification: Log final proto_plan structure
            logger.debug(
                f"[PKG] Proto-plan structure: version={proto_plan.get('version')}, "
                f"steps_count={len(proto_plan.get('steps', []))}, "
                f"has_routing={bool(proto_plan.get('routing'))}, "
                f"edges_count={len(proto_plan.get('edges', []))}"
            )

            return proto_plan

        # Return cached RouteConfig if available, otherwise build and cache
        if self._cached_route_config is None:
            self._cached_route_config = RouteConfig(
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
        
        return self._cached_route_config

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
                # Use configured organism timeout instead of passed timeout parameter
                organism_timeout = float(self.organism_timeout_s)
                res = await self.organism_client.post(
                    "/route-and-execute",
                    json={"task": payload},
                    headers=headers,
                    timeout=organism_timeout,
                )

                # 4. Handle Result - OrganismService now returns canonical envelope directly
                if isinstance(res, dict):
                    # Normalize to ensure canonical format (idempotent)
                    result_envelope = normalize_envelope(
                        res,
                        task_id=payload.get("task_id") or "unknown",
                        path="coordinator_organism_execute"
                    )
                    
                    # STRATEGY: Look for executing organ in canonical envelope
                    # Priority A: meta.routing_decision.selected_organ_id (The official telemetry)
                    # Priority B: payload.meta.routing_decision.selected_organ_id (nested in payload)
                    # Priority C: Fallback to the requested organ_id
                    
                    meta = result_envelope.get("meta", {})
                    payload_data = result_envelope.get("payload", {})
                    payload_meta = payload_data.get("meta", {}) if isinstance(payload_data, dict) else {}
                    
                    final_organ = (
                        meta.get("routing_decision", {}).get("selected_organ_id")
                        or payload_meta.get("routing_decision", {}).get("selected_organ_id")
                        or (payload_data.get("organ_id") if isinstance(payload_data, dict) else None)
                        or organ_id
                    )

                    # Add organ_id to canonical envelope meta (preserves canonical structure)
                    if "meta" not in result_envelope:
                        result_envelope["meta"] = {}
                    result_envelope["meta"]["organ_id"] = final_organ
                    
                    # Also add to payload.meta if payload is a dict (for backward compatibility)
                    if isinstance(payload_data, dict):
                        if "meta" not in payload_data:
                            payload_data["meta"] = {}
                        payload_data["meta"]["organ_id"] = final_organ
                        result_envelope["payload"] = payload_data

                    return result_envelope
                
                # Fallback: normalize whatever we got
                return normalize_envelope(
                    res,
                    task_id=payload.get("task_id") or "unknown",
                    path="coordinator_organism_execute"
                )

            except Exception as e:
                logger.error(f"Organism execution failed for {organ_id}: {e}")
                # Return canonical envelope format
                task_id = payload.get("task_id") or "unknown"
                return make_envelope(
                    task_id=task_id,
                    success=False,
                    error=str(e),
                    error_type="organism_execution_error",
                    payload={"organ_id": organ_id},
                    path="coordinator_organism_execute",
                )

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
            coordinator=self,  # Pass coordinator reference for embedding enqueue
            enable_consolidation=True,  # Enable Phase 2 result consolidation
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

        response = AnomalyTriageResponse(
            agent_id=agent_id,
            anomalies={},
            reason=reason,
            decision_kind={
                "result": {"action": "escalate" if should_escalate else "hold"}
            },
            correlation_id=cid,
            escalated=should_escalate,
        )
        # Convert to dict and normalize to canonical format
        response_dict = response.model_dump() if hasattr(response, "model_dump") else dict(response)
        return normalize_envelope(
            response_dict,
            task_id=f"triage_{agent_id}",
            path="coordinator_anomaly_triage",
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
            return make_envelope(
                task_id=f"tune_callback_{payload.job_id}",
                success=True,
                payload={"job_id": payload.job_id, "status": payload.status},
                path="coordinator_tune_callback",
            )
        except Exception as e:
            logger.error(f"Callback processing failed: {e}")
            return make_envelope(
                task_id=f"tune_callback_{payload.job_id if 'payload' in locals() else 'unknown'}",
                success=False,
                error=str(e),
                error_type="tune_callback_error",
                path="coordinator_tune_callback",
            )

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
        """
        Fast-path embedding enqueue for immediate task processing.
        
        This is the first layer of the three-layer safety system:
        1. Fast Path (this method): Immediate enqueue upon task creation
        2. Reliability Layer (Outbox): Retries if fast path fails
        3. Safety Net (Backfill): Catches tasks that slipped through
        
        Uses the new 1024d task embedding worker architecture with proper
        deduplication and non-blocking queue operations.
        """
        try:
            from seedcore.graph.task_embedding_worker import enqueue_task_embedding_job

            # Try twice with a small backoff if the queue is full
            # The queue operations should be sub-millisecond, so 1.0s timeout is safe
            for attempt in range(2):
                try:
                    success = await asyncio.wait_for(
                        enqueue_task_embedding_job(
                            self.runtime_ctx, task_id, reason=reason
                        ),
                        timeout=1.0,  # Reduced from 2.0; queue ops should be sub-millisecond
                    )
                    if success:
                        return True
                except asyncio.TimeoutError:
                    logger.warning(
                        f"Embedding queue full, attempt {attempt+1} timed out for task {task_id}"
                    )
                except Exception as e:
                    logger.error(f"Error enqueuing task {task_id} (attempt {attempt+1}): {e}")
                
                # Small backoff between retries
                if attempt < 1:  # Don't sleep after the last attempt
                    await asyncio.sleep(0.1)
            
            return False
        except ImportError as e:
            logger.critical(
                f"Deployment Error: task_embedding_worker not found! {e}. "
                "This indicates a broken deployment or missing module."
            )
            return False
        except Exception as e:
            logger.warning(f"Fast-embed failed for task {task_id}: {e}")
            return False

    async def _task_outbox_flusher_loop(self):
        """
        Reliability Layer: Transactional Outbox Pattern for 1024d embeddings.
        
        This is the second layer of the three-layer safety system:
        1. Fast Path: Immediate enqueue upon task creation (_enqueue_task_embedding_now)
        2. Reliability Layer (this method): Retries if fast path fails or pod crashes
        3. Safety Net: Backfill loop catches tasks that slipped through (in worker)
        
        Uses FOR UPDATE SKIP LOCKED to enable concurrent processing across multiple
        Coordinator pods without contention. Each pod claims different rows atomically.
        
        Production Tip: The claim_pending_nim_task_embeds method uses SELECT ... FOR UPDATE
        SKIP LOCKED, allowing multiple Coordinator pods to process different outbox rows
        concurrently without fighting over the same events.
        """
        while True:
            try:
                if self._session_factory:
                    async with self._session_factory() as s:
                        async with s.begin():
                            # Claim pending events with row-level locking (SKIP LOCKED)
                            # This allows multiple Coordinator pods to process different rows concurrently
                            rows = await self.outbox_dao.claim_pending_nim_task_embeds(
                                s, limit=50
                            )
                            for row in rows:
                                tid = json.loads(row["payload"])["task_id"]
                                if await self._enqueue_task_embedding_now(
                                    tid, "outbox"
                                ):
                                    # Successfully enqueued - remove from outbox
                                    await self.outbox_dao.delete(s, row["id"])
                                else:
                                    # Failed to enqueue - backoff for retry
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
        and one-off warmups (Drift Detector, PKG Manager).
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

        # 3.5. Initialize PKG Manager (if not already initialized)
        try:
            from ..ops.pkg import initialize_global_pkg_manager, PKGClient
            from ..database import get_async_pg_session_factory, get_async_redis_client
            
            pkg_mgr = get_global_pkg_manager()
            if not pkg_mgr:
                # Initialize PKG manager with database client
                session_factory = get_async_pg_session_factory()
                pkg_client = PKGClient(session_factory)
                redis_client = await get_async_redis_client()
                await initialize_global_pkg_manager(pkg_client, redis_client)
                logger.info("✅ PKG Manager initialized and ready")
            else:
                logger.debug("PKG Manager already initialized")
        except Exception as e:
            logger.warning(f"⚠️ PKG Manager initialization failed (non-fatal): {e}")
            # Continue without PKG - system will use fallback routing

        # 4. Launch The Infinite Loop (Maintenance)
        # This runs forever to flush the outbox (Reliability Layer)
        t_outbox = asyncio.create_task(
            self._task_outbox_flusher_loop(), name="loop_outbox"
        )
        self._bg_tasks.append(t_outbox)
        
        # 4.5. Start the task embedding worker (consumes from queue)
        # This is the background consumer that processes embedding jobs from the queue
        try:
            from seedcore.graph.task_embedding_worker import task_embedding_worker
            
            t_worker = asyncio.create_task(
                task_embedding_worker(self.runtime_ctx), name="task_embedding_worker"
            )
            self._bg_tasks.append(t_worker)
            logger.info("✅ Task embedding worker started")
        except ImportError as e:
            logger.warning(f"⚠️ Task embedding worker not available: {e}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to start task embedding worker: {e}")
        
        # 4.6. Start the backfill loop (Safety Net)
        # This catches tasks that slipped through the cracks (e.g., direct DB imports)
        try:
            from seedcore.graph.task_embedding_worker import task_embedding_backfill_loop
            
            t_backfill = asyncio.create_task(
                task_embedding_backfill_loop(self.runtime_ctx), name="task_embedding_backfill"
            )
            self._bg_tasks.append(t_backfill)
            logger.info("✅ Task embedding backfill loop started")
        except ImportError as e:
            logger.warning(f"⚠️ Task embedding backfill not available: {e}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to start task embedding backfill: {e}")

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
        """Warmup drift detector and embedder in background."""
        import random
        
        # Warmup embedder in background (non-blocking)
        try:
            from ..coordinator.core.execute import _get_global_embedder
            embedder = _get_global_embedder()
            if embedder:
                # Trigger lazy initialization by calling _ensure()
                # This will initialize Gemini/NIM/SentenceTransformer in background
                logger.info("🔥 Warming up embedder in background...")
                embedder._ensure()  # Synchronous but fast (just config check)
                # Optionally trigger a dummy embed to fully warm up the model
                # This happens asynchronously, so it won't block
                logger.info("✅ Embedder warmup initiated (will complete in background)")
        except Exception as e:
            logger.warning(f"⚠️ Embedder warmup failed (non-fatal): {e}")

        await asyncio.sleep(random.uniform(2.0, 5.0))
        try:
            if await self.ml_client.is_healthy():
                await self.ml_client.warmup_drift_detector(["warmup"])
        except Exception:
            pass

    async def health(self):
        return {"status": "healthy", "tier": "0"}

    async def ready(self):
        """
        Readiness check including background tasks and optional vendor integrations.

        Returns:
            Dict with readiness status and dependency information
        """
        deps = {}
        all_ready = self._bg_started

        # Background tasks status
        deps["background_tasks"] = "started" if self._bg_started else "not_started"

        # Optional vendor integrations (non-blocking for overall readiness)
        try:
            from seedcore.config.tuya_config import TuyaConfig

            tuya_config = TuyaConfig()
            deps["tuya"] = "enabled" if tuya_config.enabled else "disabled"
        except Exception as e:
            # Tuya config check failed - mark as unavailable but don't block readiness
            deps["tuya"] = f"unavailable: {e}"

        return {"ready": all_ready, "deps": deps}

    async def get_metrics(self):
        return self.metrics.get_metrics()

    async def get_pkg_status(self):
        """
        Get PKG evaluator status for debugging/verification.

        Never throws - always returns a safe response even if PKG is half-initialized.
        """
        try:
            status = self._verify_pkg_status()
            # Ensure "enabled" field is present for consistency
            status["enabled"] = status.get("active", False)
            return status
        except Exception as e:
            # Extra safety net - should never happen since _verify_pkg_status catches exceptions
            logger.warning(f"[PKG] Status check failed unexpectedly: {e}")
            return {
                "enabled": False,
                "active": False,
                "manager_exists": False,
                "version": None,
                "engine_type": None,
                "error": str(e),
            }

    async def get_predicate_status(self):
        """
        Get predicate router status.

        Note: predicate_config is not part of the current PKG-first architecture.
        PKG policy evaluation replaces predicate-based routing.
        """
        return {
            "rules": 0,
            "note": "predicate_config not enabled in PKG-first architecture. "
            "PKG policy evaluation handles routing decisions.",
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
            "PKG policy evaluation handles routing decisions.",
        }

    def _normalize(self, x):
        return normalize_string(x)

    def _norm_domain(self, x):
        return normalize_domain(x)

    def _static_route_fallback(self, t, d):
        return static_route_fallback(t, d)

    def _get_job_state(self, jid):
        return self.storage.get(f"job:{jid}")

    def _verify_pkg_status(self) -> Dict[str, Any]:
        """
        Verify PKG evaluator status (for debugging/testing).

        Never throws - always returns a safe response even if PKG is half-initialized.

        Returns:
            Dictionary with PKG status information:
            - enabled: bool - whether PKG is enabled and active (alias for "active")
            - active: bool - whether PKG evaluator is available
            - version: str - evaluator version if available
            - engine_type: str - engine type if available
            - manager_exists: bool - whether PKG manager exists
            - error: Optional[str] - error message if status check failed
        """
        try:
            pkg_mgr = get_global_pkg_manager()
            manager_exists = pkg_mgr is not None

            if not manager_exists:
                return {
                    "enabled": False,
                    "active": False,
                    "manager_exists": False,
                    "version": None,
                    "engine_type": None,
                    "error": "PKG manager not available",
                }

            evaluator = pkg_mgr.get_active_evaluator()
            if not evaluator:
                return {
                    "enabled": False,
                    "active": False,
                    "manager_exists": True,
                    "version": None,
                    "engine_type": None,
                    "error": "PKG manager exists but no active evaluator",
                }

            version = getattr(evaluator, "version", "unknown")
            engine_type = getattr(evaluator, "engine_type", "unknown")

            return {
                "enabled": True,
                "active": True,
                "manager_exists": True,
                "version": version,
                "engine_type": engine_type,
                "error": None,
            }
        except Exception as e:
            return {
                "enabled": False,
                "active": False,
                "manager_exists": False,
                "version": None,
                "engine_type": None,
                "error": str(e),
            }

    async def capability_monitor_status(self):
        """Get status of capability monitor."""
        if self._capability_monitor is None:
            return {
                "enabled": False,
                "running": False,
                "error": "CapabilityMonitor not initialized",
            }
        
        stats = self._capability_monitor.get_stats()
        return {
            "enabled": True,
            "running": stats.get("is_running", False),
            "stats": stats,
        }

    async def start_capability_monitor_endpoint(self):
        """Manually start capability monitor."""
        await self._start_capability_monitor()
        return {"success": True, "message": "CapabilityMonitor startup initiated"}


# Deployment Bind
coordinator_deployment = Coordinator.bind()
