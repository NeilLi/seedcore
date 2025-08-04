#!/usr/bin/env python3
"""
Docker-compatible test script for XGBoost integration.

This script is designed to run inside the Docker container where Ray is already initialized.
"""

import sys
import os
import time
import tempfile
from pathlib import Path

# Add the app directory to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

def test_xgboost_service_in_docker():
    """Test the XGBoost service functionality within Docker environment."""
    
    print("🧪 Testing XGBoost Service in Docker Environment")
    print("=" * 50)
    
    try:
        from seedcore.ml.models.xgboost_service import XGBoostService, XGBoostConfig, TrainingConfig
        
        # Use the shared data directory for models
        model_storage = "/data/models"
        print(f"📁 Using model storage: {model_storage}")
        
        # Initialize service
        print("\n1️⃣ Initializing XGBoost Service...")
        service = XGBoostService(model_storage_path=model_storage)
        print("✅ Service initialized successfully")
        
        # Test sample dataset creation
        print("\n2️⃣ Creating Sample Dataset...")
        dataset = service.create_sample_dataset(n_samples=1000, n_features=10)
        print(f"✅ Created dataset with {dataset.count()} samples")
        
        # Test model training with Docker-appropriate settings
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
                num_workers=1,  # Use 1 worker for testing in container
                cpu_per_worker=1,
                memory_per_worker=1000000000  # 1GB per worker
            ),
            model_name="docker_test_model"
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
        
        print("\n🎉 All Docker tests passed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Docker test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_api_endpoints_in_docker():
    """Test the API endpoints within the Docker container."""
    
    print("\n🌐 Testing API Endpoints in Docker")
    print("=" * 40)
    
    try:
        import requests
        
        # Test health endpoint
        print("\n1️⃣ Testing Health Endpoint...")
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            print("✅ Health endpoint working")
            health_data = response.json()
            print(f"   Service: {health_data.get('service', 'unknown')}")
        else:
            print(f"❌ Health endpoint failed: {response.status_code}")
            return False
        
        # Test XGBoost endpoints
        print("\n2️⃣ Testing XGBoost Endpoints...")
        
        # Test model listing
        response = requests.get("http://localhost:8000/xgboost/list_models", timeout=5)
        if response.status_code == 200:
            print("✅ Model listing endpoint working")
            models_data = response.json()
            print(f"   Total models: {models_data.get('total_count', 0)}")
        else:
            print(f"❌ Model listing failed: {response.status_code}")
        
        # Test model info
        response = requests.get("http://localhost:8000/xgboost/model_info", timeout=5)
        if response.status_code == 200:
            print("✅ Model info endpoint working")
            info_data = response.json()
            print(f"   Status: {info_data.get('status', 'unknown')}")
        else:
            print(f"❌ Model info failed: {response.status_code}")
        
        print("✅ API endpoint tests completed")
        return True
        
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to API service")
        print("   Make sure the Ray Serve application is running")
        return False
    except Exception as e:
        print(f"❌ API test failed: {e}")
        return False

def test_xgboost_training_via_api():
    """Test XGBoost training via the API endpoint."""
    
    print("\n🚀 Testing XGBoost Training via API")
    print("=" * 40)
    
    try:
        import requests
        
        # Prepare training request
        train_request = {
            "use_sample_data": True,
            "sample_size": 2000,  # Increased to meet minimum requirements
            "sample_features": 8,
            "name": "api_test_model",
            "xgb_config": {
                "objective": "binary:logistic",
                "eval_metric": ["logloss", "auc"],
                "eta": 0.1,
                "max_depth": 3,
                "num_boost_round": 5
            },
            "training_config": {
                "num_workers": 1,
                "use_gpu": False,
                "cpu_per_worker": 1
            }
        }
        
        print("📤 Sending training request...")
        response = requests.post(
            "http://localhost:8000/xgboost/train",
            json=train_request,
            headers={"Content-Type": "application/json"},
            timeout=60  # Longer timeout for training
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Training via API completed successfully!")
            print(f"   Model Path: {result['path']}")
            print(f"   Training Time: {result['training_time']:.2f}s")
            print(f"   Status: {result['status']}")
            
            # Test prediction with the trained model
            print("\n📊 Testing Prediction with Trained Model...")
            predict_request = {
                "features": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
                "path": result['path']
            }
            
            predict_response = requests.post(
                "http://localhost:8000/xgboost/predict",
                json=predict_request,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            if predict_response.status_code == 200:
                predict_result = predict_response.json()
                print("✅ Prediction via API completed!")
                print(f"   Prediction: {predict_result['prediction']}")
                print(f"   Model Used: {predict_result['path']}")
            else:
                print(f"❌ Prediction failed: {predict_response.status_code}")
                print(f"   Error: {predict_response.text}")
            
            return True
        else:
            print(f"❌ Training failed: {response.status_code}")
            print(f"   Error: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ API training test failed: {e}")
        return False

def main():
    """Run all Docker tests."""
    
    print("🚀 Starting XGBoost Docker Integration Tests")
    print("=" * 60)
    
    # Check if we're in the right environment
    print(f"🔍 Environment Check:")
    print(f"   PYTHONPATH: {os.getenv('PYTHONPATH', 'Not set')}")
    print(f"   RAY_ADDRESS: {os.getenv('RAY_ADDRESS', 'Not set')}")
    print(f"   Working Directory: {os.getcwd()}")
    
    # Test service functionality
    service_test_passed = test_xgboost_service_in_docker()
    
    # Test API endpoints
    api_test_passed = test_api_endpoints_in_docker()
    
    # Test training via API
    api_training_passed = test_xgboost_training_via_api()
    
    # Summary
    print("\n📊 Docker Test Summary")
    print("=" * 25)
    print(f"Service Tests: {'✅ PASSED' if service_test_passed else '❌ FAILED'}")
    print(f"API Tests: {'✅ PASSED' if api_test_passed else '❌ FAILED'}")
    print(f"API Training: {'✅ PASSED' if api_training_passed else '❌ FAILED'}")
    
    if service_test_passed and api_test_passed and api_training_passed:
        print("\n🎉 All Docker tests passed!")
        print("   The XGBoost integration is working correctly in the Docker environment.")
    else:
        print("\n⚠️  Some Docker tests failed.")
        print("   Please check the error messages above.")

if __name__ == "__main__":
    main() 