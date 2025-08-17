#!/usr/bin/env python3
"""
Comprehensive Ray cluster and jobs analysis script.
"""

import ray
import json
import time
from typing import Dict, List, Any
import os

def analyze_ray_cluster():
    """Analyze the Ray cluster status and jobs."""
    
    print("🔍 Analyzing Ray Cluster and Jobs")
    print("=" * 50)
    
    # Initialize Ray
    # Get namespace from environment, default to "seedcore-dev" for consistency
    ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
    
    # Get Ray address from environment variables, with fallback to the actual service name
    # Note: RAY_HOST env var is set to 'seedcore-head-svc' but actual service is 'seedcore-svc-head-svc'
    ray_host = os.getenv("RAY_HOST", "seedcore-svc-head-svc")
    ray_port = os.getenv("RAY_PORT", "10001")
    ray_address = f"ray://{ray_host}:{ray_port}"
    
    print(f"🔗 Connecting to Ray at: {ray_address}")
    ray.init(address=ray_address, namespace=ray_namespace)
    
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
    
    # 3. List named actors
    print("\n🎭 Named Actors:")
    print("-" * 30)
    try:
        # Use Ray state API to get all actors instead of individual lookups
        from ray.util.state import list_actors
        
        all_actors = list_actors()
        named_actors = []
        
        # Group actors by namespace
        actors_by_namespace = {}
        for actor in all_actors:
            namespace = getattr(actor, 'namespace', 'unknown')
            if namespace not in actors_by_namespace:
                actors_by_namespace[namespace] = []
            actors_by_namespace[namespace].append(actor)
        
        # Show actors by namespace
        for namespace, actors in actors_by_namespace.items():
            print(f"\n📁 Namespace: {namespace}")
            print(f"   Total actors: {len(actors)}")
            
            # Count by state
            alive_count = sum(1 for a in actors if getattr(a, 'state', 'UNKNOWN') == 'ALIVE')
            dead_count = sum(1 for a in actors if getattr(a, 'state', 'UNKNOWN') == 'DEAD')
            print(f"   Alive: {alive_count}, Dead: {dead_count}")
            
            # Show named actors
            named_in_namespace = [a for a in actors if getattr(a, 'name', None)]
            if named_in_namespace:
                print(f"   Named actors ({len(named_in_namespace)}):")
                for actor in named_in_namespace:
                    state = getattr(actor, 'state', 'UNKNOWN')
                    name = getattr(actor, 'name', 'unnamed')
                    class_name = getattr(actor, 'class_name', 'unknown')
                    print(f"     - {name} ({class_name}): {state}")
                    if name and name not in named_actors:
                        named_actors.append(name)
            else:
                print(f"   No named actors")
        
        print(f"\nTotal named actors found: {len(named_actors)}")
        
    except Exception as e:
        print(f"Error listing actors: {e}")
        # Fallback to old method
        try:
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
        except Exception as e2:
            print(f"Fallback method also failed: {e2}")
    
    # 4. Check our organism status via API
    print("\n🧬 Organism Status:")
    print("-" * 30)
    try:
        import requests
        response = requests.get("http://localhost:8002/organism/status", timeout=5)
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
        # Try different dashboard endpoints - use the correct /api/v0/ paths
        endpoints = [
            "http://seedcore-svc-head-svc:8265/api/v0/nodes",
            "http://seedcore-svc-head-svc:8265/api/v0/actors",
            "http://seedcore-svc-head-svc:8265/api/v0/jobs"
        ]
        
        for endpoint in endpoints:
            try:
                response = requests.get(endpoint, timeout=5)
                print(f"✅ {endpoint}: {response.status_code}")
                if response.status_code == 200:
                    try:
                        data = response.json()
                        if 'data' in data and 'result' in data['data']:
                            result = data['data']['result']
                            if isinstance(result, dict) and 'total' in result:
                                print(f"   Total items: {result['total']}")
                            elif isinstance(result, list):
                                print(f"   Total items: {len(result)}")
                            else:
                                print(f"   Data structure: {type(result)}")
                        else:
                            print(f"   Response structure: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
                    except Exception as parse_error:
                        print(f"   Parse error: {parse_error}")
                        print(f"   Response length: {len(response.text)} chars")
                else:
                    print(f"   Error: {response.status_code}")
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
        response = requests.post("http://localhost:8002/organism/execute/cognitive_organ_1", 
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