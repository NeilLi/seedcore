#!/usr/bin/env python3
"""
Verify Tier 0 agent discovery and API endpoints.

This script:
- Connects to Ray (using RAY_ADDRESS/RAY_NAMESPACE)
- Creates a detached, named RayAgent directly (bypassing the manager) to test discovery
- Calls /tier0/agents and /tier0/agents/state and prints results
- Prints Ray-side diagnostics if endpoints return 0 agents

Usage:
  python examples/verify_tier0_agents.py --api http://localhost:8002

Environment:
  RAY_ADDRESS   (default: auto)
  RAY_NAMESPACE (default: seedcore)
  SEEDCORE_API_ADDRESS (optional; overrides --api)
"""

import argparse
import os
import sys
import time
import json

import requests


def ensure_sys_path():
    # Ensure local src/ is importable as 'seedcore'
    repo_src = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
    if repo_src not in sys.path:
        sys.path.insert(0, repo_src)


def connect_ray():
    import ray
    from seedcore.utils.ray_utils import ensure_ray_initialized
    
    ray_address = os.getenv("RAY_ADDRESS", "auto")
    ray_namespace = os.getenv("RAY_NAMESPACE", "seedcore")
    
    if not ray.is_initialized():
        if not ensure_ray_initialized(ray_address=ray_address, ray_namespace=ray_namespace):
            raise RuntimeError("Failed to connect to Ray cluster")
    
    return ray


def create_detached_agent_if_missing(ray, agent_name: str = "discovery_test_agent") -> None:
    """Create a detached, named RayAgent directly to test discovery."""
    from seedcore.agents.ray_actor import RayAgent

    # Try to fetch existing
    try:
        handle = ray.get_actor(agent_name)
        _ = ray.get(handle.get_id.remote())
        print(f"Found existing RayAgent actor: {agent_name}")
        return
    except Exception:
        pass

    print(f"Creating detached RayAgent actor: {agent_name}")
    handle = RayAgent.options(
        name=agent_name,
        lifetime="detached",
        num_cpus=1,
    ).remote(
        agent_id=agent_name,
        initial_role_probs={"E": 0.5, "S": 0.3, "O": 0.2},
    )
    # Sanity check
    test_id = ray.get(handle.get_id.remote())
    assert test_id == agent_name, f"RayAgent get_id mismatch: {test_id} != {agent_name}"
    print(f"Created RayAgent: {agent_name}")


def call_api(api_base: str, path: str):
    url = f"{api_base.rstrip('/')}{path}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def print_summary(title: str, data: dict):
    print(f"\n=== {title} ===")
    print(json.dumps(data, indent=2))


def ray_diagnostics(ray):
    print("\n=== Ray Diagnostics ===")
    try:
        from ray.util.state import list_actors
        actors = list_actors()
        print(f"Actors reported by Ray: {len(actors)}")
        ra = [a for a in actors if str(getattr(a, 'class_name', getattr(a, 'class_name', ''))) .endswith('RayAgent') or (isinstance(a, dict) and str(a.get('class_name', '')).endswith('RayAgent'))]
        print(f"RayAgent actors: {len(ra)}")
        names = []
        namespaces = []
        for info in actors:
            name = getattr(info, 'name', None) if not isinstance(info, dict) else info.get('name') or info.get('actor_name')
            class_name = getattr(info, 'class_name', None) if not isinstance(info, dict) else info.get('class_name')
            namespace = getattr(info, 'namespace', None) if not isinstance(info, dict) else info.get('namespace')
            if name and class_name and str(class_name).endswith('RayAgent'):
                names.append(name)
                namespaces.append(namespace)
        print(f"RayAgent names: {names}")
        print(f"RayAgent namespaces: {namespaces}")
    except Exception as e:
        print(f"Ray diagnostics failed: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=os.getenv("SEEDCORE_API_ADDRESS", "http://localhost:8002"))
    parser.add_argument("--skip-create", action="store_true", help="Skip creating a detached RayAgent for discovery test")
    args = parser.parse_args()

    ensure_sys_path()
    ray = connect_ray()

    if not args.skip_create:
        create_detached_agent_if_missing(ray)
        # Give the API a moment to discover
        time.sleep(2)

    # Call endpoints
    try:
        agents_list = call_api(args.api, "/tier0/agents")
        print_summary("GET /tier0/agents", agents_list)
    except Exception as e:
        print(f"Error calling /tier0/agents: {e}")

    try:
        agents_state = call_api(args.api, "/tier0/agents/state")
        print_summary("GET /tier0/agents/state", agents_state)
    except Exception as e:
        print(f"Error calling /tier0/agents/state: {e}")

    # If zero, print Ray diagnostics
    try:
        count_a = (agents_list or {}).get("count", 0)
        total_state = len((agents_state or {}).get("agents", []))
        if (count_a == 0) and (total_state == 0):
            ray_diagnostics(ray)
    except Exception:
        pass


if __name__ == "__main__":
    main()


