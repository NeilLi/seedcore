#!/usr/bin/env python3
"""
Test script for XGBoost integration with Ray Data.

This script tests the basic functionality of the XGBoost service.
"""

import sys
import os
import time
import tempfile
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def test_xgboost_service():
    """Test the XGBoost service functionality."""
    
    print("🧪 Testing XGBoost Service Integration")
    print("=" * 40)
    
    try:
        from seedcore.ml.models.xgboost_service import XGBoostService, XGBoostConfig, TrainingConfig
        
        # Create temporary directory for models
        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"📁 Using temporary directory: {temp_dir}")
            
            # Initialize service
            print("\n1️⃣ Initializing XGBoost Service...")
            service = XGBoostService(model_storage_path=temp_dir)
            print("✅ Service initialized successfully")
            
            # Test sample dataset creation
            print("\n2️⃣ Creating Sample Dataset...")
            dataset = service.create_sample_dataset(n_samples=1000, n_features=10)
            print(f"✅ Created dataset with {dataset.count()} samples")
            
            # Test model training
            print("\n3️⃣ Training XGBoost Model...")
            start_time = time.time()
            
            result = service.train_model(
                dataset=dataset,
                label_column="target",
                xgb_config=XGBoostConfig(
                    objective="binary:logistic",
                    num_boost_round=10,  # Small number for quick test
                    max_depth=3
                ),
                training_config=TrainingConfig(
                    num_workers=1,  # Use 1 worker for testing
                    cpu_per_worker=1
                ),
                model_name="test_model"
            )
            
            training_time = time.time() - start_time
            print(f"✅ Training completed in {training_time:.2f}s")
            print(f"   Model saved to: {result['path']}")
            print(f"   Training metrics: {result['metrics']}")
            
            # Test prediction
            print("\n4️⃣ Testing Prediction...")
            sample_features = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
            prediction = service.predict(sample_features)
            print(f"✅ Prediction: {prediction}")
            
            # Test model info
            print("\n5️⃣ Testing Model Info...")
            info = service.get_model_info()
            print(f"✅ Model info: {info['status']}")
            
            # Test model listing
            print("\n6️⃣ Testing Model Listing...")
            models = service.list_models()
            print(f"✅ Found {len(models)} models")
            
            print("\n🎉 All tests passed successfully!")
            return True
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_api_endpoints():
    """Test the API endpoints (requires running service)."""
    
    print("\n🌐 Testing API Endpoints")
    print("=" * 30)
    
    try:
        import requests
        
        base_url = "http://localhost:8000"
        
        # Test health endpoint
        print("\n1️⃣ Testing Health Endpoint...")
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            print("✅ Health endpoint working")
        else:
            print(f"❌ Health endpoint failed: {response.status_code}")
            return False
        
        # Test XGBoost endpoints
        print("\n2️⃣ Testing XGBoost Endpoints...")
        
        # Test model listing
        response = requests.get(f"{base_url}/xgboost/list_models", timeout=5)
        if response.status_code == 200:
            print("✅ Model listing endpoint working")
        else:
            print(f"❌ Model listing failed: {response.status_code}")
        
        # Test model info
        response = requests.get(f"{base_url}/xgboost/model_info", timeout=5)
        if response.status_code == 200:
            print("✅ Model info endpoint working")
        else:
            print(f"❌ Model info failed: {response.status_code}")
        
        print("✅ API endpoint tests completed")
        return True
        
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to API service")
        print("   Make sure the Ray cluster and ML service are running")
        return False
    except Exception as e:
        print(f"❌ API test failed: {e}")
        return False

def main():
    """Run all tests."""
    
    print("🚀 Starting XGBoost Integration Tests")
    print("=" * 50)
    
    # Test service functionality
    service_test_passed = test_xgboost_service()
    
    # Test API endpoints (if service is running)
    api_test_passed = test_api_endpoints()
    
    # Summary
    print("\n📊 Test Summary")
    print("=" * 20)
    print(f"Service Tests: {'✅ PASSED' if service_test_passed else '❌ FAILED'}")
    print(f"API Tests: {'✅ PASSED' if api_test_passed else '❌ FAILED'}")
    
    if service_test_passed:
        print("\n🎉 Core functionality is working!")
        print("   The XGBoost integration is ready to use.")
    else:
        print("\n⚠️  Core functionality has issues.")
        print("   Please check the error messages above.")
    
    if not api_test_passed:
        print("\n💡 API tests failed - this is expected if the service isn't running.")
        print("   Start the Ray cluster and ML service to test the API endpoints.")

if __name__ == "__main__":
    main() 