#!/usr/bin/env python3
"""
Organism Serve Entrypoint for SeedCore
entrypoints/organism_entrypoint.py

This service runs the organism manager (dispatcher + organs) as a Ray Serve deployment,
converting it from plain Ray actors to a proper Serve application with structured
request/response lifecycles, health checks, and integration with Serve's autoscaling.

This fixes the issue where tasks get locked with status=running but never complete
because they're not being processed by a Serve deployment.
"""

import os
import sys
import time
import traceback
import asyncio
import logging
from typing import Dict, Any, Optional

import ray
from ray import serve
from fastapi import FastAPI
from seedcore.utils.ray_utils import ensure_ray_initialized
from pydantic import BaseModel
from typing import List


# Add the project root to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

from seedcore.logging_setup import setup_logging
setup_logging(app_name="seedcore.organism")
logger = logging.getLogger("seedcore.organism")

from seedcore.utils.ray_utils import ensure_ray_initialized

# Import organism components
from seedcore.organs.organism_manager import OrganismManager

# --- Configuration ---
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore-dev")

# Concurrency settings - adjust based on workload characteristics:
# - For I/O-bound work: 8-32 × CPU
# - For CPU-bound work: 1-2 × CPU per replica
# Environment variables:
# - ORGANISM_MAX_ONGOING_REQUESTS: Max concurrent requests (default: 16)
# - ORGANISM_NUM_CPUS: CPU allocation per replica (default: 0.5)

# --- Request/Response Models ---
class OrganismRequest(BaseModel):
    task_type: str
    params: Dict[str, Any] = None
    description: str = None
    domain: str = None
    drift_score: float = None
    app_state: Dict[str, Any] = None

class OrganismResponse(BaseModel):
    success: bool
    result: Dict[str, Any]
    error: Optional[str] = None
    task_type: str = None

class OrganismStatusResponse(BaseModel):
    status: str
    organism_initialized: bool
    organism_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# Routing models
class ResolveRouteRequest(BaseModel):
    task: Dict[str, Any]
    preferred_logical_id: Optional[str] = None

class ResolveRouteResponse(BaseModel):
    logical_id: str
    resolved_from: str
    epoch: str
    instance_id: Optional[str] = None

class BulkResolveItem(BaseModel):
    index: Optional[int] = None  # Optional for key-based de-duplication
    key: Optional[str] = None    # For de-duplication: "type|domain"
    type: str
    domain: Optional[str] = None
    preferred_logical_id: Optional[str] = None

class BulkResolveRequest(BaseModel):
    tasks: List[BulkResolveItem]

class BulkResolveResult(BaseModel):
    index: Optional[int] = None  # Optional for key-based responses
    key: Optional[str] = None    # For de-duplication responses
    logical_id: Optional[str] = None
    resolved_from: Optional[str] = None
    epoch: Optional[str] = None
    instance_id: Optional[str] = None
    status: str = "ok"  # "ok" | "fallback" | "no_active_instance" | "unknown_type" | "error"
    error: Optional[str] = None
    cache_hit: bool = False
    cache_age_ms: Optional[float] = None

class BulkResolveResponse(BaseModel):
    epoch: str
    results: List[BulkResolveResult]

# --- FastAPI app for ingress ---
app = FastAPI(title="SeedCore Organism Service", version="1.0.0")

# --------------------------------------------------------------------------
# Ray Serve Deployment: Organism Manager as Serve App
# --------------------------------------------------------------------------
@serve.deployment(
    name="OrganismManager",
    num_replicas=int(os.getenv("ORGANISM_REPLICAS", "1")),
    max_ongoing_requests=int(os.getenv("ORGANISM_MAX_ONGOING_REQUESTS", "16")),  # More conservative concurrency
    ray_actor_options={
        "num_cpus": float(os.getenv("ORGANISM_NUM_CPUS", "0.5")),
        "num_gpus": float(os.getenv("ORGANISM_NUM_GPUS", "0")),
        "memory": int(os.getenv("ORGANISM_MEMORY", "2147483648")),  # 2GB default
        # Pin replicas to the head node resource set by RAY_OVERRIDE_RESOURCES
        "resources": {"head_node": 0.001},
    },
)

@serve.ingress(app)
class OrganismService:
    def __init__(self):
        logger.info("🚀 Creating OrganismManager instance...")
        self.organism_manager = OrganismManager()
        self._initialized = False
        self._init_task = None
        self._init_lock = asyncio.Lock()
        logger.info("✅ OrganismManager instance created (will init in background)")

    async def _lazy_init(self):
        # prevent duplicate inits
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            try:
                await self.organism_manager.initialize_organism()
                self._initialized = True
                logger.info("✅ Organism initialized (background)")
            except Exception:
                logger.exception("❌ Organism init failed")

    async def reconfigure(self, config: dict = None):
        """Never block here — just kick off (or reuse) the background task."""
        logger.info("⏳ reconfigure called")
        if not self._initialized and (self._init_task is None or self._init_task.done()):
            # schedule but DO NOT await
            loop = asyncio.get_running_loop()
            self._init_task = loop.create_task(self._lazy_init())
        logger.info("🔁 reconfigure returned without blocking")


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
                "handle_task": "/handle-task",
                "get_organism_status": "/organism-status",
                "get_organism_summary": "/organism-summary",
                "initialize": "/initialize",
                "initialize_organism": "/initialize-organism",
                "shutdown": "/shutdown",
                "shutdown_organism": "/shutdown-organism"
            }
        }

    @app.get("/status", response_model=OrganismStatusResponse)
    async def status(self):
        """Get detailed status of the organism manager."""
        try:
            if not self._initialized:
                return OrganismStatusResponse(
                    status="unhealthy",
                    organism_initialized=False,
                    error="Organism not initialized"
                )
            
            # Get organism status from the manager
            org_status = await self.organism_manager.get_organism_status()
            
            return OrganismStatusResponse(
                status="healthy",
                organism_initialized=True,
                organism_info=org_status
            )
        except Exception as e:
            return OrganismStatusResponse(
                status="unhealthy",
                organism_initialized=self._initialized,
                error=str(e)
            )

    # --- Core Task Handling Endpoint ---

    @app.post("/handle-task", response_model=OrganismResponse)
    async def handle_task(self, request: OrganismRequest):
        """
        Handle incoming tasks through the organism manager.
        This is the main endpoint that replaces the plain Ray actor task handling.
        """
        task_id = getattr(request, 'id', 'unknown')
        logger.info(f"[OrganismService] 🎯 Received task {task_id} via HTTP endpoint")
        logger.info(f"[OrganismService] 📋 Task details: type={request.task_type}, domain={request.domain}")
        
        try:
            logger.info(f"[OrganismService] 🔧 Checking organism initialization status: {self._initialized}")
            if not self._initialized:
                logger.error(f"[OrganismService] ❌ Organism not initialized for task {task_id}")
                return OrganismResponse(
                    success=False,
                    result={},
                    error="Organism not initialized",
                    task_type=request.task_type
                )
            
            # Convert request to task format expected by OrganismManager
            ttype = request.task_type or "general_query"
            task = {
                "type": ttype,
                "params": request.params or {},
                "description": request.description or "",
                "domain": request.domain or "general",
                "drift_score": request.drift_score or 0.0
            }
            logger.info(f"[OrganismService] 🔄 Converted request to task format for {task_id}")
            
            # Handle the task through the organism manager
            logger.info(f"[OrganismService] 🚀 Calling organism_manager.handle_incoming_task for {task_id}")
            result = await self.organism_manager.handle_incoming_task(
                task, 
                app_state=request.app_state
            )
            logger.info(f"[OrganismService] ✅ Organism manager completed for {task_id}: success={result.get('success')}")
            
            # Note: API response structure is {"success": ..., "result": { manager_fields... }}
            # Some clients prefer a flat shape, but this maintains compatibility
            return OrganismResponse(
                success=result.get("success", True),
                result=result,
                task_type=request.task_type
            )
            
        except Exception as e:
            return OrganismResponse(
                success=False,
                result={},
                error=str(e),
                task_type=request.task_type
            )

    # --- Organism Management Endpoints ---

    @app.get("/organism-status")
    async def get_organism_status(self):
        """Get detailed status of all organs in the organism."""
        try:
            if not self._initialized:
                return {"error": "Organism not initialized"}
            
            status = await self.organism_manager.get_organism_status()
            return {"success": True, "status": status}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.get("/organism-summary")
    async def get_organism_summary(self):
        """Get a summary of the organism's current state."""
        try:
            if not self._initialized:
                return {"error": "Organism not initialized"}
            
            # Get organism status from the manager (same as organism-status endpoint)
            status = await self.organism_manager.get_organism_status()
            
            # Create a summary by aggregating the status data
            summary = {
                "total_organs": 0,
                "organs_by_type": {},
                "agents_by_type": {},
                "overall_health": "healthy",
                "last_updated": time.time()
            }

            if isinstance(status, list) and status:
                summary["total_organs"] = len(status)

                organs_by_type = {}
                agents_by_type = {}
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
            
            await self.organism_manager.initialize_organism()
            self._initialized = True
            return {"success": True, "message": "Organism initialized successfully"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.post("/janitor/ensure")
    async def ensure_janitor(self):
        """Ensure the Janitor actor exists in the configured namespace."""
        try:
            await self.organism_manager._ensure_janitor_actor()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.get("/janitor/ping")
    async def janitor_ping(self):
        """Ping the Janitor actor if available."""
        try:
            ns = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
            handle = ray.get_actor("seedcore_janitor", namespace=ns)
            pong = await self.organism_manager._async_ray_get(handle.ping.remote(), timeout=5.0)
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
            
            self.organism_manager.shutdown_organism()
            self._initialized = False
            return {"success": True, "message": "Organism shutdown successfully"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.post("/execute-on-organ")
    async def execute_on_organ(self, request: Dict[str, Any]):
        """Execute a task on a specific organ."""
        try:
            start_time = time.time()
            logger.info(f"[execute-on-organ] ▶️ request keys={list(request.keys())}")
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}
            
            organ_id = request.get("organ_id")
            task = request.get("task", {})
            organ_timeout_s = request.get("organ_timeout_s", 30.0)
            
            if not organ_id:
                return {"success": False, "error": "organ_id is required"}
            
            # Add timeout to task if provided
            if organ_timeout_s:
                task["organ_timeout_s"] = organ_timeout_s
            
            logger.info(
                f"[execute-on-organ] ⏩ organ_id={organ_id} task.type={task.get('type')} domain={task.get('domain')} timeout={organ_timeout_s}s"
            )
            result = await self.organism_manager.execute_task_on_organ(organ_id, task)
            duration = time.time() - start_time
            logger.info(
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
            
            result = await self.organism_manager.execute_task_on_random_organ(task)
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
                return {"logical_id": "utility_organ_1", "resolved_from": "fallback", 
                       "epoch": "unknown", "error": "Organism not initialized"}
            
            task = request.task
            task_type = task.get("type")
            domain = task.get("domain")
            preferred_logical_id = request.preferred_logical_id
            logger.info(
                f"[resolve-route] ▶️ task.type={task_type} domain={domain} preferred={preferred_logical_id}"
            )
            
            # Get current epoch (mock for now)
            current_epoch = "epoch-" + str(int(time.time()))
            
            # Resolve using routing directory
            logical_id, resolved_from = await self.organism_manager.routing.resolve(
                task_type, domain, preferred_logical_id, current_epoch
            )
            
            if not logical_id:
                return {"logical_id": "utility_organ_1", "resolved_from": "fallback", 
                       "epoch": current_epoch, "error": "No route found"}
            
            # Get instance info if available
            instance_id = None
            if resolved_from in ["preferred", "domain", "task", "default"]:
                instance = await self.organism_manager.routing._get_active_instance(logical_id, current_epoch)
                if instance:
                    instance_id = instance.get("instance_id")
            
            duration = time.time() - start_time
            logger.info(
                f"[resolve-route] ✅ logical_id={logical_id} from={resolved_from} epoch={current_epoch} instance_id={instance_id} in {duration:.2f}s"
            )
            return {
                "logical_id": logical_id,
                "resolved_from": resolved_from,
                "epoch": current_epoch,
                "instance_id": instance_id
            }
        except Exception as e:
            logger.error(f"Route resolution failed: {e}")
            return {"logical_id": "utility_organ_1", "resolved_from": "fallback", 
                   "epoch": "unknown", "error": str(e)}

    @app.post("/resolve-routes", response_model=BulkResolveResponse)
    async def resolve_routes(self, request: BulkResolveRequest):
        """Resolve multiple tasks to their target organs in one request."""
        try:
            if not self._initialized:
                return {"epoch": "unknown", "results": []}
            
            # Get current epoch (mock for now)
            current_epoch = "epoch-" + str(int(time.time()))
            results = []
            
            for item in request.tasks:
                try:
                    # Resolve using routing directory
                    logical_id, resolved_from = await self.organism_manager.routing.resolve(
                        item.type, item.domain, item.preferred_logical_id, current_epoch
                    )
                    
                    if not logical_id:
                        results.append(BulkResolveResult(
                            index=item.index, key=item.key, status="unknown_type",
                            epoch=current_epoch, error="No route found"
                        ))
                        continue
                    
                    # Get instance info if available
                    instance_id = None
                    cache_hit = False
                    cache_age_ms = None
                    
                    if resolved_from in ["preferred", "domain", "task", "default"]:
                        instance = await self.organism_manager.routing._get_active_instance(logical_id, current_epoch)
                        if instance:
                            instance_id = instance.get("instance_id")
                            # Check if this was a cache hit
                            cache_hit = instance.get("cache_hit", False)
                            cache_age_ms = instance.get("cache_age_ms")
                        else:
                            results.append(BulkResolveResult(
                                index=item.index, key=item.key, status="no_active_instance",
                                logical_id=logical_id, epoch=current_epoch,
                                error=f"No active instance for {logical_id}"
                            ))
                            continue
                    
                    results.append(BulkResolveResult(
                        index=item.index, key=item.key, status="ok",
                        logical_id=logical_id, resolved_from=resolved_from,
                        epoch=current_epoch, instance_id=instance_id,
                        cache_hit=cache_hit, cache_age_ms=cache_age_ms
                    ))
                    
                except Exception as e:
                    results.append(BulkResolveResult(
                        index=item.index, key=item.key, status="error",
                        epoch=current_epoch, error=str(e)
                    ))
            
            return {"epoch": current_epoch, "results": results}
            
        except Exception as e:
            logger.error(f"Bulk route resolution failed: {e}")
            return {"epoch": "unknown", "results": []}

    @app.get("/routing/rules")
    async def get_routing_rules(self):
        """Get current routing rules."""
        try:
            if not self._initialized:
                return {"error": "Organism not initialized"}
            
            return self.organism_manager.routing.get_rules()
        except Exception as e:
            return {"error": str(e)}

    @app.put("/routing/rules")
    async def update_routing_rules(self, rules: Dict[str, Any]):
        """Update routing rules."""
        try:
            if not self._initialized:
                return {"error": "Organism not initialized"}
            
            # Add/update rules
            for rule in rules.get("add", []):
                self.organism_manager.routing.set_rule(
                    rule["task_type"], rule["logical_id"], rule.get("domain")
                )
            
            # Remove rules
            for rule in rules.get("remove", []):
                self.organism_manager.routing.remove_rule(
                    rule["task_type"], rule.get("domain")
                )
            
            return {"success": True, "rules": self.organism_manager.routing.get_rules()}
        except Exception as e:
            return {"error": str(e)}

    @app.post("/routing/refresh")
    async def refresh_routing_cache(self):
        """Refresh routing cache (useful after epoch rotation)."""
        try:
            if not self._initialized:
                return {"error": "Organism not initialized"}
            
            self.organism_manager.routing.clear_cache()
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    # --- Evolution and Memory Endpoints ---

    @app.post("/evolve")
    async def evolve(self, proposal: Dict[str, Any]):
        """Execute an evolution operation (split/merge/clone/retire)."""
        try:
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}

            result = await self.organism_manager.evolve(proposal)

            # Compute acceptance (best-effort) based on delta_E_est vs cost
            delta_E_est = result.get("delta_E_est")
            cost = result.get("cost", 0.0)
            accepted = bool(delta_E_est is not None and cost is not None and delta_E_est > cost)
            result["accepted"] = accepted
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.post("/memory/threshold")
    async def set_memory_threshold(self, thresholds: Dict[str, float]):
        """Set memory thresholds for the bandit/memory controller."""
        try:
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}
            return await self.organism_manager.set_memory_thresholds(thresholds)
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- Direct Method Access for Backward Compatibility ---

    async def handle_incoming_task(self, task: Dict[str, Any], app_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Direct method access for backward compatibility with existing code.
        This allows the organism to be called directly via Serve handle.
        """
        try:
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}
            
            return await self.organism_manager.handle_incoming_task(task, app_state)
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def make_decision(self, task: Dict[str, Any], app_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Direct method access for decision making.
        """
        try:
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}
            
            return await self.organism_manager.make_decision(task, app_state)
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def plan_task(self, task: Dict[str, Any], app_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Direct method access for task planning.
        """
        try:
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}
            
            return await self.organism_manager.plan_task(task, app_state)
        except Exception as e:
            return {"success": False, "error": str(e)}


# --- Main Entrypoint ---
# At module level so Ray Serve YAML can import directly
organism_app = OrganismService.bind()

def build_organism_app(args: dict = None):
    """
    Builder function for the organism service application.
    
    This function returns a bound Serve application that can be deployed
    via Ray Serve YAML configuration.
    
    Args:
        args: Optional configuration arguments (unused in this implementation)
        
    Returns:
        Bound Serve application
    """
    return OrganismService.bind()

def main():
    logger.info("🚀 Starting deployment driver for Organism Service...")
    try:
        if not ensure_ray_initialized(ray_address=RAY_ADDR, ray_namespace=RAY_NS):
            logger.error("❌ Failed to initialize Ray connection")
            sys.exit(1)

        serve.run(
            organism_app,
            name="organism",
            route_prefix="/organism"
        )
        logger.info("✅ Organism service is running.")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down gracefully...")
    finally:
        serve.shutdown()
        logger.info("✅ Serve shutdown complete.")


if __name__ == "__main__":
    main()
