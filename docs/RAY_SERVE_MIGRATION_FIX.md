# Ray Serve Migration Fix

## Overview

This document describes the fix applied to resolve the **transition from raw Ray actors → Ray Serve deployments** issue that was causing the `Dispatcher` to fail when trying to connect to the `Coordinator`.

## 🔍 What Was Happening

The `Dispatcher` was trying to do:

```python
coord = ray.get_actor("seedcore_coordinator", namespace=RAY_NS)
```

But the system had already transitioned to using Ray Serve deployments:

* `OrganismManager` (and the old `Coordinator`) are now running as **Serve deployments**, not raw `ray.remote` actors
* `ray.get_actor()` only works for **named actors**, not Serve deployments
* Serve manages its replicas internally and doesn't register them as named actors unless explicitly configured

So the Dispatcher couldn't find `seedcore_coordinator`, causing **lookup failures**.

## ✅ Fix Applied

### Option A: Use Serve Deployment Handles (Chosen)

Instead of `ray.get_actor`, the code now uses Serve deployment handles:

```python
from ray import serve

# Before (broken):
coord = ray.get_actor("seedcore_coordinator", namespace=RAY_NS)

# After (fixed):
coord = serve.get_deployment_handle("OrganismManager", app_name="organism")
```

Then calls are made using the Serve deployment handle:

```python
# Before (broken):
result = await coord.handle.remote(task)

# After (fixed):
result = await coord.handle_incoming_task.remote(task)
```

## 📝 Files Updated

### 1. `src/seedcore/agents/queue_dispatcher.py`
- ✅ Added `from ray import serve` import
- ✅ Updated `Dispatcher.run()` to use `serve.get_deployment_handle("OrganismManager", app_name="organism")`
- ✅ Updated `_process_one()` to call `coord_handle.handle_incoming_task.remote()` instead of `coord.handle.remote()`
- ✅ Removed the old `Coordinator` class entirely
- ✅ Updated bootstrap function to remove Coordinator references
- ✅ Improved connection handling with fresh pooled connections for writes
- ✅ Enhanced watchdog timing with monotonic timestamps

### 2. `src/seedcore/api/routers/tasks_router.py`
- ✅ Updated task submission to use OrganismManager Serve deployment handle
- ✅ Updated coordinator health check endpoint to use Serve deployment health endpoint

### 3. `src/seedcore/telemetry/server.py`
- ✅ Updated coordinator proxy functions to use OrganismManager Serve deployment
- ✅ Updated health checks to use Serve deployment health endpoints

### 4. `scripts/bootstrap_dispatchers.py`
- ✅ Updated logging to reflect OrganismManager Serve deployment
- ✅ Removed Coordinator health checks from monitoring loop

### 5. `scripts/verify_env_vars.py`
- ✅ Updated to check OrganismManager Serve deployment health instead of Coordinator actor

### 6. `scripts/test_bootstrap.py`
- ✅ Updated coordinator health test to use OrganismManager Serve deployment
- ✅ Updated task creation test to use Serve deployment handle

## 🚀 Benefits of This Fix

1. **Aligned Architecture**: Dispatcher now properly integrates with the Serve-first architecture
2. **Cleaner Code**: No more fragile `ray.get_actor` lookups
3. **Better Scalability**: Serve deployments provide better autoscaling and health management
4. **Consistent Pattern**: All components now use the same Serve deployment approach

## 🔧 How It Works Now

1. **Dispatcher** gets a handle to the `OrganismManager` Serve deployment using `serve.get_deployment_handle("OrganismManager", app_name="organism")`
2. **Dispatcher** submits tasks via `coord_handle.handle_incoming_task.remote(task)`
3. **OrganismManager** Serve deployment processes tasks and returns results
4. **Dispatcher** writes results back to the database using fresh pooled connections for thread safety

## 🧪 Testing

The fix can be verified by:

1. Running the updated bootstrap script
2. Checking that dispatchers can successfully connect to the OrganismManager
3. Submitting test tasks and verifying they complete successfully
4. Running the verification scripts to confirm health checks pass

## 📚 Related Documentation

- [Coordinator Migration Summary](COORDINATOR_MIGRATION_SUMMARY.md)
- [Ray Serve Configuration](deploy/rayservice.yaml)
- [Organism Entrypoint](entrypoints/organism_entrypoint.py)

## ⚠️ Important Notes

- The old `Coordinator` Ray actor class has been completely removed
- All health checks now go through Serve deployment endpoints
- The Dispatcher no longer needs to manage Coordinator lifecycle (Serve handles this)
- Environment variable verification now checks Serve deployment health instead of actor methods
