#!/usr/bin/env python3
"""
Test script for the centralized Ray connection utility.

This script tests the ensure_ray_initialized() function in different scenarios.
"""

import os
import sys
import logging

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from seedcore.utils.ray_utils import ensure_ray_initialized, is_ray_available, get_ray_cluster_info

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_basic_functionality():
    """Test basic Ray initialization functionality."""
    print("🧪 Testing basic Ray initialization...")
    
    try:
        # Test 1: Basic initialization
        result = ensure_ray_initialized()
        print(f"✅ Basic initialization: {result}")
        
        # Test 2: Check if Ray is available
        available = is_ray_available()
        print(f"✅ Ray available: {available}")
        
        # Test 3: Get cluster info
        cluster_info = get_ray_cluster_info()
        print(f"✅ Cluster info: {cluster_info}")
        
        return True
    except Exception as e:
        print(f"❌ Basic functionality test failed: {e}")
        return False

def test_environment_variables():
    """Test Ray initialization with different environment variables."""
    print("\n🧪 Testing environment variable handling...")
    
    # Test with explicit RAY_ADDRESS
    os.environ['RAY_ADDRESS'] = 'ray://localhost:10001'
    try:
        result = ensure_ray_initialized()
        print(f"✅ With RAY_ADDRESS=ray://localhost:10001: {result}")
    except Exception as e:
        print(f"⚠️ With RAY_ADDRESS=ray://localhost:10001: {e}")
    
    # Test with custom namespace
    try:
        result = ensure_ray_initialized(ray_namespace="test-namespace")
        print(f"✅ With custom namespace 'test-namespace': {result}")
    except Exception as e:
        print(f"⚠️ With custom namespace 'test-namespace': {e}")
    
    # Clean up
    if 'RAY_ADDRESS' in os.environ:
        del os.environ['RAY_ADDRESS']
    
    return True

def test_idempotency():
    """Test that the function is idempotent (safe to call multiple times)."""
    print("\n🧪 Testing idempotency...")
    
    try:
        # Call multiple times
        result1 = ensure_ray_initialized()
        result2 = ensure_ray_initialized()
        result3 = ensure_ray_initialized()
        
        print(f"✅ First call: {result1}")
        print(f"✅ Second call: {result2}")
        print(f"✅ Third call: {result3}")
        
        # All should return True
        if result1 and result2 and result3:
            print("✅ Idempotency test passed - all calls returned True")
            return True
        else:
            print("❌ Idempotency test failed - not all calls returned True")
            return False
            
    except Exception as e:
        print(f"❌ Idempotency test failed: {e}")
        return False

def test_connection_info():
    """Test getting connection information."""
    print("\n🧪 Testing connection information...")
    
    try:
        # Get detailed cluster info
        cluster_info = get_ray_cluster_info()
        
        print("📊 Cluster Information:")
        for key, value in cluster_info.items():
            if key in ['cluster_resources', 'available_resources'] and isinstance(value, dict):
                print(f"  {key}:")
                for resource, amount in value.items():
                    print(f"    {resource}: {amount}")
            else:
                print(f"  {key}: {value}")
        
        return True
    except Exception as e:
        print(f"❌ Connection info test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("🚀 Starting centralized Ray utility tests...\n")
    
    tests = [
        test_basic_functionality,
        test_environment_variables,
        test_idempotency,
        test_connection_info,
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
        print("🎉 All tests passed! The centralized Ray utility is working correctly.")
        return 0
    else:
        print("⚠️ Some tests failed. Check the output above for details.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

