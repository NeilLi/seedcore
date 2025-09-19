#!/usr/bin/env python3
"""
Example demonstrating graph-aware Tier 0 Memory Manager functionality.

This script shows how to:
1. Create agent and organ specifications
2. Attach a graph client to the manager
3. Use graph-aware task routing
4. Run periodic reconciliation
"""

import asyncio
import os
import sys
from typing import Dict, Any

# Add the src directory to the path so we can import seedcore modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from seedcore.tier0.tier0_manager import get_tier0_manager
from seedcore.tier0.specs import AgentSpec, OrganSpec, MockGraphClient


def create_example_specs():
    """Create example agent and organ specifications."""
    
    # Create organ specifications
    vision_organ = OrganSpec(
        organ_id="vision_organ",
        provides_skills=["image_processing", "object_detection", "face_recognition"],
        uses_services=["camera_service", "storage_service"],
        governed_by_policies=["privacy_policy", "data_retention_policy"]
    )
    
    nlp_organ = OrganSpec(
        organ_id="nlp_organ", 
        provides_skills=["text_processing", "sentiment_analysis", "translation"],
        uses_services=["language_model_service", "translation_service"],
        governed_by_policies=["content_policy", "privacy_policy"]
    )
    
    # Create agent specifications
    agents = [
        AgentSpec(
            agent_id="vision_agent_1",
            organ_id="vision_organ",
            skills=["image_processing", "object_detection"],
            models=["yolo_v8", "resnet50"],
            services=["camera_service"],
            resources={"num_cpus": 2.0, "num_gpus": 1.0},
            namespace="seedcore-dev",
            lifetime="detached",
            name="vision_agent_1",
            metadata={"policies": "privacy_policy,data_retention_policy", "priority": "high"}
        ),
        AgentSpec(
            agent_id="nlp_agent_1",
            organ_id="nlp_organ",
            skills=["text_processing", "sentiment_analysis"],
            models=["bert-base", "gpt-3.5-turbo"],
            services=["language_model_service"],
            resources={"num_cpus": 1.0, "num_gpus": 0.0},
            namespace="seedcore-dev",
            lifetime="detached",
            name="nlp_agent_1",
            metadata={"policies": "content_policy,privacy_policy", "priority": "medium"}
        ),
        AgentSpec(
            agent_id="vision_agent_2",
            organ_id="vision_organ",
            skills=["face_recognition", "image_processing"],
            models=["facenet", "vgg16"],
            services=["camera_service", "storage_service"],
            resources={"num_cpus": 1.5, "num_gpus": 0.5},
            namespace="seedcore-dev",
            lifetime="detached",
            name="vision_agent_2",
            metadata={"policies": "privacy_policy", "priority": "low"}
        )
    ]
    
    organs = [vision_organ, nlp_organ]
    
    return agents, organs


async def main():
    """Main example function."""
    print("🚀 Starting Graph-Aware Tier 0 Memory Manager Example")
    
    # Get the manager instance
    manager = get_tier0_manager()
    
    # Create example specifications
    agent_specs, organ_specs = create_example_specs()
    
    # Create and attach mock graph client
    graph_client = MockGraphClient(agent_specs, organ_specs)
    manager.attach_graph(graph_client)
    
    print(f"📊 Created {len(agent_specs)} agent specs and {len(organ_specs)} organ specs")
    
    # Run initial reconciliation
    print("🔄 Running initial reconciliation...")
    manager.reconcile_from_graph()
    
    # List current agents
    agents = manager.list_agents()
    print(f"✅ Current agents: {agents}")
    
    # Example task routing scenarios
    print("\n🎯 Testing Graph-Aware Task Routing:")
    
    # Test 1: Vision task requiring specific skills
    vision_task = {
        "task_type": "image_analysis",
        "required_skills": ["image_processing", "object_detection"],
        "required_models": ["yolo_v8"],
        "organ_id": "vision_organ",
        "data": {"image_path": "/path/to/image.jpg"}
    }
    
    print(f"📸 Vision task: {vision_task}")
    candidates = manager._graph_filter_candidates(vision_task)
    print(f"   Qualified agents: {candidates}")
    
    # Test 2: NLP task
    nlp_task = {
        "task_type": "sentiment_analysis", 
        "required_skills": ["text_processing", "sentiment_analysis"],
        "required_models": ["bert-base"],
        "organ_id": "nlp_organ",
        "data": {"text": "This is a great product!"}
    }
    
    print(f"📝 NLP task: {nlp_task}")
    candidates = manager._graph_filter_candidates(nlp_task)
    print(f"   Qualified agents: {candidates}")
    
    # Test 3: Task with policy restrictions
    restricted_task = {
        "task_type": "external_api_call",
        "required_skills": ["text_processing"],
        "requires_external_network": True,
        "data": {"url": "https://external-api.com"}
    }
    
    print(f"🚫 Restricted task: {restricted_task}")
    candidates = manager._graph_filter_candidates(restricted_task)
    print(f"   Qualified agents (should be empty due to policy): {candidates}")
    
    # Test 4: Task requiring unavailable skills
    unavailable_task = {
        "task_type": "video_processing",
        "required_skills": ["video_processing", "motion_detection"],
        "data": {"video_path": "/path/to/video.mp4"}
    }
    
    print(f"🎬 Unavailable skills task: {unavailable_task}")
    candidates = manager._graph_filter_candidates(unavailable_task)
    print(f"   Qualified agents (should be empty): {candidates}")
    
    # Start periodic reconciliation
    print("\n🔄 Starting periodic reconciliation (15s interval)...")
    manager.start_graph_reconciler(interval=15)
    
    print("✅ Example completed! The reconciler will continue running in the background.")
    print("   Press Ctrl+C to stop.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Example stopped by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
