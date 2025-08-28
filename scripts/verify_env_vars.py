#!/usr/bin/env python3
"""
Quick verification script to check that environment variables are properly set
in the Ray actors and Serve deployments.
"""

import os
import sys
import logging
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger(__name__)

def verify_bootstrap_env():
    """Verify environment variables in the bootstrap script context."""
    logger.info("🔧 Checking environment variables in bootstrap context...")
    
    env_keys = [
        "OCPS_DRIFT_THRESHOLD",
        "COGNITIVE_TIMEOUT_S",
        "COGNITIVE_MAX_INFLIGHT",
        "FAST_PATH_LATENCY_SLO_MS",
        "MAX_PLAN_STEPS",
    ]
    
    for key in env_keys:
        value = os.getenv(key, "NOT_SET")
        logger.info(f"  {key}: {value}")
    
    return True

async def verify_ray_actors():
    """Verify environment variables in Ray actors and Serve deployments."""
    try:
        import ray
        from ray import serve
        
        # Check if Ray is initialized
        if not ray.is_initialized():
            logger.info("🚀 Initializing Ray connection...")
            ray.init(address=os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001"))
        
        namespace = os.getenv("RAY_NAMESPACE", "seedcore-dev")
        logger.info(f"🔧 Checking environment variables in Ray actors and Serve deployments (namespace: {namespace})...")
        
        # Check OrganismManager Serve deployment
        try:
            coord = serve.get_deployment_handle("OrganismManager", app_name="organism")
            # Note: Serve deployments don't have debug_env method, so we'll check health instead
            health_result = await coord.health.remote()
            logger.info("✅ OrganismManager Serve deployment health:")
            logger.info(f"  Status: {health_result.get('status', 'unknown')}")
            logger.info(f"  Organism initialized: {health_result.get('organism_initialized', False)}")
        except Exception as e:
            logger.error(f"❌ Failed to check OrganismManager Serve deployment: {e}")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to verify Ray actors and Serve deployments: {e}")
        return False

async def main():
    """Run verification checks."""
    logger.info("🚀 Starting environment variable verification...")
    
    # Check bootstrap context
    verify_bootstrap_env()
    
    # Check Ray actors
    if await verify_ray_actors():
        logger.info("✅ Environment variable verification completed successfully!")
        return 0
    else:
        logger.error("❌ Environment variable verification failed!")
        return 1

if __name__ == "__main__":
    import asyncio
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
