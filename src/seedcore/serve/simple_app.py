#!/usr/bin/env python3
"""
Simple Ray Serve application for SeedCore health checks.
This provides basic health monitoring without requiring full database connections.
"""

import ray
from ray import serve
from fastapi import FastAPI
from ..utils.ray_utils import ensure_ray_initialized
import logging
import os
from typing import Dict, Any
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Do not auto-start Serve at import time; entrypoint manages Serve lifecycle

# Create a simple FastAPI app
app = FastAPI(title="SeedCore Health Service", version="1.0.0")

@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "SeedCore Health Service is running", "timestamp": time.time()}

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "seedcore-health",
        "timestamp": time.time(),
        "ray_cluster": "connected" if ray.is_initialized() else "disconnected"
    }

@app.get("/ray/status")
async def ray_status():
    """Ray cluster status."""
    if ray.is_initialized():
        try:
            # Get basic Ray info
            runtime_context = ray.get_runtime_context()
            return {
                "status": "connected",
                "address": runtime_context.gcs_address,
                "namespace": runtime_context.namespace,
                "node_id": runtime_context.node_id,
                "timestamp": time.time()
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "timestamp": time.time()
            }
    else:
        return {
            "status": "disconnected",
            "timestamp": time.time()
        }

@app.get("/serve/info")
async def serve_info():
    """Ray Serve information."""
    try:
        applications = serve.list_deployments()
        return {
            "applications": list(applications.keys()),
            "serve_status": "running",
            "timestamp": time.time()
        }
    except Exception as e:
        return {
            "serve_status": "error",
            "error": str(e),
            "timestamp": time.time()
        }

@serve.deployment(
    name="seedcore-health",
    num_replicas=1,
    ray_actor_options={"num_cpus": 0.5, "num_gpus": 0}
)
@serve.ingress(app)
class SeedCoreHealthService:
    """Ray Serve deployment of the SeedCore Health Service."""
    
    def __init__(self):
        """Initialize the health service."""
        logger.info("🚀 Initializing SeedCore Health Service...")
        
        # Initialize Ray if not already done
        try:
            if not ray.is_initialized():
                # Get namespace from environment, default to "seedcore-dev" for consistency
                ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
                if not ensure_ray_initialized(ray_namespace=ray_namespace):
                    raise RuntimeError(f"Failed to initialize Ray connection (namespace={ray_namespace})")
                logger.info("✅ Ray initialized successfully")
            else:
                logger.info("✅ Ray already initialized")
        except Exception as e:
            logger.error(f"❌ Error during Ray initialization: {e}")
        
        logger.info("✅ SeedCore Health Service ready")

def deploy_health_service():
    """Deploy the SeedCore Health Service to Ray Serve."""
    try:
        logger.info("🚀 Deploying SeedCore Health Service to Ray Serve...")
        
        # Deploy the application
        app = SeedCoreHealthService.bind()
        serve.run(app, name="seedcore-health")
        
        logger.info("✅ SeedCore Health Service deployed successfully to Ray Serve")
        logger.info("📊 Serve dashboard available at: http://localhost:8265/#/serve")
        # Use environment variable for Ray Serve address
        base_url = os.getenv("RAY_SERVE_ADDRESS", "localhost:8000")
        if not base_url.startswith("http"):
            base_url = f"http://{base_url}"
        logger.info(f"🔗 Health endpoint available at: {base_url}/health")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to deploy SeedCore Health Service: {e}")
        return False

def undeploy_health_service():
    """Undeploy the SeedCore Health Service from Ray Serve."""
    try:
        logger.info("🛑 Undeploying SeedCore Health Service from Ray Serve...")
        serve.delete("seedcore-health")
        logger.info("✅ SeedCore Health Service undeployed successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to undeploy SeedCore Health Service: {e}")
        return False

if __name__ == "__main__":
    # Deploy the application when run directly
    deploy_health_service() 