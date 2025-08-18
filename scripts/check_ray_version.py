#!/usr/bin/env python3
"""
Script to check Ray version in the cluster.
"""

import ray
import sys
import os

def check_ray_version():
    """Check Ray version in the cluster."""
    try:
        # Initialize Ray connection
        if not ray.is_initialized():
            ray.init(address="ray://ray-head:10001", ignore_reinit_error=True)
            print("🔌 Connected to Ray cluster...")
        
        print("🔍 Ray Version Check")
        print("=" * 40)
        
        # Get Ray version
        ray_version = ray.__version__
        print(f"📦 Ray Version: {ray_version}")
        
        # Get Python version
        import platform
        python_version = platform.python_version()
        print(f"🐍 Python Version: {python_version}")
        
        # Get cluster info
        print(f"\n🌐 Cluster Information:")
        print(f"   🔗 Ray Address: {ray.get_runtime_context().gcs_address}")
        print(f"   ✅ Ray Initialized: {ray.is_initialized()}")
        
        # Check if we can get more detailed version info
        try:
            # Try to get version from ray.init() info
            print(f"\n📋 Additional Info:")
            print(f"   🏗️  Ray Build: {ray.__version__}")
            
            # Check if we can get cluster version info
            try:
                # This might work in newer Ray versions
                cluster_info = getattr(ray.get_runtime_context(), 'cluster_metadata', None)
                if cluster_info and 'ray_version' in cluster_info:
                    print(f"   🎯 Cluster Ray Version: {cluster_info['ray_version']}")
            except:
                pass
                
        except Exception as e:
            print(f"   ⚠️  Could not get additional version info: {str(e)[:50]}")
        
        print(f"\n💡 Version Compatibility:")
        if ray_version.startswith("2.48"):
            print(f"   ✅ Ray 2.48.x detected - compatible with Python 3.12")
        elif ray_version.startswith("2.9") or ray_version.startswith("3."):
            print(f"   ✅ Ray {ray_version} - newer version with better Python 3.12 support")
        else:
            print(f"   ⚠️  Ray {ray_version} - older version, may have Python 3.12 issues")
        
    except Exception as e:
        print(f"❌ Error checking Ray version: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = check_ray_version()
    sys.exit(0 if success else 1) 