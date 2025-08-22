#!/usr/bin/env python3
"""
Test script to verify Ray namespace inheritance behavior.
"""

import ray
import os
import time
from typing import Dict, Any

def test_namespace_inheritance():
    """Test different approaches to namespace handling in Ray."""
    
    print("🧪 Testing Ray Namespace Inheritance")
    print("=" * 50)
    
    # Get namespace from environment
    ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
    ray_host = os.getenv("RAY_HOST", "seedcore-svc-head-svc")
    ray_port = os.getenv("RAY_PORT", "10001")
    ray_address = f"ray://{ray_host}:{ray_port}"
    
    print(f"🔗 Connecting to Ray at: {ray_address}")
    print(f"🏷️ Target namespace: {ray_namespace}")
    
    try:
        # Initialize Ray
        from seedcore.utils.ray_utils import ensure_ray_initialized
        if not ensure_ray_initialized(ray_address=ray_address, ray_namespace=ray_namespace):
            print("❌ Failed to connect to Ray cluster")
            return False
        print("✅ Ray initialized successfully")
        
        # Check runtime context
        runtime_context = ray.get_runtime_context()
        current_namespace = getattr(runtime_context, 'namespace', 'unknown')
        print(f"🔧 Runtime context namespace: {current_namespace}")
        
        if current_namespace != ray_namespace:
            print(f"⚠️  WARNING: Runtime context namespace ({current_namespace}) != target namespace ({ray_namespace})")
        
        # Test 1: Create actor with explicit namespace in options
        print(f"\n🧪 Test 1: Creating actor with explicit namespace in options")
        try:
            @ray.remote
            class TestActor:
                def __init__(self, name: str):
                    self.name = name
                
                def get_info(self) -> Dict[str, Any]:
                    return {
                        "name": self.name,
                        "namespace": getattr(ray.get_runtime_context(), 'namespace', 'unknown')
                    }
            
            # Create actor with explicit namespace
            actor1 = TestActor.options(
                name="test_actor_1",
                lifetime="detached",
                namespace=ray_namespace
            ).remote("test_actor_1")
            
            print(f"✅ Actor 1 created with namespace={ray_namespace}")
            
            # Get actor info
            info1 = ray.get(actor1.get_info.remote())
            print(f"   Actor 1 info: {info1}")
            
        except Exception as e:
            print(f"❌ Test 1 failed: {e}")
        
        # Test 2: Create actor without namespace (should inherit)
        print(f"\n🧪 Test 2: Creating actor without namespace (should inherit)")
        try:
            actor2 = TestActor.options(
                name="test_actor_2",
                lifetime="detached"
            ).remote("test_actor_2")
            
            print(f"✅ Actor 2 created without explicit namespace")
            
            # Get actor info
            info2 = ray.get(actor2.get_info.remote())
            print(f"   Actor 2 info: {info2}")
            
        except Exception as e:
            print(f"❌ Test 2 failed: {e}")
        
        # Test 3: Create actor with None namespace (should use current)
        print(f"\n🧪 Test 3: Creating actor with None namespace (should use current)")
        try:
            actor3 = TestActor.options(
                name="test_actor_3",
                lifetime="detached",
                namespace=None
            ).remote("test_actor_3")
            
            print(f"✅ Actor 3 created with namespace=None")
            
            # Get actor info
            info3 = ray.get(actor3.get_info.remote())
            print(f"   Actor 3 info: {info3}")
            
        except Exception as e:
            print(f"❌ Test 3 failed: {e}")
        
        # Test 4: Check what namespace the actors actually ended up in
        print(f"\n🔍 Test 4: Checking actual actor namespaces via ray.util.state")
        try:
            from ray.util.state import list_actors
            
            all_actors = list_actors()
            test_actors = [a for a in all_actors if getattr(a, 'name', '').startswith('test_actor_')]
            
            print(f"Found {len(test_actors)} test actors:")
            for actor in test_actors:
                name = getattr(actor, 'name', 'unknown')
                namespace = getattr(actor, 'namespace', 'unknown')
                state = getattr(actor, 'state', 'unknown')
                print(f"   - {name}: namespace='{namespace}', state={state}")
                
        except Exception as e:
            print(f"❌ Test 4 failed: {e}")
        
        # Test 5: Try to get actors by name in different namespaces
        print(f"\n🔍 Test 5: Testing actor retrieval by namespace")
        try:
            # Try to get actors in target namespace
            try:
                actor_in_target = ray.get_actor("test_actor_1", namespace=ray_namespace)
                print(f"✅ Found test_actor_1 in namespace '{ray_namespace}'")
            except Exception as e:
                print(f"❌ Could not find test_actor_1 in namespace '{ray_namespace}': {e}")
            
            # Try to get actors in 'unknown' namespace
            try:
                actor_in_unknown = ray.get_actor("test_actor_1", namespace=None)
                print(f"✅ Found test_actor_1 in namespace 'unknown'")
            except Exception as e:
                print(f"❌ Could not find test_actor_1 in namespace 'unknown': {e}")
                
        except Exception as e:
            print(f"❌ Test 5 failed: {e}")
        
        # Cleanup
        print(f"\n🧹 Cleaning up test actors...")
        try:
            for actor_name in ["test_actor_1", "test_actor_2", "test_actor_3"]:
                try:
                    # Try to get and kill in different namespaces
                    for ns in [ray_namespace, None, "unknown"]:
                        try:
                            actor = ray.get_actor(actor_name, namespace=ns)
                            ray.kill(actor)
                            print(f"✅ Killed {actor_name} in namespace '{ns}'")
                            break
                        except:
                            continue
                except:
                    pass
        except Exception as e:
            print(f"⚠️  Cleanup warning: {e}")
        
        print(f"\n🎯 Test Summary:")
        print(f"   - Target namespace: {ray_namespace}")
        print(f"   - Runtime context namespace: {current_namespace}")
        print(f"   - If actors show up in 'unknown' namespace, Ray is not properly")
        print(f"     inheriting the namespace from initialization context")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_namespace_inheritance()
