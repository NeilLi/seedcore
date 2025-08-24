#!/usr/bin/env python3
"""
Simple DSPy Integration Example for SeedCore

This script demonstrates basic DSPy integration using CognitiveCore
directly (no Ray Serve). Useful for local development and quick checks.
For production, use the deployed CognitiveService (/cognitive).
"""

import os
import sys
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from seedcore.agents.cognitive_core import (
    CognitiveCore, 
    CognitiveContext, 
    CognitiveTaskType,
    initialize_cognitive_core,
)
from seedcore.config.llm_config import configure_llm_openai


def main():
    """Main function demonstrating simple DSPy integration."""
    print("🧠 Simple DSPy Integration Example for SeedCore")
    print("=" * 60)

    # Configure LLM (requires OPENAI_API_KEY)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("⚠️ OPENAI_API_KEY environment variable not set")
        return

    configure_llm_openai(api_key)
    print("✅ LLM configuration loaded")

    # Initialize cognitive core
    print("\n🚀 Initializing cognitive core...")
    try:
        cognitive_core = initialize_cognitive_core()
        print("✅ Cognitive core initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize cognitive core: {e}")
        return

    # === Example 1: Failure Analysis ===
    print("\n=== Example 1: Failure Analysis ===")
    try:
        context = CognitiveContext(
            agent_id="example_agent_1",
            task_type=CognitiveTaskType.FAILURE_ANALYSIS,
            input_data={
                "incident_id": "incident_001",
                "error_message": "Timeout after 30 seconds",
                "agent_state": {"capability_score": 0.7, "tasks_processed": 15}
            }
        )
        result = cognitive_core(context)
        print("✅ Failure analysis completed")
        print(f"   Solution: {result.get('proposed_solution', 'N/A')[:100]}...")
    except Exception as e:
        print(f"❌ Failure analysis failed: {e}")

    # === Example 2: Task Planning ===
    print("\n=== Example 2: Task Planning ===")
    try:
        context = CognitiveContext(
            agent_id="example_agent_2",
            task_type=CognitiveTaskType.TASK_PLANNING,
            input_data={
                "task_description": "Process a dataset and generate insights",
                "agent_capabilities": {"data_processing": 0.8, "analysis": 0.6},
                "available_resources": {"cpu_cores": 4, "memory_gb": 8}
            }
        )
        result = cognitive_core(context)
        print("✅ Task planning completed")
        print(f"   Plan: {result.get('step_by_step_plan', 'N/A')[:100]}...")
    except Exception as e:
        print(f"❌ Task planning failed: {e}")

    # === Example 3: Decision Making ===
    print("\n=== Example 3: Decision Making ===")
    try:
        context = CognitiveContext(
            agent_id="example_agent_3",
            task_type=CognitiveTaskType.DECISION_MAKING,
            input_data={
                "decision_context": {
                    "options": ["Option A: Fast but costly", "Option B: Slow but cheap"],
                    "constraints": ["Budget: $1000", "Time: 1 week"]
                },
                "historical_data": {
                    "success_rates": {"Option A": 0.8, "Option B": 0.6}
                }
            }
        )
        result = cognitive_core(context)
        print("✅ Decision making completed")
        print(f"   Decision: {result.get('decision', 'N/A')}")
    except Exception as e:
        print(f"❌ Decision making failed: {e}")

    print("\n" + "=" * 60)
    print("🎉 Simple DSPy integration example completed!")
    print("\nKey Benefits:")
    print("✅ Lightweight - No Ray Serve deployment required")
    print("✅ Fast - Direct cognitive core usage")
    print("✅ Easy to understand and modify")


if __name__ == "__main__":
    main()
