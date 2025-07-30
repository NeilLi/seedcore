#!/usr/bin/env python3
"""
Deploy SeedCore ML Ray Serve Application

This script deploys the ML models as Ray Serve applications.
"""

import sys
import os
import subprocess
import time
import requests
import json

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.seedcore.ml.serve_app import create_serve_app
import ray
from ray import serve

def check_ray_cluster():
    """Check if Ray cluster is running."""
    try:
        # Try to connect to Ray
        if not ray.is_initialized():
            ray.init(address="ray://seedcore-ray-head:10001")
        
        # Check cluster status
        cluster_resources = ray.cluster_resources()
        print(f"✅ Ray cluster is running with resources: {cluster_resources}")
        return True
    except Exception as e:
        print(f"❌ Failed to connect to Ray cluster: {e}")
        return False

def deploy_serve_app():
    """Deploy the ML Serve application."""
    try:
        print("🚀 Deploying SeedCore ML Serve application...")
        
        # Create the application
        app = create_serve_app()
        
        # Deploy the application
        app_name = app
        
        print("✅ ML Serve application deployed successfully!")
        print("📊 Available endpoints:")
        print("   - Salience Scoring: /SalienceScorer")
        print("   - Anomaly Detection: /AnomalyDetector")
        print("   - Scaling Prediction: /ScalingPredictor")
        
        return True
    except Exception as e:
        print(f"❌ Failed to deploy Serve application: {e}")
        return False

def test_endpoints():
    """Test the deployed endpoints."""
    print("\n🧪 Testing deployed endpoints...")
    
    endpoints = [
        ("/salience", {"features": [1.0, 2.0, 3.0]}),
        ("/anomaly", {"metrics": [0.5, 0.8, 0.2]}),
        ("/scaling", {"usage_patterns": {"cpu": 0.7, "memory": 0.6}})
    ]
    
    for endpoint, test_data in endpoints:
        try:
            url = f"http://localhost:8000{endpoint}"
            response = requests.post(url, json=test_data, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ {endpoint}: {result.get('status', 'unknown')}")
            else:
                print(f"❌ {endpoint}: HTTP {response.status_code}")
                
        except Exception as e:
            print(f"❌ {endpoint}: {e}")

def main():
    """Main deployment function."""
    print("🎯 SeedCore ML Ray Serve Deployment")
    print("=" * 50)
    
    # Check Ray cluster
    if not check_ray_cluster():
        print("💡 Make sure the Ray cluster is running:")
        print("   cd docker && ./ray-workers.sh start 3")
        return False
    
    # Deploy the application
    if not deploy_serve_app():
        return False
    
    # Wait a moment for deployment to complete
    print("\n⏳ Waiting for deployment to stabilize...")
    time.sleep(5)
    
    # Test the endpoints
    test_endpoints()
    
    print("\n🎉 Deployment completed successfully!")
    print("📈 You can now monitor the Serve application in the Ray Dashboard")
    print("   Dashboard: http://localhost:8265/#/serve")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 