#!/usr/bin/env python3
"""
Test script for the COA 3-organ, 20-agent implementation.
This script verifies that the organism is properly initialized and functioning.
"""

import asyncio
import requests
import json
import time
from typing import Dict, Any

def test_organism_endpoints():
    """Test the organism endpoints to verify the implementation."""
    base_url = "http://localhost:8000"
    
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
        task_data = {
            "task_data": {
                "type": "test_task",
                "description": "Test task for COA organism",
                "parameters": {"test": True}
            }
        }
        response = requests.post(f"{base_url}/organism/execute/random", json=task_data)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                print(f"✅ Task executed successfully on organ: {data.get('organ_id')}")
                print(f"   Result: {data.get('result', 'No result data')}")
            else:
                print(f"❌ Task execution failed: {data.get('error')}")
        else:
            print(f"❌ Failed to execute task: {response.status_code}")
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
        response = requests.get("http://localhost:8000/ray/status")
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Ray cluster is running")
            print(f"   Status: {data.get('status', 'Unknown')}")
            print(f"   Address: {data.get('address', 'Unknown')}")
        else:
            print(f"❌ Ray cluster not accessible: {response.status_code}")
    except Exception as e:
        print(f"❌ Error testing Ray cluster: {e}")

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