#!/usr/bin/env python3
# Copyright 2024 SeedCore Contributors
# Licensed under the Apache License, Version 2.0

import argparse, sys, json
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

ROUTES = {
    "ml":         {"path": "/ml/docs",        "optional": False},
    "cognitive":  {"path": "/cognitive/docs", "optional": False},
    "pipeline":   {"path": "/pipeline/docs",  "optional": False},
    "organism":   {"path": "/organism/docs",  "optional": False},
    # state/energy may not expose docs; try a ping/health then fallback to / if needed
    "state":      {"path": "/state/health",   "optional": True, "fallbacks": ["/state", "/state/metrics"]},
    "energy":     {"path": "/energy/health",  "optional": True, "fallbacks": ["/energy", "/energy/metrics"]},
}

def try_get(url: str, timeout=3.0):
    req = Request(url, headers={"User-Agent": "seedcore-smoke/1.0"})
    try:
        with urlopen(req, timeout=timeout) as r:
            code = r.getcode()
            body = r.read(200).decode(errors="ignore")
            return code, body
    except HTTPError as e:
        return e.code, str(e)
    except URLError as e:
        return None, str(e)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", default="http://127.0.0.1:8000")
    args = ap.parse_args()

    failures = []
    for name, cfg in ROUTES.items():
        url = args.gateway + cfg["path"]
        code, _ = try_get(url)
        if code and 200 <= code < 500:
            print(f"✅ {name:10s} {url} -> HTTP {code}")
            continue
        # fallbacks
        ok = False
        for fb in cfg.get("fallbacks", []):
            code, _ = try_get(args.gateway + fb)
            if code and 200 <= code < 500:
                print(f"✅ {name:10s} {args.gateway+fb} -> HTTP {code}")
                ok = True
                break
        if not ok:
            status = "optional" if cfg.get("optional", False) else "required"
            print(f"{'⚠️' if status=='optional' else '❌'} {name:10s} {url} (no healthy response)")
            if status != "optional":
                failures.append(name)

    if failures:
        print(f"❌ Required routes failing: {failures}")
        sys.exit(3)
    print("✅ HTTP smoke checks OK.")

if __name__ == "__main__":
    main()

