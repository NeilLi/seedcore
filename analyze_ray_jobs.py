#!/usr/bin/env python3
"""
Comprehensive Ray cluster and jobs analysis script.
"""

import ray
import json
import time
from typing import Dict, List, Any

def analyze_ray_cluster():
    """Analyze the Ray cluster status and jobs."""
    
    print("🔍 Analyzing Ray Cluster and Jobs")
    print("=" * 50)
    
    # Initialize Ray
    if not ray.is_initialized():
        ray.init(address="ray://ray-head:10001", namespace="seedcore")
    
    # 1. Cluster Resources
    print("\n📊 Cluster Resources:")
    print("-" * 30)
    cluster_resources = ray.cluster_resources()
    available_resources = ray.available_resources()
    
    print(f"Total Resources: {cluster_resources}")
    print(f"Available Resources: {available_resources}")
    
    # 2. Nodes
    print("\n🖥️  Cluster Nodes:")
    print("-" * 30)
    nodes = ray.nodes()
    print(f"Total Nodes: {len(nodes)}")
    
    for i, node in enumerate(nodes):
        print(f"Node {i+1}:")
        print(f"  - ID: {node['NodeID'][:16]}...")
        print(f"  - Address: {node['NodeManagerAddress']}")
        print(f"  - Alive: {node['Alive']}")
        print(f"  - Resources: {node['Resources']}")
    
    # 3. Named Actors
    print("\n🎭 Named Actors:")
    print("-" * 30)
    try:
        # Try to get named actors using different methods
        named_actors = []
        
        # Method 1: Try to get specific actors we know should exist
        organ_names = ["cognitive_organ_1", "actuator_organ_1", "utility_organ_1"]
        for name in organ_names:
            try:
                actor = ray.get_actor(name)
                named_actors.append(name)
                print(f"✅ Found actor: {name}")
            except ValueError:
                print(f"❌ Actor not found: {name}")
            except Exception as e:
                print(f"⚠️  Error checking actor {name}: {e}")
        
        # Method 2: Try to get other known actors
        other_actors = ["MissTracker", "SharedCache", "MwStore"]
        for name in other_actors:
            try:
                actor = ray.get_actor(name)
                named_actors.append(name)
                print(f"✅ Found actor: {name}")
            except ValueError:
                print(f"❌ Actor not found: {name}")
            except Exception as e:
                print(f"⚠️  Error checking actor {name}: {e}")
        
        print(f"\nTotal named actors found: {len(named_actors)}")
        
    except Exception as e:
        print(f"Error listing named actors: {e}")
    
    # 4. Check our organism status via API
    print("\n🧬 Organism Status:")
    print("-" * 30)
    try:
        import requests
        response = requests.get("http://localhost:8000/organism/status", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                organs = data.get("data", [])
                print(f"✅ Organism API working - Found {len(organs)} organs:")
                for organ in organs:
                    print(f"  - {organ.get('organ_id')}: {organ.get('agent_count')} agents")
            else:
                print(f"❌ Organism API error: {data.get('error')}")
        else:
            print(f"❌ Organism API failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Error checking organism API: {e}")
    
    # 5. Check Ray Dashboard API
    print("\n🌐 Ray Dashboard Status:")
    print("-" * 30)
    try:
        import requests
        # Try different dashboard endpoints
        endpoints = [
            "http://localhost:8265/api/cluster",
            "http://localhost:8265/api/actors",
            "http://localhost:8265/api/jobs"
        ]
        
        for endpoint in endpoints:
            try:
                response = requests.get(endpoint, timeout=5)
                print(f"✅ {endpoint}: {response.status_code}")
                if response.status_code == 200:
                    try:
                        data = response.json()
                        print(f"   Data keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
                    except:
                        print(f"   Response length: {len(response.text)} chars")
            except Exception as e:
                print(f"❌ {endpoint}: {e}")
                
    except Exception as e:
        print(f"❌ Error checking dashboard: {e}")
    
    # 6. Test task execution
    print("\n⚡ Task Execution Test:")
    print("-" * 30)
    try:
        import requests
        task_data = {
            "task_data": {
                "type": "test_task",
                "description": "Job analysis test",
                "parameters": {"test": True}
            }
        }
        response = requests.post("http://localhost:8000/organism/execute/cognitive_organ_1", 
                               json=task_data, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                print("✅ Task execution successful")
                result = data.get("result", {})
                print(f"   Agent ID: {result.get('agent_id', 'Unknown')}")
                print(f"   Success: {result.get('success', 'Unknown')}")
                print(f"   Quality: {result.get('quality', 'Unknown')}")
            else:
                print(f"❌ Task execution failed: {data.get('error')}")
        else:
            print(f"❌ Task execution HTTP error: {response.status_code}")
    except Exception as e:
        print(f"❌ Error testing task execution: {e}")
    
    print("\n" + "=" * 50)
    print("🎯 Ray Cluster Analysis Complete")
    print("=" * 50)

if __name__ == "__main__":
    analyze_ray_cluster() 