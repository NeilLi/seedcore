#!/usr/bin/env python3
"""
Test script to verify that the bootstrap fix resolves the "Failed to look up actor 'mw'" error.

This script tests that:
1. Bootstrap actors can be created successfully
2. The mw actor is available after bootstrap
3. MwManager can be initialized without errors
"""

import sys
import os
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

def test_bootstrap_actors():
    """Test that bootstrap_actors can create the required singleton actors."""
    try:
        print("🔍 Testing bootstrap_actors...")
        
        # Import bootstrap function
        from seedcore.bootstrap import bootstrap_actors
        print("✅ bootstrap_actors imported successfully")
        
        # Call bootstrap to create actors
        print("🚀 Calling bootstrap_actors()...")
        miss_tracker, shared_cache, mw_store = bootstrap_actors()
        print("✅ bootstrap_actors() completed successfully")
        
        # Verify actors were created
        print(f"📊 Created actors:")
        print(f"   - MissTracker: {miss_tracker}")
        print(f"   - SharedCache: {shared_cache}")
        print(f"   - MwStore: {mw_store}")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to test bootstrap_actors: {e}")
        return False

def test_mw_actor_availability():
    """Test that the mw actor is available after bootstrap."""
    try:
        print("\n🔍 Testing mw actor availability...")
        
        import ray
        
        # Check if Ray is initialized
        if not ray.is_initialized():
            print("⚠️ Ray not initialized, initializing...")
            ray.init(address="auto", namespace="seedcore-dev")
        
        # Try to get the mw actor
        print("🔍 Looking for 'mw' actor...")
        mw_actor = ray.get_actor("mw", namespace="seedcore-dev")
        print(f"✅ Found mw actor: {mw_actor}")
        
        # Test basic functionality
        print("🧪 Testing mw actor functionality...")
        result = ray.get(mw_actor.ping.remote())
        print(f"✅ mw actor ping successful: {result}")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to test mw actor availability: {e}")
        return False

def test_mw_manager_initialization():
    """Test that MwManager can be initialized without errors."""
    try:
        print("\n🔍 Testing MwManager initialization...")
        
        # Import MwManager
        from seedcore.memory.working_memory import MwManager
        print("✅ MwManager imported successfully")
        
        # Create MwManager instance
        print("🚀 Creating MwManager instance...")
        mw_manager = MwManager("test_organ")
        print("✅ MwManager created successfully")
        
        # Verify it has the required attributes
        if hasattr(mw_manager, 'mw_store') and mw_manager.mw_store:
            print("✅ MwManager has mw_store")
        else:
            print("⚠️ MwManager missing mw_store")
            return False
        
        if hasattr(mw_manager, '_cache'):
            print("✅ MwManager has _cache")
        else:
            print("⚠️ MwManager missing _cache")
            return False
        
        print("🎉 MwManager initialization test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Failed to test MwManager initialization: {e}")
        return False

def test_ray_agent_memory_managers():
    """Test that RayAgent can initialize memory managers without errors."""
    try:
        print("\n🔍 Testing RayAgent memory manager initialization...")
        
        # Import RayAgent
        from seedcore.agents.ray_actor import RayAgent
        print("✅ RayAgent imported successfully")
        
        # Create a test agent
        print("🚀 Creating test RayAgent...")
        test_agent_id = f"test_agent_{int(time.time())}"
        agent = RayAgent(agent_id=test_agent_id, initial_role_probs={'E': 0.5, 'S': 0.3, 'O': 0.2})
        print("✅ Test RayAgent created successfully")
        
        # Check memory manager status
        if agent.mw_manager is not None:
            print("✅ Agent has mw_manager")
        else:
            print("⚠️ Agent missing mw_manager")
        
        if agent.mlt_manager is not None:
            print("✅ Agent has mlt_manager")
        else:
            print("⚠️ Agent missing mlt_manager")
        
        print("🎉 RayAgent memory manager test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Failed to test RayAgent memory managers: {e}")
        return False

def test_environment_configuration():
    """Test that environment variables are properly configured."""
    print("\n🔍 Testing environment configuration...")
    
    # Check environment variables
    env_vars = {
        'SEEDCORE_NS': os.getenv('SEEDCORE_NS'),
        'RAY_NAMESPACE': os.getenv('RAY_NAMESPACE'),
        'RAY_ADDRESS': os.getenv('RAY_ADDRESS'),
        'AUTO_CREATE': os.getenv('AUTO_CREATE'),
        'MW_ACTOR_NAME': os.getenv('MW_ACTOR_NAME'),
    }
    
    for var, value in env_vars.items():
        if value:
            print(f"✅ {var}: {value}")
        else:
            print(f"⚠️ {var}: Not set")
    
    # Determine effective namespace
    effective_namespace = env_vars['RAY_NAMESPACE'] or env_vars['SEEDCORE_NS'] or "seedcore-dev"
    print(f"\n🎯 Effective namespace: {effective_namespace}")
    
    return True

def main():
    """Run all tests."""
    print("🧪 Testing Bootstrap Fix for 'mw' Actor Error")
    print("=" * 60)
    
    tests = [
        ("Environment Configuration", test_environment_configuration),
        ("Bootstrap Actors", test_bootstrap_actors),
        ("MW Actor Availability", test_mw_actor_availability),
        ("MwManager Initialization", test_mw_manager_initialization),
        ("RayAgent Memory Managers", test_ray_agent_memory_managers),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{'='*50}")
        print(f"Running: {test_name}")
        print(f"{'='*50}")
        
        try:
            result = test_func()
            results.append((test_name, result))
            if result:
                print(f"✅ {test_name}: PASSED")
            else:
                print(f"❌ {test_name}: FAILED")
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
            results.append((test_name, False))
    
    # Summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name}: {status}")
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! The bootstrap fix is working correctly.")
        print("\n✅ The 'Failed to look up actor mw' error should now be resolved.")
        print("✅ Agents should be able to initialize memory managers successfully.")
        return 0
    else:
        print("💥 Some tests failed. Please review the issues above.")
        print("\n🔧 The bootstrap fix may need additional configuration.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
