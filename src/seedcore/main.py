"""
Main SeedCore FastAPI application with database-backed task management.

This demonstrates how to integrate the refactored task router with proper
database initialization and background worker management using FastAPI's lifespan.
The background worker processes tasks from the queue and submits them to the
OrganismManager Serve deployment.
"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI  # pyright: ignore[reportMissingImports]
from fastapi.middleware.cors import CORSMiddleware  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncEngine  # pyright: ignore[reportMissingImports]
from sqlalchemy import text  # pyright: ignore[reportMissingImports]

from .database import get_async_pg_engine  # must return postgresql+asyncpg engine
from .models import TaskBase
from .models.fact import Base as FactBase
from .api.routers.tasks_router import router as tasks_router
from .graph.task_embedding_worker import (
    task_embedding_backfill_loop,
    task_embedding_worker,
)
from .api.routers.control_router import router as control_router
from .api.routers.pkg_router import router as pkg_router
from .ops.pkg import PKGClient, get_global_pkg_manager, initialize_global_pkg_manager
from .ops.pkg.manager import PKGMode
from .database import get_async_pg_session_factory, get_async_redis_client

logger = logging.getLogger(__name__)

ENABLE_ENV_ENDPOINT = os.getenv("ENABLE_DEBUG_ENV", "false").lower() in ("1","true","yes")
RUN_DDL_ON_STARTUP = os.getenv("RUN_DDL_ON_STARTUP", "true").lower() in ("1","true","yes")  # set false in prod

async def init_db(engine: AsyncEngine):
    """Create tables in dev; in prod prefer Alembic/migrations."""
    if not RUN_DDL_ON_STARTUP:
        return
    async with engine.begin() as conn:
        await conn.run_sync(TaskBase.metadata.create_all)
        await conn.run_sync(FactBase.metadata.create_all)


async def _verify_graph_node_support(engine: AsyncEngine) -> None:
    """Ensure ensure_task_node(uuid) exists before serving traffic."""

    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT to_regprocedure('ensure_task_node(uuid)')")
        )
        if result.scalar_one_or_none() is None:
            raise RuntimeError(
                "Database is missing ensure_task_node(uuid). Apply migration "
                "007_hgnn_graph_schema.sql or later before starting SeedCore API."
            )
    logger.info("Verified ensure_task_node(uuid) exists in the database")

async def _verify_snapshot_support(engine: AsyncEngine) -> None:
    """Verify snapshot_id support exists (migration 017)."""
    async with engine.connect() as conn:
        # Check if pkg_active_snapshot_id function exists
        result = await conn.execute(
            text("SELECT to_regprocedure('pkg_active_snapshot_id(pkg_env)')")
        )
        if result.scalar_one_or_none() is None:
            logger.warning(
                "pkg_active_snapshot_id function not found. Snapshot scoping will be disabled. "
                "Apply migration 017_pkg_tasks_snapshot_scoping.sql to enable snapshot support."
            )
        else:
            logger.info("Verified snapshot_id support (migration 017) exists in the database")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting SeedCore API application...")
    
    engine = get_async_pg_engine()  # must be asyncpg-based
    app.state.db_engine = engine
    await init_db(engine)
    await _verify_graph_node_support(engine)
    await _verify_snapshot_support(engine)
    logger.info("Database initialized successfully")

    # Initialize PKG Manager (non-fatal if unavailable)
    try:
        if not get_global_pkg_manager():
            logger.info("Initializing PKG Manager...")
            session_factory = get_async_pg_session_factory()
            pkg_client = PKGClient(session_factory)
            try:
                redis_client = await get_async_redis_client()
                logger.debug("Redis client available for PKG hot-swap")
            except Exception as redis_err:
                logger.warning("Redis unavailable for PKG hot-swap: %s", redis_err)
                redis_client = None
            mode_str = os.getenv("PKG_MODE", PKGMode.ADVISORY.value).lower().strip()
            mode = PKGMode.CONTROL if mode_str == PKGMode.CONTROL.value else PKGMode.ADVISORY
            pkg_mgr = await initialize_global_pkg_manager(pkg_client, redis_client, mode=mode)
            
            # Verify initialization succeeded
            if pkg_mgr:
                evaluator = pkg_mgr.get_active_evaluator()
                if evaluator:
                    logger.info("PKG Manager initialized successfully (mode=%s, version=%s)", mode.value, evaluator.version)
                else:
                    logger.warning("PKG Manager initialized but no active evaluator available. Check if snapshots exist in database.")
            else:
                logger.error("PKG Manager initialization returned None")
        else:
            logger.info("PKG Manager already initialized")
    except Exception as e:
        logger.error("PKG Manager initialization failed (non-fatal): %s", e, exc_info=True)
    
    # Task processing is handled by Dispatcher Ray actors (started by bootstrap scripts)
    # No local task worker needed
    logger.info("Task processing handled by Dispatcher Ray actors")

    if not hasattr(app.state, "task_embedding_queue"):
        app.state.task_embedding_queue = asyncio.Queue()
        app.state.task_embedding_pending = set()
        app.state.task_embedding_pending_lock = asyncio.Lock()
    app.state.task_embedding_worker = asyncio.create_task(task_embedding_worker(app.state))
    app.state.task_embedding_backfill = asyncio.create_task(task_embedding_backfill_loop(app.state))
    logger.info("Task embedding workers started")
    
    logger.info("SeedCore API application startup complete")
    yield
    
    # Shutdown
    logger.info("Shutting down SeedCore API application...")
    
    # Cancel background workers
    # Note: Dispatcher Ray actors are managed by bootstrap scripts, not by this FastAPI app

    if hasattr(app.state, "task_embedding_backfill"):
        logger.info("Stopping task embedding backfill...")
        app.state.task_embedding_backfill.cancel()
        try:
            await app.state.task_embedding_backfill
        except asyncio.CancelledError:
            pass

    if hasattr(app.state, "task_embedding_worker"):
        logger.info("Stopping task embedding worker...")
        app.state.task_embedding_worker.cancel()
        try:
            await app.state.task_embedding_worker
        except asyncio.CancelledError:
            pass
        logger.info("Task embedding worker stopped")
    
    # Dispose database engine
    eng: AsyncEngine = app.state.db_engine
    await eng.dispose()
    logger.info("Database engine disposed")
    
    logger.info("SeedCore API application shutdown complete")

app = FastAPI(
    title="SeedCore API",
    description="Scalable, database-backed task management system",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router, prefix="/api/v1", tags=["Tasks"])
app.include_router(control_router, prefix="/api/v1", tags=["Control"])
app.include_router(pkg_router, prefix="/api/v1", tags=["PKG"])

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "seedcore-api", "version": "1.0.0"}

@app.get("/readyz")
async def ready_check():
    """Readiness check including database and optional vendor integrations."""
    deps = {}
    all_ready = True
    
    # 1. Database connectivity check
    try:
        eng: AsyncEngine = app.state.db_engine
        async with eng.connect() as conn:
            await conn.execute(text("SELECT 1"))
        deps["db"] = "ok"
    except Exception as e:
        deps["db"] = f"error: {e}"
        all_ready = False
    
    # 2. Optional vendor integrations (non-blocking)
    try:
        from seedcore.config.tuya_config import TuyaConfig
        tuya_config = TuyaConfig()
        deps["tuya"] = "enabled" if tuya_config.enabled else "disabled"
    except Exception as e:
        # Tuya config check failed - mark as unavailable but don't block readiness
        deps["tuya"] = f"unavailable: {e}"
    
    status = "ready" if all_ready else "not_ready"
    return {"status": status, "deps": deps}

@app.get("/")
async def root():
    return {"message": "Welcome to SeedCore API", "version": "1.0.0", "docs": "/docs", "health": "/health"}

# Optional, gated env dump for debugging
if ENABLE_ENV_ENDPOINT:
    @app.get("/_env")
    async def env_dump():
        keys = [
            "SEEDCORE_PG_DSN", "RAY_ADDRESS", "RAY_NAMESPACE",
            "OCPS_DRIFT_THRESHOLD", "COGNITIVE_TIMEOUT_S",
            "COGNITIVE_MAX_INFLIGHT", "FAST_PATH_LATENCY_SLO_MS",
            "MAX_PLAN_STEPS"
        ]
        return {k: os.getenv(k, "") for k in keys}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8002")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
