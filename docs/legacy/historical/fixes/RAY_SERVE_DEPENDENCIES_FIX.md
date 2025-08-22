# Ray Serve Dependencies Fix

## Issue
The error `ModuleNotFoundError: No module named 'aiorwlock'` occurred because Ray Serve requires additional dependencies that weren't included in the requirements files.

## Root Cause
Ray Serve 2.20.0 has dependencies on:
- `aiorwlock` - For async read-write locks
- `aioredis` - For async Redis operations

These dependencies are not automatically installed with `ray[default]` and need to be explicitly added.

## Fix Applied

### 1. **Updated `docker/requirements-minimal.txt`**
```txt
# Ray Serve dependencies
aiorwlock==1.3.0
aioredis==2.0.1
```

### 2. **Updated `requirements.txt`**
```txt
ray==2.20.0
aiorwlock==1.3.0
aioredis==2.0.1
```

## Why These Dependencies Are Needed

- **`aiorwlock`**: Ray Serve uses this for managing concurrent access to deployment state and configuration
- **`aioredis`**: Ray Serve uses Redis for internal state management and caching

## Testing

After rebuilding with the updated dependencies:

1. **Rebuild the image**:
   ```bash
   docker compose --profile core --profile ray build --no-cache ray-head
   ```

2. **Start the cluster**:
   ```bash
   ./start-cluster.sh up 3
   ```

3. **Verify Ray Serve starts without errors**:
   ```bash
   docker logs seedcore-ray-head | grep -E "(ERROR|aiorwlock|aioredis)"
   ```

## Expected Result
- ✅ Ray Serve should start without the `ModuleNotFoundError`
- ✅ The MLService deployment should become healthy
- ✅ ML endpoints should be available at http://localhost:8000

## Additional Notes
If you encounter similar dependency issues in the future, you can check Ray Serve's requirements by running:
```bash
pip show ray[serve]
```

This will show all the dependencies that Ray Serve needs. 