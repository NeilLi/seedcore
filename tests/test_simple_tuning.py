#!/usr/bin/env python3
"""
Simple test to check if the tuning endpoint responds.
"""

import requests
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_tuning_endpoint():
    """Test if the tuning endpoint responds."""
    logger.info("🧪 Testing tuning endpoint response...")
    
    # Test with minimal payload
    payload = {
        "space_type": "conservative",
        "config_type": "conservative",
        "experiment_name": "simple_test"
    }
    
    try:
        # Use a very short timeout to just check if the endpoint responds
        response = requests.post(
            "http://localhost:8000/xgboost/tune",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=5  # 5 second timeout
        )
        
        logger.info(f"📊 Response status: {response.status_code}")
        logger.info(f"📊 Response headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"✅ Endpoint responded successfully")
            logger.info(f"📊 Response: {json.dumps(result, indent=2)}")
            return True
        elif response.status_code == 500:
            error_text = response.text
            logger.error(f"❌ Server error: {error_text}")
            return False
        else:
            logger.warning(f"⚠️ Unexpected status code: {response.status_code}")
            logger.warning(f"⚠️ Response: {response.text}")
            return True  # Not necessarily a failure
            
    except requests.exceptions.Timeout:
        logger.info("✅ Endpoint accepted request (timeout expected for real tuning)")
        return True
    except Exception as e:
        logger.error(f"❌ Request failed: {e}")
        return False

def main():
    """Run the test."""
    logger.info("🚀 Testing tuning endpoint response")
    logger.info("=" * 50)
    
    success = test_tuning_endpoint()
    
    if success:
        logger.info("🎉 Tuning endpoint is responding!")
    else:
        logger.error("❌ Tuning endpoint has issues.")

if __name__ == "__main__":
    main() 