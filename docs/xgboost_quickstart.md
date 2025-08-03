# XGBoost Quick Start Guide

This guide will get you up and running with XGBoost integration in SeedCore within minutes.

## Prerequisites

- Docker and Docker Compose installed
- SeedCore project cloned
- At least 4GB RAM available

## Quick Start (5 minutes)

### 1. Start the Cluster

```bash
cd docker
./start-cluster.sh
```

Wait for the cluster to be ready (you'll see "✅ ray-head is ready!")

### 2. Verify the Integration

```bash
# Verify XGBoost service is properly initialized
docker exec -it seedcore-ray-head python /app/docker/verify_xgboost_service.py

# Test basic functionality
docker exec -it seedcore-ray-head python /app/docker/test_xgboost_docker.py
```

### 3. Run the Demo

```bash
# Run the complete demo
docker exec -it seedcore-ray-head python /app/docker/xgboost_docker_demo.py
```

### 4. Access the API

```bash
# Check available endpoints
curl http://localhost:8000/

# List models
curl http://localhost:8000/xgboost/list_models

# Get model info
curl http://localhost:8000/xgboost/model_info
```

## Your First XGBoost Model

### Train a Model

```bash
curl -X POST http://localhost:8000/xgboost/train \
  -H "Content-Type: application/json" \
  -d '{
    "use_sample_data": true,
    "sample_size": 1000,
    "sample_features": 10,
    "model_name": "my_first_model",
    "xgb_config": {
      "objective": "binary:logistic",
      "num_boost_round": 10
    }
  }'
```

### Make Predictions

```bash
curl -X POST http://localhost:8000/xgboost/predict \
  -H "Content-Type: application/json" \
  -d '{
    "features": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
  }'
```

## Monitor Your Training

- **Ray Dashboard**: http://localhost:8265
- **Grafana**: http://localhost:3000 (admin/seedcore)
- **Prometheus**: http://localhost:9090

## Common Use Cases

### 1. Training with Your Own Data

```bash
# Upload your CSV file to the container
docker cp your_data.csv seedcore-ray-head:/data/

# Train with your data
curl -X POST http://localhost:8000/xgboost/train \
  -H "Content-Type: application/json" \
  -d '{
    "data_source": "/data/your_data.csv",
    "data_format": "csv",
    "label_column": "target",
    "model_name": "production_model"
  }'
```

### 2. Batch Predictions

```bash
# Upload test data
docker cp test_data.csv seedcore-ray-head:/data/

# Run batch predictions
curl -X POST http://localhost:8000/xgboost/batch_predict \
  -H "Content-Type: application/json" \
  -d '{
    "data_source": "/data/test_data.csv",
    "data_format": "csv",
    "feature_columns": ["feature_1", "feature_2", "feature_3"],
    "model_path": "/data/models/production_model/model.xgb"
  }'
```

### 3. Model Management

```bash
# List all models
curl http://localhost:8000/xgboost/list_models

# Load a specific model
curl -X POST http://localhost:8000/xgboost/load_model \
  -H "Content-Type: application/json" \
  -d '{
    "model_path": "/data/models/production_model/model.xgb"
  }'

# Delete a model
curl -X DELETE http://localhost:8000/xgboost/delete_model \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "old_model"
  }'
```

## Configuration Options

### XGBoost Parameters

```json
{
  "xgb_config": {
    "objective": "binary:logistic",
    "eval_metric": ["logloss", "auc"],
    "eta": 0.1,
    "max_depth": 5,
    "num_boost_round": 50,
    "subsample": 0.8,
    "colsample_bytree": 0.8
  }
}
```

### Training Configuration

```json
{
  "training_config": {
    "num_workers": 3,
    "use_gpu": false,
    "cpu_per_worker": 1,
    "memory_per_worker": 2000000000
  }
}
```

## Troubleshooting

### Common Issues

1. **Cluster not ready**
   ```bash
   # Check cluster status
   docker ps | grep seedcore
   
   # Check logs
   docker logs seedcore-ray-head
   ```

2. **Out of memory**
   ```bash
   # Reduce memory usage
   "memory_per_worker": 1000000000  # 1GB instead of 2GB
   ```

3. **Training too slow**
   ```bash
   # Increase workers
   "num_workers": 3  # Use all available workers
   ```

### Debug Mode

```bash
# Enable debug logging
docker exec -it seedcore-ray-head bash
export PYTHONPATH=/app:/app/src
python -c "
import logging
logging.basicConfig(level=logging.DEBUG)
from seedcore.ml.models.xgboost_service import XGBoostService
service = XGBoostService()
"
```

## Next Steps

1. **Read the full documentation**: `docs/xgboost_integration.md`
2. **Explore the API**: Check all available endpoints
3. **Monitor performance**: Use the Ray dashboard and Grafana
4. **Scale up**: Add more workers or use GPU acceleration
5. **Production deployment**: Set up proper model versioning and monitoring

## Support

- **Documentation**: `docs/xgboost_integration.md`
- **Examples**: `docker/xgboost_docker_demo.py`
- **Tests**: `docker/test_xgboost_docker.py`
- **Ray Dashboard**: http://localhost:8265 