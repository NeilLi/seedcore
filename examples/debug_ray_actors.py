#!/usr/bin/env python3
"""
Debug script to test Ray actor creation.
"""

import sys
import os
import ray

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from seedcore.utils.ray_utils import ensure_ray_initialized, get_ray_cluster_info
from seedcore.config.ray_config import get_ray_config

def test_simple_ray_actor():
    """Test creating a simple Ray actor."""
    print("🔧 Testing simple Ray actor creation...")
    
    @ray.remote
    class SimpleActor:
        def __init__(self, name):
            self.name = name
            print(f"✅ SimpleActor {name} created")
        
        def get_name(self):
            return self.name
        
        def add(self, a, b):
            return a + b
    
    try:
        # Create actor
        actor = SimpleActor.remote("test_actor")
        print(f"✅ Actor created: {actor}")
        
        # Test methods
        name = ray.get(actor.get_name.remote())
        print(f"✅ Actor name: {name}")
        
        result = ray.get(actor.add.remote(5, 3))
        print(f"✅ Actor add result: {result}")
        
        return True
    except Exception as e:
        print(f"❌ Simple actor test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_ray_agent_without_numpy():
    """Test creating our RayAgent without numpy dependency."""
    print("\n🔧 Testing RayAgent creation (no numpy)...")
    
    try:
        from seedcore.agents.ray_actor import RayAgent
        
        # Create agent
        agent = RayAgent.remote("test_agent_1", {'E': 0.6, 'S': 0.3, 'O': 0.1}, "test_organ_1")
        print(f"✅ RayAgent created: {agent}")
        
        # Test methods
        agent_id = ray.get(agent.get_id.remote())
        print(f"✅ Agent ID: {agent_id}")
        
        stats = ray.get(agent.get_summary_stats.remote())
        print(f"✅ Agent stats: {stats}")
        
        # Test task execution
        task_data = {"task_id": "test_task", "complexity": 0.7}
        result = ray.get(agent.execute_task.remote(task_data))
        print(f"✅ Task execution result: {result}")
        
        return True
    except Exception as e:
        print(f"❌ RayAgent test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_ray_agent_creation():
    """Test creating our RayAgent (with numpy)."""
    print("\n🔧 Testing RayAgent creation...")
    
    try:
        from seedcore.agents import RayAgent
        
        # Create agent
        agent = RayAgent.remote("test_agent_1", {'E': 0.6, 'S': 0.3, 'O': 0.1}, "test_organ_1")
        print(f"✅ RayAgent created: {agent}")
        
        # Test methods
        agent_id = ray.get(agent.get_id.remote())
        print(f"✅ Agent ID: {agent_id}")
        
        stats = ray.get(agent.get_summary_stats.remote())
        print(f"✅ Agent stats: {stats}")
        
        return True
    except Exception as e:
        print(f"❌ RayAgent test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main debug function."""
    print("🔍 Ray Actor Debug Script")
    print("=" * 40)
    
    # Initialize Ray
    print("🔗 Initializing Ray...")
    success = ensure_ray_initialized()
    if not success:
        print("❌ Failed to initialize Ray")
        return
    
    cluster_info = get_ray_cluster_info()
    print(f"✅ Ray connected: {cluster_info}")
    
    # Test simple actor
    simple_success = test_simple_ray_actor()
    
    # Test RayAgent (no numpy dependency)
    agent_no_numpy_success = test_ray_agent_without_numpy()
    
    # Test RayAgent (with numpy)
    agent_success = test_ray_agent_creation()
    
    print(f"\n📊 Results:")
    print(f"  Simple actor: {'✅' if simple_success else '❌'}")
    print(f"  RayAgent (no numpy): {'✅' if agent_no_numpy_success else '❌'}")
    print(f"  RayAgent (with numpy): {'✅' if agent_success else '❌'}")

if __name__ == "__main__":
    main() 