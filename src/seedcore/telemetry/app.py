from fastapi import FastAPI
from .routers import include_all
from contextlib import asynccontextmanager
import os
import logging

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting SeedCore Telemetry API...")
    
    # TODO: Initialize Ray if not already initialized
    # ray_address = os.getenv("RAY_ADDRESS", "auto")
    # if not ray.is_initialized():
    #     ray.init(address=ray_address)
    #     logger.info(f"Ray initialized with address: {ray_address}")
    
    # TODO: Initialize database connections
    # TODO: Initialize cache clients
    # TODO: Initialize metrics collection
    
    logger.info("SeedCore Telemetry API started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down SeedCore Telemetry API...")
    
    # TODO: Graceful teardown
    # TODO: Close database connections
    # TODO: Stop metrics collection
    # TODO: Cleanup Ray resources if needed
    
    logger.info("SeedCore Telemetry API shutdown complete")

app = FastAPI(
    title="SeedCore Telemetry API",
    description="Telemetry and monitoring endpoints for SeedCore system",
    version="1.0.0",
    lifespan=lifespan
)

include_all(app)  # registers all routers
