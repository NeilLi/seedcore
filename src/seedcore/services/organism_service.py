#!/usr/bin/env python3
"""
Organism Serve Deployment (FastAPI + Ray Serve)
services/organism_service.py

This module defines the FastAPI app, pydantic models, and the Serve deployment
class that exposes the organism manager over HTTP via Ray Serve.
"""

import os
import time
import asyncio
import uuid
from typing import Dict, Any

import ray  # type: ignore[reportMissingImports]
from ray import serve  # type: ignore[reportMissingImports]
from fastapi import FastAPI, HTTPException, status  # type: ignore[reportMissingImports]
# Ensure project roots are importable (mirrors original file behavior)
import sys
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

from seedcore.logging_setup import ensure_serve_logger, setup_logging
from seedcore.organs.organism_core import OrganismCore
from seedcore.models import TaskPayload
from seedcore.models.organism import (
    OrganismResponse,
    OrganismStatusResponse,
    RouterDecisionResponse,
    RouteOnlyRequest,
    RouteAndExecuteRequest,
)

# Configure logging for driver process (script that invokes serve.run)
setup_logging(app_name="seedcore.organism_service.driver")
logger = ensure_serve_logger("seedcore.organism_service", level="DEBUG")

# --- Configuration ---
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore-dev")


# --- FastAPI app for ingress ---
app = FastAPI(title="SeedCore Organism Service", version="1.0.0")


# --------------------------------------------------------------------------
# Ray Serve Deployment: Organism Manager as Serve App
# --------------------------------------------------------------------------
@serve.deployment(name="OrganismService")
@serve.ingress(app)
class OrganismService:
    def __init__(self):
        setup_logging(app_name="seedcore.organism_service.replica")
        self.logger = ensure_serve_logger("seedcore.organism_service", level="DEBUG")

        self.logger.info("🚀 Creating OrganismService instance...")
        self.organism_core = OrganismCore()
        self._initialized = False
        self._init_task = None
        self._init_lock = asyncio.Lock()
        self.logger.info("✅ OrganismService instance created (will init in background)")

    async def _lazy_init(self):
        # prevent duplicate inits
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            try:
                await self.organism_core.initialize_organism()
                self._initialized = True
                self.logger.info("✅ Organism initialized (background)")
            except Exception:
                self.logger.exception("❌ Organism init failed")


    async def reconfigure(self, config: dict | None = None):
        """Never block here — just kick off (or reuse) the background task."""
        self.logger.info("⏳ reconfigure called")
        if not self._initialized and (self._init_task is None or self._init_task.done()):
            # schedule but DO NOT await
            loop = asyncio.get_running_loop()
            self._init_task = loop.create_task(self._lazy_init())
        self.logger.info("🔁 reconfigure returned without blocking")


    # --- Health and Status Endpoints ---

    @app.get("/health")
    async def health(self):
        """Health check endpoint."""
        return {
            "status": "healthy" if self._initialized else "initializing",
            "service": "organism-manager",
            "route_prefix": "/organism",
            "ray_namespace": RAY_NS,
            "ray_address": RAY_ADDR,
            "organism_initialized": self._initialized,
            "endpoints": {
                "health": "/health",
                "status": "/status",
                "route_only": "/route-only",
                "route_and_execute": "/route-and-execute",
                "get_organism_status": "/organism-status",
                "get_organism_summary": "/organism-summary",
                "initialize": "/initialize",
                "initialize_organism": "/initialize-organism",
                "shutdown": "/shutdown",
                "shutdown_organism": "/shutdown-organism",
            },
        }

    @app.get("/status", response_model=OrganismStatusResponse)
    async def status(self):
        """Get detailed status of the organism manager."""
        try:
            if not self._initialized:
                return OrganismStatusResponse(
                    status="unhealthy",
                    organism_initialized=False,
                    error="Organism not initialized",
                )

            # Get organism status from the core
            org_status = await self.organism_core.get_system_status()

            return OrganismStatusResponse(
                status="healthy",
                organism_initialized=True,
                organism_info=org_status,
            )
        except Exception as e:
            return OrganismStatusResponse(
                status="unhealthy",
                organism_initialized=self._initialized,
                error=str(e),
            )

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

    @app.post("/initialize")
    async def initialize(self):
        """Manually trigger organism initialization (convenience endpoint)."""
        return await self.initialize_organism()

    @app.post("/initialize-organism")
    async def initialize_organism(self):
        """Manually trigger organism initialization."""
        try:
            if self._initialized:
                return {"success": True, "message": "Organism already initialized"}

            await self.organism_core.initialize_organism()
            self._initialized = True
            return {"success": True, "message": "Organism initialized successfully"}
        except Exception as e:
            return {"success": False, "error": str(e)}

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
            ns = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
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
        Pure routing. Returns RouterDecision.
        
        Canonical API for Dispatcher, Coordinator, and external IoT/human/robot services.
        Used when callers need routing decisions but not immediate execution.
        """
        try:
            # 1) Ensure organism + router exist and are initialized
            # Note: router is created in OrganismCore.initialize_organism() (line 351),
            # not in __init__(), so we must check both _initialized and router existence
            if not self._initialized or not getattr(self, "organism_core", None):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="OrganismCore not initialized",
                )
            
            # Router is only created during initialize_organism(), so check it exists
            router = getattr(self.organism_core, "router", None)
            if router is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Router not available",
                )
            
            # 2) Normalize task → TaskPayload
            task_dict = request.task or {}
            try:
                task_payload = TaskPayload.from_db(task_dict)
            except Exception:
                self.logger.warning(
                    "[route-only] Falling back to direct TaskPayload construction"
                )
                task_payload = TaskPayload(
                    task_id=str(
                        task_dict.get("task_id")
                        or task_dict.get("id")
                        or uuid.uuid4()
                    ),
                    type=task_dict.get("type") or "unknown_task",
                    params=task_dict.get("params") or {},
                    description=task_dict.get("description") or "",
                    domain=task_dict.get("domain"),
                    drift_score=float(task_dict.get("drift_score") or 0.0),
                    required_specialization=task_dict.get("required_specialization"),
                )
            
            # 3) Ask router for a decision
            decision = await router.route_only(
                payload=task_payload,
                current_epoch=request.current_epoch,
            )
            
            # 4) Map to API response model
            return RouterDecisionResponse(
                agent_id=decision.agent_id,
                organ_id=decision.organ_id,
                reason=decision.reason,
                is_high_stakes=decision.is_high_stakes,
            )
        
        except HTTPException:
            # Pass through explicit HTTP errors
            raise
        except Exception as e:
            self.logger.exception(f"[route-only] Error: {e}")
            # Soft fallback if you really want a decision shape on error
            return RouterDecisionResponse(
                agent_id="",
                organ_id="meta_control_organ",  # Reasonable fallback from config
                reason="error",
                is_high_stakes=False,
            )

    @app.post("/route-and-execute", response_model=OrganismResponse)
    async def route_and_execute(self, request: RouteAndExecuteRequest):
        """
        Routing + execution convenience method.
        
        Calls:
            1. route_only()
            2. organism.execute_on_agent()
        
        Used by simple endpoints, cognitive client, demo workflows,
        and basic actuator interactions (IoT, robots, external systems).
        
        This is a convenience API that combines routing and execution in one call.
        For more control, use route_only() followed by execute_on_agent() separately.
        """
        try:
            # 1) Ensure organism + router exist and are initialized
            # Note: router is created in OrganismCore.initialize_organism() (line 351),
            # not in __init__(), so we must check both _initialized and router existence
            if not self._initialized or not getattr(self, "organism_core", None):
                return OrganismResponse(
                    success=False,
                    result={},
                    error="OrganismCore not initialized",
                    task_type=None,
                )
            
            # Router is only created during initialize_organism(), so check it exists
            router = getattr(self.organism_core, "router", None)
            if router is None:
                return OrganismResponse(
                    success=False,
                    result={},
                    error="Router not available",
                    task_type=None,
                )
            
            # 2) Normalize task → TaskPayload
            task_dict = request.task or {}
            task_id = task_dict.get("task_id") or task_dict.get("id") or "unknown"
            task_type = task_dict.get("type") or "general_query"
            
            self.logger.info(f"[route-and-execute] 🎯 Received task {task_id}")
            
            try:
                task_payload = TaskPayload.from_db(task_dict)
            except Exception:
                self.logger.warning(
                    f"[route-and-execute] Falling back to direct TaskPayload construction for {task_id}"
                )
                task_payload = TaskPayload(
                    task_id=str(task_id),
                    type=task_type,
                    params=task_dict.get("params") or {},
                    description=task_dict.get("description") or "",
                    domain=task_dict.get("domain"),
                    drift_score=float(task_dict.get("drift_score") or 0.0),
                    required_specialization=task_dict.get("required_specialization"),
                )
            
            # 3) Call router.route_and_execute() which handles both routing and execution
            result = await router.route_and_execute(
                payload=task_payload,
                current_epoch=request.current_epoch,
            )
            
            # 4) Check for errors and wrap in response
            has_error = "error" in result
            return OrganismResponse(
                success=not has_error,
                result=result,
                task_type=task_type,
                error=result.get("error") if has_error else None,
            )
        
        except Exception as e:
            task_dict = getattr(request, "task", {}) or {}
            task_id = task_dict.get("task_id") or task_dict.get("id") or "unknown"
            task_type = task_dict.get("type") or "general_query"
            self.logger.exception(f"[route-and-execute] ❌ Error in task {task_id}: {e}")
            return OrganismResponse(
                success=False,
                result={},
                error=str(e),
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


# Expose a bound app for optional importers (mirrors the original pattern)
organism_app = OrganismService.bind()
