#!/usr/bin/env python3
"""
XGBoost Service Initialization Script

This script initializes the XGBoost service during Ray cluster startup.
It ensures the service is ready and functional before the ML endpoints are available.
"""

import sys
import os
import time
import logging
from pathlib import Path

# Add the app directory to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_xgboost_service():
    """Initialize the XGBoost service."""
    
    print("🔧 Initializing XGBoost Service...")
    
    try:
        # Import and initialize XGBoost service
        from seedcore.ml.models.xgboost_service import get_xgboost_service
        
        # Get the service instance
        xgb_service = get_xgboost_service()
        
        if xgb_service is None:
            raise RuntimeError("Failed to get XGBoost service instance")
        
        print("✅ XGBoost service instance created")
        
        # Test basic functionality
        print("🧪 Testing XGBoost service functionality...")
        
        # Test dataset creation
        test_dataset = xgb_service.create_sample_dataset(n_samples=100, n_features=5)
        print(f"✅ Dataset creation test passed - created {test_dataset.count()} samples")
        
        # Test model storage
        models = xgb_service.list_models()
        print(f"✅ Model listing test passed - found {len(models)} existing models")
        
        # Test model info
        info = xgb_service.get_model_info()
        print(f"✅ Model info test passed - status: {info['status']}")
        
        print("🎉 XGBoost service initialization completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ XGBoost service initialization failed: {e}")
        logger.error(f"XGBoost service initialization error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main initialization function."""
    
    print("🚀 XGBoost Service Initialization")
    print("=" * 40)
    
    # Check environment
    print("🔍 Environment Check:")
    print(f"   RAY_ADDRESS: {os.getenv('RAY_ADDRESS', 'Not set')}")
    print(f"   PYTHONPATH: {os.getenv('PYTHONPATH', 'Not set')}")
    print(f"   Working Directory: {os.getcwd()}")
    print()
    
    # Wait a bit for Ray to be ready
    print("⏳ Waiting for Ray to be ready...")
    time.sleep(5)
    
    # Check Ray initialization status
    try:
        import ray
        if ray.is_initialized():
            print("✅ Ray is already initialized, proceeding with XGBoost service")
        else:
            print("⚠️ Ray is not initialized, this may cause issues")
    except Exception as e:
        print(f"⚠️ Could not check Ray initialization status: {e}")
    
    # Initialize the service
    success = init_xgboost_service()
    
    if success:
        print("\n✅ XGBoost service is ready!")
        print("   The service can now handle training and prediction requests.")
    else:
        print("\n⚠️ XGBoost service initialization failed.")
        print("   The service may not work properly.")
        sys.exit(1)

if __name__ == "__main__":
    main() 