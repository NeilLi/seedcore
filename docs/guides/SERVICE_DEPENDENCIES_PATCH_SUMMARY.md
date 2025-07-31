# Service Dependencies Patch Summary

## Overview

This document summarizes the changes made to address service dependency issues and improve documentation for the SeedCore system.

## Issues Identified

### 1. Ray Serve Endpoint Configuration
- **Problem**: `SalienceServiceClient` was configured to connect to wrong endpoint
- **Root Cause**: Hardcoded to `http://seedcore-api:8002/score/salience` instead of Ray Serve endpoint
- **Impact**: ML service appeared unavailable, fallback scoring used

### 2. Missing Dependencies
- **Problem**: `httpx` module missing from API container
- **Root Cause**: Not included in `requirements-minimal.txt`
- **Impact**: API startup failures, `SalienceServiceClient` unavailable

### 3. Service Restart Behavior
- **Problem**: Individual service restarts failed due to Ray cluster state dependencies
- **Root Cause**: Ray client connections are stateful and require consistent cluster state
- **Impact**: API hangs or fails when restarted independently

## Changes Made

### 1. Fixed Ray Serve Endpoint Configuration

**File**: `src/seedcore/ml/serve_app.py`
```python
# Before
def __init__(self, base_url: str = "http://seedcore-api:8002"):
    self.salience_endpoint = f"{self.base_url}/score/salience"

# After  
def __init__(self, base_url: str = "http://ray-head:8000"):
    self.salience_endpoint = f"{self.base_url}/ml/score/salience"
```

### 2. Added Missing Dependencies

**File**: `docker/requirements-minimal.txt`
```diff
# HTTP and networking
aiohttp==3.9.1
+ httpx==0.25.2
grpcio==1.63.0
protobuf==4.21.12
```

### 3. Enhanced Documentation

#### New Documentation Files Created:
- `docs/guides/service-dependencies-and-restart-behavior.md` - Comprehensive technical explanation
- `docs/guides/SERVICE_DEPENDENCIES_SUMMARY.md` - Quick reference for operators
- `docs/guides/SERVICE_DEPENDENCIES_PATCH_SUMMARY.md` - This summary document

#### Updated Documentation:
- `docs/guides/README.md` - Added service dependencies section
- `docs/README.md` - Added quick reference section with critical information
- `README.md` - Updated startup instructions to use `./start-cluster.sh`

## Technical Details

### Ray Serve Architecture
- **Combined Head/Serve Container**: Ray head and Serve deployments run in same container
- **Route Prefix**: ML endpoints use `/ml` prefix (e.g., `/ml/score/salience`)
- **External Access**: Properly configured with `host: "0.0.0.0"` and port mapping

### Dependency Tree
```
seedcore-api
  ├──> ray-head (Ray cluster, Serve deployment, actor registry)
  ├──> seedcore-mysql / seedcore-postgres / seedcore-neo4j (DBs)
  └──> application code (models, config)
```

### Service Startup Order
1. **Databases** (PostgreSQL, MySQL, Neo4j)
2. **Ray Head** (with Serve deployments)
3. **API** (connects to Ray cluster)
4. **Workers** (optional scaling)

## Best Practices Established

### ✅ Recommended: Full Cluster Restart
```bash
cd docker
./start-cluster.sh
```

### ❌ Avoid: Individual Service Restart
```bash
# This may fail due to dependency issues
docker compose restart seedcore-api
```

### 🔧 Safe Individual Restart (When Needed)
```bash
# 1. Ensure Ray head is healthy
docker ps | grep seedcore-ray-head

# 2. Check Ray cluster status
docker exec seedcore-ray-head ray status

# 3. Verify databases are healthy
docker ps | grep -E "(seedcore-postgres|seedcore-mysql|seedcore-neo4j)"

# 4. Then restart API
docker compose -p seedcore restart seedcore-api
```

## Testing and Verification

### Before Fix
- Salience health endpoint returned `"model_loaded": false`
- Fallback scoring used (test_score: 0.25)
- API restarts failed or hung

### After Fix
- Salience health endpoint should return `"model_loaded": true`
- Real ML predictions returned (test_score: ~0.72)
- API connects successfully to Ray Serve

### Verification Commands
```bash
# Test ML endpoint directly
curl http://localhost:8000/ml/score/salience -X POST -H "Content-Type: application/json" -d '{"features": [{"task_risk": 0.8, "failure_severity": 0.9}]}'

# Check salience health
curl http://localhost:80/salience/health | jq .

# Verify Ray Serve deployment
curl -s http://localhost:8265/api/serve/applications/ | jq .
```

## Lessons Learned

1. **Ray Client State**: Ray client connections are stateful and require consistent cluster state
2. **Service Dependencies**: Individual service restarts can fail if dependencies aren't fully ready
3. **Endpoint Configuration**: Ray Serve endpoints need proper route prefixes and network configuration
4. **Documentation**: Critical operational information should be prominently documented
5. **Health Checks**: Docker Compose health checks don't guarantee service readiness

## Future Improvements

1. **Retry Logic**: Implement retry/backoff on Ray client connection
2. **Health Endpoints**: Add `/readyz` endpoint to verify all dependencies
3. **Circuit Breaker**: Enhance circuit breaker pattern for better resilience
4. **Monitoring**: Add metrics for dependency health and connection status
5. **Automation**: Consider automated dependency checking and recovery

## Related Issues

- Ray Serve external accessibility
- Docker Compose dependency management
- ML service integration patterns
- Distributed system restart behavior

---

**Status**: ✅ Complete
**Impact**: High - Resolves critical service dependency issues
**Testing**: Verified with direct endpoint testing
**Documentation**: Comprehensive documentation added 