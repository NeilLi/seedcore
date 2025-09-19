#!/usr/bin/env python3
"""
Test script for the COA 3-organ, 20-agent implementation.
This script verifies that the organism is properly initialized and functioning.
"""

import asyncio
import requests
import json
import time
import os
from typing import Dict, Any

def teardown_module(module):
    """Ensure Ray is properly shut down after tests to prevent state contamination."""
    try:
        import ray
        if ray.is_initialized():
            ray.shutdown()
            print("✅ Ray shut down in teardown_module")
    except Exception as e:
        print(f"Ray teardown skipped: {e}")

def test_organism_endpoints():
    """Test the organism endpoints to verify the implementation."""
    # When running inside the container, use the internal service address
    # Check if we're running inside the container
    if os.path.exists('/.dockerenv') or os.getenv('KUBERNETES_SERVICE_HOST'):
        # Running inside container, use internal service address
        base_url = "http://localhost:8002"
        print("   Running inside container, using internal service address")
    else:
        # Running locally, use environment variable or default
        base_url = os.getenv("SEEDCORE_API", "localhost:8002")
        if not base_url.startswith("http"):
            base_url = f"http://{base_url}"
    
    print("🔍 Testing COA Organism Implementation")
    print("=" * 50)
    
    # Test 1: Check organism status
    print("\n1. Testing organism status...")
    try:
        response = requests.get(f"{base_url}/organism/status")
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                organs = data.get("data", [])
                print(f"✅ Organism status retrieved successfully")
                print(f"   Found {len(organs)} organs:")
                for organ in organs:
                    print(f"   - {organ.get('organ_id')} ({organ.get('organ_type')}): {organ.get('agent_count')} agents")
            else:
                print(f"❌ Organism not initialized: {data.get('error')}")
        else:
            print(f"❌ Failed to get organism status: {response.status_code}")
    except Exception as e:
        print(f"❌ Error testing organism status: {e}")
    
    # Test 2: Get organism summary
    print("\n2. Testing organism summary...")
    try:
        response = requests.get(f"{base_url}/organism/summary")
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                summary = data.get("summary", {})
                print(f"✅ Organism summary retrieved successfully")
                print(f"   Initialized: {summary.get('initialized')}")
                print(f"   Organ count: {summary.get('organ_count')}")
                print(f"   Total agents: {summary.get('total_agent_count')}")
                
                # Show detailed organ info
                organs = summary.get("organs", {})
                for organ_id, organ_info in organs.items():
                    if isinstance(organ_info, dict) and "error" not in organ_info:
                        print(f"   - {organ_id}: {organ_info.get('agent_count', 0)} agents")
                    else:
                        print(f"   - {organ_id}: Error getting status")
            else:
                print(f"❌ Failed to get summary: {data.get('error')}")
        else:
            print(f"❌ Failed to get organism summary: {response.status_code}")
    except Exception as e:
        print(f"❌ Error testing organism summary: {e}")
    
    # Test 3: Execute task on random organ
    print("\n3. Testing task execution on random organ...")
    try:
        # Get available organs first to select a random one
        response = requests.get(f"{base_url}/organism/status")
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                # Use the same data structure as test 1: data.get("data", [])
                organs = data.get("data", [])
                if organs:
                    # Select a random organ from available organs
                    import random
                    random_organ = random.choice(organs)
                    organ_id = random_organ.get("organ_id", "cognitive_organ_1")  # fallback
                    
                    print(f"   Selected random organ: {organ_id}")
                    
                    task_data = {
                        "task_data": {
                            "type": "test_task",
                            "description": "Test task for COA organism",
                            "parameters": {"test": True}
                        }
                    }
                    response = requests.post(f"{base_url}/organism/execute/{organ_id}", json=task_data)
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("success"):
                            print(f"✅ Task executed successfully on organ: {data.get('organ_id')}")
                            print(f"   Result: {data.get('result', 'No result data')}")
                        else:
                            print(f"❌ Task execution failed: {data.get('error')}")
                    else:
                        print(f"❌ Failed to execute task: {response.status_code}")
                else:
                    print("❌ No organs available for random selection")
                    print(f"   Debug: Response data structure: {data}")
            else:
                print(f"❌ Failed to get organism status: {data.get('error')}")
        else:
            print(f"❌ Failed to get organism status: {response.status_code}")
    except Exception as e:
        print(f"❌ Error testing task execution: {e}")
    
    # Test 4: Execute task on specific organ
    print("\n4. Testing task execution on specific organ...")
    try:
        task_data = {
            "task_data": {
                "type": "cognitive_task",
                "description": "Test cognitive reasoning task",
                "parameters": {"complexity": "high"}
            }
        }
        response = requests.post(f"{base_url}/organism/execute/cognitive_organ_1", json=task_data)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                print(f"✅ Cognitive task executed successfully")
                print(f"   Result: {data.get('result', 'No result data')}")
            else:
                print(f"❌ Cognitive task failed: {data.get('error')}")
        else:
            print(f"❌ Failed to execute cognitive task: {response.status_code}")
    except Exception as e:
        print(f"❌ Error testing cognitive task: {e}")
    
    print("\n" + "=" * 50)
    print("🎯 COA Organism Test Complete")
    print("=" * 50)

def test_ray_cluster():
    """Test Ray cluster status to ensure it's running."""
    print("\n🔍 Testing Ray Cluster Status")
    print("-" * 30)
    
    try:
        # When running inside the container, use the internal service address
        # Check if we're running inside the container
        if os.path.exists('/.dockerenv') or os.getenv('KUBERNETES_SERVICE_HOST'):
            # Running inside container, use internal service address
            base_url = "http://localhost:8002"
            print("   Running inside container, using internal service address")
        else:
            # Running locally, use environment variable or default
            base_url = os.getenv("SEEDCORE-API", "localhost:8002")
            if not base_url.startswith("http"):
                base_url = f"http://{base_url}"
        
        print(f"   Testing endpoint: {base_url}/ray/status")
        response = requests.get(f"{base_url}/ray/status", timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Ray cluster is running")
            print(f"   Ray configured: {data.get('ray_configured', 'Unknown')}")
            print(f"   Ray available: {data.get('ray_available', 'Unknown')}")
            print(f"   Config: {data.get('config', 'Unknown')}")
            if 'cluster_info' in data:
                cluster_info = data['cluster_info']
                print(f"   Cluster info: {cluster_info}")
        elif response.status_code == 500:
            # Try to get error details from response body
            try:
                error_data = response.json()
                print(f"❌ Ray cluster endpoint returned 500 error:")
                print(f"   Error: {error_data.get('error', 'Unknown server error')}")
                if 'error_type' in error_data:
                    print(f"   Error type: {error_data.get('error_type')}")
            except:
                print(f"❌ Ray cluster endpoint returned 500 error (no error details)")
                print(f"   Response body: {response.text[:200]}...")
        else:
            print(f"❌ Ray cluster not accessible: {response.status_code}")
            print(f"   Response body: {response.text[:200]}...")
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Connection error: {e}")
        print("   Make sure the seedcore-api service is running")
    except requests.exceptions.Timeout as e:
        print(f"❌ Timeout error: {e}")
        print("   The request took too long to complete")
    except Exception as e:
        print(f"❌ Error testing Ray cluster: {e}")
        print(f"   Error type: {type(e).__name__}")

if __name__ == "__main__":
    print("🚀 Starting COA Organism Tests...")
    
    # Test Ray cluster first
    test_ray_cluster()
    
    # Test organism endpoints
    test_organism_endpoints()
    
    print("\n💡 Next Steps:")
    print("   • Check the logs: docker logs seedcore-api")
    print("   • Access dashboard: http://localhost:8265")
    print("   • Monitor real-time: docker logs -f seedcore-api") 