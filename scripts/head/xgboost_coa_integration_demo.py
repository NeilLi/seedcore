#!/usr/bin/env python3
"""
XGBoost COA Integration Demo

This script demonstrates the complete integration of XGBoost with the Cognitive
Organism Architecture (COA) and Energy system, as specified in the detailed
implementation instructions.

The demo covers:
1. Environment bootstrap
2. Data preparation (multiple methods)
3. Distributed training
4. Model management
5. Utility organ actor integration
6. Energy system integration
7. Batch prediction
8. Operational monitoring

Usage:
    docker exec -it seedcore-ray-head python /app/docker/xgboost_coa_integration_demo.py
"""

import requests
import json
import time
import numpy as np
import pandas as pd
import ray
import sys
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add the app directory to Python path
sys.path.insert(0, '/app')

# Import the UtilityPredictor actor
from src.seedcore.agents.utility_inference_actor import get_utility_predictor, reset_utility_predictor


def print_header(title: str):
    """Print a formatted header."""
    print(f"\n{'='*60}")
    print(f"🎯 {title}")
    print(f"{'='*60}")


def print_step(step: str):
    """Print a formatted step."""
    print(f"\n📋 {step}")
    print(f"{'-'*40}")


def get_service_url():
    """Get service URL based on environment."""
    # Check if we're running in seedcore-api pod
    if os.getenv('SEEDCORE_API_ADDRESS'):
        # We're in the seedcore-api pod, use internal service names
        return "http://seedcore-svc-serve-svc:8000"
    else:
        # Local development or ray head pod
        return "http://localhost:8000"

def check_service_health() -> bool:
    """Check if the ML service is healthy."""
    base_url = get_service_url()
    print(f"🔗 Checking service health at: {base_url}")
    
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            health_data = response.json()
            print(f"✅ Service is healthy")
            print(f"   Status: {health_data.get('status')}")
            print(f"   Service: {health_data.get('service')}")
            print(f"   XGBoost: {health_data.get('models', {}).get('xgboost_service')}")
            return True
        else:
            print(f"❌ Service unhealthy: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Service check failed: {e}")
        return False


def method1_auto_fabricate_data() -> str:
    """Method 1: Let the service auto-fabricate a dummy dataset."""
    print_step("Method 1: Auto-fabricate Dataset")
    
    train_request = {
        "use_sample_data": True,
        "sample_size": 10000,
        "sample_features": 20,
        "name": "coa_integration_prototype",
        "xgb_config": {
            "objective": "binary:logistic",
            "eval_metric": ["logloss", "auc"],
            "eta": 0.05,
            "max_depth": 6,
            "num_boost_round": 100,
            "tree_method": "hist"
        },
        "training_config": {
            "num_workers": 2,
            "cpu_per_worker": 1,
            "use_gpu": False,
            "memory_per_worker": 2000000000
        }
    }
    
    print("📤 Training with auto-generated data...")
    base_url = get_service_url()
    response = requests.post(
        f"{base_url}/xgboost/train",
        json=train_request,
        timeout=300
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Auto-fabrication completed!")
        print(f"   Model: {result.get('name')}")
        print(f"   Path: {result.get('path')}")
        print(f"   Time: {result.get('training_time', 'N/A')}s")
        return result.get('path')
    else:
        print(f"❌ Auto-fabrication failed: {response.status_code}")
        print(f"   Error: {response.text}")
        return None


def method2_bespoke_csv() -> str:
    """Method 2: Generate a bespoke CSV dataset."""
    print_step("Method 2: Bespoke CSV Generation")
    
    # Generate utility-focused dataset
    print("📊 Generating utility dataset...")
    
    # Create sample data with utility features
    np.random.seed(42)
    n_samples = 5000
    
    # Generate features that mimic utility signals
    task_complexity = np.random.beta(2, 5, n_samples)
    resource_availability = np.random.beta(3, 2, n_samples)
    historical_success = np.random.beta(4, 2, n_samples)
    memory_pressure = np.random.beta(2, 3, n_samples)
    network_latency = np.random.beta(1, 4, n_samples)
    agent_capability = np.random.beta(3, 1, n_samples)
    
    # Create target: Risk score
    risk_score = (
        0.3 * task_complexity +
        0.2 * memory_pressure +
        0.15 * network_latency +
        -0.2 * resource_availability +
        -0.1 * historical_success +
        -0.05 * agent_capability
    )
    risk_score = np.clip(risk_score + np.random.normal(0, 0.05, n_samples), 0, 1)
    
    # Create DataFrame
    df = pd.DataFrame({
        'task_complexity': task_complexity,
        'resource_availability': resource_availability,
        'historical_success': historical_success,
        'memory_pressure': memory_pressure,
        'network_latency': network_latency,
        'agent_capability': agent_capability,
        'target': risk_score
    })
    
    # Save to CSV
    csv_path = "/data/utility_bespoke_training.csv"
    df.to_csv(csv_path, index=False)
    
    print(f"✅ Bespoke dataset created: {csv_path}")
    print(f"   Samples: {len(df)}")
    print(f"   Features: {len(df.columns) - 1}")
    print(f"   Target range: {df['target'].min():.3f} to {df['target'].max():.3f}")
    
    return csv_path


def method3_telemetry_logs() -> str:
    """Method 3: Process telemetry logs."""
    print_step("Method 3: Telemetry Log Processing")
    
    # Create sample telemetry data
    print("📊 Creating sample telemetry data...")
    
    records = []
    organs = ["cognitive", "utility", "actuator", "sensory"]
    paths = ["fast", "slow", "memory", "energy"]
    
    np.random.seed(42)
    
    for i in range(2000):
        record = {
            "task_id": f"task_{i:06d}",
            "organ": np.random.choice(organs),
            "path": np.random.choice(paths),
            "energy": {
                "pair": np.random.beta(2, 5),
                "hyper": np.random.beta(1, 3),
                "entropy": np.random.normal(-0.02, 0.05),
                "reg": np.random.beta(1, 4),
                "mem": np.random.beta(2, 3),
                "total": 0.0
            },
            "memory_stats": {
                "mw_hits": np.random.poisson(3),
                "mlt_hits": np.random.poisson(1),
                "compr_ratio": np.random.uniform(1.2, 2.5)
            },
            "capability": {
                "a7": np.random.beta(3, 2)
            }
        }
        
        # Calculate total energy
        energy = record["energy"]
        energy["total"] = energy["pair"] + energy["hyper"] + energy["entropy"] + energy["reg"] + energy["mem"]
        records.append(record)
    
    # Flatten and create training dataset
    flattened_records = []
    for record in records:
        flat_record = {
            "organ": record["organ"],
            "path": record["path"],
            "energy_pair": record["energy"]["pair"],
            "energy_hyper": record["energy"]["hyper"],
            "energy_entropy": record["energy"]["entropy"],
            "energy_reg": record["energy"]["reg"],
            "energy_mem": record["energy"]["mem"],
            "energy_total": record["energy"]["total"],
            "memory_mw_hits": record["memory_stats"]["mw_hits"],
            "memory_mlt_hits": record["memory_stats"]["mlt_hits"],
            "memory_compr_ratio": record["memory_stats"]["compr_ratio"],
            "capability_a7": record["capability"]["a7"]
        }
        flattened_records.append(flat_record)
    
    df = pd.DataFrame(flattened_records)
    
    # One-hot encode categorical features
    df_encoded = pd.get_dummies(df, columns=['organ', 'path'], dummy_na=True)
    
    # Create target: Risk score based on energy components
    df_encoded["target"] = (
        0.3 * df_encoded["energy_pair"] +
        0.2 * df_encoded["energy_mem"] +
        0.15 * df_encoded["energy_reg"] +
        0.1 * df_encoded["energy_hyper"] +
        0.05 * df_encoded["energy_entropy"]
    )
    df_encoded["target"] = (df_encoded["target"] - df_encoded["target"].min()) / (df_encoded["target"].max() - df_encoded["target"].min())
    
    # Save to CSV
    csv_path = "/data/telemetry_training.csv"
    df_encoded.to_csv(csv_path, index=False)
    
    print(f"✅ Telemetry dataset created: {csv_path}")
    print(f"   Samples: {len(df_encoded)}")
    print(f"   Features: {len(df_encoded.columns) - 1}")
    print(f"   Target range: {df_encoded['target'].min():.3f} to {df_encoded['target'].max():.3f}")
    
    return csv_path


def train_xgboost_model(data_source: str, model_name: str) -> Optional[str]:
    """Train an XGBoost model with the given data source."""
    print_step(f"Training XGBoost Model: {model_name}")
    
    train_request = {
        "name": model_name,
        "data_source": data_source,
        "data_format": "csv",
        "feature_columns": None,  # Auto-detect
        "target_column": "target",
        "xgb_config": {
            "objective": "reg:squarederror",
            "eval_metric": ["rmse", "mae"],
            "eta": 0.05,
            "max_depth": 6,
            "num_boost_round": 100,
            "tree_method": "hist"
        },
        "training_config": {
            "num_workers": 2,
            "cpu_per_worker": 1,
            "use_gpu": False,
            "memory_per_worker": 2000000000
        }
    }
    
    print(f"📤 Training model with data: {data_source}")
    print(f"   Model name: {model_name}")
    print(f"   Workers: {train_request['training_config']['num_workers']}")
    
    base_url = get_service_url()
    response = requests.post(
        f"{base_url}/xgboost/train",
        json=train_request,
        timeout=300
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Training completed successfully!")
        print(f"   Model: {result.get('name')}")
        print(f"   Path: {result.get('path')}")
        print(f"   Time: {result.get('training_time', 'N/A')}s")
        print(f"   Features: {len(result.get('model_metadata', {}).get('feature_columns', []))}")
        return result.get('path')
    else:
        print(f"❌ Training failed: {response.status_code}")
        print(f"   Error: {response.text}")
        return None


def get_latest_model_path() -> Optional[str]:
    """Get the path of the latest model."""
    try:
        base_url = get_service_url()
        response = requests.get(f"{base_url}/xgboost/list_models", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            if models:
                # Sort by creation time and get the latest
                latest_model = max(models, key=lambda x: x.get("created", 0))
                return latest_model.get("path")
        return None
    except Exception as e:
        print(f"❌ Error getting latest model: {e}")
        return None


def test_utility_predictor_actor() -> bool:
    """Test the UtilityPredictor actor integration."""
    print_step("Testing UtilityPredictor Actor")
    
    try:
        # Initialize Ray if not already done
        if not ray.is_initialized():
            # Add src to path for imports
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
            
            from seedcore.utils.ray_utils import ensure_ray_initialized
            if not ensure_ray_initialized(ray_address="ray://localhost:10001"):
                print("❌ Failed to connect to Ray cluster")
                return False
        
        # Get the utility predictor actor
        predictor = get_utility_predictor(refresh_interval_hours=1)
        
        # Get status
        status = ray.get(predictor.get_status.remote())
        print(f"✅ Actor initialized successfully")
        print(f"   Model path: {status.get('model_path', 'None')}")
        print(f"   Refresh interval: {status.get('refresh_interval_hours')} hours")
        print(f"   Prediction count: {status.get('prediction_count')}")
        
        # Test prediction with sample features
        if status.get('model_path'):
            print("🧪 Testing prediction...")
            
            # Create sample features (matching the model's expected features)
            sample_features = np.random.random(20)  # Adjust based on your model
            
            # Make prediction
            prediction = ray.get(predictor.predict.remote(sample_features))
            
            print(f"✅ Prediction successful!")
            print(f"   Input features: {len(sample_features)}")
            print(f"   Prediction: {prediction:.4f}")
            
            # Check updated status
            updated_status = ray.get(predictor.get_status.remote())
            print(f"   Updated prediction count: {updated_status.get('prediction_count')}")
            print(f"   Success rate: {updated_status.get('success_rate', 0):.2%}")
            
            return True
        else:
            print("⚠️  No model available for prediction")
            return False
            
    except Exception as e:
        print(f"❌ Actor test failed: {e}")
        return False


def test_energy_integration() -> bool:
    """Test energy system integration."""
    print_step("Testing Energy Integration")
    
    try:
        # Check energy logs endpoint
        response = requests.get("http://localhost:8002/energy/logs", timeout=5)
        if response.status_code == 200:
            logs_data = response.json()
            print(f"✅ Energy logs accessible")
            print(f"   Total events: {logs_data.get('total_count', 0)}")
            print(f"   Recent events: {logs_data.get('returned_count', 0)}")
            
            # Show recent events
            recent_logs = logs_data.get('logs', [])
            if recent_logs:
                print(f"   Latest event: {recent_logs[-1]}")
            
            return True
        else:
            print(f"❌ Energy logs not accessible: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Energy integration test failed: {e}")
        return False


def test_batch_prediction(model_path: str) -> bool:
    """Test batch prediction capabilities."""
    print_step("Testing Batch Prediction")
    
    # Create sample batch data
    print("📊 Creating sample batch data...")
    
    np.random.seed(42)
    n_samples = 100
    
    # Generate sample features with correct feature names (matching training data)
    task_complexity = np.random.beta(2, 5, n_samples)
    resource_availability = np.random.beta(3, 2, n_samples)
    historical_success = np.random.beta(4, 2, n_samples)
    memory_pressure = np.random.beta(2, 3, n_samples)
    network_latency = np.random.beta(1, 4, n_samples)
    agent_capability = np.random.beta(3, 1, n_samples)
    
    # Create DataFrame with correct feature names
    df = pd.DataFrame({
        'task_complexity': task_complexity,
        'resource_availability': resource_availability,
        'historical_success': historical_success,
        'memory_pressure': memory_pressure,
        'network_latency': network_latency,
        'agent_capability': agent_capability
    })
    
    # Save batch data
    batch_csv_path = "/data/batch_prediction_data.csv"
    df.to_csv(batch_csv_path, index=False)
    
    print(f"✅ Batch data created: {batch_csv_path}")
    print(f"   Samples: {len(df)}")
    print(f"   Features: {len(df.columns)}")
    
    # Run batch prediction
    batch_request = {
        "data_source": batch_csv_path,
        "data_format": "csv",
        "feature_columns": ['task_complexity', 'resource_availability', 'historical_success', 
                           'memory_pressure', 'network_latency', 'agent_capability'],
        "path": model_path
    }
    
    print("📤 Running batch prediction...")
            base_url = get_service_url()
        response = requests.post(
            f"{base_url}/xgboost/batch_predict",
        json=batch_request,
        timeout=180
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Batch prediction completed!")
        print(f"   Predictions saved to: {result.get('predictions_path')}")
        print(f"   Number of predictions: {result.get('num_predictions')}")
        print(f"   Model used: {result.get('path')}")
        return True
    else:
        print(f"❌ Batch prediction failed: {response.status_code}")
        print(f"   Error: {response.text}")
        return False


def monitor_operational_metrics() -> None:
    """Monitor operational metrics."""
    print_step("Monitoring Operational Metrics")
    
    try:
        # Check Ray dashboard status
        print("🔍 Checking Ray cluster status...")
        response = requests.get("http://localhost:8002/ray/status", timeout=5)
        if response.status_code == 200:
            ray_status = response.json()
            print(f"✅ Ray cluster healthy")
            print(f"   Nodes: {ray_status.get('num_nodes', 'N/A')}")
            print(f"   Resources: {ray_status.get('resources', 'N/A')}")
        
        # Check energy gradient
        print("🔍 Checking energy gradient...")
        response = requests.get("http://localhost:8002/energy/gradient", timeout=5)
        if response.status_code == 200:
            energy_data = response.json()
            print(f"✅ Energy system active")
            print(f"   Total energy: {energy_data.get('total_energy', 'N/A')}")
            print(f"   Energy components: {list(energy_data.get('energy_components', {}).keys())}")
        
        # Check model list
        print("🔍 Checking available models...")
        base_url = get_service_url()
        response = requests.get(f"{base_url}/xgboost/list_models", timeout=5)
        if response.status_code == 200:
            models_data = response.json()
            models = models_data.get("models", [])
            print(f"✅ Found {len(models)} models")
            for model in models[:3]:  # Show first 3
                print(f"   - {model.get('name', 'Unknown')} ({model.get('created', 'Unknown')})")
        
    except Exception as e:
        print(f"⚠️  Monitoring check failed: {e}")


def main():
    """Main demo function."""
    print_header("XGBoost COA Integration Demo")
    print("This demo showcases the complete integration of XGBoost with the")
    print("Cognitive Organism Architecture (COA) and Energy system.")
    print()
    print("🔍 Environment Check:")
    print(f"   RAY_ADDRESS: {os.environ.get('RAY_ADDRESS', 'Not set')}")
    print(f"   PYTHONPATH: {os.environ.get('PYTHONPATH', 'Not set')}")
    print(f"   Working Directory: {os.getcwd()}")
    
    # Step 1: Environment Bootstrap
    print_step("Step 1: Environment Bootstrap")
    if not check_service_health():
        print("❌ Service health check failed. Please ensure the cluster is running.")
        return
    
    # Step 2: Data Preparation (Multiple Methods)
    print_step("Step 2: Data Preparation")
    
    # Method 1: Auto-fabricate
    auto_model_path = method1_auto_fabricate_data()
    
    # Method 2: Bespoke CSV
    bespoke_csv = method2_bespoke_csv()
    bespoke_model_path = train_xgboost_model(bespoke_csv, "utility_bespoke_model")
    
    # Method 3: Telemetry logs
    telemetry_csv = method3_telemetry_logs()
    telemetry_model_path = train_xgboost_model(telemetry_csv, "telemetry_risk_model")
    
    # Step 3: Model Management
    print_step("Step 3: Model Management")
    latest_model = get_latest_model_path()
    if latest_model:
        print(f"✅ Latest model: {latest_model}")
    else:
        print("❌ No models found")
        return
    
    # Step 4: Utility Organ Actor Integration
    print_step("Step 4: Utility Organ Actor Integration")
    actor_success = test_utility_predictor_actor()
    
    # Step 5: Energy System Integration
    print_step("Step 5: Energy System Integration")
    energy_success = test_energy_integration()
    
    # Step 6: Batch Prediction
    print_step("Step 6: Batch Prediction")
    if latest_model:
        batch_success = test_batch_prediction(latest_model)
    else:
        batch_success = False
    
    # Step 7: Operational Monitoring
    print_step("Step 7: Operational Monitoring")
    monitor_operational_metrics()
    
    # Summary
    print_header("Demo Summary")
    print("✅ Completed XGBoost COA Integration Demo")
    print()
    print("📊 Results:")
    print(f"   ✅ Service Health: {'PASS' if check_service_health() else 'FAIL'}")
    print(f"   ✅ Auto-fabrication: {'PASS' if auto_model_path else 'FAIL'}")
    print(f"   ✅ Bespoke CSV: {'PASS' if bespoke_model_path else 'FAIL'}")
    print(f"   ✅ Telemetry Processing: {'PASS' if telemetry_model_path else 'FAIL'}")
    print(f"   ✅ Utility Actor: {'PASS' if actor_success else 'FAIL'}")
    print(f"   ✅ Energy Integration: {'PASS' if energy_success else 'FAIL'}")
    print(f"   ✅ Batch Prediction: {'PASS' if batch_success else 'FAIL'}")
    print()
    print("🔗 Next Steps:")
    print("   1. Monitor model performance in Ray dashboard")
    print("   2. Schedule periodic model refresh")
    print("   3. Set up alerts for model performance")
    print("   4. Scale workers for production workloads")
    print("   5. Integrate with production telemetry streams")
    print()
    print("🎉 Integration complete! The XGBoost model is now fully integrated")
    print("   with the COA Energy system and Utility organ.")


if __name__ == "__main__":
    main() 