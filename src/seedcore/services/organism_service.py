#!/usr/bin/env python3
"""
Organism Serve Deployment (FastAPI + Ray Serve)
services/organism_service.py
"""

from __future__ import annotations

import os
import time
import asyncio
import uuid
import traceback
from typing import Dict, Any, Optional

import ray  # pyright: ignore[reportMissingImports]
from ray import serve  # pyright: ignore[reportMissingImports]
from fastapi import FastAPI, HTTPException, status  # pyright: ignore[reportMissingImports]

# SeedCore Imports
from seedcore.organs.organism_core import OrganismCore
from seedcore.organs.router import RoutingDirectory
from seedcore.models import TaskPayload
from seedcore.models.organism import (
    OrganismResponse,
    OrganismStatusResponse,
    RouterDecisionResponse,
    RouteOnlyRequest,
    RouteAndExecuteRequest,
)
from seedcore.logging_setup import ensure_serve_logger, setup_logging

# --- Configuration ---
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))

# Configure logging
setup_logging(app_name="seedcore.organism_service.driver")
logger = ensure_serve_logger("seedcore.organism_service", level="DEBUG")

app = FastAPI(title="SeedCore Organism Service", version="2.0.0")


# --------------------------------------------------------------------------
# Ray Serve Deployment: Organism Manager
# --------------------------------------------------------------------------
@serve.deployment(
    name="OrganismService", health_check_period_s=10, health_check_timeout_s=30
)
@serve.ingress(app)
class OrganismService:
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize the service shell.
        Initialization is triggered by bootstrap or can be auto-started via env var.
        """
        logger.info("🚀 Creating OrganismService instance...")
        self.config = config or {}

        # Core Components
        # Pass config to OrganismCore so it's available during initialization
        self.organism_core = OrganismCore(config=self.config)
        self.router: Optional[RoutingDirectory] = None

        # State Management
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._init_task: Optional[asyncio.Task] = None
        
        # Init error tracking
        self._init_error: Optional[str] = None
        self._init_error_trace: Optional[str] = None
        self._init_started_at: Optional[float] = None
        self._init_finished_at: Optional[float] = None

        # Auto-init is opt-in (disabled by default to allow bootstrap to complete first)
        AUTO_INIT = os.getenv("SEEDCORE_AUTO_INIT", "false").lower() == "true"
        if AUTO_INIT:
            logger.info("🔧 AUTO_INIT enabled - starting initialization immediately")
            self._start_init_if_needed()
        else:
            logger.info("✅ OrganismService created (waiting for manual initialization)")

    def _start_init_if_needed(self) -> None:
        """Start (or restart) init task if not initialized and no active task running."""
        if self._initialized:
            return
        if self._init_task is None or self._init_task.done():
            self._init_error = None
            self._init_error_trace = None
            self._init_started_at = time.time()
            self._init_finished_at = None
            loop = asyncio.get_running_loop()
            self._init_task = loop.create_task(self._lazy_init())
            logger.info("🔄 Starting initialization task...")

    async def _lazy_init(self):
        """
        Idempotent initialization logic.
        Safe to call multiple times; only runs once.
        """
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return
            try:
                logger.info("⚙️  Running initialization sequence...")
                # 1. Initialize Core (Parallelized in previous step)
                await self.organism_core.initialize_organism()

                # 2. Initialize Router
                # Config is passed down if needed
                self.router = RoutingDirectory(organism=self.organism_core)

                self._initialized = True
                self._init_finished_at = time.time()
                logger.info("✅ Organism and Router fully initialized")

            except Exception as e:
                self._init_error = f"{type(e).__name__}: {e}"
                self._init_error_trace = traceback.format_exc()
                self._init_finished_at = time.time()
                logger.critical(f"❌ Organism init failed: {self._init_error}", exc_info=True)
                # We don't raise here to keep the actor alive for retries
                # but readiness checks will fail.

    async def _ensure_initialized(self, timeout: float = 180.0):
        """
        Barrier method: Waits for initialization to complete.
        Call this at the start of every business-critical endpoint.
        Automatically triggers init if it hasn't started or previously failed.
        """
        if self._initialized:
            return

        # Start init if it hasn't started or previously failed
        self._start_init_if_needed()

        # Wait for init task
        if self._init_task and not self._init_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._init_task), timeout=timeout)
            except asyncio.TimeoutError:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Service is still initializing (timeout={timeout}s)",
                )

        if not self._initialized:
            detail = self._init_error or "Service initialization failed (Check logs)"
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=detail,
            )

    async def reconfigure(self, config: dict | None = None):
        """Update config and trigger re-init if needed without blocking."""
        logger.info(f"⏳ Reconfigure called: {config}")
        self.config = config or {}

        # Propagate config to router if it exists
        if self.router and hasattr(self.router, "update_config"):
            self.router.update_config(self.config)

        # If failed previously or not started, try again
        if not self._initialized and (
            self._init_task is None or self._init_task.done()
        ):
            loop = asyncio.get_running_loop()
            self._init_task = loop.create_task(self._lazy_init())

        logger.info("🔁 Reconfigure applied")

    # --- Health and Status Endpoints ---

    def check_health(self):
        """Ray Serve Health Check."""
        # Optional: Fail health check if init crashed hard
        # For now, we return healthy if the actor is alive,
        # allowing /health endpoint to report "initializing" status.
        pass

    @app.get("/health")
    async def health(self):
        health_data = {
            "status": "healthy" if self._initialized else "initializing",
            "service": "OrganismService",
            "organism_initialized": self._initialized,
            "ray_namespace": RAY_NAMESPACE,
        }
        # Include init error if initialization failed (helps with debugging)
        if self._init_error:
            health_data["init_error"] = self._init_error
        return health_data

    @app.get("/init-status")
    async def init_status(self):
        """Get detailed initialization status for debugging."""
        status_data = {
            "initialized": self._initialized,
            "init_started_at": self._init_started_at,
            "init_finished_at": self._init_finished_at,
            "init_task_done": (self._init_task.done() if self._init_task else None),
            "init_error": self._init_error,
        }
        # Include traceback only in debug mode or if explicitly requested
        if os.getenv("SEEDCORE_DEBUG_INIT_TRACE", "false").lower() == "true":
            status_data["init_error_trace"] = self._init_error_trace
        return status_data

    @app.get("/status", response_model=OrganismStatusResponse)
    async def status(self):
        try:
            if not self._initialized:
                return OrganismStatusResponse(
                    status="unhealthy",
                    organism_initialized=False,
                    error="Initializing...",
                )
            org_status = await self.organism_core.get_system_status()
            return OrganismStatusResponse(
                status="healthy",
                organism_initialized=True,
                organism_info=org_status,
            )
        except Exception as e:
            return OrganismStatusResponse(status="unhealthy", error=str(e))

    # --- Organism Management Endpoints ---

    @app.get("/organism-status")
    async def get_organism_status(self):
        """Get detailed status of all organs in the organism."""
        try:
            if not self._initialized:
                return {"error": "Organism not initialized"}

            status = await self.organism_core.get_system_status()
            return {"success": True, "status": status}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.get("/organism-summary")
    async def get_organism_summary(self):
        """Get a summary of the organism's current state."""
        try:
            if not self._initialized:
                return {"error": "Organism not initialized"}

            # Get organism status from the core (same as organism-status endpoint)
            status = await self.organism_core.get_system_status()

            # Create a summary by aggregating the status data
            summary: Dict[str, Any] = {
                "total_organs": 0,
                "organs_by_type": {},
                "agents_by_type": {},
                "overall_health": "healthy",
                "last_updated": time.time(),
            }

            if isinstance(status, list) and status:
                summary["total_organs"] = len(status)

                organs_by_type: Dict[str, int] = {}
                agents_by_type: Dict[str, int] = {}
                overall_healthy = True

                for organ in status:
                    if not isinstance(organ, dict):
                        overall_healthy = False
                        continue

                    otype = organ.get("organ_type", "unknown")
                    agents = int(organ.get("agent_count", 0))
                    organs_by_type[otype] = organs_by_type.get(otype, 0) + 1
                    agents_by_type[otype] = agents_by_type.get(otype, 0) + agents

                    # treat missing status as healthy
                    if organ.get("status", "healthy") != "healthy":
                        overall_healthy = False

                summary["organs_by_type"] = organs_by_type
                summary["agents_by_type"] = agents_by_type
                summary["overall_health"] = "healthy" if overall_healthy else "degraded"

            return {"success": True, "summary": summary}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.post("/initialize-organism")
    async def initialize_organism(self):
        """Manually trigger init (HTTP endpoint)."""
        # Trigger init if needed, then wait for completion
        self._start_init_if_needed()
        timeout = float(os.getenv("ORG_INIT_TIMEOUT_S", "180"))
        await self._ensure_initialized(timeout=timeout)
        return {"success": True, "message": "Organism initialized"}

    async def rpc_initialize_organism(self):
        """
        RPC method for initialization (called via Ray remote handle).
        
        This method starts initialization asynchronously and returns immediately.
        The bootstrap should then poll /health or /init-status to check completion.
        This avoids Ray RPC timeouts for long-running initialization.
        """
        if self._initialized:
            return {"success": True, "message": "Organism already initialized"}

        # Check if initialization is already in progress
        if self._init_task is not None and not self._init_task.done():
            return {
                "success": True, 
                "message": "Initialization already in progress",
                "status": "initializing"
            }

        # Trigger init if needed (will restart if previously failed)
        self._start_init_if_needed()

        # Return immediately - don't wait for completion
        # Bootstrap should poll /health or /init-status to check when done
        return {
            "success": True,
            "message": "Initialization started",
            "status": "initializing"
        }

    @app.post("/janitor/ensure")
    async def ensure_janitor(self):
        """Ensure the Janitor actor exists in the configured namespace."""
        try:
            await self.organism_core._ensure_janitor_actor()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.get("/janitor/ping")
    async def janitor_ping(self):
        """Ping the Janitor actor if available."""
        try:
            ns = RAY_NAMESPACE
            handle = ray.get_actor("seedcore_janitor", namespace=ns)
            # Use direct ray.get instead of _async_ray_get
            pong = await asyncio.to_thread(ray.get, handle.ping.remote())
            return {"success": True, "ping": pong, "namespace": ns}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.post("/shutdown")
    async def shutdown(self):
        """Manually trigger organism shutdown (convenience endpoint)."""
        return await self.shutdown_organism()

    @app.post("/shutdown-organism")
    async def shutdown_organism(self):
        """Manually trigger organism shutdown."""
        try:
            if not self._initialized:
                return {"error": "Organism not initialized"}

            await self.organism_core.shutdown()
            self._initialized = False
            return {"success": True, "message": "Organism shutdown successfully"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- Routing Endpoints ---

    @app.post("/route-only", response_model=RouterDecisionResponse)
    async def route_only(self, request: RouteOnlyRequest):
        """
        Pure routing decision endpoint.
        """
        # 1. Barrier: Wait for init instead of failing immediately
        await self._ensure_initialized()

        try:
            # 2. Input Normalization
            task_payload = self._normalize_payload(request.task or {})

            # 3. Router Logic (Optimized Call)
            decision = await self.router.route_only(payload=task_payload)

            # 4. Response Mapping
            return RouterDecisionResponse(
                agent_id=decision.agent_id,
                organ_id=decision.organ_id,
                reason=decision.reason,
                is_high_stakes=decision.is_high_stakes,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"[route-only] Error: {e}")
            # Fail-Safe Fallback
            return RouterDecisionResponse(
                agent_id="",
                organ_id="meta_control_organ",
                reason="service_error_fallback",
                is_high_stakes=False,
            )

    @app.post("/route-and-execute", response_model=OrganismResponse)
    async def route_and_execute(self, request: RouteAndExecuteRequest):
        """
        Routing + Execution endpoint.
        """
        # 1. Barrier: Wait for init
        await self._ensure_initialized()

        task_dict = request.task or {}
        task_type = task_dict.get("type", "query")
        task_id = task_dict.get("task_id", "unknown")

        logger.info(f"[route-and-execute] 🎯 Task {task_id} ({task_type})")

        try:
            # 2. Normalize
            task_payload = self._normalize_payload(task_dict)

            # 3. Delegation (Optimized Call)
            result = await self.router.route_and_execute(
                payload=task_payload,
                current_epoch=request.current_epoch,
            )

            # 4. Response
            error_msg = result.get("error")
            return OrganismResponse(
                success=not bool(error_msg),
                result=result,
                task_type=task_type,
                error=str(error_msg) if error_msg else None,
            )

        except Exception as e:
            logger.exception(f"[route-and-execute] Critical: {e}")
            return OrganismResponse(
                success=False,
                result={},
                error=f"Service Error: {str(e)}",
                task_type=task_type,
            )

    # --- Evolution and Memory Endpoints ---

    @app.post("/evolve")
    async def evolve(self, proposal: Dict[str, Any]):
        """Execute an evolution operation (split/merge/clone/retire)."""
        try:
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}

            result = await self.organism_core.evolve(proposal)

            # Compute acceptance (best-effort) based on delta_E_realized vs cost
            delta_E_realized = result.get("delta_E_realized")
            cost = result.get("cost", 0.0)
            accepted = bool(
                delta_E_realized is not None
                and cost is not None
                and cost > 0
                and delta_E_realized > cost
            )
            result["accepted"] = accepted
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- State Service Integration ---

    async def rpc_get_all_agent_handles(self) -> Dict[str, Any]:
        """
        Get all agent handles from all organs.

        This method is used by the StateService's AgentAggregator to poll all agents.
        It delegates to the underlying OrganismCore.

        Returns:
            Dict[str, Any]: Dictionary of agent_id -> agent_handle (Ray actor handle)
        """
        if not self._initialized:
            return {}
        return await self.organism_core.get_all_agent_handles()

    # ------------------------------------------------------------------
    #  HELPER METHODS
    # ------------------------------------------------------------------

    def _normalize_payload(self, task_dict: Dict[str, Any]) -> TaskPayload:
        """Robust payload converter."""
        try:
            if hasattr(TaskPayload, "from_db"):
                return TaskPayload.from_db(task_dict)
            return TaskPayload(**task_dict)
        except Exception:
            # Fallback
            return TaskPayload(
                task_id=str(task_dict.get("id") or uuid.uuid4()),
                type=task_dict.get("type") or "unknown_task",
                params=task_dict.get("params") or {},
                description=task_dict.get("description") or "",
                domain=task_dict.get("domain"),
                required_specialization=task_dict.get("required_specialization"),
            )


# Expose a bound app for optional importers (mirrors the original pattern)
organism_app = OrganismService.bind()
