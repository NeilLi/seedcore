#!/usr/bin/env python3
"""
Debug script to test organ actors and identify the hanging issue.
"""

import asyncio
import ray
import logging
from pathlib import Path
import sys
import os

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from seedcore.organs.organism_manager import OrganismManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_organ_actors():
    """Test organ actors directly to identify the issue."""
    
    logger.info("🔍 Testing organ actors directly...")
    
    # Initialize Ray if not already done
    if not ray.is_initialized():
        # Get namespace from environment, default to "seedcore-dev" for consistency
        ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
        
        # Get Ray address from environment variables, with fallback to the actual service name
        # Note: RAY_HOST env var is set to 'seedcore-head-svc' but actual service is 'seedcore-svc-head-svc'
        ray_host = os.getenv("RAY_HOST", "seedcore-svc-head-svc")
        ray_port = os.getenv("RAY_PORT", "10001")
        ray_address = f"ray://{ray_host}:{ray_port}"
        
        print(f"🔗 Connecting to Ray at: {ray_address}")
        from seedcore.utils.ray_utils import ensure_ray_initialized
        if not ensure_ray_initialized(ray_address=ray_address, ray_namespace=ray_namespace):
            raise RuntimeError("Failed to connect to Ray cluster")
        logger.info("✅ Ray initialized")
    
    # Get the organism manager
    manager = OrganismManager()
    
    # Test getting existing organs
    logger.info("🔍 Testing organ retrieval...")
    try:
        cognitive_organ = ray.get_actor("cognitive_organ_1")
        logger.info("✅ Retrieved cognitive_organ_1")
        
        # Test a simple method call
        logger.info("🔍 Testing get_agent_handles method...")
        try:
            result = await asyncio.wait_for(
                cognitive_organ.get_agent_handles.remote(),
                timeout=5.0
            )
            logger.info(f"✅ get_agent_handles returned: {result}")
        except asyncio.TimeoutError:
            logger.error("❌ get_agent_handles timed out after 5 seconds")
        except Exception as e:
            logger.error(f"❌ get_agent_handles failed: {e}")
            
        # Test get_status method
        logger.info("🔍 Testing get_status method...")
        try:
            result = await asyncio.wait_for(
                cognitive_organ.get_status.remote(),
                timeout=5.0
            )
            logger.info(f"✅ get_status returned: {result}")
        except asyncio.TimeoutError:
            logger.error("❌ get_status timed out after 5 seconds")
        except Exception as e:
            logger.error(f"❌ get_status failed: {e}")
            
    except Exception as e:
        logger.error(f"❌ Failed to get cognitive_organ_1: {e}")
    
    # Test other organs
    for organ_name in ["actuator_organ_1", "utility_organ_1"]:
        logger.info(f"🔍 Testing {organ_name}...")
        try:
            organ = ray.get_actor(organ_name)
            logger.info(f"✅ Retrieved {organ_name}")
            
            # Test get_status
            try:
                result = await asyncio.wait_for(
                    organ.get_status.remote(),
                    timeout=5.0
                )
                logger.info(f"✅ {organ_name} get_status: {result}")
            except asyncio.TimeoutError:
                logger.error(f"❌ {organ_name} get_status timed out")
            except Exception as e:
                logger.error(f"❌ {organ_name} get_status failed: {e}")
                
        except Exception as e:
            logger.error(f"❌ Failed to get {organ_name}: {e}")

if __name__ == "__main__":
    asyncio.run(test_organ_actors()) 