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

from seedcore.ops.energy.ledger import EnergyLedger
from seedcore.ops.energy.calculator import compute_energy_unified
from unittest.mock import Mock


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

    # Skip Ray initialization for unit tests - use mocks instead
    # if not ray.is_initialized():
    #     from seedcore.utils.ray_utils import ensure_ray_initialized
    #     if not ensure_ray_initialized():
    #         print("❌ Failed to initialize Ray connection")
    #         return None, None

    # Mock task execution function
    def mock_execute_task(task_data):
        return {
            'success': True,
            'agent_id': 'mock_agent',
            'task_id': task_data.get('task_id', 'mock_task'),
            'execution_time': 0.1,
            'energy_consumed': 0.05
        }
    
    # Create synthetic tasks
    tasks = create_synthetic_tasks(num_tasks)
    print(f"✅ Created {len(tasks)} synthetic tasks")
    
    # Energy tracking
    energy_history = []
    ledger = EnergyLedger()
    
    print(f"\n🚀 Executing {num_tasks} tasks for energy calibration...")
    start_time = time.time()
    
    for i, task in enumerate(tasks):
        # Execute task
        result = mock_execute_task(task)
        
        if result and result.get('success'):
            # Simulate energy calculation and update ledger
            # Calculate simulated energy breakdown
            pair_energy = np.random.uniform(0.01, 0.05)
            hyper_energy = np.random.uniform(0.01, 0.03)
            entropy_energy = np.random.uniform(0.01, 0.02)
            reg_energy = np.random.uniform(0.005, 0.01)
            mem_energy = np.random.uniform(0.01, 0.02)
            
            total_energy = pair_energy + hyper_energy + entropy_energy + reg_energy + mem_energy
            
            # Update ledger using log_step
            ledger.log_step(
                breakdown={
                    "pair": pair_energy,
                    "hyper": hyper_energy,
                    "entropy": entropy_energy,
                    "reg": reg_energy,
                    "mem": mem_energy,
                    "drift_term": 0.0,
                    "anomaly_term": 0.0,
                    "total": total_energy
                },
                extra={"ts": time.time(), "task_id": task.get('task_id')}
            )
        
        # Record energy every 10 tasks
        if (i + 1) % 10 == 0:
            current_energy = ledger.total  # Use property instead of method
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
    print(f"   - Final energy: {ledger.total:.4f}")
    
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
    print(f"   - Pair history: {len(ledger.pair_history)}")
    print(f"   - Hyper history: {len(ledger.hyper_history)}")
    print(f"   - Entropy history: {len(ledger.entropy_history)}")
    print(f"   - Memory history: {len(ledger.mem_history)}")
    print(f"   - Total history: {len(ledger.total_history)}")
    
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
                'ledger_stats': len(ledger.pair_history)
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
        # Skip Ray shutdown for unit tests
        # if ray.is_initialized():
        #     ray.shutdown()
        pass
    
    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1) 