# 📘 SeedCore ML Service – Complete Reference Guide

This document provides a comprehensive reference for working with the **SeedCore ML Service**, including architecture, development workflow, deployment practices, smoke testing, and advanced operations.

---

## 1. Overview

The **ML Service** is a comprehensive microservice in **SeedCore** responsible for:

### **Core ML Capabilities**
* **Salience Scoring** → prioritizing events by importance with text and feature-based scoring
* **Anomaly Detection** → flagging unusual behavior using Neural-CUSUM drift detection
* **Scaling Prediction** → recommending scale-up/down actions based on system metrics
* **Drift Detection** → Neural-CUSUM based drift scoring for OCPS integration

### **LLM Integration**
* **Chat Completions** → LLM inference with OpenAI-compatible API
* **Embeddings** → Text embedding generation for vector operations
* **Reranking** → Document reranking for search and retrieval
* **Model Management** → LLM model listing and management

### **XGBoost Lifecycle Management**
* **Training** → Distributed model training with sample and real datasets
* **Prediction** → Single and batch prediction capabilities
* **Tuning** → Hyperparameter optimization (sync and async)
* **Model Management** → Load, refresh, promote, and delete models
* **Energy Integration** → Model promotion with energy system validation

### **Advanced Features**
* **Async Job Management** → Background job processing with status tracking
* **Energy System Integration** → Model promotion with Lipschitz cap validation
* **Drift Detection** → Real-time drift scoring with fallback mechanisms
* **Status Tracking** → Ray actor-based job status management

### **Technology Stack**
* **Ray Serve** → Distributed model serving and scaling
* **FastAPI** → HTTP ingress and API documentation
* **XGBoost** → ML model training and inference
* **Neural-CUSUM** → Drift detection and anomaly detection
* **SentenceTransformers** → Text embedding generation

---

## 2. Architecture

### **Core Components**

* **MLService**: Main Ray Serve deployment exposing all endpoints
* **FastAPI Router**: Defines REST API endpoints with comprehensive error handling
* **StatusActor**: Ray actor for managing shared job status across processes
* **DriftDetector**: Neural-CUSUM based drift detection with lazy initialization
* **XGBoost Service**: Distributed model training, prediction, and management
* **SalienceScorer**: Feature and text-based salience scoring
* **LLM Integration**: Chat, embeddings, and reranking capabilities

### **Service Architecture**

```
┌─────────────────────────────────────────────────────────────┐
│                    ML Service (Ray Serve)                   │
├─────────────────────────────────────────────────────────────┤
│  FastAPI Router (ml_app)                                   │
│  ├── Health & Status Endpoints                             │
│  ├── Core ML Endpoints (salience, anomaly, scaling)        │
│  ├── Drift Detection Endpoints                             │
│  ├── LLM Endpoints (chat, embeddings, rerank)              │
│  └── XGBoost Endpoints (train, predict, tune, manage)      │
├─────────────────────────────────────────────────────────────┤
│  Background Services                                        │
│  ├── StatusActor (Ray Actor) - Job status management       │
│  ├── DriftDetector - Neural-CUSUM drift detection          │
│  ├── XGBoostService - Model lifecycle management           │
│  └── SalienceScorer - Event prioritization                 │
└─────────────────────────────────────────────────────────────┘
```

### **API Endpoints**

If deployed with `route_prefix: /ml` (recommended):

#### **Health & Status**
* `GET /ml/` - Service information and endpoint listing
* `GET /ml/health` - Health check with system metrics

#### **Core ML Capabilities**
* `POST /ml/score/salience` - Salience scoring (features or text)
* `POST /ml/detect/anomaly` - Anomaly detection using drift scoring
* `POST /ml/predict/scaling` - Scaling recommendations

#### **Drift Detection**
* `POST /ml/drift/score` - Neural-CUSUM drift scoring
* `POST /ml/drift/warmup` - Drift detector warmup

#### **LLM Integration**
* `POST /ml/chat` - Chat completions
* `POST /ml/embeddings` - Text embeddings
* `POST /ml/rerank` - Document reranking
* `GET /ml/models` - List available models

#### **XGBoost Management**
* `POST /ml/xgboost/train` - Train models
* `POST /ml/xgboost/predict` - Single predictions
* `POST /ml/xgboost/batch_predict` - Batch predictions
* `POST /ml/xgboost/load_model` - Load model from path
* `GET /ml/xgboost/list_models` - List available models
* `GET /ml/xgboost/model_info` - Get current model info
* `DELETE /ml/xgboost/delete_model` - Delete model
* `POST /ml/xgboost/tune` - Synchronous hyperparameter tuning
* `POST /ml/xgboost/refresh_model` - Refresh current model
* `POST /ml/xgboost/promote` - Promote model with energy validation

#### **Async Job Management**
* `POST /ml/xgboost/tune/submit` - Submit async tuning job
* `GET /ml/xgboost/tune/status/{job_id}` - Get job status
* `GET /ml/xgboost/tune/jobs` - List all jobs

#### **Documentation**
* Swagger UI → `/ml/docs`
* OpenAPI spec → `/ml/openapi.json`

---

## 3. Development Workflow

### **Environment Setup**

```bash
git clone <repo>
cd seedcore
conda activate base   # or use venv/poetry
pip install -r requirements.txt
```

### **Local Development Options**

#### **Option 1: Direct Ray Serve (Development)**
```bash
# Start Ray cluster
ray start --head

# Run ML service directly
python src/seedcore/ml/serve_app.py
```

#### **Option 2: Using Entrypoint (Production-like)**
```bash
# Start Ray cluster
ray start --head

# Run via entrypoint
python entrypoints/ml_entrypoint.py
```

#### **Option 3: Ray Serve YAML Deployment**
```bash
# Start Ray cluster
ray start --head

# Deploy via YAML
ray serve deploy src/seedcore/ml/serve_app.py:build_ml_service --name ml_service --route-prefix /ml
```

### **Service Access**

After starting the service:
* **API Documentation**: `http://127.0.0.1:8000/ml/docs`
* **Health Check**: `http://127.0.0.1:8000/ml/health`
* **Service Info**: `http://127.0.0.1:8000/ml/`

### **Development Iteration**

* **Code Changes**: Update models, endpoints, or logic in `serve_app.py` or `ml_entrypoint.py`
* **Service Restart**: Use `serve.run()` reload or restart the service
* **Testing**: Unit tests under `tests/ml/`
* **Environment Variables**: Configure via `.env` or environment variables

### **Environment Configuration**

The service supports extensive environment variable configuration:

```bash
# Ray Configuration
export RAY_ADDRESS=ray://seedcore-svc-head-svc:10001
export RAY_NAMESPACE=seedcore-dev

# Service Configuration
export SEEDCORE_NS=seedcore-dev
export SERVE_GATEWAY=http://seedcore-svc-stable-svc:8000
export METRICS_ENABLED=1

# Model Configuration
export MODEL_CACHE_DIR=/app/models
export DRIFT_DETECTOR_MODEL=all-MiniLM-L6-v2
export DRIFT_DETECTOR_DEVICE=cpu
export DRIFT_DETECTOR_MAX_TEXT_LENGTH=512
export DRIFT_DETECTOR_ENABLE_FALLBACK=true

# Energy System Integration
export SEEDCORE_PROMOTION_LTOT_CAP=0.98
export SEEDCORE_E_GUARD=0.0
export SEEDCORE_API_ADDRESS=localhost:8002
```

---

## 4. Advanced Features

### **Drift Detection System**

The ML Service includes a sophisticated drift detection system based on Neural-CUSUM:

#### **Neural-CUSUM Drift Detector**
- **Text Embeddings**: Uses SentenceTransformer for text feature extraction
- **Runtime Metrics**: Combines with system metrics for comprehensive drift detection
- **MLP Processing**: Lightweight neural network for log-likelihood scoring
- **OCPS Integration**: Designed for OCPSValve integration with <50ms latency
- **Fallback Support**: Graceful degradation when models are unavailable

#### **Drift Detection Endpoints**
```bash
# Compute drift score for a task
POST /ml/drift/score
{
  "task": {
    "id": "task_123",
    "type": "anomaly_detection",
    "description": "Task description",
    "priority": 6,
    "complexity": 0.7
  },
  "text": "Optional text content for embedding"
}

# Warm up drift detector (call during startup)
POST /ml/drift/warmup
{
  "sample_texts": ["sample text 1", "sample text 2"]
}
```

#### **Drift Detection Response**
```json
{
  "drift_score": 0.75,
  "log_likelihood": -2.3,
  "confidence": 0.85,
  "processing_time_ms": 45,
  "model_version": "v1.0",
  "model_checksum": "abc123",
  "drift_mode": "text_embedding",
  "accuracy_warning": false,
  "status": "success",
  "timestamp": 1640995200.0
}
```

### **LLM Integration**

The service provides OpenAI-compatible LLM endpoints:

#### **Chat Completions**
```bash
POST /ml/chat
{
  "model": "llama3-8b",
  "messages": [
    {"role": "user", "content": "Hello, how are you?"}
  ],
  "temperature": 0.7,
  "max_tokens": 100
}
```

#### **Embeddings**
```bash
POST /ml/embeddings
{
  "model": "embedding-model",
  "input": "text to embed"  # or ["text1", "text2"]
}
```

#### **Reranking**
```bash
POST /ml/rerank
{
  "model": "rerank-model",
  "query": "search query",
  "documents": ["doc1", "doc2", "doc3"],
  "top_k": 10
}
```

### **Async Job Management**

The service supports background job processing with status tracking:

#### **Job Submission**
```bash
POST /ml/xgboost/tune/submit
{
  "space_type": "default",
  "config_type": "default",
  "experiment_name": "my_experiment"
}
```

#### **Job Status Monitoring**
```bash
# Get job status
GET /ml/xgboost/tune/status/{job_id}

# List all jobs
GET /ml/xgboost/tune/jobs
```

#### **Job Status Response**
```json
{
  "status": "RUNNING",
  "result": null,
  "progress": "Running... 120s elapsed",
  "submitted_at": 1640995200.0
}
```

### **Energy System Integration**

The service integrates with SeedCore's energy system for model promotion:

#### **Model Promotion with Energy Validation**
```bash
POST /ml/xgboost/promote
{
  "model_path": "/path/to/candidate/model.xgb",
  "delta_E": -0.1,
  "latency_ms": 50,
  "beta_mem_new": 0.8
}
```

#### **Energy Validation Rules**
- **Lipschitz Cap**: `L_tot < PROMOTION_LTOT_CAP` (default: 0.98)
- **Energy Guard**: `delta_E <= -E_GUARD` (default: 0.0)
- **Pre-flight Check**: Validates energy state before promotion
- **Post-flight Check**: Validates energy state after promotion
- **Rollback**: Automatic rollback if energy constraints violated

---

## 5. Deployment

### **Ray Serve YAML Configuration**

#### **Basic Configuration**
```yaml
serveConfigV2: |
  http_options:
    host: 0.0.0.0
    port: 8000
    location: HeadOnly

  applications:
    - name: ml_service
      import_path: entrypoints.ml_entrypoint:build_ml_service
      route_prefix: /ml
      ray_actor_options:
        num_cpus: 0.1
        num_gpus: 0
        memory: 200_000_000
      max_ongoing_requests: 32
```

#### **Advanced Configuration with Environment Variables**
```yaml
serveConfigV2: |
  http_options:
    host: 0.0.0.0
    port: 8000
    location: HeadOnly

  applications:
    - name: ml_service
      import_path: entrypoints.ml_entrypoint:build_ml_service
      route_prefix: /ml
      ray_actor_options:
        num_cpus: 1.0
        num_gpus: 0
        memory: 500_000_000
      max_ongoing_requests: 64
      env:
        SEEDCORE_NS: "seedcore-dev"
        RAY_NAMESPACE: "seedcore-dev"
        SERVE_GATEWAY: "http://seedcore-svc-stable-svc:8000"
        METRICS_ENABLED: "1"
        MODEL_CACHE_DIR: "/app/models"
        DRIFT_DETECTOR_MODEL: "all-MiniLM-L6-v2"
        DRIFT_DETECTOR_DEVICE: "cpu"
        DRIFT_DETECTOR_MAX_TEXT_LENGTH: "512"
        DRIFT_DETECTOR_ENABLE_FALLBACK: "true"
        SEEDCORE_PROMOTION_LTOT_CAP: "0.98"
        SEEDCORE_E_GUARD: "0.0"
        SEEDCORE_API_ADDRESS: "seedcore-api:8002"
```

### **Deployment Methods**

#### **Method 1: Kubernetes Deployment**
```bash
# Deploy via Kubernetes
kubectl apply -f deploy/rayservice.yaml

# Check deployment status
kubectl get RayService
kubectl describe RayService seedcore-svc

# Check pod status
kubectl get pods -l app=ray-serve
kubectl logs -f <ml-service-pod>
```

#### **Method 2: Direct Ray Serve Deployment**
```bash
# Start Ray cluster
ray start --head

# Deploy ML service
ray serve deploy entrypoints.ml_entrypoint:build_ml_service \
  --name ml_service \
  --route-prefix /ml

# Check deployment
ray serve status
```

#### **Method 3: Python Script Deployment**
```python
import ray
from ray import serve
from entrypoints.ml_entrypoint import build_ml_service

# Initialize Ray
ray.init()

# Deploy service
serve.run(
    build_ml_service(),
    name="ml_service",
    route_prefix="/ml"
)
```

### **Service Configuration**

#### **Resource Requirements**
- **CPU**: 0.1-1.0 cores (configurable)
- **Memory**: 200MB-500MB (configurable)
- **GPU**: Optional (for model inference)
- **Max Concurrent Requests**: 32-64 (configurable)

#### **Environment Variables**
| Variable | Default | Description |
|----------|---------|-------------|
| `SEEDCORE_NS` | `seedcore-dev` | SeedCore namespace |
| `RAY_NAMESPACE` | `seedcore-dev` | Ray namespace |
| `SERVE_GATEWAY` | `http://seedcore-svc-stable-svc:8000` | Service gateway URL |
| `MODEL_CACHE_DIR` | `/app/models` | Model cache directory |
| `DRIFT_DETECTOR_MODEL` | `all-MiniLM-L6-v2` | Drift detector model |
| `DRIFT_DETECTOR_DEVICE` | `cpu` | Device for drift detection |
| `SEEDCORE_PROMOTION_LTOT_CAP` | `0.98` | Lipschitz cap for model promotion |
| `SEEDCORE_E_GUARD` | `0.0` | Energy guard for model promotion |

---

## 6. Verification & Smoke Testing

### **API Documentation**

* **Swagger UI**: `http://<host>:8000/ml/docs`
* **OpenAPI Spec**: `http://<host>:8000/ml/openapi.json`
* **Service Info**: `http://<host>:8000/ml/`

### **Health Check**

```bash
curl http://<host>:8000/ml/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "ml_serve",
  "timestamp": 1640995200.0,
  "models": {
    "salience_scorer": "available",
    "xgboost_service": "available"
  },
  "system": {
    "cpu_percent": 15.2,
    "memory_percent": 45.8,
    "disk_percent": 23.1
  },
  "version": "1.0.0"
}
```

### **Comprehensive Smoke Testing**

#### **Core ML Endpoints**
```bash
# Salience Scoring
curl -X POST http://<host>:8000/ml/score/salience \
  -H "Content-Type: application/json" \
  -d '{"features":[{"type":"system_event","severity":"high"}]}'

# Anomaly Detection
curl -X POST http://<host>:8000/ml/detect/anomaly \
  -H "Content-Type: application/json" \
  -d '{"data":[0.1,0.2,5.0]}'

# Scaling Prediction
curl -X POST http://<host>:8000/ml/predict/scaling \
  -H "Content-Type: application/json" \
  -d '{"metrics":{"cpu_usage":0.8,"memory_usage":0.6}}'
```

#### **Drift Detection**
```bash
# Drift Scoring
curl -X POST http://<host>:8000/ml/drift/score \
  -H "Content-Type: application/json" \
  -d '{"task":{"id":"test_task","type":"test","description":"Test task"},"text":"Sample text for drift detection"}'

# Drift Warmup
curl -X POST http://<host>:8000/ml/drift/warmup \
  -H "Content-Type: application/json" \
  -d '{"sample_texts":["test text 1","test text 2"]}'
```

#### **LLM Endpoints**
```bash
# Chat Completions
curl -X POST http://<host>:8000/ml/chat \
  -H "Content-Type: application/json" \
  -d '{"model":"llama3-8b","messages":[{"role":"user","content":"Hello"}]}'

# Embeddings
curl -X POST http://<host>:8000/ml/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"embedding-model","input":"text to embed"}'

# Reranking
curl -X POST http://<host>:8000/ml/rerank \
  -H "Content-Type: application/json" \
  -d '{"model":"rerank-model","query":"search query","documents":["doc1","doc2"]}'
```

#### **XGBoost Management**
```bash
# List Models
curl http://<host>:8000/ml/xgboost/list_models

# Train Model (with sample data)
curl -X POST http://<host>:8000/ml/xgboost/train \
  -H "Content-Type: application/json" \
  -d '{"use_sample_data":true,"sample_size":1000,"sample_features":10,"name":"test_model"}'

# Predict
curl -X POST http://<host>:8000/ml/xgboost/predict \
  -H "Content-Type: application/json" \
  -d '{"features":[[1,2,3,4,5]]}'
```

---

## 7. Troubleshooting

### **Common Issues**

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| `404 Not Found` | Wrong `route_prefix` | Ensure requests use `/ml/...` |
| `DEPLOY_FAILED` | Wrong `import_path` in YAML | Use `entrypoints.ml_entrypoint:build_ml_service` |
| `/docs` loads but endpoints missing | App didn't start properly | Check Ray Serve logs |
| Training too slow | Using large dataset | Use `"use_sample_data": true` for quick tests |
| Drift detection fails | Model not loaded | Call `/ml/drift/warmup` endpoint |
| Energy validation fails | Energy system unavailable | Check `SEEDCORE_API_ADDRESS` configuration |
| Async jobs stuck | StatusActor unavailable | Check Ray cluster health |

### **Logging and Debugging**

#### **Ray Serve Logs**
```bash
# Kubernetes
kubectl logs -f <ml-service-pod>

# Direct Ray
ray serve status
ray logs
```

#### **Service Health Monitoring**
```bash
# Check service health
curl http://<host>:8000/ml/health

# Check Ray cluster status
ray status

# Check Ray Serve deployments
ray serve status
```

#### **Drift Detector Debugging**
```bash
# Check drift detector status
curl -X POST http://<host>:8000/ml/drift/warmup \
  -H "Content-Type: application/json" \
  -d '{}'

# Check drift detector performance
curl -X POST http://<host>:8000/ml/drift/score \
  -H "Content-Type: application/json" \
  -d '{"task":{"id":"debug_task","type":"debug"},"text":"debug text"}'
```

### **Performance Optimization**

#### **Drift Detection Optimization**
- **Warmup**: Call `/ml/drift/warmup` during service startup
- **Model Caching**: Ensure `MODEL_CACHE_DIR` is properly configured
- **Device Selection**: Use `DRIFT_DETECTOR_DEVICE=cpu` for CPU-only environments

#### **XGBoost Optimization**
- **Sample Data**: Use `"use_sample_data": true` for testing
- **Resource Limits**: Configure appropriate CPU/memory limits
- **Batch Processing**: Use batch prediction for large datasets

#### **Async Job Management**
- **Status Monitoring**: Regularly check job status via `/ml/xgboost/tune/jobs`
- **Resource Cleanup**: Monitor job completion and cleanup
- **Error Handling**: Implement proper error handling for failed jobs

---

## 8. Advanced Operations

### **XGBoost Model Lifecycle Management**

#### **Complete Model Workflow**
1. **Train** with sample or real dataset
2. **Predict** single row or batch
3. **Tune** hyperparameters (sync or async)
4. **Promote** new model with energy validation
5. **Refresh** to reload active model
6. **Monitor** model performance and health

#### **Model Promotion Workflow**
```bash
# 1. Train a new model
curl -X POST http://<host>:8000/ml/xgboost/train \
  -H "Content-Type: application/json" \
  -d '{"use_sample_data":true,"sample_size":5000,"name":"candidate_model"}'

# 2. Promote model with energy validation
curl -X POST http://<host>:8000/ml/xgboost/promote \
  -H "Content-Type: application/json" \
  -d '{"model_path":"/path/to/candidate_model.xgb","delta_E":-0.1}'

# 3. Refresh current model
curl -X POST http://<host>:8000/ml/xgboost/refresh_model
```

### **Async Job Management**

#### **Job Submission and Monitoring**
```bash
# 1. Submit async tuning job
curl -X POST http://<host>:8000/ml/xgboost/tune/submit \
  -H "Content-Type: application/json" \
  -d '{"space_type":"default","experiment_name":"my_experiment"}'

# 2. Monitor job status
curl http://<host>:8000/ml/xgboost/tune/status/{job_id}

# 3. List all jobs
curl http://<host>:8000/ml/xgboost/tune/jobs
```

#### **Job Status Management**
- **PENDING**: Job submitted, waiting to start
- **RUNNING**: Job in progress with heartbeat updates
- **COMPLETED**: Job finished successfully
- **FAILED**: Job failed with error details

### **Drift Detection Operations**

#### **Drift Detector Management**
```bash
# Warm up drift detector (call during startup)
curl -X POST http://<host>:8000/ml/drift/warmup \
  -H "Content-Type: application/json" \
  -d '{"sample_texts":["sample text 1","sample text 2"]}'

# Compute drift score for monitoring
curl -X POST http://<host>:8000/ml/drift/score \
  -H "Content-Type: application/json" \
  -d '{"task":{"id":"monitor_task","type":"monitoring"},"text":"system metrics"}'
```

### **CI/CD Integration**

#### **Automated Testing Pipeline**
```bash
# 1. Health check
curl -f http://<host>:8000/ml/health || exit 1

# 2. Core functionality test
curl -X POST http://<host>:8000/ml/score/salience \
  -H "Content-Type: application/json" \
  -d '{"features":[{"type":"test","severity":"low"}]}' || exit 1

# 3. Drift detection test
curl -X POST http://<host>:8000/ml/drift/score \
  -H "Content-Type: application/json" \
  -d '{"task":{"id":"test","type":"test"},"text":"test"}' || exit 1

# 4. XGBoost test
curl -X POST http://<host>:8000/ml/xgboost/train \
  -H "Content-Type: application/json" \
  -d '{"use_sample_data":true,"sample_size":100,"name":"test_model"}' || exit 1
```

---

## 9. Best Practices

### **Service Architecture**
* Always use `route_prefix` (e.g. `/ml`) to avoid conflicts
* Separate **ML service** from **cognitive service** (`/cognitive`)
* Use **environment variables** for configuration
* Implement **proper error handling** and logging

### **Model Management**
* Use **sample data** for smoke tests and development
* Keep **long-running jobs** async (submit → status → fetch results)
* Implement **model versioning** and rollback strategies
* Monitor **model performance** and drift

### **Performance Optimization**
* **Warm up** drift detector during service startup
* Use **appropriate resource limits** for Ray actors
* Implement **caching** for frequently used models
* Monitor **system metrics** and resource usage

### **Monitoring and Observability**
* Monitor via **Ray Dashboard** (`http://<head-node>:8265`)
* Implement **health checks** and status endpoints
* Use **structured logging** for debugging
* Monitor **async job status** and completion

---

## 10. Roadmap & Future Enhancements

### **Planned Features**
* **Prometheus/Grafana metrics** for inference latency & throughput
* **Auto-promote models** using SLA checks and performance metrics
* **Multi-model support** (ensembles, model chaining)
* **Advanced drift detection** with multiple algorithms
* **Real-time model monitoring** and alerting

### **Integration Enhancements**
* **SeedCore cognitive core** integration for higher-level reasoning
* **Energy system** advanced integration and optimization
* **Database integration** for model metadata and performance tracking
* **Distributed training** support for large-scale models

### **Performance Improvements**
* **GPU acceleration** for model inference
* **Model quantization** for reduced memory usage
* **Batch processing** optimization
* **Caching strategies** for improved response times

---

## 11. Quick Commands Reference

### **Health & Status**
```bash
# Service health
curl http://127.0.0.1:8000/ml/health

# Service information
curl http://127.0.0.1:8000/ml/

# Ray cluster status
ray status
ray serve status
```

### **Core ML Operations**
```bash
# Salience Scoring
curl -X POST http://127.0.0.1:8000/ml/score/salience \
  -H "Content-Type: application/json" \
  -d '{"features":[{"type":"system_event","severity":"high"}]}'

# Anomaly Detection
curl -X POST http://127.0.0.1:8000/ml/detect/anomaly \
  -H "Content-Type: application/json" \
  -d '{"data":[0.1,0.2,5.0]}'

# Scaling Prediction
curl -X POST http://127.0.0.1:8000/ml/predict/scaling \
  -H "Content-Type: application/json" \
  -d '{"metrics":{"cpu_usage":0.8,"memory_usage":0.6}}'
```

### **Drift Detection**
```bash
# Drift scoring
curl -X POST http://127.0.0.1:8000/ml/drift/score \
  -H "Content-Type: application/json" \
  -d '{"task":{"id":"test","type":"test"},"text":"sample text"}'

# Drift warmup
curl -X POST http://127.0.0.1:8000/ml/drift/warmup \
  -H "Content-Type: application/json" \
  -d '{"sample_texts":["text1","text2"]}'
```

### **XGBoost Management**
```bash
# List models
curl http://127.0.0.1:8000/ml/xgboost/list_models

# Train model
curl -X POST http://127.0.0.1:8000/ml/xgboost/train \
  -H "Content-Type: application/json" \
  -d '{"use_sample_data":true,"sample_size":1000,"name":"test_model"}'

# Predict
curl -X POST http://127.0.0.1:8000/ml/xgboost/predict \
  -H "Content-Type: application/json" \
  -d '{"features":[[1,2,3,4,5]]}'

# Promote model
curl -X POST http://127.0.0.1:8000/ml/xgboost/promote \
  -H "Content-Type: application/json" \
  -d '{"model_path":"/path/to/model.xgb","delta_E":-0.1}'
```

### **LLM Operations**
```bash
# Chat completions
curl -X POST http://127.0.0.1:8000/ml/chat \
  -H "Content-Type: application/json" \
  -d '{"model":"llama3-8b","messages":[{"role":"user","content":"Hello"}]}'

# Embeddings
curl -X POST http://127.0.0.1:8000/ml/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"embedding-model","input":"text to embed"}'

# Reranking
curl -X POST http://127.0.0.1:8000/ml/rerank \
  -H "Content-Type: application/json" \
  -d '{"model":"rerank-model","query":"search","documents":["doc1","doc2"]}'
```

---

## 12. Summary

The **SeedCore ML Service** is a comprehensive microservice providing:

### **Core Capabilities**
- **Advanced ML Operations**: Salience scoring, anomaly detection, scaling prediction
- **Drift Detection**: Neural-CUSUM based real-time drift scoring
- **LLM Integration**: Chat, embeddings, and reranking capabilities
- **XGBoost Management**: Complete model lifecycle with energy system integration
- **Async Job Processing**: Background job management with status tracking

### **Production Features**
- **Ray Serve Architecture**: Distributed, scalable model serving
- **Comprehensive API**: 20+ endpoints with full documentation
- **Energy System Integration**: Model promotion with validation
- **Health Monitoring**: System metrics and service health checks
- **Error Handling**: Robust error handling and fallback mechanisms

### **Development & Operations**
- **Multiple Deployment Options**: Direct Ray, Kubernetes, Python scripts
- **Environment Configuration**: Extensive configuration via environment variables
- **Comprehensive Testing**: Smoke tests and verification procedures
- **Troubleshooting Guides**: Detailed debugging and optimization guides

✅ **This reference provides a complete guide for developing, deploying, and operating the SeedCore ML Service in production environments.**
