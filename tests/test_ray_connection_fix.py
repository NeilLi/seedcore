#!/usr/bin/env python3
"""
Test script to verify the Ray connection fix works correctly.
"""

import os
import sys
import logging

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def teardown_module(module):
    """Ensure Ray is properly shut down after tests to prevent state contamination."""
    try:
        import ray
        if ray.is_initialized():
            ray.shutdown()
            logger.info("✅ Ray shut down in teardown_module")
    except Exception as e:
        logger.debug(f"Ray teardown skipped: {e}")

def test_ray_connection():
    """Test Ray connection using the centralized utility."""
    print("🧪 Testing Ray connection...")
    
    try:
        from seedcore.utils.ray_utils import ensure_ray_initialized
        
        # Test connection
        result = ensure_ray_initialized()
        print(f"✅ Ray connection result: {result}")
        
        if result:
            print("✅ Ray connection successful!")
            return True
        else:
            print("❌ Ray connection failed!")
            return False
            
    except Exception as e:
        print(f"❌ Ray connection test failed: {e}")
        return False

def test_agent_creation():
    """Test agent creation using the tier0 manager."""
    print("\n🧪 Testing agent creation...")
    
    try:
        from seedcore.tier0.tier0_manager import Tier0MemoryManager
        
        # Create manager
        manager = Tier0MemoryManager()
        print("✅ Tier0MemoryManager created successfully")
        
        # Try to create a simple agent
        agent_id = "test_agent_1"
        role_probs = {"E": 0.8, "S": 0.1, "O": 0.1}
        
        print(f"Creating agent: {agent_id}")
        result = manager.create_agent(agent_id, role_probs)
        print(f"✅ Agent creation result: {result}")
        
        # List agents
        agents = manager.list_agents()
        print(f"✅ Available agents: {agents}")
        
        return True
        
    except Exception as e:
        print(f"❌ Agent creation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_ray_status():
    """Test Ray status and context."""
    print("\n🧪 Testing Ray status...")
    
    try:
        import ray
        
        if ray.is_initialized():
            print("✅ Ray is initialized")
            
            # Get runtime context
            runtime_context = ray.get_runtime_context()
            print(f"✅ Ray namespace: {getattr(runtime_context, 'namespace', 'unknown')}")
            print(f"✅ Ray address: {getattr(runtime_context, 'gcs_address', 'unknown')}")
            
            # Get cluster resources
            try:
                resources = ray.cluster_resources()
                print(f"✅ Cluster resources: {dict(resources)}")
            except Exception as e:
                print(f"⚠️ Could not get cluster resources: {e}")
                
            return True
        else:
            print("❌ Ray is not initialized")
            return False
            
    except Exception as e:
        print(f"❌ Ray status test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("🚀 Starting Ray connection fix tests...\n")
    
    tests = [
        test_ray_connection,
        test_ray_status,
        test_agent_creation,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
    
    print(f"\n📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! The Ray connection fix is working correctly.")
        return 0
    else:
        print("⚠️ Some tests failed. Check the output above for details.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
