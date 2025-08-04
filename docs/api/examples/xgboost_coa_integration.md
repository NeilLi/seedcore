# XGBoost COA Integration Guide

This document provides a comprehensive guide for integrating XGBoost machine learning models with the Cognitive Organism Architecture (COA) and Energy system in SeedCore.

## Table of Contents

1. [Big-Picture Fit](#big-picture-fit)
2. [Environment Bootstrap](#environment-bootstrap)
3. [Data Preparation](#data-preparation)
4. [Distributed Training](#distributed-training)
5. [Model Management](#model-management)
6. [Utility Organ Actor](#utility-organ-actor)
7. [Energy Integration](#energy-integration)
8. [Batch Prediction](#batch-prediction)
9. [Operational Checklist](#operational-checklist)
10. [Troubleshooting](#troubleshooting)

## Big-Picture Fit

Section 6 of the Cognitive Organism Architecture (COA) paper specifies that the Utility (Heart) organ is responsible for low-level optimization and resource balancing across the entire agent swarm. Training an XGBoost model to predict a utility signal—such as risk, computational cost, or success probability—aligns perfectly with this role.

The workflow is designed to be a **closed loop**:

1. **Training** runs periodically as new data becomes available, writing the updated model artifact to the shared `/data/models` volume
2. **Inference** is exposed to the Utility organ via a lightweight Ray actor, which calls the FastAPI `/xgboost/predict` endpoint for real-time predictions
3. **Energy Integration**: After each prediction, the actor logs the outcome to the central Energy ledger, ensuring the model's performance directly influences the `mem`, `pair`, or `hyper` terms in the Unified Energy Function (E_core)

## Environment Bootstrap

### One-Time Setup

Launch the complete SeedCore environment:

```bash
# From the repository root directory
cd docker
./start-cluster.sh down && ./start-cluster.sh up 1
# or
./start-cluster.sh restart
```

This script initiates:
- Ray cluster (one head and one worker node)
- FastAPI server with ML service
- Pre-configured containers with Ray Data, xgboost_ray, XGBoost, scikit-learn, and pandas

### Verify Environment

```bash
# Check service health
curl http://localhost:8000/health

# Check Ray cluster
curl http://localhost:8000/ray/status

# Check XGBoost service availability
curl http://localhost:8000/xgboost/list_models
```

## Data Preparation

The `/xgboost/train` and `/xgboost/batch_predict` endpoints expect training data to be accessible at a path like `/data/my_training.csv`. The `/data` directory is a Docker volume shared across all services.

### Method 1: Auto-Fabricate Dataset (Fastest)

For rapid testing, let the service generate synthetic data:

```bash
curl -X POST http://localhost:8000/xgboost/train \
  -H 'Content-Type: application/json' \
  -d '{
    "use_sample_data": true,
    "sample_size": 10000,
    "sample_features": 20,
    "name": "prototype_model",
    "xgb_config": { "objective": "binary:logistic" }
  }'
```

### Method 2: Generate Bespoke CSV

Use the provided script to create custom datasets:

```bash
# Generate classification dataset
docker exec -it seedcore-ray-head python /app/scripts/make_my_training.py \
  --type classification --samples 50000 --features 32

# Generate regression dataset
docker exec -it seedcore-ray-head python /app/scripts/make_my_training.py \
  --type regression --samples 50000 --features 32

# Generate utility-focused dataset
docker exec -it seedcore-ray-head python /app/scripts/make_my_training.py \
  --type utility --samples 10000
```

### Method 3: Process Telemetry Logs (Production)

For production models, use real organ telemetry logs:

```bash
# Process existing telemetry logs
docker exec -it seedcore-ray-head python /app/scripts/process_telemetry_logs.py \
  --log-pattern "/var/log/organ/*.jsonl" \
  --target-type "energy_total" \
  --output "/data/telemetry_training.csv"

# Create sample telemetry data for testing
docker exec -it seedcore-ray-head python /app/scripts/process_telemetry_logs.py \
  --target-type "risk_score" \
  --output "/data/telemetry_risk_training.csv"
```

### Method 4: Public Datasets

Download and use public datasets:

```bash
# Download UCI dataset
curl -L -o /data/my_training.csv \
  https://archive.ics.uci.edu/ml/machine-learning-databases/00462/drug_consumption.data
```

## Distributed Training

### Basic Training

```bash
curl -X POST http://localhost:8000/xgboost/train \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "utility_risk_v1",
    "data_source": "/data/my_training.csv",
    "feature_columns": ["feature_0", "feature_1", "..."],
    "target_column": "target",
    "xgb_config": {
      "objective": "binary:logistic",
      "eval_metric": ["logloss","auc"],
      "eta": 0.05,
      "max_depth": 6,
      "num_boost_round": 200,
      "tree_method": "hist"
    },
    "training_config": {
      "num_workers": 3,
      "cpu_per_worker": 2,
      "use_gpu": false,
      "memory_per_worker": 4000000000
    }
  }'
```

### Advanced Training with Custom Parameters

```bash
curl -X POST http://localhost:8000/xgboost/train \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "utility_advanced_v1",
    "data_source": "/data/telemetry_training.csv",
    "xgb_config": {
      "objective": "reg:squarederror",
      "eval_metric": ["rmse", "mae"],
      "eta": 0.03,
      "max_depth": 8,
      "subsample": 0.8,
      "colsample_bytree": 0.8,
      "num_boost_round": 300,
      "tree_method": "hist",
      "early_stopping_rounds": 50
    },
    "training_config": {
      "num_workers": 4,
      "cpu_per_worker": 4,
      "use_gpu": false,
      "memory_per_worker": 8000000000
    }
  }'
```

### Expected Response

```json
{
  "path": "/data/models/utility_risk_v1/model.xgb",
  "training_time": 123.45,
  "metrics": { 
    "validation_0-auc": 0.962, 
    "validation_0-logloss": 0.11 
  },
  "model_metadata": {
    "feature_names": ["feature_0", "..."],
    "feature_columns": ["feature_0", "feature_1", "..."],
    "training_config": { ... }
  }
}
```

## Model Management

### List Available Models

```bash
curl http://localhost:8000/xgboost/list_models
```

### Get Model Information

```bash
curl http://localhost:8000/xgboost/model_info
```

### Get Latest Model Path

```python
import requests
import operator

def get_latest_model_path():
    """Queries the API to find the path of the most recent model."""
    try:
        r = requests.get("http://localhost:8000/xgboost/list_models", timeout=5)
        r.raise_for_status()
        models = r.json().get("models", [])
        if not models:
            return None
        # Sort by 'created' timestamp descending and get the first one
        newest_model = max(models, key=operator.itemgetter("created"))
        return newest_model.get("path")
    except requests.RequestException as e:
        print(f"Error fetching models: {e}")
        return None
```

## Utility Organ Actor

### Core Actor Implementation

The `UtilityPredictor` actor is implemented in `src/seedcore/agents/utility_inference_actor.py`:

```python
import ray
from src.seedcore.agents.utility_inference_actor import get_utility_predictor

# Get the global actor instance
predictor = get_utility_predictor(refresh_interval_hours=24)

# Make predictions
features = np.random.random(20)  # Adjust based on your model
prediction = ray.get(predictor.predict.remote(features))
print(f"Prediction: {prediction}")

# Get actor status
status = ray.get(predictor.get_status.remote())
print(f"Model path: {status['model_path']}")
print(f"Success rate: {status['success_rate']:.2%}")
```

### Actor Features

- **Dynamic Model Loading**: Automatically loads the latest model
- **Configurable Refresh**: Set refresh interval (default: 24 hours)
- **Energy Integration**: Logs predictions to energy system
- **Performance Tracking**: Monitors success rate and prediction count
- **Error Handling**: Graceful fallback for failed predictions

### Actor Methods

```python
# Force model refresh
ray.get(predictor.force_refresh.remote())

# Update refresh interval
ray.get(predictor.update_refresh_interval.remote(12))  # 12 hours

# Get detailed status
status = ray.get(predictor.get_status.remote())
```

## Energy Integration

### Energy Logging Endpoint

The system provides `/energy/log` endpoint for logging prediction events:

```python
# Energy event structure
energy_event = {
    "ts": datetime.utcnow().timestamp(),
    "organ": "utility",
    "metric": "predicted_risk",
    "value": prediction,
    "model_path": model_path,
    "success": True,
    "prediction_count": 42,
    "success_rate": 0.95
}

# Log to energy system
requests.post("http://localhost:8000/energy/log", json=energy_event)
```

### Energy Terms Integration

The logged events influence the Unified Energy Function (E_core):

| Energy Term | Update Rule | Rationale |
|-------------|-------------|-----------|
| `pair` | Successful predictions reduce pair energy (better collaboration) | Tracks collaboration quality between agents |
| `mem` | Model loading adds to memory pressure | Reflects memory usage for model storage |
| `reg` | High prediction count increases complexity | Penalizes overall state complexity |

### View Energy Logs

```bash
# Get recent energy logs
curl "http://localhost:8000/energy/logs?limit=50"

# Check energy gradient
curl http://localhost:8000/energy/gradient
```

## Batch Prediction

### Offline Scoring

For large datasets, use batch prediction:

```bash
curl -X POST http://localhost:8000/xgboost/batch_predict \
  -H 'Content-Type: application/json' \
  -d '{
    "data_source": "/data/unscored_data.csv",
    "data_format": "csv",
    "feature_columns": ["f0", "f1", "..."],
    "path": "/data/models/utility_risk_v1/model.xgb"
  }'
```

### Expected Response

```json
{
  "status": "success",
  "predictions_path": "/data/predictions_1754280958.parquet",
  "num_predictions": 1000,
  "path": "/data/models/utility_risk_v1/model.xgb"
}
```

## Operational Checklist

### Monitoring

- **Ray Dashboard**: Monitor training jobs at http://localhost:8265
- **Service Health**: Regular health checks via `/health` endpoint
- **Model Performance**: Track validation metrics in training responses
- **Energy Metrics**: Monitor energy logs for model impact

### Refresh Schedule

```python
# Schedule periodic model refresh
import schedule
import time

def refresh_model():
    predictor = get_utility_predictor()
    ray.get(predictor.force_refresh.remote())

# Refresh every 6 hours
schedule.every(6).hours.do(refresh_model)

while True:
    schedule.run_pending()
    time.sleep(60)
```

### Alerting

Set up monitoring to alert when:
- Validation AUC falls below threshold (e.g., 0.85)
- Training time exceeds expected duration
- Model refresh fails
- Energy impact becomes negative

### Scaling

For high-throughput requirements:

```yaml
# docker-compose.yml - Add GPU workers
services:
  ray-worker-gpu:
    image: seedcore-ray-worker:latest
    environment:
      - RAY_ADDRESS=ray://ray-head:10001
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

```json
// Training config with GPU
{
  "training_config": {
    "num_workers": 4,
    "cpu_per_worker": 4,
    "use_gpu": true,
    "memory_per_worker": 8000000000
  }
}
```

### Security

The FastAPI layer provides:
- Request validation
- Access logging
- Rate limiting (configurable)
- Input sanitization

For high-assurance needs, the COA framework supports:
- Trusted Execution Environments (TEEs)
- Zero-knowledge proofs (zk-SNARKs)
- Advanced safety layers

## Troubleshooting

### Common Issues

#### 1. Model Not Found

```bash
# Check available models
curl http://localhost:8000/xgboost/list_models

# Verify model path exists
docker exec -it seedcore-ray-head ls -la /data/models/
```

#### 2. Feature Mismatch

```bash
# Check model metadata
curl http://localhost:8000/xgboost/model_info

# Ensure feature count matches
# Training: 20 features, Prediction: 20 features
```

#### 3. Training Timeout

```bash
# Increase timeout
curl -X POST http://localhost:8000/xgboost/train \
  --max-time 600 \
  -H 'Content-Type: application/json' \
  -d '{ ... }'

# Reduce dataset size for testing
"sample_size": 1000  # Instead of 10000
```

#### 4. Memory Issues

```json
// Reduce memory per worker
{
  "training_config": {
    "memory_per_worker": 1000000000  // 1GB instead of 2GB
  }
}
```

#### 5. Ray Connection Issues

```bash
# Check Ray cluster status
curl http://localhost:8000/ray/status

# Restart Ray cluster
./start-cluster.sh restart

# Check Ray logs
docker logs seedcore-ray-head
```

### Debug Commands

```bash
# Check service logs
docker logs seedcore-api

# Check Ray worker logs
docker logs seedcore-workers-ray-worker-1

# Monitor resource usage
docker stats

# Check data directory
docker exec -it seedcore-ray-head ls -la /data/

# Test API endpoints
curl http://localhost:8000/health
curl http://localhost:8000/xgboost/list_models
```

### Performance Optimization

1. **Dataset Size**: Start with smaller datasets for testing
2. **Worker Count**: Match workers to available CPU cores
3. **Memory**: Monitor memory usage and adjust `memory_per_worker`
4. **GPU**: Enable GPU for large datasets and complex models
5. **Caching**: Use model caching to avoid repeated loading

## Complete Integration Demo

Run the complete integration demo:

```bash
docker exec -it seedcore-ray-head python /app/docker/xgboost_coa_integration_demo.py
```

This demo covers:
- Environment bootstrap
- Data preparation (all methods)
- Distributed training
- Model management
- Utility actor integration
- Energy system integration
- Batch prediction
- Operational monitoring

## Next Steps

1. **Production Deployment**: Scale workers and enable GPU support
2. **Real Data Integration**: Connect to production telemetry streams
3. **Model Monitoring**: Implement comprehensive monitoring and alerting
4. **Performance Tuning**: Optimize hyperparameters for your specific use case
5. **Security Hardening**: Implement additional security measures as needed

The XGBoost integration is now fully operational and integrated with the COA Energy system, creating a truly adaptive and self-improving organism. 