#!/usr/bin/env python3
"""
Example: Run the slow loop (role evolution) and show role performance metrics.

Usage:
  python examples/run_slow_loop.py --api http://localhost:8002
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
    url = f"{base}/actions/run_slow_loop"
    print(f"POST {url}")
    r = requests.post(url, json={}, timeout=60)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))


if __name__ == "__main__":
    main()


