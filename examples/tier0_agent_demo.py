#!/usr/bin/env python3
"""
Tier 0 (Ma) Agent Demo
Demonstrates Ray actor-based agents with per-agent memory and performance tracking.
"""

import sys
import os
import time
import random
import asyncio
import json
from typing import Dict, Any

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from seedcore.utils.ray_utils import init_ray, get_ray_cluster_info
from seedcore.config.ray_config import get_ray_config
from seedcore.agents import RayAgent, Tier0MemoryManager, tier0_manager

def setup_ray_connection():
    """Initialize Ray connection using environment variables."""
    print("🔗 Setting up Ray connection...")
    
    # Initialize Ray using our flexible configuration
    success = init_ray()
    if not success:
        print("❌ Failed to initialize Ray")
        return False
    
    # Get cluster info
    cluster_info = get_ray_cluster_info()
    print(f"✅ Ray connected: {cluster_info}")
    return True

def create_sample_agents(manager: Tier0MemoryManager, num_agents: int = 3):
    """Create sample agents with different configurations."""
    print(f"\n🤖 Creating {num_agents} sample agents...")
    
    agent_configs = []
    for i in range(num_agents):
        # Create different role probability distributions
        if i == 0:
            role_probs = {'E': 0.7, 'S': 0.2, 'O': 0.1}  # Explorer
        elif i == 1:
            role_probs = {'E': 0.2, 'S': 0.7, 'O': 0.1}  # Specialist
        else:
            role_probs = {'E': 0.3, 'S': 0.3, 'O': 0.4}  # Observer
        
        agent_configs.append({
            "agent_id": f"agent_{i+1}",
            "role_probs": role_probs
        })
    
    created_ids = manager.create_agents_batch(agent_configs)
    print(f"✅ Created agents: {created_ids}")
    return created_ids

def run_task_simulation(manager: Tier0MemoryManager, num_tasks: int = 10):
    """Run a simulation with multiple tasks."""
    print(f"\n🚀 Running task simulation ({num_tasks} tasks)...")
    
    task_types = [
        {"type": "data_analysis", "complexity": 0.8},
        {"type": "pattern_recognition", "complexity": 0.6},
        {"type": "optimization", "complexity": 0.9},
        {"type": "classification", "complexity": 0.5},
        {"type": "prediction", "complexity": 0.7}
    ]
    
    results = []
    for i in range(num_tasks):
        # Select random task type
        task_type = random.choice(task_types)
        task_data = {
            "task_id": f"task_{i+1}",
            "type": task_type["type"],
            "complexity": task_type["complexity"],
            "payload": f"Sample data for {task_type['type']}",
            "timestamp": time.time()
        }
        
        # Execute on random agent
        result = manager.execute_task_on_random_agent(task_data)
        if result:
            results.append(result)
            print(f"  ✅ Task {i+1} completed by {result['agent_id']} "
                  f"(success={result['success']}, quality={result['quality']:.3f})")
        else:
            print(f"  ❌ Task {i+1} failed")
        
        time.sleep(0.5)  # Small delay between tasks
    
    return results

async def demonstrate_heartbeats(manager: Tier0MemoryManager):
    """Demonstrate heartbeat collection and monitoring."""
    print(f"\n❤️ Demonstrating heartbeat collection...")
    
    # Collect heartbeats from all agents
    heartbeats = await manager.collect_heartbeats()
    
    print(f"📊 Collected heartbeats from {len(heartbeats)} agents:")
    for agent_id, heartbeat in heartbeats.items():
        perf = heartbeat['performance_metrics']
        print(f"  {agent_id}: capability={perf['capability_score_c']:.3f}, "
              f"tasks={perf['tasks_processed']}, success_rate={perf['success_rate']:.3f}")
    
    # Get system summary
    summary = manager.get_system_summary()
    print(f"\n📈 System Summary:")
    print(f"  Total agents: {summary['total_agents']}")
    print(f"  Total tasks: {summary['total_tasks_processed']}")
    print(f"  Avg capability: {summary['average_capability_score']:.3f}")
    print(f"  Avg memory util: {summary['average_memory_utilization']:.3f}")
    print(f"  Total memory writes: {summary['total_memory_writes']}")
    
    return heartbeats

def demonstrate_agent_interactions(manager: Tier0MemoryManager):
    """Demonstrate agent-to-agent interactions."""
    print(f"\n🤝 Demonstrating agent interactions...")
    
    agents = manager.list_agents()
    if len(agents) < 2:
        print("  Need at least 2 agents for interactions")
        return
    
    # Simulate some peer interactions
    for i in range(5):
        agent1 = random.choice(agents)
        agent2 = random.choice([a for a in agents if a != agent1])
        
        # Record interaction on both agents
        agent1_handle = manager.get_agent(agent1)
        agent2_handle = manager.get_agent(agent2)
        
        if agent1_handle and agent2_handle:
            # Record peer interactions
            agent1_handle.record_peer_interaction.remote(agent2)
            agent2_handle.record_peer_interaction.remote(agent1)
            
            print(f"  {agent1} ↔ {agent2} (interaction {i+1})")
    
    # Update skill deltas
    for agent_id in agents:
        agent_handle = manager.get_agent(agent_id)
        if agent_handle:
            skill_delta = random.uniform(-0.1, 0.1)
            agent_handle.update_skill_delta.remote("collaboration", skill_delta)
            print(f"  {agent_id} skill delta: collaboration += {skill_delta:.3f}")

def show_detailed_agent_state(manager: Tier0MemoryManager, agent_id: str):
    """Show detailed state of a specific agent."""
    print(f"\n🔍 Detailed state for {agent_id}:")
    
    agent_handle = manager.get_agent(agent_id)
    if not agent_handle:
        print(f"  Agent {agent_id} not found")
        return
    
    # Get heartbeat and stats
    heartbeat = manager.get_agent_heartbeat(agent_id)
    stats = manager.agent_stats.get(agent_id, {})
    
    if heartbeat:
        print(f"  State embedding: {len(heartbeat['state_embedding_h'])} dimensions")
        print(f"  Role probabilities: {heartbeat['role_probs']}")
        print(f"  Performance metrics:")
        perf = heartbeat['performance_metrics']
        for key, value in perf.items():
            if isinstance(value, float):
                print(f"    {key}: {value:.3f}")
            else:
                print(f"    {key}: {value}")
        
        print(f"  Memory metrics:")
        mem = heartbeat['memory_metrics']
        for key, value in mem.items():
            print(f"    {key}: {value}")
        
        print(f"  Local state:")
        local = heartbeat['local_state']
        print(f"    Skill deltas: {local['skill_deltas']}")
        print(f"    Peer interactions: {local['peer_interactions']}")
        print(f"    Recent quality scores: {local['recent_quality_scores']}")

async def main():
    """Main demonstration function."""
    print("🎯 Tier 0 (Ma) Agent Demo")
    print("=" * 50)
    
    # Setup Ray connection
    if not setup_ray_connection():
        return
    
    # Create manager
    manager = Tier0MemoryManager()
    
    try:
        # Create sample agents
        agent_ids = create_sample_agents(manager, num_agents=3)
        
        # Run task simulation
        results = run_task_simulation(manager, num_tasks=8)
        
        # Demonstrate agent interactions
        demonstrate_agent_interactions(manager)
        
        # Collect heartbeats and show system state
        heartbeats = await demonstrate_heartbeats(manager)
        
        # Show detailed state of first agent
        if agent_ids:
            show_detailed_agent_state(manager, agent_ids[0])
        
        # Demonstrate heartbeat monitoring (brief)
        print(f"\n📡 Starting brief heartbeat monitoring (5 seconds)...")
        monitoring_task = asyncio.create_task(
            manager.start_heartbeat_monitoring(interval_seconds=2)
        )
        
        # Let it run for a few seconds
        await asyncio.sleep(5)
        monitoring_task.cancel()
        
        print(f"\n✅ Demo completed successfully!")
        print(f"📊 Final system state:")
        final_summary = manager.get_system_summary()
        print(json.dumps(final_summary, indent=2))
        
    except Exception as e:
        print(f"❌ Error during demo: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup
        print(f"\n🧹 Cleaning up...")
        manager.shutdown_agents()

if __name__ == "__main__":
    asyncio.run(main()) 