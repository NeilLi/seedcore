# Ray Serve Connection Fix

## Issue Summary
The `serve_entrypoint.py` script was failing with `RuntimeError: RAY_ADDRESS env var not set!` even though the environment variable was properly configured in Docker Compose.

## Root Cause Analysis
The issue was **NOT** that `RAY_ADDRESS` was missing, but rather a **double Ray initialization problem**:

1. **Ray was started** with `ray start --head` in the startup script
2. **Ray was initialized** with `ray.init()` in the startup script's Python block
3. **serve_entrypoint.py tried to initialize Ray again** with `ray.init(address=RAY_ADDRESS, log_to_driver=False)`

This caused the error: `RuntimeError: Ray Client is already connected. Maybe you called ray.init("ray://<address>") twice by accident?`

## Solution
Modified `serve_entrypoint.py` to check if Ray is already initialized before attempting to initialize it again:

```python
# Check if Ray is already initialized to avoid double initialization
if not ray.is_initialized():
    ray.init(address=RAY_ADDRESS, log_to_driver=False)
else:
    print("✅ Ray is already initialized, skipping initialization")
```

## Configuration Details
- **Ray Head Node**: `172.18.0.2:6379` (internal Redis)
- **Ray Client Server**: `172.18.0.2:10001` (for client connections)
- **Ray Dashboard**: `172.18.0.2:8265` (web UI)
- **Ray Serve**: `172.18.0.2:8000` (ML API endpoints)
- **Environment Variable**: `RAY_ADDRESS=ray://localhost:10001`

## Verification
Ray Serve is now working correctly and responding to health checks:
```bash
curl http://localhost:8000
# Returns: {"status":"ok","service":"seedcore-ml","version":"1.0.0",...}
```

## Files Modified
- `docker/serve_entrypoint.py` - Added Ray initialization check
- `docker/docker-compose.yml` - Added RAY_ADDRESS environment variable
- `docker/start-ray-with-serve.sh` - Added RAY_ADDRESS export

## Date
August 2, 2025 