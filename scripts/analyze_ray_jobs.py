#!/usr/bin/env python3
"""
Comprehensive Ray cluster and jobs analysis script.

Runs inside the seedcore-api pod or host (with access to Ray head service).
"""

import ray
import os
import requests


def connect_to_ray():
    """Ensure connection to Ray cluster (only once)."""
    ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
    ray_host = os.getenv("RAY_HOST", "seedcore-svc-head-svc")
    ray_port = os.getenv("RAY_PORT", "10001")
    ray_address = f"ray://{ray_host}:{ray_port}"

    print(f"🔗 Connecting to Ray at: {ray_address} (ns={ray_namespace})")

    if not ray.is_initialized():
        from seedcore.utils.ray_utils import ensure_ray_initialized
        if not ensure_ray_initialized(ray_address=ray_address, ray_namespace=ray_namespace):
            print("❌ Failed to connect to Ray cluster")
            return False
    else:
        print("ℹ️ Ray already initialized")

    return True


def analyze_cluster_resources():
    """Show cluster-wide resources."""
    print("\n📊 Cluster Resources")
    print("-" * 40)
    print(f"Total: {ray.cluster_resources()}")
    print(f"Available: {ray.available_resources()}")


def analyze_nodes():
    """List cluster nodes using dashboard API."""
    print("\n🖥️  Cluster Nodes")
    print("-" * 40)
    try:
        r = requests.get("http://seedcore-svc-head-svc:8265/api/v0/nodes", timeout=5)
        if r.status_code == 200:
            data = r.json()
            
            # Handle the actual API response structure
            if isinstance(data, dict) and data.get("result") in [True, "success"]:
                result_block = data.get("data", {}).get("result", {})
                nodes_data = result_block.get("result", [])
                print(f"Total Nodes: {len(nodes_data)}")

                for n in nodes_data:
                    if isinstance(n, dict):
                        node_id = n.get("node_id", n.get("nodeId", "unknown"))
                        node_name = n.get("node_name", n.get("nodeName", "unknown"))
                        state = n.get("state", "unknown")
                        print(f"  - {str(node_id)[:8]} @ {node_name} :: {state}")
                    else:
                        print(f"  - {n}")
            else:
                print(f"❌ API error: {data.get('msg', 'Unknown error')}")
        else:
            print(f"❌ HTTP {r.status_code}")
    except Exception as e:
        print(f"❌ Error listing nodes: {e}")


def analyze_actors():
    """List actors using dashboard API."""
    print("\n🎭 Actors by Namespace")
    print("-" * 40)
    try:
        r = requests.get("http://seedcore-svc-head-svc:8265/api/v0/actors", timeout=5)
        if r.status_code == 200:
            data = r.json()
            
            # Handle the actual API response structure
            if isinstance(data, dict) and data.get("result") in [True, "success"]:
                result_block = data.get("data", {}).get("result", {})
                actors_data = result_block.get("result", [])
                
                if isinstance(actors_data, list) and len(actors_data) > 0:
                    ns_map = {}
                    for a in actors_data:
                        if isinstance(a, dict):
                            ns = a.get("namespace", "unknown")
                            ns_map.setdefault(ns, []).append(a)

                    for ns, items in ns_map.items():
                        print(f"\n📁 Namespace: {ns} (Total: {len(items)})")
                        alive = [x for x in items if isinstance(x, dict) and x.get("state") == "ALIVE"]
                        dead = [x for x in items if isinstance(x, dict) and x.get("state") == "DEAD"]
                        print(f"   Alive: {len(alive)}, Dead: {len(dead)}")
                        named = [x for x in items if isinstance(x, dict) and x.get("name")]
                        for x in named:
                            name = x.get('name', 'unnamed')
                            class_name = x.get('className', x.get('class_name', 'unknown'))
                            state = x.get('state', 'unknown')
                            print(f"   • {name} ({class_name}) :: {state}")
                else:
                    print(f"❌ No actors data found or empty list")
            else:
                print(f"❌ API error: {data.get('msg', 'Unknown error')}")
        else:
            print(f"❌ HTTP {r.status_code}")
    except Exception as e:
        print(f"❌ Error listing actors: {e}")


def analyze_jobs():
    """List jobs using dashboard API."""
    print("\n📦 Ray Jobs")
    print("-" * 40)
    try:
        r = requests.get("http://seedcore-svc-head-svc:8265/api/v0/jobs", timeout=5)
        if r.status_code == 200:
            data = r.json()
            
            # Handle the actual API response structure
            if isinstance(data, dict) and data.get("result") in [True, "success"]:
                result_block = data.get("data", {}).get("result", {})
                jobs_data = result_block.get("result", [])
                
                if isinstance(jobs_data, list) and len(jobs_data) > 0:
                    print(f"Total jobs: {len(jobs_data)}")
                    
                    # Show first 5 jobs safely
                    for i, j in enumerate(jobs_data):
                        if i >= 5:  # Limit to first 5
                            break
                            
                        if isinstance(j, dict):
                            job_id = j.get('jobId', j.get('job_id', 'unknown'))
                            status = j.get('status', 'unknown')
                            # Try different possible namespace fields
                            namespace = j.get('namespace', j.get('entrypointNumArgs', 'unknown'))
                            print(f"  - {job_id}: {status} (ns={namespace})")
                        else:
                            print(f" - {j}")
                else:
                    print(f"❌ No jobs data found or empty list")
            else:
                print(f"❌ API error: {data.get('msg', 'Unknown error')}")
        else:
            print(f"❌ HTTP {r.status_code}")
    except Exception as e:
        print(f"❌ Error listing jobs: {e}")


def check_organism_status():
    """Check organism API for organs + agents."""
    print("\n🧬 Organism Status")
    print("-" * 40)
    try:
        r = requests.get("http://localhost:8002/organism/status", timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data.get("success"):
                organs = data.get("data", [])
                print(f"✅ Found {len(organs)} organs")
                for o in organs:
                    print(f"   - {o.get('organ_id')} :: {o.get('agent_count')} agents")
            else:
                print(f"❌ API error: {data.get('error')}")
        else:
            print(f"❌ HTTP {r.status_code}")
    except Exception as e:
        print(f"❌ Error: {e}")


def check_dashboard():
    """Check Ray dashboard API endpoints."""
    print("\n🌐 Ray Dashboard API")
    print("-" * 40)
    endpoints = [
        "http://seedcore-svc-head-svc:8265/api/v0/nodes",
        "http://seedcore-svc-head-svc:8265/api/v0/actors",
        "http://seedcore-svc-head-svc:8265/api/v0/jobs",
    ]
    for ep in endpoints:
        try:
            r = requests.get(ep, timeout=5)
            print(f"✅ {ep}: {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                print(f"   Keys: {list(data.keys())}")
        except Exception as e:
            print(f"❌ {ep}: {e}")


def test_task_execution():
    """Run a simple task through organism API."""
    print("\n⚡ Task Execution Test")
    print("-" * 40)
    try:
        task = {
            "task_data": {
                "type": "test_task",
                "description": "Job analysis test",
                "parameters": {"test": True},
            }
        }
        r = requests.post(
            "http://localhost:8002/organism/execute/cognitive_organ_1",
            json=task,
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("success"):
                result = data.get("result", {})
                print("✅ Task executed")
                print(f"   Agent: {result.get('agent_id')}")
                print(f"   Success: {result.get('success')}")
                print(f"   Quality: {result.get('quality')}")
            else:
                print(f"❌ Task failed: {data.get('error')}")
        else:
            print(f"❌ HTTP {r.status_code}")
    except Exception as e:
        print(f"❌ Error: {e}")


def main():
    print("🔍 Ray Cluster and Jobs Analysis")
    print("=" * 60)

    if not connect_to_ray():
        return False

    analyze_cluster_resources()
    analyze_nodes()
    analyze_actors()
    analyze_jobs()
    check_organism_status()
    check_dashboard()
    test_task_execution()

    print("\n🎯 Analysis Complete")
    print("=" * 60)
    return True


if __name__ == "__main__":
    ok = main()
    exit(0 if ok else 1)
