"""
Main SeedCore FastAPI application with database-backed task management.

This demonstrates how to integrate the refactored task router with proper
database initialization and background worker management using FastAPI's lifespan.
"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import database and models
from .database import get_async_pg_engine
from .models.task import Base as TaskBase
from .models.fact import Base as FactBase
from .api.routers.tasks_router import router as tasks_router
from .api.routers.control_router import router as control_router

# Import the worker function
from .api.routers.tasks_router import _task_worker

async def init_db():
    """Create database tables on startup if they don't exist."""
    try:
        engine = get_async_pg_engine()
        async with engine.begin() as conn:
            # This will create both 'tasks' and 'facts' tables
            await conn.run_sync(TaskBase.metadata.create_all)
            await conn.run_sync(FactBase.metadata.create_all)
        print("✅ Database tables created/verified successfully.")
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        raise

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    print("🚀 Initializing SeedCore application...")
    
    print("🚀 Initializing database...")
    await init_db()
    print("✅ Database initialized.")

    # Initialize app state
    app.state.task_queue = asyncio.Queue()
    print("✅ App state initialized.")

    # Start the single background task worker
    print("🚀 Starting task worker...")
    worker_task = asyncio.create_task(_task_worker(app.state))
    print("✅ Task worker started.")
    
    yield # Application is running
    
    # --- SHUTDOWN ---
    print("🛑 Shutting down task worker...")
    # Gracefully shut down the worker
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    print("✅ Worker shutdown complete.")

# Create the FastAPI application with lifespan management
app = FastAPI(
    title="SeedCore API",
    description="Scalable, database-backed task management system",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the refactored routers
app.include_router(tasks_router, prefix="/api/v1", tags=["Tasks"])
app.include_router(control_router, prefix="/api/v1", tags=["Control"])

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "seedcore-api",
        "version": "1.0.0"
    }

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Welcome to SeedCore API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
