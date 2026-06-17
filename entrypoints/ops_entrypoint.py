#!/usr/bin/env python3
import asyncio
import sys
import time
from typing import Any, Dict, Optional

# Explicitly import FastAPI Response to avoid collision with your data models
from fastapi import FastAPI, HTTPException, Response as StarletteResponse  # pyright: ignore[reportMissingImports]
from ray import serve  # pyright: ignore[reportMissingImports]

# Add the project root to Python path
sys.path.insert(0, "/app")
sys.path.insert(0, "/app/src")

from seedcore.logging_setup import ensure_serve_logger, setup_logging
from seedcore.services.eventizer_service import EventizerService
from seedcore.services.fact_service import FactManagerService
from seedcore.services.state_service import (
    StateService,
    startup_event as state_startup_event,
    shutdown_event as state_shutdown_event,
    get_system_metrics as state_get_system_metrics,
    health as state_health,
)
from seedcore.services.energy_service import (
    EnergyService,
    startup_event as energy_startup_event,
    shutdown_event as energy_shutdown_event,
    configure_embedded_state_provider,
    clear_embedded_state_provider,
)
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


_ops_embedded_services_started = False
_ops_embedded_services_lock: Optional[asyncio.Lock] = None


def _get_embedded_startup_lock() -> asyncio.Lock:
    global _ops_embedded_services_lock
    if _ops_embedded_services_lock is None:
        _ops_embedded_services_lock = asyncio.Lock()
    return _ops_embedded_services_lock


async def _ensure_embedded_ops_dependencies_started() -> None:
    """Initialize embedded state/energy lifecycle when ops runs in-process."""
    global _ops_embedded_services_started
    if _ops_embedded_services_started:
        return

    lock = _get_embedded_startup_lock()
    async with lock:
        if _ops_embedded_services_started:
            return
        await state_startup_event()
        configure_embedded_state_provider(
            metrics_fetch=lambda: state_get_system_metrics(None),
            health_fetch=state_health,
        )
        await energy_startup_event()
        _ops_embedded_services_started = True
        logger.info(
            "OpsGateway embedded state/energy lifecycle initialized"
        )


@ops_app.on_event("startup")
async def _ops_startup_event() -> None:
    await _ensure_embedded_ops_dependencies_started()


@ops_app.on_event("shutdown")
async def _ops_shutdown_event() -> None:
    global _ops_embedded_services_started
    if not _ops_embedded_services_started:
        return
    results = await asyncio.gather(
        energy_shutdown_event(),
        state_shutdown_event(),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, Exception):
            logger.warning(
                "OpsGateway embedded shutdown encountered error: %s", result
            )
    clear_embedded_state_provider()
    _ops_embedded_services_started = False

def _instantiate_deployment_backend(deployment_obj: Any, *args, **kwargs) -> Any:
    """
    Instantiate the class wrapped by @serve.deployment.

    Ray 2.53+ disallows constructing Deployment objects directly
    (e.g., `EventizerService()`), but OpsGateway needs in-process backends.
    Ray Serve ingress wrappers expose the original class through `__wrapped__`;
    instantiate that class so we do not construct the ASGI wrapper manually.
    """
    target_cls = getattr(deployment_obj, "func_or_class", None) or getattr(
        deployment_obj, "_func_or_class", None
    )
    if target_cls is None:
        raise RuntimeError(
            f"Could not resolve backend class from deployment object: {deployment_obj!r}"
        )
    target_cls = getattr(target_cls, "__wrapped__", target_cls)
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
    # Internal RPC Surface (preferred for in-cluster callers)
    # ========================================================================

    async def rpc_state_system_metrics(self):
        await _ensure_embedded_ops_dependencies_started()
        return await self.state.rpc_system_metrics()

    async def rpc_state_unified_state(self):
        await _ensure_embedded_ops_dependencies_started()
        return await self.state.rpc_unified_state()

    async def rpc_state_agent_snapshots(self):
        await _ensure_embedded_ops_dependencies_started()
        return await self.state.rpc_agent_snapshots()

    async def rpc_state_update_w_mode(self, payload: Dict[str, Any]):
        await _ensure_embedded_ops_dependencies_started()
        return await self.state.rpc_update_w_mode(payload)

    async def rpc_state_health(self):
        await _ensure_embedded_ops_dependencies_started()
        return await self.state.rpc_health()

    async def rpc_state_status(self):
        await _ensure_embedded_ops_dependencies_started()
        return await self.state.rpc_status()

    async def rpc_energy_metrics(self):
        await _ensure_embedded_ops_dependencies_started()
        return await self.energy.rpc_get_metrics()

    async def rpc_energy_compute_from_state(self):
        await _ensure_embedded_ops_dependencies_started()
        return await self.energy.rpc_compute_from_state()

    async def rpc_energy_compute(self, payload: Dict[str, Any]):
        await _ensure_embedded_ops_dependencies_started()
        return await self.energy.rpc_compute_energy(EnergyRequest(**payload))

    async def rpc_energy_optimize(self, payload: Dict[str, Any]):
        await _ensure_embedded_ops_dependencies_started()
        return await self.energy.rpc_optimize_agents(OptimizationRequest(**payload))

    async def rpc_energy_flywheel_result(self, payload: Dict[str, Any]):
        await _ensure_embedded_ops_dependencies_started()
        return await self.energy.rpc_flywheel_result(FlywheelResultRequest(**payload))

    async def rpc_energy_health(self):
        await _ensure_embedded_ops_dependencies_started()
        return await self.energy.rpc_health()

    async def rpc_energy_status(self):
        await _ensure_embedded_ops_dependencies_started()
        return await self.energy.rpc_status()

    async def rpc_energy_meta(self):
        await _ensure_embedded_ops_dependencies_started()
        return await self.energy.rpc_get_meta()

    async def rpc_energy_log(self, payload: Dict[str, Any]):
        await _ensure_embedded_ops_dependencies_started()
        return await self.energy.rpc_log_event(payload)

    async def rpc_energy_logs(self, limit: int = 100):
        await _ensure_embedded_ops_dependencies_started()
        return await self.energy.rpc_get_logs(limit=limit)

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
            data = await self.rpc_state_system_metrics()

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

    @ops_app.get("/state/unified-state")
    async def state_unified_state(self):
        """Full unified state snapshot for planner/debug workloads."""
        try:
            return await self.rpc_state_unified_state()
        except Exception as e:
            logger.error(f"State unified-state error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @ops_app.get("/state/agent-snapshots")
    async def state_agent_snapshots(self):
        """Raw Crude Oil — snapshots."""
        try:
            return await self.rpc_state_agent_snapshots()
        except Exception as e:
            logger.error(f"State snapshots error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @ops_app.post("/state/config/w_mode")
    async def state_update_w_mode(self, payload: Dict[str, Any]):
        """Update state config w_mode."""
        try:
            return await self.rpc_state_update_w_mode(payload)
        except Exception as e:
            logger.error(f"State config error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @ops_app.get("/state/health")
    async def state_health(self):
        """State service health check."""
        return await self.rpc_state_health()

    @ops_app.get("/state/status")
    async def state_status(self):
        """State service readiness/details."""
        return await self.rpc_state_status()

    # ========================================================================
    # Energy Service Routes
    # ========================================================================

    @ops_app.get("/energy/metrics")
    async def energy_metrics(self):
        """Get energy metrics."""
        return await self.rpc_energy_metrics()

    @ops_app.get("/energy/compute-from-state")
    async def energy_compute_from_state(self):
        """Compute energy from state."""
        return await self.rpc_energy_compute_from_state()

    @ops_app.post("/energy/compute")
    async def energy_compute(self, payload: Dict[str, Any]):
        """Compute energy."""
        return await self.rpc_energy_compute(payload)

    @ops_app.post("/energy/optimize")
    async def energy_optimize(self, payload: Dict[str, Any]):
        """Optimize energy."""
        return await self.rpc_energy_optimize(payload)

    @ops_app.post("/flywheel/result")
    async def flywheel_result(self, payload: Dict[str, Any]):
        """Flywheel result."""
        return await self.rpc_energy_flywheel_result(payload)

    @ops_app.get("/energy/health")
    async def energy_health(self):
        """Energy service health check."""
        return await self.rpc_energy_health()

    @ops_app.get("/energy/status")
    async def energy_status(self):
        """Energy service readiness/details."""
        return await self.rpc_energy_status()

    @ops_app.get("/energy/meta")
    async def energy_meta(self):
        """Energy service promotion/contractivity metadata."""
        return await self.rpc_energy_meta()

    @ops_app.post("/energy/log")
    async def energy_log(self, payload: Dict[str, Any]):
        """Record an operational energy event."""
        return await self.rpc_energy_log(payload)

    @ops_app.get("/energy/logs")
    async def energy_logs(self, limit: int = 100):
        """Fetch recent energy events."""
        return await self.rpc_energy_logs(limit=limit)

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
                self.rpc_state_health(),
                self.rpc_energy_health(),
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
