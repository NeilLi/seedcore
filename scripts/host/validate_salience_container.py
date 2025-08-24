#!/usr/bin/env python3
"""
Validate Salience Scoring Service with SeedCore API (Kubernetes)

This script validates the complete salience scoring service running in Kubernetes,
following the operation manual guidelines and testing all integration points.
"""

import sys
import os
import time
import requests
import subprocess
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SeedCoreK8sValidator:
    """Validator for SeedCore salience scoring service running in Kubernetes."""
    
    def __init__(self, base_url: str = None, namespace: str = "seedcore-dev"):
        self.base_url = base_url or os.environ.get("SEEDCORE_API_URL", "http://localhost:8002")
        self.namespace = namespace
        self.test_results = []
        
    def log_test(self, test_name: str, success: bool, details: str = ""):
        """Log test results."""
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} {test_name}")
        if details:
            logger.info(f"   {details}")
        
        self.test_results.append({
            "test": test_name,
            "success": success,
            "details": details
        })
    
    def check_pod_status(self) -> bool:
        """Check if seedcore-api pod is running in Kubernetes."""
        logger.info("🔍 Checking seedcore-api pod status in Kubernetes...")
        
        try:
            result = subprocess.run(
                ["kubectl", "-n", self.namespace, "get", "pods", "-l", "app=seedcore-api", "-o", "jsonpath={.items[*].status.phase}"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                statuses = result.stdout.strip().split()
                if statuses and all(s == "Running" for s in statuses):
                    logger.info("✅ seedcore-api pod(s) are running")
                    return True
                else:
                    logger.error(f"❌ seedcore-api pod(s) not running: {statuses}")
                    return False
            else:
                logger.error(f"❌ kubectl error: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"❌ Error checking Kubernetes pod status: {e}")
            return False
    
    def test_api_health(self) -> bool:
        """Test the main API health endpoint."""
        logger.info("🧪 Testing API health...")
        
        try:
            response = requests.get(f"{self.base_url}/health", timeout=10)
            if response.status_code == 200:
                health_data = response.json()
                logger.info(f"✅ API health check passed")
                logger.info(f"   Status: {health_data.get('status', 'unknown')}")
                return True
            else:
                logger.error(f"❌ API health check failed: HTTP {response.status_code}")
                return False
        except requests.exceptions.ConnectionError:
            logger.error("❌ Could not connect to API server")
            logger.info(f"💡 Check if service is exposed: kubectl -n {self.namespace} get svc seedcore-api")
            return False
        except Exception as e:
            logger.error(f"❌ API health test error: {e}")
            return False

    # keep all your existing salience, batch scoring, agent, flashbulb, ray, monitoring tests unchanged...
    # just like in your original script, they work as long as base_url is correct

    def run_all_tests(self) -> bool:
        """Run all validation tests."""
        logger.info("🎯 SeedCore Kubernetes Validation Suite")
        logger.info("=" * 60)
        
        tests = [
            ("Pod Status", self.check_pod_status),
            ("API Health", self.test_api_health),
            # add the other tests here (unchanged from your version)
        ]
        
        for test_name, test_func in tests:
            logger.info(f"\n🔍 Running {test_name} Test")
            logger.info("-" * 40)
            try:
                success = test_func()
                self.log_test(test_name, success)
            except Exception as e:
                logger.error(f"❌ {test_name} test error: {e}")
                self.log_test(test_name, False, str(e))
        
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        logger.info(f"\n📊 Validation Summary: {passed}/{total} passed")
        return passed == total

def main():
    validator = SeedCoreK8sValidator()
    success = validator.run_all_tests()
    return success

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
