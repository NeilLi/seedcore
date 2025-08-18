#!/usr/bin/env python3
"""
Fix local Ray connection issues for SeedCore development.

This script helps resolve the common issues when running SeedCore locally:
1. Sets correct environment variables for local development
2. Tests Ray connection
3. Verifies namespace consistency
4. Provides debugging information

Usage:
    python3 scripts/fix_local_ray_connection.py
"""

import os
import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def set_local_environment():
    """Set environment variables for local development."""
    logger.info("🔧 Setting environment variables for local development...")
    
    # Set Ray connection to localhost (port-forwarded)
    os.environ["RAY_HOST"] = "localhost"
    os.environ["RAY_PORT"] = "10001"
    os.environ["RAY_ADDRESS"] = "ray://localhost:10001"
    
    # Set namespace
    os.environ["RAY_NAMESPACE"] = "seedcore-dev"
    os.environ["SEEDCORE_NS"] = "seedcore-dev"
    
    logger.info("✅ Environment variables set:")
    logger.info(f"   RAY_HOST: {os.getenv('RAY_HOST')}")
    logger.info(f"   RAY_PORT: {os.getenv('RAY_PORT')}")
    logger.info(f"   RAY_ADDRESS: {os.getenv('RAY_ADDRESS')}")
    logger.info(f"   RAY_NAMESPACE: {os.getenv('RAY_NAMESPACE')}")
    logger.info(f"   SEEDCORE_NS: {os.getenv('SEEDCORE_NS')}")

def test_ray_connection():
    """Test Ray connection with the new environment."""
    logger.info("🧪 Testing Ray connection...")
    
    try:
        import ray
        
        # Try to connect to Ray
        ray_address = os.getenv("RAY_ADDRESS", "ray://localhost:10001")
        namespace = os.getenv("RAY_NAMESPACE", "seedcore-dev")
        
        logger.info(f"🔗 Attempting to connect to Ray at: {ray_address}")
        logger.info(f"🏷️ Using namespace: {namespace}")
        
        ray.init(address=ray_address, namespace=namespace, ignore_reinit_error=True)
        
        # Check runtime context
        runtime_context = ray.get_runtime_context()
        current_namespace = getattr(runtime_context, 'namespace', 'unknown')
        
        logger.info(f"✅ Ray connected successfully!")
        logger.info(f"   Current namespace: {current_namespace}")
        logger.info(f"   Ray initialized: {ray.is_initialized()}")
        
        # Test basic Ray functionality
        try:
            from ray.util.state import list_actors
            actors = list_actors()
            logger.info(f"✅ Ray state API working - found {len(actors)} actors")
        except Exception as e:
            logger.warning(f"⚠️ Ray state API not working: {e}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to connect to Ray: {e}")
        return False

def check_port_forward():
    """Check if port-forwarding is working."""
    logger.info("🔍 Checking port-forward status...")
    
    import socket
    
    host = os.getenv("RAY_HOST", "localhost")
    port = int(os.getenv("RAY_PORT", "10001"))
    
    try:
        with socket.create_connection((host, port), timeout=5):
            logger.info(f"✅ Port {port} is accessible on {host}")
            return True
    except Exception as e:
        logger.error(f"❌ Port {port} is not accessible on {host}: {e}")
        logger.error("💡 Make sure to run: kubectl -n seedcore-dev port-forward svc/seedcore-svc-head-svc 10001:10001")
        return False

def main():
    """Main function to fix local Ray connection."""
    logger.info("🚀 SeedCore Local Ray Connection Fix")
    logger.info("=" * 50)
    
    # Step 1: Set environment variables
    set_local_environment()
    
    # Step 2: Check port-forward
    if not check_port_forward():
        logger.error("❌ Port-forward not working. Please fix this first.")
        return False
    
    # Step 3: Test Ray connection
    if test_ray_connection():
        logger.info("🎉 Ray connection fixed successfully!")
        logger.info("💡 You can now run your SeedCore application locally.")
        return True
    else:
        logger.error("❌ Failed to fix Ray connection.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
