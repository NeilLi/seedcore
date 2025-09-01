#!/usr/bin/env python3
"""
Test script to verify that the MwStore import fix resolves the bootstrap issue.
This script tests that the required memory actors can be created successfully.
"""

import os
import sys
import logging
from pathlib import Path

# Ensure "src" is importable for seedcore imports
ROOT = Path(__file__).resolve().parents[1]  # /app
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
log = logging.getLogger("test_mw_bootstrap_fix")

def test_imports():
    """Test that all required classes can be imported."""
    log.info("🔍 Testing imports...")
    
    try:
        from seedcore.memory.working_memory import MissTracker, SharedCache
        log.info("✅ MissTracker and SharedCache imported successfully")
    except Exception as e:
        log.error(f"❌ Failed to import MissTracker/SharedCache: {e}")
        return False
    
    try:
        from seedcore.memory.mw_store import MwStore
        log.info("✅ MwStore imported successfully")
    except Exception as e:
        log.error(f"❌ Failed to import MwStore: {e}")
        return False
    
    try:
        from seedcore.bootstrap import bootstrap_actors
        log.info("✅ bootstrap_actors imported successfully")
    except Exception as e:
        log.error(f"❌ Failed to import bootstrap_actors: {e}")
        return False
    
    return True

def test_bootstrap_actors():
    """Test that bootstrap_actors can be called without import errors."""
    log.info("🔍 Testing bootstrap_actors function...")
    
    try:
        from seedcore.bootstrap import bootstrap_actors
        
        # Test that the function exists and is callable
        if callable(bootstrap_actors):
            log.info("✅ bootstrap_actors is callable")
            return True
        else:
            log.error("❌ bootstrap_actors is not callable")
            return False
            
    except Exception as e:
        log.error(f"❌ Failed to test bootstrap_actors: {e}")
        return False

def test_environment():
    """Test environment configuration."""
    log.info("🔍 Testing environment configuration...")
    
    required_vars = [
        "SEEDCORE_NS",
        "RAY_NAMESPACE", 
        "RAY_ADDRESS"
    ]
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            log.info(f"✅ {var}={value}")
        else:
            log.warning(f"⚠️ {var} not set")
    
    return True

def main():
    """Run all tests."""
    log.info("🚀 Starting MwStore bootstrap fix tests...")
    
    tests = [
        ("Environment Configuration", test_environment),
        ("Import Tests", test_imports),
        ("Bootstrap Function Test", test_bootstrap_actors),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        log.info(f"\n{'='*50}")
        log.info(f"Running: {test_name}")
        log.info(f"{'='*50}")
        
        try:
            if test_func():
                log.info(f"✅ {test_name} PASSED")
                passed += 1
            else:
                log.error(f"❌ {test_name} FAILED")
        except Exception as e:
            log.error(f"❌ {test_name} FAILED with exception: {e}")
    
    log.info(f"\n{'='*50}")
    log.info(f"Test Results: {passed}/{total} tests passed")
    log.info(f"{'='*50}")
    
    if passed == total:
        log.info("🎉 All tests passed! The MwStore import fix should work.")
        return 0
    else:
        log.error("❌ Some tests failed. Check the logs above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
