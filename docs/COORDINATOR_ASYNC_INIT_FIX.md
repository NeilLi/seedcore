# Coordinator Async Initialization Fix

## Problem Description

The Coordinator Ray actor was crashing with the error:
```
RuntimeError: this event loop is already running.
```

This occurred because the Coordinator's `__init__` method was calling:
```python
self.loop.run_until_complete(self.org.initialize_organism())
```

## Root Cause

In Ray actors, the worker process starts an asyncio event loop internally. When you try to call `loop.run_until_complete(...)` inside the actor's `__init__`, you get that error because the loop is already running.

## Solution: Async `__init__` Pattern

Ray supports async initialization of actors. We've implemented this pattern:

```python
@ray.remote(name="seedcore_coordinator", lifetime="detached", num_cpus=0.1, namespace=RAY_NS)
class Coordinator:
    async def __init__(self):
        """
        Async initialization for Ray actor compatibility.
        
        This method is called automatically by Ray when the actor is created.
        It initializes the OrganismManager and waits for it to be ready.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            from src.seedcore.organs.organism_manager import OrganismManager
            
            logger.info("🚀 Initializing Coordinator actor...")
            
            # Create OrganismManager instance
            self.org = OrganismManager()
            
            # Initialize organism inside the actor (Ray already initialized in cluster)
            logger.info("⏳ Initializing organism...")
            await self.org.initialize_organism()
            
            logger.info("✅ Coordinator actor initialization completed successfully")
            
        except Exception as e:
            logger.error(f"❌ Coordinator initialization failed: {e}")
            # Re-raise to ensure Ray knows the actor creation failed
            raise RuntimeError(f"Coordinator initialization failed: {e}") from e
```

## Key Benefits

### 1. **No More Event Loop Errors**
- ✅ Eliminates `RuntimeError: this event loop is already running`
- ✅ Works seamlessly with Ray's internal asyncio event loop
- ✅ No need for workarounds or hacks

### 2. **Proper Error Handling**
- ✅ Initialization failures are properly reported to Ray
- ✅ Actor creation fails fast if initialization fails
- ✅ Comprehensive logging during initialization

### 3. **Better Health Checking**
- ✅ New `get_status()` method provides detailed health information
- ✅ Distinguishes between "initializing" and "healthy" states
- ✅ Bootstrap script can wait for full initialization

### 4. **Robust Task Handling**
- ✅ Task failures are caught and returned as structured errors
- ✅ No more unhandled exceptions crashing the actor
- ✅ Better observability into what's happening

## Implementation Details

### Bootstrap Script Updates

The bootstrap script now properly waits for initialization:

```python
# Wait for the async initialization to complete
logger.info("⏳ Waiting for Coordinator initialization...")

# Use get_status() for more comprehensive health checking
max_wait_time = 60  # seconds
start_time = time.time()

while time.time() - start_time < max_wait_time:
    try:
        status = ray.get(coord_ref.get_status.remote(), timeout=10.0)
        if status.get("status") == "healthy" and status.get("organism_initialized"):
            logger.info("✅ Coordinator actor created and fully initialized")
            break
        elif status.get("status") == "initializing":
            logger.info("⏳ Coordinator still initializing, waiting...")
            time.sleep(2)
        else:
            logger.warning(f"⚠️ Coordinator status: {status}")
            time.sleep(2)
    except Exception as e:
        logger.warning(f"⚠️ Waiting for Coordinator initialization: {e}")
        time.sleep(2)
else:
    # Timeout reached
    raise TimeoutError("Coordinator initialization timed out after 60 seconds")
```

### New Methods

#### `get_status()`
Returns comprehensive health information:
```python
{
    "status": "healthy" | "initializing" | "unhealthy",
    "organism_initialized": bool,
    "coordinator": "available" | "unavailable" | "error",
    "error": str  # Only present if status is "unhealthy"
}
```

#### Enhanced `handle()`
Now includes proper error handling:
```python
async def handle(self, task: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return await self.org.handle_incoming_task(task, app_state=None)
    except Exception as e:
        logger.error(f"❌ Task handling failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "task_type": task.get("type", "unknown")
        }
```

## Testing

### Test Script
Run the test script to verify the fix:
```bash
python scripts/test_coordinator_async_init.py
```

### Unit Tests
Run the unit tests:
```bash
pytest tests/test_coordinator_async_init.py -v
```

## Migration Guide

### Before (Broken)
```python
class Coordinator:
    def __init__(self):
        self.loop = asyncio.get_event_loop()
        self.org = OrganismManager()
        # ❌ This crashes in Ray actors
        self.loop.run_until_complete(self.org.initialize_organism())
```

### After (Fixed)
```python
class Coordinator:
    async def __init__(self):
        self.org = OrganismManager()
        # ✅ This works correctly in Ray actors
        await self.org.initialize_organism()
```

### Bootstrap Script Changes
```python
# Before: No waiting for initialization
coord = Coordinator.options(...).remote()

# After: Wait for full initialization
coord_ref = Coordinator.options(...).remote()
# Wait for initialization to complete
status = ray.get(coord_ref.get_status.remote(), timeout=60.0)
```

## Compatibility

- ✅ **Ray 2.0+**: Full support for async `__init__`
- ✅ **Python 3.7+**: Async/await syntax support
- ✅ **Existing API**: No breaking changes to public methods
- ✅ **Bootstrap**: Updated to handle async initialization

## Troubleshooting

### Common Issues

1. **Initialization Timeout**
   - Check if OrganismManager initialization is taking too long
   - Verify Ray cluster resources are sufficient
   - Check logs for initialization errors

2. **Actor Creation Fails**
   - Look for initialization error logs
   - Verify OrganismManager dependencies are available
   - Check Ray cluster health

3. **Status Always "initializing"**
   - Verify `_initialized` flag is set in OrganismManager
   - Check if initialization completed successfully
   - Look for exceptions during initialization

### Debug Commands

```python
# Check Coordinator status
coord = ray.get_actor("seedcore_coordinator", namespace="your-namespace")
status = ray.get(coord.get_status.remote())
print(status)

# Test ping
ping = ray.get(coord.ping.remote())
print(ping)

# Test task handling
result = ray.get(coord.handle.remote({"type": "get_organism_status"}))
print(result)
```

## Future Improvements

1. **Health Check Endpoints**: Add `/coordinator/status` to API routers
2. **Metrics**: Track initialization time and success rates
3. **Retry Logic**: Implement retry for failed initializations
4. **Graceful Degradation**: Handle partial initialization states

## Conclusion

This fix transforms the Coordinator from a crash-prone actor into a robust, async-safe component that:

- ✅ **Never crashes** due to event loop conflicts
- ✅ **Provides clear status** information during initialization
- ✅ **Handles errors gracefully** without breaking the actor
- ✅ **Works seamlessly** with Ray's async architecture

The async `__init__` pattern is the recommended approach for Ray actors that need to perform async operations during initialization.
