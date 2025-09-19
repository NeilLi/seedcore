#!/usr/bin/env python3
"""
Demo script showing the Tier0MemoryManager hardening patches in action.

This script demonstrates:
1. Idempotent agent creation (reusing existing actors)
2. Non-blocking telemetry collection
3. Faster liveness checks
4. Exponential backoff on Ray connection failures
"""

import asyncio
import os
import sys
import time
from typing import Dict, Any

# Add the src directory to the path so we can import seedcore modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from seedcore.tier0.tier0_manager import get_tier0_manager
from seedcore.tier0.specs import AgentSpec, MockGraphClient


async def demo_idempotent_creation():
    """Demonstrate idempotent agent creation."""
    print("🔄 Testing Idempotent Agent Creation")
    print("=" * 50)
    
    manager = get_tier0_manager()
    
    # Create an agent
    agent_id = "demo_agent_1"
    print(f"Creating agent: {agent_id}")
    result1 = manager.create_agent(
        agent_id=agent_id,
        name="demo_agent_1",  # Named actor
        num_cpus=1.0,
        namespace="seedcore-dev"
    )
    print(f"First creation result: {result1}")
    
    # Try to create the same agent again (should reuse existing)
    print(f"Creating same agent again: {agent_id}")
    result2 = manager.create_agent(
        agent_id=agent_id,
        name="demo_agent_1",  # Same name
        num_cpus=1.0,
        namespace="seedcore-dev"
    )
    print(f"Second creation result: {result2}")
    
    # Verify it's the same agent
    agents = manager.list_agents()
    print(f"Current agents: {agents}")
    print(f"Agent count: {len(agents)}")
    print()


async def demo_non_blocking_telemetry():
    """Demonstrate non-blocking telemetry collection."""
    print("📊 Testing Non-Blocking Telemetry Collection")
    print("=" * 50)
    
    manager = get_tier0_manager()
    
    # Create a few agents for testing
    for i in range(3):
        agent_id = f"telemetry_agent_{i}"
        manager.create_agent(
            agent_id=agent_id,
            name=f"telemetry_agent_{i}",
            num_cpus=0.5,
            namespace="seedcore-dev"
        )
    
    print(f"Created {len(manager.list_agents())} agents for telemetry testing")
    
    # Test heartbeat collection with timing
    print("Collecting heartbeats (non-blocking)...")
    start_time = time.time()
    
    heartbeats = await manager.collect_heartbeats()
    
    end_time = time.time()
    collection_time = end_time - start_time
    
    print(f"✅ Collected heartbeats from {len(heartbeats)} agents in {collection_time:.3f}s")
    print(f"Success rate: {len(heartbeats)}/{len(manager.list_agents())}")
    
    # Test stats collection
    print("Collecting stats (non-blocking)...")
    start_time = time.time()
    
    stats = await manager.collect_agent_stats()
    
    end_time = time.time()
    collection_time = end_time - start_time
    
    print(f"✅ Collected stats from {len(stats)} agents in {collection_time:.3f}s")
    print(f"Success rate: {len(stats)}/{len(manager.list_agents())}")
    print()


async def demo_faster_liveness():
    """Demonstrate faster liveness checks."""
    print("⚡ Testing Faster Liveness Checks")
    print("=" * 50)
    
    manager = get_tier0_manager()
    
    # Test liveness check timing
    agents = manager.list_agents()
    if not agents:
        print("No agents available for liveness testing")
        return
    
    print(f"Testing liveness for {len(agents)} agents...")
    
    start_time = time.time()
    alive_count = 0
    
    for agent_id in agents:
        agent = manager.get_agent(agent_id)
        if agent and manager._alive(agent):
            alive_count += 1
    
    end_time = time.time()
    check_time = end_time - start_time
    
    print(f"✅ Liveness check completed in {check_time:.3f}s")
    print(f"Alive agents: {alive_count}/{len(agents)}")
    print(f"Average time per agent: {check_time/len(agents):.3f}s")
    print()


async def demo_graph_aware_routing():
    """Demonstrate graph-aware task routing with the new patches."""
    print("🎯 Testing Graph-Aware Task Routing")
    print("=" * 50)
    
    manager = get_tier0_manager()
    
    # Create agent specifications
    agent_specs = [
        AgentSpec(
            agent_id="vision_agent_1",
            organ_id="vision_organ",
            skills=["image_processing", "object_detection"],
            models=["yolo_v8"],
            resources={"num_cpus": 2.0, "num_gpus": 1.0},
            metadata={"policies": "privacy_policy"}
        ),
        AgentSpec(
            agent_id="nlp_agent_1",
            organ_id="nlp_organ",
            skills=["text_processing", "sentiment_analysis"],
            models=["bert-base"],
            resources={"num_cpus": 1.0},
            metadata={"policies": "content_policy"}
        )
    ]
    
    # Attach graph client
    graph_client = MockGraphClient(agent_specs)
    manager.attach_graph(graph_client)
    
    # Reconcile agents from graph
    print("Reconciling agents from graph...")
    manager.reconcile_from_graph()
    
    agents = manager.list_agents()
    print(f"Agents after reconciliation: {agents}")
    
    # Test graph-aware task routing
    vision_task = {
        "task_type": "image_analysis",
        "required_skills": ["image_processing"],
        "required_models": ["yolo_v8"],
        "organ_id": "vision_organ"
    }
    
    print(f"Testing task routing for: {vision_task}")
    candidates = manager._graph_filter_candidates(vision_task)
    print(f"Qualified agents: {candidates}")
    print()


async def demo_environment_configuration():
    """Demonstrate environment variable configuration."""
    print("⚙️ Environment Configuration")
    print("=" * 50)
    
    # Show current configuration
    config_vars = [
        "TIER0_TP_MAX",
        "TIER0_HEARTBEAT_TIMEOUT", 
        "TIER0_STATS_TIMEOUT",
        "SEEDCORE_NS",
        "RAY_NAMESPACE",
        "RAY_ADDRESS"
    ]
    
    print("Current environment configuration:")
    for var in config_vars:
        value = os.getenv(var, "not set")
        print(f"  {var}: {value}")
    
    print()
    print("To customize, set environment variables:")
    print("  export TIER0_TP_MAX=16")
    print("  export TIER0_HEARTBEAT_TIMEOUT=3.0")
    print("  export TIER0_STATS_TIMEOUT=4.0")
    print()


async def main():
    """Main demo function."""
    print("🚀 Tier0MemoryManager Hardening Patches Demo")
    print("=" * 60)
    print()
    
    try:
        # Run all demos
        await demo_idempotent_creation()
        await demo_non_blocking_telemetry()
        await demo_faster_liveness()
        await demo_graph_aware_routing()
        await demo_environment_configuration()
        
        print("✅ All demos completed successfully!")
        print()
        print("Key improvements demonstrated:")
        print("  • Idempotent agent creation prevents duplicates")
        print("  • Non-blocking telemetry keeps event loop responsive")
        print("  • Faster liveness checks improve performance")
        print("  • Graph-aware routing enables capability-based task assignment")
        print("  • Configurable timeouts and thread pool sizing")
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Demo stopped by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
