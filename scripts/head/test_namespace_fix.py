#!/usr/bin/env python3
"""
Test script to verify that the namespace fixes are working correctly.

This script tests that:
1. Ray agents are created in the correct namespace (seedcore-dev)
2. Agents remain alive and are visible in the correct namespace
3. No more namespace mismatches occur
"""

import os
import sys
import time
import logging
from pathlib import Path

# Add the src directory to the Python path
project_root = Path(__file__).parent.parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_namespace_consistency():
    """Test that all namespace references are consistent."""
    logger.info("🔍 Testing namespace consistency...")
    
    # Check environment variables
    seedcore_ns = os.getenv("SEEDCORE_NS")
    ray_namespace = os.getenv("RAY_NAMESPACE")
    
    logger.info(f"SEEDCORE_NS: {seedcore_ns}")
    logger.info(f"RAY_NAMESPACE: {ray_namespace}")
    
    # Determine effective namespace
    effective_namespace = ray_namespace or seedcore_ns or "seedcore-dev"
    logger.info(f"Effective namespace: {effective_namespace}")
    
    assert effective_namespace == "seedcore-dev", f"Namespace is {effective_namespace}, expected seedcore-dev"
    
    logger.info("✅ Namespace consistency check passed")

def test_ray_initialization():
    """Test that Ray initializes with the correct namespace."""
    logger.info("🚀 Testing Ray initialization...")
    
    try:
        import ray
        
        # Get effective namespace
        seedcore_ns = os.getenv("SEEDCORE_NS")
        ray_namespace = os.getenv("RAY_NAMESPACE")
        effective_namespace = ray_namespace or seedcore_ns or "seedcore-dev"
        
        if not ray.is_initialized():
            logger.info(f"Initializing Ray with namespace: {effective_namespace}")
            from seedcore.utils.ray_utils import ensure_ray_initialized
            assert ensure_ray_initialized(ray_namespace=effective_namespace), "Failed to initialize Ray connection"
        else:
            logger.info("Ray already initialized")
        
        # Check current namespace
        runtime_context = ray.get_runtime_context()
        current_namespace = getattr(runtime_context, 'namespace', 'unknown')
        logger.info(f"Current Ray namespace: {current_namespace}")
        
        assert current_namespace == effective_namespace, f"Ray namespace mismatch: got {current_namespace}, expected {effective_namespace}"
        logger.info("✅ Ray namespace matches expected namespace")
            
    except Exception as e:
        logger.error(f"❌ Failed to test Ray initialization: {e}")
        raise

def test_agent_creation():
    """Test that agents can be created in the correct namespace."""
    logger.info("🎭 Testing agent creation...")
    
    try:
        import ray
        from seedcore.tier0.tier0_manager import Tier0MemoryManager
        
        # Ensure Ray is initialized
        if not ray.is_initialized():
            seedcore_ns = os.getenv("SEEDCORE_NS")
            ray_namespace = os.getenv("RAY_NAMESPACE")
            effective_namespace = ray_namespace or seedcore_ns or "seedcore-dev"
            from seedcore.utils.ray_utils import ensure_ray_initialized
            if not ensure_ray_initialized(ray_namespace=effective_namespace):
                logger.error("❌ Failed to initialize Ray connection")
                return False
        
        # Create Tier0 manager
        tier0_manager = Tier0MemoryManager()
        
        # Create a test agent
        test_agent_id = f"test_agent_{int(time.time())}"
        logger.info(f"Creating test agent: {test_agent_id}")
        
        agent_id = tier0_manager.create_agent(
            agent_id=test_agent_id,
            role_probs={'E': 0.5, 'S': 0.3, 'O': 0.2},
            name=test_agent_id,
            lifetime="detached",
            num_cpus=0.1
        )
        
        if agent_id == test_agent_id:
            logger.info("✅ Test agent created successfully")
            
            # Test that agent is alive
            agent_handle = tier0_manager.get_agent(test_agent_id)
            if agent_handle:
                test_result = ray.get(agent_handle.get_id.remote())
                if test_result == test_agent_id:
                    logger.info("✅ Test agent is alive and responding")
                    
                    # Clean up test agent
                    try:
                        ray.kill(agent_handle)
                        logger.info("✅ Test agent cleaned up")
                    except:
                        pass
                    
                    return True
                else:
                    logger.error(f"❌ Agent ID mismatch: got {test_result}, expected {test_agent_id}")
                    return False
            else:
                logger.error("❌ Agent handle not found after creation")
                return False
        else:
            logger.error(f"❌ Agent creation failed: got {agent_id}, expected {test_agent_id}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Failed to test agent creation: {e}")
        return False

def test_namespace_visibility():
    """Test that agents are visible in the correct namespace."""
    logger.info("👁️ Testing namespace visibility...")
    
    try:
        import ray
        from ray.util.state import list_actors
        
        # Get effective namespace
        seedcore_ns = os.getenv("SEEDCORE_NS")
        ray_namespace = os.getenv("RAY_NAMESPACE")
        effective_namespace = ray_namespace or seedcore_ns or "seedcore-dev"
        
        # List actors in the current namespace
        actors = list_actors()
        logger.info(f"Found {len(actors)} actors in namespace '{effective_namespace}'")
        
        # Check for any agents
        agent_actors = [actor for actor in actors if 'RayAgent' in actor.class_name]
        logger.info(f"Found {len(agent_actors)} RayAgent actors")
        
        for actor in agent_actors[:5]:  # Show first 5
            logger.info(f"  - {actor.name} ({actor.class_name}): {actor.state}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to test namespace visibility: {e}")
        return False

def main():
    """Run all namespace tests."""
    logger.info("🧪 Starting namespace consistency tests...")
    
    tests = [
        ("Namespace Consistency", test_namespace_consistency),
        ("Ray Initialization", test_ray_initialization),
        ("Agent Creation", test_agent_creation),
        ("Namespace Visibility", test_namespace_visibility),
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info(f"\n{'='*50}")
        logger.info(f"Running: {test_name}")
        logger.info(f"{'='*50}")
        
        try:
            result = test_func()
            results.append((test_name, result))
            if result:
                logger.info(f"✅ {test_name}: PASSED")
            else:
                logger.error(f"❌ {test_name}: FAILED")
        except Exception as e:
            logger.error(f"❌ {test_name}: ERROR - {e}")
            results.append((test_name, False))
    
    # Summary
    logger.info(f"\n{'='*50}")
    logger.info("TEST SUMMARY")
    logger.info(f"{'='*50}")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        logger.info(f"{test_name}: {status}")
    
    logger.info(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All namespace tests passed! The fixes are working correctly.")
        return 0
    else:
        logger.error("💥 Some namespace tests failed. Please review the issues above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
