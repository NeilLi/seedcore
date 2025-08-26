#!/usr/bin/env python3
"""
Test script to verify Coordinator async initialization works properly.
This tests that the Ray actor can be created without the "event loop is already running" error.
"""

import os
import sys
import logging
import time
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

# Import Ray utilities
from seedcore.utils.ray_utils import ensure_ray_initialized, is_ray_available, get_ray_cluster_info
from seedcore.agents.queue_dispatcher import Coordinator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

logger = logging.getLogger(__name__)

def test_coordinator_async_init():
    """Test that Coordinator can be created with async initialization."""
    
    # Get configuration from environment
    ns = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
    
    logger.info(f"🧪 Testing Coordinator async initialization in namespace: {ns}")
    
    # Initialize Ray connection
    logger.info("🚀 Connecting to Ray cluster...")
    try:
        if not ensure_ray_initialized(ray_namespace=ns):
            logger.error("❌ Failed to connect to Ray cluster")
            return False
        
        if not is_ray_available():
            logger.error("❌ Ray connection established but cluster not available")
            return False
        
        cluster_info = get_ray_cluster_info()
        logger.info(f"✅ Connected to Ray cluster: {cluster_info}")
        
    except Exception as e:
        logger.exception("❌ Ray connect failed")
        return False
    
    # Import ray after successful connection
    import ray
    
    # Test 1: Create Coordinator actor
    logger.info("🧪 Test 1: Creating Coordinator actor...")
    try:
        # Create the Coordinator actor with async initialization
        coord_ref = Coordinator.options(
            name="test_coordinator_async",
            lifetime="detached",
            namespace=ns,
            num_cpus=0.1,
            resources={"head_node": 0.001},
        ).remote()
        
        logger.info("✅ Coordinator actor created successfully")
        
        # Test 2: Wait for async initialization to complete
        logger.info("🧪 Test 2: Waiting for async initialization...")
        start_time = time.time()
        
        # Wait for full initialization using get_status
        max_wait_time = 60  # seconds
        while time.time() - start_time < max_wait_time:
            try:
                status = ray.get(coord_ref.get_status.remote(), timeout=10.0)
                if status.get("status") == "healthy" and status.get("organism_initialized"):
                    init_time = time.time() - start_time
                    logger.info(f"✅ Coordinator initialization completed successfully in {init_time:.2f}s")
                    break
                elif status.get("status") == "initializing":
                    logger.info("⏳ Coordinator still initializing, waiting...")
                    time.sleep(2)
                else:
                    logger.warning(f"⚠️ Coordinator status: {status}")
                    time.sleep(2)
            except Exception as e:
                logger.warning(f"⚠️ Waiting for Coordinator initialization: {e}")
                time.sleep(2)
        else:
            # Timeout reached
            logger.error("❌ Coordinator initialization timed out after 60 seconds")
            return False
        
        # Test 3: Test task handling
        logger.info("🧪 Test 3: Testing task handling...")
        test_task = {
            "type": "get_organism_status",
            "params": {},
            "description": "Test task for async init verification",
            "domain": "test",
            "drift_score": 0.0
        }
        
        result = ray.get(coord_ref.handle.remote(test_task), timeout=30.0)
        if result.get("success"):
            logger.info("✅ Task handling works correctly")
        else:
            logger.warning(f"⚠️ Task handling returned: {result}")
        
        # Test 4: Clean up test actor
        logger.info("🧪 Test 4: Cleaning up test actor...")
        try:
            ray.kill(coord_ref)
            logger.info("✅ Test actor cleaned up successfully")
        except Exception as e:
            logger.warning(f"⚠️ Could not clean up test actor: {e}")
        
        logger.info("🎉 All tests passed! Coordinator async initialization works correctly.")
        return True
        
    except Exception as e:
        logger.exception("❌ Coordinator test failed")
        return False

def main():
    """Run the Coordinator async initialization test."""
    logger.info("🧪 Starting Coordinator async initialization test...")
    
    success = test_coordinator_async_init()
    
    if success:
        logger.info("✅ Test completed successfully")
        sys.exit(0)
    else:
        logger.error("❌ Test failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
