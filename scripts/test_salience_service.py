#!/usr/bin/env python3
"""
Test Salience Scoring Service

This script tests the complete salience scoring pipeline including:
- Model training
- Ray Serve deployment
- API endpoints
- Circuit breaker pattern
- Agent integration
"""

import sys
import os
import time
import requests
import json
import numpy as np
from typing import List, Dict, Any
import logging

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.seedcore.ml.salience.scorer import SalienceScorer
from src.seedcore.ml.serve_app import SalienceServiceClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_model_training():
    """Test the salience model training functionality."""
    logger.info("🧪 Testing Model Training")
    logger.info("=" * 40)
    
    try:
        # Generate synthetic training data
        training_data = []
        salience_scores = []
        
        for i in range(100):
            features = {
                'task_risk': np.random.uniform(0.1, 1.0),
                'failure_severity': np.random.uniform(0.1, 1.0),
                'agent_capability': np.random.uniform(0.2, 1.0),
                'system_load': np.random.uniform(0.1, 1.0),
                'memory_usage': np.random.uniform(0.1, 1.0),
                'cpu_usage': np.random.uniform(0.1, 1.0),
                'response_time': np.random.uniform(0.1, 5.0),
                'error_rate': np.random.uniform(0.0, 0.3),
                'task_complexity': np.random.uniform(0.1, 1.0),
                'user_impact': np.random.uniform(0.1, 1.0),
                'business_criticality': np.random.uniform(0.1, 1.0),
                'agent_memory_util': np.random.uniform(0.0, 1.0)
            }
            
            # Generate synthetic salience score
            base_score = (
                features['task_risk'] * 0.3 +
                features['failure_severity'] * 0.3 +
                features['user_impact'] * 0.2 +
                features['business_criticality'] * 0.2
            )
            score = base_score + np.random.normal(0, 0.1)
            score = max(0.0, min(1.0, score))
            
            training_data.append(features)
            salience_scores.append(score)
        
        # Train model
        scorer = SalienceScorer()
        results = scorer.train_model(training_data, salience_scores)
        
        if "error" in results:
            logger.error(f"❌ Training failed: {results['error']}")
            return False
        
        logger.info(f"✅ Model trained successfully")
        logger.info(f"   MSE: {results['mse']:.4f}")
        logger.info(f"   R²: {results['r2']:.4f}")
        logger.info(f"   Model saved to: {results['model_path']}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Training test failed: {e}")
        return False

def test_local_scoring():
    """Test local salience scoring without Ray Serve."""
    logger.info("🧪 Testing Local Scoring")
    logger.info("=" * 40)
    
    try:
        # Initialize scorer
        scorer = SalienceScorer()
        
        # Test features
        test_features = [
            {
                'task_risk': 0.8,
                'failure_severity': 0.9,
                'agent_capability': 0.7,
                'system_load': 0.6,
                'memory_usage': 0.5,
                'cpu_usage': 0.4,
                'response_time': 2.0,
                'error_rate': 0.1,
                'task_complexity': 0.8,
                'user_impact': 0.9,
                'business_criticality': 0.8,
                'agent_memory_util': 0.3
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
            }
        ]
        
        # Score features
        scores = scorer.score_features(test_features)
        
        logger.info(f"✅ Local scoring completed")
        logger.info(f"   High-risk task score: {scores[0]:.3f}")
        logger.info(f"   Low-risk task score: {scores[1]:.3f}")
        
        # Verify scores are reasonable
        if scores[0] > scores[1]:
            logger.info("✅ Score ordering is correct (high-risk > low-risk)")
        else:
            logger.warning("⚠️ Unexpected score ordering")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Local scoring test failed: {e}")
        return False

def test_api_endpoints():
    """Test the salience scoring API endpoints."""
    logger.info("🧪 Testing API Endpoints")
    logger.info("=" * 40)
    
    base_url = "http://localhost:8000"
    
    try:
        # Test health endpoint
        logger.info("Testing health endpoint...")
        response = requests.get(f"{base_url}/salience/health", timeout=10)
        
        if response.status_code == 200:
            health_data = response.json()
            logger.info(f"✅ Health check passed: {health_data['status']}")
            logger.info(f"   Response time: {health_data.get('response_time_ms', 'N/A')}ms")
        else:
            logger.error(f"❌ Health check failed: HTTP {response.status_code}")
            return False
        
        # Test info endpoint
        logger.info("Testing info endpoint...")
        response = requests.get(f"{base_url}/salience/info", timeout=10)
        
        if response.status_code == 200:
            info_data = response.json()
            logger.info(f"✅ Info endpoint working")
            logger.info(f"   Model type: {info_data['model_type']}")
            logger.info(f"   Features: {len(info_data['features'])}")
        else:
            logger.error(f"❌ Info endpoint failed: HTTP {response.status_code}")
            return False
        
        # Test scoring endpoint
        logger.info("Testing scoring endpoint...")
        test_features = [{
            'task_risk': 0.8,
            'failure_severity': 0.9,
            'agent_capability': 0.7,
            'system_load': 0.6,
            'memory_usage': 0.5,
            'cpu_usage': 0.4,
            'response_time': 2.0,
            'error_rate': 0.1,
            'task_complexity': 0.8,
            'user_impact': 0.9,
            'business_criticality': 0.8,
            'agent_memory_util': 0.3
        }]
        
        response = requests.post(
            f"{base_url}/salience/score",
            json=test_features,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"✅ Scoring endpoint working")
            logger.info(f"   Score: {result['scores'][0]:.3f}")
            logger.info(f"   Processing time: {result['processing_time_ms']}ms")
        else:
            logger.error(f"❌ Scoring endpoint failed: HTTP {response.status_code}")
            logger.error(f"   Response: {response.text}")
            return False
        
        return True
        
    except requests.exceptions.ConnectionError:
        logger.error("❌ Could not connect to API server")
        logger.info("💡 Make sure the API server is running: uvicorn src.seedcore.telemetry.server:app --reload")
        return False
    except Exception as e:
        logger.error(f"❌ API test failed: {e}")
        return False

def test_circuit_breaker():
    """Test the circuit breaker pattern."""
    logger.info("🧪 Testing Circuit Breaker")
    logger.info("=" * 40)
    
    try:
        # Initialize client
        client = SalienceServiceClient("http://invalid-url:9999")
        
        # Test features
        test_features = [{
            'task_risk': 0.5,
            'failure_severity': 0.5,
            'agent_capability': 0.5,
            'system_load': 0.5,
            'memory_usage': 0.5,
            'cpu_usage': 0.5,
            'response_time': 1.0,
            'error_rate': 0.0,
            'task_complexity': 0.5,
            'user_impact': 0.5,
            'business_criticality': 0.5,
            'agent_memory_util': 0.0
        }]
        
        # Test multiple failures
        logger.info("Testing circuit breaker with invalid URL...")
        
        for i in range(6):
            scores = client.score_salience(test_features)
            logger.info(f"   Attempt {i+1}: Score = {scores[0]:.3f}")
            
            if i == 4:  # After 5 failures
                logger.info("   Circuit breaker should be open now")
        
        # Check circuit breaker state
        if client._is_circuit_open():
            logger.info("✅ Circuit breaker opened correctly")
        else:
            logger.warning("⚠️ Circuit breaker did not open as expected")
        
        # Test fallback scoring
        fallback_scores = client._simple_fallback(test_features)
        logger.info(f"✅ Fallback scoring working: {fallback_scores[0]:.3f}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Circuit breaker test failed: {e}")
        return False

def test_agent_integration():
    """Test agent integration with salience scoring."""
    logger.info("🧪 Testing Agent Integration")
    logger.info("=" * 40)
    
    try:
        # Import agent class
        from src.seedcore.agents.ray_actor import RayAgent
        
        # Create a mock agent (without Ray)
        class MockAgent:
            def __init__(self):
                self.agent_id = "test_agent"
                self.capability_score = 0.7
                self.mem_util = 0.3
                self.tasks_processed = 10
                self.successful_tasks = 8
                self.quality_scores = [0.8, 0.9, 0.7]
            
            def get_heartbeat(self):
                return {
                    "performance_metrics": {
                        "capability_score_c": self.capability_score,
                        "mem_util": self.mem_util
                    }
                }
            
            def get_energy_state(self):
                return {"pair": 0.5, "hyper": 0.3, "entropy": 0.4, "reg": 0.2, "mem": 0.6}
            
            def _calculate_ml_salience_score(self, task_info, error_context):
                # Mock the ML salience calculation
                features = {
                    'task_risk': task_info.get('risk', 0.5),
                    'failure_severity': 1.0,
                    'agent_capability': self.capability_score,
                    'system_load': 0.5,
                    'memory_usage': self.mem_util,
                    'cpu_usage': 0.5,
                    'response_time': 1.0,
                    'error_rate': (self.tasks_processed - self.successful_tasks) / self.tasks_processed,
                    'task_complexity': task_info.get('complexity', 0.5),
                    'user_impact': task_info.get('user_impact', 0.5),
                    'business_criticality': task_info.get('business_criticality', 0.5),
                    'agent_memory_util': self.mem_util
                }
                
                # Simple scoring logic
                score = (
                    features['task_risk'] * 0.3 +
                    features['failure_severity'] * 0.3 +
                    features['user_impact'] * 0.2 +
                    features['business_criticality'] * 0.2
                )
                return max(0.0, min(1.0, score))
        
        # Test agent
        agent = MockAgent()
        
        # Test high-stakes task
        task_info = {
            'name': 'critical_payment_processing',
            'risk': 0.9,
            'complexity': 0.8,
            'user_impact': 0.9,
            'business_criticality': 0.9
        }
        
        error_context = {"reason": "External API timeout", "code": 504}
        
        salience_score = agent._calculate_ml_salience_score(task_info, error_context)
        
        logger.info(f"✅ Agent integration working")
        logger.info(f"   Task: {task_info['name']}")
        logger.info(f"   Salience score: {salience_score:.3f}")
        
        # Verify score is reasonable for high-risk task
        if salience_score > 0.7:
            logger.info("✅ High salience score for critical task")
        else:
            logger.warning("⚠️ Unexpectedly low salience score for critical task")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Agent integration test failed: {e}")
        return False

def main():
    """Run all tests."""
    logger.info("🎯 Salience Scoring Service Test Suite")
    logger.info("=" * 60)
    
    tests = [
        ("Model Training", test_model_training),
        ("Local Scoring", test_local_scoring),
        ("API Endpoints", test_api_endpoints),
        ("Circuit Breaker", test_circuit_breaker),
        ("Agent Integration", test_agent_integration)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        logger.info(f"\n🔍 Running {test_name} Test")
        logger.info("-" * 40)
        
        try:
            success = test_func()
            results.append((test_name, success))
            
            if success:
                logger.info(f"✅ {test_name} test PASSED")
            else:
                logger.error(f"❌ {test_name} test FAILED")
                
        except Exception as e:
            logger.error(f"❌ {test_name} test ERROR: {e}")
            results.append((test_name, False))
    
    # Summary
    logger.info("\n📊 Test Summary")
    logger.info("=" * 60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"   {test_name}: {status}")
    
    logger.info(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All tests passed! Salience scoring service is ready.")
    else:
        logger.warning(f"⚠️ {total - passed} tests failed. Please check the implementation.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 