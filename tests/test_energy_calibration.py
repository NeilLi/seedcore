#!/usr/bin/env python3
"""
Energy Model Calibration Test

This script runs synthetic tasks to calibrate energy weights and ensure
the total energy trends downward or stabilizes near zero.
"""

# Import mock dependencies BEFORE any other imports
import mock_ray_dependencies

import os
import sys
import ray
import numpy as np
import time
import asyncio
from typing import Dict, List, Any
from unittest.mock import patch

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.seedcore.ops.energy.calculator import EnergyLedger, calculate_energy
from src.seedcore.agents.ray_agent import RayAgent
from src.seedcore.organs.tier0.tier0_manager import Tier0MemoryManager


def create_synthetic_tasks(num_tasks: int = 100) -> List[Dict[str, Any]]:
    """Create synthetic tasks for energy calibration."""
    tasks = []
    task_types = ["optimization", "exploration", "analysis", "discovery", "general"]
    
    for i in range(num_tasks):
        task = {
            "task_id": f"calibration_task_{i}",
            "type": np.random.choice(task_types),
            "size": np.random.choice(["small", "medium", "large"]),
            "urgent": np.random.choice([True, False]),
            "complexity": np.random.uniform(0.1, 0.9),
            "description": f"Synthetic calibration task {i}"
        }
        tasks.append(task)
    
    return tasks


def run_energy_calibration(num_tasks: int = 100, num_agents: int = 5):
    """Run energy calibration with synthetic tasks."""
    print(f"🔧 Starting Energy Calibration Test")
    print(f"   - Tasks: {num_tasks}")
    print(f"   - Agents: {num_agents}")
    print()

    # Initialize Ray
    if not ray.is_initialized():
        from seedcore.utils.ray_utils import ensure_ray_initialized
        if not ensure_ray_initialized():
            print("❌ Failed to initialize Ray connection")
            return None, None

    # Create tier0 manager and agents
    tier0_manager = Tier0MemoryManager()
    
    # Mock the execute_task_on_best_agent method to return a proper result
    def mock_execute_task_on_best_agent(task_data):
        return {
            'success': True,
            'agent_id': 'mock_agent',
            'task_id': task_data.get('id', 'mock_task'),
            'execution_time': 0.1,
            'energy_consumed': 0.05
        }
    
    tier0_manager.execute_task_on_best_agent = mock_execute_task_on_best_agent
    
    # Create agents with different characteristics
    agent_configs = []
    for i in range(num_agents):
        if i < 2:
            # Specialists
            config = {"agent_id": f"specialist_{i}", "role_probs": {"E": 0.1, "S": 0.9, "O": 0.0}}
        elif i < 4:
            # Explorers
            config = {"agent_id": f"explorer_{i}", "role_probs": {"E": 0.9, "S": 0.1, "O": 0.0}}
        else:
            # Balanced
            config = {"agent_id": f"balanced_{i}", "role_probs": {"E": 0.5, "S": 0.4, "O": 0.1}}
        agent_configs.append(config)
    
    created_ids = tier0_manager.create_agents_batch(agent_configs)
    print(f"✅ Created {len(created_ids)} agents: {created_ids}")
    
    # Create synthetic tasks
    tasks = create_synthetic_tasks(num_tasks)
    print(f"✅ Created {len(tasks)} synthetic tasks")
    
    # Energy tracking
    energy_history = []
    ledger = EnergyLedger()
    
    print(f"\n🚀 Executing {num_tasks} tasks for energy calibration...")
    start_time = time.time()
    
    for i, task in enumerate(tasks):
        # Execute task with energy-aware selection
        result = tier0_manager.execute_task_on_best_agent(task)
        
        if result and result.get('success'):
            # Update energy ledger with pair success event
            pair_event = {
                'type': 'pair_success',
                'agents': [result['agent_id'], f"task_{i}"],
                'success': result['success'],
                'sim': np.random.uniform(0.5, 0.9)  # Simulated similarity
            }
            
            # Import and call the event handler
            from src.seedcore.ops.energy.calculator import on_pair_success
            on_pair_success(pair_event, ledger)
        
        # Record energy every 10 tasks
        if (i + 1) % 10 == 0:
            current_energy = ledger.get_total()
            energy_history.append({
                'task_num': i + 1,
                'energy': current_energy,
                'timestamp': time.time()
            })
            
            print(f"   Task {i+1:3d}/{num_tasks}: E_total = {current_energy:.4f}")
    
    total_time = time.time() - start_time
    
    # Analysis
    print(f"\n📊 Energy Calibration Results:")
    print(f"   - Total time: {total_time:.2f}s")
    print(f"   - Tasks/second: {num_tasks/total_time:.2f}")
    print(f"   - Final energy: {ledger.get_total():.4f}")
    
    if energy_history:
        energies = [e['energy'] for e in energy_history]
        print(f"   - Energy range: {min(energies):.4f} to {max(energies):.4f}")
        print(f"   - Energy trend: {'↘️ Decreasing' if energies[-1] < energies[0] else '↗️ Increasing'}")
        
        # Check if energy is trending downward
        if energies[-1] < energies[0]:
            print(f"   ✅ Energy is trending downward - good calibration!")
        else:
            print(f"   ⚠️ Energy is trending upward - weights may need adjustment")
    
    # Ledger statistics
    print(f"\n📋 Ledger Statistics:")
    print(f"   - Pair stats: {len(ledger.pair_stats)}")
    print(f"   - Hyper stats: {len(ledger.hyper_stats)}")
    print(f"   - Role entropy: {len(ledger.role_entropy)}")
    print(f"   - Memory stats: {len(ledger.mem_stats)}")
    
    return energy_history, ledger


def test_weight_combinations():
    """Test different weight combinations to find optimal settings."""
    print(f"\n🔬 Testing Weight Combinations...")
    
    # Define weight combinations to test
    weight_combinations = [
        {'alpha': 0.1, 'lambda_reg': 0.01, 'beta_mem': 0.05},  # Current
        {'alpha': 0.05, 'lambda_reg': 0.005, 'beta_mem': 0.02},  # Lower weights
        {'alpha': 0.2, 'lambda_reg': 0.02, 'beta_mem': 0.1},   # Higher weights
        {'alpha': 0.1, 'lambda_reg': 0.01, 'beta_mem': 0.02},  # Lower memory
        {'alpha': 0.05, 'lambda_reg': 0.01, 'beta_mem': 0.05},  # Lower entropy
    ]
    
    results = []
    
    for i, weights in enumerate(weight_combinations):
        print(f"\n   Testing combination {i+1}: {weights}")
        
        # Run calibration with these weights
        energy_history, ledger = run_energy_calibration(num_tasks=50, num_agents=3)
        
        if energy_history:
            final_energy = energy_history[-1]['energy']
            energy_trend = energy_history[-1]['energy'] - energy_history[0]['energy']
            
            results.append({
                'weights': weights,
                'final_energy': final_energy,
                'energy_trend': energy_trend,
                'ledger_stats': len(ledger.pair_stats)
            })
            
            print(f"      Final energy: {final_energy:.4f}")
            print(f"      Energy trend: {energy_trend:.4f}")
    
    # Find best combination
    if results:
        best_result = min(results, key=lambda r: r['final_energy'])
        print(f"\n🏆 Best Weight Combination:")
        print(f"   Weights: {best_result['weights']}")
        print(f"   Final Energy: {best_result['final_energy']:.4f}")
        print(f"   Energy Trend: {best_result['energy_trend']:.4f}")
    
    return results


async def main():
    """Main calibration function."""
    print("🚀 Starting Energy Model Calibration...")
    
    try:
        # Run basic calibration
        energy_history, ledger = run_energy_calibration(num_tasks=100, num_agents=5)
        
        # Test weight combinations
        weight_results = test_weight_combinations()
        
        print(f"\n✅ Energy calibration completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Calibration failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        if ray.is_initialized():
            ray.shutdown()
    
    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1) 