#!/usr/bin/env python3
"""
Example: Consolidate a small batch of Mw items into Holon Fabric (Mlt) once.

This script:
- Fetches a limited Mw snapshot via the dev-only endpoint /admin/mw_snapshot
- Connects to Ray and submits consolidation_worker with provided DSNs

Usage:
  python examples/holon_consolidate_once.py --api http://localhost:8002 --limit 10 --tau 0.3 --batch 10
"""
import argparse
import os
import json
import time
import base64
import requests
import ray


def decode_blob(enc: dict):
    t = enc.get("type")
    if t == "bytes":
        return base64.b64decode(enc.get("b64", ""))
    if t == "array":
        return enc.get("data", [])
    if t == "str":
        return enc.get("data", "")
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=os.getenv("SEEDCORE_API_BASE", "http://localhost:8002"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--tau", type=float, default=0.3)
    parser.add_argument("--batch", type=int, default=10)
    parser.add_argument("--ray", default=os.getenv("RAY_ADDRESS", "ray://ray-head:10001"))
    parser.add_argument("--pg_dsn", default=os.getenv("PG_DSN"))
    parser.add_argument("--neo_uri", default=os.getenv("NEO4J_URI") or os.getenv("NEO4J_BOLT_URL", "bolt://neo4j:7687"))
    parser.add_argument("--neo_user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo_pass", default=os.getenv("NEO4J_PASSWORD", "password"))
    args = parser.parse_args()

    api = args.api.rstrip("/")

    # 1) Fetch Mw snapshot
    url = f"{api}/admin/mw_snapshot?limit={args.limit}"
    print(f"Fetching Mw snapshot from {url} ...")
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    if "mw" not in data:
        raise SystemExit(f"Unexpected response: {data}")

    # Rehydrate to a simple dict[str, any]
    mw = {}
    for item in data.get("mw", []):
        key = item.get("key")
        enc = item.get("blob", {})
        blob = decode_blob(enc)
        mw[key] = {"blob": blob, "ts": item.get("ts", time.time())}

    print(f"Snapshot size: {len(mw)}")

    # 2) Connect to Ray
    print(f"Connecting to Ray at {args.ray} ...")
    ray.init(address=args.ray, ignore_reinit_error=True)

    # 3) Submit consolidation worker
    from src.seedcore.memory.consolidation_task import consolidation_worker
    print("Submitting consolidation job ...")
    t0 = time.time()
    n = ray.get(consolidation_worker.remote(
        args.pg_dsn or os.getenv("PG_DSN"),
        args.neo_uri,
        (args.neo_user, args.neo_pass),
        mw, args.tau, args.batch
    ))
    dt = time.time() - t0
    print(f"Consolidated {n} items in {dt:.2f}s")


if __name__ == "__main__":
    main()


