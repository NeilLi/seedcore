#!/usr/bin/env python3
import asyncio
import sys
import time
from typing import Any, Dict

# Explicitly import FastAPI Response to avoid collision with your data models
from fastapi import FastAPI, HTTPException, Response as StarletteResponse  # pyright: ignore[reportMissingImports]
from ray import serve  # pyright: ignore[reportMissingImports]

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

def _instantiate_deployment_backend(deployment_obj: Any, *args, **kwargs) -> Any:
    """
    Instantiate the class wrapped by @serve.deployment.

    Ray 2.53+ disallows constructing Deployment objects directly
    (e.g., `EventizerService()`), but OpsGateway needs in-process backends.
    """
    target_cls = getattr(deployment_obj, "func_or_class", None) or getattr(
        deployment_obj, "_func_or_class", None
    )
    if target_cls is None:
        raise RuntimeError(
            f"Could not resolve backend class from deployment object: {deployment_obj!r}"
        )
    return target_cls(*args, **kwargs)


@serve.deployment
@serve.ingress(ops_app)
class OpsGateway:
    """
    Unified gateway for all ops services.
    
    Architecture: Routes are defined at class level using @ops_app decorators
    so they are visible during FastAPI startup and OpenAPI schema generation.
    """

    def __init__(self) -> None:
        # Keep a single ingress deployment in this Serve application.
        # Instantiate wrapped backend classes (not deployment objects) to avoid
        # multiple ingress deployments in one app graph on Ray 2.53+.
        self.eventizer = _instantiate_deployment_backend(EventizerService)
        self.fact = _instantiate_deployment_backend(FactManagerService)
        self.state = _instantiate_deployment_backend(StateService)
        self.energy = _instantiate_deployment_backend(EnergyService)

    # ========================================================================
    # Eventizer Routes
    # ========================================================================

    @ops_app.post("/eventizer/process")
    async def process_eventizer(self, payload: Dict[str, Any]):
        """Process eventizer request."""
        try:
            result = await self.eventizer.process(payload)
            return result
        except Exception as e:
            logger.error(f"Eventizer error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @ops_app.get("/eventizer/health")
    async def eventizer_health(self):
        """Eventizer health check."""
        try:
            return await self.eventizer.health()
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
            return await self.fact.create_fact(payload)
        except Exception as e:
            logger.error(f"Fact error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @ops_app.post("/fact/query")
    async def fact_query(self, payload: Dict[str, Any]):
        """Query facts."""
        try:
            return await self.fact.query_fact(payload)
        except Exception as e:
            logger.error(f"Fact query error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @ops_app.get("/fact/health")
    async def fact_health(self):
        """Fact service health check."""
        return await self.fact.health_check()

    # ========================================================================
    # State Service Routes
    # ========================================================================

    @ops_app.get("/state/system-metrics")
    async def state_system_metrics(self, response: StarletteResponse):
        """Refined Jet Fuel — precomputed aggregates."""
        try:
            data = await self.state.rpc_system_metrics()

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
            return await self.state.rpc_agent_snapshots()
        except Exception as e:
            logger.error(f"State snapshots error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @ops_app.post("/state/config/w_mode")
    async def state_update_w_mode(self, payload: Dict[str, Any]):
        """Update state config w_mode."""
        try:
            return await self.state.rpc_update_w_mode()
        except Exception as e:
            logger.error(f"State config error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @ops_app.get("/state/health")
    async def state_health(self):
        """State service health check."""
        return await self.state.rpc_health()

    # ========================================================================
    # Energy Service Routes
    # ========================================================================

    @ops_app.get("/energy/metrics")
    async def energy_metrics(self):
        """Get energy metrics."""
        return await self.energy.rpc_get_metrics()

    @ops_app.get("/energy/compute-from-state")
    async def energy_compute_from_state(self):
        """Compute energy from state."""
        return await self.energy.rpc_compute_from_state()

    @ops_app.post("/energy/compute")
    async def energy_compute(self, payload: Dict[str, Any]):
        """Compute energy."""
        req = EnergyRequest(**payload)
        return await self.energy.rpc_compute_energy(req)

    @ops_app.post("/energy/optimize")
    async def energy_optimize(self, payload: Dict[str, Any]):
        """Optimize energy."""
        req = OptimizationRequest(**payload)
        return await self.energy.rpc_optimize_agents(req)

    @ops_app.post("/flywheel/result")
    async def flywheel_result(self, payload: Dict[str, Any]):
        """Flywheel result."""
        req = FlywheelResultRequest(**payload)
        return await self.energy.rpc_flywheel_result(req)

    @ops_app.get("/energy/health")
    async def energy_health(self):
        """Energy service health check."""
        return await self.energy.rpc_health()

    # ========================================================================
    # Overall Health
    # ========================================================================

    @ops_app.get("/health")
    async def ops_health(self):
        """Overall ops gateway health check."""
        start_time = time.time()
        try:
            results = await asyncio.gather(
                self.eventizer.health(),
                self.fact.health_check(),
                self.state.rpc_health(),
                self.energy.rpc_health(),
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


def build_ops_app(args: dict | None = None) -> Any:
    logger.info("Building ops application...")
    args = args or {}

    gateway_cpus = float(args.get("gateway_num_cpus", 0.2))

    gateway = OpsGateway.options(
        ray_actor_options={"num_cpus": gateway_cpus}
    ).bind()
    return gateway


if __name__ == "__main__":
    pass
