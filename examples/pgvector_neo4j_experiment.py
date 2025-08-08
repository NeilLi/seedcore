#!/usr/bin/env python3
"""
PGVector + Neo4j Memory Loop Experiment (example script)

Replaces the old /run_pgvector_neo4j_experiment endpoint.
Runs the comprehensive memory loop to exercise PGVector (Mlt) and Neo4j paths,
and prints a compact summary of results.

Usage:
  python examples/pgvector_neo4j_experiment.py --api http://localhost:8002
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

    # Hit the combined memory loop that exercises PGVector/Neo4j integration
    url = f"{base}/run_memory_loop"
    print(f"Running memory loop via {url} ...")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()

    # Pretty-print a compact summary
    summary = {
        "message": data.get("message"),
        "compression_knob": data.get("compression_knob"),
        "average_mem_util": data.get("average_mem_util"),
        "memory_energy": data.get("memory_energy"),
        "cost_vq": data.get("cost_vq_breakdown", {}).get("cost_vq"),
        "memory_system_stats": data.get("memory_system_stats", {}),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()


