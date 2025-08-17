# MW Actor Bootstrap Fix Summary

## 🚨 Problem Identified

The error `Failed to look up actor 'mw' in namespace 'seedcore-dev'` occurred because:

1. **RayAgent initialization** was trying to create `MwManager` instances
2. **MwManager initialization** was trying to connect to the `mw` actor
3. **The `mw` actor didn't exist** because `bootstrap_actors()` was never called
4. **The organism manager** was creating agents without ensuring prerequisite actors existed

## 🔍 Root Cause Analysis

### Missing Bootstrap Call
The `organism_manager.py` was creating agents that needed memory managers, but it wasn't calling `bootstrap_actors()` to ensure the required singleton actors existed first.

### Required Singleton Actors
The system needs these actors to be created before agents can initialize:
- **`mw`** - MwStore for working memory management
- **`miss_tracker`** - MissTracker for tracking cache misses
- **`shared_cache`** - SharedCache for cluster-wide caching

### Configuration Issue
The `working_memory.py` module has `CONFIG.auto_create = False` by default, which means it won't automatically create missing actors. This requires explicit bootstrap.

## ✅ Fix Implemented

### 1. Added Bootstrap Call to Organism Manager

**File**: `src/seedcore/organs/organism_manager.py`

**Location**: After Ray initialization, before creating agents

**Code Added**:
```python
# Bootstrap required singleton actors (mw, miss_tracker, shared_cache)
try:
    from ..bootstrap import bootstrap_actors
    logger.info("🚀 Bootstrapping required singleton actors...")
    bootstrap_actors()
    logger.info("✅ Singleton actors bootstrapped successfully")
except Exception as e:
    logger.warning(f"⚠️ Failed to bootstrap singleton actors: {e}")
    logger.warning("⚠️ Agents may have limited functionality without memory managers")
```

### 2. What This Fix Does

1. **Ensures prerequisite actors exist** before any agents are created
2. **Creates the `mw` actor** in the correct namespace (`seedcore-dev`)
3. **Creates `miss_tracker` and `shared_cache` actors** for complete functionality
4. **Provides graceful fallback** if bootstrap fails (agents continue with limited functionality)

## 🔧 How the Fix Works

### Bootstrap Sequence
1. **Ray initialization** - Ensures Ray is running in the correct namespace
2. **Bootstrap actors** - Creates `mw`, `miss_tracker`, `shared_cache` as detached actors
3. **Agent creation** - Agents can now successfully connect to memory managers
4. **Memory manager initialization** - `MwManager` can connect to the `mw` actor

### Actor Creation Details
```python
def bootstrap_actors():
    """Ensure all singleton actors exist; return handles as a tuple."""
    miss_tracker = _get_or_create(MissTracker, "miss_tracker")
    shared_cache = _get_or_create(SharedCache, "shared_cache")
    mw_store = _get_or_create(MwStore, "mw")
    return miss_tracker, shared_cache, mw_store
```

## 🧪 Testing

### Test Script Created
- **File**: `scripts/test_bootstrap_fix.py`
- **Purpose**: Verify that the bootstrap fix resolves the mw actor error
- **Tests**:
  1. Environment configuration check
  2. Bootstrap actors functionality
  3. MW actor availability verification
  4. MwManager initialization
  5. RayAgent memory manager initialization

### Running Tests
```bash
# Set environment variables
export SEEDCORE_NS=seedcore-dev
export RAY_NAMESPACE=seedcore-dev

# Run the test script
python3 scripts/test_bootstrap_fix.py
```

## 🚀 Expected Results After Fix

### Before Fix
```
ERROR:src.seedcore.agents.tier0_manager:❌ Failed to initialize Ray: name 'os' is not defined
ERROR:src.seedcore.agents.ray_actor:⚠️ Failed to initialize memory managers for cognitive_organ_1_agent_0: Failed to look up actor 'mw' in namespace 'seedcore-dev'
```

### After Fix
```
INFO:src.seedcore.organs.organism_manager:✅ Ray initialized locally with namespace: seedcore-dev
INFO:src.seedcore.organs.organism_manager:🚀 Bootstrapping required singleton actors...
INFO:src.seedcore.organs.organism_manager:✅ Singleton actors bootstrapped successfully
INFO:src.seedcore.agents.ray_actor:✅ Agent cognitive_organ_1_agent_0 initialized with memory managers
```

## 🔍 Verification Commands

### Check Actor Availability
```bash
# List actors in the correct namespace
ray list actors --namespace seedcore-dev

# Check specific actors
ray get-actor mw --namespace seedcore-dev
ray get-actor miss_tracker --namespace seedcore-dev
ray get-actor shared_cache --namespace seedcore-dev
```

### Check Ray Dashboard
```bash
# Check actor tables in Ray dashboard
curl -s http://localhost:8265/api/v0/actors | jq '.data.result.result | map(select(.state=="ALIVE")) | length'
```

## 🎯 Key Benefits of the Fix

1. **Eliminates the mw actor error** - Agents can now initialize memory managers
2. **Ensures proper startup sequence** - Prerequisites are created before dependencies
3. **Maintains namespace consistency** - All actors are created in `seedcore-dev`
4. **Provides graceful degradation** - System continues even if some actors fail
5. **Improves reliability** - No more "Failed to look up actor" errors

## 🚨 Important Notes

### Environment Variables Required
Make sure these are set in your deployment:
```bash
export SEEDCORE_NS=seedcore-dev
export RAY_NAMESPACE=seedcore-dev  # Optional, will use SEEDCORE_NS if not set
```

### Deployment Order
1. **Ray cluster** must be running
2. **Environment variables** must be set
3. **Organism manager** will bootstrap actors automatically
4. **Agents** can then be created successfully

### Monitoring
After deployment, verify:
- `bootstrap_actors()` is called successfully
- `mw`, `miss_tracker`, `shared_cache` actors are visible
- Agents initialize without memory manager errors
- No more "Failed to look up actor 'mw'" errors

## 🔄 Alternative Solutions

### Option 1: Enable AUTO_CREATE
```bash
export AUTO_CREATE=1
```
This would let the working_memory module create actors automatically, but bootstrap is preferred for explicit control.

### Option 2: Manual Actor Creation
```python
# Create actors manually before creating agents
from seedcore.bootstrap import bootstrap_actors
bootstrap_actors()
```

### Option 3: Lazy Initialization
Modify MwManager to handle missing actors gracefully, but this reduces functionality.

## 📚 Related Documentation

- [Namespace Fix Summary](./NAMESPACE_FIX_SUMMARY.md)
- [Ray Configuration Pattern](../RAY_CONFIGURATION_PATTERN.md)
- [Working Memory Architecture](../memory/working_memory.py)
- [Bootstrap Module](../bootstrap.py)

## 🎉 Summary

The fix ensures that **required singleton actors are created before agents need them**, eliminating the "Failed to look up actor 'mw'" error. By adding a bootstrap call to the organism manager, the system now:

✅ **Creates prerequisite actors** in the correct namespace  
✅ **Initializes memory managers** successfully  
✅ **Eliminates startup errors** related to missing actors  
✅ **Maintains system reliability** with proper initialization sequence  

This fix, combined with the earlier namespace fixes, should resolve all the Ray actor visibility and initialization issues you were experiencing.
