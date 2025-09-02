#!/usr/bin/env python3
"""
Diagnostic script to check organism service connection and status.
This script helps diagnose why tasks are getting stuck in retry loops.
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

async def check_ray_connection():
    """Check if Ray is properly initialized and connected."""
    try:
        import ray
        logger.info("🔍 Checking Ray connection...")
        
        if not ray.is_initialized():
            logger.error("❌ Ray is not initialized")
            return False
            
        # Get Ray cluster info
        cluster_resources = ray.cluster_resources()
        logger.info(f"✅ Ray cluster resources: {cluster_resources}")
        
        # Check namespace
        namespace = os.getenv("RAY_NAMESPACE", "seedcore-dev")
        logger.info(f"✅ Ray namespace: {namespace}")
        
        return True
    except Exception as e:
        logger.error(f"❌ Ray connection check failed: {e}")
        return False

async def check_serve_deployments():
    """Check available Ray Serve deployments."""
    try:
        from ray import serve
        logger.info("🔍 Checking Ray Serve deployments...")
        
        deployments = serve.list_deployments()
        logger.info(f"✅ Available deployments: {list(deployments.keys())}")
        
        # Check if organism app exists
        apps = serve.list_applications()
        logger.info(f"✅ Available applications: {list(apps.keys())}")
        
        if "organism" not in apps:
            logger.error("❌ 'organism' application not found in Serve deployments")
            return False
            
        logger.info("✅ 'organism' application found")
        return True
    except Exception as e:
        logger.error(f"❌ Serve deployments check failed: {e}")
        return False

async def check_organism_manager_handle():
    """Check if we can get a handle to the OrganismManager."""
    try:
        from ray import serve
        logger.info("🔍 Getting OrganismManager handle...")
        
        coord_handle = serve.get_deployment_handle("OrganismManager", app_name="organism")
        logger.info(f"✅ Successfully got OrganismManager handle: {coord_handle}")
        
        # Test health endpoint
        logger.info("🏥 Testing health endpoint...")
        health_result = await coord_handle.health.remote()
        logger.info(f"✅ Health check result: {health_result}")
        
        return True
    except Exception as e:
        logger.error(f"❌ OrganismManager handle check failed: {e}")
        return False

async def check_organism_status():
    """Check organism initialization status."""
    try:
        from ray import serve
        logger.info("🔍 Checking organism status...")
        
        coord_handle = serve.get_deployment_handle("OrganismManager", app_name="organism")
        
        # Check status endpoint
        status_result = await coord_handle.status.remote()
        logger.info(f"✅ Status check result: {status_result}")
        
        # Check organism status
        org_status_result = await coord_handle.get_organism_status.remote()
        logger.info(f"✅ Organism status result: {org_status_result}")
        
        return True
    except Exception as e:
        logger.error(f"❌ Organism status check failed: {e}")
        return False

async def test_task_processing():
    """Test if we can process a simple task."""
    try:
        from ray import serve
        logger.info("🔍 Testing task processing...")
        
        coord_handle = serve.get_deployment_handle("OrganismManager", app_name="organism")
        
        # Create a simple test task
        test_task = {
            "type": "general_query",
            "params": {},
            "description": "Test task for connection diagnosis",
            "domain": "test",
            "drift_score": 0.1
        }
        
        logger.info(f"📤 Sending test task: {test_task}")
        result = await coord_handle.handle_incoming_task.remote(test_task)
        logger.info(f"✅ Test task result: {result}")
        
        return True
    except Exception as e:
        logger.error(f"❌ Task processing test failed: {e}")
        return False

async def main():
    """Run all diagnostic checks."""
    logger.info("🚀 Starting organism connection diagnostics...")
    
    checks = [
        ("Ray Connection", check_ray_connection),
        ("Serve Deployments", check_serve_deployments),
        ("OrganismManager Handle", check_organism_manager_handle),
        ("Organism Status", check_organism_status),
        ("Task Processing", test_task_processing),
    ]
    
    results = {}
    for name, check_func in checks:
        logger.info(f"\n{'='*50}")
        logger.info(f"Running check: {name}")
        logger.info(f"{'='*50}")
        
        try:
            result = await check_func()
            results[name] = result
            if result:
                logger.info(f"✅ {name}: PASSED")
            else:
                logger.error(f"❌ {name}: FAILED")
        except Exception as e:
            logger.error(f"❌ {name}: ERROR - {e}")
            results[name] = False
    
    # Summary
    logger.info(f"\n{'='*50}")
    logger.info("DIAGNOSTIC SUMMARY")
    logger.info(f"{'='*50}")
    
    passed = sum(1 for result in results.values() if result)
    total = len(results)
    
    for name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        logger.info(f"{name}: {status}")
    
    logger.info(f"\nOverall: {passed}/{total} checks passed")
    
    if passed == total:
        logger.info("🎉 All checks passed! Organism service should be working.")
    else:
        logger.error("⚠️ Some checks failed. Check the logs above for details.")
        
        # Provide troubleshooting suggestions
        logger.info("\n🔧 Troubleshooting suggestions:")
        if not results.get("Ray Connection", False):
            logger.info("- Check Ray cluster is running and accessible")
            logger.info("- Verify RAY_ADDRESS and RAY_NAMESPACE environment variables")
        if not results.get("Serve Deployments", False):
            logger.info("- Check if organism service is deployed")
            logger.info("- Run: python entrypoints/organism_entrypoint.py")
        if not results.get("OrganismManager Handle", False):
            logger.info("- Check if OrganismManager deployment exists in 'organism' app")
            logger.info("- Verify Serve deployment is healthy")
        if not results.get("Organism Status", False):
            logger.info("- Check if organism is properly initialized")
            logger.info("- Run organism initialization if needed")
        if not results.get("Task Processing", False):
            logger.info("- Check organism routing configuration")
            logger.info("- Verify organs and agents are available")

if __name__ == "__main__":
    asyncio.run(main())
