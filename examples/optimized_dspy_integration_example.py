#!/usr/bin/env python3
"""
Optimized DSPy Integration Example for SeedCore

This script demonstrates DSPy integration with SeedCore using an optimized approach
that integrates with the existing serve_entrypoint.py to ensure proper namespace
management and avoid deployment conflicts.
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
from ray import serve
from seedcore.agents.cognitive_core import (
    CognitiveCore, 
    CognitiveContext, 
    CognitiveTaskType,
    initialize_cognitive_core,
    get_cognitive_core
)
from seedcore.agents.ray_actor import RayAgent
from seedcore.serve.cognitive_serve import (
    CognitiveCoreServe,
    CognitiveCoreClient,
    CognitiveRequest,
    CognitiveResponse
)
from seedcore.config.llm_config import configure_llm_openai

# Configuration constants
COGNITIVE_APP_NAME = "sc_cognitive"  # Use consistent naming with serve_entrypoint
COGNITIVE_ROUTE_PREFIX = "/cognitive"      # Dedicated route prefix
MAX_DEPLOY_RETRIES = 30
DELAY = 2

def wait_for_http_ready(url, max_retries=30, delay=2):
    """Wait for HTTP endpoint to be ready."""
    import urllib.request
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    print(f"✅ Service ready at {url}")
                    return True
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"🔄 Service not ready ({e}); retrying in {delay}s...")
                time.sleep(delay)
            else:
                print(f"❌ Service at {url} failed to become ready after {max_retries} attempts.")
    return False

def check_existing_deployments():
    """Check for existing deployments and handle conflicts."""
    try:
        # Check if our cognitive app is already deployed
        existing_apps = serve.list_applications()
        print(f"🔍 Existing applications: {list(existing_apps.keys())}")
        
        if COGNITIVE_APP_NAME in existing_apps:
            print(f"✅ Cognitive app '{COGNITIVE_APP_NAME}' already deployed")
            return True
        else:
            print(f"📝 Cognitive app '{COGNITIVE_APP_NAME}' not found, will deploy")
            return False
            
    except Exception as e:
        print(f"⚠️ Could not check existing deployments: {e}")
        return False

def deploy_cognitive_core_optimized(
    llm_provider: str = "openai",
    model: str = "gpt-4o",
    num_replicas: int = 2
) -> bool:
    """
    Deploy the cognitive core with optimized conflict handling.
    
    Args:
        llm_provider: LLM provider to use
        model: Model to use
        num_replicas: Number of replicas to deploy
        
    Returns:
        True if deployment successful, False otherwise
    """
    try:
        # Check if already deployed
        if check_existing_deployments():
            return True
        
        print(f"🚀 Deploying cognitive core as '{COGNITIVE_APP_NAME}'...")
        
        # Ensure Ray is initialized
        if not ray.is_initialized():
            ray_address = os.getenv("RAY_ADDRESS")
            if ray_address:
                ray.init(address=ray_address, log_to_driver=False)
                print(f"✅ Connected to Ray cluster at {ray_address}")
            else:
                ray.init()
                print("✅ Connected to local Ray instance")
        
        # Ensure Serve is running
        try:
            serve_status = serve.status()
            print(f"✅ Serve is running: {serve_status}")
        except Exception:
            print("🔧 Starting Serve...")
            serve.start(
                http_options={
                    'host': '0.0.0.0',
                    'port': 8000
                },
                detached=True
            )
            print("✅ Serve started")
        
        # Create deployment
        deployment = CognitiveCoreServe.options(
            num_replicas=num_replicas,
            name=COGNITIVE_APP_NAME
        ).bind(llm_provider, model)
        
        # Deploy with consistent naming and route prefix
        serve.run(
            deployment, 
            name=COGNITIVE_APP_NAME,
            route_prefix=COGNITIVE_ROUTE_PREFIX
        )
        
        # Wait for deployment to be ready
        print("⏳ Waiting for cognitive core deployment to be ready...")
        health_url = f"http://localhost:8000{COGNITIVE_ROUTE_PREFIX}/health"
        if wait_for_http_ready(health_url, MAX_DEPLOY_RETRIES, DELAY):
            print(f"✅ Cognitive core deployed successfully as '{COGNITIVE_APP_NAME}'")
            print(f"   Route: {COGNITIVE_ROUTE_PREFIX}")
            print(f"   Health: {health_url}")
            return True
        else:
            print(f"❌ Cognitive core deployment failed to become ready")
            return False
        
    except Exception as e:
        print(f"❌ Failed to deploy cognitive core: {e}")
        import traceback
        traceback.print_exc()
        return False

def undeploy_cognitive_core_optimized():
    """Undeploy the cognitive core with proper cleanup."""
    try:
        print(f"🔄 Undeploying cognitive core '{COGNITIVE_APP_NAME}'...")
        serve.delete(COGNITIVE_APP_NAME)
        print(f"✅ Cognitive core '{COGNITIVE_APP_NAME}' undeployed")
        return True
    except Exception as e:
        print(f"⚠️ Failed to undeploy cognitive core: {e}")
        return False

def example_1_basic_cognitive_core():
    """Example 1: Basic cognitive core usage."""
    print("=== Example 1: Basic Cognitive Core Usage ===")
    
    try:
        # Initialize cognitive core
        cognitive_core = initialize_cognitive_core()
        print("✅ Cognitive core initialized")
        
        # Test failure analysis
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
        print("✅ Failure analysis completed")
        print(f"   Thought: {result.get('thought', 'N/A')[:100]}...")
        print(f"   Solution: {result.get('proposed_solution', 'N/A')[:100]}...")
        print(f"   Confidence: {result.get('confidence_score', 'N/A')}")
        print()
        
    except Exception as e:
        print(f"❌ Error in basic cognitive core example: {e}")
        print()

async def example_2_optimized_ray_serve_deployment():
    """Example 2: Optimized Ray Serve deployment."""
    print("=== Example 2: Optimized Ray Serve Deployment ===")
    
    try:
        # Deploy cognitive core with optimized approach
        deployment_success = deploy_cognitive_core_optimized(
            llm_provider="openai",
            model="gpt-4o",
            num_replicas=2
        )
        
        if not deployment_success:
            print("❌ Deployment failed, skipping Ray Serve examples")
            return
        
        # Wait a moment for deployment to be fully ready
        await asyncio.sleep(3)
        
        # Create client
        client = CognitiveCoreClient(COGNITIVE_APP_NAME)
        print(f"✅ Created cognitive core client for '{COGNITIVE_APP_NAME}'")
        
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
        
        # Test decision making through Ray Serve
        decision_result = await client.make_decision(
            "serve_agent_001",
            {
                "options": ["Option A: Fast but expensive", "Option B: Slow but cheap"],
                "constraints": ["Budget: $1000", "Time: 1 week"],
                "goals": ["Maximize quality", "Minimize cost"]
            },
            {
                "previous_decisions": ["Option A chosen 3 times", "Option B chosen 1 time"],
                "success_rates": {"Option A": 0.8, "Option B": 0.6}
            }
        )
        
        print("🎯 Ray Serve Decision Making Result:")
        print(f"  Success: {decision_result.get('success', False)}")
        print(f"  Reasoning: {decision_result.get('reasoning', '')[:200]}...")
        print(f"  Decision: {decision_result.get('decision', '')}")
        print(f"  Confidence: {decision_result.get('confidence', 'N/A')}")
        print()
        
        # Show deployment status
        print("📊 Deployment Status:")
        try:
            serve_status = serve.status()
            apps = serve_status.applications
            if COGNITIVE_APP_NAME in apps:
                app_status = apps[COGNITIVE_APP_NAME]
                print(f"  App: {COGNITIVE_APP_NAME}")
                print(f"  Status: {app_status.status}")
                print(f"  Route: {COGNITIVE_ROUTE_PREFIX}")
                print(f"  Deployments: {list(app_status.deployments.keys())}")
            else:
                print(f"  App '{COGNITIVE_APP_NAME}' not found in status")
        except Exception as e:
            print(f"  Could not get deployment status: {e}")
        
        print()
        
    except Exception as e:
        print(f"❌ Error in optimized Ray Serve deployment example: {e}")
        import traceback
        traceback.print_exc()
        print()

def example_3_ray_agent_integration():
    """Example 3: Ray Agent integration with cognitive core."""
    print("=== Example 3: Ray Agent Integration ===")
    
    try:
        # Create a Ray agent
        agent_id = "cognitive_agent_001"
        agent = RayAgent.remote(
            agent_id=agent_id,
            initial_capability=0.7,
            initial_memory_utilization=0.3
        )
        
        print(f"✅ Created Ray agent: {agent_id}")
        
        # Get agent heartbeat to see cognitive core integration
        heartbeat = ray.get(agent.get_heartbeat.remote())
        print(f"✅ Agent heartbeat: {heartbeat}")
        
        # Execute a task that uses cognitive reasoning
        task_data = {
            "task_type": "cognitive_analysis",
            "input": "Analyze system performance patterns",
            "complexity": 0.6
        }
        
        result = ray.get(agent.execute_task.remote(task_data))
        print(f"✅ Task execution result: {result}")
        print()
        
    except Exception as e:
        print(f"❌ Error in Ray agent integration example: {e}")
        print()

def example_4_api_endpoints():
    """Example 4: Test API endpoints."""
    print("=== Example 4: API Endpoints ===")
    
    try:
        import requests
        
        base_url = "http://localhost:8002"
        cognitive_url = f"http://localhost:8000{COGNITIVE_ROUTE_PREFIX}"
        
        # Test DSPy status endpoint
        print("🔍 Testing DSPy status endpoint...")
        response = requests.get(f"{base_url}/dspy/status", timeout=10)
        if response.status_code == 200:
            status_data = response.json()
            print(f"✅ DSPy status: {status_data}")
        else:
            print(f"❌ DSPy status failed: {response.status_code}")
        
        # Test cognitive core health endpoint
        print("🔍 Testing cognitive core health endpoint...")
        try:
            response = requests.get(f"{cognitive_url}/health", timeout=10)
            if response.status_code == 200:
                print(f"✅ Cognitive core health: {response.json()}")
            else:
                print(f"❌ Cognitive core health failed: {response.status_code}")
        except Exception as e:
            print(f"⚠️ Cognitive core health check failed: {e}")
        
        print()
        
    except Exception as e:
        print(f"❌ Error in API endpoints example: {e}")
        print()

async def main():
    """Main function demonstrating optimized DSPy integration."""
    print("🧠 Optimized DSPy Integration Example for SeedCore")
    print("=" * 60)
    
    # Configure LLM
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
    
    # Run examples
    example_1_basic_cognitive_core()
    await example_2_optimized_ray_serve_deployment()
    example_3_ray_agent_integration()
    example_4_api_endpoints()
    
    # Cleanup
    print("🧹 Cleaning up...")
    undeploy_cognitive_core_optimized()
    
    print("\n" + "=" * 60)
    print("🎉 Optimized DSPy integration example completed!")
    print("\nKey Improvements:")
    print("✅ Consistent naming with serve_entrypoint.py")
    print("✅ Proper namespace management")
    print("✅ Conflict detection and handling")
    print("✅ Optimized deployment process")
    print("✅ Better error handling and status reporting")
    print("\nBenefits:")
    print("✅ No deployment conflicts")
    print("✅ Single DSPy serve instance")
    print("✅ Proper route prefix management")
    print("✅ Integration with existing Ray cluster")

if __name__ == "__main__":
    asyncio.run(main())
