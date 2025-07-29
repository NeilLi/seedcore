#!/usr/bin/env python3
"""
Test script for the Energy Model Foundation implementation.

This script tests the energy calculation engine and energy-aware agent selection.
"""

import os
import sys
import asyncio
import ray
import numpy as np
from typing import Dict, Any

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.seedcore.energy.calculator import (
    calculate_pair_energy,
    calculate_entropy_energy,
    calculate_reg_energy,
    calculate_total_energy
)
from src.seedcore.energy.optimizer import (
    calculate_agent_suitability_score,
    select_best_agent,
    get_ideal_role_for_task,
    estimate_task_complexity
)
from src.seedcore.agents.ray_actor import RayAgent
from src.seedcore.agents.tier0_manager import Tier0MemoryManager


def test_energy_calculations():
    """Test the energy calculation functions."""
    print("🧪 Testing Energy Calculations...")
    
    # Create mock agents for testing
    agents = []
    for i in range(3):
        agent = RayAgent.remote(f"test_agent_{i}")
        # Set different role probabilities for testing
        if i == 0:
            ray.get(agent.update_role_probs.remote({'E': 0.8, 'S': 0.2, 'O': 0.0}))
        elif i == 1:
            ray.get(agent.update_role_probs.remote({'E': 0.2, 'S': 0.8, 'O': 0.0}))
        else:
            ray.get(agent.update_role_probs.remote({'E': 0.5, 'S': 0.3, 'O': 0.2}))
        agents.append(agent)
    
    # Test pair energy calculation
    pair_energy = calculate_pair_energy(agents)
    print(f"  ✅ Pair Energy: {pair_energy:.4f}")
    
    # Test entropy energy calculation
    entropy_energy = calculate_entropy_energy(agents, alpha=0.5)
    print(f"  ✅ Entropy Energy: {entropy_energy:.4f}")
    
    # Test regularization energy calculation
    reg_energy = calculate_reg_energy(agents, lambda_reg=0.01)
    print(f"  ✅ Regularization Energy: {reg_energy:.4f}")
    
    # Test total energy calculation (with mock memory system)
    class DummyMem:
        def __init__(self, bytes_used=1000, hit_count=0, datastore=None):
            self.bytes_used = bytes_used
            self.hit_count = hit_count
            self.datastore = datastore if datastore is not None else []
    class MockMemorySystem:
        def __init__(self):
            self.Mw = DummyMem(1000, 10, [1, 2, 3])
            self.Mlt = DummyMem(2000, 20, [4, 5])
    
    mock_memory = MockMemorySystem()
    total_energy = calculate_total_energy(agents, mock_memory)
    print(f"  ✅ Total Energy: {total_energy}")
    
    return True


def test_agent_selection():
    """Test the energy-aware agent selection."""
    print("\n🧪 Testing Agent Selection...")
    
    # Create a tier0 manager and some agents
    tier0_manager = Tier0MemoryManager()
    
    # Create agents with different characteristics
    agent_configs = [
        {"agent_id": "specialist_1", "role_probs": {"E": 0.1, "S": 0.9, "O": 0.0}},
        {"agent_id": "explorer_1", "role_probs": {"E": 0.9, "S": 0.1, "O": 0.0}},
        {"agent_id": "balanced_1", "role_probs": {"E": 0.5, "S": 0.4, "O": 0.1}},
    ]
    
    created_ids = tier0_manager.create_agents_batch(agent_configs)
    print(f"  ✅ Created {len(created_ids)} agents: {created_ids}")
    
    # Test task complexity estimation
    task_data = {"type": "optimization", "size": "medium", "urgent": False}
    complexity = estimate_task_complexity(task_data)
    print(f"  ✅ Task Complexity: {complexity:.3f}")
    
    # Test ideal role mapping
    ideal_role = get_ideal_role_for_task("optimization")
    print(f"  ✅ Ideal Role for Optimization: {ideal_role}")
    
    # Test agent suitability scoring
    agent_handles = list(tier0_manager.agents.values())
    weights = {'w_pair': 1.0, 'w_hyper': 1.0, 'w_explore': 0.2}
    
    for i, agent in enumerate(agent_handles):
        score = calculate_agent_suitability_score(agent, task_data, weights)
        agent_id = ray.get(agent.get_id.remote())
        print(f"  ✅ Agent {agent_id} suitability score: {score:.4f}")
    
    # Test best agent selection
    best_agent = select_best_agent(agent_handles, task_data, weights)
    if best_agent:
        best_id = ray.get(best_agent.get_id.remote())
        print(f"  ✅ Best Agent Selected: {best_id}")
    else:
        print("  ❌ No best agent selected")
    
    return True


def test_energy_aware_task_execution():
    """Test the energy-aware task execution."""
    print("\n🧪 Testing Energy-Aware Task Execution...")
    
    # Create a tier0 manager and some agents
    tier0_manager = Tier0MemoryManager()
    
    # Create agents with different characteristics
    agent_configs = [
        {"agent_id": "specialist_2", "role_probs": {"E": 0.1, "S": 0.9, "O": 0.0}},
        {"agent_id": "explorer_2", "role_probs": {"E": 0.9, "S": 0.1, "O": 0.0}},
    ]
    
    created_ids = tier0_manager.create_agents_batch(agent_configs)
    print(f"  ✅ Created {len(created_ids)} agents: {created_ids}")
    
    # Test energy-aware task execution
    task_data = {
        "type": "optimization",
        "size": "medium",
        "urgent": False,
        "description": "Test optimization task"
    }
    
    result = tier0_manager.execute_task_on_best_agent(task_data)
    if result:
        print(f"  ✅ Task executed successfully: {result}")
    else:
        print("  ❌ Task execution failed")
    
    return True


async def main():
    """Main test function."""
    print("🚀 Starting Energy Model Foundation Tests...\n")
    
    # Initialize Ray
    if not ray.is_initialized():
        ray.init(ignore_reinit_error=True)
    
    try:
        # Run tests
        test_energy_calculations()
        test_agent_selection()
        test_energy_aware_task_execution()
        
        print("\n✅ All Energy Model Foundation tests completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Shutdown Ray
        if ray.is_initialized():
            ray.shutdown()
    
    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1) 