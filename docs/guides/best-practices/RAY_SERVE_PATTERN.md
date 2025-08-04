# Ray Serve Deployment Pattern

This document describes the recommended pattern for deploying Ray Serve applications in the SeedCore project, based on lessons learned from production debugging.

## Overview

Ray Serve provides a scalable way to deploy ML models as microservices. This pattern ensures:
- **External accessibility**: Applications are accessible from outside the container
- **Dashboard visibility**: Applications show up correctly in the Ray Dashboard
- **Proper routing**: No conflicts between multiple applications
- **Reliable deployment**: Consistent startup and recovery

## Key Lessons Learned

### 1. External Access Configuration

**Problem**: Serve applications deployed but not accessible externally.

**Solution**: Configure Serve to listen on all interfaces:

```python
# In start-ray-with-serve.sh
serve.start(
    detached=True,
    http_options={
        "host": "0.0.0.0",  # Listen on all interfaces
        "port": 8000
    }
)
```

### 2. Application Deployment Pattern

**Problem**: Applications not showing up in dashboard or conflicting routes.

**Solution**: Use FastAPI with `@serve.ingress` for proper routing:

```python
from fastapi import FastAPI
from ray import serve

# Create FastAPI app with proper routes
app = FastAPI()

@app.post("/score/salience")
async def score_salience(request: Dict[str, Any]):
    # Implementation
    pass

@serve.deployment(num_replicas=2)
@serve.ingress(app)  # Use ingress instead of route_prefix
class SalienceScorer:
    def __init__(self):
        pass
```

### 3. Namespace Management

**Problem**: Applications not visible in dashboard API.

**Solution**: Use consistent namespace and connect to existing instance:

```python
# In serve_entrypoint.py
ray.init(address=RAY_ADDRESS, namespace="serve")
serve.connect()  # Connect to existing Serve instance
```

## Architecture

### Container Structure

```
seedcore-ray-head (Ray Cluster + Serve Controller)
├── Ray Dashboard (port 8265)
├── Ray Serve Proxy (port 8000)
└── Serve Controller

seedcore-ray-serve (Application Deployment)
├── Connects to ray-head
├── Deploys applications
└── Monitors health
```

### Network Configuration

```yaml
# docker-compose.yml
ray-head:
  ports:
    - "8000:8000"      # Ray Serve application port
    - "8265:8265"      # Dashboard UI
    - "10001:10001"    # Ray head gRPC
  shm_size: '4gb'      # Shared memory for performance
```

## Implementation

### 1. Ray Head Node Startup

```bash
#!/bin/bash
# docker/start-ray-with-serve.sh

# Start Ray head node
ray start --head \
    --dashboard-host 0.0.0.0 \
    --dashboard-port 8265 \
    --port=6379 \
    --include-dashboard true \
    --metrics-export-port=8080 \
    --num-cpus 1

# Wait for Ray to be ready
sleep 10

# Start Serve with external access
python -c "
import ray
from ray import serve
ray.init()
serve.start(
    detached=True,
    http_options={
        'host': '0.0.0.0',
        'port': 8000
    }
)
print('✅ Ray Serve started with external access')
"

# Deploy applications
python /app/scripts/deploy_simple_serve.py
```

### 2. Application Deployment

```python
# docker/serve_entrypoint.py
import ray, os, time
from ray import serve
from src.seedcore.ml.serve_app import create_serve_app

RAY_ADDRESS = os.getenv("RAY_ADDRESS", "ray://seedcore-ray-head:10001")

while True:
    try:
        # Connect to existing Ray cluster
        if not ray.is_initialized():
            ray.init(address=RAY_ADDRESS, namespace="serve")
        
        # Connect to existing Serve instance
        serve.connect()

        # Deploy application
        app = create_serve_app()
        serve.run(app, name="seedcore-ml")

        print("🟢 Serve deployments are live")
        
        while True:
            time.sleep(3600)
    except (ConnectionError, RuntimeError) as e:
        print(f"🔄 Ray not ready ({e}); retrying in 3 s …")
        time.sleep(3)
```

### 3. Application Definition

```python
# src/seedcore/ml/serve_app.py
from fastapi import FastAPI
from ray import serve
from typing import Dict, Any
import time

# Create FastAPI app
salience_app = FastAPI()

@salience_app.post("/score/salience")
async def score_salience(request: Dict[str, Any]):
    """Score the salience of input data."""
    try:
        features_list = request.get("features", [])
        
        if not features_list:
            return {"error": "No features provided", "status": "error"}
        
        # Apply salience scoring
        scores = []
        for features in features_list:
            task_risk = features.get('task_risk', 0.5)
            failure_severity = features.get('failure_severity', 0.5)
            score = task_risk * failure_severity
            scores.append(score)
        
        return {
            "scores": scores,
            "model": "salience_scorer",
            "status": "success",
            "timestamp": time.time()
        }
        
    except Exception as e:
        return {"error": str(e), "status": "error", "timestamp": time.time()}

@serve.deployment(
    num_replicas=2,
    ray_actor_options={"num_cpus": 1, "num_gpus": 0}
)
@serve.ingress(salience_app)
class SalienceScorer:
    """Ray Serve deployment for salience scoring models."""
    
    def __init__(self):
        print("SalienceScorer initialized")

def create_serve_app():
    """Create a single Ray Serve deployment."""
    try:
        salience_scorer = SalienceScorer.bind()
        return salience_scorer
    except Exception as e:
        print(f"Error creating Serve application: {e}")
        raise
```

## Monitoring and Debugging

### Health Checks

```bash
# Check cluster status
docker ps | grep ray

# Check Ray head logs
docker logs seedcore-ray-head --tail 20

# Check Serve container logs
docker logs seedcore-ray-serve-1 --tail 20
```

### API Endpoints

```bash
# Check applications via API
curl -s http://localhost:8265/api/serve/applications/ | jq .

# Test endpoints
curl http://localhost:8000/
curl -X POST http://localhost:8000/score/salience \
  -H "Content-Type: application/json" \
  -d '{"features": [{"task_risk": 0.5, "failure_severity": 0.3}]}'
```

### Dashboard URLs

- **Ray Dashboard**: http://localhost:8265
- **Serve Dashboard**: http://localhost:8265/#/serve
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000

## Common Issues and Solutions

### 1. "Serve not started" Warning

**Cause**: Dashboard false positive
**Solution**: Check if applications are actually running:
```bash
docker logs seedcore-ray-head | grep "Application.*ready"
```

### 2. Endpoints Not Responding

**Cause**: External access not configured
**Solution**: Ensure Serve listens on `0.0.0.0:8000`

### 3. Applications Not in Dashboard

**Cause**: Namespace or API issues
**Solution**: Use consistent namespace and check API endpoints

### 4. Route Conflicts

**Cause**: Multiple apps using same route prefix
**Solution**: Use FastAPI with `@serve.ingress` for proper routing

## Performance Considerations

### Resource Allocation

```python
@serve.deployment(
    num_replicas=2,
    ray_actor_options={
        "num_cpus": 1,
        "num_gpus": 0,
        "memory": 1024 * 1024 * 1024  # 1GB memory
    }
)
```

### Shared Memory

```yaml
# docker-compose.yml
ray-head:
  shm_size: '4gb'  # Increase for better performance
```

## Deployment Commands

### Start Cluster

```bash
cd docker
./start-cluster.sh
```

### Stop Cluster

```bash
cd docker
./stop-all.sh
```

### Restart Serve

```bash
docker restart seedcore-ray-serve-1
```

### Check Status

```bash
docker compose -f docker-compose.yml ps
```

## Best Practices

1. **Always use FastAPI with `@serve.ingress`** for proper routing
2. **Configure external access** with `host: "0.0.0.0"`
3. **Use consistent namespace** across all deployments
4. **Monitor logs** for deployment issues
5. **Test endpoints** after deployment
6. **Use health checks** for reliability
7. **Configure proper resources** for performance

## Troubleshooting

For detailed troubleshooting information, see:
- [Ray Serve Troubleshooting Guide](docs/monitoring/ray_serve_troubleshooting.md)
- [Ray Cluster Diagnostic Report](docs/monitoring/ray_cluster_diagnostic_report.md)

## References

- [Ray Serve Documentation](https://docs.ray.io/en/latest/serve/index.html)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/) 