# Ray Actor Enhancement Summary

## ✅ What We've Accomplished

### 1. Enhanced bootstrap.py
- **Race-safe actor creation** with `get_if_exists=True` support
- **Auto Ray initialization** when needed
- **Consistent namespace handling** across all actor operations
- **Better error handling and logging**
- **Fixed function names**: `get_mv_store()` → `get_mw_store()`

### 2. Enhanced working_memory.py
- **Robust MwManager** with resilient actor lookups
- **Async-safe operations** using threadpool for Ray calls
- **Configurable behavior** via environment variables
- **Retry logic with backoff** for startup race conditions
- **Optional auto-creation** of missing actors
- **Better error messages** and structured logging

### 3. Updated Import Patterns
- **Centralized imports** from `src.seedcore.bootstrap`
- **Consistent namespace usage** across all actor lookups
- **Fixed all call sites** to use the new import pattern

## 🔧 Key Improvements

### Namespace Consistency
- All actor lookups now use the same namespace logic
- Prevents the "Failed to look up actor with name 'mw'" error
- Supports both explicit `RAY_NAMESPACE` and runtime context

### Resilience
- **12 retries with 0.5s backoff** for actor lookups
- **Race-safe creation** using `get_if_exists=True`
- **Graceful fallbacks** when actors are missing

### Configuration
- **Environment-driven** behavior control
- **AUTO_CREATE=1** for automatic actor creation
- **Configurable retry behavior** and timeouts

## 🚀 Next Steps

### 1. Set Environment Variables
Ensure consistent environment across all services:

```bash
# Required
export RAY_NAMESPACE=seedcore-dev

# Optional but recommended
export RAY_ADDRESS=auto
export AUTO_CREATE=1  # If you want missing actors auto-created
```

### 2. Update Service Startup
Early in your service startup (e.g., in `serve_entrypoint.py` or main app):

```python
from src.seedcore.bootstrap import bootstrap_actors

# Ensure all singleton actors exist
bootstrap_actors()  # Creates 'mw', 'miss_tracker', 'shared_cache' as detached
```

### 3. Restart Services
- **Restart your seedcore-api container** to pick up the code changes
- **Verify bootstrap process** runs successfully during startup
- **Check that the 'mw' actor** is now accessible

### 4. Test the Fix
The error should no longer occur:
```
❌ Before: Failed to look up actor with name 'mw'
✅ After: ✅ MwManager for organ='utility_organ_1_agent_0' ready
```

## 🔍 Verification

### Check Actor Status
```bash
# From ray-head container
python -m scripts.monitor_actors

# Or check directly
python -c "
import ray
ray.init(address='ray://ray-head:10001', namespace='seedcore-dev')
print('✅ Ray initialized')
print('🎭 Actors:', ray.list_named_actors())
"
```

### Expected Output
```
📊 Singleton Actors Status:
🎭 MissTracker: ✅ Running
🎭 SharedCache: ✅ Running  
🎭 MwStore: ✅ Running
```

## 🎯 Benefits

1. **No more namespace mismatches** - consistent actor lookups
2. **Faster startup** - race-safe actor creation
3. **Better debugging** - structured error messages
4. **Async compatibility** - non-blocking Ray operations
5. **Configurable behavior** - environment-driven settings
6. **Resilient operation** - retry logic and fallbacks

## 🚨 Troubleshooting

### If actors still can't be found:
1. **Check namespace consistency**: Ensure `RAY_NAMESPACE` is set the same everywhere
2. **Verify bootstrap ran**: Look for "Ray initialized" and "Bootstrapped actors" logs
3. **Check Ray cluster health**: Ensure Ray is running and accessible
4. **Enable auto-create**: Set `AUTO_CREATE=1` for automatic actor creation

### Common Issues:
- **Namespace mismatch**: Different services using different namespaces
- **Bootstrap not called**: Actors never created during startup
- **Ray not initialized**: Service trying to use Ray before initialization
- **Permission issues**: Ray cluster access problems

## 📚 Additional Resources

- **Ray Namespace Documentation**: https://docs.ray.io/en/latest/ray-core/actors/namespaces.html
- **KubeRay Best Practices**: https://ray-project.github.io/kuberay/
- **Actor Lifecycle Management**: https://docs.ray.io/en/latest/ray-core/actors/actor-lifecycle.html

