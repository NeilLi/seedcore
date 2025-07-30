# SeedCore Machine Learning Module

This module provides ML-based features for intelligent system management, including salience scoring, anomaly detection, and predictive scaling.

## Features

### 🎯 Salience Scoring (`salience/`)
- **Purpose**: Rank and prioritize system events, user interactions, and resource usage patterns
- **Use Cases**: 
  - Prioritizing alerts and notifications
  - Ranking user engagement
  - Identifying critical system events

### 🔍 Anomaly Detection (`patterns/`)
- **Purpose**: Detect unusual patterns and anomalies in system behavior
- **Use Cases**:
  - System performance anomalies
  - Security threat detection
  - Predictive maintenance signals

### 📈 Predictive Scaling (`scaling/`)
- **Purpose**: Predict resource requirements and optimize allocation
- **Use Cases**:
  - Auto-scaling based on usage patterns
  - Resource optimization recommendations
  - Performance prediction

## Ray Serve Integration

The ML models are deployed using **Ray Serve** for production-ready model serving with:
- **Automatic scaling** based on demand
- **High availability** with multiple replicas
- **Real-time inference** with low latency
- **Monitoring** through Ray Dashboard

## Quick Start

### 1. Deploy ML Models

```bash
# Make sure Ray cluster is running
cd docker && ./ray-workers.sh start 3

# Deploy the ML Serve application
python scripts/deploy_ml_serve.py
```

### 2. Test the Models

```bash
# Test all ML endpoints
python scripts/test_ml_models.py
```

### 3. Monitor in Ray Dashboard

Visit the Ray Dashboard at `http://localhost:8265/#/serve` to monitor:
- Model deployments
- Request metrics
- Performance statistics
- Scaling behavior

## API Endpoints

### Salience Scoring
```bash
POST http://localhost:8000/salience
Content-Type: application/json

{
  "features": [
    {"type": "system_event", "severity": "high", "frequency": 0.8},
    {"type": "user_interaction", "engagement": 0.6, "duration": 120}
  ]
}
```

### Anomaly Detection
```bash
POST http://localhost:8000/anomaly
Content-Type: application/json

{
  "metrics": [
    {"cpu_usage": 0.95, "memory_usage": 0.8, "timestamp": 1234567890}
  ]
}
```

### Scaling Prediction
```bash
POST http://localhost:8000/scaling
Content-Type: application/json

{
  "usage_patterns": {
    "cpu_avg": 0.7,
    "memory_avg": 0.6,
    "request_rate": 100,
    "response_time": 0.2
  }
}
```

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Salience      │    │   Anomaly       │    │   Scaling       │
│   Scorer        │    │   Detector      │    │   Predictor     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │   Ray Serve     │
                    │   Application   │
                    └─────────────────┘
                                 │
                    ┌─────────────────┐
                    │   Ray Cluster   │
                    │   (Distributed) │
                    └─────────────────┘
```

## Development

### Adding New Models

1. Create your model class in the appropriate submodule
2. Add the deployment to `serve_app.py`
3. Update the deployment script
4. Add tests to `test_ml_models.py`

### Model Training

Models can be trained using Ray's distributed training capabilities:

```python
import ray
from ray import train

# Train your model with Ray
def train_model():
    # Your training logic here
    pass

# Run distributed training
ray.init()
train.run(train_model)
```

## Monitoring

- **Ray Dashboard**: `http://localhost:8265`
- **Prometheus Metrics**: `http://localhost:9090`
- **Grafana Dashboards**: `http://localhost:3000`

## Next Steps

1. **Implement Real Models**: Replace placeholder models with actual ML implementations
2. **Add Training Pipelines**: Set up automated model training and deployment
3. **Enhance Monitoring**: Add custom metrics and alerts
4. **Scale Infrastructure**: Add GPU support for complex models 