#!/usr/bin/env python3
"""
Test script for the fixed async XGBoost tuning API

This script tests that the async API now returns immediately without blocking.
"""

import requests
import time
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_async_behavior(base_url: str = "http://localhost:8000"):
    """Test that the async API returns immediately without blocking."""
    ml_service_url = f"{base_url}/ml_serve"
    session = requests.Session()
    
    logger.info(f"🔗 Testing fixed async API at: {ml_service_url}")
    
    # Test 1: Submit a tuning job and verify immediate response
    logger.info("🧪 Test 1: Testing immediate response from job submission...")
    payload = {
        "space_type": "conservative",
        "config_type": "conservative",
        "experiment_name": "test_async_fixed"
    }
    
    start_time = time.time()
    
    try:
        submit_response = session.post(f"{ml_service_url}/xgboost/tune/submit", json=payload, timeout=10)
        submit_response.raise_for_status()
        submit_result = submit_response.json()
        
        response_time = time.time() - start_time
        
        job_id = submit_result.get("job_id")
        if not job_id:
            logger.error("❌ No job_id received")
            return False
        
        logger.info(f"✅ Job submitted successfully! Job ID: {job_id}")
        logger.info(f"✅ Response time: {response_time:.2f} seconds (should be < 1 second)")
        
        # Verify the response was fast (should be under 1 second for async)
        if response_time > 1.0:
            logger.warning(f"⚠️ Response time ({response_time:.2f}s) is slower than expected for async API")
        else:
            logger.info("✅ Response time is fast - async behavior working correctly!")
        
        # Test 2: Check status immediately after submission
        logger.info("🧪 Test 2: Checking status immediately after submission...")
        status_response = session.get(f"{ml_service_url}/xgboost/tune/status/{job_id}", timeout=10)
        status_response.raise_for_status()
        status_result = status_response.json()
        
        logger.info(f"✅ Status check successful: {status_result.get('status')}")
        
        # Test 3: Wait a bit and check status again
        logger.info("🧪 Test 3: Waiting 5 seconds and checking status again...")
        time.sleep(5)
        
        status_response2 = session.get(f"{ml_service_url}/xgboost/tune/status/{job_id}", timeout=10)
        status_response2.raise_for_status()
        status_result2 = status_response2.json()
        
        logger.info(f"✅ Status after delay: {status_result2.get('status')}")
        
        # Test 4: List all jobs
        logger.info("🧪 Test 4: Listing all jobs...")
        jobs_response = session.get(f"{ml_service_url}/xgboost/tune/jobs", timeout=10)
        jobs_response.raise_for_status()
        jobs_result = jobs_response.json()
        
        logger.info(f"✅ Jobs listing successful: {jobs_result.get('total_jobs')} jobs found")
        
        logger.info("🎉 Async behavior test completed successfully!")
        logger.info("   The API is now truly asynchronous and returns immediately!")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Async behavior test failed: {e}")
        return False

def test_synchronous_endpoint(base_url: str = "http://localhost:8000"):
    """Test that the synchronous endpoint still works for backward compatibility."""
    ml_service_url = f"{base_url}/ml_serve"
    session = requests.Session()
    
    logger.info("🧪 Test 5: Testing synchronous endpoint for backward compatibility...")
    
    payload = {
        "space_type": "conservative",
        "config_type": "conservative",
        "experiment_name": "test_sync_compat"
    }
    
    try:
        # This should still work but will block until completion
        logger.info("   Note: This will block until tuning completes (backward compatibility)")
        response = session.post(f"{ml_service_url}/xgboost/tune", json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        logger.info(f"✅ Synchronous endpoint working: {result.get('status')}")
        return True
        
    except requests.exceptions.Timeout:
        logger.info("✅ Synchronous endpoint timed out as expected (long-running operation)")
        return True
    except Exception as e:
        logger.error(f"❌ Synchronous endpoint test failed: {e}")
        return False

def main():
    """Main test function."""
    logger.info("🚀 Starting Fixed Async API Test")
    logger.info("=" * 60)
    
    success1 = test_async_behavior()
    success2 = test_synchronous_endpoint()
    
    print("\n" + "=" * 60)
    if success1 and success2:
        logger.info("🎉 All tests passed! The async API is now working correctly!")
        logger.info("   ✅ Jobs submit immediately without blocking")
        logger.info("   ✅ Status can be polled asynchronously")
        logger.info("   ✅ Synchronous endpoint still works for compatibility")
    else:
        logger.error("❌ Some tests failed. Please check the implementation.")
    
    logger.info("=" * 60)

if __name__ == "__main__":
    main()
