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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy import text

logger = logging.getLogger(__name__)

from .database import get_async_pg_engine  # must return postgresql+asyncpg engine
from .models import TaskBase
from .models.fact import Base as FactBase
from .api.routers.tasks_router import router as tasks_router
from .graph.task_embedding_worker import (
    task_embedding_backfill_loop,
    task_embedding_worker,
)
from .api.routers.control_router import router as control_router

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting SeedCore API application...")
    
    engine = get_async_pg_engine()  # must be asyncpg-based
    app.state.db_engine = engine
    await init_db(engine)
    await _verify_graph_node_support(engine)
    logger.info("Database initialized successfully")
    
    # Initialize task queue (task processing is handled by queue_dispatcher.py)
    if not hasattr(app.state, "task_queue"):
        app.state.task_queue = asyncio.Queue()
    logger.info("Task queue initialized (processing handled by queue_dispatcher)")

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

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "seedcore-api", "version": "1.0.0"}

@app.get("/readyz")
async def ready_check():
    # verify DB quickly to gate readiness
    try:
        eng: AsyncEngine = app.state.db_engine
        async with eng.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready", "deps": {"db": "ok"}}
    except Exception as e:
        return {"status": "not_ready", "deps": {"db": f"error: {e}"}}

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
