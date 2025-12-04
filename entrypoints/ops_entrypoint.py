#!/usr/bin/env python3
import sys
import time
from typing import Any, Dict

# Explicitly import FastAPI Response to avoid collision with your data models
from fastapi import APIRouter, FastAPI, HTTPException, Response as StarletteResponse  # pyright: ignore[reportMissingImports]
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


@serve.deployment
@serve.ingress(FastAPI())
class OpsGateway:
    """
    Unified gateway for all ops services.
    """

    def __init__(
        self,
        eventizer_handle: DeploymentHandle,
        fact_handle: DeploymentHandle,
        state_handle: DeploymentHandle,
        energy_handle: DeploymentHandle,
    ) -> None:
        self.app = FastAPI(
            title="SeedCore Ops App",
            version="2.0.0",
            docs_url="/docs",
        )

        # Handles are captured here, available to closures below
        self.eventizer = eventizer_handle
        self.fact = fact_handle
        self.state = state_handle
        self.energy = energy_handle

        router = APIRouter(prefix="")

        # --- Eventizer ---
        @router.post("/eventizer/process")
        async def process_eventizer(payload: Dict[str, Any]):
            try:
                # RPC call
                return await self.eventizer.process.remote(payload)
            except Exception as e:
                logger.error(f"Eventizer error: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.get("/eventizer/health")
        async def eventizer_health():
            return await self.eventizer.health.remote()

        # --- Fact Manager ---
        # NOTE: If FactManager uses Pydantic now, we pass the dict.
        # Ray's remote() handles arguments as python objects.
        # If FactManager expects a Pydantic model object, you might need to construct it here,
        # OR ensure FactManager accepts a dict and converts it internally.
        @router.post("/fact/create")
        async def fact_create(payload: Dict[str, Any]):
            try:
                return await self.fact.create_fact.remote(payload)
            except Exception as e:
                logger.error(f"Fact error: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.post("/fact/query")
        async def fact_query(payload: Dict[str, Any]):
            try:
                return await self.fact.query_fact.remote(payload)
            except Exception as e:
                logger.error(f"Fact query error: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.get("/fact/health")
        async def fact_health():
            return await self.fact.health_check.remote()

        # --- State Service ---

        # FIX 1 & 2: Removed 'self', used StarletteResponse
        @router.get("/state/system-metrics")
        async def state_system_metrics(response: StarletteResponse):
            """Refined Jet Fuel — precomputed aggregates."""
            try:
                # Use self.state (captured from closure)
                data = await self.state.rpc_system_metrics.remote()

                if isinstance(data, dict):
                    meta = data.get("meta", {})
                    # Using StarletteResponse to set headers
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

        @router.get("/state/agent-snapshots")
        async def state_agent_snapshots():
            """Raw Crude Oil — snapshots."""
            try:
                return await self.state.rpc_agent_snapshots.remote()
            except Exception as e:
                logger.error(f"State snapshots error: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.post("/state/config/w_mode")
        async def state_update_w_mode(payload: Dict[str, Any]):
            try:
                return await self.state.rpc_update_w_mode.remote(payload)
            except Exception as e:
                logger.error(f"State config error: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.get("/state/health")
        async def state_health():
            return await self.state.rpc_health.remote()

        # --- Energy Service ---
        @router.get("/energy/metrics")
        async def energy_metrics():
            return await self.energy.rpc_get_metrics.remote()

        @router.get("/energy/compute-from-state")
        async def energy_compute_from_state():
            return await self.energy.rpc_compute_from_state.remote()

        @router.post("/energy/compute")
        async def energy_compute(payload: Dict[str, Any]):
            # Re-wrap into Pydantic before sending to Actor
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

        # --- Overall Health ---
        @router.get("/health")
        async def ops_health():
            start_time = time.time()
            try:
                results = await asyncio.gather(
                    self.eventizer.health.remote(),
                    self.fact.health_check.remote(),  # updated method name
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

        self.app.include_router(router)


# Import asyncio for the gather in health check
import asyncio  # noqa: E402


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
