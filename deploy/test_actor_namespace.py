#!/usr/bin/env python3
"""
Test script to check actor namespace behavior.
"""

import ray
import os

def test_actor_namespace():
    """Test if new actors are created in the correct namespace."""
    
    print("🧪 Testing Actor Namespace Behavior")
    print("=" * 50)
    
    # Check environment variables
    ray_namespace = os.getenv("RAY_NAMESPACE", "not_set")
    print(f"Environment RAY_NAMESPACE: {ray_namespace}")
    
    # Initialize Ray
    ray_host = os.getenv("RAY_HOST", "seedcore-svc-head-svc")
    ray_port = os.getenv("RAY_PORT", "10001")
    ray_address = f"ray://{ray_host}:{ray_port}"
    
    print(f"Connecting to Ray at: {ray_address}")
    ray.init(address=ray_address, namespace=ray_namespace)
    
    print(f"Connected namespace: {ray.get_runtime_context().namespace}")
    
    # Check existing actors
    from ray.util.state import list_actors
    existing_actors = list_actors()
    print(f"\nExisting actors: {len(existing_actors)}")
    
    # Check namespaces of existing actors
    namespaces = set()
    for actor in existing_actors:
        namespace = getattr(actor, 'namespace', 'unknown')
        namespaces.add(namespace)
        if getattr(actor, 'name', None):
            print(f"  - {actor.name}: namespace='{namespace}'")
    
    print(f"Namespaces found: {namespaces}")
    
    # Create a new test actor
    print(f"\nCreating new test actor...")
    
    @ray.remote
    class TestActor:
        def __init__(self, name):
            self.name = name
        
        def get_info(self):
            return {
                "name": self.name,
                "namespace": getattr(ray.get_runtime_context(), 'namespace', 'unknown')
            }
    
    # Create actor with explicit namespace
    actor = TestActor.options(
        name="test_new_namespace_actor",
        lifetime="detached"
    ).remote("test_actor")
    
    print("✅ New actor created successfully")
    
    # Get actor info
    info = ray.get(actor.get_info.remote())
    print(f"   Actor info: {info}")
    
    # Check if the new actor appears in list_actors with correct namespace
    print(f"\nChecking new actor in list_actors...")
    updated_actors = list_actors()
    new_actor = None
    
    for a in updated_actors:
        if getattr(a, 'name', None) == "test_new_namespace_actor":
            new_actor = a
            break
    
    if new_actor:
        new_actor_namespace = getattr(new_actor, 'namespace', 'unknown')
        print(f"   New actor namespace in list_actors: '{new_actor_namespace}'")
        
        if new_actor_namespace == ray_namespace:
            print("   ✅ New actor has correct namespace")
        else:
            print(f"   ❌ New actor has wrong namespace: expected '{ray_namespace}', got '{new_actor_namespace}'")
    else:
        print("   ❌ New actor not found in list_actors")
    
    # Clean up
    ray.kill(actor)
    print("✅ Test actor cleaned up")
    
    return True

if __name__ == "__main__":
    test_actor_namespace()
