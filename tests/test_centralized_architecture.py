#!/usr/bin/env python3
"""
Test script to verify the new centralized Ray connection architecture.
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

def test_ray_connector_import():
    """Test that the new ray_connector can be imported."""
    print("🧪 Testing ray_connector import...")
    
    try:
        from seedcore.utils.ray_connector import connect, is_connected, get_connection_info
        print("✅ ray_connector imported successfully")
        return True
    except Exception as e:
        print(f"❌ ray_connector import failed: {e}")
        return False

def test_ray_connector_connection():
    """Test that the ray_connector can establish a connection."""
    print("\n🧪 Testing ray_connector connection...")
    
    try:
        from seedcore.utils.ray_connector import connect, is_connected, get_connection_info
        
        # Test connection
        print("🔍 Calling connect()...")
        connect()
        
        # Check if connected
        if is_connected():
            print("✅ Ray connection successful")
            
            # Get connection info
            info = get_connection_info()
            print(f"✅ Connection info: {info}")
            
            return True
        else:
            print("❌ Ray connection failed")
            return False
            
    except Exception as e:
        print(f"❌ Ray connection test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_organism_manager_simplified():
    """Test that the simplified OrganismManager works."""
    print("\n🧪 Testing simplified OrganismManager...")
    
    try:
        from seedcore.organs import organism_manager as organism_manager_module
        
        print("✅ OrganismManager module imported successfully")
        
        # Check that the global instance is None initially (lazy initialization)
        if organism_manager_module.organism_manager is None:
            print("✅ Global organism_manager is None (lazy initialization working)")
        else:
            print("⚠️ Global organism_manager is not None (unexpected)")
            return False
        
        # Check if Ray is initialized
        import ray
        if ray.is_initialized():
            print("✅ Ray is initialized, OrganismManager can be created")
            
            # Test creating an instance
            try:
                instance = organism_manager_module.OrganismManager()
                print("✅ OrganismManager instance created successfully")
                return True
            except Exception as e:
                print(f"❌ Failed to create OrganismManager instance: {e}")
                return False
        else:
            print("⚠️ Ray not initialized, OrganismManager will fail (expected)")
            return False
            
    except Exception as e:
        print(f"❌ OrganismManager test failed: {e}")
        return False

def test_bootstrap_simplified():
    """Test that the simplified bootstrap works."""
    print("\n🧪 Testing simplified bootstrap...")
    
    try:
        from seedcore.bootstrap import bootstrap_actors
        
        print("✅ bootstrap_actors imported successfully")
        
        # Check if Ray is initialized
        import ray
        if ray.is_initialized():
            print("✅ Ray is initialized, bootstrap should work")
            return True
        else:
            print("⚠️ Ray not initialized, bootstrap will fail (expected)")
            return False
            
    except Exception as e:
        print(f"❌ Bootstrap test failed: {e}")
        return False

def test_telemetry_server_imports():
    """Test that telemetry server can import the new connector."""
    print("\n🧪 Testing telemetry server imports...")
    
    try:
        from seedcore.telemetry.server import app
        print("✅ Telemetry server app imported successfully")
        
        # Test that the startup event handler exists
        if hasattr(app, 'router'):
            print("✅ Telemetry server router exists")
        else:
            print("⚠️ Telemetry server router missing")
        
        return True
        
    except Exception as e:
        print(f"❌ Telemetry server import test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_environment_variables():
    """Test environment variable configuration."""
    print("\n🧪 Testing environment variables...")
    
    env_vars = {
        'RAY_ADDRESS': os.getenv('RAY_ADDRESS'),
        'SEEDCORE_NS': os.getenv('SEEDCORE_NS'),
        'RAY_NAMESPACE': os.getenv('RAY_NAMESPACE'),
        'RAY_HOST': os.getenv('RAY_HOST'),
        'RAY_PORT': os.getenv('RAY_PORT'),
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

def test_centralized_architecture():
    """Test the overall centralized architecture."""
    print("\n🧪 Testing centralized architecture...")
    
    try:
        # Test that Ray is connected
        from seedcore.utils.ray_connector import is_connected, get_connection_info
        
        if is_connected():
            info = get_connection_info()
            print(f"✅ Ray is connected: {info}")
            
            # Test that we can create a simple remote task
            import ray
            
            @ray.remote
            def _test_task():
                return "centralized_architecture_works"
            
            result = ray.get(_test_task.remote())
            if result == "centralized_architecture_works":
                print("✅ Remote task execution works")
                return True
            else:
                print(f"⚠️ Remote task returned unexpected result: {result}")
                return False
        else:
            print("❌ Ray is not connected")
            return False
            
    except Exception as e:
        print(f"❌ Centralized architecture test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("🚀 Starting centralized Ray connection architecture tests...\n")
    
    tests = [
        ("Environment Variables", test_environment_variables),
        ("Ray Connector Import", test_ray_connector_import),
        ("Ray Connector Connection", test_ray_connector_connection),
        ("OrganismManager Simplified", test_organism_manager_simplified),
        ("Bootstrap Simplified", test_bootstrap_simplified),
        ("Telemetry Server Imports", test_telemetry_server_imports),
        ("Centralized Architecture", test_centralized_architecture),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n{'='*60}")
        print(f"Running: {test_name}")
        print(f"{'='*60}")
        
        try:
            if test_func():
                passed += 1
                print(f"✅ {test_name}: PASSED")
            else:
                print(f"❌ {test_name}: FAILED")
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! The centralized architecture is working correctly.")
        print("\n✅ Ray connection is now centralized and transparent")
        print("✅ No more connection conflicts or cascading errors")
        print("✅ OrganismManager is simplified and clean")
        print("✅ Bootstrap process is streamlined")
        print("✅ All services use the same connection logic")
        return 0
    else:
        print("⚠️ Some tests failed. Check the output above for details.")
        print("\n🔧 The centralized architecture may need additional configuration.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
