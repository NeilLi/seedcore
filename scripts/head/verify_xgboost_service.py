#!/usr/bin/env python3
"""
XGBoost Service Verification Script

This script verifies that the XGBoost service is properly initialized and working.
Run this script to check the status of the XGBoost integration.
"""

import sys
import os
import requests
import time
from pathlib import Path

# Add the app directory to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

def get_service_url():
    """Get service URL based on environment."""
    # Check if we're running in seedcore-api pod
    if os.getenv('SEEDCORE_API_ADDRESS'):
        # We're in the seedcore-api pod, use internal service names
        return "http://seedcore-svc-serve-svc:8000"
    else:
        # Local development or ray head pod
        return "http://localhost:8000"

def verify_xgboost_service():
    """Verify XGBoost service functionality."""
    
    print("🔍 Verifying XGBoost Service...")
    print("=" * 40)
    
    # Check 1: Service Import
    print("\n1️⃣ Checking XGBoost service import...")
    try:
        from seedcore.ml.models.xgboost_service import get_xgboost_service
        print("✅ XGBoost service module imported successfully")
    except Exception as e:
        print(f"❌ Failed to import XGBoost service: {e}")
        return False
    
    # Check 2: Service Initialization
    print("\n2️⃣ Checking XGBoost service initialization...")
    try:
        xgb_service = get_xgboost_service()
        if xgb_service is None:
            print("❌ XGBoost service is None")
            return False
        print("✅ XGBoost service initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize XGBoost service: {e}")
        return False
    
    # Check 3: Basic Functionality
    print("\n3️⃣ Testing basic functionality...")
    try:
        # Test dataset creation
        dataset = xgb_service.create_sample_dataset(n_samples=50, n_features=5)
        print(f"✅ Dataset creation: {dataset.count()} samples")
        
        # Test model listing
        models = xgb_service.list_models()
        print(f"✅ Model listing: {len(models)} models found")
        
        # Test model info
        info = xgb_service.get_model_info()
        print(f"✅ Model info: {info['status']}")
        
    except Exception as e:
        print(f"❌ Basic functionality test failed: {e}")
        return False
    
    # Check 4: API Endpoints
    print("\n4️⃣ Testing API endpoints...")
    base_url = get_service_url()
    print(f"🔗 Testing API at: {base_url}")
    
    try:
        # Test health endpoint
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            health_data = response.json()
            xgboost_status = health_data.get('models', {}).get('xgboost_service', 'unknown')
            print(f"✅ Health endpoint: XGBoost status = {xgboost_status}")
        else:
            print(f"❌ Health endpoint failed: {response.status_code}")
            return False
        
        # Test XGBoost endpoints
        response = requests.get(f"{base_url}/xgboost/list_models", timeout=5)
        if response.status_code == 200:
            print("✅ XGBoost list_models endpoint working")
        else:
            print(f"❌ XGBoost list_models endpoint failed: {response.status_code}")
            return False
        
        response = requests.get(f"{base_url}/xgboost/model_info", timeout=5)
        if response.status_code == 200:
            print("✅ XGBoost model_info endpoint working")
        else:
            print(f"❌ XGBoost model_info endpoint failed: {response.status_code}")
            return False
        
    except Exception as e:
        print(f"❌ API endpoint test failed: {e}")
        return False
    
    print("\n🎉 All verification tests passed!")
    return True

def main():
    """Main verification function."""
    
    print("🚀 XGBoost Service Verification")
    print("=" * 50)
    
    # Check environment
    print("🔍 Environment Check:")
    print(f"   RAY_ADDRESS: {os.getenv('RAY_ADDRESS', 'Not set')}")
    print(f"   PYTHONPATH: {os.getenv('PYTHONPATH', 'Not set')}")
    print(f"   Working Directory: {os.getcwd()}")
    
    # Check Ray initialization status
    ray_address = os.getenv("RAY_ADDRESS")
    if ray_address:
        print(f"   RAY_ADDRESS: ✅ {ray_address}")
    else:
        print("   RAY_ADDRESS: ⚠️ Not set (will use local Ray)")
    
    try:
        import ray
        if ray.is_initialized():
            print("   Ray Status: ✅ Initialized")
        else:
            print("   Ray Status: ❌ Not initialized")
    except Exception as e:
        print(f"   Ray Status: ⚠️ Error checking - {e}")
    print()
    
    # Run verification
    success = verify_xgboost_service()
    
    if success:
        print("\n✅ XGBoost service verification completed successfully!")
        print("   The XGBoost integration is working properly.")
        print("\n📋 Available endpoints:")
        print("   - Training: POST /xgboost/train")
        print("   - Prediction: POST /xgboost/predict")
        print("   - Batch Prediction: POST /xgboost/batch_predict")
        print("   - Model Management: GET /xgboost/list_models, /xgboost/model_info")
        base_url = get_service_url()
        print(f"\n🔗 Access the API at: {base_url}")
    else:
        print("\n❌ XGBoost service verification failed!")
        print("   Please check the error messages above.")
        sys.exit(1)

if __name__ == "__main__":
    main() 