#!/usr/bin/env python3
"""
Test script for the Enhanced Energy Model Foundation implementation.

This script tests the real energy calculation engine and energy-aware agent selection
with incremental updates and energy ledger functionality.
"""

# Import mock dependencies BEFORE any other imports
import mock_ray_dependencies

import os
import sys
import asyncio
import ray
import numpy as np
from typing import Dict, Any

# Ensure we're using the correct Ray mock
if not hasattr(ray, 'get') or not hasattr(ray, 'remote'):
    print("⚠️  Ray mock not properly loaded, re-importing...")
    import importlib
    importlib.reload(mock_ray_dependencies)
    import ray

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.seedcore.energy.calculator import (
    EnergyLedger,
    EnergyTerms,
    calculate_energy,
    energy_gradient_payload,
    on_pair_success,
    on_role_update,
    on_state_update,
    on_mem_event
)
from src.seedcore.energy.optimizer import (
    score_agent,
    select_best_agent,
    get_ideal_role_for_task,
    estimate_task_complexity
)
from src.seedcore.agents.ray_actor import RayAgent
from src.seedcore.agents.tier0_manager import Tier0MemoryManager


def test_energy_ledger():
    """Test the EnergyLedger functionality."""
    print("🧪 Testing Energy Ledger...")
    
    # Create a new ledger
    ledger = EnergyLedger()
    
    # Test initial state
    assert ledger.terms.pair == 0.0
    assert ledger.terms.total == 0.0
    
    # Test pair success event
    event = {
        'agents': ['agent1', 'agent2'],
        'success': 0.8,
        'sim': 0.7
    }
    on_pair_success(event, ledger)
    
    # Check that pair stats were updated
    pair_key = tuple(sorted(['agent1', 'agent2']))
    assert pair_key in ledger.pair_stats
    assert ledger.pair_stats[pair_key]['w'] > 0.0
    assert ledger.pair_stats[pair_key]['sim'] == 0.7
    
    # Test role update event
    role_event = {
        'H_new': 1.5,
        'H_prev': 1.0
    }
    on_role_update(role_event, ledger, alpha=0.1)
    
    # Test memory event
    mem_event = {
        'cost_delta': 0.1
    }
    on_mem_event(mem_event, ledger, beta_mem=0.2)
    
    # Test total calculation
    total = ledger.get_total()
    assert total != 0.0
    
    # Test telemetry payload
    payload = energy_gradient_payload(ledger)
    assert 'ts' in payload
    assert 'E_terms' in payload
    assert 'pair_stats_count' in payload
    
    print(f"  ✅ Energy Ledger: pair_stats={len(ledger.pair_stats)}, total={total:.4f}")
    return True


def test_real_energy_calculations():
    """Test the real energy calculation functions."""
    print("\n🧪 Testing Real Energy Calculations...")
    
    # Create mock agents for testing
    agents = []
    for i in range(3):
        agent = RayAgent.remote(f"test_agent_{i}", organ_id="test_organ_1")
        # Set different role probabilities for testing
        if i == 0:
            ray.get(agent.update_role_probs.remote({'E': 0.8, 'S': 0.2, 'O': 0.0}))
        elif i == 1:
            ray.get(agent.update_role_probs.remote({'E': 0.2, 'S': 0.8, 'O': 0.0}))
        else:
            ray.get(agent.update_role_probs.remote({'E': 0.5, 'S': 0.3, 'O': 0.2}))
        agents.append(agent)
    
    # Create system state
    state = {
        'agents': agents,
        'memory_stats': {'cost_vq': 0.15},
        'pair_stats': {
            ('agent1', 'agent2'): {'w': 0.8, 'sim': 0.7},
            ('agent1', 'agent3'): {'w': 0.6, 'sim': 0.5}
        },
        'alpha': 0.1,
        'lambda_reg': 0.01,
        'beta_mem': 0.05
    }
    
    # Calculate energy using real implementation
    energy_terms = calculate_energy(state)
    
    print(f"  ✅ Real Energy Calculation:")
    print(f"    - Pair Energy: {energy_terms.pair:.4f}")
    print(f"    - Entropy Energy: {energy_terms.entropy:.4f}")
    print(f"    - Regularization Energy: {energy_terms.reg:.4f}")
    print(f"    - Memory Energy: {energy_terms.mem:.4f}")
    print(f"    - Total Energy: {energy_terms.total:.4f}")
    
    return True


def test_enhanced_agent_selection():
    """Test the enhanced energy-aware agent selection."""
    print("\n🧪 Testing Enhanced Agent Selection...")
    
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
    
    # Test individual agent scoring
    agent_handles = list(tier0_manager.agents.values())
    task = {"type": "optimization", "required_capability": 0.3}
    
    for i, agent in enumerate(agent_handles):
        score = score_agent(agent, task)
        agent_id = ray.get(agent.get_id.remote())
        print(f"  ✅ Agent {agent_id} energy score: {score:.4f}")
    
    # Test best agent selection
    best_agent, predicted_delta_e = select_best_agent(agent_handles, task)
    if best_agent:
        best_id = ray.get(best_agent.get_id.remote())
        print(f"  ✅ Best Agent Selected: {best_id} (predicted ΔE: {predicted_delta_e:.4f})")
    else:
        print("  ❌ No best agent selected")
    
    return True


def test_energy_aware_task_execution():
    """Test the energy-aware task execution with new features."""
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
    
    # Test energy-aware task execution with capability requirement
    task_data = {
        "type": "optimization",
        "size": "medium",
        "urgent": False,
        "description": "Test optimization task",
        "required_capability": 0.3
    }
    
    result = tier0_manager.execute_task_on_best_agent(task_data)
    if result:
        print(f"  ✅ Task executed successfully: {result}")
    else:
        print("  ❌ Task execution failed")
    
    # Test collaborative task with partner
    collaborative_task = {
        "type": "analysis",
        "size": "large",
        "partner_id": "explorer_2",
        "partner_embedding": np.random.randn(128).tolist(),
        "description": "Collaborative analysis task"
    }
    
    result = tier0_manager.execute_task_on_best_agent(collaborative_task)
    if result:
        print(f"  ✅ Collaborative task executed: {result}")
    else:
        print("  ❌ Collaborative task failed")
    
    return True


def test_agent_energy_proxy():
    """Test the agent energy proxy functionality."""
    print("\n🧪 Testing Agent Energy Proxy...")
    
    # Create an agent
    agent = RayAgent.remote("test_proxy_agent", organ_id="test_organ_1")
    
    # Update agent metrics
    ray.get(agent.update_local_metrics.remote(0.8, 0.9, 3))
    
    # Get energy proxy
    proxy = ray.get(agent.get_energy_proxy.remote())
    
    print(f"  ✅ Energy Proxy:")
    print(f"    - Capability: {proxy['capability']:.3f}")
    print(f"    - Entropy Contribution: {proxy['entropy_contribution']:.3f}")
    print(f"    - Memory Utility: {proxy['mem_util']:.3f}")
    print(f"    - State Norm: {proxy['state_norm']:.3f}")
    
    # Test that capability was updated
    assert proxy['capability'] > 0.5  # Should be higher than initial 0.5
    assert proxy['mem_util'] > 0.0    # Should be updated from initial 0.0
    
    return True


async def main():
    """Main test function."""
    print("🚀 Starting Enhanced Energy Model Foundation Tests...\n")
    
    # Initialize Ray
    if not ray.is_initialized():
        from seedcore.utils.ray_utils import ensure_ray_initialized
        if not ensure_ray_initialized():
            print("❌ Failed to initialize Ray connection")
            return False
    
    try:
        # Run tests
        test_energy_ledger()
        test_real_energy_calculations()
        test_enhanced_agent_selection()
        test_energy_aware_task_execution()
        test_agent_energy_proxy()
        
        print("\n✅ All Enhanced Energy Model Foundation tests completed successfully!")
        
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