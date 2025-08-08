#!/usr/bin/env python3
"""
Example: Reset energy ledger, pair statistics, and memory system.

Usage:
  python examples/actions_reset.py --api http://localhost:8002
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
    url = f"{base}/actions/reset"
    print(f"POST {url}")
    r = requests.post(url, json={}, timeout=30)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))


if __name__ == "__main__":
    main()


