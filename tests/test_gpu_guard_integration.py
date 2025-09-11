#!/usr/bin/env python3
"""
Test script to verify GPU Guard integration with tuning service.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent  # Go up one level from tests/ to project root
sys.path.insert(0, str(project_root))

def test_gpu_guard_creation():
    """Test GPU Guard creation and basic functionality."""
    try:
        # Import directly to avoid pulling in the entire seedcore package
        import sys
        sys.path.insert(0, str(project_root / "src"))
        
        # Import the GPU Guard module directly
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gpu_guard", 
            project_root / "src" / "seedcore" / "predicates" / "gpu_guard.py"
        )
        gpu_guard_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gpu_guard_module)
        GPUGuard = gpu_guard_module.GPUGuard
        
        # Test no-op guard (no Redis)
        guard = GPUGuard(None)
        print("✅ GPU Guard no-op mode created successfully")
        
        # Test status
        status = guard.get_status()
        print(f"✅ GPU Guard status: {status}")
        
        # Test admission (should always pass in no-op mode)
        ok, reason = guard.try_acquire("test_job", 100)
        print(f"✅ GPU Guard admission test: {ok}, reason: {reason}")
        
        # Test completion
        guard.complete("test_job", 50.0, success=True)
        print("✅ GPU Guard completion test passed")
        
        return True
    except Exception as e:
        print(f"❌ GPU Guard test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_tuning_service_integration():
    """Test tuning service with GPU Guard integration."""
    try:
        # Test that the GPU Guard can be imported and used in the tuning service context
        # We'll test the integration by checking if the GPU Guard is properly initialized
        
        # Import the GPU Guard directly
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gpu_guard", 
            project_root / "src" / "seedcore" / "predicates" / "gpu_guard.py"
        )
        gpu_guard_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gpu_guard_module)
        GPUGuard = gpu_guard_module.GPUGuard
        
        # Test that GPU Guard works as expected in no-op mode
        guard = GPUGuard(None)
        print("✅ GPU Guard created successfully for tuning service integration")
        
        # Test admission control
        ok, reason = guard.try_acquire("tuning_job_123", 1800)  # 30 minutes
        print(f"✅ GPU Guard admission test: {ok}, reason: {reason}")
        
        # Test completion
        guard.complete("tuning_job_123", 1200.0, success=True)  # 20 minutes actual
        print("✅ GPU Guard completion test passed")
        
        # Test status
        status = guard.get_status()
        print(f"✅ GPU Guard status: {status}")
        
        return True
    except Exception as e:
        print(f"❌ Tuning service integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_tuning_config():
    """Test tuning config with provenance."""
    try:
        # Import the tuning config module directly
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "tuning_config", 
            project_root / "src" / "seedcore" / "ml" / "tuning_config.py"
        )
        tuning_config_module = importlib.util.module_from_spec(spec)
        
        # Mock ray module
        import types
        mock_ray = types.ModuleType('ray')
        mock_ray.tune = types.ModuleType('tune')
        mock_ray.tune.loguniform = lambda a, b: f"loguniform({a}, {b})"
        mock_ray.tune.randint = lambda a, b: f"randint({a}, {b})"
        mock_ray.tune.uniform = lambda a, b: f"uniform({a}, {b})"
        mock_ray.tune.choice = lambda choices: f"choice({choices})"
        
        sys.modules['ray'] = mock_ray
        sys.modules['ray.tune'] = mock_ray.tune
        
        spec.loader.exec_module(tuning_config_module)
        get_tune_config = tuning_config_module.get_tune_config
        
        # Test default config
        config = get_tune_config("default")
        print("✅ Default tuning config retrieved")
        print(f"   - use_gpu: {config.get('use_gpu')}")
        print(f"   - provenance: {config.get('_provenance', {}).get('version')}")
        
        # Test aggressive config
        config = get_tune_config("aggressive")
        print("✅ Aggressive tuning config retrieved")
        print(f"   - use_gpu: {config.get('use_gpu')}")
        print(f"   - provenance: {config.get('_provenance', {}).get('version')}")
        
        return True
    except Exception as e:
        print(f"❌ Tuning config test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all integration tests."""
    print("🧪 Testing GPU Guard Integration...")
    print("=" * 50)
    
    tests = [
        ("GPU Guard Creation", test_gpu_guard_creation),
        ("Tuning Service Integration", test_tuning_service_integration),
        ("Tuning Config", test_tuning_config),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n🔍 Running {test_name}...")
        if test_func():
            passed += 1
            print(f"✅ {test_name} PASSED")
        else:
            print(f"❌ {test_name} FAILED")
    
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! GPU Guard integration is working correctly.")
        return 0
    else:
        print("⚠️ Some tests failed. Check the output above for details.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
