# XGBoost Daily Reference

**Last Updated**: 2025-08-03  
**Version**: 1.0  
**Cluster Status**: ✅ Operational

## Quick Start

### 1. Start the Cluster
```bash
cd /home/ubuntu/project/seedcore/docker
./start-cluster.sh restart
```

### 2. Wait for Services to be Ready
```bash
# Wait 2-3 minutes for full startup
sleep 120

# Check health with timestamp
echo "$(date '+%Y-%m-%d %H:%M:%S') - Checking service health..."
curl http://localhost:8000/health
echo "$(date '+%Y-%m-%d %H:%M:%S') - Health check completed"
```

### 3. Run Integration Test
```bash
echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting XGBoost integration test..."
docker exec seedcore-ray-head python3 /app/docker/test_xgboost_docker.py
echo "$(date '+%Y-%m-%d %H:%M:%S') - Integration test completed"
```

## Common Operations

### Training a Model

#### Quick Training with Sample Data
```bash
# Generate timestamped model name
MODEL_NAME="quick_test_model_$(date '+%Y%m%d_%H%M%S')"

echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting quick training with model: $MODEL_NAME"

curl -X POST http://localhost:8000/xgboost/train \
  -H "Content-Type: application/json" \
  -d '{
    "use_sample_data": true,
    "sample_size": 10000,
    "sample_features": 20,
    "name": "'$MODEL_NAME'"
  }'

echo "$(date '+%Y-%m-%d %H:%M:%S') - Quick training completed for model: $MODEL_NAME"
```

#### Training with Custom Configuration
```bash
# Generate timestamped model name
MODEL_NAME="production_model_$(date '+%Y%m%d_%H%M%S')"

echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting production training with model: $MODEL_NAME"

curl -X POST http://localhost:8000/xgboost/train \
  -H "Content-Type: application/json" \
  -d '{
    "use_sample_data": true,
    "sample_size": 50000,
    "sample_features": 30,
    "name": "'$MODEL_NAME'",
    "xgb_config": {
      "objective": "binary:logistic",
      "eval_metric": ["logloss", "auc"],
      "eta": 0.05,
      "max_depth": 6,
      "tree_method": "hist",
      "num_boost_round": 100
    },
    "training_config": {
      "num_workers": 3,
      "use_gpu": false,
      "cpu_per_worker": 1
    }
  }'

echo "$(date '+%Y-%m-%d %H:%M:%S') - Production training completed for model: $MODEL_NAME"
```

### Making Predictions

#### Single Prediction
```bash
curl -X POST http://localhost:8000/xgboost/predict \
  -H "Content-Type: application/json" \
  -d '{
    "features": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    "path": "/data/models/production_model/model.xgb"
  }'
```

#### Prediction with Loaded Model
```bash
# First load the model
curl -X POST http://localhost:8000/xgboost/load_model \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/data/models/production_model/model.xgb"
  }'

# Then predict (model will be loaded automatically)
curl -X POST http://localhost:8000/xgboost/predict \
  -H "Content-Type: application/json" \
  -d '{
    "features": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
  }'
```

### Model Management

#### List All Models
```bash
curl http://localhost:8000/xgboost/list_models
```

#### Get Model Information
```bash
curl http://localhost:8000/xgboost/model_info
```

#### Load a Specific Model
```bash
curl -X POST http://localhost:8000/xgboost/load_model \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/data/models/my_model/model.xgb"
  }'
```

#### Delete a Model
```bash
curl -X DELETE http://localhost:8000/xgboost/delete_model \
  -H "Content-Type: application/json" \
  -d '{
    "name": "old_model"
  }'
```

## Health Checks

### Service Health
```bash
echo "$(date '+%Y-%m-%d %H:%M:%S') - Checking service health..."
curl http://localhost:8000/health
echo "$(date '+%Y-%m-%d %H:%M:%S') - Health check completed"
```

### Ray Cluster Status
```bash
echo "$(date '+%Y-%m-%d %H:%M:%S') - Checking Ray cluster status..."
docker exec seedcore-ray-head ray status
echo "$(date '+%Y-%m-%d %H:%M:%S') - Ray cluster status check completed"
```

### Container Status
```bash
echo "$(date '+%Y-%m-%d %H:%M:%S') - Checking container status..."
docker ps | grep ray
echo "$(date '+%Y-%m-%d %H:%M:%S') - Container status check completed"
```

## Monitoring

### Check Logs
```bash
# Ray head logs with timestamp
echo "$(date '+%Y-%m-%d %H:%M:%S') - Checking Ray head logs..."
docker logs seedcore-ray-head --tail 50

# Ray worker logs with timestamp
echo "$(date '+%Y-%m-%d %H:%M:%S') - Checking Ray worker logs..."
docker logs seedcore-workers-ray-worker-1 --tail 50

# Follow logs in real-time with timestamp
echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting real-time log monitoring..."
docker logs seedcore-ray-head -f
```

### Check Resource Usage
```bash
# CPU and memory usage with timestamp
echo "$(date '+%Y-%m-%d %H:%M:%S') - Checking resource usage..."
docker stats seedcore-ray-head seedcore-workers-ray-worker-1

# Disk usage for models with timestamp
echo "$(date '+%Y-%m-%d %H:%M:%S') - Checking model storage usage..."
docker exec seedcore-ray-head du -sh /data/models/
echo "$(date '+%Y-%m-%d %H:%M:%S') - Resource usage check completed"
```

### Check Model Storage
```bash
# List all models with timestamp
echo "$(date '+%Y-%m-%d %H:%M:%S') - Listing all models..."
docker exec seedcore-ray-head ls -la /data/models/

# Check specific model with timestamp
echo "$(date '+%Y-%m-%d %H:%M:%S') - Checking specific model..."
docker exec seedcore-ray-head ls -la /data/models/production_model/

# View model metadata with timestamp
echo "$(date '+%Y-%m-%d %H:%M:%S') - Viewing model metadata..."
docker exec seedcore-ray-head cat /data/models/production_model/metadata.json
echo "$(date '+%Y-%m-%d %H:%M:%S') - Model storage check completed"
```

## Troubleshooting

### Common Issues and Solutions

#### 1. Service Not Responding
```bash
echo "$(date '+%Y-%m-%d %H:%M:%S') - Troubleshooting: Service not responding"

# Check if containers are running
echo "$(date '+%Y-%m-%d %H:%M:%S') - Checking container status..."
docker ps | grep ray

# Restart if needed
echo "$(date '+%Y-%m-%d %H:%M:%S') - Restarting cluster..."
./start-cluster.sh restart

# Wait and check health
echo "$(date '+%Y-%m-%d %H:%M:%S') - Waiting for services to start..."
sleep 60
echo "$(date '+%Y-%m-%d %H:%M:%S') - Checking health after restart..."
curl http://localhost:8000/health
echo "$(date '+%Y-%m-%d %H:%M:%S') - Service troubleshooting completed"
```

#### 2. Training Fails
```bash
# Check logs for errors
docker logs seedcore-ray-head --tail 100 | grep -E "(error|Error|ERROR|failed|Failed)"

# Run test to verify functionality
docker exec seedcore-ray-head python3 /app/docker/test_xgboost_docker.py
```

#### 3. Prediction Errors
```bash
# Check if model exists
docker exec seedcore-ray-head ls -la /data/models/

# Verify model file
docker exec seedcore-ray-head file /data/models/my_model/model.xgb

# Check model metadata
docker exec seedcore-ray-head cat /data/models/my_model/metadata.json
```

#### 4. Ray Cluster Issues
```bash
# Check Ray status
docker exec seedcore-ray-head ray status

# Check worker connectivity
docker exec seedcore-workers-ray-worker-1 ps aux | grep ray

# Restart workers if needed
./start-cluster.sh restart
```

### Debug Commands

#### Test XGBoost Integration
```bash
docker exec seedcore-ray-head python3 /app/docker/test_xgboost_docker.py
```

#### Verify Service
```bash
docker exec seedcore-ray-head python3 /app/docker/verify_xgboost_service.py
```

#### Check Python Environment
```bash
docker exec seedcore-ray-head python3 -c "
import ray
import xgboost
import xgboost_ray
print('✅ All imports successful')
print(f'Ray version: {ray.__version__}')
print(f'XGBoost version: {xgboost.__version__}')
print(f'XGBoost-Ray version: {xgboost_ray.__version__}')
"
```

## Performance Tuning

### Resource Configuration

#### Conservative Settings (Development)
```json
{
  "training_config": {
    "num_workers": 1,
    "use_gpu": false,
    "cpu_per_worker": 1
  }
}
```

#### Production Settings
```json
{
  "training_config": {
    "num_workers": 3,
    "use_gpu": false,
    "cpu_per_worker": 2
  }
}
```

#### High-Performance Settings
```json
{
  "training_config": {
    "num_workers": 4,
    "use_gpu": true,
    "cpu_per_worker": 4
  }
}
```

### Training Parameters

#### Fast Training (Quick Tests)
```json
{
  "xgb_config": {
    "objective": "binary:logistic",
    "eval_metric": ["logloss"],
    "eta": 0.3,
    "max_depth": 3,
    "tree_method": "hist",
    "num_boost_round": 10
  }
}
```

#### Balanced Training (Development)
```json
{
  "xgb_config": {
    "objective": "binary:logistic",
    "eval_metric": ["logloss", "auc"],
    "eta": 0.1,
    "max_depth": 5,
    "tree_method": "hist",
    "num_boost_round": 50
  }
}
```

#### Production Training
```json
{
  "xgb_config": {
    "objective": "binary:logistic",
    "eval_metric": ["logloss", "auc"],
    "eta": 0.05,
    "max_depth": 6,
    "tree_method": "hist",
    "num_boost_round": 100,
    "early_stopping_rounds": 10
  }
}
```

## Data Formats

### Sample Data Generation
```bash
# Small dataset for testing
curl -X POST http://localhost:8000/xgboost/train \
  -H "Content-Type: application/json" \
  -d '{
    "use_sample_data": true,
    "sample_size": 1000,
    "sample_features": 10,
    "name": "test_model"
  }'
```

### CSV Data Loading
```bash
# Upload CSV file first, then train
curl -X POST http://localhost:8000/xgboost/train \
  -H "Content-Type: application/json" \
  -d '{
    "data_source": "/data/my_data.csv",
    "data_format": "csv",
    "label_column": "target",
    "name": "csv_model"
  }'
```

### Parquet Data Loading
```bash
curl -X POST http://localhost:8000/xgboost/train \
  -H "Content-Type: application/json" \
  -d '{
    "data_source": "/data/my_data.parquet",
    "data_format": "parquet",
    "label_column": "target",
    "name": "parquet_model"
  }'
```

## Batch Operations

### Batch Prediction Script
```python
import requests
import json

# Load model
response = requests.post(
    "http://localhost:8000/xgboost/load_model",
    json={"path": "/data/models/production_model/model.xgb"}
)

# Batch predictions
features_batch = [
    [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0] * 2,  # 20 features
    [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 0.1] * 2,
    [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 0.1, 0.2] * 2,
]

predictions = []
for features in features_batch:
    response = requests.post(
        "http://localhost:8000/xgboost/predict",
        json={"features": features}
    )
    result = response.json()
    predictions.append(result["prediction"])

print(f"Predictions: {predictions}")
```

## Maintenance

### Regular Tasks

#### Daily
- [ ] Check service health: `curl http://localhost:8000/health`
- [ ] Monitor logs for errors: `docker logs seedcore-ray-head --tail 100`
- [ ] Check resource usage: `docker stats seedcore-ray-head`

#### Weekly
- [ ] Clean up old models: `docker exec seedcore-ray-head ls -la /data/models/`
- [ ] Check disk usage: `docker exec seedcore-ray-head du -sh /data/models/`
- [ ] Run full integration test: `docker exec seedcore-ray-head python3 /app/docker/test_xgboost_docker.py`

#### Monthly
- [ ] Update dependencies if needed
- [ ] Review and clean up model storage
- [ ] Check for performance improvements
- [ ] Review logs for patterns

### Backup and Recovery

#### Backup Models
```bash
# Create backup of all models
docker exec seedcore-ray-head tar -czf /tmp/models_backup_$(date +%Y%m%d).tar.gz -C /data/models .

# Copy backup to host
docker cp seedcore-ray-head:/tmp/models_backup_$(date +%Y%m%d).tar.gz ./backups/
```

#### Restore Models
```bash
# Copy backup to container
docker cp ./backups/models_backup_20241201.tar.gz seedcore-ray-head:/tmp/

# Extract backup
docker exec seedcore-ray-head tar -xzf /tmp/models_backup_20241201.tar.gz -C /data/models/
```

## Quick Reference Commands

### Essential Commands
```bash
# Health check
curl http://localhost:8000/health

# List models
curl http://localhost:8000/xgboost/list_models

# Quick training
curl -X POST http://localhost:8000/xgboost/train -H "Content-Type: application/json" -d '{"use_sample_data": true, "sample_size": 1000, "name": "test"}'

# Quick prediction
curl -X POST http://localhost:8000/xgboost/predict -H "Content-Type: application/json" -d '{"features": [0.1]*20}'

# Check logs
docker logs seedcore-ray-head --tail 20

# Test integration
docker exec seedcore-ray-head python3 /app/docker/test_xgboost_docker.py
```

### Container Management
```bash
# Restart cluster
./start-cluster.sh restart

# Check containers
docker ps | grep ray

# Check resource usage
docker stats seedcore-ray-head seedcore-workers-ray-worker-1

# Follow logs
docker logs seedcore-ray-head -f
```

### Model Management
```bash
# List models
docker exec seedcore-ray-head ls -la /data/models/

# Check model size
docker exec seedcore-ray-head du -sh /data/models/*

# View model metadata
docker exec seedcore-ray-head cat /data/models/model_name/metadata.json

# Delete model
docker exec seedcore-ray-head rm -rf /data/models/model_name
```

---

*This daily reference should be updated as new features and best practices are discovered.* 