#!/usr/bin/env python3
"""
Simple script to clean up any existing test actors that might be left over from previous runs.
"""

import os
import ray

def cleanup_test_actors():
    """Clean up any existing test actors."""
    print("🧹 Cleaning up test actors...")
    
    # Initialize Ray connection
    ray_host = os.getenv("RAY_HOST", "seedcore-svc-head-svc")
    ray_port = os.getenv("RAY_PORT", "10001")
    ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
    
    try:
        ray_address = f"ray://{ray_host}:{ray_port}"
        print(f"Connecting to Ray at: {ray_address}")
        
        if not ray.is_initialized():
            ray.init(address=ray_address, namespace=ray_namespace)
            print("✅ Ray connection established")
        else:
            print("✅ Ray already initialized")
        
        # List and clean up test actors
        try:
            from ray.util.state import list_actors
            actors = list_actors()
            
            # Find test actors
            test_actors = []
            for actor in actors:
                if actor.name and (
                    actor.name.startswith("test_organ_") or 
                    actor.name == "test_organ" or
                    actor.name.startswith("test_")
                ):
                    test_actors.append(actor)
            
            if test_actors:
                print(f"Found {len(test_actors)} test actors to clean up:")
                for actor in test_actors:
                    print(f"  - {actor.name} (ID: {actor.actor_id}, State: {actor.state})")
                
                # Clean them up
                cleaned_count = 0
                for actor in test_actors:
                    try:
                        ray.kill(actor.actor_id)
                        print(f"✅ Cleaned up: {actor.name}")
                        cleaned_count += 1
                    except Exception as e:
                        print(f"⚠️ Could not clean up {actor.name}: {e}")
                
                print(f"\n🎉 Cleanup complete: {cleaned_count}/{len(test_actors)} actors cleaned up")
            else:
                print("✅ No test actors found to clean up")
                
        except Exception as e:
            print(f"❌ Error listing actors: {e}")
            
    except Exception as e:
        print(f"❌ Failed to connect to Ray: {e}")
        return False
    
    finally:
        # Clean up Ray connection
        try:
            if ray.is_initialized():
                ray.shutdown()
                print("✅ Ray connection closed")
        except:
            pass
    
    return True

if __name__ == "__main__":
    print("🧹 Test Actor Cleanup Script")
    print("=" * 40)
    
    success = cleanup_test_actors()
    
    if success:
        print("\n🎉 Cleanup completed successfully!")
    else:
        print("\n❌ Cleanup encountered issues.")
    
    exit(0 if success else 1)
