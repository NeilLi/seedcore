# SeedCore Service Boundaries Implementation

## Overview

This document describes the implementation of clean service boundaries between `seedcore-api` and `orchestrator` services, eliminating overlap and establishing clear ownership of concerns.

## Service Architecture

### 1. seedcore-api (FastAPI) — System of Record (SoR) for Tasks & Facts

**Owns:**
- Task & Fact schemas and all client-facing CRUD
- Database operations for tasks and facts
- API documentation and client interfaces

**Endpoints:**
- `POST /api/v1/tasks` → Create task row, return task_id
- `GET /api/v1/tasks/{id}` → Get task status/result
- `GET /api/v1/tasks` → List tasks
- `POST /api/v1/tasks/{id}/cancel` → Cancel task (optional)
- Facts/memory endpoints (Flashbulb, etc.)

**Does NOT:**
- Reach into Ray directly
- Route/execute tasks
- Handle organism control

**Readiness Gates:**
- Database availability (already in place)

**SLO:**
- API latency + DB availability

### 2. orchestrator (Ray Serve app) — Execution Gateway (internal)

**Owns:**
- Execution/control plane over Serve
- Organism management and control
- Pipeline operations
- Ray service coordination

**Endpoints:**
- `/organism/health`, `/organism/status`, `/organism/initialize`, `/organism/shutdown`
- `/pipeline/create-task` → Creates tasks via seedcore-api
- `/pipeline/anomaly-triage` → ML pipeline operations
- `/pipeline/tune/status/{job_id}` → ML tuning status

**Does NOT:**
- Write Task rows directly
- Overlap with seedcore-api task endpoints

**SLO:**
- Availability of routing & Ray backends

### 3. Dispatcher / GraphDispatcher (Ray detached actors) — Workers

**Continue to:**
- Claim tasks directly from DB
- Push results back via SQL
- Call OrganismManager (Serve) → Coordinator (actor)

### 4. OrganismManager (Serve facade) + Coordinator (actor) — Control & Execution

**Owns:**
- Organism state, routing, escalation
- On escalate → call cognitive Serve
- Organs/Agents do the actual work

### 5. cognitive, ml_service (Serve apps) — Stateless services

**Called only by:**
- Coordinator/agents

## Implementation Changes

### A) Deprecated Task Creation in Orchestrator

**Before:**
```python
@orch_app.post("/tasks")
async def create_task(self, request: TaskCreateRequest):
    # Direct task creation logic
```

**After:**
```python
@orch_app.post("/tasks")
async def create_task_deprecated(self, request: TaskCreateRequest):
    # Returns 410 Gone with redirect information
    raise HTTPException(
        status_code=410,
        detail={
            "error": "Task creation endpoint has been moved",
            "new_endpoint": "/api/v1/tasks",
            "service": "seedcore-api"
        },
        headers={
            "Location": "/api/v1/tasks",
            "X-Deprecated-Endpoint": "/tasks",
            "X-New-Service": "seedcore-api"
        }
    )
```

### B) New Task Creation via seedcore-api

**Added:**
```python
@orch_app.post("/pipeline/create-task")
async def create_task_via_api(self, request: TaskCreateRequest):
    # Calls seedcore-api to create task
    api_response = await _create_task_via_api(task_data)
    return TaskResponse(...)
```

**Helper Function:**
```python
async def _create_task_via_api(task_data: Dict[str, Any], correlation_id: str = None):
    async with httpx.AsyncClient(timeout=SEEDCORE_API_TIMEOUT) as client:
        response = await client.post(
            f"{SEEDCORE_API_URL}/api/v1/tasks",
            json=task_data,
            headers={
                "X-Service": "orchestrator",
                "X-Correlation-ID": correlation_id,
                "X-Task-ID": task_id,
                "X-Source-Service": "orchestrator",
                "X-Target-Service": "seedcore-api"
            }
        )
```

### C) Moved Ray Control Routes

**Added to Orchestrator:**
```python
@orch_app.get("/organism/health")
@orch_app.get("/organism/status")
@orch_app.post("/organism/initialize")
@orch_app.post("/organism/shutdown")
```

**Removed from seedcore-api:**
- All Ray-related routers (organism_router, tier0_router, energy_router, holon_router, dspy_router)
- Kept only: tasks_router, control_router (DB-only)

### D) Ingress Routing

**Configuration:**
```yaml
# Route API requests to seedcore-api
- path: /api/v1(/|$)(.*)
  backend:
    service:
      name: seedcore-api
      port: 8002

# Route organism control to orchestrator
- path: /organism(/|$)(.*)
  backend:
    service:
      name: orchestrator-service
      port: 8000

# Route pipeline operations to orchestrator
- path: /pipeline(/|$)(.*)
  backend:
    service:
      name: orchestrator-service
      port: 8000
```

## Observability & Correlation

### Correlation Headers

**Added to all inter-service calls:**
- `X-Correlation-ID`: Unique request identifier
- `X-Task-ID`: Task identifier (when applicable)
- `X-Source-Service`: Calling service name
- `X-Target-Service`: Target service name

### Response Correlation

**All responses include:**
```json
{
  "result": "...",
  "_correlation": {
    "correlation_id": "uuid",
    "task_id": "uuid",
    "source_service": "orchestrator",
    "target_service": "seedcore-api"
  }
}
```

### Logging

**Service identification in logs:**
- `service=seedcore-api` for API operations
- `service=orchestrator` for orchestration operations
- `owner=Coordinator` for control-plane operations

## Environment Variables

### Orchestrator Configuration

```bash
# seedcore-api integration
SEEDCORE_API_URL=http://seedcore-api:8002
SEEDCORE_API_TIMEOUT=5.0

# Ray Serve gateway
SERVE_GATEWAY=http://seedcore-svc-stable-svc:8000
ORCH_HTTP_TIMEOUT=10.0
```

### Service Discovery

```bash
# Orchestrator can reach seedcore-api via:
# - Kubernetes service: seedcore-api:8002
# - Environment variable: SEEDCORE_API_URL
```

## Migration Checklist

### ✅ Completed

- [x] Deprecated `/tasks` endpoint in orchestrator with 410 Gone
- [x] Added `/pipeline/create-task` that calls seedcore-api
- [x] Moved organism control routes to orchestrator
- [x] Added correlation headers to all inter-service calls
- [x] Created ingress routing configuration
- [x] Added proper error handling and timeouts

### 🔄 Next Steps

- [ ] Deploy orchestrator service with new endpoints
- [ ] Update client applications to use new endpoints
- [ ] Monitor for 410 Gone responses and update clients
- [ ] Add metrics for inter-service calls
- [ ] Test end-to-end task creation flow

## Testing the Implementation

### 1. Test Deprecated Endpoint

```bash
curl -X POST http://orchestrator:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"type": "test", "description": "test task"}'

# Expected: 410 Gone with redirect information
```

### 2. Test New Task Creation

```bash
curl -X POST http://orchestrator:8000/pipeline/create-task \
  -H "Content-Type: application/json" \
  -d '{"type": "test", "description": "test task"}'

# Expected: Task created via seedcore-api
```

### 3. Test Organism Control

```bash
curl http://orchestrator:8000/organism/health
curl http://orchestrator:8000/organism/status
```

### 4. Test Direct API Access

```bash
curl -X POST http://seedcore-api:8002/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{"type": "test", "description": "test task"}'

# Expected: Direct task creation
```

## Benefits

1. **Clear Ownership**: Each service has distinct responsibilities
2. **Single Source of Truth**: Tasks are only created via seedcore-api
3. **Proper Separation**: Data plane (DB/API) vs compute plane (Ray)
4. **Observability**: Full request tracing across services
5. **Scalability**: Services can be scaled independently
6. **Maintainability**: Clear boundaries make changes easier

## Rollback Plan

If issues arise:

1. **Quick Rollback**: Revert orchestrator changes, restore direct task creation
2. **Gradual Migration**: Keep both endpoints active during transition
3. **Client Updates**: Update clients to use new endpoints gradually
4. **Monitoring**: Watch for 410 Gone responses and client errors

## Future Enhancements

1. **Circuit Breaker**: Add circuit breaker pattern for seedcore-api calls
2. **Retry Logic**: Implement exponential backoff for failed calls
3. **Caching**: Cache organism status to reduce Ray calls
4. **Metrics**: Add Prometheus metrics for inter-service calls
5. **Health Checks**: Add dependency health checks (orchestrator → seedcore-api)
