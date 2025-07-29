#!/usr/bin/env python3
"""
Deploy SeedCore API to Ray Serve.
This script deploys the SeedCore API as a Ray Serve application.
"""

import sys
import os
import logging
from pathlib import Path

# Add the src directory to the Python path
project_root = Path(__file__).parent.parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

from seedcore.serve.app import deploy_seedcore_api, undeploy_seedcore_api

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Main deployment function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Deploy SeedCore API to Ray Serve")
    parser.add_argument(
        "--action", 
        choices=["deploy", "undeploy", "status"], 
        default="deploy",
        help="Action to perform (default: deploy)"
    )
    
    args = parser.parse_args()
    
    if args.action == "deploy":
        logger.info("🚀 Starting SeedCore API Ray Serve deployment...")
        success = deploy_seedcore_api()
        if success:
            logger.info("✅ Deployment completed successfully!")
            logger.info("📊 Check the Ray Serve dashboard at: http://localhost:8265/#/serve")
        else:
            logger.error("❌ Deployment failed!")
            sys.exit(1)
    
    elif args.action == "undeploy":
        logger.info("🛑 Undeploying SeedCore API from Ray Serve...")
        success = undeploy_seedcore_api()
        if success:
            logger.info("✅ Undeployment completed successfully!")
        else:
            logger.error("❌ Undeployment failed!")
            sys.exit(1)
    
    elif args.action == "status":
        logger.info("📊 Checking Ray Serve status...")
        try:
            from ray import serve
            applications = serve.list_deployments()
            if applications:
                logger.info("✅ Active Ray Serve applications:")
                for name, app in applications.items():
                    logger.info(f"   - {name}: {app}")
            else:
                logger.info("ℹ️ No active Ray Serve applications")
        except Exception as e:
            logger.error(f"❌ Error checking status: {e}")

if __name__ == "__main__":
    main() 