#!/usr/bin/env python3
"""
Simple test script to verify organism connection and task processing.
"""

import os
import sys
import asyncio
import logging
from typing import Dict, Any

# Add project root to path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_organism_connection():
    """Test basic organism connection and task processing."""
    try:
        import ray
        from ray import serve
        
        logger.info("🔍 Testing organism connection...")
        
        # Get the organism handle
        coord_handle = serve.get_deployment_handle("OrganismManager", app_name="organism")
        logger.info(f"✅ Got organism handle: {coord_handle}")
        
        # Test health check
        logger.info("🏥 Testing health check...")
        health_result = await coord_handle.health.remote()
        logger.info(f"✅ Health check result: {health_result}")
        
        # Test a simple task
        logger.info("🚀 Testing simple task...")
        test_task = {
            "type": "general_query",
            "params": {},
            "description": "Test connection",
            "domain": "test",
            "drift_score": 0.1
        }
        
        logger.info(f"📤 Sending test task: {test_task}")
        result = await coord_handle.handle_incoming_task.remote(test_task)
        logger.info(f"✅ Test task result: {result}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        logger.exception("Full traceback:")
        return False

async def main():
    """Run the test."""
    logger.info("🚀 Starting organism connection test...")
    
    success = await test_organism_connection()
    
    if success:
        logger.info("🎉 Test passed! Organism connection is working.")
    else:
        logger.error("❌ Test failed! Check the logs above for details.")

if __name__ == "__main__":
    asyncio.run(main())
