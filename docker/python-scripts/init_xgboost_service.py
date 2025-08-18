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

def setup_storage_path():
    """Setup and verify the XGBoost storage path."""
    
    # Get storage path from environment variable, default to writable location
    default_storage = Path(os.getenv("XGB_STORAGE_PATH", "/app/data/models"))
    print(f"📁 Setting up XGBoost storage path: {default_storage}")
    
    try:
        # Create the storage directory if it doesn't exist
        default_storage.mkdir(parents=True, exist_ok=True)
        
        # Test if the directory is writable
        test_file = default_storage / ".write_test"
        test_file.write_text("test")
        test_file.unlink()  # Clean up test file
        
        print(f"✅ Storage path is writable: {default_storage}")
        return default_storage
        
    except Exception as e:
        print(f"⚠️ Warning: Could not write to {default_storage}: {e}")
        
        # Fallback to /app/data/models if the configured path is not writable
        fallback_path = Path("/app/data/models")
        print(f"🔄 Falling back to fallback path: {fallback_path}")
        
        try:
            fallback_path.mkdir(parents=True, exist_ok=True)
            test_file = fallback_path / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            
            print(f"✅ Fallback storage path is writable: {fallback_path}")
            return fallback_path
            
        except Exception as fallback_error:
            print(f"❌ Error: Both storage paths are not writable")
            print(f"   Primary: {default_storage} - {e}")
            print(f"   Fallback: {fallback_path} - {fallback_error}")
            raise RuntimeError("No writable storage path available for XGBoost models")

def init_xgboost_service():
    """Initialize the XGBoost service."""
    
    print("🔧 Initializing XGBoost Service...")
    
    try:
        # Setup storage path first
        storage_path = setup_storage_path()
        
        # Set environment variable for the service to use
        os.environ["XGB_STORAGE_PATH"] = str(storage_path)
        print(f"🔧 Set XGB_STORAGE_PATH environment variable to: {storage_path}")
        
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
    print(f"   XGB_STORAGE_PATH: {os.getenv('XGB_STORAGE_PATH', 'Not set (will use default)')}")
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