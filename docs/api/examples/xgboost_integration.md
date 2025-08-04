# XGBoost with Ray Data Integration

This document describes the integration of XGBoost with Ray Data for distributed training and inference in the SeedCore platform.

## Overview

The XGBoost integration leverages Ray Data and `xgboost_ray` to provide:
- **Distributed Training**: Train XGBoost models across your Ray cluster (1 head + 3 workers)
- **Data Pipeline Integration**: Seamless data loading from various sources (CSV, Parquet, etc.)
- **Model Management**: Save, load, and manage trained models
- **Batch and Real-time Inference**: Support for both single predictions and batch processing
- **REST API**: Full integration with the SeedCore ML service

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   FastAPI       │    │   Ray Data      │    │   XGBoost       │
│   Endpoints     │───▶│   Dataset       │───▶│   Distributed   │
│                 │    │   Processing    │    │   Training      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Model         │    │   Ray Cluster   │    │   Model         │
│   Storage       │    │   (1+3 nodes)   │    │   Inference     │
│   & Metadata    │    │                 │    │   Engine        │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Quick Start

### 1. Start the Ray Cluster

```bash
# Start the SeedCore cluster with Ray
cd docker
./start-cluster.sh
```

### 2. Dependencies

The required dependencies are automatically installed in the Docker containers:
- `ray[data]==2.20.0`
- `xgboost>=2.0.0`
- `xgboost-ray>=0.1.20`
- `scikit-learn>=1.3.0`
- `pandas>=2.0.0`

### 3. Test the Integration

```bash
# Test the integration inside the Docker container
docker exec -it seedcore-ray-head python /app/docker/test_xgboost_docker.py

# Run the full demo
docker exec -it seedcore-ray-head python /app/docker/xgboost_docker_demo.py
```

## API Endpoints

### Training

#### POST `/xgboost/train`

Train a new XGBoost model using distributed Ray training.

**Request Body:**
```json
{
  "use_sample_data": true,
  "sample_size": 10000,
  "sample_features": 20,
  "name": "my_model",
  "xgb_config": {
    "objective": "binary:logistic",
    "eval_metric": ["logloss", "auc"],
    "eta": 0.1,
    "max_depth": 5,
    "num_boost_round": 50
  },
  "training_config": {
    "num_workers": 3,
    "use_gpu": false,
    "cpu_per_worker": 1
  }
}
```

**Response:**
```json
{
  "status": "success",
  "path": "/data/models/my_model/model.xgb",
  "name": "my_model",
  "training_time": 45.23,
  "metrics": {
    "validation_0-auc": 0.95,
    "validation_0-logloss": 0.12
  },
  "config": {
    "xgb_config": {...},
    "training_config": {...}
  }
}
```

### Prediction

#### POST `/xgboost/predict`

Make predictions using a trained model.

**Request Body:**
```json
{
  "features": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
  "path": "/data/models/my_model/model.xgb"
}
```

**Response:**
```json
{
  "status": "success",
  "prediction": 0.85,
  "path": "/data/models/my_model/model.xgb"
}
```

### Batch Prediction

#### POST `/xgboost/batch_predict`

Make predictions on a dataset.

**Request Body:**
```json
{
  "data_source": "/data/my_dataset.csv",
  "data_format": "csv",
  "feature_columns": ["feature_0", "feature_1", "feature_2"],
  "path": "/data/models/my_model/model.xgb"
}
```

**Response:**
```json
{
  "status": "success",
  "predictions_path": "/data/predictions_1234567890.parquet",
  "num_predictions": 1000,
  "path": "/data/models/my_model/model.xgb"
}
```

### Model Management

#### GET `/xgboost/list_models`

List all available models.

**Response:**
```json
{
  "models": [
    {
      "name": "my_model",
      "path": "/data/models/my_model/model.xgb",
      "created": 1234567890.0,
      "training_time": 45.23,
      "metrics": {...}
    }
  ],
  "total_count": 1
}
```

#### GET `/xgboost/model_info`

Get information about the currently loaded model.

#### POST `/xgboost/load_model`

Load a specific model.

#### DELETE `/xgboost/delete_model`

Delete a model.

## Configuration Options

### XGBoost Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `objective` | string | `"binary:logistic"` | XGBoost objective function |
| `eval_metric` | list | `["logloss", "auc"]` | Evaluation metrics |
| `eta` | float | `0.1` | Learning rate |
| `max_depth` | int | `5` | Maximum tree depth |
| `tree_method` | string | `"hist"` | Tree construction method |
| `num_boost_round` | int | `50` | Number of boosting rounds |

### Training Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `num_workers` | int | `3` | Number of Ray workers |
| `use_gpu` | bool | `false` | Use GPU acceleration |
| `cpu_per_worker` | int | `1` | CPU cores per worker |
| `memory_per_worker` | int | `2000000000` | Memory per worker (bytes) |

## Data Sources

The integration supports loading data from various sources:

### CSV Files
```python
dataset = ray.data.read_csv("/path/to/data.csv")
```

### Parquet Files
```python
dataset = ray.data.read_parquet("/path/to/data.parquet")
```

### Pandas DataFrames
```python
import pandas as pd
df = pd.DataFrame(...)
dataset = ray.data.from_pandas(df)
```

### Cloud Storage
```python
# S3
dataset = ray.data.read_parquet("s3://my-bucket/data/")

# Azure Blob Storage
dataset = ray.data.read_csv("az://my-container/data.csv")
```

## Performance Optimization

### 1. Data Partitioning

Ray Data automatically partitions your dataset across workers:
```python
# Optimize partition size for your cluster
dataset = ray.data.read_csv("/data/large_file.csv").repartition(10)
```

### 2. Memory Management

Configure memory per worker based on your data size:
```json
{
  "training_config": {
    "memory_per_worker": 4000000000,  // 4GB per worker
    "num_workers": 3
  }
}
```

### 3. GPU Acceleration

Enable GPU training if available:
```json
{
  "training_config": {
    "use_gpu": true,
    "num_workers": 3
  }
}
```

## Monitoring and Debugging

### Ray Dashboard

Access the Ray dashboard at `http://localhost:8265` to monitor:
- Cluster resources
- Task execution
- Memory usage
- Training progress

### Logging

The service provides detailed logging:
```python
import logging
logging.getLogger("src.seedcore.ml.models.xgboost_service").setLevel(logging.DEBUG)
```

### Metrics

Training metrics are automatically collected and returned:
- AUC (Area Under Curve)
- Log Loss
- Training time
- Resource utilization

## Best Practices

### 1. Data Preparation

- Ensure your data is clean and preprocessed
- Use appropriate data types (float32 for features)
- Handle missing values before training

### 2. Hyperparameter Tuning

- Start with default parameters
- Use cross-validation for hyperparameter selection
- Monitor validation metrics to prevent overfitting

### 3. Resource Management

- Monitor cluster resources during training
- Adjust `num_workers` based on available CPUs
- Use appropriate memory settings

### 4. Model Persistence

- Always save models after training
- Use descriptive model names
- Keep track of model metadata

## Troubleshooting

### Common Issues

1. **Out of Memory**
   - Reduce `memory_per_worker`
   - Use smaller batch sizes
   - Repartition data

2. **Slow Training**
   - Increase `num_workers`
   - Use GPU if available
   - Optimize data loading

3. **Model Loading Failures**
   - Check file permissions
   - Verify model path exists
   - Ensure model format compatibility

### Debug Mode

Enable debug logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Docker Integration

The XGBoost integration is designed to work seamlessly within the SeedCore Docker environment:

### Container Setup

The integration automatically:
- Connects to the existing Ray cluster using `RAY_ADDRESS` environment variable
- Follows the same Ray initialization pattern as other services to avoid double initialization
- Uses the shared `/data` volume for model storage
- Leverages the existing Ray Serve infrastructure
- Integrates with the monitoring stack (Prometheus/Grafana)

### Ray Initialization Pattern

The XGBoost service follows the established Ray initialization pattern:
```python
# Check if Ray is already initialized to avoid double initialization
if not ray.is_initialized():
    ray_address = os.getenv("RAY_ADDRESS")
    if ray_address:
        ray.init(address=ray_address, log_to_driver=False)
    else:
        ray.init()  # Local initialization
else:
    logger.info("✅ Ray is already initialized, skipping initialization")
```

This ensures consistency with the existing Ray Serve setup and prevents initialization conflicts.

### Running in Docker

```bash
# Start the cluster
cd docker
./start-cluster.sh

# Test the integration
docker exec -it seedcore-ray-head python /app/docker/test_xgboost_docker.py

# Run the demo
docker exec -it seedcore-ray-head python /app/docker/xgboost_docker_demo.py

# Access the API
curl http://localhost:8000/xgboost/list_models
```

### Model Storage

Models are stored in the shared `/data/models` directory, which is:
- Persisted across container restarts
- Accessible from all containers in the cluster
- Mounted as a Docker volume

## Integration with SeedCore

The XGBoost integration is fully integrated with the SeedCore ML service:

- **Health Checks**: Included in service health monitoring
- **Error Handling**: Consistent error responses
- **Logging**: Integrated with SeedCore logging system
- **Metrics**: Exported to Prometheus/Grafana

## Examples

See `examples/xgboost_demo.py` for complete usage examples including:
- Basic training and prediction
- Advanced features (CSV loading, batch prediction)
- Model management operations
- Error handling

## Support

For issues and questions:
1. Check the Ray dashboard for cluster status
2. Review service logs
3. Test with the demo script
4. Consult XGBoost and Ray Data documentation 