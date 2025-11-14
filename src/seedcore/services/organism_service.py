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
from typing import Dict, Any, List

import ray  # type: ignore[reportMissingImports]
from ray import serve  # type: ignore[reportMissingImports]
from fastapi import FastAPI  # type: ignore[reportMissingImports]
# Ensure project roots are importable (mirrors original file behavior)
import sys
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

from seedcore.logging_setup import ensure_serve_logger, setup_logging
from seedcore.organs.organism_core import OrganismCore
from seedcore.models import TaskPayload
from seedcore.agents.roles.specialization import Specialization
from seedcore.models.organism import (
    BulkResolveRequest,
    BulkResolveResponse,
    BulkResolveResult,
    OrganismResponse,
    OrganismStatusResponse,
    ResolveRouteRequest,
    ResolveRouteResponse,
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
@serve.deployment(
    name="OrganismService",
    num_replicas=int(os.getenv("ORGANISM_REPLICAS", "1")),
    max_ongoing_requests=int(os.getenv("ORGANISM_MAX_ONGOING_REQUESTS", "16")),
    ray_actor_options={
        "num_cpus": float(os.getenv("ORGANISM_NUM_CPUS", "0.2")),
        "num_gpus": float(os.getenv("ORGANISM_NUM_GPUS", "0")),
        "memory": int(os.getenv("ORGANISM_MEMORY", "2147483648")),  # 2GB default
        # Pin replicas to the head node resource set by RAY_OVERRIDE_RESOURCES
        "resources": {"head_node": 0.001},
    },
)
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
                "route_task": "/route-task",
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

    # --- Core Task Handling Endpoint ---

    @app.post("/route-task", response_model=OrganismResponse)
    async def route_task(self, request: Dict[str, Any]):
        """
        route incoming tasks using TaskPayload as the canonical structure.
        Incoming JSON may be directly a TaskPayload or any compatible dict.
        """

        task_id = request.get("task_id") or request.get("id") or "unknown"
        task_type = request.get("type") or "general_query"

        self.logger.info(f"[OrganismService] 🎯 Received task {task_id}")
        self.logger.info(f"[OrganismService] 📋 task_type={task_type}, domain={request.get('domain')}")

        try:
            if not self._initialized:
                return OrganismResponse(
                    success=False,
                    result={},
                    error="Organism not initialized",
                    task_type=task_type,
                )

            # Try to interpret body as TaskPayload
            try:
                task_payload = TaskPayload.from_db(request)
            except Exception:
                self.logger.warning(
                    f"[OrganismService] Falling back to direct TaskPayload construction for {task_id}"
                )
                task_payload = TaskPayload(
                    task_id=str(task_id),
                    type=request.get("type") or "unknown_task",
                    params=request.get("params") or {},
                    description=request.get("description") or "",
                    domain=request.get("domain"),
                    drift_score=float(request.get("drift_score") or 0.0),
                    required_specialization=request.get("required_specialization")
                )

            # Resolve specialization
            spec_str = task_payload.required_specialization
            try:
                specialization = Specialization(spec_str) if spec_str else Specialization.GENERALIST
            except Exception:
                self.logger.warning(
                    f"[OrganismService] Invalid specialization '{spec_str}', defaulting to GENERALIST"
                )
                specialization = Specialization.GENERALIST

            # Execute via organism core
            self.logger.info(
                f"[OrganismService] 🚀 Routing task {task_id} to {specialization.value}"
            )

            result = await self.organism_core.route_task(
                specialization=specialization,
                payload=task_payload,
                metadata=request.get("metadata") or {}
            )

            has_error = "error" in result
            return OrganismResponse(
                success=not has_error,
                result=result,
                task_type=task_type,
                error=result.get("error") if has_error else None,
            )

        except Exception as e:
            self.logger.exception(f"[OrganismService] ❌ Error in task {task_id}: {e}")
            return OrganismResponse(
                success=False,
                result={},
                error=str(e),
                task_type=task_type,
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

    @app.post("/execute-on-organ")
    async def execute_on_organ(self, request: Dict[str, Any]):
        """Execute a task on a specific organ."""
        try:
            start_time = time.time()
            self.logger.info(f"[execute-on-organ] ▶️ request keys={list(request.keys())}")
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}

            organ_id = request.get("organ_id")
            task_raw = request.get("task", {}) or {}
            organ_timeout_s = request.get("organ_timeout_s", 30.0)

            if not organ_id:
                return {"success": False, "error": "organ_id is required"}

            # Add timeout to task if provided
            if isinstance(task_raw, dict):
                raw_timeout = task_raw.get("organ_timeout_s")
                if raw_timeout is not None:
                    organ_timeout_s = raw_timeout

            try:
                task_payload = TaskPayload.from_db(task_raw)
            except Exception as exc:
                self.logger.warning(
                    "[execute-on-organ] TaskPayload.from_db fallback due to %s; attempting direct construction",
                    exc,
                )
                fallback_id = task_raw.get("task_id") or task_raw.get("id") or str(uuid.uuid4())
                task_payload = TaskPayload(
                    task_id=str(fallback_id),
                    type=task_raw.get("type") or "unknown_task",
                    params=task_raw.get("params") or {},
                    description=task_raw.get("description") or "",
                    domain=task_raw.get("domain"),
                    drift_score=float(task_raw.get("drift_score") or 0.0),
                )

            task_id = task_payload.task_id or str(uuid.uuid4())
            if not task_payload.task_id or task_payload.task_id in ("", "None"):
                task_payload = task_payload.copy(update={"task_id": task_id})
            else:
                task_id = task_payload.task_id

            task_data = task_payload.model_dump()

            # Retain any extra keys from the raw task that the payload model doesn't surface
            if isinstance(task_raw, dict):
                for key, value in task_raw.items():
                    if key not in task_data:
                        task_data[key] = value

            task_data["organ_timeout_s"] = organ_timeout_s
            task_data.setdefault("id", task_id)

            self.logger.info(
                "[execute-on-organ] ⏩ organ_id=%s task_id=%s task.type=%s domain=%s priority=%s timeout=%ss",
                organ_id,
                task_id,
                task_payload.type,
                task_payload.domain,
                getattr(task_payload, "priority", None),
                organ_timeout_s,
            )
            # Use existing task_payload for OrganismCore
            result = await self.organism_core.execute_task_on_organ(organ_id, task_payload, task_data.get("metadata"))
            duration = time.time() - start_time
            self.logger.info(
                f"[execute-on-organ] ✅ completed organ_id={organ_id} success={result.get('success', True)} in {duration:.2f}s"
            )
            return {"success": True, **result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.post("/execute-on-random")
    async def execute_on_random(self, request: Dict[str, Any]):
        """Execute a task on a randomly selected organ."""
        try:
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}

            task = request.get("task", {})
            organ_timeout_s = request.get("organ_timeout_s", 30.0)

            # Add timeout to task if provided
            if organ_timeout_s:
                task["organ_timeout_s"] = organ_timeout_s

            # Convert task to TaskPayload for OrganismCore
            task_payload = TaskPayload.from_db(task) if not isinstance(task, TaskPayload) else task
            result = await self.organism_core.execute_task_on_random_organ(task_payload, task.get("metadata"))
            return {"success": True, **result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- Routing Endpoints ---

    @app.post("/resolve-route", response_model=ResolveRouteResponse)
    async def resolve_route(self, request: ResolveRouteRequest):
        """Resolve a single task to its target organ."""
        try:
            start_time = time.time()
            if not self._initialized:
                return {
                    "logical_id": "utility_organ_1",
                    "resolved_from": "fallback",
                    "epoch": "unknown",
                    "error": "Organism not initialized",
                }

            task = request.task
            task_type = task.get("type")
            domain = task.get("domain")
            preferred_logical_id = request.preferred_logical_id
            self.logger.info(
                f"[resolve-route] ▶️ task.type={task_type} domain={domain} preferred={preferred_logical_id}"
            )

            # Get current epoch (mock for now)
            current_epoch = "epoch-" + str(int(time.time()))

            # Resolve using specialization-based routing
            # OrganismCore uses specialization → organ mapping instead of routing directory
            try:
                spec = Specialization(task_type.upper()) if task_type else Specialization.GENERALIST
            except (KeyError, ValueError, AttributeError):
                spec = Specialization.GENERALIST
            
            # Get organ from specialization mapping
            spec_map = self.organism_core.map_specializations()
            logical_id = spec_map.get(spec.name, "utility_organ_1")
            resolved_from = "specialization"

            if not logical_id:
                return {
                    "logical_id": "utility_organ_1",
                    "resolved_from": "fallback",
                    "epoch": current_epoch,
                    "error": "No route found",
                }

            # Get instance info if available
            instance_id = None
            if resolved_from in ["preferred", "domain", "task", "default", "specialization"]:
                organ_status = await self.organism_core.get_organ_status(logical_id)
                if organ_status and "instance_id" in organ_status:
                    instance_id = organ_status.get("instance_id")

            duration = time.time() - start_time
            self.logger.info(
                f"[resolve-route] ✅ logical_id={logical_id} from={resolved_from} epoch={current_epoch} instance_id={instance_id} in {duration:.2f}s"
            )
            return {
                "logical_id": logical_id,
                "resolved_from": resolved_from,
                "epoch": current_epoch,
                "instance_id": instance_id,
            }
        except Exception as e:
            self.logger.error(f"Route resolution failed: {e}")
            return {
                "logical_id": "utility_organ_1",
                "resolved_from": "fallback",
                "epoch": "unknown",
                "error": str(e),
            }

    @app.post("/resolve-routes", response_model=BulkResolveResponse)
    async def resolve_routes(self, request: BulkResolveRequest):
        """Resolve multiple tasks to their target organs in one request."""
        try:
            if not self._initialized:
                return {"epoch": "unknown", "results": []}

            # Get current epoch (mock for now)
            current_epoch = "epoch-" + str(int(time.time()))
            results: List[BulkResolveResult] = []

            for item in request.tasks:
                try:
                    # Resolve using specialization-based routing
                    try:
                        spec = Specialization(item.type.upper()) if item.type else Specialization.GENERALIST
                    except (KeyError, ValueError, AttributeError):
                        spec = Specialization.GENERALIST
                    
                    # Get organ from specialization mapping
                    spec_map = self.organism_core.map_specializations()
                    logical_id = spec_map.get(spec.name, "utility_organ_1")
                    resolved_from = "specialization"

                    if not logical_id:
                        results.append(BulkResolveResult(
                            index=item.index, key=item.key, status="unknown_type",
                            epoch=current_epoch, error="No route found",
                        ))
                        continue

                    # Get instance info if available
                    instance_id = None
                    cache_hit = False
                    cache_age_ms = None

                    if resolved_from in ["preferred", "domain", "task", "default", "specialization"]:
                        organ_status = await self.organism_core.get_organ_status(logical_id)
                        if organ_status and "instance_id" in organ_status:
                            instance_id = organ_status.get("instance_id")
                            # Cache info not available in OrganismCore
                            cache_hit = False
                            cache_age_ms = None
                        else:
                            results.append(BulkResolveResult(
                                index=item.index, key=item.key, status="no_active_instance",
                                logical_id=logical_id, epoch=current_epoch,
                                error=f"No active instance for {logical_id}",
                            ))
                            continue

                    results.append(BulkResolveResult(
                        index=item.index, key=item.key, status="ok",
                        logical_id=logical_id, resolved_from=resolved_from,
                        epoch=current_epoch, instance_id=instance_id,
                        cache_hit=cache_hit, cache_age_ms=cache_age_ms,
                    ))

                except Exception as e:
                    results.append(BulkResolveResult(
                        index=item.index, key=item.key, status="error",
                        epoch=current_epoch, error=str(e),
                    ))

            return {"epoch": current_epoch, "results": results}

        except Exception as e:
            self.logger.error(f"Bulk route resolution failed: {e}")
            return {"epoch": "unknown", "results": []}

    @app.get("/routing/rules")
    async def get_routing_rules(self):
        """Get current routing rules."""
        try:
            if not self._initialized:
                return {"error": "Organism not initialized"}

            # OrganismCore uses specialization → organ mapping instead of routing rules
            return {"specialization_map": self.organism_core.map_specializations()}
        except Exception as e:
            return {"error": str(e)}

    @app.put("/routing/rules")
    async def update_routing_rules(self, rules: Dict[str, Any]):
        """Update routing rules."""
        try:
            if not self._initialized:
                return {"error": "Organism not initialized"}

            # OrganismCore uses specialization → organ mapping instead of routing rules
            # Routing is configured via organ configs, not runtime rules
            # Return current mapping as "rules"
            return {"success": True, "rules": {"specialization_map": self.organism_core.map_specializations()}}
        except Exception as e:
            return {"error": str(e)}

    @app.post("/routing/refresh")
    async def refresh_routing_cache(self):
        """Refresh routing cache (useful after epoch rotation)."""
        try:
            if not self._initialized:
                return {"error": "Organism not initialized"}

            # OrganismCore doesn't use routing cache - routing is direct specialization → organ mapping
            return {"success": True, "message": "Routing cache cleared (no-op in OrganismCore)"}
        except Exception as e:
            return {"error": str(e)}

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

    async def get_all_agent_handles(self) -> Dict[str, Any]:
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
