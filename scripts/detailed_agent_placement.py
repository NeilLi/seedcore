#!/usr/bin/env python3
"""
Detailed Agent Placement Analysis
Shows exactly which worker nodes agents are running on.
"""

import ray
import requests
from datetime import datetime
import os

def analyze_detailed_placement():
    """Analyze detailed agent placement across workers."""
    
    print("🔍 Detailed Agent Placement Analysis")
    print("=" * 60)
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
    
    # 1. Get cluster nodes
    nodes = ray.nodes()
    
    print("🖥️  CLUSTER NODES:")
    print("-" * 40)
    
    node_map = {}
    for i, node in enumerate(nodes):
        node_id = node['NodeID']
        is_head = 'node:__internal_head__' in node['Resources']
        node_type = "Head" if is_head else "Worker"
        
        node_map[node_id] = {
            'index': i + 1,
            'type': node_type,
            'address': node['NodeManagerAddress'],
            'alive': node['Alive']
        }
        
        status = "🟢 Alive" if node['Alive'] else "🔴 Dead"
        print(f"Node {i+1} ({node_type}): {status}")
        print(f"  - ID: {node_id[:16]}...")
        print(f"  - Address: {node['NodeManagerAddress']}")
        print()
    
    # 2. Analyze COA organs and their agents
    print("🧬 COA ORGAN & AGENT ANALYSIS:")
    print("-" * 40)
    
    organ_actors = ["cognitive_organ_1", "actuator_organ_1", "utility_organ_1"]
    
    for organ_name in organ_actors:
        try:
            actor = ray.get_actor(organ_name)
            print(f"✅ {organ_name}:")
            
            # Get organ status
            try:
                status_future = actor.get_status.remote()
                status = ray.get(status_future)
                
                organ_type = status.get('organ_type', 'Unknown')
                agent_count = status.get('agent_count', 0)
                agent_ids = status.get('agent_ids', [])
                
                print(f"  - Type: {organ_type}")
                print(f"  - Agent Count: {agent_count}")
                
                if agent_ids:
                    print(f"  - Agent IDs: {agent_ids}")
                    
                    # Try to get agent details
                    for agent_id in agent_ids:
                        try:
                            # Try to get agent heartbeat or status
                            agent_future = actor.get_agent_heartbeat.remote(agent_id)
                            agent_data = ray.get(agent_future)
                            print(f"    * {agent_id}: Active")
                            
                            # Try to get agent location info
                            if hasattr(actor, 'get_agent_location'):
                                location_future = actor.get_agent_location.remote(agent_id)
                                location = ray.get(location_future)
                                print(f"      Location: {location}")
                            
                        except Exception as e:
                            print(f"    * {agent_id}: Error getting details - {str(e)[:50]}")
                
            except Exception as e:
                print(f"  - Status Error: {str(e)[:50]}")
            
            print()
            
        except ValueError:
            print(f"❌ {organ_name}: Not Found")
            print()
        except Exception as e:
            print(f"❌ {organ_name}: Error - {str(e)[:50]}")
            print()
    
    # 3. Check Ray Dashboard for actor placement
    print("📊 RAY DASHBOARD ACTOR PLACEMENT:")
    print("-" * 40)
    
    try:
        # Get actors from Ray dashboard API
        response = requests.get("http://localhost:8265/api/actors", timeout=5)
        if response.status_code == 200:
            data = response.json()
            actors = data.get('data', [])
            
            print(f"Total Actors in Dashboard: {len(actors)}")
            print()
            
            # Group actors by node
            actors_by_node = {}
            
            for actor in actors:
                node_id = actor.get('node_id', 'Unknown')
                actor_id = actor.get('actor_id', 'Unknown')
                state = actor.get('state', 'Unknown')
                name = actor.get('name', 'Unnamed')
                
                if node_id not in actors_by_node:
                    actors_by_node[node_id] = []
                
                actors_by_node[node_id].append({
                    'actor_id': actor_id,
                    'name': name,
                    'state': state
                })
            
            # Display actors by node
            for node_id, node_actors in actors_by_node.items():
                node_info = node_map.get(node_id, {})
                node_type = node_info.get('type', 'Unknown')
                node_index = node_info.get('index', '?')
                
                print(f"Node {node_index} ({node_type}): {len(node_actors)} actors")
                print(f"  - Node ID: {node_id[:16]}...")
                
                for actor in node_actors:
                    actor_name = actor['name'] if actor['name'] != 'Unnamed' else actor['actor_id'][:16]
                    print(f"    * {actor_name} ({actor['state']})")
                
                print()
        else:
            print(f"❌ Dashboard API failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Dashboard Error: {e}")
    
    # 4. Check Tier 0 agents if available
    print("🤖 TIER 0 AGENT ANALYSIS:")
    print("-" * 40)
    
    try:
        response = requests.get("http://localhost:8000/tier0/summary", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                tier0_data = data.get("data", {})
                agents = tier0_data.get("agents", [])
                
                print(f"Tier 0 Agents: {len(agents)}")
                
                for agent in agents:
                    agent_id = agent.get('agent_id', 'Unknown')
                    success_rate = agent.get('success_rate', 0)
                    quality_score = agent.get('quality_score', 0)
                    
                    print(f"  - {agent_id}:")
                    print(f"    Success Rate: {success_rate:.3f}")
                    print(f"    Quality Score: {quality_score:.3f}")
            else:
                print(f"❌ Tier 0 API error: {data.get('error')}")
        else:
            print(f"❌ Tier 0 API failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Tier 0 Error: {e}")
    
    print()
    print("✅ Detailed placement analysis complete!")

if __name__ == "__main__":
    analyze_detailed_placement() 