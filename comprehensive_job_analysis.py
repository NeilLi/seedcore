#!/usr/bin/env python3
"""
Comprehensive Ray jobs, tasks, and actors analysis using Ray's Python API.
"""

import ray
import json
import time
import asyncio
from typing import Dict, List, Any

def analyze_ray_jobs_comprehensive():
    """Comprehensive analysis of Ray jobs, tasks, and actors."""
    
    print("🔍 Comprehensive Ray Jobs Analysis")
    print("=" * 60)
    
    # Initialize Ray
    if not ray.is_initialized():
        ray.init(address="ray://ray-head:10001", namespace="seedcore")
    
    # 1. Cluster Overview
    print("\n📊 CLUSTER OVERVIEW:")
    print("-" * 40)
    cluster_resources = ray.cluster_resources()
    available_resources = ray.available_resources()
    
    print(f"Total CPU: {cluster_resources.get('CPU', 0)}")
    print(f"Available CPU: {available_resources.get('CPU', 0)}")
    print(f"Total Memory: {cluster_resources.get('memory', 0) / (1024**3):.2f} GB")
    print(f"Available Memory: {available_resources.get('memory', 0) / (1024**3):.2f} GB")
    print(f"Total Object Store: {cluster_resources.get('object_store_memory', 0) / (1024**3):.2f} GB")
    print(f"Available Object Store: {available_resources.get('object_store_memory', 0) / (1024**3):.2f} GB")
    
    # 2. Nodes Analysis
    print("\n🖥️  NODES ANALYSIS:")
    print("-" * 40)
    nodes = ray.nodes()
    print(f"Total Nodes: {len(nodes)}")
    
    for i, node in enumerate(nodes):
        print(f"\nNode {i+1}:")
        print(f"  - ID: {node['NodeID'][:16]}...")
        print(f"  - Address: {node['NodeManagerAddress']}")
        print(f"  - Status: {'🟢 Alive' if node['Alive'] else '🔴 Dead'}")
        print(f"  - CPU: {node['Resources'].get('CPU', 0)}")
        print(f"  - Memory: {node['Resources'].get('memory', 0) / (1024**3):.2f} GB")
        print(f"  - Object Store: {node['Resources'].get('object_store_memory', 0) / (1024**3):.2f} GB")
    
    # 3. Named Actors Analysis
    print("\n🎭 NAMED ACTORS ANALYSIS:")
    print("-" * 40)
    
    # Check our COA organs
    organ_actors = ["cognitive_organ_1", "actuator_organ_1", "utility_organ_1"]
    organ_status = {}
    
    for organ_name in organ_actors:
        try:
            actor = ray.get_actor(organ_name)
            organ_status[organ_name] = "✅ Active"
            print(f"✅ {organ_name}: Active")
        except ValueError:
            organ_status[organ_name] = "❌ Not Found"
            print(f"❌ {organ_name}: Not Found")
        except Exception as e:
            organ_status[organ_name] = f"⚠️ Error: {e}"
            print(f"⚠️ {organ_name}: Error - {e}")
    
    # Check other system actors
    system_actors = ["MissTracker", "SharedCache", "MwStore"]
    system_status = {}
    
    for actor_name in system_actors:
        try:
            actor = ray.get_actor(actor_name)
            system_status[actor_name] = "✅ Active"
            print(f"✅ {actor_name}: Active")
        except ValueError:
            system_status[actor_name] = "❌ Not Found"
            print(f"❌ {actor_name}: Not Found")
        except Exception as e:
            system_status[actor_name] = f"⚠️ Error: {e}"
            print(f"⚠️ {actor_name}: Error - {e}")
    
    # 4. Test Organ Functionality
    print("\n🧬 ORGAN FUNCTIONALITY TEST:")
    print("-" * 40)
    
    for organ_name in organ_actors:
        if organ_status[organ_name] == "✅ Active":
            try:
                actor = ray.get_actor(organ_name)
                # Try to get organ status
                status_future = actor.get_status.remote()
                status = ray.get(status_future)
                print(f"✅ {organ_name}:")
                print(f"   - Type: {status.get('organ_type', 'Unknown')}")
                print(f"   - Agent Count: {status.get('agent_count', 0)}")
                print(f"   - Agent IDs: {status.get('agent_ids', [])}")
            except Exception as e:
                print(f"❌ {organ_name}: Error getting status - {e}")
    
    # 5. API Endpoints Test
    print("\n🌐 API ENDPOINTS TEST:")
    print("-" * 40)
    
    try:
        import requests
        
        # Test organism endpoints
        endpoints = [
            ("Organism Status", "http://localhost:8000/organism/status"),
            ("Organism Summary", "http://localhost:8000/organism/summary"),
            ("Ray Status", "http://localhost:8000/ray/status")
        ]
        
        for name, url in endpoints:
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    print(f"✅ {name}: HTTP {response.status_code}")
                else:
                    print(f"❌ {name}: HTTP {response.status_code}")
            except Exception as e:
                print(f"❌ {name}: Error - {e}")
                
    except Exception as e:
        print(f"❌ API testing error: {e}")
    
    # 6. Task Execution Test
    print("\n⚡ TASK EXECUTION TEST:")
    print("-" * 40)
    
    try:
        import requests
        
        # Test task execution on each organ
        for organ_name in organ_actors:
            if organ_status[organ_name] == "✅ Active":
                try:
                    task_data = {
                        "task_data": {
                            "type": "analysis_test",
                            "description": f"Testing {organ_name} functionality",
                            "parameters": {"test": True, "organ": organ_name}
                        }
                    }
                    
                    response = requests.post(
                        f"http://localhost:8000/organism/execute/{organ_name}",
                        json=task_data,
                        timeout=10
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("success"):
                            result = data.get("result", {})
                            print(f"✅ {organ_name}: Task executed successfully")
                            print(f"   - Agent: {result.get('agent_id', 'Unknown')}")
                            print(f"   - Success: {result.get('success', 'Unknown')}")
                            print(f"   - Quality: {result.get('quality', 'Unknown'):.3f}")
                        else:
                            print(f"❌ {organ_name}: Task failed - {data.get('error')}")
                    else:
                        print(f"❌ {organ_name}: HTTP error {response.status_code}")
                        
                except Exception as e:
                    print(f"❌ {organ_name}: Error - {e}")
                    
    except Exception as e:
        print(f"❌ Task execution testing error: {e}")
    
    # 7. Performance Analysis
    print("\n📈 PERFORMANCE ANALYSIS:")
    print("-" * 40)
    
    # Calculate resource utilization
    total_cpu = cluster_resources.get('CPU', 0)
    available_cpu = available_resources.get('CPU', 0)
    used_cpu = total_cpu - available_cpu
    cpu_utilization = (used_cpu / total_cpu * 100) if total_cpu > 0 else 0
    
    total_memory = cluster_resources.get('memory', 0)
    available_memory = available_resources.get('memory', 0)
    used_memory = total_memory - available_memory
    memory_utilization = (used_memory / total_memory * 100) if total_memory > 0 else 0
    
    print(f"CPU Utilization: {cpu_utilization:.1f}% ({used_cpu}/{total_cpu})")
    print(f"Memory Utilization: {memory_utilization:.1f}% ({used_memory/(1024**3):.2f}GB/{total_memory/(1024**3):.2f}GB)")
    
    # 8. Summary and Recommendations
    print("\n📋 SUMMARY AND RECOMMENDATIONS:")
    print("-" * 40)
    
    # Count active components
    active_organs = sum(1 for status in organ_status.values() if status == "✅ Active")
    active_system_actors = sum(1 for status in system_status.values() if status == "✅ Active")
    
    print(f"✅ Active Organs: {active_organs}/3")
    print(f"✅ Active System Actors: {active_system_actors}/3")
    print(f"✅ Cluster Nodes: {len([n for n in nodes if n['Alive']])}/{len(nodes)}")
    
    # Recommendations
    print("\n💡 RECOMMENDATIONS:")
    if active_organs == 3:
        print("✅ All COA organs are active and functioning")
    else:
        print("⚠️  Some COA organs are not active - check logs")
    
    if active_system_actors == 3:
        print("✅ All system actors are active")
    else:
        print("⚠️  Some system actors are missing - may be normal for this setup")
    
    if cpu_utilization < 80:
        print("✅ CPU utilization is healthy")
    else:
        print("⚠️  High CPU utilization detected")
    
    if memory_utilization < 80:
        print("✅ Memory utilization is healthy")
    else:
        print("⚠️  High memory utilization detected")
    
    print("\n" + "=" * 60)
    print("🎯 Comprehensive Ray Jobs Analysis Complete")
    print("=" * 60)

if __name__ == "__main__":
    analyze_ray_jobs_comprehensive() 