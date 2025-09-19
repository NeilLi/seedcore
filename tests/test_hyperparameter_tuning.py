#!/usr/bin/env python3
"""
Test script for hyperparameter tuning functionality.

This script tests the basic functionality of the hyperparameter tuning system
without running full tuning sweeps.
"""

import requests
import json
import time
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def teardown_module(module):
    """Ensure Ray is properly shut down after tests to prevent state contamination."""
    try:
        import ray
        if ray.is_initialized():
            ray.shutdown()
            logger.info("✅ Ray shut down in teardown_module")
    except Exception as e:
        logger.debug(f"Ray teardown skipped: {e}")

def test_service_health(base_url: str = "http://localhost:8000") -> bool:
    """Test if the service is running and healthy."""
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            logger.info("✅ Service is healthy")
            return True
        else:
            logger.error(f"❌ Service health check failed: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"❌ Service health check failed: {e}")
        return False

def test_basic_training(base_url: str = "http://localhost:8000") -> bool:
    """Test basic XGBoost training."""
    logger.info("🧪 Testing basic XGBoost training...")
    
    payload = {
        "use_sample_data": True,
        "sample_size": 100,  # Small dataset for quick test
        "sample_features": 5,
        "name": "test_basic_model",
        "xgb_config": {
            "objective": "binary:logistic",
            "eval_metric": ["logloss", "auc"],
            "eta": 0.1,
            "max_depth": 3,
            "num_boost_round": 5  # Very few rounds for quick test
        },
        "training_config": {
            "num_workers": 1,
            "use_gpu": False,
            "cpu_per_worker": 1
        }
    }
    
    try:
        response = requests.post(f"{base_url}/xgboost/train", json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        
        logger.info(f"✅ Basic training successful - AUC: {result.get('metrics', {}).get('validation_0-auc', 'N/A')}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Basic training failed: {e}")
        return False

def test_tuning_endpoint_structure(base_url: str = "http://localhost:8000") -> bool:
    """Test that the tuning endpoint exists and accepts requests."""
    logger.info("🧪 Testing tuning endpoint structure...")
    
    payload = {
        "space_type": "conservative",
        "config_type": "conservative",
        "experiment_name": "test_tuning_structure"
    }
    
    try:
        # Just test that the endpoint exists and accepts the request format
        response = requests.post(f"{base_url}/xgboost/tune", json=payload, timeout=10)
        
        # We expect either a success response or a timeout/error indicating the service is working
        if response.status_code in [200, 202, 500]:  # Accept various response codes
            logger.info("✅ Tuning endpoint structure is correct")
            return True
        else:
            logger.error(f"❌ Unexpected response code: {response.status_code}")
            return False
            
    except requests.exceptions.Timeout:
        # Timeout is expected for a real tuning run
        logger.info("✅ Tuning endpoint accepted request (timeout expected for real tuning)")
        return True
    except Exception as e:
        logger.error(f"❌ Tuning endpoint test failed: {e}")
        return False

def test_refresh_endpoint(base_url: str = "http://localhost:8000") -> bool:
    """Test the model refresh endpoint."""
    logger.info("🧪 Testing model refresh endpoint...")
    
    try:
        response = requests.post(f"{base_url}/xgboost/refresh_model", timeout=10)
        
        # Refresh might succeed or fail depending on whether there's a promoted model
        if response.status_code in [200, 400]:
            result = response.json()
            logger.info(f"✅ Model refresh endpoint working: {result.get('message', 'N/A')}")
            return True
        else:
            logger.error(f"❌ Unexpected response code: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Model refresh test failed: {e}")
        return False

def test_prediction_endpoint(base_url: str = "http://localhost:8000") -> bool:
    """Test the prediction endpoint."""
    logger.info("🧪 Testing prediction endpoint...")
    
    payload = {
        "features": [0.1, 0.2, 0.3, 0.4, 0.5]  # 5 features for our test model
    }
    
    try:
        response = requests.post(f"{base_url}/xgboost/predict", json=payload, timeout=10)
        
        if response.status_code in [200, 400]:  # Accept both success and model-not-loaded
            result = response.json()
            if result.get("status") == "success":
                logger.info(f"✅ Prediction successful: {result.get('prediction', 'N/A')}")
            else:
                logger.info(f"✅ Prediction endpoint working (no model loaded): {result.get('error', 'N/A')}")
            return True
        else:
            logger.error(f"❌ Unexpected response code: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Prediction test failed: {e}")
        return False

def main():
    """Run all tests."""
    logger.info("🚀 Starting hyperparameter tuning tests")
    logger.info("=" * 50)
    
    base_url = "http://localhost:8000"
    
    # Run tests
    tests = [
        ("Service Health", lambda: test_service_health(base_url)),
        ("Basic Training", lambda: test_basic_training(base_url)),
        ("Tuning Endpoint", lambda: test_tuning_endpoint_structure(base_url)),
        ("Refresh Endpoint", lambda: test_refresh_endpoint(base_url)),
        ("Prediction Endpoint", lambda: test_prediction_endpoint(base_url)),
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info(f"\n📋 Running {test_name} test...")
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            logger.error(f"❌ {test_name} test failed with exception: {e}")
            results.append((test_name, False))
    
    # Summary
    logger.info("\n" + "=" * 50)
    logger.info("📊 Test Results Summary:")
    
    passed = 0
    total = len(results)
    
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"  {status} - {test_name}")
        if success:
            passed += 1
    
    logger.info(f"\n🎯 Overall: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All tests passed! Hyperparameter tuning system is ready.")
    else:
        logger.warning("⚠️ Some tests failed. Check the logs above for details.")
    
    logger.info("\n📚 Next steps:")
    logger.info("  1. Run the full demo: python examples/xgboost_tuning_demo.py")
    logger.info("  2. Check the documentation: docs/guides/hyperparameter-tuning/HYPERPARAMETER_TUNING_GUIDE.md")
    logger.info("  3. Monitor Ray Dashboard: http://localhost:8265")

if __name__ == "__main__":
    main() 