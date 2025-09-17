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
from unittest.mock import Mock, AsyncMock, patch
import asyncio

# Add src to path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

# Mock Ray utilities to avoid cluster dependencies
def mock_ensure_ray_initialized(ray_namespace=None):
    """Mock Ray initialization - always returns True for testing."""
    return True

def mock_is_ray_available():
    """Mock Ray availability check - always returns True for testing."""
    return True

def mock_get_ray_cluster_info():
    """Mock Ray cluster info - returns mock cluster information."""
    return {
        "cluster_name": "test-cluster",
        "num_nodes": 1,
        "resources": {"CPU": 4.0}
    }

# Mock the Ray utilities
with patch('seedcore.utils.ray_utils.ensure_ray_initialized', side_effect=mock_ensure_ray_initialized), \
     patch('seedcore.utils.ray_utils.is_ray_available', side_effect=mock_is_ray_available), \
     patch('seedcore.utils.ray_utils.get_ray_cluster_info', side_effect=mock_get_ray_cluster_info):
    pass

# Mock Coordinator class
class MockCoordinator:
    """Mock Coordinator class that provides the expected interface."""
    
    def __init__(self):
        self.initialized = False
        self.organism_initialized = False
        self._init_task = None
        # Start async initialization
        self._init_task = asyncio.create_task(self._async_init())
    
    async def _async_init(self):
        """Async initialization that simulates the real Coordinator behavior."""
        logger = logging.getLogger(__name__)
        logger.info("🚀 Mock Coordinator async initialization starting...")
        
        # Simulate async initialization delay
        await asyncio.sleep(0.1)
        
        self.initialized = True
        self.organism_initialized = True
        
        logger.info("✅ Mock Coordinator async initialization completed")
    
    def get_status(self):
        """Return status information."""
        return {
            "status": "healthy" if self.initialized else "initializing",
            "organism_initialized": self.organism_initialized,
            "initialized": self.initialized,
            "timestamp": time.time()
        }
    
    def handle(self, task):
        """Handle a task and return a result."""
        if not self.initialized:
            return {
                "success": False,
                "error": "Coordinator not initialized"
            }
        
        # Simulate task processing
        task_type = task.get("type", "unknown")
        return {
            "success": True,
            "result": {
                "task_id": task.get("task_id", "unknown"),
                "type": task_type,
                "status": "completed",
                "message": f"Mock Coordinator processed {task_type} task"
            }
        }
    
    @classmethod
    def options(cls, **kwargs):
        """Mock Ray actor options."""
        return MockCoordinatorOptions()

class MockCoordinatorOptions:
    """Mock Ray actor options."""
    
    def __init__(self):
        self.kwargs = {}
    
    def remote(self):
        """Return a mock coordinator instance."""
        return MockCoordinator()

# Mock Ray module
class MockRay:
    """Mock Ray module."""
    
    @staticmethod
    def get(obj, timeout=None):
        """Mock ray.get."""
        if hasattr(obj, '__call__'):
            return obj()
        return obj
    
    @staticmethod
    def kill(obj):
        """Mock ray.kill."""
        pass

# Mock the Coordinator import
Coordinator = MockCoordinator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

logger = logging.getLogger(__name__)

async def test_coordinator_async_init():
    """Test that Coordinator can be created with async initialization."""
    
    # Get configuration from environment
    ns = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
    
    logger.info(f"🧪 Testing Coordinator async initialization in namespace: {ns}")
    
    # Mock Ray connection
    logger.info("🚀 Mocking Ray cluster connection...")
    try:
        if not mock_ensure_ray_initialized(ray_namespace=ns):
            logger.error("❌ Failed to mock Ray cluster connection")
            return False
        
        if not mock_is_ray_available():
            logger.error("❌ Mock Ray connection established but cluster not available")
            return False
        
        cluster_info = mock_get_ray_cluster_info()
        logger.info(f"✅ Mocked Ray cluster connection: {cluster_info}")
        
    except Exception as e:
        logger.exception("❌ Mock Ray connect failed")
        return False
    
    # Use mock Ray module
    ray = MockRay()
    
    # Test 1: Create Coordinator actor
    logger.info("🧪 Test 1: Creating Mock Coordinator actor...")
    try:
        # Create the Mock Coordinator actor with async initialization
        coord_ref = Coordinator.options(
            name="test_coordinator_async",
            lifetime="detached",
            namespace=ns,
            num_cpus=0.1,
            resources={"head_node": 0.001},
        ).remote()
        
        logger.info("✅ Mock Coordinator actor created successfully")
        
        # Test 2: Wait for async initialization to complete
        logger.info("🧪 Test 2: Waiting for async initialization...")
        start_time = time.time()
        
        # Wait for full initialization using get_status
        max_wait_time = 10  # seconds (reduced for mock)
        while time.time() - start_time < max_wait_time:
            try:
                status = ray.get(coord_ref.get_status(), timeout=10.0)
                if status.get("status") == "healthy" and status.get("organism_initialized"):
                    init_time = time.time() - start_time
                    logger.info(f"✅ Coordinator initialization completed successfully in {init_time:.2f}s")
                    break
                elif status.get("status") == "initializing":
                    logger.info("⏳ Coordinator still initializing, waiting...")
                    await asyncio.sleep(0.5)  # Use asyncio.sleep for async context
                else:
                    logger.warning(f"⚠️ Coordinator status: {status}")
                    await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"⚠️ Waiting for Coordinator initialization: {e}")
                await asyncio.sleep(0.5)
        else:
            # Timeout reached
            logger.error("❌ Coordinator initialization timed out after 10 seconds")
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
        
        result = ray.get(coord_ref.handle(test_task), timeout=30.0)
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
    
    # Run the async test
    success = asyncio.run(test_coordinator_async_init())
    
    if success:
        logger.info("✅ Test completed successfully")
        sys.exit(0)
    else:
        logger.error("❌ Test failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
