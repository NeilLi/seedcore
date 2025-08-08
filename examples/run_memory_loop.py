#!/usr/bin/env python3
"""
Example: Run the comprehensive memory loop (adaptive memory + energy update).

Usage:
  python examples/run_memory_loop.py --api http://localhost:8002
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
    url = f"{base}/run_memory_loop"
    print(f"GET {url}")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))


if __name__ == "__main__":
    main()


