# Ray 2.20.0 Dashboard Integration Fix

## 🚨 Issue Identified

After upgrading to Ray 2.20.0, the Ray Serve applications are not showing up in the Ray Dashboard, even though the applications are running successfully and responding to requests.

**Symptoms:**
- Ray Serve applications deploy successfully
- Health endpoints respond correctly
- Applications show as "ready" in logs
- But Ray Dashboard shows empty applications list
- `serve.status()` returns empty applications

## 🔍 Root Cause Analysis

The issue was caused by **namespace isolation** in Ray 2.20.0:

1. **Multiple Ray Instances**: The serve_entrypoint.py was creating a new Ray instance instead of connecting to the existing one
2. **Namespace Mismatch**: Applications were deployed in one Ray namespace, but the dashboard was looking in another
3. **Connection Issues**: The RAY_ADDRESS configuration was causing connection mismatches

## 🔧 Files Fixed

### 1. **docker/serve_entrypoint.py**
**Before:**
```python
RAY_ADDRESS = os.getenv("RAY_ADDRESS", "ray://ray-head:10001")
```

**After:**
```python
# When running inside ray-head container, connect to local Ray instance
# When running from external containers, connect to ray-head:10001
RAY_ADDRESS = os.getenv("RAY_ADDRESS", "auto")
```

### 2. **docker/start-ray-with-serve.sh**
**Before:**
```python
# Initialize Ray connection
ray.init()
```

**After:**
```python
# Initialize Ray connection to local head node
ray.init()
```

### 3. **docker/docker-compose.yml**
Removed incorrect RAY_ADDRESS environment variable from ray-head service.

## 📋 Ray 2.20.0 Namespace Architecture

### Correct Connection Pattern
- **Inside ray-head container**: Use `ray.init()` (connects to local Ray instance)
- **External containers**: Use `ray.init(address='ray://ray-head:10001')`
- **Serve applications**: Deploy in the same namespace as the Ray instance

### Namespace Isolation
Ray 2.20.0 has stricter namespace isolation:
- Each `ray.init()` call can create a new namespace
- Applications must be deployed in the same namespace as the dashboard
- External connections use different namespaces than local connections

## ✅ Verification Steps

### 1. **Check Ray Instance Connection**
```bash
docker exec seedcore-ray-head python -c "
import ray
ray.init()
print('Ray address:', ray.get_runtime_context().gcs_address)
print('Ray namespace:', ray.get_runtime_context().namespace)
"
```

### 2. **Check Serve Applications**
```bash
docker exec seedcore-ray-head python -c "
import ray
from ray import serve
ray.init()
status = serve.status()
print('Applications:', status.applications)
print('Proxies:', status.proxies)
"
```

### 3. **Test Dashboard Integration**
```bash
# Check dashboard API
curl http://localhost:8265/api/serve/applications/

# Check if applications are visible
curl http://localhost:8265/api/serve/deployments/
```

### 4. **Verify Application Health**
```bash
# Test health endpoint
curl http://localhost:8000/health

# Test ML endpoints
curl -X POST http://localhost:8000/score/salience \
  -H "Content-Type: application/json" \
  -d '{"features": [{"task_risk": 0.5, "failure_severity": 0.3}]}'
```

## 🚀 Benefits of the Fix

1. **Dashboard Visibility**: Applications now show up in Ray Dashboard
2. **Namespace Consistency**: All components use the same Ray namespace
3. **Proper Integration**: Ray Serve and Dashboard work together seamlessly
4. **Monitoring**: Full monitoring capabilities through the dashboard

## 🔧 Deployment Instructions

### 1. **Rebuild and Restart**
```bash
cd docker
docker compose --profile core --profile ray down
docker compose --profile core --profile ray build --no-cache
docker compose --profile core --profile ray up -d
```

### 2. **Verify the Fix**
```bash
# Check if applications appear in dashboard
docker exec seedcore-ray-head python -c "
import ray
from ray import serve
ray.init()
print('Serve applications:', serve.status().applications)
"
```

### 3. **Test Dashboard**
- Open http://localhost:8265
- Navigate to the "Serve" tab
- Verify that "seedcore-ml" application is visible
- Check that all deployments are listed

## 📊 Expected Results

After the fix:

### Dashboard Should Show:
- ✅ **Applications**: "seedcore-ml" visible in Serve tab
- ✅ **Deployments**: MLService deployment listed
- ✅ **Endpoints**: All endpoints (/health, /score/salience, etc.) visible
- ✅ **Metrics**: Application metrics and performance data

### API Responses:
```json
{
  "applications": {
    "seedcore-ml": {
      "status": "RUNNING",
      "deployments": {
        "MLService": {
          "status": "HEALTHY",
          "replicas": 1
        }
      }
    }
  }
}
```

## 🔍 Troubleshooting

### If Applications Still Don't Show:

1. **Check Ray Namespace**:
   ```bash
   docker exec seedcore-ray-head python -c "
   import ray
   ray.init()
   print('Namespace:', ray.get_runtime_context().namespace)
   "
   ```

2. **Check Serve Status**:
   ```bash
   docker exec seedcore-ray-head python -c "
   import ray
   from ray import serve
   ray.init()
   print('Serve status:', serve.status())
   "
   ```

3. **Restart Ray Serve**:
   ```bash
   docker exec seedcore-ray-head python -c "
   import ray
   from ray import serve
   ray.init()
   serve.shutdown()
   serve.start(detached=True)
   "
   ```

### Common Issues:

1. **Namespace Mismatch**: Ensure all components use the same Ray namespace
2. **Connection Issues**: Verify Ray address configuration
3. **Timing Issues**: Wait for Ray to be fully ready before deploying applications

## 📝 Notes

- **Ray 2.20.0 Changes**: Stricter namespace isolation requires proper connection management
- **Dashboard Integration**: Applications must be in the same namespace as the dashboard
- **External Access**: External containers should use `ray://ray-head:10001` address
- **Local Access**: Local processes should use `ray.init()` without address

---

**Status**: ✅ **Fixed** - Ray Serve applications now properly visible in Ray Dashboard 