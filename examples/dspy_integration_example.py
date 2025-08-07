#!/usr/bin/env python3
"""
DSPy Integration Example for SeedCore

This script demonstrates the comprehensive DSPy integration with SeedCore,
showing both embedded cognitive core usage and Ray Serve deployment modes.
"""

import os
import sys
import asyncio
import json
import time
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import ray
from seedcore.agents.cognitive_core import (
    CognitiveCore, 
    CognitiveContext, 
    CognitiveTaskType,
    initialize_cognitive_core,
    get_cognitive_core
)
from seedcore.agents.ray_actor import RayAgent
from seedcore.serve.cognitive_serve import (
    deploy_cognitive_core,
    CognitiveCoreClient,
    undeploy_cognitive_core
)
from seedcore.config.llm_config import configure_llm_openai


def example_1_basic_cognitive_core():
    """Example 1: Basic cognitive core usage."""
    print("=== Example 1: Basic Cognitive Core Usage ===")
    
    try:
        # Initialize cognitive core
        cognitive_core = initialize_cognitive_core()
        print(f"✅ Cognitive core initialized: {cognitive_core}")
        
        # Create a simple failure analysis context
        incident_context = {
            "incident_id": "test_incident_001",
            "error_message": "Task execution failed due to timeout",
            "agent_state": {
                "capability_score": 0.6,
                "memory_utilization": 0.4,
                "tasks_processed": 15
            },
            "task_context": {
                "task_type": "data_processing",
                "complexity": 0.8,
                "timestamp": time.time()
            }
        }
        
        # Create cognitive context
        context = CognitiveContext(
            agent_id="test_agent_001",
            task_type=CognitiveTaskType.FAILURE_ANALYSIS,
            input_data=incident_context
        )
        
        # Perform cognitive reasoning
        result = cognitive_core(context)
        
        print("🔍 Failure Analysis Result:")
        print(f"  Success: {result.get('success', False)}")
        print(f"  Thought Process: {result.get('thought', '')[:200]}...")
        print(f"  Proposed Solution: {result.get('proposed_solution', '')[:200]}...")
        print(f"  Confidence Score: {result.get('confidence_score', 0.0)}")
        print()
        
    except Exception as e:
        print(f"❌ Error in basic cognitive core example: {e}")
        print()


def example_2_task_planning():
    """Example 2: Task planning with cognitive reasoning."""
    print("=== Example 2: Task Planning ===")
    
    try:
        cognitive_core = get_cognitive_core()
        if not cognitive_core:
            cognitive_core = initialize_cognitive_core()
        
        # Create task planning context
        input_data = {
            "task_description": "Analyze a large dataset of customer interactions to identify patterns in support ticket resolution times",
            "agent_capabilities": {
                "capability_score": 0.7,
                "data_analysis_skills": 0.8,
                "machine_learning_skills": 0.6,
                "communication_skills": 0.9
            },
            "available_resources": {
                "compute_power": "high",
                "memory": "16GB",
                "time_constraint": "48 hours",
                "data_access": "full_access"
            }
        }
        
        context = CognitiveContext(
            agent_id="analyst_agent_001",
            task_type=CognitiveTaskType.TASK_PLANNING,
            input_data=input_data
        )
        
        result = cognitive_core(context)
        
        print("📋 Task Planning Result:")
        print(f"  Success: {result.get('success', False)}")
        print(f"  Step-by-Step Plan: {result.get('step_by_step_plan', '')[:300]}...")
        print(f"  Estimated Complexity: {result.get('estimated_complexity', '')[:200]}...")
        print(f"  Risk Assessment: {result.get('risk_assessment', '')[:200]}...")
        print()
        
    except Exception as e:
        print(f"❌ Error in task planning example: {e}")
        print()


def example_3_decision_making():
    """Example 3: Decision making with cognitive reasoning."""
    print("=== Example 3: Decision Making ===")
    
    try:
        cognitive_core = get_cognitive_core()
        if not cognitive_core:
            cognitive_core = initialize_cognitive_core()
        
        # Create decision making context
        input_data = {
            "decision_context": {
                "decision_type": "resource_allocation",
                "options": [
                    {"name": "Option A", "cost": 1000, "benefit": 0.8, "risk": 0.3},
                    {"name": "Option B", "cost": 1500, "benefit": 0.9, "risk": 0.2},
                    {"name": "Option C", "cost": 800, "benefit": 0.6, "risk": 0.5}
                ],
                "constraints": {
                    "budget_limit": 1200,
                    "time_constraint": "1 week",
                    "quality_requirement": 0.7
                }
            },
            "historical_data": {
                "previous_decisions": [
                    {"option": "Option A", "outcome": "success", "actual_cost": 950},
                    {"option": "Option B", "outcome": "success", "actual_cost": 1600},
                    {"option": "Option C", "outcome": "partial_success", "actual_cost": 750}
                ],
                "success_rate": {"Option A": 0.8, "Option B": 0.9, "Option C": 0.6}
            }
        }
        
        context = CognitiveContext(
            agent_id="manager_agent_001",
            task_type=CognitiveTaskType.DECISION_MAKING,
            input_data=input_data
        )
        
        result = cognitive_core(context)
        
        print("🎯 Decision Making Result:")
        print(f"  Success: {result.get('success', False)}")
        print(f"  Reasoning: {result.get('reasoning', '')[:300]}...")
        print(f"  Decision: {result.get('decision', '')[:200]}...")
        print(f"  Confidence: {result.get('confidence', 0.0)}")
        print(f"  Alternative Options: {result.get('alternative_options', '')[:200]}...")
        print()
        
    except Exception as e:
        print(f"❌ Error in decision making example: {e}")
        print()


async def example_4_ray_agent_integration():
    """Example 4: Integration with Ray agents."""
    print("=== Example 4: Ray Agent Integration ===")
    
    try:
        # Initialize Ray if not already done
        if not ray.is_initialized():
            ray.init(ignore_reinit_error=True)
        
        # Create a Ray agent
        agent = RayAgent.remote("cognitive_agent_001", {'E': 0.7, 'S': 0.2, 'O': 0.1})
        print(f"✅ Created Ray agent: {agent}")
        
        # Test basic agent functionality
        agent_id = ray.get(agent.get_id.remote())
        print(f"✅ Agent ID: {agent_id}")
        
        # Test cognitive reasoning through the agent
        # Note: This would require the agent to have access to memory systems
        # For demonstration, we'll show the method signature
        print("🧠 Agent cognitive methods available:")
        print("  - reason_about_failure(incident_id)")
        print("  - plan_complex_task(task_description, available_resources)")
        print("  - make_decision(decision_context, historical_data)")
        print("  - synthesize_memory(memory_fragments, synthesis_goal)")
        print("  - assess_capabilities(target_capabilities)")
        print()
        
        # Get agent summary stats
        stats = ray.get(agent.get_summary_stats.remote())
        print(f"📊 Agent Stats: {stats}")
        print()
        
    except Exception as e:
        print(f"❌ Error in Ray agent integration example: {e}")
        print()


async def example_5_ray_serve_deployment():
    """Example 5: Ray Serve deployment for scalable cognitive workloads."""
    print("=== Example 5: Ray Serve Deployment ===")
    
    try:
        # Deploy cognitive core as Ray Serve application
        deployment_name = deploy_cognitive_core(
            llm_provider="openai",
            model="gpt-4o",
            num_replicas=2,
            name="cognitive_core_demo"
        )
        print(f"✅ Deployed cognitive core as '{deployment_name}'")
        
        # Wait a moment for deployment to be ready
        await asyncio.sleep(2)
        
        # Create client
        client = CognitiveCoreClient("cognitive_core_demo")
        print(f"✅ Created cognitive core client")
        
        # Test failure analysis through Ray Serve
        incident_context = {
            "incident_id": "serve_test_001",
            "error_message": "Network timeout during API call",
            "agent_state": {
                "capability_score": 0.5,
                "memory_utilization": 0.3,
                "tasks_processed": 20
            }
        }
        
        result = await client.reason_about_failure("serve_agent_001", incident_context)
        
        print("🔍 Ray Serve Failure Analysis Result:")
        print(f"  Success: {result.get('success', False)}")
        print(f"  Agent ID: {result.get('agent_id', '')}")
        print(f"  Incident ID: {result.get('incident_id', '')}")
        print(f"  Thought Process: {result.get('thought_process', '')[:200]}...")
        print(f"  Proposed Solution: {result.get('proposed_solution', '')[:200]}...")
        print()
        
        # Test task planning through Ray Serve
        task_result = await client.plan_task(
            "serve_agent_001",
            "Implement a real-time monitoring dashboard for system metrics",
            {"capability_score": 0.8, "frontend_skills": 0.9, "backend_skills": 0.7},
            {"time_limit": "2 weeks", "team_size": 3, "budget": 5000}
        )
        
        print("📋 Ray Serve Task Planning Result:")
        print(f"  Success: {task_result.get('success', False)}")
        print(f"  Step-by-Step Plan: {task_result.get('step_by_step_plan', '')[:300]}...")
        print()
        
        # Clean up deployment
        undeploy_cognitive_core("cognitive_core_demo")
        print("✅ Undeployed cognitive core")
        print()
        
    except Exception as e:
        print(f"❌ Error in Ray Serve deployment example: {e}")
        print()


def example_6_memory_synthesis():
    """Example 6: Memory synthesis with cognitive reasoning."""
    print("=== Example 6: Memory Synthesis ===")
    
    try:
        cognitive_core = get_cognitive_core()
        if not cognitive_core:
            cognitive_core = initialize_cognitive_core()
        
        # Create memory synthesis context
        input_data = {
            "memory_fragments": [
                {
                    "id": "mem_001",
                    "content": "Customer support ticket resolved in 2 hours",
                    "timestamp": time.time() - 3600,
                    "tags": ["support", "resolution", "customer"]
                },
                {
                    "id": "mem_002", 
                    "content": "Similar ticket pattern observed in previous week",
                    "timestamp": time.time() - 86400,
                    "tags": ["pattern", "historical", "support"]
                },
                {
                    "id": "mem_003",
                    "content": "System performance degraded during peak hours",
                    "timestamp": time.time() - 7200,
                    "tags": ["performance", "system", "peak_hours"]
                }
            ],
            "synthesis_goal": "Identify patterns in customer support efficiency and system performance"
        }
        
        context = CognitiveContext(
            agent_id="analyst_agent_002",
            task_type=CognitiveTaskType.MEMORY_SYNTHESIS,
            input_data=input_data
        )
        
        result = cognitive_core(context)
        
        print("🧠 Memory Synthesis Result:")
        print(f"  Success: {result.get('success', False)}")
        print(f"  Synthesized Insight: {result.get('synthesized_insight', '')[:300]}...")
        print(f"  Confidence Level: {result.get('confidence_level', 0.0)}")
        print(f"  Related Patterns: {result.get('related_patterns', '')[:200]}...")
        print()
        
    except Exception as e:
        print(f"❌ Error in memory synthesis example: {e}")
        print()


def example_7_capability_assessment():
    """Example 7: Capability assessment with cognitive reasoning."""
    print("=== Example 7: Capability Assessment ===")
    
    try:
        cognitive_core = get_cognitive_core()
        if not cognitive_core:
            cognitive_core = initialize_cognitive_core()
        
        # Create capability assessment context
        input_data = {
            "performance_data": {
                "tasks_processed": 50,
                "successful_tasks": 42,
                "quality_scores": [0.8, 0.9, 0.7, 0.85, 0.9, 0.8, 0.75, 0.9, 0.85, 0.8],
                "capability_score": 0.75,
                "memory_utilization": 0.6,
                "peer_interactions": {"agent_001": 5, "agent_002": 3, "agent_003": 7}
            },
            "current_capabilities": {
                "capability_score": 0.75,
                "role_probabilities": {"E": 0.6, "S": 0.3, "O": 0.1},
                "skill_deltas": {"data_analysis": 0.2, "communication": 0.1, "problem_solving": 0.15},
                "performance_history": {
                    "tasks_processed": 50,
                    "successful_tasks": 42,
                    "avg_quality": 0.84
                }
            },
            "target_capabilities": {
                "capability_score": 0.9,
                "role_probabilities": {"E": 0.7, "S": 0.2, "O": 0.1},
                "required_skills": {
                    "data_analysis": 0.8,
                    "communication": 0.9,
                    "problem_solving": 0.85,
                    "machine_learning": 0.7
                }
            }
        }
        
        context = CognitiveContext(
            agent_id="assessment_agent_001",
            task_type=CognitiveTaskType.CAPABILITY_ASSESSMENT,
            input_data=input_data
        )
        
        result = cognitive_core(context)
        
        print("📊 Capability Assessment Result:")
        print(f"  Success: {result.get('success', False)}")
        print(f"  Capability Gaps: {result.get('capability_gaps', '')[:300]}...")
        print(f"  Improvement Plan: {result.get('improvement_plan', '')[:300]}...")
        print(f"  Priority Recommendations: {result.get('priority_recommendations', '')[:200]}...")
        print()
        
    except Exception as e:
        print(f"❌ Error in capability assessment example: {e}")
        print()


async def main():
    """Run all DSPy integration examples."""
    print("🧠 DSPy Integration Examples for SeedCore")
    print("=" * 60)
    print()
    
    # Check if OpenAI API key is available
    if not os.getenv('OPENAI_API_KEY'):
        print("⚠️  Warning: OPENAI_API_KEY not set. Some examples may fail.")
        print("   Set your OpenAI API key in the environment to test with real LLM responses.")
        print()
    
    try:
        # Run examples
        example_1_basic_cognitive_core()
        example_2_task_planning()
        example_3_decision_making()
        await example_4_ray_agent_integration()
        await example_5_ray_serve_deployment()
        example_6_memory_synthesis()
        example_7_capability_assessment()
        
        print("✅ All DSPy integration examples completed successfully!")
        print()
        print("🎯 Summary of Integration Modes:")
        print("  1. Embedded Cognitive Core: Direct integration with agents")
        print("  2. Ray Serve Deployment: Scalable, shared inference")
        print("  3. FastAPI Endpoints: Lightweight testing and experimentation")
        print()
        print("🚀 Next Steps:")
        print("  - Configure your OpenAI API key for real LLM responses")
        print("  - Deploy Ray Serve for production workloads")
        print("  - Integrate with your existing agent workflows")
        print("  - Monitor cognitive reasoning performance and costs")
        
    except Exception as e:
        print(f"❌ Error running examples: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(asyncio.run(main())) 