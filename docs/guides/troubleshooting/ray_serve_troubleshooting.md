# Ray Serve Troubleshooting Guide

This document provides solutions for common Ray Serve issues encountered in the SeedCore project.

## Common Issues and Solutions

### 1. "Serve not started" Warning in Dashboard

**Problem**: The Ray Dashboard shows "Serve not started. Please deploy a serve application first" even though Ray Serve is running.

**Root Cause**: This is typically a **false positive**. The actual issue is usually one of the following:
- Serve is running but not accessible externally
- Dashboard API detection issues
- Namespace conflicts

**Diagnosis Steps**:
```bash
# Check if Serve is actually running
docker logs seedcore-ray-head | grep -i serve

# Check Serve status via API
curl -s http://localhost:8265/api/serve/applications/ | jq .

# Check if endpoints are accessible
curl http://localhost:8000/
```

**Solutions**:

#### A. External Access Configuration
Ensure Ray Serve is configured to listen on all interfaces:

```python
# In start-ray-with-serve.sh
serve.start(
    detached=True,
    http_options={
        "host": "0.0.0.0",
        "port": 8000
    }
)
```

#### B. Proper Application Deployment
Use FastAPI with `@serve.ingress` for proper route handling:

```python
from fastapi import FastAPI
from ray import serve

# Create FastAPI app
app = FastAPI()

@app.post("/score/salience")
async def score_salience(request: Dict[str, Any]):
    # Your endpoint logic here
    pass

@serve.deployment(num_replicas=2)
@serve.ingress(app)
class SalienceScorer:
    def __init__(self):
        pass
```

### 2. Endpoints Not Responding (404/Connection Issues)

**Problem**: Serve applications are deployed but endpoints return 404 or connection errors.

**Root Cause**: 
- Serve proxy not listening on correct interface
- Port mapping issues
- Application routing conflicts

**Diagnosis**:
```bash
# Check if proxy is running
docker logs seedcore-ray-head | grep "Proxy starting"

# Check port mapping
docker port seedcore-ray-head | grep 8000

# Test endpoint accessibility
curl -v http://localhost:8000/
```

**Solutions**:

#### A. Verify External Access Configuration
```bash
# Check Serve configuration in logs
docker logs seedcore-ray-head | grep "Application.*ready at"

# Should show: Application 'app-name' is ready at http://0.0.0.0:8000/
```

#### B. Check Application Conflicts
Ensure applications don't use conflicting route prefixes:

```python
# ❌ Both apps using same route
@serve.deployment(route_prefix="/")  # Conflicts
class App1: pass

@serve.deployment(route_prefix="/")  # Conflicts  
class App2: pass

# ✅ Use different routes
@serve.deployment(route_prefix="/app1")
class App1: pass

@serve.deployment(route_prefix="/app2") 
class App2: pass
```

### 3. Dashboard API Not Showing Applications

**Problem**: `curl http://localhost:8265/api/serve/applications/` returns empty applications list.

**Root Cause**:
- Namespace issues
- API version mismatches
- Application not properly registered

**Diagnosis**:
```bash
# Check applications in different namespaces
docker exec seedcore-ray-head python -c "
import ray; from ray import serve
ray.init(namespace='serve')
print('Applications:', serve.status().applications)
"
```

**Solutions**:

#### A. Use Correct Namespace
```python
# In serve_entrypoint.py
ray.init(address=RAY_ADDRESS, namespace="serve")
serve.connect()  # Connect to existing Serve instance
```

#### B. Verify Application Registration
```bash
# Check if application is deployed
docker logs seedcore-ray-serve-1 | grep "Application.*ready"

# Should show: Application 'app-name' is ready at http://127.0.0.1:8000/
```

### 4. Model File Not Found Warnings

**Problem**: Logs show "Trained model not found, using simple model"

**Root Cause**: Missing model files in container

**Solution**:
```bash
# Create models directory
mkdir -p src/seedcore/ml/models/

# Copy model files if available
docker cp salience_model.pkl seedcore-ray-serve-1:/app/src/seedcore/ml/models/
```

**Note**: This is a **warning, not an error**. The application will use fallback scoring.

## Configuration Best Practices

### 1. Ray Head Node Configuration

```yaml
# docker-compose.yml
ray-head:
  command: ["/bin/bash", "docker/start-ray-with-serve.sh"]
  ports:
    - "8000:8000"      # Ray Serve application port
    - "8265:8265"      # Dashboard UI
```

### 2. Serve Entrypoint Configuration

```python
# docker/serve_entrypoint.py
import ray
from ray import serve

RAY_ADDRESS = os.getenv("RAY_ADDRESS", "ray://seedcore-ray-head:10001")

# Connect to existing Serve instance
ray.init(address=RAY_ADDRESS, namespace="serve")
serve.connect()

# Deploy application
app = create_serve_app()
serve.run(app, name="seedcore-ml")
```

### 3. Application Deployment Pattern

```python
# src/seedcore/ml/serve_app.py
from fastapi import FastAPI
from ray import serve

# Create FastAPI app with proper routes
app = FastAPI()

@app.post("/score/salience")
async def score_salience(request: Dict[str, Any]):
    # Implementation
    pass

@serve.deployment(num_replicas=2)
@serve.ingress(app)
class SalienceScorer:
    def __init__(self):
        pass
```

## Debugging Commands

### Check Cluster Status
```bash
# Check all containers
docker ps

# Check Ray head logs
docker logs seedcore-ray-head --tail 50

# Check Serve container logs
docker logs seedcore-ray-serve-1 --tail 50
```

### Check Serve Status
```bash
# Check applications via API
curl -s http://localhost:8265/api/serve/applications/ | jq .

# Check applications via Python
docker exec seedcore-ray-head python -c "
import ray; from ray import serve
ray.init(namespace='serve')
print('Applications:', serve.status().applications)
"
```

### Test Endpoints
```bash
# Test simple endpoint
curl http://localhost:8000/

# Test salience scoring
curl -X POST http://localhost:8000/score/salience \
  -H "Content-Type: application/json" \
  -d '{"features": [{"task_risk": 0.5, "failure_severity": 0.3}]}'
```

## Common Error Messages

### "The new client HTTP config differs from the existing one"
**Cause**: Multiple Serve clients trying to configure HTTP options
**Solution**: Use `serve.connect()` instead of `serve.start()` when connecting to existing instance

### "Proxy actor readiness check didn't complete"
**Cause**: Serve proxy startup timeout
**Solution**: Wait longer for startup or check resource constraints

### "Failed to start the dashboard"
**Cause**: Dashboard startup issues (usually not critical)
**Solution**: Check if dashboard is accessible at `http://localhost:8265`

## Performance Optimization

### Shared Memory Configuration
```yaml
# docker-compose.yml
ray-head:
  shm_size: '4gb'  # Increase shared memory for better performance
```

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

## Monitoring and Observability

### Dashboard URLs
- **Ray Dashboard**: http://localhost:8265
- **Serve Dashboard**: http://localhost:8265/#/serve
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000

### Log Locations
- **Ray Head**: `docker logs seedcore-ray-head`
- **Serve Container**: `docker logs seedcore-ray-serve-1`
- **Application Logs**: Inside container at `/tmp/ray/session_*/logs/`

## Quick Fix Checklist

When Ray Serve issues occur, follow this checklist:

1. ✅ **Check if Serve is actually running**
   ```bash
   docker logs seedcore-ray-head | grep -i serve
   ```

2. ✅ **Verify external access configuration**
   ```bash
   docker logs seedcore-ray-head | grep "ready at.*0.0.0.0"
   ```

3. ✅ **Check application deployment**
   ```bash
   curl -s http://localhost:8265/api/serve/applications/ | jq .
   ```

4. ✅ **Test endpoint accessibility**
   ```bash
   curl http://localhost:8000/
   ```

5. ✅ **Check for route conflicts**
   - Ensure applications use different route prefixes
   - Use FastAPI with `@serve.ingress` for proper routing

6. ✅ **Verify namespace configuration**
   ```python
   ray.init(namespace="serve")
   serve.connect()
   ```

7. ✅ **Restart if necessary**
   ```bash
   docker restart seedcore-ray-serve-1
   ```

## Related Documentation

- [Ray Serve Documentation](https://docs.ray.io/en/latest/serve/index.html)
- [Ray Cluster Setup](docs/monitoring/ray_cluster_setup.md)
- [Docker Configuration](docker/README.md)
- [ML Model Deployment](docs/guides/ml_model_deployment.md) 