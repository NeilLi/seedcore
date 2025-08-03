# XGBoost Integration Reference

## Overview

This document provides a comprehensive reference for the XGBoost integration with Ray Data in the SeedCore platform. The integration enables distributed XGBoost training using Ray Data for preprocessing and provides a robust fallback mechanism for local training when distributed training encounters issues.

## Architecture

### Core Components

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   FastAPI       │    │   Ray Serve     │    │   XGBoost       │
│   Endpoints     │◄──►│   Deployment    │◄──►│   Service       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Ray Data      │    │   Ray Cluster   │    │   Model Storage │
│   Preprocessing │    │   (Head+Worker) │    │   (/data/models)│
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Service Architecture

1. **FastAPI Layer**: RESTful API endpoints for XGBoost operations
2. **Ray Serve Layer**: Model serving and deployment management
3. **XGBoost Service Layer**: Core training and prediction logic
4. **Ray Data Layer**: Distributed data preprocessing
5. **Ray Cluster Layer**: Distributed computing infrastructure
6. **Model Storage Layer**: Persistent model storage

## File Structure

```
src/seedcore/ml/
├── serve_app.py                    # Main FastAPI application
├── models/
│   ├── __init__.py                 # Module exports
│   ├── xgboost_service.py          # Core XGBoost service
│   └── xgboost_models.py           # Pydantic models for API
├── __init__.py                     # Package initialization
└── ...

docker/
├── test_xgboost_docker.py          # Docker integration tests
├── verify_xgboost_service.py       # Service verification
└── ...

docs/
├── xgboost_integration_reference.md # This file
├── xgboost_daily_reference.md       # Daily usage guide
└── ...
```

## Core Classes and Functions

### XGBoostService

**Location**: `src/seedcore/ml/models/xgboost_service.py`

**Purpose**: Core service class for XGBoost operations

**Key Methods**:

```python
class XGBoostService:
    def __init__(self, model_storage_path: str = "/data/models")
    def create_sample_dataset(self, n_samples: int = 10000, n_features: int = 20) -> ray.data.Dataset
    def load_dataset_from_source(self, source_path: str, format: str = "auto") -> ray.data.Dataset
    def train_model(self, dataset: ray.data.Dataset, label_column: str = "target", 
                   xgb_config: Optional[XGBoostConfig] = None,
                   training_config: Optional[TrainingConfig] = None,
                   model_name: Optional[str] = None) -> Dict[str, Any]
    def predict(self, features: Union[List, np.ndarray, pd.DataFrame]) -> np.ndarray
    def batch_predict(self, dataset: ray.data.Dataset, feature_columns: List[str]) -> ray.data.Dataset
    def load_model(self, model_path: str) -> bool
    def get_model_info(self) -> Dict[str, Any]
    def list_models(self) -> List[Dict[str, Any]]
    def delete_model(self, model_name: str) -> bool
```

### Configuration Classes

**XGBoostConfig**:
```python
@dataclass
class XGBoostConfig:
    objective: str = "binary:logistic"
    eval_metric: List[str] = None
    eta: float = 0.1
    max_depth: int = 5
    tree_method: str = "hist"
    num_boost_round: int = 50
    early_stopping_rounds: int = 10
```

**TrainingConfig**:
```python
@dataclass
class TrainingConfig:
    num_workers: int = 3
    use_gpu: bool = False
    cpu_per_worker: int = 1
    memory_per_worker: int = 2000000000  # 2GB
```

### Pydantic Models

**Location**: `src/seedcore/ml/models/xgboost_models.py`

**Key Models**:
- `ModelObjective`: Enum for XGBoost objective functions
- `TreeMethod`: Enum for XGBoost tree methods
- `XGBoostConfigRequest`: API request model for XGBoost configuration
- `TrainingConfigRequest`: API request model for training configuration
- `TrainModelRequest`: API request model for training
- `PredictRequest`: API request model for predictions
- `TrainModelResponse`: API response model for training results
- `PredictResponse`: API response model for predictions

## API Endpoints

### Training Endpoints

#### POST `/xgboost/train`

**Purpose**: Train a new XGBoost model

**Request Body**:
```json
{
  "use_sample_data": true,
  "sample_size": 10000,
  "sample_features": 20,
  "label_column": "target",
  "model_name": "my_model",
  "xgb_config": {
    "objective": "binary:logistic",
    "eval_metric": ["logloss", "auc"],
    "eta": 0.1,
    "max_depth": 5,
    "tree_method": "hist",
    "num_boost_round": 50
  },
  "training_config": {
    "num_workers": 3,
    "use_gpu": false,
    "cpu_per_worker": 1
  }
}
```

**Response**:
```json
{
  "status": "success",
  "model_path": "/data/models/my_model/model.xgb",
  "model_name": "my_model",
  "training_time": 17.55,
  "metrics": {"status": "completed"},
  "config": {...}
}
```

### Prediction Endpoints

#### POST `/xgboost/predict`

**Purpose**: Make predictions using a trained model

**Request Body**:
```json
{
  "features": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
  "model_path": "/data/models/my_model/model.xgb"
}
```

**Response**:
```json
{
  "status": "success",
  "prediction": 0.63177866,
  "model_path": "/data/models/my_model/model.xgb"
}
```

### Model Management Endpoints

#### GET `/xgboost/list_models`

**Purpose**: List all available models

**Response**:
```json
{
  "models": [
    {
      "name": "my_model",
      "path": "/data/models/my_model/model.xgb",
      "created": 1754215421.8065517
    }
  ],
  "total_count": 1
}
```

#### GET `/xgboost/model_info`

**Purpose**: Get information about the current model

**Response**:
```json
{
  "status": "model_loaded",
  "model_path": "/data/models/my_model/model.xgb",
  "metadata": {...}
}
```

#### POST `/xgboost/load_model`

**Purpose**: Load a specific model

**Request Body**:
```json
{
  "model_path": "/data/models/my_model/model.xgb"
}
```

#### DELETE `/xgboost/delete_model`

**Purpose**: Delete a model

**Request Body**:
```json
{
  "model_name": "my_model"
}
```

## Training Process

### Distributed Training Flow

1. **Data Preparation**:
   ```python
   dataset = ray.data.from_pandas(df)  # or from other sources
   ```

2. **Configuration Setup**:
   ```python
   xgb_config = XGBoostConfig(
       objective="binary:logistic",
       eval_metric=["logloss", "auc"],
       eta=0.1,
       max_depth=5
   )
   
   training_config = TrainingConfig(
       num_workers=3,
       use_gpu=False,
       cpu_per_worker=1
   )
   ```

3. **RayDMatrix Creation**:
   ```python
   dtrain = RayDMatrix(
       data=dataset,
       label=label_column,
       num_actors=training_config.num_workers
   )
   ```

4. **Distributed Training**:
   ```python
   result = train(
       params=xgb_params,
       dtrain=dtrain,
       num_boost_round=xgb_config.num_boost_round,
       ray_params={
           "num_actors": training_config.num_workers,
           "cpus_per_actor": training_config.cpu_per_worker,
           "gpus_per_actor": 1 if training_config.use_gpu else 0,
       }
   )
   ```

### Fallback Mechanism

When distributed training fails (e.g., due to network issues), the system automatically falls back to local training:

1. **Error Detection**: Catches `getaddrinfo()` and other network-related errors
2. **Data Conversion**: Converts Ray Dataset to pandas DataFrame
3. **Local Training**: Uses standard XGBoost training
4. **MockResult Creation**: Creates compatible result object for consistency

```python
try:
    # Attempt distributed training
    result = train(...)
except Exception as e:
    # Fallback to local training
    df_list = dataset.take_all()
    df = pd.concat(df_list, ignore_index=True)
    X = df.drop(columns=[label_column])
    y = df[label_column]
    dtrain_local = xgb.DMatrix(X, label=y)
    bst = xgb.train(local_params, dtrain_local, num_boost_round=xgb_config.num_boost_round)
    result = MockResult(bst)
```

## Data Sources

### Supported Formats

1. **Pandas DataFrame**: Direct conversion to Ray Dataset
2. **CSV Files**: `ray.data.read_csv()`
3. **Parquet Files**: `ray.data.read_parquet()`
4. **Synthetic Data**: Built-in sample data generation

### Data Loading Examples

```python
# From CSV
dataset = ray.data.read_csv("data.csv")

# From Parquet
dataset = ray.data.read_parquet("data.parquet")

# From Pandas DataFrame
dataset = ray.data.from_pandas(df)

# Synthetic data
dataset = service.create_sample_dataset(n_samples=10000, n_features=20)
```

## Model Storage

### Storage Structure

```
/data/models/
├── model_name_1/
│   ├── model.xgb          # XGBoost model file
│   └── metadata.json      # Training metadata
├── model_name_2/
│   ├── model.xgb
│   └── metadata.json
└── ...
```

### Metadata Format

```json
{
  "model_name": "my_model",
  "model_path": "/data/models/my_model/model.xgb",
  "training_time": 17.55,
  "metrics": {"status": "completed"},
  "config": {
    "xgb_config": {...},
    "training_config": {...}
  }
}
```

## Error Handling

### Common Errors and Solutions

1. **Distributed Training Failures**:
   - **Error**: `getaddrinfo() argument 1 must be string or None`
   - **Solution**: Automatic fallback to local training
   - **Cause**: Network configuration issues in Docker environment

2. **Feature Names Mismatch**:
   - **Error**: `data did not contain feature names, but the following fields are expected`
   - **Solution**: Automatic feature name generation in prediction
   - **Cause**: Training data has feature names, prediction data doesn't

3. **Enum Conversion Issues**:
   - **Error**: `Unknown objective function: ModelObjective.BINARY_LOGISTIC`
   - **Solution**: Automatic enum to string conversion in API layer
   - **Cause**: Pydantic enum values not converted to strings

### Error Recovery

The system implements multiple layers of error recovery:

1. **API Layer**: Input validation and type conversion
2. **Service Layer**: Graceful degradation and fallback mechanisms
3. **Training Layer**: Automatic fallback from distributed to local training
4. **Prediction Layer**: Feature name handling and data format conversion

## Performance Considerations

### Training Performance

1. **Distributed Training**: Scales across Ray cluster workers
2. **Local Fallback**: Single-node training when distributed fails
3. **Memory Management**: Configurable memory per worker
4. **GPU Support**: Optional GPU acceleration

### Prediction Performance

1. **Batch Prediction**: Efficient processing of multiple samples
2. **Model Caching**: Loaded models stay in memory
3. **Feature Optimization**: Efficient feature name handling

### Resource Configuration

```python
# Conservative settings
training_config = TrainingConfig(
    num_workers=2,
    cpu_per_worker=1,
    memory_per_worker=1000000000  # 1GB
)

# Aggressive settings
training_config = TrainingConfig(
    num_workers=4,
    cpu_per_worker=2,
    memory_per_worker=4000000000  # 4GB
)
```

## Monitoring and Logging

### Log Levels

- **INFO**: Training progress, model operations
- **WARNING**: Fallback activations, configuration issues
- **ERROR**: Training failures, prediction errors

### Key Log Messages

```
✅ Service initialized successfully
✅ Created dataset with 1000 samples
❌ Distributed training failed: getaddrinfo() error
🔄 Falling back to local XGBoost training...
✅ Local training completed successfully
✅ Training completed in 17.55s
✅ Prediction: [0.63177866]
```

### Health Monitoring

The service provides health endpoints for monitoring:

```bash
curl http://localhost:8000/health
```

Response includes XGBoost service status and available endpoints.

## Security Considerations

### Input Validation

1. **API Requests**: Pydantic model validation
2. **File Paths**: Sanitization and validation
3. **Model Names**: Safe filename generation

### Access Control

1. **Container Isolation**: Docker-based deployment
2. **Network Security**: Internal Ray cluster communication
3. **File Permissions**: Restricted model storage access

## Troubleshooting

### Common Issues

1. **Ray Cluster Connectivity**:
   ```bash
   # Check Ray status
   docker exec seedcore-ray-head ray status
   
   # Check worker connectivity
   docker logs seedcore-workers-ray-worker-1
   ```

2. **Service Health**:
   ```bash
   # Check service health
   curl http://localhost:8000/health
   
   # Check Ray Serve status
   docker exec seedcore-ray-head ray status
   ```

3. **Model Storage**:
   ```bash
   # Check model storage
   docker exec seedcore-ray-head ls -la /data/models/
   
   # Check model metadata
   docker exec seedcore-ray-head cat /data/models/model_name/metadata.json
   ```

### Debug Commands

```bash
# Test XGBoost integration
docker exec seedcore-ray-head python3 /app/docker/test_xgboost_docker.py

# Verify service
docker exec seedcore-ray-head python3 /app/docker/verify_xgboost_service.py

# Check logs
docker logs seedcore-ray-head --tail 100
```

## Best Practices

### Training

1. **Start Small**: Begin with sample data and small datasets
2. **Monitor Resources**: Watch CPU and memory usage
3. **Use Fallback**: Expect and plan for local training fallback
4. **Validate Data**: Ensure data quality before training

### Prediction

1. **Feature Consistency**: Maintain consistent feature order and names
2. **Batch Processing**: Use batch prediction for multiple samples
3. **Model Loading**: Load models once and reuse for multiple predictions

### Deployment

1. **Resource Planning**: Allocate sufficient CPU and memory
2. **Monitoring**: Set up health checks and logging
3. **Backup**: Regularly backup trained models
4. **Testing**: Test with representative data before production

## Future Enhancements

### Planned Features

1. **Model Versioning**: Automatic model versioning and rollback
2. **Hyperparameter Tuning**: Integration with Ray Tune
3. **Model Explainability**: SHAP integration for model interpretation
4. **Distributed Prediction**: Scale prediction across cluster
5. **Model Compression**: Model quantization and optimization

### Performance Improvements

1. **Memory Optimization**: Better memory management for large datasets
2. **Caching**: Intelligent model and data caching
3. **Async Processing**: Non-blocking training and prediction
4. **GPU Optimization**: Better GPU utilization and memory management

---

*This reference document should be updated as the XGBoost integration evolves.* 