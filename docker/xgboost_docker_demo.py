#!/usr/bin/env python3
"""
XGBoost Docker Demo for SeedCore

This script demonstrates the XGBoost integration within the Docker container environment.
Run this script inside the Ray head container to test the integration.
This is a test

Usage:
    docker exec -it seedcore-ray-head python /app/docker/xgboost_docker_demo.py
"""

import sys
import os
import time
import json
import requests
from pathlib import Path

# Add the app directory to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

def demo_basic_training():
    """Demonstrate basic XGBoost training via API."""
    
    print("🚀 XGBoost Basic Training Demo")
    print("=" * 40)
    
    # Prepare training request
    train_request = {
        "use_sample_data": True,
        "sample_size": 2000,
        "sample_features": 12,
        "name": "demo_basic_model",
        "xgb_config": {
            "objective": "binary:logistic",
            "eval_metric": ["logloss", "auc"],
            "eta": 0.1,
            "max_depth": 4,
            "num_boost_round": 20
        },
        "training_config": {
            "num_workers": 1,
            "use_gpu": False,
            "cpu_per_worker": 1
        }
    }
    
    print("📤 Training XGBoost model...")
    response = requests.post(
        "http://localhost:8000/xgboost/train",
        json=train_request,
        headers={"Content-Type": "application/json"},
        timeout=120
    )
    
    if response.status_code == 200:
        result = response.json()
        print("✅ Training completed successfully!")
        print(f"   Model: {result['name']}")
        print(f"   Path: {result['path']}")
        print(f"   Time: {result['training_time']:.2f}s")
        print(f"   AUC: {result['metrics'].get('validation_0-auc', 'N/A')}")
        return result['path']
    else:
        print(f"❌ Training failed: {response.status_code}")
        print(f"   Error: {response.text}")
        return None

def demo_prediction(model_path):
    """Demonstrate prediction with the trained model."""
    
    print("\n📊 XGBoost Prediction Demo")
    print("=" * 35)
    
    # Create sample features
    sample_features = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 0.1, 0.2]
    
    predict_request = {
        "features": sample_features,
        "path": model_path
    }
    
    print("📤 Making prediction...")
    response = requests.post(
        "http://localhost:8000/xgboost/predict",
        json=predict_request,
        headers={"Content-Type": "application/json"},
        timeout=10
    )
    
    if response.status_code == 200:
        result = response.json()
        print("✅ Prediction completed!")
        print(f"   Prediction: {result['prediction']}")
        print(f"   Model: {result['path']}")
    else:
        print(f"❌ Prediction failed: {response.status_code}")
        print(f"   Error: {response.text}")

def demo_model_management():
    """Demonstrate model management features."""
    
    print("\n🗂️  XGBoost Model Management Demo")
    print("=" * 40)
    
    # List models
    print("📋 Listing available models...")
    response = requests.get("http://localhost:8000/xgboost/list_models", timeout=10)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Found {result['total_count']} models:")
        for model in result['models']:
            print(f"   - {model['name']} (created: {time.ctime(model['created'])})")
    else:
        print(f"❌ Failed to list models: {response.status_code}")
    
    # Get model info
    print("\nℹ️  Getting current model info...")
    response = requests.get("http://localhost:8000/xgboost/model_info", timeout=10)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Model info: {result['status']}")
        if result['path']:
            print(f"   Current model: {result['path']}")
    else:
        print(f"❌ Failed to get model info: {response.status_code}")

def demo_advanced_training():
    """Demonstrate advanced training with custom parameters."""
    
    print("\n🔧 XGBoost Advanced Training Demo")
    print("=" * 40)
    
    # Advanced training request
    train_request = {
        "use_sample_data": True,
        "sample_size": 3000,
        "sample_features": 15,
        "name": "demo_advanced_model",
        "xgb_config": {
            "objective": "binary:logistic",
            "eval_metric": ["logloss", "auc"],
            "eta": 0.05,
            "max_depth": 6,
            "num_boost_round": 30,
            "subsample": 0.8,
            "colsample_bytree": 0.8
        },
        "training_config": {
            "num_workers": 1,
            "use_gpu": False,
            "cpu_per_worker": 1,
            "memory_per_worker": 1500000000  # 1.5GB
        }
    }
    
    print("📤 Training advanced XGBoost model...")
    response = requests.post(
        "http://localhost:8000/xgboost/train",
        json=train_request,
        headers={"Content-Type": "application/json"},
        timeout=180
    )
    
    if response.status_code == 200:
        result = response.json()
        print("✅ Advanced training completed!")
        print(f"   Model: {result['name']}")
        print(f"   Time: {result['training_time']:.2f}s")
        print(f"   AUC: {result['metrics'].get('validation_0-auc', 'N/A')}")
        print(f"   Log Loss: {result['metrics'].get('validation_0-logloss', 'N/A')}")
        return result['path']
    else:
        print(f"❌ Advanced training failed: {response.status_code}")
        print(f"   Error: {response.text}")
        return None

def demo_batch_prediction():
    """Demonstrate batch prediction capabilities."""
    
    print("\n📦 XGBoost Batch Prediction Demo")
    print("=" * 35)
    
    # Create a sample CSV file for batch prediction
    import pandas as pd
    import numpy as np
    from sklearn.datasets import make_classification
    
    # Generate sample data with same number of features as advanced training (15)
    # Reduced sample size for faster processing
    X, y = make_classification(n_samples=50, n_features=15, random_state=42)
    df = pd.DataFrame(X, columns=[f"feature_{i}" for i in range(15)])
    df["target"] = y
    
    # Save to CSV in the shared data directory
    csv_path = "/data/batch_demo_data.csv"
    df.to_csv(csv_path, index=False)
    print(f"📊 Created sample CSV file: {csv_path}")
    
    # Batch prediction request
    batch_request = {
        "data_source": csv_path,
        "data_format": "csv",
        "feature_columns": [f"feature_{i}" for i in range(15)],
        "path": "/data/models/demo_advanced_model/model.xgb"
    }
    
    print("📤 Running batch prediction...")
    print(f"   Data source: {csv_path}")
    print(f"   Features: {len(batch_request['feature_columns'])} columns")
    print(f"   Model: {batch_request['path']}")
    
    try:
        response = requests.post(
            "http://localhost:8000/xgboost/batch_predict",
            json=batch_request,
            headers={"Content-Type": "application/json"},
            timeout=180  # Increased timeout to 3 minutes
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Batch prediction completed!")
            print(f"   Predictions saved to: {result['predictions_path']}")
            print(f"   Number of predictions: {result['num_predictions']}")
        else:
            print(f"❌ Batch prediction failed: {response.status_code}")
            print(f"   Error: {response.text}")
            
    except requests.exceptions.Timeout:
        print("❌ Batch prediction timed out after 3 minutes")
        print("   This might be due to Ray processing delays or system load")
        print("   Try reducing the batch size or checking system resources")
    except requests.exceptions.ConnectionError:
        print("❌ Connection error during batch prediction")
        print("   Check if the API service is still running")
    except Exception as e:
        print(f"❌ Unexpected error during batch prediction: {e}")

def main():
    """Run the complete XGBoost Docker demo."""
    
    print("🎯 XGBoost Docker Integration Demo")
    print("=" * 50)
    print("This demo showcases XGBoost integration in the Docker environment")
    print("Running inside the Ray head container...")
    print()
    
    # Check environment
    print("🔍 Environment Check:")
    print(f"   RAY_ADDRESS: {os.getenv('RAY_ADDRESS', 'Not set')}")
    print(f"   PYTHONPATH: {os.getenv('PYTHONPATH', 'Not set')}")
    print(f"   Working Directory: {os.getcwd()}")
    print()
    
    try:
        # Test health endpoint first
        print("🏥 Testing service health...")
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            print("✅ Service is healthy")
        else:
            print(f"❌ Service health check failed: {response.status_code}")
            return
        
        # Run demos
        model_path = demo_basic_training()
        if model_path:
            demo_prediction(model_path)
        
        demo_model_management()
        
        advanced_model_path = demo_advanced_training()
        if advanced_model_path:
            demo_batch_prediction()
        
        print("\n🎉 Demo completed successfully!")
        print("\n📋 Summary:")
        print("   ✅ Basic training and prediction")
        print("   ✅ Model management")
        print("   ✅ Advanced training with custom parameters")
        print("   ✅ Batch prediction capabilities")
        print("\n🔗 Next Steps:")
        print("   - Try training with your own data")
        print("   - Experiment with different hyperparameters")
        print("   - Monitor training in the Ray dashboard")
        print("   - Use the models for production inference")
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 
