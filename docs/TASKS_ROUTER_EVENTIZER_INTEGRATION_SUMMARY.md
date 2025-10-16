# Tasks Router Eventizer Integration Summary

## Overview
This document summarizes the integration of the EventizerServiceClient into the tasks_router.py to enable proper communication with the remote EventizerService deployed under the unified `/ops` application.

## Problem Statement
The tasks_router.py was directly instantiating and using the EventizerService locally, but since it runs on an independent pod (via main.py), it should communicate with the remote EventizerService deployed under the `/ops` application using HTTP calls.

## Changes Made

### 1. `/Users/ningli/project/seedcore/src/seedcore/api/routers/tasks_router.py`

#### **Import Changes:**
```python
# Before
from ...services.eventizer_service import EventizerService
from ...services.eventizer.schemas.eventizer_models import EventizerRequest, EventizerConfig

# After
from ...serve.eventizer_client import EventizerServiceClient
```

#### **Service Instantiation Changes:**
```python
# Before
_eventizer_service: EventizerService | None = None

async def get_eventizer_service() -> EventizerService:
    global _eventizer_service
    if _eventizer_service is None:
        config = EventizerConfig()
        _eventizer_service = EventizerService(config)
        await _eventizer_service.initialize()
        logger.info("Eventizer service initialized")
    return _eventizer_service

# After
_eventizer_client: EventizerServiceClient | None = None

async def get_eventizer_client() -> EventizerServiceClient:
    global _eventizer_client
    if _eventizer_client is None:
        _eventizer_client = EventizerServiceClient()
        logger.info("Eventizer service client initialized")
    return _eventizer_client
```

#### **Processing Logic Changes:**
```python
# Before
eventizer_service = await get_eventizer_service()
eventizer_request = EventizerRequest(
    text=task_description,
    task_type=task_type,
    domain=domain,
    preserve_pii=False,
    include_metadata=True
)
eventizer_response = await eventizer_service.process_text(eventizer_request)

# After
eventizer_client = await get_eventizer_client()
eventizer_payload = {
    "text": task_description,
    "task_type": task_type,
    "domain": domain,
    "preserve_pii": False,
    "include_metadata": True
}
eventizer_response_data = await eventizer_client.process_eventizer_request(eventizer_payload)
```

#### **Response Handling Changes:**
```python
# Before (using EventizerResponse object)
enriched_params.update({
    "event_tags": eventizer_response.event_tags.model_dump(),
    "attributes": eventizer_response.attributes.model_dump(),
    "confidence": eventizer_response.confidence.model_dump(),
    "needs_ml_fallback": eventizer_response.confidence.needs_ml_fallback,
    # ...
})

# After (using dictionary response)
enriched_params.update({
    "event_tags": eventizer_response_data.get("event_tags", {}),
    "attributes": eventizer_response_data.get("attributes", {}),
    "confidence": eventizer_response_data.get("confidence", {}),
    "needs_ml_fallback": eventizer_response_data.get("confidence", {}).get("needs_ml_fallback", True),
    # ...
})
```

## Architecture Changes

### Before (Direct Service Usage)
```
tasks_router.py (Independent Pod)
    ↓ (Direct instantiation)
EventizerService (Local)
    ↓ (Local processing)
Response Object
```

### After (HTTP Client Usage)
```
tasks_router.py (Independent Pod)
    ↓ (HTTP client)
EventizerServiceClient
    ↓ (HTTP calls)
/ops/eventizer/process (Ray Serve)
    ↓ (Remote processing)
EventizerService (Ops Pod)
    ↓ (JSON response)
Dictionary Response
```

## Integration Points

### 1. **Service Discovery**
- **Uses**: `SERVE_GATEWAY` from `seedcore.utils.ray_utils`
- **Fallback**: `http://127.0.0.1:8000/ops`
- **Endpoint**: `/ops/eventizer/process`

### 2. **RayService Configuration**
- **Application**: `ops` (unified application)
- **Route Prefix**: `/ops`
- **Service**: `EventizerService` deployment
- **Replicas**: 1 (0.4 CPUs, 1GB memory)

### 3. **Main Application**
- **Independent Pod**: tasks_router runs via `main.py`
- **Port**: 8002 (separate from Ray Serve on 8000)
- **Communication**: HTTP calls to Ray Serve application

## Benefits

### 1. **Proper Service Architecture**
- ✅ **Separation of concerns**: tasks_router focuses on task management
- ✅ **Service isolation**: EventizerService runs in dedicated Ray Serve deployment
- ✅ **Scalability**: Independent scaling of task processing and eventizer services

### 2. **Consistency**
- ✅ **Unified client pattern**: Uses same EventizerServiceClient as other services
- ✅ **HTTP-based communication**: Consistent with other inter-service calls
- ✅ **Service discovery**: Uses centralized gateway discovery mechanism

### 3. **Reliability**
- ✅ **Circuit breaker**: Built-in failure handling and recovery
- ✅ **Retry logic**: Automatic retry on transient failures
- ✅ **Error handling**: Graceful fallback when eventizer is unavailable

### 4. **Operational Benefits**
- ✅ **Monitoring**: Can monitor HTTP calls and response times
- ✅ **Debugging**: Clear separation between task processing and eventizer logic
- ✅ **Deployment**: Independent deployment of task and eventizer services

## Testing

### Test Files Created
1. **`examples/test_tasks_router_eventizer_integration.py`**
   - Tests EventizerServiceClient integration
   - Simulates exact tasks_router flow
   - Validates response structure and error handling

### Test Coverage
- ✅ Client initialization and service discovery
- ✅ Health check functionality
- ✅ Basic text processing
- ✅ Response structure validation
- ✅ Error handling
- ✅ Tasks router simulation

## Usage Example

### Task Creation with Eventizer Processing
```python
# In tasks_router.py
async def create_task(payload: Dict[str, Any]) -> TaskRead:
    # Extract task information
    task_description = payload.get("description", "")
    task_type = payload.get("type", "")
    domain = payload.get("domain")
    
    # Process through eventizer if description provided
    if task_description.strip():
        try:
            eventizer_client = await get_eventizer_client()
            
            eventizer_payload = {
                "text": task_description,
                "task_type": task_type,
                "domain": domain,
                "preserve_pii": False,
                "include_metadata": True
            }
            
            # HTTP call to remote eventizer service
            eventizer_response_data = await eventizer_client.process_eventizer_request(eventizer_payload)
            
            # Enrich task params with eventizer results
            enriched_params.update({
                "event_tags": eventizer_response_data.get("event_tags", {}),
                "attributes": eventizer_response_data.get("attributes", {}),
                "confidence": eventizer_response_data.get("confidence", {}),
                "needs_ml_fallback": eventizer_response_data.get("confidence", {}).get("needs_ml_fallback", True),
                # ... additional metadata
            })
            
        except Exception as e:
            logger.error("Eventizer processing failed: %s", e)
            enriched_params["eventizer_error"] = str(e)
            enriched_params["needs_ml_fallback"] = True
    
    # Create task with enriched parameters
    # ...
```

## Related Files

- **Tasks Router**: `src/seedcore/api/routers/tasks_router.py`
- **Main Application**: `src/seedcore/main.py`
- **Eventizer Client**: `src/seedcore/serve/eventizer_client.py`
- **Ray Utils**: `src/seedcore/utils/ray_utils.py`
- **Ops Entrypoint**: `entrypoints/ops_entrypoint.py`
- **RayService Config**: `deploy/rayservice.yaml`
- **Test Script**: `examples/test_tasks_router_eventizer_integration.py`

## Next Steps

1. **Deploy and test** the updated tasks_router in the actual environment
2. **Monitor performance** and HTTP call latency
3. **Verify error handling** works correctly in production
4. **Consider caching** for frequently processed text patterns if needed
