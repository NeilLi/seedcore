#!/usr/bin/env python3
"""
Simple XGBoost COA Integration Test

This script provides a lightweight test of the XGBoost COA integration
without overwhelming system resources.
"""

import requests
import json
import time
import numpy as np
import sys
import os

# Add the app directory to Python path
sys.path.insert(0, '/app')

def print_step(step: str):
    """Print a formatted step."""
    print(f"\n📋 {step}")
    print(f"{'-'*40}")

def test_service_health():
    """Test if the ML service is healthy."""
    print_step("Testing Service Health")
    
    try:
        response = requests.get("http://localhost:8000/health", timeout=10)
        if response.status_code == 200:
            health_data = response.json()
            print(f"✅ Service is healthy")
            print(f"   Status: {health_data.get('status')}")
            print(f"   Service: {health_data.get('service')}")
            print(f"   XGBoost: {health_data.get('models', {}).get('xgboost_service')}")
            return True
        else:
            print(f"❌ Service unhealthy: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Service check failed: {e}")
        return False

def test_energy_endpoints():
    """Test energy logging endpoints."""
    print_step("Testing Energy Endpoints")
    
    try:
        # Test energy logs endpoint (telemetry server on internal network)
        api_address = os.getenv("SEEDCORE_API_ADDRESS", "seedcore-api:8002")
        if not api_address.startswith("http"):
            api_address = f"http://{api_address}"
        response = requests.get(f"{api_address}/energy/logs", timeout=10)
        if response.status_code == 200:
            logs_data = response.json()
            print(f"✅ Energy logs accessible")
            print(f"   Total events: {logs_data.get('total_count', 0)}")
            return True
        else:
            print(f"❌ Energy logs not accessible: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Energy endpoints test failed: {e}")
        return False

def test_simple_training():
    """Test simple XGBoost training with minimal resources."""
    print_step("Testing Simple XGBoost Training")
    
    train_request = {
        "use_sample_data": True,
        "sample_size": 1000,  # Small dataset
        "sample_features": 10,  # Few features
        "name": "simple_test_model",
        "xgb_config": {
            "objective": "binary:logistic",
            "eval_metric": ["logloss"],
            "eta": 0.1,
            "max_depth": 3,
            "num_boost_round": 10,  # Few rounds
            "tree_method": "hist"
        },
        "training_config": {
            "num_workers": 1,  # Single worker
            "cpu_per_worker": 0.5,  # Use only 0.5 CPU cores per worker
            "use_gpu": False,
            "memory_per_worker": 500000000  # 500MB
        }
    }
    
    print("📤 Training simple model...")
    try:
        response = requests.post(
            "http://localhost:8000/xgboost/train",
            json=train_request,
            timeout=120  # 2 minutes timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Simple training completed!")
            print(f"   Model: {result.get('name')}")
            print(f"   Path: {result.get('path')}")
            print(f"   Time: {result.get('training_time', 'N/A')}s")
            return result.get('path')
        else:
            print(f"❌ Simple training failed: {response.status_code}")
            print(f"   Error: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Training request failed: {e}")
        return None

def test_model_management():
    """Test model management endpoints."""
    print_step("Testing Model Management")
    
    try:
        # List models
        response = requests.get("http://localhost:8000/xgboost/list_models", timeout=10)
        if response.status_code == 200:
            models_data = response.json()
            models = models_data.get("models", [])
            print(f"✅ Model listing works")
            print(f"   Found {len(models)} models")
            if models:
                print(f"   Latest: {models[0].get('name', 'Unknown')}")
            return True
        else:
            print(f"❌ Model listing failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Model management test failed: {e}")
        return False

def test_simple_prediction(model_path):
    """Test simple prediction."""
    print_step("Testing Simple Prediction")
    
    if not model_path:
        print("⚠️  No model path provided, skipping prediction test")
        return False
    
    # Create simple features
    features = np.random.random(10).tolist()  # 10 features
    
    predict_request = {
        "features": features,
        "path": model_path
    }
    
    try:
        response = requests.post(
            "http://localhost:8000/xgboost/predict",
            json=predict_request,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Prediction successful!")
            print(f"   Prediction: {result.get('prediction')}")
            print(f"   Model: {result.get('path')}")
            return True
        else:
            print(f"❌ Prediction failed: {response.status_code}")
            print(f"   Error: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Prediction request failed: {e}")
        return False

def test_energy_logging():
    """Test energy logging functionality."""
    print_step("Testing Energy Logging")
    
    energy_event = {
        "ts": time.time(),
        "organ": "utility",
        "metric": "test_prediction",
        "value": 0.75,
        "model_path": "/data/models/test_model.xgb",
        "success": True,
        "prediction_count": 1,
        "success_rate": 1.0
    }
    
    try:
        api_address = os.getenv("SEEDCORE_API_ADDRESS", "seedcore-api:8002")
        if not api_address.startswith("http"):
            api_address = f"http://{api_address}"
        response = requests.post(
            f"{api_address}/energy/log",
            json=energy_event,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Energy logging successful!")
            print(f"   Status: {result.get('status')}")
            print(f"   Event count: {result.get('event_count')}")
            return True
        else:
            print(f"❌ Energy logging failed: {response.status_code}")
            print(f"   Error: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Energy logging request failed: {e}")
        return False

def main():
    """Main test function."""
    print("🎯 Simple XGBoost COA Integration Test")
    print("=" * 50)
    
    # Test 1: Service Health
    health_ok = test_service_health()
    if not health_ok:
        print("❌ Service health check failed. Exiting.")
        return
    
    # Test 2: Energy Endpoints
    energy_ok = test_energy_endpoints()
    
    # Test 3: Simple Training
    model_path = test_simple_training()
    
    # Test 4: Model Management
    model_mgmt_ok = test_model_management()
    
    # Test 5: Simple Prediction
    prediction_ok = False
    if model_path:
        prediction_ok = test_simple_prediction(model_path)
    
    # Test 6: Energy Logging
    energy_log_ok = test_energy_logging()
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Test Summary")
    print("=" * 50)
    print(f"   ✅ Service Health: {'PASS' if health_ok else 'FAIL'}")
    print(f"   ✅ Energy Endpoints: {'PASS' if energy_ok else 'FAIL'}")
    print(f"   ✅ Simple Training: {'PASS' if model_path else 'FAIL'}")
    print(f"   ✅ Model Management: {'PASS' if model_mgmt_ok else 'FAIL'}")
    print(f"   ✅ Simple Prediction: {'PASS' if prediction_ok else 'FAIL'}")
    print(f"   ✅ Energy Logging: {'PASS' if energy_log_ok else 'FAIL'}")
    
    passed_tests = sum([health_ok, energy_ok, bool(model_path), model_mgmt_ok, prediction_ok, energy_log_ok])
    total_tests = 6
    
    print(f"\n🎯 Overall Result: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("🎉 All tests passed! XGBoost COA integration is working correctly.")
    else:
        print("⚠️  Some tests failed. Check the logs for details.")
    
    print("\n🔗 Next Steps:")
    print("   1. Run the full integration demo when resources are available")
    print("   2. Test with larger datasets and more workers")
    print("   3. Integrate with production telemetry streams")

if __name__ == "__main__":
    main() 