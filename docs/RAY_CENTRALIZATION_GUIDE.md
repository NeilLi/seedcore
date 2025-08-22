# Ray Connection Centralization Guide

This document explains the new centralized approach to managing Ray connections across the SeedCore codebase.

## Overview

Previously, Ray connections were scattered throughout the codebase with inconsistent parameters and connection logic. This made the system hard to maintain and debug. We've now centralized all Ray connection logic into a single, robust utility function.

## The Solution: `ensure_ray_initialized()`

### Location
`src/seedcore/utils/ray_utils.py`

### Function Signature
```python
def ensure_ray_initialized(
    ray_address: Optional[str] = None, 
    ray_namespace: Optional[str] = "seedcore-dev"
) -> bool
```

### Behavior
1. **Idempotent**: Safe to call multiple times
2. **Environment-aware**: Automatically detects the correct connection method
3. **Smart fallback**: Uses environment variables when available

### Connection Logic
1. If already connected, does nothing
2. If `RAY_ADDRESS` env var is set, connects as a client to that address
3. If `RAY_ADDRESS` is not set, connects with `address="auto"` to join existing cluster

## Environment Configuration

### For Client Pods (e.g., `seedcore-api`)
Set `RAY_ADDRESS` to connect to the remote cluster:

```yaml
# seedcore-api-deployment.yaml
spec:
  containers:
  - name: seedcore-api
    env:
    - name: RAY_ADDRESS
      value: "ray://seedcore-svc-head-svc:10001"
    - name: RAY_NAMESPACE
      value: "seedcore-dev"
```

### For Ray Pods (Head and Workers)
**Do NOT** set `RAY_ADDRESS`. The utility will use `address="auto"` to connect to the local Ray instance.

## Usage Examples

### Before (Scattered ray.init calls)
```python
# Old way - scattered throughout codebase
if not ray.is_initialized():
    try:
        ray.init(address=self.config.ray_address, ignore_reinit_error=True, namespace=_env_ns())
    except Exception:
        ray.init(ignore_reinit_error=True, namespace=_env_ns())
```

### After (Centralized utility)
```python
# New way - single, consistent call
from seedcore.utils.ray_utils import ensure_ray_initialized

if not ensure_ray_initialized(ray_address=self.config.ray_address, ray_namespace=_env_ns()):
    raise ConnectionError("Failed to connect to Ray cluster")
```

## Refactored Files

The following files have been updated to use the centralized utility:

- `src/seedcore/cognitive/dspy_client.py`
- `src/seedcore/organs/organism_manager.py`
- `src/seedcore/api/routers/tier0_router.py`
- `src/seedcore/bootstrap.py`
- `src/seedcore/memory/working_memory.py`
- `entrypoints/serve_entrypoint.py`
- `entrypoints/cognitive_entrypoint.py`

## Benefits

1. **Consistency**: All Ray connections use the same logic and parameters
2. **Maintainability**: Single place to update connection logic
3. **Reliability**: Robust error handling and fallback mechanisms
4. **Environment Awareness**: Automatically adapts to different deployment scenarios
5. **Performance**: Module-level flag prevents repeated initialization checks

## Migration Checklist

To complete the migration to the centralized approach:

1. ✅ Replace `ray_utils.py` with optimized implementation
2. ✅ Refactor key files to use `ensure_ray_initialized()`
3. ✅ Update Kubernetes manifests to set `RAY_ADDRESS` correctly
4. ✅ Test in different environments (local, Kubernetes, Docker Compose)
5. ✅ Remove remaining scattered `ray.init()` calls

## Testing

Test the centralized approach in different scenarios:

```bash
# Test as client (should connect to remote cluster)
RAY_ADDRESS="ray://localhost:10001" python -c "
from seedcore.utils.ray_utils import ensure_ray_initialized
print('Success:', ensure_ray_initialized())
"

# Test as Ray pod (should use auto)
python -c "
from seedcore.utils.ray_utils import ensure_ray_initialized
print('Success:', ensure_ray_initialized())
"
```

## Troubleshooting

### Common Issues

1. **Connection refused**: Check if Ray cluster is running and accessible
2. **Namespace mismatch**: Verify `RAY_NAMESPACE` environment variable
3. **Permission denied**: Ensure proper network policies in Kubernetes

### Debug Mode

Enable debug logging to see connection details:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
from seedcore.utils.ray_utils import ensure_ray_initialized
ensure_ray_initialized()
```

## Future Enhancements

1. **Connection pooling**: For high-throughput scenarios
2. **Health monitoring**: Automatic reconnection on failures
3. **Metrics collection**: Track connection success/failure rates
4. **Circuit breaker**: Prevent cascading failures

