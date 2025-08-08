#!/usr/bin/env python3
"""
Example: Run all control loops in sequence (fast, slow, memory) via one call.

Usage:
  python examples/run_all_loops.py --api http://localhost:8002
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
    url = f"{base}/run_all_loops"
    print(f"GET {url}")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))


if __name__ == "__main__":
    main()


