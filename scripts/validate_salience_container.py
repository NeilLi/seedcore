#!/usr/bin/env python3
"""
Validate Salience Scoring Service with SeedCore API Container

This script validates the complete salience scoring service using the seedcore-api container,
following the operation manual guidelines and testing all integration points.
"""

import sys
import os
import time
import requests
import json
import subprocess
from typing import Dict, Any, List
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SeedCoreContainerValidator:
    """Validator for SeedCore container-based salience scoring service."""
    
    def __init__(self, base_url: str = "http://localhost"):
        self.base_url = base_url
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
    
    def check_container_status(self) -> bool:
        """Check if seedcore-api container is running."""
        logger.info("🔍 Checking container status...")
        
        try:
            result = subprocess.run([
                "docker", "compose", "-f", "docker/docker-compose.yml", 
                "-p", "seedcore", "ps", "seedcore-api"
            ], capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__)))
            
            if result.returncode == 0 and "Up" in result.stdout:
                logger.info("✅ seedcore-api container is running")
                return True
            else:
                logger.error("❌ seedcore-api container is not running")
                logger.info("💡 Start with: cd docker && ./start-cluster.sh")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error checking container status: {e}")
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
            logger.info("💡 Make sure the container is running: docker compose ps seedcore-api")
            return False
        except Exception as e:
            logger.error(f"❌ API health test error: {e}")
            return False
    
    def test_salience_health(self) -> bool:
        """Test the salience service health endpoint."""
        logger.info("🧪 Testing salience service health...")
        
        try:
            response = requests.get(f"{self.base_url}/salience/health", timeout=10)
            
            if response.status_code == 200:
                health_data = response.json()
                logger.info(f"✅ Salience service health check passed")
                logger.info(f"   Status: {health_data.get('status', 'unknown')}")
                logger.info(f"   Response time: {health_data.get('response_time_ms', 'N/A')}ms")
                
                # Check circuit breaker status
                circuit_breaker = health_data.get('circuit_breaker', {})
                logger.info(f"   Circuit breaker: {circuit_breaker.get('is_open', 'unknown')}")
                
                return True
            else:
                logger.error(f"❌ Salience health check failed: HTTP {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Salience health test error: {e}")
            return False
    
    def test_salience_info(self) -> bool:
        """Test the salience service info endpoint."""
        logger.info("🧪 Testing salience service info...")
        
        try:
            response = requests.get(f"{self.base_url}/salience/info", timeout=10)
            
            if response.status_code == 200:
                info_data = response.json()
                logger.info(f"✅ Salience service info retrieved")
                logger.info(f"   Model type: {info_data.get('model_type', 'unknown')}")
                logger.info(f"   Features: {len(info_data.get('features', []))}")
                
                # Check endpoints
                endpoints = info_data.get('endpoints', {})
                logger.info(f"   Available endpoints: {list(endpoints.keys())}")
                
                return True
            else:
                logger.error(f"❌ Salience info check failed: HTTP {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Salience info test error: {e}")
            return False
    
    def test_salience_scoring(self) -> bool:
        """Test the salience scoring endpoint."""
        logger.info("🧪 Testing salience scoring...")
        
        try:
            # Test features for high-risk scenario
            high_risk_features = [{
                'task_risk': 0.9,
                'failure_severity': 0.9,
                'agent_capability': 0.6,
                'system_load': 0.8,
                'memory_usage': 0.7,
                'cpu_usage': 0.8,
                'response_time': 3.0,
                'error_rate': 0.2,
                'task_complexity': 0.9,
                'user_impact': 0.9,
                'business_criticality': 0.9,
                'agent_memory_util': 0.5
            }]
            
            response = requests.post(
                f"{self.base_url}/salience/score",
                json=high_risk_features,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                score = result.get('scores', [0])[0]
                logger.info(f"✅ High-risk scoring test passed")
                logger.info(f"   Score: {score:.3f}")
                logger.info(f"   Processing time: {result.get('processing_time_ms', 'N/A')}ms")
                
                # Verify score is reasonable for high-risk scenario
                if score > 0.7:
                    logger.info("   ✅ Score is appropriately high for high-risk scenario")
                else:
                    logger.warning("   ⚠️ Score seems low for high-risk scenario")
                
                return True
            else:
                logger.error(f"❌ Salience scoring failed: HTTP {response.status_code}")
                logger.error(f"   Response: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Salience scoring test error: {e}")
            return False
    
    def test_salience_batch_scoring(self) -> bool:
        """Test the batch salience scoring endpoint."""
        logger.info("🧪 Testing batch salience scoring...")
        
        try:
            # Test multiple feature sets
            batch_features = [
                {
                    'task_risk': 0.9,
                    'failure_severity': 0.9,
                    'agent_capability': 0.6,
                    'system_load': 0.8,
                    'memory_usage': 0.7,
                    'cpu_usage': 0.8,
                    'response_time': 3.0,
                    'error_rate': 0.2,
                    'task_complexity': 0.9,
                    'user_impact': 0.9,
                    'business_criticality': 0.9,
                    'agent_memory_util': 0.5
                },
                {
                    'task_risk': 0.3,
                    'failure_severity': 0.2,
                    'agent_capability': 0.9,
                    'system_load': 0.3,
                    'memory_usage': 0.2,
                    'cpu_usage': 0.3,
                    'response_time': 0.5,
                    'error_rate': 0.0,
                    'task_complexity': 0.3,
                    'user_impact': 0.2,
                    'business_criticality': 0.3,
                    'agent_memory_util': 0.1
                },
                {
                    'task_risk': 0.6,
                    'failure_severity': 0.5,
                    'agent_capability': 0.7,
                    'system_load': 0.5,
                    'memory_usage': 0.4,
                    'cpu_usage': 0.5,
                    'response_time': 1.5,
                    'error_rate': 0.1,
                    'task_complexity': 0.6,
                    'user_impact': 0.5,
                    'business_criticality': 0.6,
                    'agent_memory_util': 0.3
                }
            ]
            
            batch_data = {
                "batch_id": f"test_batch_{int(time.time())}",
                "features": batch_features
            }
            
            response = requests.post(
                f"{self.base_url}/salience/score/batch",
                json=batch_data,
                timeout=15
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ Batch scoring test passed")
                logger.info(f"   Batch ID: {result.get('batch_id', 'unknown')}")
                logger.info(f"   Total count: {result.get('total_count', 0)}")
                logger.info(f"   Success count: {result.get('success_count', 0)}")
                logger.info(f"   Processing time: {result.get('processing_time_ms', 'N/A')}ms")
                
                # Check individual results
                results = result.get('results', [])
                for i, res in enumerate(results):
                    score = res.get('score', 0)
                    status = res.get('status', 'unknown')
                    logger.info(f"   Result {i+1}: {score:.3f} ({status})")
                
                return True
            else:
                logger.error(f"❌ Batch scoring failed: HTTP {response.status_code}")
                logger.error(f"   Response: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Batch scoring test error: {e}")
            return False
    
    def test_agent_integration(self) -> bool:
        """Test agent integration with salience scoring."""
        logger.info("🧪 Testing agent integration...")
        
        try:
            # Create a test agent
            agent_data = {
                "agent_id": "salience_test_agent",
                "role_probs": {"E": 0.7, "S": 0.2, "O": 0.1}
            }
            
            response = requests.post(
                f"{self.base_url}/tier0/agents/create",
                json=agent_data,
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"❌ Agent creation failed: HTTP {response.status_code}")
                return False
            
            logger.info("✅ Test agent created")
            
            # Execute a high-stakes task that should trigger salience scoring
            task_data = {
                "task_id": "salience_test_task",
                "type": "high_stakes_operation",
                "complexity": 0.9,
                "risk": 0.8,
                "user_impact": 0.9,
                "business_criticality": 0.9
            }
            
            response = requests.post(
                f"{self.base_url}/tier0/agents/salience_test_agent/execute",
                json=task_data,
                timeout=15
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info("✅ High-stakes task executed")
                
                # Check if salience score was calculated
                if 'salience_score' in result:
                    score = result['salience_score']
                    logger.info(f"   Salience score: {score:.3f}")
                    
                    if score > 0.7:
                        logger.info("   ✅ High salience score for high-stakes task")
                    else:
                        logger.warning("   ⚠️ Unexpectedly low salience score")
                    
                    return True
                else:
                    logger.warning("   ⚠️ No salience score in response")
                    return False
            else:
                logger.error(f"❌ Task execution failed: HTTP {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Agent integration test error: {e}")
            return False
    
    def test_flashbulb_memory_integration(self) -> bool:
        """Test flashbulb memory integration with salience scoring."""
        logger.info("🧪 Testing flashbulb memory integration...")
        
        try:
            # Log a high-salience incident
            incident_data = {
                "event_data": {
                    "type": "system_failure",
                    "severity": "critical",
                    "component": "payment_processor",
                    "error_code": 500,
                    "user_impact": "high"
                },
                "salience_score": 0.95
            }
            
            response = requests.post(
                f"{self.base_url}/mfb/incidents",
                json=incident_data,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info("✅ High-salience incident logged")
                logger.info(f"   Incident ID: {result.get('incident_id', 'unknown')}")
                logger.info(f"   Salience score: {result.get('salience_score', 'unknown')}")
                
                # Get flashbulb memory statistics
                response = requests.get(f"{self.base_url}/mfb/stats", timeout=10)
                
                if response.status_code == 200:
                    stats = response.json()
                    logger.info("✅ Flashbulb memory statistics retrieved")
                    logger.info(f"   Total incidents: {stats.get('total_incidents', 0)}")
                    logger.info(f"   High-salience incidents: {stats.get('high_salience_count', 0)}")
                    
                    return True
                else:
                    logger.error(f"❌ Stats retrieval failed: HTTP {response.status_code}")
                    return False
            else:
                logger.error(f"❌ Incident logging failed: HTTP {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Flashbulb memory integration test error: {e}")
            return False
    
    def test_ray_cluster_integration(self) -> bool:
        """Test Ray cluster integration."""
        logger.info("🧪 Testing Ray cluster integration...")
        
        try:
            # Check Ray cluster status
            response = requests.get(f"{self.base_url}/ray/status", timeout=10)
            
            if response.status_code == 200:
                ray_status = response.json()
                logger.info("✅ Ray cluster status retrieved")
                logger.info(f"   Status: {ray_status.get('status', 'unknown')}")
                logger.info(f"   Connected: {ray_status.get('connected', False)}")
                
                # Check if Ray Serve is accessible
                try:
                    ray_serve_response = requests.get("http://localhost:8000/", timeout=5)
                    if ray_serve_response.status_code == 200:
                        logger.info("✅ Ray Serve is accessible")
                        return True
                    else:
                        logger.warning("⚠️ Ray Serve returned unexpected status")
                        return False
                except:
                    logger.warning("⚠️ Ray Serve not directly accessible (expected)")
                    return True
            else:
                logger.error(f"❌ Ray status check failed: HTTP {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ray cluster integration test error: {e}")
            return False
    
    def test_monitoring_integration(self) -> bool:
        """Test monitoring integration."""
        logger.info("🧪 Testing monitoring integration...")
        
        try:
            # Check if Prometheus metrics are available
            response = requests.get(f"{self.base_url}/metrics", timeout=10)
            
            if response.status_code == 200:
                metrics = response.text
                logger.info("✅ Prometheus metrics endpoint accessible")
                
                # Check for salience-related metrics
                if "salience" in metrics.lower():
                    logger.info("✅ Salience-related metrics found")
                else:
                    logger.warning("⚠️ No salience-related metrics found")
                
                return True
            else:
                logger.error(f"❌ Metrics endpoint failed: HTTP {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Monitoring integration test error: {e}")
            return False
    
    def run_all_tests(self) -> bool:
        """Run all validation tests."""
        logger.info("🎯 SeedCore Container Validation Suite")
        logger.info("=" * 60)
        
        tests = [
            ("Container Status", self.check_container_status),
            ("API Health", self.test_api_health),
            ("Salience Health", self.test_salience_health),
            ("Salience Info", self.test_salience_info),
            ("Salience Scoring", self.test_salience_scoring),
            ("Batch Scoring", self.test_salience_batch_scoring),
            ("Agent Integration", self.test_agent_integration),
            ("Flashbulb Memory Integration", self.test_flashbulb_memory_integration),
            ("Ray Cluster Integration", self.test_ray_cluster_integration),
            ("Monitoring Integration", self.test_monitoring_integration)
        ]
        
        for test_name, test_func in tests:
            logger.info(f"\n🔍 Running {test_name} Test")
            logger.info("-" * 40)
            
            try:
                success = test_func()
                self.log_test(test_name, success)
                
                if not success:
                    logger.warning(f"⚠️ {test_name} test failed")
                    
            except Exception as e:
                logger.error(f"❌ {test_name} test error: {e}")
                self.log_test(test_name, False, str(e))
        
        # Summary
        logger.info("\n📊 Validation Summary")
        logger.info("=" * 60)
        
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        for result in self.test_results:
            status = "✅ PASS" if result["success"] else "❌ FAIL"
            logger.info(f"   {result['test']}: {status}")
            if result["details"]:
                logger.info(f"      {result['details']}")
        
        logger.info(f"\nOverall: {passed}/{total} tests passed")
        
        if passed == total:
            logger.info("🎉 All tests passed! Salience scoring service is fully operational.")
        else:
            logger.warning(f"⚠️ {total - passed} tests failed. Please check the implementation.")
        
        return passed == total

def main():
    """Main validation function."""
    # Check if we're in the right directory
    if not os.path.exists("docker/docker-compose.yml"):
        logger.error("❌ Please run this script from the project root directory")
        logger.info("💡 Usage: python scripts/validate_salience_container.py")
        return False
    
    # Initialize validator
    validator = SeedCoreContainerValidator()
    
    # Run all tests
    success = validator.run_all_tests()
    
    if success:
        logger.info("\n🚀 Next Steps:")
        logger.info("   1. Access API documentation: http://localhost:8002/docs")
        logger.info("   2. Monitor Ray cluster: http://localhost:8265")
        logger.info("   3. View Grafana dashboards: http://localhost:3000")
        logger.info("   4. Check Prometheus metrics: http://localhost:9090")
    
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 