# Ray Serve Proxy Actor Fixes

## Issues Fixed

The error `The actor died unexpectedly before finishing this task` was caused by several resource and configuration issues in the Ray Serve deployment.

## Root Causes

1. **Resource Constraints**: Ray was started with only 1 CPU but the serve deployment requested 2 replicas with 1 CPU each
2. **Memory Issues**: No memory limits specified, causing potential OOM kills
3. **Serve Configuration**: Proxy actor was being killed due to resource exhaustion
4. **Startup Timing**: Serve was starting before Ray was fully ready

## Fixes Applied

### 1. **Increased Ray Resources** (`docker/start-ray-with-serve.sh`)
```bash
# Before
ray start --head --num-cpus 1

# After  
ray start --head \
    --num-cpus 4 \
    --memory 4000000000 \
    --object-store-memory 2000000000
```

### 2. **Reduced Serve Deployment Resources** (`src/seedcore/ml/serve_app.py`)
```python
# Before
@serve.deployment(
    num_replicas=2,
    ray_actor_options={"num_cpus": 1, "num_gpus": 0}
)

# After
@serve.deployment(
    num_replicas=1,
    ray_actor_options={"num_cpus": 0.25, "num_gpus": 0, "memory": 500000000}
)
```

### 3. **Improved Serve Startup** (`docker/serve_entrypoint.py`)
```python
# Added proper serve configuration
serve.start(
    http_options={"host": "0.0.0.0", "port": 8000},
    detached=True
)

# Added startup delay
time.sleep(10)  # Wait for Ray to be fully ready
```

### 4. **Lazy Loading for ML Models**
- Added lazy loading for salience scorer to avoid startup issues
- Added fallback error handling for model loading
- Simplified health check to avoid blocking startup

### 5. **Better Error Handling**
- Increased retry delays from 5s to 10s
- Added more detailed error logging
- Added fallback scoring when ML models fail to load

## Configuration Summary

### Ray Head Node Resources
- **CPUs**: 4 (increased from 1)
- **Memory**: 4GB (added)
- **Object Store**: 2GB (added)

### Serve Deployment Resources  
- **Replicas**: 1 (reduced from 2)
- **CPU per replica**: 0.25 (reduced from 1)
- **Memory per replica**: 500MB (added)

## Testing

After applying these fixes:

1. **Build the updated images**:
   ```bash
   docker compose --profile ray build --no-cache
   ```

2. **Start the cluster**:
   ```bash
   ./start-cluster.sh up 3
   ```

3. **Verify Serve is working**:
   ```bash
   curl http://localhost:8000/health
   ```

4. **Test ML endpoints**:
   ```bash
   curl -X POST http://localhost:8000/score/salience \
     -H "Content-Type: application/json" \
     -d '{"features": [{"task_risk": 0.5, "failure_severity": 0.3}]}'
   ```

## Expected Results

- ✅ Ray Serve proxy actor should start successfully
- ✅ ML endpoints should be available at http://localhost:8000
- ✅ Health check should return healthy status
- ✅ Salience scoring should work with fallback handling 