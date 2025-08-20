#!/usr/bin/env python3
"""
Simple test script for the async XGBoost tuning API

This script tests the new async endpoints without running a full tuning job.
"""

import requests
import time
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_async_endpoints(base_url: str = "http://localhost:8000"):
    """Test the async API endpoints."""
    ml_service_url = f"{base_url}/ml_serve"
    session = requests.Session()
    
    logger.info(f"🔗 Testing async API at: {ml_service_url}")
    
    # Test 1: Submit a tuning job
    logger.info("🧪 Test 1: Submitting tuning job...")
    payload = {
        "space_type": "conservative",
        "config_type": "conservative",
        "experiment_name": "test_async_api"
    }
    
    try:
        submit_response = session.post(f"{ml_service_url}/xgboost/tune/submit", json=payload, timeout=300)
        submit_response.raise_for_status()
        submit_result = submit_response.json()
        
        job_id = submit_result.get("job_id")
        if not job_id:
            logger.error("❌ No job_id received")
            return False
        
        logger.info(f"✅ Job submitted successfully! Job ID: {job_id}")
        
        # Test 2: Check initial status
        logger.info("🧪 Test 2: Checking initial status...")
        status_response = session.get(f"{ml_service_url}/xgboost/tune/status/{job_id}", timeout=300)
        status_response.raise_for_status()
        status_result = status_response.json()
        
        logger.info(f"✅ Status: {status_result}")
        
        # Test 3: List all jobs
        logger.info("🧪 Test 3: Listing all jobs...")
        jobs_response = session.get(f"{ml_service_url}/xgboost/tune/jobs", timeout=300)
        jobs_response.raise_for_status()
        jobs_result = jobs_response.json()
        
        logger.info(f"✅ Jobs: {jobs_result}")
        
        # Test 4: Check status again after a short delay
        logger.info("🧪 Test 4: Checking status after delay...")
        time.sleep(2)
        
        status_response2 = session.get(f"{ml_service_url}/xgboost/tune/status/{job_id}", timeout=300)
        status_response2.raise_for_status()
        status_result2 = status_response2.json()
        
        logger.info(f"✅ Status after delay: {status_result2}")
        
        # Test 5: Test root endpoint to see new async endpoints
        logger.info("🧪 Test 5: Checking root endpoint...")
        root_response = session.get(f"{ml_service_url}/", timeout=300)
        root_response.raise_for_status()
        root_result = root_response.json()
        
        xgboost_endpoints = root_result.get("endpoints", {}).get("xgboost", {})
        if "tune_async" in xgboost_endpoints:
            logger.info("✅ Async endpoints are listed in root endpoint")
            logger.info(f"   Async endpoints: {xgboost_endpoints['tune_async']}")
        else:
            logger.warning("⚠️ Async endpoints not found in root endpoint")
        
        logger.info("🎉 All async API tests completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Async API test failed: {e}")
        return False

def main():
    """Main function."""
    logger.info("🚀 Starting Async API Test")
    logger.info("=" * 50)
    
    success = test_async_endpoints()
    
    if success:
        logger.info("✅ Async API test completed successfully!")
    else:
        logger.error("❌ Async API test failed!")
    
    logger.info("=" * 50)

if __name__ == "__main__":
    main()
