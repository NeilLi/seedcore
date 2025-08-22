#!/usr/bin/env python3
"""
Debug script to test tuning functionality directly.
"""

import sys
import os
sys.path.append('/app')

import ray
import logging
from src.seedcore.ml.tuning_service import get_tuning_service

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_ray_connection():
    """Test Ray connection."""
    logger.info("🧪 Testing Ray connection...")
    
    try:
        if not ray.is_initialized():
            # Try to connect to Ray
            from seedcore.utils.ray_utils import ensure_ray_initialized
            if not ensure_ray_initialized(ray_address="ray://localhost:10001"):
                logger.error("❌ Failed to connect to Ray cluster")
                return False
            logger.info("✅ Connected to Ray cluster")
        else:
            logger.info("✅ Ray already initialized")
        
        logger.info(f"✅ Ray initialized: {ray.is_initialized()}")
        logger.info(f"✅ Ray address: {ray.get_runtime_context().gcs_address}")
        logger.info(f"✅ Available resources: {ray.available_resources()}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to connect to Ray: {e}")
        return False

def test_tuning_service():
    """Test tuning service."""
    logger.info("🧪 Testing tuning service...")
    
    try:
        # Get tuning service
        tuning_service = get_tuning_service()
        logger.info("✅ Tuning service created")
        
        # Test with minimal configuration
        result = tuning_service.run_tuning_sweep(
            space_type="conservative",
            config_type="conservative",
            experiment_name="debug_test"
        )
        
        logger.info(f"✅ Tuning result: {result}")
        return True
    except Exception as e:
        logger.error(f"❌ Tuning service failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run debug tests."""
    logger.info("🚀 Starting debug tests")
    logger.info("=" * 50)
    
    # Test Ray connection
    ray_success = test_ray_connection()
    
    if ray_success:
        # Test tuning service
        tuning_success = test_tuning_service()
        
        if tuning_success:
            logger.info("🎉 All debug tests passed!")
        else:
            logger.error("❌ Tuning service test failed")
    else:
        logger.error("❌ Ray connection test failed")

if __name__ == "__main__":
    main() 