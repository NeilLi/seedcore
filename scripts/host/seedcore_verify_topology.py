#!/usr/bin/env python3
# Copyright 2024 SeedCore Contributors
# Licensed under the Apache License, Version 2.0

import argparse, sys, json
from urllib.request import urlopen, Request

EXPECTED_APPS = {
    "ml_service": {"route_prefix": "/ml"},
    "cognitive":  {"route_prefix": "/cognitive"},
    "coordinator":{"route_prefix": "/pipeline"},
    "state":      {"route_prefix": "/state"},
    "energy":     {"route_prefix": "/energy"},
    "organism":   {"route_prefix": "/organism"},
}

def fetch_json(url: str):
    req = Request(url, headers={"User-Agent": "seedcore-verify/1.0"})
    with urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())

def fail(msg: str):
    print(f"❌ {msg}")
    sys.exit(1)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ray-dash", default="http://127.0.0.1:8265", help="Ray dashboard base URL")
    args = ap.parse_args()

    url = f"{args.ray_dash}/api/serve/applications/"
    try:
        data = fetch_json(url)
    except Exception as e:
        fail(f"Could not reach Ray Serve API at {url}: {e}")

    apps = data.get("applications") or {}
    missing = [name for name in EXPECTED_APPS if name not in apps]
    if missing:
        fail(f"Missing expected applications: {missing}")

    # Validate health + routes
    for name, expect in EXPECTED_APPS.items():
        app = apps[name]
        status = app.get("status")
        route = app.get("route_prefix")
        if status != "RUNNING":
            fail(f"App '{name}' not RUNNING (status={status})")
        if route != expect["route_prefix"]:
            fail(f"App '{name}' route_prefix mismatch: got {route}, expected {expect['route_prefix']}")
        # Validate deployments healthy
        deployments = (app.get("deployments") or {}).values()
        for d in deployments:
            dstatus = d.get("status")
            if dstatus != "HEALTHY":
                fail(f"Deployment {name}::{d.get('name')} is not HEALTHY (status={dstatus})")

    print("✅ Ray Serve topology healthy:")
    for name in EXPECTED_APPS:
        app = apps[name]
        reps = sum(len(d.get("replicas") or []) for d in (app["deployments"] or {}).values())
        print(f"   • {name:12s} — route={app['route_prefix']}, replicas={reps}, status={app['status']}")

if __name__ == "__main__":
    main()

