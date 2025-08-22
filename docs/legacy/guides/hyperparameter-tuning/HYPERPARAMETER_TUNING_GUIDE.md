# Hyperparameter Tuning with Ray Tune

This guide details how to automate hyperparameter sweeps for your XGBoost models using **Ray Tune**, integrated with the SeedCore Cognitive Organism Architecture.

## Overview

The hyperparameter tuning system provides:
- **Automated hyperparameter optimization** using Ray Tune
- **Multiple search space configurations** (conservative, default, aggressive)
- **ASHA scheduler** for early stopping of underperforming trials
- **Model promotion** to stable, production-ready paths
- **Flashbulb memory integration** for logging high-impact tuning events
- **Seamless integration** with existing XGBoost training pipeline

## Architecture Integration

### Flywheel Optimization Loop

In the Cognitive Organism Architecture, hyperparameter tuning implements the optional "slow-cadence" **Flywheel Loop** that performs model optimization to improve the organism's long-term performance.

- **Trigger**: Manual, scheduled, or automatic when monitoring detects performance degradation
- **Mechanism**: The **Utility Organ** orchestrates tuning jobs using the entire Ray cluster
- **Evolutionary Impact**: Successful tuning enhances **Accuracy** and **Smartness** axes
- **Memory & Energy**: High-impact tuning events are logged to **Flashbulb Memory (`M_fb`)** for durable recall

## Quick Start

### 1. Basic Tuning

```bash
# Start a conservative tuning sweep (recommended for first-time users)
curl -X POST http://localhost:8000/xgboost/tune \
  -H "Content-Type: application/json" \
  -d '{
    "space_type": "conservative",
    "config_type": "conservative", 
    "experiment_name": "my_first_tuning"
  }'
```

**Expected Response:**
```json
{
  "status": "success",
  "experiment_name": "my_first_tuning",
  "best_trial": {
    "trial_id": "abc123_00000",
    "auc": 0.85,
    "logloss": 0.45,
    "training_time": 45.2,
    "config": {
      "eta": 0.1,
      "max_depth": 6,
      "subsample": 0.8,
      "colsample_bytree": 0.8,
      "lambda": 2.0,
      "alpha": 1.0
    }
  },
  "promotion": {
    "status": "success",
    "blessed_path": "/data/models/utility_risk_model_latest/model.xgb"
  },
  "total_trials": 5,
  "experiment_path": "/home/ray/ray_results/tune_xgb_trainable_2025-08-04_10-52-31"
}
```

### 2. Monitor Progress

```bash
# Check Ray Dashboard for real-time progress
open http://localhost:8265

# Check current model status
curl http://localhost:8000/xgboost/model_info

# List all available models
curl http://localhost:8000/xgboost/list_models
```

### 3. Use the Best Model

```bash
# Refresh to use the best tuned model
curl -X POST http://localhost:8000/xgboost/refresh_model

# Make predictions with the tuned model
curl -X POST http://localhost:8000/xgboost/predict \
  -H "Content-Type: application/json" \
  -d '{
    "features": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
  }'
```

## Search Space Configurations

### Conservative Space
- **Use case**: Quick testing, development, limited resources
- **Trials**: 5
- **Time budget**: 10 minutes
- **Parameters**: Narrower ranges, focused exploration
- **Best for**: First-time users, debugging, quick validation

```python
XGBOOST_CONSERVATIVE_SPACE = {
    "eta": tune.loguniform(5e-2, 1.5e-1),      # 0.05 to 0.15
    "max_depth": tune.randint(4, 8),           # 4 to 7
    "subsample": tune.uniform(0.7, 0.9),       # 0.7 to 0.9
    "colsample_bytree": tune.uniform(0.7, 0.9), # 0.7 to 0.9
    "lambda": tune.uniform(1.0, 3.0),          # 1.0 to 3.0
    "alpha": tune.uniform(0.0, 2.0),           # 0.0 to 2.0
    "num_boost_round": 20,                     # Reduced for faster testing
    "early_stopping_rounds": 5                 # Early stopping for efficiency
}
```

### Default Space
- **Use case**: Production tuning, balanced performance
- **Trials**: 50
- **Time budget**: 1 hour
- **Parameters**: Standard ranges, comprehensive exploration

```python
XGBOOST_SEARCH_SPACE = {
    "eta": tune.loguniform(1e-2, 2e-1),       # 0.01 to 0.2
    "max_depth": tune.randint(4, 11),          # 4 to 10
    "subsample": tune.uniform(0.6, 0.9),       # 0.6 to 0.9
    "colsample_bytree": tune.uniform(0.6, 0.9), # 0.6 to 0.9
    "lambda": tune.uniform(1.0, 4.0),          # 1.0 to 4.0
    "alpha": tune.uniform(0.0, 3.0),           # 0.0 to 3.0
    "num_boost_round": 200
}
```

### Aggressive Space
- **Use case**: Maximum performance, extensive exploration
- **Trials**: 100
- **Time budget**: 2 hours
- **Parameters**: Wide ranges, additional parameters

```python
XGBOOST_AGGRESSIVE_SPACE = {
    "eta": tune.loguniform(1e-3, 3e-1),       # 0.001 to 0.3
    "max_depth": tune.randint(3, 12),          # 3 to 11
    "subsample": tune.uniform(0.5, 1.0),       # 0.5 to 1.0
    "colsample_bytree": tune.uniform(0.5, 1.0), # 0.5 to 1.0
    "colsample_bylevel": tune.uniform(0.5, 1.0), # 0.5 to 1.0
    "lambda": tune.uniform(0.1, 5.0),          # 0.1 to 5.0
    "alpha": tune.uniform(0.0, 5.0),           # 0.0 to 5.0
    "gamma": tune.uniform(0.0, 1.0),           # 0.0 to 1.0
    "min_child_weight": tune.uniform(1.0, 10.0), # 1.0 to 10.0
    "num_boost_round": tune.randint(100, 300)  # 100 to 299
}
```

## API Reference

### POST `/xgboost/tune`

Run a hyperparameter tuning sweep.

**Request Body:**
```json
{
  "space_type": "default",                    // "conservative", "default", "aggressive"
  "config_type": "default",                   // "conservative", "default", "aggressive"
  "custom_search_space": null,                // Optional custom search space
  "custom_tune_config": null,                 // Optional custom tuning config
  "experiment_name": "xgboost_tuning"         // Name for the experiment
}
```

**Response:**
```json
{
  "status": "success",
  "experiment_name": "xgboost_tuning",
  "best_trial": {
    "trial_id": "tune_trial_abc123",
    "auc": 0.975,
    "logloss": 0.089,
    "training_time": 45.23,
    "config": {
      "eta": 0.08,
      "max_depth": 7,
      "subsample": 0.8,
      "colsample_bytree": 0.85,
      "lambda": 2.1,
      "alpha": 1.5
    }
  },
  "promotion": {
    "status": "success",
    "source_path": "/data/models/tune_trial_abc123/model.xgb",
    "blessed_path": "/data/models/utility_risk_model_latest/model.xgb",
    "metadata_path": "/data/models/utility_risk_model_latest/tuning_metadata.json"
  },
  "total_trials": 50,
  "experiment_path": "/tmp/ray_results/xgboost_tuning"
}
```

### POST `/xgboost/refresh_model`

Refresh the model to use the latest promoted model from tuning.

**Response:**
```json
{
  "status": "success",
  "message": "Model refreshed successfully",
  "current_model_path": "/data/models/utility_risk_model_latest/model.xgb"
}
```

## Custom Tuning

### Custom Search Space

The system supports both Ray Tune objects and dictionary format for custom search spaces:

**Dictionary Format (Recommended for API calls):**
```python
custom_search_space = {
    "objective": "binary:logistic",
    "eval_metric": ["logloss", "auc"],
    "tree_method": "hist",
    "eta": {"type": "loguniform", "lower": 0.01, "upper": 0.3},
    "max_depth": {"type": "randint", "lower": 3, "upper": 8},
    "subsample": {"type": "uniform", "lower": 0.7, "upper": 1.0},
    "colsample_bytree": {"type": "uniform", "lower": 0.7, "upper": 1.0},
    "lambda": {"type": "uniform", "lower": 0.1, "upper": 3.0},
    "alpha": {"type": "uniform", "lower": 0.0, "upper": 2.0},
    "num_boost_round": 100,
    "early_stopping_rounds": 10
}
```

**Ray Tune Objects (For direct Python usage):**
```python
from ray import tune

custom_search_space = {
    "objective": "binary:logistic",
    "eval_metric": ["logloss", "auc"],
    "tree_method": "hist",
    "eta": tune.loguniform(0.01, 0.3),
    "max_depth": tune.randint(3, 8),
    "subsample": tune.uniform(0.7, 1.0),
    "colsample_bytree": tune.uniform(0.7, 1.0),
    "lambda": tune.uniform(0.1, 3.0),
    "alpha": tune.uniform(0.0, 2.0),
    "num_boost_round": 100,
    "early_stopping_rounds": 10
}
```

### Custom Tuning Config

```python
custom_tune_config = {
    "num_samples": 25,              # Number of trials
    "max_concurrent_trials": 4,     # Concurrent trials
    "time_budget_s": 1800,          # 30 minutes
    "grace_period": 10,             # Minimum training iterations
    "reduction_factor": 2           # ASHA reduction factor
}
```

**Note**: In modern Ray Tune, experiment names and local directories are handled automatically by the framework. The `experiment_name` parameter is used for logging and identification but doesn't affect the file system structure.

## Monitoring and Debugging

### Ray Dashboard

Access the Ray Dashboard at `http://localhost:8265` to monitor:
- Trial progress and status
- Real-time metrics (AUC, LogLoss)
- Resource utilization
- Trial configurations

### Logs

```bash
# Check tuning logs
docker logs seedcore-ray-head | grep -i tune

# Check model promotion logs
docker logs seedcore-ray-head | grep -i "model promoted"
```

### Flashbulb Memory

Tuning events are automatically logged to flashbulb memory:

```json
{
  "event_type": "model_tuning_completed",
  "timestamp": 1640995200.0,
  "outcome": "success",
  "experiment_name": "xgboost_tuning",
  "best_model_path": "/data/models/utility_risk_model_latest/model.xgb",
  "metric_achieved": {
    "auc": 0.975,
    "logloss": 0.089
  },
  "best_params": {
    "eta": 0.08,
    "max_depth": 7,
    "subsample": 0.8
  },
  "salience": 0.95
}
```

## Best Practices

### 1. Start Conservative

Begin with conservative tuning to validate the pipeline:

```bash
curl -X POST http://localhost:8000/xgboost/tune \
  -d '{"space_type": "conservative", "config_type": "conservative"}'
```

### 2. Monitor Resources

Watch resource usage during tuning:
- CPU utilization across workers
- Memory consumption
- Network I/O for distributed training

### 3. Use Appropriate Time Budgets

- **Development**: 30 minutes (conservative)
- **Production**: 1-2 hours (default/aggressive)
- **Research**: 4+ hours (custom aggressive)

### 4. Validate Results

Always validate the best model:

```bash
# Refresh to best model
curl -X POST http://localhost:8000/xgboost/refresh_model

# Test on validation set
curl -X POST http://localhost:8000/xgboost/batch_predict \
  -d '{"data_source": "/data/validation.csv", "feature_columns": ["f1", "f2", ...]}'
```

### 5. Track Experiments

Use meaningful experiment names:

```bash
curl -X POST http://localhost:8000/xgboost/tune \
  -d '{"experiment_name": "production_model_v2_2024_01"}'
```

## Troubleshooting

### Common Issues

1. **Trials failing**: Check resource allocation and dataset availability
2. **Poor performance**: Verify search space ranges and evaluation metrics
3. **Timeouts**: Increase time budget or reduce trial complexity
4. **Memory issues**: Reduce concurrent trials or worker memory

### Debug Commands

```bash
# Check Ray cluster status
docker exec seedcore-ray-head ray status

# Check tuning results
ls -la /tmp/ray_results/

# Check promoted models
ls -la /data/models/utility_risk_model_latest/

# Check flashbulb memory
curl http://localhost:8000/mfb/incidents
```

## Integration with Cognitive Organism

### Energy Model Impact

Successful tuning reduces energy consumption:
- **Lower `pair` energy**: Better model accuracy reduces prediction errors
- **Lower `mem` energy**: Optimized models require less memory
- **Net positive delta**: Long-term energy savings outweigh tuning costs

### Memory Integration

- **Working Memory**: Tuning results cached for quick access
- **Long-term Memory**: Model configurations and performance history
- **Flashbulb Memory**: High-impact tuning events for durable recall

### Evolution Tracking

Tuning contributes to organism evolution:
- **Accuracy axis**: Improved model performance
- **Smartness axis**: Better hyperparameter selection
- **Adaptability**: Learning from tuning history

## Advanced Features

### Scheduled Tuning

Set up automated tuning schedules:

```python
# Weekly tuning job
import schedule
import time

def weekly_tuning():
    requests.post("http://localhost:8000/xgboost/tune", 
                 json={"space_type": "default", "experiment_name": "weekly_tuning"})

schedule.every().monday.at("02:00").do(weekly_tuning)

while True:
    schedule.run_pending()
    time.sleep(60)
```

### Performance Monitoring

Monitor model performance and trigger tuning:

```python
def check_performance():
    response = requests.get("http://localhost:8000/xgboost/model_info")
    current_auc = response.json().get("metrics", {}).get("auc", 0.0)
    
    if current_auc < 0.90:  # Performance threshold
        requests.post("http://localhost:8000/xgboost/tune",
                     json={"space_type": "conservative", "experiment_name": "performance_tuning"})
```

### Multi-Objective Tuning

For complex scenarios, consider multiple objectives:

```python
custom_search_space = {
    "eta": tune.loguniform(1e-2, 2e-1),
    "max_depth": tune.randint(4, 11),
    # Add regularization for model size
    "lambda": tune.uniform(1.0, 4.0),
    "alpha": tune.uniform(0.0, 3.0),
    # Add training speed considerations
    "num_boost_round": tune.randint(50, 200)
}
```

## Troubleshooting

### Common Issues and Solutions

#### 1. "No best trial found" Error

**Symptoms:**
```json
{
  "status": "error",
  "error": "No best trial found for the given metric: mean_accuracy"
}
```

**Causes:**
- Trials are failing to complete
- Resource allocation issues
- Training configuration problems

**Solutions:**
```bash
# Check Ray cluster resources
docker exec seedcore-ray-head ray status

# Verify Ray is running
docker exec seedcore-ray-head python3 -c "import ray; print(ray.is_initialized())"

# Check available resources
docker exec seedcore-ray-head python3 -c "import ray; print(ray.available_resources())"
```

#### 2. Resource Allocation Warnings

**Symptoms:**
```
❌ Distributed training failed: No trial resources are available for launching the actor
```

**Solutions:**
- The system automatically falls back to local training
- This is normal and expected behavior
- Local training still provides full functionality

#### 3. Slow Training Performance

**Symptoms:**
- Trials taking longer than expected
- Low resource utilization

**Solutions:**
```bash
# Use conservative tuning for faster results
curl -X POST http://localhost:8000/xgboost/tune \
  -H "Content-Type: application/json" \
  -d '{
    "space_type": "conservative",
    "config_type": "conservative",
    "experiment_name": "quick_test"
  }'
```

#### 4. Model Promotion Failures

**Symptoms:**
```json
{
  "promotion": {
    "status": "error",
    "error": "Source model not found"
  }
}
```

**Solutions:**
```bash
# Check model storage
ls -la /data/models/

# Verify model files exist
find /data/models -name "*.xgb" -type f

# Refresh model manually
curl -X POST http://localhost:8000/xgboost/refresh_model
```

### Debug Commands

```bash
# Check Ray cluster status
docker exec seedcore-ray-head ray status

# Check tuning results
ls -la /tmp/ray_results/

# Check promoted models
ls -la /data/models/utility_risk_model_latest/

# Check flashbulb memory
curl http://localhost:8000/mfb/incidents

# Monitor Ray dashboard
open http://localhost:8265

# Check container logs
docker logs seedcore-ray-head --tail 100
```

### Performance Optimization

#### For Production Use:
1. **Use default or aggressive space** for better results
2. **Increase time budget** for comprehensive search
3. **Monitor resource usage** during tuning
4. **Schedule tuning during off-peak hours**

#### For Development:
1. **Use conservative space** for quick iteration
2. **Set shorter time budgets** for faster feedback
3. **Focus on key parameters** (eta, max_depth, subsample)

### Best Practices

1. **Start with conservative tuning** to validate setup
2. **Monitor Ray dashboard** during tuning
3. **Check model promotion** after completion
4. **Validate results** with test predictions
5. **Document successful configurations** for future reference

## Conclusion

The hyperparameter tuning system provides a powerful, automated way to optimize XGBoost models within the SeedCore Cognitive Organism Architecture. By following the best practices outlined in this guide, you can achieve significant performance improvements while maintaining system stability and resource efficiency.

**Key Benefits:**
- ✅ **Automated optimization** with minimal manual intervention
- ✅ **Multiple search strategies** for different use cases
- ✅ **Seamless integration** with existing ML pipeline
- ✅ **Flashbulb memory logging** for high-impact events
- ✅ **Model promotion** for production deployment
- ✅ **Resource-efficient** with automatic fallback mechanisms

For more information, see:
- [Ray Tune Documentation](https://docs.ray.io/en/latest/tune/index.html)
- [XGBoost Parameter Guide](https://xgboost.readthedocs.io/en/latest/parameter.html)
- [SeedCore Architecture Guide](../architecture/ARCHITECTURE.md) 