# Namespace Fix Summary

## 🚨 Problem Identified

The issue was a **namespace mismatch** where Ray agents were being created in the `seedcore` namespace but the system was looking for them in the `seedcore-dev` namespace. This caused:

1. ✅ **Agents to be created successfully** (logs showed "created")
2. ❌ **Agents to disappear immediately** (not visible in `seedcore-dev` namespace)
3. ❌ **Empty actor tables** in the Ray dashboard
4. ❌ **Failed dependency lookups** (e.g., "Failed to look up actor 'mw' in namespace 'seedcore-dev'")

## 🔍 Root Cause Analysis

### Environment Configuration
- **Expected namespace**: `seedcore-dev` (set in environment variables)
- **Actual namespace used**: `seedcore` (hardcoded in multiple files)

### Files with Hardcoded Namespaces
1. `src/seedcore/organs/organism_manager.py` - Lines 128, 132
2. `src/seedcore/agents/tier0_manager.py` - Lines 278, 283  
3. `src/seedcore/utils/ray_utils.py` - Lines 142, 165
4. `src/seedcore/config/ray_config.py` - Line 40
5. `src/seedcore/api/routers/tier0_router.py` - Line 165
6. `src/seedcore/serve/simple_app.py` - Line 97
7. `entrypoints/cognitive_entrypoint.py` - Line 37
8. Various script files in `scripts/` directory

## ✅ Fixes Implemented

### 1. Core Library Files

#### `src/seedcore/organs/organism_manager.py`
```python
# BEFORE (hardcoded):
ray.init(address=ray_address, ignore_reinit_error=True, namespace="seedcore")

# AFTER (environment-driven):
ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
ray.init(address=ray_address, ignore_reinit_error=True, namespace=ray_namespace)
```

#### `src/seedcore/agents/tier0_manager.py`
```python
# BEFORE (hardcoded):
ray_namespace = os.getenv("RAY_NAMESPACE", "seedcore")

# AFTER (environment-driven):
ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
```

#### `src/seedcore/utils/ray_utils.py`
```python
# BEFORE (hardcoded):
ray.init(address=ray_address, ignore_reinit_error=True, namespace="seedcore")

# AFTER (environment-driven):
ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
ray.init(address=ray_address, ignore_reinit_error=True, namespace=ray_namespace)
```

#### `src/seedcore/config/ray_config.py`
```python
# BEFORE (hardcoded):
self.namespace = "seedcore"

# AFTER (environment-driven):
self.namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
```

### 2. API and Service Files

#### `src/seedcore/api/routers/tier0_router.py`
```python
# BEFORE (hardcoded):
ns = os.getenv("RAY_NAMESPACE", "seedcore")

# AFTER (environment-driven):
ns = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
```

#### `src/seedcore/serve/simple_app.py`
```python
# BEFORE (hardcoded):
ray.init(address="auto", namespace="seedcore")

# AFTER (environment-driven):
ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
ray.init(address="auto", namespace=ray_namespace)
```

### 3. Docker Entrypoint Files

#### `entrypoints/cognitive_entrypoint.py`
```python
# BEFORE (hardcoded):
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore")

# AFTER (environment-driven):
RAY_NS = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
```

### 4. Script Files

#### `scripts/ray_monitor_live.py`
```python
# BEFORE (hardcoded):
actor = ray.get_actor(name, namespace='seedcore')

# AFTER (environment-driven):
ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
actor = ray.get_actor(name, namespace=ray_namespace)
```

## 🔧 Environment Variable Priority

The fix implements a consistent priority order for namespace resolution:

1. **`RAY_NAMESPACE`** - Highest priority (explicit override)
2. **`SEEDCORE_NS`** - Medium priority (SeedCore-specific setting)
3. **`"seedcore-dev"`** - Default fallback (consistent with deployment configs)

```python
ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
```

## 🧪 Testing

### Test Script Created
- **File**: `scripts/test_namespace_fix.py`
- **Purpose**: Verify namespace consistency across all components
- **Tests**:
  1. Namespace consistency check
  2. Ray initialization with correct namespace
  3. Agent creation in correct namespace
  4. Namespace visibility verification

### Running Tests
```bash
# Set environment variables
export SEEDCORE_NS=seedcore-dev
export RAY_ADDRESS=ray://ray-head:10001

# Run the test script
python scripts/test_namespace_fix.py
```

## 🚀 Expected Results After Fix

### Before Fix
```
✅ Agents created successfully
❌ Agents not visible in seedcore-dev namespace
❌ Empty actor tables
❌ Failed dependency lookups
```

### After Fix
```
✅ Agents created successfully
✅ Agents visible in seedcore-dev namespace
✅ Actor tables populated
✅ Dependency lookups successful
✅ Agents remain alive (detached lifetime)
```

## 🔍 Verification Commands

### Check Namespace Consistency
```bash
# Verify environment variables
echo "SEEDCORE_NS: $SEEDCORE_NS"
echo "RAY_NAMESPACE: $RAY_NAMESPACE"

# Check Ray dashboard
curl -s http://localhost:8265/api/v0/actors | jq '.data.result.result | map(select(.state=="ALIVE")) | length'
```

### Check Agent Visibility
```bash
# List actors in the correct namespace
ray list actors --namespace seedcore-dev

# Check specific agents
ray get-actor cognitive_organ_1_agent_0 --namespace seedcore-dev
```

## 🎯 Key Benefits of the Fix

1. **Consistent Namespace Usage** - All components now use the same namespace
2. **Environment-Driven Configuration** - No more hardcoded values
3. **Deployment Flexibility** - Easy to change namespaces via environment variables
4. **Agent Persistence** - Agents now stay alive in the correct namespace
5. **Proper Dependency Resolution** - Memory managers and other actors can be found

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
3. **SeedCore services** can then be deployed

### Monitoring
After deployment, verify:
- Agents are visible in `ray list actors --namespace seedcore-dev`
- Actor tables in Ray dashboard show the agents
- No more "Failed to look up actor" errors

## 🔄 Rollback Plan

If issues occur, you can temporarily revert by setting:
```bash
export RAY_NAMESPACE=seedcore
export SEEDCORE_NS=seedcore
```

But this is not recommended as it reintroduces the namespace mismatch problem.

## 📚 Related Documentation

- [Ray Configuration Pattern](../RAY_CONFIGURATION_PATTERN.md)
- [Ray Cluster Diagnostics](../monitoring/setup/ray-cluster-diagnostics.md)
- [Agent Distribution Analysis](../monitoring/setup/AGENT_DISTRIBUTION_ANALYSIS.md)
