#!/usr/bin/env python3
import asyncio
import sys
import time
from typing import Any, Dict

# Explicitly import FastAPI Response to avoid collision with your data models
from fastapi import FastAPI, HTTPException, Response as StarletteResponse  # pyright: ignore[reportMissingImports]
from ray import serve  # pyright: ignore[reportMissingImports]
from ray.serve.handle import DeploymentHandle  # pyright: ignore[reportMissingImports]

# Add the project root to Python path
sys.path.insert(0, "/app")
sys.path.insert(0, "/app/src")

from seedcore.logging_setup import ensure_serve_logger, setup_logging
from seedcore.services.eventizer_service import EventizerService
from seedcore.services.fact_service import FactManagerService
from seedcore.services.state_service import StateService
from seedcore.services.energy_service import EnergyService
from seedcore.models.energy import (
    EnergyRequest,
    OptimizationRequest,
    FlywheelResultRequest,
)

# Configuration
setup_logging(app_name="seedcore.ops_service.driver")
logger = ensure_serve_logger("seedcore.ops_service", level="DEBUG")

# Create FastAPI app globally - routes will be registered at class level
ops_app = FastAPI(
    title="SeedCore Ops App",
    version="2.0.0",
    docs_url="/docs",
)


@serve.deployment
@serve.ingress(ops_app)
class OpsGateway:
    """
    Unified gateway for all ops services.
    
    Architecture: Routes are defined at class level using @ops_app decorators
    so they are visible during FastAPI startup and OpenAPI schema generation.
    """

    def __init__(
        self,
        eventizer_handle: DeploymentHandle,
        fact_handle: DeploymentHandle,
        state_handle: DeploymentHandle,
        energy_handle: DeploymentHandle,
    ) -> None:
        # Store handles for use in route methods
        self.eventizer = eventizer_handle
        self.fact = fact_handle
        self.state = state_handle
        self.energy = energy_handle

    # ========================================================================
    # Eventizer Routes
    # ========================================================================

    @ops_app.post("/eventizer/process")
    async def process_eventizer(self, payload: Dict[str, Any]):
        """Process eventizer request."""
        try:
            result = await self.eventizer.process.remote(payload)
            return result
        except Exception as e:
            logger.error(f"Eventizer error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @ops_app.get("/eventizer/health")
    async def eventizer_health(self):
        """Eventizer health check."""
        try:
            return await self.eventizer.health.remote()
        except Exception as e:
            logger.error(f"Eventizer health error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ========================================================================
    # Fact Manager Routes
    # ========================================================================

    @ops_app.post("/fact/create")
    async def fact_create(self, payload: Dict[str, Any]):
        """Create a fact."""
        try:
            return await self.fact.create_fact.remote(payload)
        except Exception as e:
            logger.error(f"Fact error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @ops_app.post("/fact/query")
    async def fact_query(self, payload: Dict[str, Any]):
        """Query facts."""
        try:
            return await self.fact.query_fact.remote(payload)
        except Exception as e:
            logger.error(f"Fact query error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @ops_app.get("/fact/health")
    async def fact_health(self):
        """Fact service health check."""
        return await self.fact.health_check.remote()

    # ========================================================================
    # State Service Routes
    # ========================================================================

    @ops_app.get("/state/system-metrics")
    async def state_system_metrics(self, response: StarletteResponse):
        """Refined Jet Fuel — precomputed aggregates."""
        try:
            data = await self.state.rpc_system_metrics.remote()

            if isinstance(data, dict):
                meta = data.get("meta", {})
                response.headers["X-System-Status"] = str(
                    meta.get("status", "unknown")
                )
                response.headers["X-Processing-Time"] = (
                    f"{meta.get('latency_ms', 0):.3f}ms"
                )

            return data
        except Exception as e:
            logger.error(f"State metrics error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @ops_app.get("/state/agent-snapshots")
    async def state_agent_snapshots(self):
        """Raw Crude Oil — snapshots."""
        try:
            return await self.state.rpc_agent_snapshots.remote()
        except Exception as e:
            logger.error(f"State snapshots error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @ops_app.post("/state/config/w_mode")
    async def state_update_w_mode(self, payload: Dict[str, Any]):
        """Update state config w_mode."""
        try:
            return await self.state.rpc_update_w_mode.remote(payload)
        except Exception as e:
            logger.error(f"State config error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @ops_app.get("/state/health")
    async def state_health(self):
        """State service health check."""
        return await self.state.rpc_health.remote()

    # ========================================================================
    # Energy Service Routes
    # ========================================================================

    @ops_app.get("/energy/metrics")
    async def energy_metrics(self):
        """Get energy metrics."""
        return await self.energy.rpc_get_metrics.remote()

    @ops_app.get("/energy/compute-from-state")
    async def energy_compute_from_state(self):
        """Compute energy from state."""
        return await self.energy.rpc_compute_from_state.remote()

    @ops_app.post("/energy/compute")
    async def energy_compute(self, payload: Dict[str, Any]):
        """Compute energy."""
        req = EnergyRequest(**payload)
        return await self.energy.rpc_compute_energy.remote(req)

    @ops_app.post("/energy/optimize")
    async def energy_optimize(self, payload: Dict[str, Any]):
        """Optimize energy."""
        req = OptimizationRequest(**payload)
        return await self.energy.rpc_optimize_agents.remote(req)

    @ops_app.post("/flywheel/result")
    async def flywheel_result(self, payload: Dict[str, Any]):
        """Flywheel result."""
        req = FlywheelResultRequest(**payload)
        return await self.energy.rpc_flywheel_result.remote(req)

    @ops_app.get("/energy/health")
    async def energy_health(self):
        """Energy service health check."""
        return await self.energy.rpc_health.remote()

    # ========================================================================
    # Overall Health
    # ========================================================================

    @ops_app.get("/health")
    async def ops_health(self):
        """Overall ops gateway health check."""
        start_time = time.time()
        try:
            results = await asyncio.gather(
                self.eventizer.health.remote(),
                self.fact.health_check.remote(),
                self.state.rpc_health.remote(),
                self.energy.rpc_health.remote(),
                return_exceptions=True,
            )

            # Unpack results safely
            eventizer_h, fact_h, state_h, energy_h = [
                r if not isinstance(r, Exception) else str(r) for r in results
            ]

            latency_ms = (time.time() - start_time) * 1000

            return {
                "status": "healthy",
                "latency_ms": round(latency_ms, 2),
                "services": {
                    "eventizer": eventizer_h,
                    "fact": fact_h,
                    "state": state_h,
                    "energy": energy_h,
                },
            }

        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}


def build_ops_app(args: dict = None) -> serve.Deployment:
    logger.info("Building ops application...")

    eventizer_app = EventizerService.bind()
    fact_app = FactManagerService.bind()
    state_app = StateService.bind()
    energy_app = EnergyService.bind()

    gateway = OpsGateway.bind(
        eventizer_handle=eventizer_app,
        fact_handle=fact_app,
        state_handle=state_app,
        energy_handle=energy_app,
    )
    return gateway


if __name__ == "__main__":
    pass
