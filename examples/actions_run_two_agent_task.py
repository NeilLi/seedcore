#!/usr/bin/env python3
"""
Example: Trigger two-agent task simulation.

Replaces the need for calling /actions/run_two_agent_task directly from UI; use CLI.

Usage:
  python examples/actions_run_two_agent_task.py --api http://localhost:8002
"""
import argparse
import os
import requests
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=os.getenv("SEEDCORE_API_BASE", "http://localhost:8002"))
    args = parser.parse_args()

    base = args.api.rstrip("/")
    url = f"{base}/actions/run_two_agent_task"
    print(f"POST {url}")
    r = requests.post(url, json={}, timeout=30)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))


if __name__ == "__main__":
    main()


