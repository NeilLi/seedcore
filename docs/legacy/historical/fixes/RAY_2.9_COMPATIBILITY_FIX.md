# Ray 2.9 Compatibility Fixes

## Issues Identified

Ray 2.9 has several compatibility issues that affect the SeedCore deployment:

### 1. Namespace Issues
- **Problem**: Ray Serve applications are deployed in the "serve" namespace, but the dashboard API only shows applications in the default namespace
- **Symptom**: Dashboard shows empty applications list even when Serve is running
- **Root Cause**: Ray 2.9 changed how namespaces work with the dashboard API

### 2. HTTP Binding Issues
- **Problem**: Serve proxy binds to 127.0.0.1 instead of 0.0.0.0, preventing external access
- **Symptom**: Applications are accessible from within containers but not from host
- **Root Cause**: Ray 2.9 changed default HTTP binding behavior

### 3. API Compatibility Issues
- **Problem**: `serve.connect()` method doesn't exist in Ray 2.9
- **Symptom**: AttributeError when trying to connect to existing Serve instance
- **Root Cause**: API changes between Ray versions

### 4. Dashboard API Issues
- **Problem**: `/api/serve/applications/` endpoint returns empty applications
- **Symptom**: Dashboard shows "Serve not started" even when applications are running
- **Root Cause**: Namespace isolation in Ray 2.9

## Fixes Applied

### 1. Removed Namespace Specifications
```python
# Before (causing issues)
ray.init(address=RAY_ADDRESS, namespace="serve")
_miss_tracker = ray.get_actor("miss_tracker", namespace="seedcore")

# After (Ray 2.9 compatible)
ray.init(address=RAY_ADDRESS)  # Default namespace
_miss_tracker = ray.get_actor("miss_tracker")  # Default namespace
```

### 2. Fixed HTTP Configuration
```python
# In docker/start-ray-with-serve.sh
serve.start(
    http_options={
        'host': '0.0.0.0',  # Bind to all interfaces
        'port': 8000
    },
    detached=True
)
```

### 3. Removed Deprecated API Calls
```python
# Before (causing AttributeError)
serve.connect()  # Doesn't exist in Ray 2.9

# After (Ray 2.9 compatible)
# Removed serve.connect() - connection handled by ray.init()
```

### 4. Updated serve.run() Parameters
```python
# Before (deprecated in Ray 2.9)
serve.run(
    app, 
    name=APP_NAME,
    host="0.0.0.0",
    port=8000,
    dashboard_host="0.0.0.0",
    dashboard_port=8265
)

# After (Ray 2.9 compatible)
serve.run(
    app, 
    name=APP_NAME
)
```

## Files Modified

1. **docker/serve_entrypoint.py**
   - Removed `serve.connect()` call
   - Updated namespace handling
   - Fixed serve.run() parameters

2. **docker/start-ray-with-serve.sh**
   - Added proper HTTP configuration in serve.start()
   - Ensured binding to 0.0.0.0

3. **src/seedcore/memory/working_memory.py**
   - Removed namespace specifications from actor lookups
   - Updated to use default namespace

## Current Status

✅ **Ray Serve Application**: Successfully deployed and running
✅ **Health Endpoint**: Accessible at http://localhost:8000/health
✅ **ML Endpoints**: All endpoints available and functional
⚠️ **Dashboard API**: Still shows empty applications (known Ray 2.9 limitation)

## Workarounds for Dashboard Issues

Since the dashboard API has limitations in Ray 2.9, use these alternatives:

### 1. Check Application Status via Python
```bash
docker exec seedcore-ray-head python -c "
import ray; from ray import serve
ray.init()
print('Applications:', serve.status().applications)
"
```

### 2. Test Endpoints Directly
```bash
# Health check
curl http://localhost:8000/health

# Salience scoring
curl -X POST http://localhost:8000/score/salience \
  -H "Content-Type: application/json" \
  -d '{"features": [{"task_risk": 0.5, "failure_severity": 0.3}]}'
```

### 3. Monitor via Logs
```bash
docker logs seedcore-ray-head | grep -i serve
```

## Verification Commands

```bash
# Check if Ray cluster is running
docker ps | grep ray

# Check Ray Serve status
docker exec seedcore-ray-head python -c "
import ray; from ray import serve
ray.init()
print('Serve status:', serve.status())
"

# Test health endpoint
curl -s http://localhost:8000/health | jq .

# Check application logs
docker logs seedcore-ray-head --tail 50 | grep -i "MLService\|serve"
```

## Expected Behavior

After applying these fixes:

1. **Ray Serve starts successfully** in the default namespace
2. **Applications are deployed** and accessible via HTTP
3. **Health endpoint responds** with proper JSON
4. **ML endpoints work** for salience scoring, anomaly detection, etc.
5. **Dashboard may show empty applications** (Ray 2.9 limitation)
6. **External access works** via localhost:8000

## Known Limitations

- Dashboard API may not show applications due to Ray 2.9 namespace changes
- Some Ray 2.9 features may have different behavior than newer versions
- Monitoring via dashboard may require alternative approaches

## Future Considerations

- Consider upgrading to a newer Ray version when namespace issues are resolved
- Implement custom monitoring endpoints for better visibility
- Add health checks that work around dashboard limitations 