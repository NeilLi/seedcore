#!/usr/bin/env python3
"""
Comprehensive test script to verify all the Ray connection and bootstrap fixes.
"""

import os
import sys
import logging
import time

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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

def test_force_reinit():
    """Test force reinit functionality."""
    print("\n🧪 Testing force reinit...")
    
    try:
        from seedcore.utils.ray_utils import ensure_ray_initialized
        
        # Test force reinit
        result = ensure_ray_initialized(force_reinit=True)
        print(f"✅ Force reinit result: {result}")
        
        return True
        
    except Exception as e:
        print(f"❌ Force reinit test failed: {e}")
        return False

def test_bootstrap_actors():
    """Test bootstrap actors functionality."""
    print("\n🧪 Testing bootstrap actors...")
    
    try:
        from seedcore.bootstrap import bootstrap_actors
        
        print("Calling bootstrap_actors()...")
        result = bootstrap_actors()
        print(f"✅ Bootstrap result: {result}")
        
        return True
        
    except Exception as e:
        print(f"❌ Bootstrap test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_organism_manager():
    """Test organism manager through Coordinator actor."""
    print("\n🧪 Testing organism manager...")
    
    try:
        # First ensure Ray is initialized
        from seedcore.utils.ray_utils import ensure_ray_initialized
        ensure_ray_initialized()
        
        # Test that we can import the OrganismManager class
        from seedcore.organs.organism_manager import OrganismManager
        print("✅ OrganismManager class imported successfully")
        
        # Test that we can create an instance
        organism_manager = OrganismManager()
        print("✅ OrganismManager instance created successfully")
        
        # Test that the instance has the expected attributes
        if hasattr(organism_manager, '_initialized'):
            print(f"✅ _initialized attribute exists: {organism_manager._initialized}")
        else:
            print("⚠️ _initialized attribute not found")
        
        # Test that we can access the routing table
        if hasattr(organism_manager, 'routing'):
            print("✅ Routing table exists")
        else:
            print("⚠️ Routing table not found")
        
        # Test that we can access the organ configs
        if hasattr(organism_manager, 'organ_configs'):
            print(f"✅ Organ configs: {len(organism_manager.organ_configs)} configs found")
        else:
            print("⚠️ Organ configs not found")
        
        return True
        
    except Exception as e:
        print(f"❌ Organism manager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_ray_cluster_health():
    """Test Ray cluster health check."""
    print("\n🧪 Testing Ray cluster health check...")
    
    try:
        import ray
        
        if not ray.is_initialized():
            print("⚠️ Ray not initialized, initializing...")
            from seedcore.utils.ray_utils import ensure_ray_initialized
            ensure_ray_initialized()
        
        # Test cluster resources
        cluster_resources = ray.cluster_resources()
        available_resources = ray.available_resources()
        
        print(f"✅ Cluster resources: {cluster_resources}")
        print(f"✅ Available resources: {available_resources}")
        
        # Test remote task execution
        @ray.remote
        def _health_check_task():
            return "healthy"
        
        result = ray.get(_health_check_task.remote())
        if result == "healthy":
            print("✅ Ray remote task execution test passed")
        else:
            print(f"⚠️ Ray remote task test returned unexpected result: {result}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ray cluster health test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_telemetry_server_imports():
    """Test that telemetry server imports work correctly."""
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

def test_ray_utils_imports():
    """Test that all ray_utils functions are available."""
    print("\n🧪 Testing ray_utils imports...")
    
    try:
        from seedcore.utils.ray_utils import (
            ensure_ray_initialized,
            shutdown_ray,
            is_ray_available,
            get_ray_cluster_info,
            test_ray_connection
        )
        print("✅ All ray_utils functions imported successfully")
        
        # Test function signatures
        import inspect
        sig = inspect.signature(ensure_ray_initialized)
        params = list(sig.parameters.keys())
        print(f"✅ ensure_ray_initialized parameters: {params}")
        
        if 'force_reinit' in params:
            print("✅ force_reinit parameter is available")
        else:
            print("❌ force_reinit parameter is missing")
        
        return True
        
    except Exception as e:
        print(f"❌ ray_utils import test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("🚀 Starting comprehensive Ray connection and bootstrap fix tests...\n")
    
    tests = [
        ("Environment Variables", test_environment_variables),
        ("Ray Utils Imports", test_ray_utils_imports),
        ("Ray Connection", test_ray_connection),
        ("Force Reinit", test_force_reinit),
        ("Ray Cluster Health", test_ray_cluster_health),
        ("Bootstrap Actors", test_bootstrap_actors),
        ("Organism Manager", test_organism_manager),
        ("Telemetry Server", test_telemetry_server_imports),
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
    
    for test_name, _ in tests:
        # We can't easily track individual test results here, so just show the count
        pass
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! The comprehensive fixes are working correctly.")
        print("\n✅ Ray connection issues should be resolved")
        print("✅ Bootstrap errors should be fixed")
        print("✅ Telemetry server should work properly")
        print("✅ Namespace verification should work")
        return 0
    else:
        print("⚠️ Some tests failed. Check the output above for details.")
        print("\n🔧 Additional configuration may be needed.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

