#!/usr/bin/env python3
"""
Test script to verify the bootstrap fix works correctly.
"""

import os
import sys
import logging

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
    """Test organism manager initialization."""
    print("\n🧪 Testing organism manager...")
    
    try:
        from seedcore.organs.organism_manager import organism_manager
        
        print("✅ Organism manager imported successfully")
        print(f"Initialized: {organism_manager._initialized}")
        
        return True
        
    except Exception as e:
        print(f"❌ Organism manager test failed: {e}")
        import traceback
        traceback.print_exc()
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

def main():
    """Run all tests."""
    print("🚀 Starting bootstrap fix tests...\n")
    
    tests = [
        test_ray_connection,
        test_bootstrap_actors,
        test_organism_manager,
        test_force_reinit,
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
        print("🎉 All tests passed! The bootstrap fix is working correctly.")
        return 0
    else:
        print("⚠️ Some tests failed. Check the output above for details.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
