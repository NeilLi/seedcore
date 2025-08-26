#!/usr/bin/env python3
"""
Test script to verify Ray Serve endpoints behind the /ml base path.
"""

import os
import json
import urllib.request
import urllib.error

# Ensure our package is importable if needed
import sys
sys.path.insert(0, "/app")

from src.seedcore.utils.ray_utils import get_serve_urls  # uses RAY_ADDRESS/SERVE_GATEWAY

def test_endpoint(url, method="GET", data=None, headers=None, timeout=10):
    headers = headers or {}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") if resp.length is None or resp.length > 0 else ""
            return {
                "status": resp.status,
                "success": True,
                "data": json.loads(raw) if raw else None,
            }
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8") if e.fp else ""
        return {"status": e.code, "success": False, "error": f"HTTP {e.code}: {e.reason}", "body": err_body}
    except Exception as e:
        return {"status": None, "success": False, "error": str(e)}

def main():
    print("🧪 Testing Ray Serve Health Endpoints")
    print("=" * 50)

    urls = get_serve_urls()  # derives from RAY_ADDRESS/SERVE_GATEWAY
    print(f"🧪 get_serve_urls: {urls}")
    root = urls["ml_root"].rstrip("/")
    health = urls["ml_health"]
    salience = urls["ml_salience"]

    endpoints = [
        ("Root endpoint (GET)", root + "/", "GET", None),
        ("Health endpoint (GET)", health, "GET", None),
        # IMPORTANT: salience expects a list of dict features, not raw numbers
        ("Salience endpoint (POST)", salience, "POST",
         {"features": [{"task_risk": 0.8, "failure_severity": 0.6}]}),
        ("Salience endpoint (GET - should fail)", salience, "GET", None),
    ]

    for name, url, method, payload in endpoints:
        print(f"\n🔍 Testing {name}...")
        result = test_endpoint(url, method=method, data=payload)
        if result["success"]:
            print(f"✅ {name}: HTTP {result['status']}")
            if result.get("data") is not None:
                print(json.dumps(result["data"], indent=2))
        else:
            print(f"❌ {name}: {result['error']}")
            if result.get("body"):
                print(f"   Body: {result['body'][:300]}")

    print("\n" + "=" * 50)
    print("🎯 Expected Results:")
    print("✅ Root endpoint should return 200 with service info")
    print("✅ Health endpoint should return 200 with health status")
    print("✅ Salience POST should return 200 with scores (or your model’s payload)")
    print("❌ Salience GET should return 405 Method Not Allowed")
    print("=" * 50)

if __name__ == "__main__":
    main()
