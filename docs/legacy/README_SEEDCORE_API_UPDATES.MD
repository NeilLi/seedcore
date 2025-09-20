# SeedCore API Pod XGBoost Demo Updates

## Overview

This document describes the changes made to fix the XGBoost demo scripts to run properly on the `seedcore-api` pod instead of the `ray head` pod.

## Issues Fixed

### 1. Connection Errors
- **Problem**: Demo scripts were hardcoded to connect to `localhost:8000`, but in the seedcore-api pod, the ML service is at `seedcore-head-svc:8000`
- **Solution**: Added environment-aware service URL detection

### 2. Permission Errors
- **Problem**: Demo scripts tried to write to `/data` directory which doesn't have write permissions in the seedcore-api pod
- **Solution**: Added fallback to writable directories (`/tmp`, `/app/tmp`, or current directory + `tmp`)

### 3. Service Discovery
- **Problem**: Hardcoded localhost URLs didn't work in Kubernetes pod environment
- **Solution**: Auto-detection of service URLs based on environment variables

## Files Updated

### 1. `examples/xgboost_demo.py`
- Added `get_service_url()` function for environment-aware URL detection
- Updated all hardcoded `localhost:8000` URLs to use dynamic service URLs
- Fixed CSV file writing to use writable directories
- Added better error handling and timeout configurations
- Improved connection error messages

### 2. `examples/xgboost_tuning_demo.py`
- Added environment-aware service URL detection in constructor
- Updated base URL initialization to auto-detect environment

### 3. `docker/python-scripts/xgboost_docker_demo.py`
- Added `get_service_url()` function
- Updated all hardcoded service URLs
- Added environment-aware service discovery

### 4. `docker/python-scripts/xgboost_coa_integration_demo.py`
- Added `get_service_url()` function
- Updated all hardcoded service URLs
- Added environment-aware service discovery

### 5. `examples/test_environment.py` (New)
- Created environment testing script to debug connectivity issues
- Tests environment variables, service connectivity, and writable directories

## Environment Variables Used

The scripts now automatically detect the environment using these variables:

- `SEEDCORE_API_ADDRESS`: Indicates we're running in the seedcore-api pod
- When set: Uses `http://seedcore-head-svc:8000` for ML service
- When not set: Falls back to `http://localhost:8000` for local development

## Service URLs

### In seedcore-api pod:
- **ML Service**: `http://seedcore-head-svc:8000`
- **Ray Dashboard**: `http://seedcore-head-svc:8265`

### In local development:
- **ML Service**: `http://localhost:8000`
- **Ray Dashboard**: `http://localhost:8265`

## Writable Directories

The scripts now try these directories in order for writing CSV files:

1. `/tmp` - Usually writable in most containers
2. `/app/tmp` - App-specific temp directory (if it exists)
3. `./tmp` - Current directory + tmp subdirectory
4. `/data` - Last resort (may not be writable)

## Usage

### Running in seedcore-api pod:
```bash
# Test environment first
python examples/test_environment.py

# Run XGBoost demo
python examples/xgboost_demo.py

# Run tuning demo
python examples/xgboost_tuning_demo.py
```

### Running locally:
```bash
# The scripts will automatically detect local environment
python examples/xgboost_demo.py
```

## Troubleshooting

### Connection Issues
1. Run `examples/test_environment.py` to check connectivity
2. Verify `seedcore-head-svc` is accessible from the pod
3. Check if Ray cluster is running and healthy

### Permission Issues
1. The scripts will automatically find writable directories
2. Check `/tmp` permissions: `ls -la /tmp`
3. Create a local tmp directory: `mkdir -p tmp`

### Environment Variables
1. Ensure `docker/env.example` is loaded into the pod
2. Check key variables: `echo $SEEDCORE_API_ADDRESS`
3. Verify Ray namespace: `echo $RAY_NAMESPACE`

## Benefits

1. **Environment Agnostic**: Scripts work in both seedcore-api pod and local development
2. **Better Error Handling**: More informative error messages and fallback strategies
3. **Automatic Discovery**: No need to manually configure service URLs
4. **Robust File Operations**: Automatic fallback to writable directories
5. **Improved Debugging**: Better logging and environment testing tools

## Future Improvements

1. Add configuration file support for custom service URLs
2. Implement service health monitoring and retry logic
3. Add metrics collection for service performance
4. Create Kubernetes service discovery integration
5. Add support for multiple Ray clusters
