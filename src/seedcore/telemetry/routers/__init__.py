from fastapi import FastAPI

from .actions import router as actions_router
from .admin import router as admin_router
from .agents import router as agents_router
from .coordinator import router as coordinator_router
from .dspy import router as dspy_router
from .energy import router as energy_router
from .health import router as health_router
from .healthz import router as healthz_router
from .maintenance import router as maintenance_router
from .metrics import router as metrics_router
from .mw import router as mw_router
from .pair_stats import router as pair_stats_router
from .ray import router as ray_router
from .readyz import router as readyz_router
from .run_all_loops import router as run_all_loops_router
from .run_memory_loop import router as run_memory_loop_router
from .run_simulation_step import router as run_simulation_step_router
from .run_slow_loop import router as run_slow_loop_router
from .run_slow_loop_simple import router as run_slow_loop_simple_router
from .system import router as system_router
from .tier0 import router as tier0_router

def include_all(app: FastAPI) -> None:
    # Prefixed routers
    app.include_router(actions_router, prefix='/actions')
    app.include_router(admin_router, prefix='/admin')
    app.include_router(agents_router, prefix='/agents')
    app.include_router(coordinator_router, prefix='/coordinator')
    app.include_router(dspy_router, prefix='/dspy')
    app.include_router(energy_router, prefix='/energy')
    app.include_router(maintenance_router, prefix='/maintenance')
    app.include_router(mw_router, prefix='/mw')
    app.include_router(ray_router, prefix='/ray')
    app.include_router(system_router, prefix='/system')
    app.include_router(tier0_router, prefix='/tier0')
    
    # Root-level routers (no prefix)
    app.include_router(health_router)
    app.include_router(healthz_router)
    app.include_router(metrics_router)
    app.include_router(pair_stats_router)
    app.include_router(readyz_router)
    app.include_router(run_all_loops_router)
    app.include_router(run_memory_loop_router)
    app.include_router(run_simulation_step_router)
    app.include_router(run_slow_loop_router)
    app.include_router(run_slow_loop_simple_router)
