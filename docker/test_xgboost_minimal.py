#!/usr/bin/env python3
"""
Minimal XGBoost COA Integration Test for 2-CPU Environment

This script provides a minimal test of the XGBoost COA integration
designed to work within resource-constrained environments.
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
        response = requests.get("http://seedcore-api:8002/energy/logs", timeout=10)
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

def test_minimal_training():
    """Test minimal XGBoost training with very few resources."""
    print_step("Testing Minimal XGBoost Training")
    
    train_request = {
        "use_sample_data": True,
        "sample_size": 1000,  # Minimum required by API
        "sample_features": 5,  # Very few features
        "name": "minimal_test_model",
        "xgb_config": {
            "objective": "binary:logistic",
            "eval_metric": ["logloss"],
            "eta": 0.3,
            "max_depth": 2,
            "num_boost_round": 5,  # Very few rounds
            "tree_method": "hist"
        },
        "training_config": {
            "num_workers": 1,  # Single worker
            "cpu_per_worker": 1,  # Must be integer, minimum 1
            "use_gpu": False,
            "memory_per_worker": 1000000000  # 1GB minimum required
        }
    }
    
    print("📤 Training minimal model...")
    try:
        response = requests.post(
            "http://localhost:8000/xgboost/train",
            json=train_request,
            timeout=120  # 2 minutes timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Minimal training completed!")
            print(f"   Model: {result.get('name')}")
            print(f"   Path: {result.get('path')}")
            print(f"   Time: {result.get('training_time', 'N/A')}s")
            return result.get('path')
        else:
            print(f"❌ Minimal training failed: {response.status_code}")
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

def test_minimal_prediction(model_path):
    """Test minimal prediction."""
    print_step("Testing Minimal Prediction")
    
    if not model_path:
        print("⚠️  No model path provided, skipping prediction test")
        return False
    
    # Create minimal features
    features = np.random.random(5).tolist()  # 5 features
    
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
        "metric": "minimal_test",
        "value": 0.5,
        "model_path": "/data/models/minimal_test_model.xgb",
        "success": True,
        "prediction_count": 1,
        "success_rate": 1.0
    }
    
    try:
        response = requests.post(
            "http://seedcore-api:8002/energy/log",
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
    print("🎯 Minimal XGBoost COA Integration Test (2-CPU Environment)")
    print("=" * 60)
    print("This test is optimized for resource-constrained environments")
    print("with limited CPU cores (2-CPU VM).")
    print()
    
    # Test 1: Service Health
    health_ok = test_service_health()
    if not health_ok:
        print("❌ Service health check failed. Exiting.")
        return
    
    # Test 2: Energy Endpoints
    energy_ok = test_energy_endpoints()
    
    # Test 3: Minimal Training
    model_path = test_minimal_training()
    
    # Test 4: Model Management
    model_mgmt_ok = test_model_management()
    
    # Test 5: Minimal Prediction
    prediction_ok = False
    if model_path:
        prediction_ok = test_minimal_prediction(model_path)
    
    # Test 6: Energy Logging
    energy_log_ok = test_energy_logging()
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Summary")
    print("=" * 60)
    print(f"   ✅ Service Health: {'PASS' if health_ok else 'FAIL'}")
    print(f"   ✅ Energy Endpoints: {'PASS' if energy_ok else 'FAIL'}")
    print(f"   ✅ Minimal Training: {'PASS' if model_path else 'FAIL'}")
    print(f"   ✅ Model Management: {'PASS' if model_mgmt_ok else 'FAIL'}")
    print(f"   ✅ Minimal Prediction: {'PASS' if prediction_ok else 'FAIL'}")
    print(f"   ✅ Energy Logging: {'PASS' if energy_log_ok else 'FAIL'}")
    
    passed_tests = sum([health_ok, energy_ok, bool(model_path), model_mgmt_ok, prediction_ok, energy_log_ok])
    total_tests = 6
    
    print(f"\n🎯 Overall Result: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("🎉 All tests passed! XGBoost COA integration works in 2-CPU environment.")
    else:
        print("⚠️  Some tests failed. This is expected in resource-constrained environments.")
    
    print("\n🔗 Recommendations for 2-CPU Environment:")
    print("   1. Use minimal training configurations (small datasets, few features)")
    print("   2. Run only 1 Ray worker to avoid resource contention")
    print("   3. Use reduced CPU allocation (0.1-0.5 cores per worker)")
    print("   4. Consider using pre-trained models for production")
    print("   5. Scale up to larger instances for full training workloads")

if __name__ == "__main__":
    main() 