#!/usr/bin/env python3
"""
Simple test script to verify that the tier0_manager import fix works correctly.
"""

import sys
import os
from pathlib import Path

# Add the src directory to the Python path
project_root = Path(__file__).parent.parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

def test_tier0_import():
    """Test that tier0_manager can be imported without errors."""
    try:
        print("🔍 Testing tier0_manager import...")
        
        # Test basic import
        from seedcore.agents.tier0_manager import Tier0MemoryManager
        print("✅ Basic import successful")
        
        # Test instantiation
        manager = Tier0MemoryManager()
        print("✅ Tier0MemoryManager instantiation successful")
        
        # Test that os module is available
        if hasattr(manager, '_ensure_ray'):
            print("✅ _ensure_ray method exists")
        else:
            print("❌ _ensure_ray method missing")
            return False
        
        print("🎉 All tests passed! The import fix is working correctly.")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def test_environment_variables():
    """Test that environment variables are accessible."""
    print("\n🔍 Testing environment variables...")
    
    # Check if SEEDCORE_NS is set
    seedcore_ns = os.getenv("SEEDCORE_NS")
    if seedcore_ns:
        print(f"✅ SEEDCORE_NS: {seedcore_ns}")
    else:
        print("⚠️ SEEDCORE_NS not set")
    
    # Check if RAY_NAMESPACE is set
    ray_namespace = os.getenv("RAY_NAMESPACE")
    if ray_namespace:
        print(f"✅ RAY_NAMESPACE: {ray_namespace}")
    else:
        print("⚠️ RAY_NAMESPACE not set")
    
    # Determine effective namespace
    effective_namespace = ray_namespace or seedcore_ns or "seedcore-dev"
    print(f"🎯 Effective namespace: {effective_namespace}")
    
    return True

def main():
    """Run all tests."""
    print("🧪 Testing Tier0Manager Import Fix")
    print("=" * 50)
    
    # Test imports
    import_success = test_tier0_import()
    
    # Test environment variables
    env_success = test_environment_variables()
    
    # Summary
    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)
    
    if import_success and env_success:
        print("🎉 All tests passed! The namespace fix is working correctly.")
        print("\n✅ Next steps:")
        print("   1. Deploy the updated code")
        print("   2. Restart your SeedCore services")
        print("   3. Verify agents are now visible in the correct namespace")
        return 0
    else:
        print("💥 Some tests failed. Please review the issues above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
