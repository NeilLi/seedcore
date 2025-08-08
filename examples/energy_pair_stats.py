#!/usr/bin/env python3
"""
Example: Fetch pair collaboration statistics from the energy namespace.

Usage:
  python examples/energy_pair_stats.py --api http://localhost:8002
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
    url = f"{base}/energy/pair_stats"
    print(f"GET {url}")
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))


if __name__ == "__main__":
    main()


