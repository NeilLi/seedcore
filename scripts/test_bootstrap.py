#!/usr/bin/env python3
"""
Test script to verify the bootstrap functionality and test health checks.
This script can be used to test the Coordinator and Dispatcher actors after bootstrap.
"""

import os
import sys
import time
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from seedcore.utils.ray_utils import ensure_ray_initialized, is_ray_available, get_ray_cluster_info

def test_ray_connection():
    """Test Ray connection and get cluster info."""
    print("🔍 Testing Ray connection...")
    
    # Get namespace from environment
    ns = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
    print(f"📋 Using namespace: {ns}")
    
    # Test Ray connection
    if not ensure_ray_initialized(ray_namespace=ns):
        print("❌ Failed to connect to Ray")
        return False
    
    if not is_ray_available():
        print("❌ Ray connection established but cluster not available")
        return False
    
    # Get cluster info
    cluster_info = get_ray_cluster_info()
    print(f"✅ Ray cluster info: {cluster_info}")
    return True

def test_coordinator_health():
    """Test Coordinator actor health."""
    print("\n🔍 Testing Coordinator health...")
    
    try:
        import ray
        ns = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
        
        # Try to get Coordinator actor
        coord = ray.get_actor("seedcore_coordinator", namespace=ns)
        print("✅ Coordinator actor found")
        
        # Test ping
        ping_ref = coord.ping.remote()
        ping_result = ray.get(ping_ref, timeout=10.0)
        if ping_result == "pong":
            print("✅ Coordinator ping successful")
            return True
        else:
            print(f"⚠️ Coordinator ping returned unexpected result: {ping_result}")
            return False
            
    except Exception as e:
        print(f"❌ Coordinator health check failed: {e}")
        return False

def test_dispatcher_health():
    """Test Dispatcher actors health."""
    print("\n🔍 Testing Dispatcher health...")
    
    try:
        import ray
        ns = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
        
        # Check for dispatcher actors
        dispatcher_count = int(os.getenv("SEEDCORE_DISPATCHERS", "2"))
        healthy_dispatchers = 0
        
        for i in range(dispatcher_count):
            dispatcher_name = f"seedcore_dispatcher_{i}"
            try:
                dispatcher = ray.get_actor(dispatcher_name, namespace=ns)
                print(f"✅ Dispatcher {dispatcher_name} found")
                
                # Test ping
                ping_ref = dispatcher.ping.remote()
                ping_result = ray.get(ping_ref, timeout=5.0)
                if ping_result == "pong":
                    print(f"✅ Dispatcher {dispatcher_name} ping successful")
                    healthy_dispatchers += 1
                else:
                    print(f"⚠️ Dispatcher {dispatcher_name} ping returned unexpected result: {ping_result}")
                    
            except Exception as e:
                print(f"❌ Dispatcher {dispatcher_name} health check failed: {e}")
        
        print(f"📊 Healthy dispatchers: {healthy_dispatchers}/{dispatcher_count}")
        return healthy_dispatchers > 0
        
    except Exception as e:
        print(f"❌ Dispatcher health check failed: {e}")
        return False

def test_reaper_health():
    """Test Reaper actor health."""
    print("\n🔍 Testing Reaper health...")
    
    try:
        import ray
        ns = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
        
        # Try to get Reaper actor
        reaper = ray.get_actor("seedcore_reaper", namespace=ns)
        print("✅ Reaper actor found")
        
        # Test ping
        ping_ref = reaper.ping.remote()
        ping_result = ray.get(ping_ref, timeout=5.0)
        if ping_result == "pong":
            print("✅ Reaper ping successful")
            return True
        else:
            print(f"⚠️ Reaper ping returned unexpected result: {ping_result}")
            return False
            
    except Exception as e:
        print(f"ℹ️ Reaper health check skipped: {e}")
        return False

def test_task_creation():
    """Test creating a simple task to verify the system works."""
    print("\n🔍 Testing task creation...")
    
    try:
        import ray
        import uuid
        ns = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
        
        # Get Coordinator actor
        coord = ray.get_actor("seedcore_coordinator", namespace=ns)
        
        # Create a simple test task
        test_task = {
            "type": "get_organism_status",
            "params": {},
            "description": "Test task for bootstrap verification",
            "domain": None,
            "drift_score": 0.0
        }
        
        # Submit task to Coordinator
        result_ref = coord.handle.remote(test_task)
        result = ray.get(result_ref, timeout=30.0)
        
        print(f"✅ Task submitted successfully: {result}")
        return True
        
    except Exception as e:
        print(f"❌ Task creation test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("🚀 Starting bootstrap verification tests...")
    print("=" * 50)
    
    tests = [
        ("Ray Connection", test_ray_connection),
        ("Coordinator Health", test_coordinator_health),
        ("Dispatcher Health", test_dispatcher_health),
        ("Reaper Health", test_reaper_health),
        ("Task Creation", test_task_creation),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ Test '{test_name}' failed with exception: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Test Results Summary:")
    print("=" * 50)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
        if result:
            passed += 1
    
    print(f"\n📈 Overall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Bootstrap is working correctly.")
        return 0
    else:
        print("⚠️ Some tests failed. Check the logs above for details.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
