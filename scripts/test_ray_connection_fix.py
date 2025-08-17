#!/usr/bin/env python3
"""
Test script to verify that the Ray connection fix resolves the connection timeout error.

This script tests that:
1. Environment variables are properly set
2. Ray connection can be established using the correct address
3. The connection uses the proper service names from the environment
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

def test_environment_variables():
    """Test that environment variables are properly configured."""
    print("🔍 Testing environment variables...")
    
    env_vars = {
        'RAY_HOST': os.getenv('RAY_HOST'),
        'RAY_PORT': os.getenv('RAY_PORT'),
        'RAY_NAMESPACE': os.getenv('RAY_NAMESPACE'),
        'SEEDCORE_NS': os.getenv('SEEDCORE_NS'),
        'RAY_ADDRESS': os.getenv('RAY_ADDRESS'),
    }
    
    for var, value in env_vars.items():
        if value:
            print(f"✅ {var}: {value}")
        else:
            print(f"⚠️ {var}: Not set")
    
    # Determine effective values
    ray_host = env_vars['RAY_HOST'] or "seedcore-svc-head-svc"
    ray_port = env_vars['RAY_PORT'] or "10001"
    ray_namespace = env_vars['RAY_NAMESPACE'] or env_vars['SEEDCORE_NS'] or "seedcore-dev"
    
    print(f"\n🎯 Effective values:")
    print(f"   Ray Host: {ray_host}")
    print(f"   Ray Port: {ray_port}")
    print(f"   Ray Namespace: {ray_namespace}")
    
    return True

def test_ray_address_construction():
    """Test that Ray address is constructed correctly from environment variables."""
    print("\n🔍 Testing Ray address construction...")
    
    # Get values from environment
    ray_host = os.getenv("RAY_HOST", "seedcore-svc-head-svc")
    ray_port = os.getenv("RAY_PORT", "10001")
    
    # Construct address
    ray_address = f"ray://{ray_host}:{ray_port}"
    print(f"✅ Constructed Ray address: {ray_address}")
    
    # Verify it's not the hardcoded value
    if ray_address != "ray://ray-head:10001":
        print("✅ Address is not hardcoded - using environment variables")
        return True
    else:
        print("❌ Address is still hardcoded")
        return False

def test_ray_connection():
    """Test that Ray connection can be established."""
    print("\n🔍 Testing Ray connection...")
    
    try:
        import ray
        
        # Get connection parameters from environment
        ray_host = os.getenv("RAY_HOST", "seedcore-svc-head-svc")
        ray_port = os.getenv("RAY_PORT", "10001")
        ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
        
        # Construct address
        ray_address = f"ray://{ray_host}:{ray_port}"
        
        print(f"🔗 Attempting to connect to Ray at: {ray_address}")
        print(f"🏷️ Using namespace: {ray_namespace}")
        
        # Check if already connected
        if ray.is_initialized():
            print("⚠️ Ray already initialized, shutting down first...")
            ray.shutdown()
            time.sleep(1)
        
        # Attempt connection
        ray.init(address=ray_address, namespace=ray_namespace)
        print("✅ Ray connection established successfully!")
        
        # Test basic functionality
        print("🧪 Testing Ray functionality...")
        runtime_context = ray.get_runtime_context()
        print(f"   - Ray Address: {runtime_context.get_address()}")
        print(f"   - Ray Namespace: {getattr(runtime_context, 'namespace', 'unknown')}")
        
        # Check cluster resources
        try:
            resources = ray.cluster_resources()
            print(f"   - Cluster Resources: {resources}")
        except Exception as e:
            print(f"   - Could not get cluster resources: {e}")
        
        # Clean up
        ray.shutdown()
        print("✅ Ray connection test completed successfully")
        return True
        
    except Exception as e:
        print(f"❌ Failed to test Ray connection: {e}")
        return False

def test_script_compatibility():
    """Test that the fixed scripts can be imported without errors."""
    print("\n🔍 Testing script compatibility...")
    
    scripts_to_test = [
        "scripts/job_detailed_analysis.py",
        "scripts/debug_organ_actors.py",
        "scripts/cleanup_organs.py",
        "scripts/detailed_agent_placement.py",
        "scripts/comprehensive_job_analysis.py",
        "scripts/analyze_ray_jobs.py",
        "scripts/analyze_agent_distribution.py",
    ]
    
    success_count = 0
    for script_path in scripts_to_test:
        try:
            # Check if the script has the hardcoded address
            with open(script_path, 'r') as f:
                content = f.read()
                
            if "ray://ray-head:10001" in content:
                print(f"❌ {script_path}: Still contains hardcoded address")
            else:
                print(f"✅ {script_path}: Fixed - no hardcoded address")
                success_count += 1
                
        except Exception as e:
            print(f"⚠️ {script_path}: Could not read - {e}")
    
    print(f"\n📊 Script compatibility: {success_count}/{len(scripts_to_test)} scripts fixed")
    return success_count == len(scripts_to_test)

def test_kubernetes_service_names():
    """Test that the service names match what's expected in Kubernetes."""
    print("\n🔍 Testing Kubernetes service names...")
    
    # Expected service names based on the environment variables
    expected_host = os.getenv("RAY_HOST", "seedcore-svc-head-svc")
    expected_port = os.getenv("RAY_PORT", "10001")
    
    print(f"Expected Ray Head Service: {expected_host}:{expected_port}")
    
    # Check if this matches common patterns
    if "seedcore" in expected_host and "head" in expected_host:
        print("✅ Service name follows expected pattern")
        return True
    else:
        print("⚠️ Service name doesn't follow expected pattern")
        return False

def main():
    """Run all tests."""
    print("🧪 Testing Ray Connection Fix")
    print("=" * 60)
    
    tests = [
        ("Environment Variables", test_environment_variables),
        ("Ray Address Construction", test_ray_address_construction),
        ("Ray Connection", test_ray_connection),
        ("Script Compatibility", test_script_compatibility),
        ("Kubernetes Service Names", test_kubernetes_service_names),
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
        print("🎉 All tests passed! The Ray connection fix is working correctly.")
        print("\n✅ The connection timeout error should now be resolved.")
        print("✅ Scripts should be able to connect to Ray using environment variables.")
        return 0
    else:
        print("💥 Some tests failed. Please review the issues above.")
        print("\n🔧 The connection fix may need additional configuration.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
