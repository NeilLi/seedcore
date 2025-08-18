#!/usr/bin/env python3
"""
XGBoost with Ray Data Integration Demo for SeedCore

This script demonstrates how to use the XGBoost integration with Ray Data
for distributed training and inference in the SeedCore platform.

Usage:
    python examples/xgboost_demo.py
"""

import sys
import os
import time
import json
import requests
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def get_service_urls():
    """Get service URLs based on environment."""
    # Check if we're running in seedcore-api pod
    if os.getenv('SEEDCORE_API_ADDRESS'):
        # We're in the seedcore-api pod, use internal service names
        base_url = "http://seedcore-svc-serve-svc:8000"
        ray_dashboard = "http://seedcore-svc-head-svc:8265"
    else:
        # Local development
        base_url = "http://localhost:8000"
        ray_dashboard = "http://localhost:8265"
    
    return base_url, ray_dashboard

def demo_xgboost_integration():
    """Demonstrate XGBoost integration with Ray Data."""
    
    print("🚀 XGBoost with Ray Data Integration Demo")
    print("=" * 50)
    
    # Get service URLs based on environment
    base_url, ray_dashboard = get_service_urls()
    print(f"🔗 Using ML service at: {base_url}")
    print(f"🔗 Ray dashboard at: {ray_dashboard}")
    
    # Test 1: Health Check
    print("\n1️⃣ Testing ML Service Health...")
    try:
        response = requests.get(f"{base_url}/health", timeout=10)
        if response.status_code == 200:
            print("✅ ML Service is healthy")
            print(f"   Service: {response.json().get('service', 'unknown')}")
        else:
            print(f"❌ Health check failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Cannot connect to ML service: {e}")
        print(f"   Make sure the Ray cluster is running and the ML service is deployed at {base_url}")
        print(f"   Check if seedcore-head-svc is accessible from this pod")
        return
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return
    
    # Test 2: Train XGBoost Model with Sample Data
    print("\n2️⃣ Training XGBoost Model with Sample Data...")
    
    train_request = {
        "use_sample_data": True,
        "sample_size": 5000,
        "sample_features": 15,
        "name": "demo_model",
        "xgb_config": {
            "objective": "binary:logistic",
            "eval_metric": ["logloss", "auc"],
            "eta": 0.1,
            "max_depth": 4,
            "num_boost_round": 30
        },
        "training_config": {
            "num_workers": 3,
            "use_gpu": False,
            "cpu_per_worker": 1
        }
    }
    
    try:
        response = requests.post(
            f"{base_url}/xgboost/train",
            json=train_request,
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Model training completed successfully!")
            print(f"   Model Path: {result['path']}")
            print(f"   Training Time: {result['training_time']:.2f}s")
            print(f"   Final AUC: {result['metrics'].get('validation_0-auc', 'N/A')}")
            
            model_path = result['path']
        else:
            print(f"❌ Training failed: {response.status_code}")
            print(f"   Error: {response.text}")
            return
            
    except Exception as e:
        print(f"❌ Training request failed: {e}")
        return
    
    # Test 3: Make Predictions
    print("\n3️⃣ Making Predictions...")
    
    # Create sample features
    sample_features = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    
    predict_request = {
        "features": sample_features,
        "path": model_path
    }
    
    try:
        response = requests.post(
            f"{base_url}/xgboost/predict",
            json=predict_request,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Prediction completed successfully!")
            print(f"   Prediction: {result['prediction']}")
            print(f"   Probability: {result['probability']:.4f}")
            print(f"   Features used: {len(sample_features)}")
        else:
            print(f"❌ Prediction failed: {response.status_code}")
            print(f"   Error: {response.text}")
            
    except Exception as e:
        print(f"❌ Prediction request failed: {e}")
    
    # Test 4: Model Information
    print("\n4️⃣ Getting Model Information...")
    
    try:
        response = requests.get(f"{base_url}/xgboost/model/{os.path.basename(model_path)}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Model info retrieved successfully!")
            print(f"   Model Name: {result.get('name', 'N/A')}")
            print(f"   Created: {result.get('created_at', 'N/A')}")
            print(f"   Size: {result.get('size_mb', 'N/A')} MB")
        else:
            print(f"❌ Model info failed: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Model info request failed: {e}")
    
    print("\n📊 Training Summary:")
    print(f"   - Model saved to: {model_path}")
    print(f"   - Ray dashboard: {ray_dashboard}")
    print("\n💡 Next steps:")
    print("1. Try training with your own data by providing a data_source path")
    print("2. Experiment with different XGBoost hyperparameters")
    print("3. Use batch prediction for large datasets")
    print("4. Monitor training progress in the Ray dashboard")

def demo_advanced_features():
    """Demonstrate advanced XGBoost features."""
    
    print("\n🔧 Advanced Features Demo")
    print("=" * 30)
    
    base_url, _ = get_service_urls()
    
    # Create a CSV file for demonstration - use a writable directory
    import pandas as pd
    import numpy as np
    from sklearn.datasets import make_classification
    
    # Generate sample data
    X, y = make_classification(n_samples=1000, n_features=10, random_state=42)
    df = pd.DataFrame(X, columns=[f"feature_{i}" for i in range(10)])
    df["target"] = y
    
    # Save to CSV in a writable directory
    # Try different writable locations
    writable_dirs = [
        "/tmp",  # Usually writable
        "/app/tmp" if os.path.exists("/app") else None,  # App-specific temp
        os.path.join(os.getcwd(), "tmp")  # Current directory + tmp
    ]
    
    csv_path = None
    for dir_path in writable_dirs:
        if dir_path and os.access(dir_path, os.W_OK):
            try:
                os.makedirs(dir_path, exist_ok=True)
                csv_path = os.path.join(dir_path, "demo_data.csv")
                df.to_csv(csv_path, index=False)
                print(f"📊 Created sample CSV file: {csv_path}")
                break
            except Exception as e:
                print(f"⚠️  Could not write to {dir_path}: {e}")
                continue
    
    if not csv_path:
        print("❌ Could not find a writable directory for CSV file")
        print("   Skipping advanced features demo")
        return
    
    # Train with CSV data
    print("\n📈 Training with CSV Data...")
    
    train_request = {
        "data_source": csv_path,
        "data_format": "csv",
        "name": "csv_demo_model",
        "label_column": "target",
        "xgb_config": {
            "objective": "binary:logistic",
            "eval_metric": ["logloss", "auc"],
            "eta": 0.05,
            "max_depth": 6,
            "num_boost_round": 50
        }
    }
    
    try:
        response = requests.post(
            f"{base_url}/xgboost/train",
            json=train_request,
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✅ CSV training completed!")
            print(f"   Model: {result['path']}")
            print(f"   Time: {result['training_time']:.2f}s")
            
            # Test batch prediction
            print("\n📊 Testing Batch Prediction...")
            
            batch_request = {
                "data_source": csv_path,
                "data_format": "csv",
                "feature_columns": [f"feature_{i}" for i in range(10)],
                "path": result['path']
            }
            
            batch_response = requests.post(
                f"{base_url}/xgboost/batch_predict",
                json=batch_request,
                headers={"Content-Type": "application/json"},
                timeout=60
            )
            
            if batch_response.status_code == 200:
                batch_result = batch_response.json()
                print("✅ Batch prediction completed!")
                print(f"   Predictions saved to: {batch_result['predictions_path']}")
                print(f"   Number of predictions: {batch_result['num_predictions']}")
            else:
                print(f"❌ Batch prediction failed: {batch_response.status_code}")
                print(f"   Error: {batch_response.text}")
                
        else:
            print(f"❌ CSV training failed: {response.status_code}")
            print(f"   Error: {response.text}")
            
    except Exception as e:
        print(f"❌ Advanced demo failed: {e}")

if __name__ == "__main__":
    print("Starting XGBoost Integration Demo...")
    
    # Basic demo
    demo_xgboost_integration()
    
    # Advanced demo
    demo_advanced_features()
    
    print("\n✨ Demo completed! Check the Ray dashboard for monitoring.") 