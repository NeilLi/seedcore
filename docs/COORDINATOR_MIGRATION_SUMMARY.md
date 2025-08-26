# Coordinator + Dispatcher Migration Summary

## Overview

This document summarizes the complete implementation of the **Coordinator + Dispatcher** setup, removing local `OrganismManager` initialization from API entrypoints and replacing them with Coordinator proxy calls.

## ✅ Implementation Checklist

### 1) ✅ Actor Code Complete (Coordinator + Dispatcher)

**Location**: `src/seedcore/agents/queue_dispatcher.py` (moved from `organs/`)

**Coordinator Actor**:
- ✅ `@ray.remote(name="seedcore_coordinator", lifetime="detached", num_cpus=0.1, namespace=RAY_NS)`
- ✅ `async def handle(self, task: dict) -> dict` - delegates to OrganismManager
- ✅ `def ping(self) -> str` - returns `"pong"`
- ✅ Owns a **single** `OrganismManager` instance
- ✅ Initializes organism inside the actor (Ray already initialized in cluster)

**Dispatcher Actor**:
- ✅ `@ray.remote(lifetime="detached", num_cpus=0.1, namespace=RAY_NS)`
- ✅ Connects to Postgres via `asyncpg` pool
- ✅ Claims tasks via `FOR UPDATE SKIP LOCKED`
- ✅ Calls `coord = ray.get_actor("seedcore_coordinator", namespace=...)`
- ✅ Uses `res_ref = coord.handle.remote(payload)` and awaits in async contexts
- ✅ Writes result/error back and sets status to `COMPLETED` / `FAILED` / `RETRY`

### 2) ✅ Start Actors at Cluster Bootstrap

**Bootstrap Script**: `scripts/bootstrap_dispatchers.py`
- ✅ Initializes Ray connection (`ray.init(address="auto")`)
- ✅ Creates Coordinator actor if not exists
- ✅ Creates N Dispatcher actors if not exist
- ✅ Starts dispatcher run loops
- ✅ Maintains actors with health checks
- ✅ Uses correct namespace from environment variables

**Kubernetes Job**: `k8s/bootstrap-dispatchers-job.yaml`
- ✅ Runs on Ray head node (`nodeSelector: ray.io/node-type: head`)
- ✅ Uses ConfigMap for script content
- ✅ Includes health checks and resource limits
- ✅ Environment variable configuration

### 3) ✅ DB Schema: Tasks Table

**Migration**: `migrations/001_create_tasks_table.sql`
- ✅ `id UUID PRIMARY KEY`
- ✅ `status TEXT CHECK (status IN ('QUEUED','RUNNING','COMPLETED','FAILED','RETRY'))`
- ✅ `attempts INT NOT NULL DEFAULT 0`
- ✅ `locked_by TEXT NULL`
- ✅ `locked_at TIMESTAMP WITH TIME ZONE NULL`
- ✅ `run_after TIMESTAMP WITH TIME ZONE NULL`
- ✅ `type TEXT NOT NULL`
- ✅ `description TEXT NULL`
- ✅ `domain TEXT NULL`
- ✅ `drift_score DOUBLE PRECISION NOT NULL DEFAULT 0`
- ✅ `params JSONB NOT NULL DEFAULT '{}'::jsonb`
- ✅ `result JSONB NULL`
- ✅ `error TEXT NULL`
- ✅ `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- ✅ `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- ✅ Automatic `updated_at` trigger
- ✅ Performance indexes for claim queries

### 4) ✅ API: Coordinator Proxies Complete

**Files Updated**:
- ✅ `src/seedcore/telemetry/server.py`
- ✅ `src/seedcore/api/routers/tasks_router.py`
- ✅ `src/seedcore/api/routers/organism_router.py`

**Changes Made**:
- ✅ Removed local `OrganismManager` initialization
- ✅ Added Coordinator proxy functions
- ✅ Updated all organism operations to use Coordinator
- ✅ Added `/coordinator/health` endpoints
- ✅ Fixed async Ray calls to use `await` instead of `ray.get()`

**Coordinator Proxy Pattern**:
```python
async def get_coordinator_actor():
    ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
    coord = ray.get_actor("seedcore_coordinator", namespace=ray_namespace)
    return coord

async def submit_task_to_coordinator(task: dict):
    coord = await get_coordinator_actor()
    result = await coord.handle.remote(task)
    return result
```

### 5) ✅ OrganismManager Control Messages

**New Task Type Handlers**:
- ✅ `get_organism_status` - Returns organism status
- ✅ `execute_on_organ` - Executes task on specific organ
- ✅ `execute_on_random_organ` - Executes task on random organ
- ✅ `get_organism_summary` - Returns organism summary
- ✅ `initialize_organism` - Initializes organism
- ✅ `shutdown_organism` - Shuts down organism

**Implementation**:
- ✅ Added to `handle_incoming_task()` method
- ✅ Proper error handling and response formatting
- ✅ Uses existing OrganismManager methods
- ✅ Ray import available for organ handle operations

### 6) ✅ Namespace Handling Everywhere

**Consistent Namespace Usage**:
```python
ns = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
ray.get_actor("seedcore_coordinator", namespace=ns)
```

**Applied In**:
- ✅ Bootstrap script
- ✅ All API routers
- ✅ Health check endpoints
- ✅ Task worker
- ✅ Kubernetes manifests

### 7) ✅ Short-ID Support (CLI vs API)

**Short-ID Resolution**:
```python
async def _resolve_task_id(session: AsyncSession, task_id_or_prefix: str) -> uuid.UUID:
    try:
        return uuid.UUID(task_id_or_prefix)
    except ValueError:
        # Treat as prefix - find tasks that start with this prefix
        query = select(Task.id).where(Task.id.cast(String).like(f"{task_id_or_prefix}%")).limit(2)
        # ... resolution logic
```

**Updated Endpoints**:
- ✅ `GET /tasks/{task_id}` - Accepts full UUID or short prefix
- ✅ `POST /tasks/{task_id}/run` - Accepts full UUID or short prefix
- ✅ `POST /tasks/{task_id}/cancel` - Accepts full UUID or short prefix
- ✅ `GET /tasks/{task_id}/status` - Accepts full UUID or short prefix

### 8) ✅ Observability

**Health Check Endpoints**:
- ✅ `/coordinator/health` - Available on multiple routers
- ✅ Coordinator ping test
- ✅ Status reporting (healthy/degraded/unhealthy)

**Logging**:
- ✅ Bootstrap script logging
- ✅ API router logging
- ✅ Error handling and reporting

### 9) ✅ Failure & Retry Policy

**Dispatcher Retry Logic**:
- ✅ Increments `attempts` on failure
- ✅ Schedules next try with backoff: `run_after = NOW() + INTERVAL '30 seconds' * LEAST(attempts, 10)`
- ✅ Moves to `FAILED` after max attempts
- ✅ Reaper pass for stuck `RUNNING` tasks

**Error Handling**:
- ✅ Coordinator unavailable responses
- ✅ Task failure status updates
- ✅ Proper error messages in responses

### 10) ✅ Readiness and Testing

**Readiness Probe**:
- ✅ `/readyz` endpoint updated (no more local OM)
- ✅ Ray connection verification
- ✅ Coordinator health check

**Smoke Test Ready**:
- ✅ POST `/tasks` (QUEUED)
- ✅ Dispatcher claims tasks (status RUNNING)
- ✅ Task completion (COMPLETED/FAILED)
- ✅ Result shape and routing path reporting

## 🛠 Architecture Benefits

### Before (Local OrganismManager)
- ❌ API entrypoints held `OrganismManager` instances
- ❌ `OrganismManager` initialized during FastAPI startup
- ❌ API calls directly used local `OrganismManager` methods
- ❌ API in execution path, competing with detached coordinator

### After (Coordinator Proxy)
- ✅ API entrypoints are thin proxy layers
- ✅ No local `OrganismManager` instances
- ✅ All organism management via detached `seedcore_coordinator` Ray actor
- ✅ Clear separation of concerns
- ✅ Scalable architecture

## 📁 Files Created/Modified

### New Files
- `scripts/bootstrap_dispatchers.py` - Bootstrap script
- `migrations/001_create_tasks_table.sql` - Database migration
- `k8s/bootstrap-dispatchers-job.yaml` - Kubernetes Job manifest

### Modified Files
- `src/seedcore/telemetry/server.py` - Removed local OM, added Coordinator proxies
- `src/seedcore/api/routers/tasks_router.py` - Coordinator proxy, short-ID support
- `src/seedcore/api/routers/organism_router.py` - Coordinator proxy for all operations
- `src/seedcore/organs/organism_manager.py` - Added API task type handlers

### Moved Files
- `src/seedcore/organs/queue_dispatcher.py` → `src/seedcore/agents/queue_dispatcher.py`

## 🚀 Deployment Steps

### 1. Database Setup
```bash
# Apply the migration
psql -d seedcore -f migrations/001_create_tasks_table.sql
```

### 2. Start Coordinator + Dispatchers
```bash
# Option A: Run bootstrap script directly
python scripts/bootstrap_dispatchers.py

# Option B: Use Kubernetes Job
kubectl apply -f k8s/bootstrap-dispatchers-job.yaml
```

### 3. Verify Setup
```bash
# Check Coordinator health
curl http://localhost:8000/coordinator/health

# Check organism status
curl http://localhost:8000/organism/status

# Create and monitor a task
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"type": "test", "description": "Test task"}'
```

## 🔍 Testing

### Health Checks
- ✅ `/coordinator/health` - Coordinator responsiveness
- ✅ `/readyz` - Overall system readiness
- ✅ `/organism/status` - Organism status via Coordinator

### Task Processing
- ✅ Task creation and queuing
- ✅ Dispatcher claiming and processing
- ✅ Result storage and retrieval
- ✅ Error handling and retry logic

### Short-ID Support
- ✅ Full UUID resolution
- ✅ Short prefix resolution
- ✅ Ambiguous ID error handling
- ✅ CLI compatibility

## 🎯 Future Enhancements

### Load Balancing
- Multiple Coordinator instances for high availability
- Load distribution across Coordinators

### Monitoring
- Prometheus metrics for Dispatcher performance
- Ray metrics integration
- Task processing latency tracking

### Caching
- API-level caching of frequently requested organism information
- Redis-based result caching

### Circuit Breakers
- Implement circuit breakers for Coordinator failures
- Automatic fallback mechanisms

## 📚 References

- **Queue Dispatcher**: `src/seedcore/agents/queue_dispatcher.py`
- **Bootstrap Script**: `scripts/bootstrap_dispatchers.py`
- **Database Migration**: `migrations/001_create_tasks_table.sql`
- **Kubernetes Job**: `k8s/bootstrap-dispatchers-job.yaml`
- **API Documentation**: FastAPI auto-generated docs at `/docs`

## 🆘 Troubleshooting

### Common Issues

1. **Coordinator Not Found**
   - Check Ray namespace configuration
   - Verify bootstrap script ran successfully
   - Check Ray cluster connectivity

2. **Database Connection Errors**
   - Verify PostgreSQL connection string
   - Check database schema migration
   - Verify table permissions

3. **Task Processing Failures**
   - Check Coordinator health
   - Verify Dispatcher actors are running
   - Check task table schema

### Debug Commands

```bash
# Check Ray actors
ray list actors

# Check Coordinator health
curl http://localhost:8000/coordinator/health

# Check task status
curl http://localhost:8000/tasks

# Check organism status
curl http://localhost:8000/organism/status
```

---

**Migration Status**: ✅ **COMPLETE**

All checklist items have been implemented. The system is ready for production use with the new Coordinator + Dispatcher architecture.
