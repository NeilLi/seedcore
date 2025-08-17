#!/usr/bin/env python3
"""
Agent Distribution Analysis Script
"""

import ray
import requests
import os
from datetime import datetime

def analyze_agent_distribution():
    """Analyze how agents are distributed across Ray workers."""
    
    print("🔍 Agent Distribution Analysis")
    print("=" * 50)
    print(f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
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
    
    # 1. Cluster Overview
    print("📊 CLUSTER OVERVIEW:")
    print("-" * 30)
    
    cluster_resources = ray.cluster_resources()
    available_resources = ray.available_resources()
    nodes = ray.nodes()
    
    print(f"Total Nodes: {len(nodes)}")
    print(f"Total CPU: {cluster_resources.get('CPU', 0)}")
    print(f"Used CPU: {cluster_resources.get('CPU', 0) - available_resources.get('CPU', 0)}")
    print()
    
    # 2. Node Analysis
    print("🖥️  NODE ANALYSIS:")
    print("-" * 30)
    
    worker_count = 0
    head_count = 0
    
    for i, node in enumerate(nodes):
        is_head = 'node:__internal_head__' in node['Resources']
        status = "🟢 Alive" if node['Alive'] else "🔴 Dead"
        node_type = "Head" if is_head else "Worker"
        
        if is_head:
            head_count += 1
        else:
            worker_count += 1
            
        print(f"Node {i+1} ({node_type}): {status}")
        print(f"  - Address: {node['NodeManagerAddress']}")
        print(f"  - CPU: {node['Resources'].get('CPU', 0)}")
        print()
    
    # 3. COA Organ Analysis
    print("🧬 COA ORGAN ANALYSIS:")
    print("-" * 30)
    
    organ_actors = ["cognitive_organ_1", "actuator_organ_1", "utility_organ_1"]
    total_agents = 0
    
    for organ_name in organ_actors:
        try:
            actor = ray.get_actor(organ_name)
            print(f"✅ {organ_name}: Active")
            
            # Try to get organ status
            try:
                status_future = actor.get_status.remote()
                status = ray.get(status_future)
                agent_count = status.get('agent_count', 0)
                agent_ids = status.get('agent_ids', [])
                organ_type = status.get('organ_type', 'Unknown')
                
                print(f"  - Type: {organ_type}")
                print(f"  - Agents: {agent_count}")
                if agent_ids:
                    print(f"  - Agent IDs: {agent_ids}")
                
                total_agents += agent_count
                
            except Exception as e:
                print(f"  - Status Error: {str(e)[:50]}")
                
        except ValueError:
            print(f"❌ {organ_name}: Not Found")
        except Exception as e:
            print(f"❌ {organ_name}: Error - {str(e)[:50]}")
    
    print(f"\nTotal Agents: {total_agents}")
    print()
    
    # 4. API Analysis
    print("🌐 API ANALYSIS:")
    print("-" * 30)
    
    try:
        # Check organism status
        # Use environment variable for Ray Serve address
        base_url = os.getenv("RAY_SERVE_ADDRESS", "localhost:8000")
        if not base_url.startswith("http"):
            base_url = f"http://{base_url}"
        response = requests.get(f"{base_url}/organism/status", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                organs = data.get("data", [])
                print(f"✅ Organism API: {len(organs)} organs found")
                
                for organ in organs:
                    organ_id = organ.get('organ_id')
                    agent_count = organ.get('agent_count', 0)
                    print(f"  - {organ_id}: {agent_count} agents")
            else:
                print(f"❌ Organism API error: {data.get('error')}")
        else:
            print(f"❌ Organism API failed: {response.status_code}")
    except Exception as e:
        print(f"❌ API Error: {e}")
    
    print()
    
    # 5. Distribution Summary
    print("📈 DISTRIBUTION SUMMARY:")
    print("-" * 30)
    
    print(f"Head Node: {head_count}")
    print(f"Worker Nodes: {worker_count}")
    print(f"Total Agents: {total_agents}")
    
    if total_agents > 0 and worker_count > 0:
        avg_agents = total_agents / worker_count
        print(f"Average Agents per Worker: {avg_agents:.2f}")
        
        if avg_agents <= 1:
            print("Distribution: Concentrated")
        elif avg_agents <= 3:
            print("Distribution: Balanced")
        else:
            print("Distribution: Distributed")
    
    print("\n✅ Analysis complete!")

if __name__ == "__main__":
    analyze_agent_distribution() 