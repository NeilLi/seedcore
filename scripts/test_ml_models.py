#!/usr/bin/env python3
"""
Test SeedCore ML Models

This script tests the ML models to ensure they work correctly.
"""

import sys
import os
import requests
import json
import time

def test_salience_scoring():
    """Test the salience scoring endpoint."""
    print("🧪 Testing Salience Scoring...")
    
    test_data = {
        "features": [
            {"type": "system_event", "severity": "high", "frequency": 0.8},
            {"type": "user_interaction", "engagement": 0.6, "duration": 120},
            {"type": "resource_usage", "cpu": 0.9, "memory": 0.7}
        ]
    }
    
    try:
        response = requests.post(
            "http://localhost:8000/SalienceScorer",
            json=test_data,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            scores = result.get("scores", [])
            print(f"✅ Salience scores: {scores}")
            return True
        else:
            print(f"❌ HTTP {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_anomaly_detection():
    """Test the anomaly detection endpoint."""
    print("🧪 Testing Anomaly Detection...")
    
    test_data = {
        "metrics": [
            {"cpu_usage": 0.95, "memory_usage": 0.8, "timestamp": time.time()},
            {"cpu_usage": 0.3, "memory_usage": 0.4, "timestamp": time.time()},
            {"cpu_usage": 0.1, "memory_usage": 0.2, "timestamp": time.time()}
        ]
    }
    
    try:
        response = requests.post(
            "http://localhost:8000/AnomalyDetector",
            json=test_data,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            anomalies = result.get("anomalies", [])
            print(f"✅ Anomalies detected: {anomalies}")
            return True
        else:
            print(f"❌ HTTP {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_scaling_prediction():
    """Test the scaling prediction endpoint."""
    print("🧪 Testing Scaling Prediction...")
    
    test_data = {
        "usage_patterns": {
            "cpu_avg": 0.7,
            "memory_avg": 0.6,
            "request_rate": 100,
            "response_time": 0.2
        }
    }
    
    try:
        response = requests.post(
            "http://localhost:8000/ScalingPredictor",
            json=test_data,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            predictions = result.get("predictions", {})
            print(f"✅ Scaling predictions: {predictions}")
            return True
        else:
            print(f"❌ HTTP {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    """Main test function."""
    print("🎯 SeedCore ML Models Test")
    print("=" * 40)
    
    # Test all endpoints
    tests = [
        test_salience_scoring,
        test_anomaly_detection,
        test_scaling_prediction
    ]
    
    results = []
    for test in tests:
        result = test()
        results.append(result)
        print()
    
    # Summary
    passed = sum(results)
    total = len(results)
    
    print("📊 Test Summary:")
    print(f"   Passed: {passed}/{total}")
    print(f"   Failed: {total - passed}/{total}")
    
    if passed == total:
        print("🎉 All tests passed!")
        return True
    else:
        print("❌ Some tests failed!")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 