#!/usr/bin/env python3
"""
Deploy Salience Scoring Service

This script deploys the complete salience scoring service including:
1. Model training
2. Ray Serve deployment
3. API server startup
4. Health checks
"""

import sys
import os
import time
import subprocess
import requests
import json
from typing import Dict, Any
import logging

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_dependencies():
    """Check if all required dependencies are available."""
    logger.info("🔍 Checking dependencies...")
    
    try:
        import sklearn
        logger.info("✅ scikit-learn available")
    except ImportError:
        logger.error("❌ scikit-learn not available")
        logger.info("💡 Install with: pip install scikit-learn>=1.3.0")
        return False
    
    try:
        import ray
        logger.info("✅ Ray available")
    except ImportError:
        logger.error("❌ Ray not available")
        logger.info("💡 Install with: pip install ray>=2.10")
        return False
    
    try:
        import fastapi
        logger.info("✅ FastAPI available")
    except ImportError:
        logger.error("❌ FastAPI not available")
        logger.info("💡 Install with: pip install fastapi")
        return False
    
    return True

def train_model():
    """Train the salience scoring model."""
    logger.info("🎯 Training Salience Model")
    logger.info("=" * 40)
    
    try:
        # Run the training script
        result = subprocess.run([
            sys.executable, "scripts/train_salience_model.py"
        ], capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__)))
        
        if result.returncode == 0:
            logger.info("✅ Model training completed successfully")
            return True
        else:
            logger.error(f"❌ Model training failed: {result.stderr}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Model training error: {e}")
        return False

def check_ray_cluster():
    """Check if Ray cluster is running."""
    logger.info("🔍 Checking Ray cluster...")
    
    try:
        import ray
        
        # Try to connect to Ray
        if not ray.is_initialized():
            from seedcore.utils.ray_utils import ensure_ray_initialized
            if not ensure_ray_initialized(ray_address="ray://seedcore-svc-head-svc:10001"):
                logger.error("❌ Failed to connect to Ray cluster")
                return False
        
        # Check cluster status
        cluster_resources = ray.cluster_resources()
        logger.info(f"✅ Ray cluster is running with resources: {cluster_resources}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ray cluster not available: {e}")
        logger.info("💡 Start Ray cluster with: cd docker && ./ray-workers.sh start 3")
        return False

def deploy_ray_serve():
    """Deploy the Ray Serve application."""
    logger.info("🚀 Deploying Ray Serve Application")
    logger.info("=" * 40)
    
    try:
        # Run the deployment script
        result = subprocess.run([
            sys.executable, "scripts/deploy_ml_serve.py"
        ], capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__)))
        
        if result.returncode == 0:
            logger.info("✅ Ray Serve deployment completed")
            return True
        else:
            logger.error(f"❌ Ray Serve deployment failed: {result.stderr}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Ray Serve deployment error: {e}")
        return False

def start_api_server():
    """Start the FastAPI server."""
    logger.info("🌐 Starting API Server")
    logger.info("=" * 40)
    
    try:
        # Start the server in the background
        server_process = subprocess.Popen([
            sys.executable, "-m", "uvicorn", 
            "src.seedcore.telemetry.server:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--reload"
        ], cwd=os.path.dirname(os.path.dirname(__file__)))
        
        # Wait for server to start
        logger.info("⏳ Waiting for API server to start...")
        time.sleep(5)
        
        # Check if server is running
        try:
            response = requests.get("http://localhost:8000/health", timeout=10)
            if response.status_code == 200:
                logger.info("✅ API server is running")
                return server_process
            else:
                logger.error(f"❌ API server health check failed: {response.status_code}")
                server_process.terminate()
                return None
        except requests.exceptions.ConnectionError:
            logger.error("❌ Could not connect to API server")
            server_process.terminate()
            return None
            
    except Exception as e:
        logger.error(f"❌ Failed to start API server: {e}")
        return None

def test_salience_endpoints():
    """Test the salience scoring endpoints."""
    logger.info("🧪 Testing Salience Endpoints")
    logger.info("=" * 40)
    
    try:
        # Test health endpoint
        response = requests.get("http://localhost:8000/salience/health", timeout=10)
        if response.status_code != 200:
            logger.error(f"❌ Health endpoint failed: {response.status_code}")
            return False
        
        health_data = response.json()
        logger.info(f"✅ Health check: {health_data['status']}")
        
        # Test info endpoint
        response = requests.get("http://localhost:8000/salience/info", timeout=10)
        if response.status_code != 200:
            logger.error(f"❌ Info endpoint failed: {response.status_code}")
            return False
        
        info_data = response.json()
        logger.info(f"✅ Service info: {info_data['model_type']}")
        
        # Test scoring endpoint
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
            "http://localhost:8000/salience/score",
            json=test_features,
            timeout=10
        )
        
        if response.status_code != 200:
            logger.error(f"❌ Scoring endpoint failed: {response.status_code}")
            return False
        
        result = response.json()
        logger.info(f"✅ Scoring test: {result['scores'][0]:.3f}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Endpoint testing failed: {e}")
        return False

def run_integration_tests():
    """Run integration tests."""
    logger.info("🧪 Running Integration Tests")
    logger.info("=" * 40)
    
    try:
        # Run the test script
        result = subprocess.run([
            sys.executable, "scripts/test_salience_service.py"
        ], capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__)))
        
        if result.returncode == 0:
            logger.info("✅ Integration tests passed")
            return True
        else:
            logger.error(f"❌ Integration tests failed: {result.stderr}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Integration test error: {e}")
        return False

def main():
    """Main deployment function."""
    logger.info("🎯 Salience Scoring Service Deployment")
    logger.info("=" * 60)
    
    # Step 1: Check dependencies
    if not check_dependencies():
        logger.error("❌ Dependency check failed")
        return False
    
    # Step 2: Train model
    if not train_model():
        logger.error("❌ Model training failed")
        return False
    
    # Step 3: Check Ray cluster
    if not check_ray_cluster():
        logger.error("❌ Ray cluster check failed")
        return False
    
    # Step 4: Deploy Ray Serve
    if not deploy_ray_serve():
        logger.error("❌ Ray Serve deployment failed")
        return False
    
    # Step 5: Start API server
    server_process = start_api_server()
    if not server_process:
        logger.error("❌ API server startup failed")
        return False
    
    # Step 6: Test endpoints
    if not test_salience_endpoints():
        logger.error("❌ Endpoint testing failed")
        server_process.terminate()
        return False
    
    # Step 7: Run integration tests
    if not run_integration_tests():
        logger.error("❌ Integration tests failed")
        server_process.terminate()
        return False
    
    logger.info("🎉 Salience Scoring Service Deployment Complete!")
    logger.info("=" * 60)
    logger.info("📊 Available Endpoints:")
    logger.info("   - Health: http://localhost:8000/salience/health")
    logger.info("   - Info: http://localhost:8000/salience/info")
    logger.info("   - Score: POST http://localhost:8000/salience/score")
    logger.info("   - Batch Score: POST http://localhost:8000/salience/score/batch")
    logger.info("")
    logger.info("🔧 Ray Dashboard: http://localhost:8265")
    logger.info("📈 API Documentation: http://localhost:8000/docs")
    logger.info("")
    logger.info("💡 To stop the service, press Ctrl+C")
    
    try:
        # Keep the server running
        server_process.wait()
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down...")
        server_process.terminate()
        server_process.wait()
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 