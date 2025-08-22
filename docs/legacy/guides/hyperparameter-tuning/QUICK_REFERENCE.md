# Hyperparameter Tuning Quick Reference

## 🚀 Quick Start Commands

### Basic Tuning (Recommended for First-Time Users)
```bash
curl -X POST http://localhost:8000/xgboost/tune \
  -H "Content-Type: application/json" \
  -d '{
    "space_type": "conservative",
    "config_type": "conservative",
    "experiment_name": "quick_test"
  }'
```

### Production Tuning
```bash
curl -X POST http://localhost:8000/xgboost/tune \
  -H "Content-Type: application/json" \
  -d '{
    "space_type": "default",
    "config_type": "default",
    "experiment_name": "production_tuning"
  }'
```

### Aggressive Tuning (Best Results)
```bash
curl -X POST http://localhost:8000/xgboost/tune \
  -H "Content-Type: application/json" \
  -d '{
    "space_type": "aggressive",
    "config_type": "aggressive",
    "experiment_name": "comprehensive_tuning"
  }'
```

## 📊 Monitoring Commands

### Check Tuning Progress
```bash
# Ray Dashboard (real-time progress)
open http://localhost:8265

# Check current model status
curl http://localhost:8000/xgboost/model_info

# List all models
curl http://localhost:8000/xgboost/list_models
```

### Use Best Model
```bash
# Refresh to use the best tuned model
curl -X POST http://localhost:8000/xgboost/refresh_model

# Test the tuned model
curl -X POST http://localhost:8000/xgboost/predict \
  -H "Content-Type: application/json" \
  -d '{
    "features": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
  }'
```

## ⚙️ Configuration Options

### Space Types
| Type | Trials | Time Budget | Use Case |
|------|--------|-------------|----------|
| `conservative` | 5 | 10 min | Quick testing, debugging |
| `default` | 50 | 1 hour | Production tuning |
| `aggressive` | 100 | 2 hours | Best results, comprehensive search |

### Config Types
| Type | Concurrent Trials | Grace Period | Use Case |
|------|------------------|--------------|----------|
| `conservative` | 2 | 5 rounds | Resource-constrained |
| `default` | 4 | 10 rounds | Balanced performance |
| `aggressive` | 8 | 15 rounds | Maximum parallelism |

## 🔧 Custom Tuning

### Custom Search Space
```bash
curl -X POST http://localhost:8000/xgboost/tune \
  -H "Content-Type: application/json" \
  -d '{
    "custom_search_space": {
      "eta": {"type": "loguniform", "lower": 0.01, "upper": 0.3},
      "max_depth": {"type": "randint", "lower": 3, "upper": 8},
      "subsample": {"type": "uniform", "lower": 0.7, "upper": 1.0},
      "colsample_bytree": {"type": "uniform", "lower": 0.7, "upper": 1.0},
      "lambda": {"type": "uniform", "lower": 0.1, "upper": 3.0},
      "alpha": {"type": "uniform", "lower": 0.0, "upper": 2.0},
      "num_boost_round": 100,
      "early_stopping_rounds": 10
    },
    "experiment_name": "custom_tuning"
  }'
```

### Custom Tuning Config
```bash
curl -X POST http://localhost:8000/xgboost/tune \
  -H "Content-Type: application/json" \
  -d '{
    "custom_tune_config": {
      "num_samples": 25,
      "max_concurrent_trials": 3,
      "time_budget_s": 1800,
      "grace_period": 8,
      "reduction_factor": 2
    },
    "experiment_name": "custom_config_tuning"
  }'
```

## 🐛 Troubleshooting

### Common Issues

#### 1. "No best trial found" Error
```bash
# Check Ray cluster status
docker exec seedcore-ray-head ray status

# Verify Ray is running
docker exec seedcore-ray-head python3 -c "import ray; print(ray.is_initialized())"
```

#### 2. Resource Allocation Warnings
- **Normal behavior**: System automatically falls back to local training
- **No action needed**: Local training provides full functionality

#### 3. Model Promotion Failures
```bash
# Check model storage
ls -la /data/models/

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

# Check container logs
docker logs seedcore-ray-head --tail 100
```

## 📈 Expected Results

### Conservative Tuning
- **Duration**: 5-10 minutes
- **Trials**: 5
- **Expected AUC**: 0.75-0.85
- **Best for**: Quick validation, debugging

### Default Tuning
- **Duration**: 30-60 minutes
- **Trials**: 50
- **Expected AUC**: 0.80-0.90
- **Best for**: Production use

### Aggressive Tuning
- **Duration**: 1-2 hours
- **Trials**: 100
- **Expected AUC**: 0.85-0.95
- **Best for**: Best possible results

## 🎯 Best Practices

1. **Start with conservative tuning** to validate setup
2. **Monitor Ray dashboard** during tuning
3. **Check model promotion** after completion
4. **Validate results** with test predictions
5. **Document successful configurations** for future reference

## 📚 Additional Resources

- [Full Hyperparameter Tuning Guide](./HYPERPARAMETER_TUNING_GUIDE.md)
- [Ray Tune Documentation](https://docs.ray.io/en/latest/tune/index.html)
- [XGBoost Parameter Guide](https://xgboost.readthedocs.io/en/latest/parameter.html) 