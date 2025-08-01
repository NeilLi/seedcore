#!/usr/bin/env python3
"""
Test script to verify the health endpoint fix for Ray Serve.
This script tests both the root and health endpoints to ensure they respond correctly.
"""

import urllib.request
import urllib.error
import json
import time

def test_endpoint(url, method="GET", data=None):
    """Test an endpoint and return the result."""
    try:
        if data:
            # For POST requests
            req = urllib.request.Request(
                url, 
                data=json.dumps(data).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
        else:
            # For GET requests
            req = urllib.request.Request(url)
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            response_data = resp.read().decode('utf-8')
            return {
                "status": resp.status,
                "success": True,
                "data": json.loads(response_data) if response_data else None
            }
    except urllib.error.HTTPError as e:
        return {
            "status": e.code,
            "success": False,
            "error": f"HTTP {e.code}: {e.reason}"
        }
    except Exception as e:
        return {
            "status": None,
            "success": False,
            "error": str(e)
        }

def main():
    """Test the health endpoints."""
    print("🧪 Testing Ray Serve Health Endpoints")
    print("=" * 50)
    
    base_url = "http://localhost:8000"
    endpoints = [
        ("Root endpoint (GET)", f"{base_url}/", "GET"),
        ("Health endpoint (GET)", f"{base_url}/health", "GET"),
        ("Salience endpoint (POST)", f"{base_url}/score/salience", "POST", {"features": [1.0, 2.0, 3.0]}),
        ("Salience endpoint (GET - should fail)", f"{base_url}/score/salience", "GET"),
    ]
    
    for name, url, method, *args in endpoints:
        print(f"\n🔍 Testing {name}...")
        data = args[0] if args else None
        result = test_endpoint(url, method, data)
        
        if result["success"]:
            print(f"✅ {name}: HTTP {result['status']}")
            if result["data"]:
                print(f"   Response: {json.dumps(result['data'], indent=2)}")
        else:
            print(f"❌ {name}: {result['error']}")
    
    print("\n" + "=" * 50)
    print("🎯 Expected Results:")
    print("✅ Root endpoint should return 200 with service info")
    print("✅ Health endpoint should return 200 with health status")
    print("✅ Salience POST should return 200 with scores")
    print("❌ Salience GET should return 405 Method Not Allowed")
    print("=" * 50)

if __name__ == "__main__":
    main() 