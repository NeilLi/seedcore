# Salience Scoring Service Operations Guide

This guide covers the operation and management of the ML-based salience scoring service within the SeedCore container infrastructure.

## 🎯 Overview

The Salience Scoring Service replaces the simple heuristic-based scoring (`risk * severity`) with a sophisticated ML model that considers 11 different features for intelligent salience prediction.

### Key Features
- **GradientBoostingRegressor**: ML model for intelligent salience scoring
- **Circuit Breaker Pattern**: Automatic fallback to simple scoring when ML service is unavailable
- **Ray Serve Integration**: Production-ready model serving with auto-scaling
- **Comprehensive API**: REST endpoints for scoring, health checks, and monitoring
- **Agent Integration**: Seamless integration with RayAgent for real-time scoring

## 🚀 Quick Start

### 1. Start the Complete System

```bash
cd docker
./start-cluster.sh
```

This starts all services including:
- Databases (PostgreSQL, MySQL, Neo4j)
- Ray cluster (head + workers)
- SeedCore API with salience scoring
- Monitoring stack (Prometheus, Grafana)

### 2. Train the Salience Model

```bash
# From project root
python scripts/train_salience_model.py
```

This will:
- Generate synthetic training data (or use historical data if available)
- Train a GradientBoostingRegressor model
- Save the model to `src/seedcore/ml/models/salience_model.pkl`
- Display training metrics (MSE, R²)

### 3. Deploy Ray Serve

```bash
# From project root
python scripts/deploy_ml_serve.py
```

This deploys the ML models as Ray Serve applications.

### 4. Validate the Service

```bash
# From project root
python scripts/validate_salience_container.py
```

This runs comprehensive tests including:
- Container status checks
- API health validation
- Salience scoring tests
- Agent integration tests
- Monitoring integration

## 📊 API Endpoints

### Salience Scoring Endpoints

#### Single Scoring
```bash
curl -X POST "http://localhost:8002/salience/score" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "task_risk": 0.8,
      "failure_severity": 0.9,
      "agent_capability": 0.7,
      "system_load": 0.6,
      "memory_usage": 0.5,
      "cpu_usage": 0.4,
      "response_time": 2.0,
      "error_rate": 0.1,
      "task_complexity": 0.8,
      "user_impact": 0.9,
      "business_criticality": 0.8,
      "agent_memory_util": 0.3
    }
  ]'
```

**Response:**
```json
{
  "scores": [0.847],
  "count": 1,
  "processing_time_ms": 45.2,
  "model": "gradient_boosting_regressor",
  "status": "success"
}
```

#### Batch Scoring
```bash
curl -X POST "http://localhost:8002/salience/score/batch" \
  -H "Content-Type: application/json" \
  -d '{
    "batch_id": "batch_001",
    "features": [
      {
        "task_risk": 0.8,
        "failure_severity": 0.9,
        "agent_capability": 0.7,
        "system_load": 0.6,
        "memory_usage": 0.5,
        "cpu_usage": 0.4,
        "response_time": 2.0,
        "error_rate": 0.1,
        "task_complexity": 0.8,
        "user_impact": 0.9,
        "business_criticality": 0.8,
        "agent_memory_util": 0.3
      },
      {
        "task_risk": 0.3,
        "failure_severity": 0.2,
        "agent_capability": 0.9,
        "system_load": 0.3,
        "memory_usage": 0.2,
        "cpu_usage": 0.3,
        "response_time": 0.5,
        "error_rate": 0.0,
        "task_complexity": 0.3,
        "user_impact": 0.2,
        "business_criticality": 0.3,
        "agent_memory_util": 0.1
      }
    ]
  }'
```

#### Health Check
```bash
curl "http://localhost:8002/salience/health"
```

**Response:**
```json
{
  "status": "healthy",
  "service": "salience_scoring",
  "model_loaded": true,
  "response_time_ms": 12.5,
  "test_score": 0.847,
  "circuit_breaker": {
    "failure_count": 0,
    "is_open": false
  }
}
```

#### Service Information
```bash
curl "http://localhost:8002/salience/info"
```

**Response:**
```json
{
  "service": "salience_scoring",
  "model_type": "gradient_boosting_regressor",
  "features": [
    "task_risk", "failure_severity", "agent_capability", "system_load",
    "memory_usage", "cpu_usage", "response_time", "error_rate",
    "task_complexity", "user_impact", "business_criticality"
  ],
  "endpoints": {
    "score": "POST /salience/score",
    "batch_score": "POST /salience/score/batch",
    "health": "GET /salience/health",
    "info": "GET /salience/info"
  },
  "circuit_breaker": {
    "enabled": true,
    "threshold": 5,
    "timeout_seconds": 60,
    "fallback_enabled": true
  }
}
```

## 🔧 Agent Integration

### Automatic Integration

The salience scoring is automatically integrated with RayAgent. When agents execute high-stakes tasks, the system:

1. **Extracts Features**: Collects 11 features from agent state and task context
2. **Calls ML Service**: Requests salience score from Ray Serve
3. **Circuit Breaker**: Falls back to simple scoring if ML service is unavailable
4. **Flashbulb Memory**: Logs high-salience incidents automatically

### Manual Agent Testing

```bash
# Create a test agent
curl -X POST "http://localhost:8002/tier0/agents/create" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "test_agent",
    "role_probs": {"E": 0.7, "S": 0.2, "O": 0.1}
  }'

# Execute a high-stakes task
curl -X POST "http://localhost:8002/tier0/agents/test_agent/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "critical_task",
    "type": "high_stakes_operation",
    "complexity": 0.9,
    "risk": 0.8,
    "user_impact": 0.9,
    "business_criticality": 0.9
  }'
```

## 📈 Monitoring & Observability

### Grafana Dashboards

Access Grafana at `http://localhost:3000` (admin/seedcore):

- **SeedCore System Overview**: System metrics and agent performance
- **Ray Cluster Monitoring**: Ray cluster health and resource utilization
- **Salience Service Metrics**: Salience scoring performance and circuit breaker status

### Prometheus Metrics

Access Prometheus at `http://localhost:9090`:

- **API Metrics**: Request rates, response times, error rates
- **Ray Metrics**: Cluster health, task execution, resource usage
- **System Metrics**: CPU, memory, disk, network usage

### Ray Dashboard

Access Ray Dashboard at `http://localhost:8265`:

- **Cluster Overview**: Node status, resource allocation
- **Ray Serve**: Model deployment status and performance
- **Task Monitoring**: Job execution and resource utilization

## 🐛 Troubleshooting

### Common Issues

#### 1. Salience Service Not Responding

**Symptoms:**
- Health check fails
- Scoring requests timeout
- Circuit breaker opens

**Diagnosis:**
```bash
# Check container status
docker compose -p seedcore ps seedcore-api

# Check logs
docker compose -p seedcore logs seedcore-api

# Check Ray cluster
docker compose -p seedcore logs ray-head
```

**Solutions:**
- Restart the API container: `docker compose -p seedcore restart seedcore-api`
- Restart Ray cluster: `docker compose -p seedcore restart ray-head ray-serve`
- Check model file exists: `ls -la src/seedcore/ml/models/`

#### 2. Model Not Loading

**Symptoms:**
- Health check shows `"model_loaded": false`
- Scoring falls back to simple heuristic

**Diagnosis:**
```bash
# Check if model file exists
ls -la src/seedcore/ml/models/salience_model.pkl

# Check model training
python scripts/train_salience_model.py
```

**Solutions:**
- Train the model: `python scripts/train_salience_model.py`
- Check scikit-learn installation: `pip install scikit-learn>=1.3.0`
- Verify model file permissions

#### 3. Circuit Breaker Opening

**Symptoms:**
- Health check shows `"is_open": true`
- Scoring uses fallback method
- High failure count

**Diagnosis:**
```bash
# Check Ray Serve status
curl "http://localhost:8000/"

# Check Ray cluster health
curl "http://localhost:8265/api/version"
```

**Solutions:**
- Restart Ray Serve: `docker compose -p seedcore restart ray-serve`
- Check Ray cluster resources: `curl "http://localhost:8265/api/cluster_resources"`
- Increase circuit breaker timeout if needed

#### 4. High Response Times

**Symptoms:**
- Scoring requests take >100ms
- Batch scoring times out

**Diagnosis:**
```bash
# Check system resources
docker stats seedcore-api

# Check Ray cluster load
curl "http://localhost:8265/api/cluster_resources"
```

**Solutions:**
- Scale Ray workers: `./ray-workers.sh start 5`
- Check system resources (CPU, memory)
- Optimize model features or retrain with simpler model

### Performance Tuning

#### Model Performance
```bash
# Retrain with different parameters
python scripts/train_salience_model.py --n_estimators 200 --learning_rate 0.05

# Evaluate model performance
python scripts/test_salience_service.py
```

#### Ray Serve Tuning
```python
# In src/seedcore/ml/serve_app.py
@serve.deployment(
    num_replicas=4,  # Increase replicas
    ray_actor_options={"num_cpus": 2, "num_gpus": 0},  # More CPU
    max_concurrent_queries=200  # Higher concurrency
)
```

#### Circuit Breaker Tuning
```python
# In src/seedcore/ml/serve_app.py
class SalienceServiceClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.circuit_breaker_threshold = 3  # Lower threshold
        self.circuit_breaker_timeout = 30   # Shorter timeout
```

## 🔄 Maintenance

### Regular Tasks

#### Daily
- Check service health: `curl "http://localhost:8002/salience/health"`
- Monitor circuit breaker status
- Review error logs: `docker compose -p seedcore logs seedcore-api`

#### Weekly
- Retrain model with new data (if available)
- Update model performance metrics
- Review and tune circuit breaker parameters

#### Monthly
- Full system validation: `python scripts/validate_salience_container.py`
- Performance benchmarking
- Model retraining with expanded dataset

### Backup & Recovery

#### Model Backup
```bash
# Backup trained model
cp src/seedcore/ml/models/salience_model.pkl backups/salience_model_$(date +%Y%m%d).pkl

# Restore model
cp backups/salience_model_20241201.pkl src/seedcore/ml/models/salience_model.pkl
```

#### Configuration Backup
```bash
# Backup configuration
cp docker/docker-compose.yml backups/
cp src/seedcore/ml/serve_app.py backups/
```

## 📚 Additional Resources

### Documentation
- [SeedCore Architecture Guide](../architecture/README.md)
- [Ray Workers Guide](ray-workers-guide.md)
- [Docker Setup Guide](docker-setup-guide.md)
- [Quick Reference](QUICK_REFERENCE.md)

### Scripts
- `scripts/train_salience_model.py`: Model training
- `scripts/test_salience_service.py`: Local testing
- `scripts/validate_salience_container.py`: Container validation
- `scripts/deploy_salience_service.py`: Complete deployment

### Monitoring URLs
- **API Documentation**: http://localhost:8002/docs
- **Ray Dashboard**: http://localhost:8265
- **Grafana**: http://localhost:3000
- **Prometheus**: http://localhost:9090

## 🎯 Success Metrics

### Performance Targets
- **Response Time**: <50ms for single scoring, <200ms for batch scoring
- **Availability**: >99.9% uptime
- **Accuracy**: R² > 0.8 on test data
- **Circuit Breaker**: <1% of requests trigger fallback

### Monitoring Alerts
- Circuit breaker opens
- Response time >100ms
- Model loading failures
- Ray cluster health issues

This guide ensures the salience scoring service operates reliably within the SeedCore container infrastructure while providing comprehensive monitoring and troubleshooting capabilities. 