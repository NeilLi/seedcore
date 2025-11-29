#!/usr/bin/env python3
"""
Ops Service Entrypoint for SeedCore - Merged Application

This entrypoint creates a unified Ray Serve application that hosts:
- EventizerService: Text processing and classification
- FactManagerService: Policy-driven fact management with PKG integration
- StateService: Centralized state aggregation
- EnergyService: Energy calculations and optimization

All services are exposed under a single /ops route prefix with a lightweight
OpsGateway that fans in/out to each service via Ray Serve handles.
"""

import sys
import time
from typing import Any, Dict

from fastapi import APIRouter, FastAPI, HTTPException  # type: ignore[reportMissingImports]
from ray import serve  # type: ignore[reportMissingImports]

# Type hint for Ray Serve handles
try:
    from ray.serve.handle import DeploymentHandle  # type: ignore[reportMissingImports]
except ImportError:
    # Fallback for older versions or if not available
    DeploymentHandle = Any

# Add the project root to Python path
sys.path.insert(0, "/app")
sys.path.insert(0, "/app/src")

from seedcore.logging_setup import ensure_serve_logger, setup_logging
from seedcore.services.eventizer_service import EventizerService
from seedcore.services.fact_service import FactManagerService
from seedcore.services.state_service import state_app
from seedcore.services.energy_service import energy_app
from seedcore.models.energy import (
    EnergyRequest,
    OptimizationRequest,
    FlywheelResultRequest,
)

setup_logging(app_name="seedcore.ops_service.driver")
logger = ensure_serve_logger("seedcore.ops_service", level="DEBUG")

# Models are handled internally by the service

# --- Configuration ---
# ---------- Serve Deployments (wrappers) ----------
# ---------- HTTP Gateway (single public ingress) ----------
@serve.deployment
@serve.ingress(FastAPI())
class OpsGateway:
    """Unified gateway for all ops services - SINGLE FastAPI ingress for the ops application."""

    def __init__(
        self,
        eventizer_handle: DeploymentHandle,
        fact_handle: DeploymentHandle,
        state_handle: DeploymentHandle,
        energy_handle: DeploymentHandle,
    ) -> None:
        # FastAPI app with explicit docs configuration
        # This is the ONLY ingress with docs in the ops application
        self.app = FastAPI(
            title="SeedCore Ops App",
            description="Unified application for EventizerService, FactManagerService, StateService, and EnergyService",
            version="1.0.0",
            docs_url="/docs",  # Explicit docs path
            redoc_url="/redoc",  # Explicit redoc path
            openapi_url="/openapi.json",  # Explicit OpenAPI schema path
        )

        self.eventizer = eventizer_handle
        self.fact = fact_handle
        self.state = state_handle
        self.energy = energy_handle

        # Create router for all ops endpoints
        router = APIRouter(prefix="")

        # Eventizer endpoints (matching eventizer_client.py interface)
        #
        # ARCHITECTURE: Distillation Engine
        # --------------------------------
        @router.post("/eventizer/process")
        async def process_eventizer(payload: Dict[str, Any]):
            try:
                result = await self.eventizer.process.remote(payload)
                return result
            except Exception as e:
                logger.error(f"Eventizer service call failed: {e}")
                raise HTTPException(
                    status_code=500, detail=f"Service unavailable: {str(e)}"
                )

        @router.get("/eventizer/health")
        async def eventizer_health():
            """Eventizer health check."""
            return await self.eventizer.health.remote()

        # Fact endpoints (matching fact_client.py interface)
        #
        # ARCHITECTURE: Distillation Engine
        # --------------------------------
        @router.post("/fact/create")
        async def fact_create(payload: Dict[str, Any]):
            """Create a fact."""
            try:
                result = await self.fact.create_fact.remote(payload)
                return result
            except Exception as e:
                logger.error(f"Fact creation failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.post("/fact/query")
        async def fact_query(payload: Dict[str, Any]):
            """Query fact."""
            try:
                result = await self.fact.query_fact.remote(payload)
                return result
            except Exception as e:
                logger.error(f"Fact query failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.get("/fact/health")
        async def fact_health():
            """fact health check."""
            return await self.fact.health.remote()

        # State endpoints (matching state_client.py interface)
        #
        # ARCHITECTURE: Distillation Engine
        # --------------------------------
        # The StateService's AgentAggregator acts as a "distillation engine":
        # - Raw Crude Oil: `_agent_snapshots` cache (multi-megabyte raw data)
        # - Refined Jet Fuel: `_system_metrics` cache (small, pre-computed aggregates)
        #
        # The distillation happens in `AgentAggregator._compute_system_metrics()`,
        # which consumes `_agent_snapshots` and refines it into `_system_metrics`.
        # The real consumer of `_agent_snapshots` is the aggregator itself.

        @router.get("/state/system-metrics")
        async def state_system_metrics():
            """
            Refined Jet Fuel — precomputed aggregates for real-time routing.
            """
            try:
                return await self.state.rpc_system_metrics.remote()
            except Exception as e:
                logger.error(f"State system metrics retrieval failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get("/state/agent-snapshots")
        async def state_agent_snapshots():
            """
            Raw Crude Oil — multi-megabyte snapshots for debugging / offline analysis.
            """
            try:
                return await self.state.rpc_agent_snapshots.remote()
            except Exception as e:
                logger.error(f"State agent snapshots retrieval failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.post("/state/config/w_mode")
        async def state_update_w_mode(payload: Dict[str, Any]):
            """Update the global system weight configuration (w_mode)."""
            try:
                return await self.state.rpc_update_w_mode.remote(payload)
            except Exception as e:
                logger.error(f"State w_mode update failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.get("/state/health")
        async def state_health():
            """StateService health check."""
            try:
                return await self.state.rpc_health.remote()
            except Exception as e:
                logger.error(f"State health check failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        # Energy endpoints (matching energy_client.py interface)
        #
        # ARCHITECTURE: Distillation Engine
        # --------------------------------
        @router.get("/energy/metrics")
        async def energy_metrics():
            return await self.energy.rpc_metrics.remote()

        @router.get("/energy/compute-from-state")
        async def energy_compute_from_state():
            return await self.energy.rpc_compute_from_state.remote()

        @router.post("/energy/compute")
        async def energy_compute(payload: Dict[str, Any]):
            req = EnergyRequest(**payload)
            return await self.energy.rpc_compute_energy.remote(req)

        @router.post("/energy/optimize")
        async def energy_optimize(payload: Dict[str, Any]):
            req = OptimizationRequest(**payload)
            return await self.energy.rpc_optimize_agents.remote(req)

        @router.post("/flywheel/result")
        async def flywheel_result(payload: Dict[str, Any]):
            req = FlywheelResultRequest(**payload)
            return await self.energy.rpc_flywheel_result.remote(req)

        @router.get("/energy/health")
        async def energy_health():
            return await self.energy.rpc_health.remote()

        @router.get("/health")
        async def ops_health():
            """Overall ops application health."""
            start_time = time.time()
            try:
                # Pure RPC (no synthetic ASGI request objects)
                eventizer_health = await self.eventizer.health.remote()
                fact_health = await self.fact.health.remote()
                state_health = await self.state.rpc_health.remote()
                energy_health = await self.energy.rpc_health.remote()

                latency_ms = (time.time() - start_time) * 1000

                return {
                    "status": "healthy",
                    "application": "ops",
                    "version": "1.0.0",
                    "time": time.time(),
                    "latency_ms": round(latency_ms, 2),
                    "services": {
                        "eventizer": eventizer_health,
                        "fact": fact_health,
                        "state": state_health,
                        "energy": energy_health,
                    },
                }

            except Exception as e:
                logger.error(f"Ops health check failed: {e}")
                latency_ms = (time.time() - start_time) * 1000
                return {
                    "status": "unhealthy",
                    "application": "ops",
                    "version": "1.0.0",
                    "time": time.time(),
                    "latency_ms": round(latency_ms, 2),
                    "error": str(e),
                }

        # Include all routes
        self.app.include_router(router)

    # FastAPI needs to reference the ASGI app via @serve.ingress
    # The app is already configured in __init__


# ---------- Application Builder ----------

def build_ops_app(args: dict = None) -> serve.Deployment:
    """
    Ray Serve application builder for the unified ops service.
    """

    logger.info("Building ops application with unified services")

    # Bind individual service deployments
    # Only OpsGateway has @serve.ingress(FastAPI()) to avoid docs conflicts
    eventizer_app = EventizerService.bind()
    fact_app = FactManagerService.bind()

    # Wire gateway with handles - OpsGateway is the ONLY public ingress
    gateway = OpsGateway.bind(
        eventizer_handle=eventizer_app,
        fact_handle=fact_app,
        state_handle=state_app,
        energy_handle=energy_app,
    )

    logger.info("Ops application built successfully with single ingress (OpsGateway)")
    return gateway


def main():
    """Standalone runner for testing."""
    logger.info("🚀 Starting Ops Application (standalone mode)...")

    try:
        # This would normally be handled by Ray Serve
        logger.info("Ops application configured for Ray Serve deployment")
        logger.info("Use 'ray serve start' or RayService YAML to deploy")

    except Exception as e:
        logger.error(f"Failed to start ops application: {e}")
        raise


if __name__ == "__main__":
    main()
