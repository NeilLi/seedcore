# Docker Python Scripts Service URL Updates

## Overview

This document describes the updates made to all scripts in the `docker/python-scripts` subfolder to use the correct service URLs for the seedcore-api pod environment.

## Service URL Changes

### Before (Hardcoded)
- **ML Service**: `http://localhost:8000`
- **Ray Dashboard**: `http://localhost:8265`

### After (Environment-Aware)
- **In seedcore-api pod**: `http://seedcore-svc-serve-svc:8000`
- **In local development**: `http://localhost:8000` (fallback)

## Files Updated

### 1. `xgboost_coa_integration_demo.py` ✅
- **Status**: Already updated by user
- **Changes**: Uses `http://seedcore-svc-serve-svc:8000` in seedcore-api pod
- **Function**: `get_service_url()` added

### 2. `xgboost_docker_demo.py` ✅
- **Status**: Already updated by user
- **Changes**: Uses `http://seedcore-svc-serve-svc:8000` in seedcore-api pod
- **Function**: `get_service_url()` added

### 3. `test_xgboost_minimal.py` ✅
- **Status**: Updated
- **Changes**: 
  - Added `get_service_url()` function
  - Updated all hardcoded URLs to use dynamic service URLs
  - Added environment-aware service discovery
- **Endpoints Updated**:
  - `/health` → `{base_url}/health`
  - `/xgboost/train` → `{base_url}/xgboost/train`
  - `/xgboost/list_models` → `{base_url}/xgboost/list_models`
  - `/xgboost/predict` → `{base_url}/xgboost/predict`

### 4. `verify_xgboost_service.py` ✅
- **Status**: Updated
- **Changes**:
  - Added `get_service_url()` function
  - Updated all hardcoded URLs to use dynamic service URLs
  - Added environment-aware service discovery
- **Endpoints Updated**:
  - `/health` → `{base_url}/health`
  - `/xgboost/list_models` → `{base_url}/xgboost/list_models`
  - `/xgboost/model_info` → `{base_url}/xgboost/model_info`
  - API access URL display → dynamic

### 5. `test_xgboost_integration_simple.py` ✅
- **Status**: Updated
- **Changes**:
  - Added `get_service_url()` function
  - Updated all hardcoded URLs to use dynamic service URLs
  - Added environment-aware service discovery
- **Endpoints Updated**:
  - `/health` → `{base_url}/health`
  - `/xgboost/train` → `{base_url}/xgboost/train`
  - `/xgboost/list_models` → `{base_url}/xgboost/list_models`
  - `/xgboost/predict` → `{base_url}/xgboost/predict`

### 6. `test_xgboost_docker.py` ✅
- **Status**: Updated
- **Changes**:
  - Added `get_service_url()` function
  - Updated all hardcoded URLs to use dynamic service URLs
  - Added environment-aware service discovery
- **Endpoints Updated**:
  - `/health` → `{base_url}/health`
  - `/xgboost/list_models` → `{base_url}/xgboost/list_models`
  - `/xgboost/model_info` → `{base_url}/xgboost/model_info`
  - `/xgboost/train` → `{base_url}/xgboost/train`
  - `/xgboost/predict` → `{base_url}/xgboost/predict`

### 7. `test_serve_simple.py` ⚠️
- **Status**: No changes needed
- **Reason**: This script is for local Ray Serve testing and should keep localhost URLs
- **Note**: Designed to run locally, not in seedcore-api pod

### 8. `init_xgboost_service.py` ⚠️
- **Status**: No changes needed
- **Reason**: No HTTP endpoints used, only internal service calls
- **Note**: Service initialization script, no external HTTP calls

### 9. `test_ray_basic.py` ⚠️
- **Status**: No changes needed
- **Reason**: No HTTP endpoints used, only Ray internal operations
- **Note**: Ray connectivity test script, no external HTTP calls

## Implementation Details

### Service URL Function
All updated scripts now include this function:

```python
def get_service_url():
    """Get service URL based on environment."""
    # Check if we're running in seedcore-api pod
    if os.getenv('SEEDCORE_API_ADDRESS'):
        # We're in the seedcore-api pod, use internal service names
        return "http://seedcore-svc-serve-svc:8000"
    else:
        # Local development or ray head pod
        return "http://localhost:8000"
```

### Usage Pattern
Scripts now use this pattern for all HTTP requests:

```python
base_url = get_service_url()
response = requests.get(f"{base_url}/health", timeout=10)
```

### Environment Detection
- **`SEEDCORE_API_ADDRESS`** environment variable indicates seedcore-api pod
- **When set**: Uses `seedcore-svc-serve-svc:8000`
- **When not set**: Falls back to `localhost:8000`

## Benefits

1. **Environment Agnostic**: Scripts work in both seedcore-api pod and local development
2. **Automatic Discovery**: No manual configuration needed
3. **Consistent URLs**: All scripts use the same service discovery logic
4. **Easy Maintenance**: Single function to update service URLs
5. **Better Debugging**: Clear indication of which service is being used

## Testing

To verify the updates work correctly:

1. **In seedcore-api pod**:
   ```bash
   python docker/python-scripts/test_xgboost_minimal.py
   ```

2. **Locally**:
   ```bash
   python docker/python-scripts/test_xgboost_minimal.py
   ```

The scripts will automatically detect the environment and use the appropriate service URLs.

## Future Considerations

1. **Service Discovery**: Consider implementing Kubernetes service discovery
2. **Configuration**: Add support for custom service URLs via environment variables
3. **Health Checks**: Add service health monitoring and fallback logic
4. **Metrics**: Track service connectivity and performance metrics
