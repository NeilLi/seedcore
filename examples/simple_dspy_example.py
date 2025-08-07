#!/usr/bin/env python3
"""
Simple DSPy Integration Example for SeedCore

This script demonstrates basic DSPy integration with SeedCore using the embedded
cognitive core, without the complexity of Ray Serve deployment.
"""

import os
import sys
import json
import time
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from seedcore.agents.cognitive_core import (
    CognitiveCore, 
    CognitiveContext, 
    CognitiveTaskType,
    initialize_cognitive_core,
    get_cognitive_core
)
from seedcore.config.llm_config import configure_llm_openai

def main():
    """Main function demonstrating simple DSPy integration."""
    print("🧠 Simple DSPy Integration Example for SeedCore")
    print("=" * 60)
    
    # Configure LLM (you'll need to set OPENAI_API_KEY)
    try:
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            print("⚠️ OPENAI_API_KEY environment variable not set")
            print("Please set OPENAI_API_KEY environment variable")
            return
        
        configure_llm_openai(api_key)
        print("✅ LLM configuration loaded")
    except Exception as e:
        print(f"⚠️ LLM configuration failed: {e}")
        print("Please set OPENAI_API_KEY environment variable")
        return
    
    # Initialize cognitive core
    print("\n🚀 Initializing cognitive core...")
    try:
        cognitive_core = initialize_cognitive_core()
        print("✅ Cognitive core initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize cognitive core: {e}")
        return
    
    # Example 1: Failure Analysis
    print("\n=== Example 1: Failure Analysis ===")
    try:
        context = CognitiveContext(
            agent_id="test_agent_1",
            task_type=CognitiveTaskType.FAILURE_ANALYSIS,
            input_data={
                "incident_id": "test_incident_001",
                "error_message": "Task timeout after 30 seconds",
                "agent_state": {
                    "capability_score": 0.7,
                    "memory_utilization": 0.4,
                    "tasks_processed": 15
                }
            }
        )
        
        result = cognitive_core(context)
        print(f"✅ Failure analysis completed")
        print(f"   Thought: {result.get('thought', 'N/A')[:100]}...")
        print(f"   Solution: {result.get('proposed_solution', 'N/A')[:100]}...")
        print(f"   Confidence: {result.get('confidence_score', 'N/A')}")
        
    except Exception as e:
        print(f"❌ Failure analysis failed: {e}")
    
    # Example 2: Task Planning
    print("\n=== Example 2: Task Planning ===")
    try:
        context = CognitiveContext(
            agent_id="test_agent_2",
            task_type=CognitiveTaskType.TASK_PLANNING,
            input_data={
                "task_description": "Process a large dataset and generate insights",
                "agent_capabilities": {
                    "data_processing": 0.8,
                    "analysis": 0.6,
                    "memory": 0.7
                },
                "available_resources": {
                    "cpu_cores": 4,
                    "memory_gb": 8,
                    "time_limit": "2 hours"
                }
            }
        )
        
        result = cognitive_core(context)
        print(f"✅ Task planning completed")
        print(f"   Plan: {result.get('step_by_step_plan', 'N/A')[:100]}...")
        print(f"   Complexity: {result.get('estimated_complexity', 'N/A')}")
        print(f"   Risk: {result.get('risk_assessment', 'N/A')[:100]}...")
        
    except Exception as e:
        print(f"❌ Task planning failed: {e}")
    
    # Example 3: Decision Making
    print("\n=== Example 3: Decision Making ===")
    try:
        context = CognitiveContext(
            agent_id="test_agent_3",
            task_type=CognitiveTaskType.DECISION_MAKING,
            input_data={
                "decision_context": {
                    "options": ["Option A: Fast but expensive", "Option B: Slow but cheap"],
                    "constraints": ["Budget: $1000", "Time: 1 week"],
                    "goals": ["Maximize quality", "Minimize cost"]
                },
                "historical_data": {
                    "previous_decisions": ["Option A chosen 3 times", "Option B chosen 1 time"],
                    "success_rates": {"Option A": 0.8, "Option B": 0.6}
                }
            }
        )
        
        result = cognitive_core(context)
        print(f"✅ Decision making completed")
        print(f"   Reasoning: {result.get('reasoning', 'N/A')[:100]}...")
        print(f"   Decision: {result.get('decision', 'N/A')}")
        print(f"   Confidence: {result.get('confidence', 'N/A')}")
        
    except Exception as e:
        print(f"❌ Decision making failed: {e}")
    
    # Example 4: Problem Solving
    print("\n=== Example 4: Problem Solving ===")
    try:
        context = CognitiveContext(
            agent_id="test_agent_4",
            task_type=CognitiveTaskType.PROBLEM_SOLVING,
            input_data={
                "problem_statement": "System performance is degrading under high load",
                "constraints": {
                    "budget": "$500",
                    "time": "24 hours",
                    "downtime": "minimal"
                },
                "available_tools": {
                    "monitoring": "Prometheus + Grafana",
                    "profiling": "Python cProfile",
                    "optimization": "Code review tools"
                }
            }
        )
        
        result = cognitive_core(context)
        print(f"✅ Problem solving completed")
        print(f"   Approach: {result.get('solution_approach', 'N/A')[:100]}...")
        print(f"   Steps: {result.get('solution_steps', 'N/A')[:100]}...")
        print(f"   Metrics: {result.get('success_metrics', 'N/A')}")
        
    except Exception as e:
        print(f"❌ Problem solving failed: {e}")
    
    # Example 5: Memory Synthesis
    print("\n=== Example 5: Memory Synthesis ===")
    try:
        context = CognitiveContext(
            agent_id="test_agent_5",
            task_type=CognitiveTaskType.MEMORY_SYNTHESIS,
            input_data={
                "memory_fragments": [
                    {"type": "task_completion", "content": "Successfully processed 1000 records", "timestamp": "2024-01-01"},
                    {"type": "error", "content": "Timeout occurred on large dataset", "timestamp": "2024-01-02"},
                    {"type": "optimization", "content": "Implemented batch processing", "timestamp": "2024-01-03"}
                ],
                "synthesis_goal": "Identify patterns in task performance and optimization opportunities"
            }
        )
        
        result = cognitive_core(context)
        print(f"✅ Memory synthesis completed")
        print(f"   Insight: {result.get('synthesized_insight', 'N/A')[:100]}...")
        print(f"   Confidence: {result.get('confidence_level', 'N/A')}")
        print(f"   Patterns: {result.get('related_patterns', 'N/A')[:100]}...")
        
    except Exception as e:
        print(f"❌ Memory synthesis failed: {e}")
    
    # Example 6: Capability Assessment
    print("\n=== Example 6: Capability Assessment ===")
    try:
        context = CognitiveContext(
            agent_id="test_agent_6",
            task_type=CognitiveTaskType.CAPABILITY_ASSESSMENT,
            input_data={
                "agent_performance_data": {
                    "tasks_completed": 50,
                    "success_rate": 0.85,
                    "avg_processing_time": "2.5 seconds",
                    "error_rate": 0.15
                },
                "current_capabilities": {
                    "data_processing": 0.7,
                    "analysis": 0.6,
                    "optimization": 0.5
                },
                "target_capabilities": {
                    "data_processing": 0.9,
                    "analysis": 0.8,
                    "optimization": 0.7
                }
            }
        )
        
        result = cognitive_core(context)
        print(f"✅ Capability assessment completed")
        print(f"   Gaps: {result.get('capability_gaps', 'N/A')[:100]}...")
        print(f"   Plan: {result.get('improvement_plan', 'N/A')[:100]}...")
        print(f"   Priorities: {result.get('priority_recommendations', 'N/A')[:100]}...")
        
    except Exception as e:
        print(f"❌ Capability assessment failed: {e}")
    
    print("\n" + "=" * 60)
    print("🎉 Simple DSPy integration example completed!")
    print("\nKey Benefits:")
    print("✅ Lightweight - No Ray Serve deployment overhead")
    print("✅ Fast - Direct cognitive core usage")
    print("✅ Simple - Easy to understand and modify")
    print("✅ Resource-efficient - Minimal memory and CPU usage")
    print("\nNext Steps:")
    print("1. Set OPENAI_API_KEY environment variable")
    print("2. Run: python examples/simple_dspy_example.py")
    print("3. Modify the examples to fit your use case")

if __name__ == "__main__":
    main()
