# Architecture Migration Summary: State and Energy Services + Database Schema Evolution

## Overview

This document summarizes the implementation of **Option C** from the architectural recommendation: creating two standalone Ray Serve applications for state aggregation and energy calculations, decoupling them from the organism subsystem. Additionally, it documents the comprehensive database schema evolution including task management, HGNN (Heterogeneous Graph Neural Network) architecture, facts management, and runtime registry systems. The document also covers the **dual-dispatcher architecture** that separates graph-related tasks from general task processing, providing specialized handling and optimization for different workload types.

## 🎯 Implementation Summary

### ✅ Completed Tasks

1. **Created Standalone State Service** (`/src/seedcore/services/state_service.py`)
   - Extracted `StateAggregator` functionality into a dedicated Ray Serve application
   - Provides centralized state collection from distributed Ray actors and memory managers
   - Implements Paper §3.1 requirements for light aggregators
   - RESTful API with endpoints for unified state queries

2. **Created Standalone Energy Service** (`/src/seedcore/services/energy_service.py`)
   - Pure computational service that consumes `UnifiedState` data
   - Provides energy calculations, gradients, and agent optimization
   - No state collection responsibilities - purely computational
   - RESTful API with endpoints for energy computation and optimization

3. **Updated Ray Service Deployment** (`/deploy/rayservice.yaml`)
   - Added two new services: `state` and `energy`
   - Configured appropriate resource allocation for each service
   - Maintained existing organism service configuration

4. **Updated OrganismManager** (`/src/seedcore/organs/organism_manager.py`)
   - Removed local `StateAggregator` dependency
   - Updated to use state service via Ray actor communication
   - Maintains backward compatibility for existing `get_unified_state()` method

5. **Updated Telemetry Endpoints** (`/src/seedcore/telemetry/routers/energy.py`)
   - Modified to use both state and energy services
   - Added new endpoints for energy computation and agent optimization
   - Maintains existing API compatibility

6. **Created Service Entrypoints**
   - `entrypoints/state_entrypoint.py` - State service deployment
   - `entrypoints/energy_entrypoint.py` - Energy service deployment

7. **Database Schema Evolution** (13 migrations)
   - **Task Management System**: Complete coordinator-dispatcher task queue with lease management
   - **Task Dispatcher Architecture**: Dual-dispatcher system (QueueDispatcher + GraphDispatcher) with specialized task routing
   - **Task Schema Enhancements**: JSONB conversion, check constraints, and optimized indexing
   - **HGNN Architecture**: Two-layer heterogeneous graph with task and agent/organ layers
   - **Graph Embeddings**: Vector-based graph embeddings with ANN indexing
   - **Facts Management**: Text-based fact storage with full-text search capabilities
   - **Runtime Registry**: Instance management and cluster coordination system

## 🏗️ Architecture Changes

### Before (Monolithic)
```
OrganismManager
├── StateAggregator (local)
│   ├── AgentStateAggregator
│   ├── MemoryManagerAggregator
│   └── SystemStateAggregator
└── Energy Module (imported)
    ├── Energy Calculator
    ├── Energy Ledger
    └── Energy Optimizer
```

### After (Microservices)
```
State Service (Ray Serve)
├── StateAggregator
│   ├── AgentStateAggregator
│   ├── MemoryManagerAggregator
│   └── SystemStateAggregator
└── REST API

Energy Service (Ray Serve)
├── Energy Calculator
├── Energy Ledger
├── Energy Optimizer
└── REST API

OrganismManager
├── State Service Client
└── Energy Service Client (via telemetry)
```

## 🗄️ Database Schema Evolution

### Migration Overview

The database schema has evolved through 13 comprehensive migrations, establishing a robust foundation for distributed task management, graph-based AI, and runtime coordination:

| Migration | Purpose | Key Components |
|-----------|---------|----------------|
| 001-006 | **Task Management** | Task queue, status tracking, lease management |
| 007 | **Task Schema Enhancements** | JSONB conversion, check constraints, optimized indexing |
| 008-009 | **HGNN Architecture** | Two-layer graph schema, node mapping, edge relationships |
| 010-011 | **Facts System** | Text-based fact storage, task-fact integration |
| 012-013 | **Runtime Registry** | Instance management, cluster coordination |

### 1. Task Management System (Migrations 001-006)

#### Core Task Schema
```sql
-- Tasks table with comprehensive status tracking and enhanced schema
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status taskstatus NOT NULL DEFAULT 'created',
    attempts INTEGER NOT NULL DEFAULT 0,
    locked_by TEXT NULL,
    locked_at TIMESTAMP WITH TIME ZONE NULL,
    run_after TIMESTAMP WITH TIME ZONE NULL,
    type TEXT NOT NULL,
    description TEXT NULL,
    domain TEXT NULL,
    drift_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB NULL,
    error TEXT NULL,
    owner_id TEXT NULL,
    lease_expires_at TIMESTAMP WITH TIME ZONE NULL,
    last_heartbeat TIMESTAMP WITH TIME ZONE NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- Enhanced constraints and indexes
    CONSTRAINT ck_tasks_attempts_nonneg CHECK (attempts >= 0)
);

-- Enhanced indexing strategy for optimal performance
CREATE INDEX ix_tasks_status_runafter ON tasks (status, run_after);
CREATE INDEX ix_tasks_created_at_desc ON tasks (created_at);
CREATE INDEX ix_tasks_type ON tasks (type);
CREATE INDEX ix_tasks_domain ON tasks (domain);
CREATE INDEX ix_tasks_params_gin ON tasks USING gin (params);
```

#### Task Status Enum
```sql
CREATE TYPE taskstatus AS ENUM (
    'created', 'queued', 'running', 'completed', 
    'failed', 'cancelled', 'retry'
);
```

#### Key Features
- **Lease Management**: Prevents task conflicts with `owner_id`, `lease_expires_at`, `last_heartbeat`
- **Retry Logic**: Automatic requeuing with exponential backoff
- **Drift Scoring**: OCPS valve decision making (0.0 = fast path, ≥0.5 = escalation)
- **Enhanced Schema**: JSONB conversion, check constraints, and optimized indexing
- **Performance Indexes**: 
  - `ix_tasks_status_runafter`: Composite index for task claiming queries
  - `ix_tasks_created_at_desc`: Optimized for chronological ordering
  - `ix_tasks_type`: Fast task type filtering
  - `ix_tasks_domain`: Domain-based task routing
  - `ix_tasks_params_gin`: GIN index for JSONB parameter queries
- **Data Integrity**: Check constraint ensures `attempts >= 0`
- **JSONB Support**: Native JSONB for `params` and `result` with efficient querying

### 2. Task Dispatcher Architecture

The system implements a **dual-dispatcher architecture** that separates graph-related tasks from general task processing, enabling specialized handling and optimization for different workload types.

#### Dispatcher Types

**1. QueueDispatcher** (`queue_dispatcher.py`)
- Handles all **non-graph tasks** (excludes graph-specific task types)
- Uses async PostgreSQL connection pooling with `asyncpg`
- Implements concurrent task processing with bounded concurrency
- Routes tasks through a configurable router system (default: `coordinator_http`)
- Provides automatic lease renewal for long-running tasks
- Implements watchdog for stuck task recovery

**2. GraphDispatcher** (`graph_dispatcher.py`)
- Handles **graph-specific tasks** exclusively
- Manages graph embedding operations (SAGE/Neo4j integration)
- Manages NIM retrieval embedding operations (PostgreSQL integration)
- Uses synchronous SQLAlchemy for database operations
- Supports HGNN-aware node resolution across multiple entity types
- Implements chunked embedding processing for large batches

#### Task Type Classification

**Graph Task Types** (handled by GraphDispatcher):
```python
GRAPH_TASK_TYPES = (
    "graph_embed",           # Legacy: numeric node IDs
    "graph_rag_query",       # Legacy: numeric node IDs
    "graph_embed_v2",        # HGNN-aware: UUID/text IDs
    "graph_rag_query_v2",    # HGNN-aware: UUID/text IDs
    "graph_fact_embed",      # Facts system embeddings
    "graph_fact_query",      # Facts system queries
    "nim_task_embed",        # NIM retrieval embeddings
    "graph_sync_nodes",      # Maintenance: sync graph_node_map
)
```

**General Task Types** (handled by QueueDispatcher):
- All other task types not in `GRAPH_TASK_TYPES`
- Routed through coordinator service for execution
- Examples: `cognitive_task`, `agent_task`, `organ_task`, etc.

#### Task Structure & Fields

**TaskPayload Model** (for inter-service communication):
```python
class TaskPayload(BaseModel):
    type: str                          # Task type identifier
    params: Dict[str, Any] = {}       # Task parameters (JSONB)
    description: str = ""              # Human-readable description
    domain: Optional[str] = None      # Logical domain/namespace
    drift_score: float = 0.0          # OCPS drift score (0.0 = fast path)
    task_id: str                      # Task UUID as string
```

**Task Database Schema** (PostgreSQL):
- **Identifiers**: `id` (UUID), `owner_id` (TEXT), `locked_by` (TEXT)
- **Classification**: `type` (TEXT), `domain` (TEXT), `description` (TEXT)
- **Inputs/Outputs**: `params` (JSONB), `result` (JSONB), `error` (TEXT)
- **State Management**: 
  - `status` (taskstatus enum)
  - `attempts` (INTEGER, non-negative)
  - `drift_score` (DOUBLE PRECISION)
- **Scheduling**: 
  - `run_after` (TIMESTAMPTZ) - delayed execution
  - `lease_expires_at` (TIMESTAMPTZ) - lease expiration
  - `last_heartbeat` (TIMESTAMPTZ) - worker liveness
  - `locked_at` (TIMESTAMPTZ) - lock acquisition time
- **Timestamps**: `created_at`, `updated_at` (TIMESTAMPTZ)

#### Task Status Lifecycle

```
created → queued → running → completed
                        ↓
                    failed/retry
                        ↓
                    (retry → queued → running ...)
```

**Status Definitions**:
- `created`: Initial state after task creation
- `queued`: Ready for processing, waiting for dispatcher claim
- `running`: Currently being processed by a dispatcher
- `completed`: Successfully finished with result stored
- `failed`: Permanently failed (after max attempts)
- `cancelled`: Intentionally cancelled (e.g., duplicate detection)
- `retry`: Scheduled for retry after failure

#### QueueDispatcher Features

**1. Concurrent Processing**
- Bounded concurrency via semaphore (`MAX_CONCURRENCY`, default: 16)
- Fire-and-forget task processing (tasks don't block each other)
- Independent connection acquisition per task worker

**2. Batch Claiming**
- Claims multiple tasks per iteration (`CLAIM_BATCH_SIZE`, default: 8)
- In-batch duplicate detection and cancellation
- Uses `FOR UPDATE SKIP LOCKED` for safe concurrent claiming

**3. Lease Management**
- Automatic lease extension for running tasks (default: 600 seconds)
- Periodic lease renewal every 30 seconds during task execution
- Graceful lease expiration handling via watchdog

**4. Retry Logic**
- Exponential backoff: `min(10 * (2 ** attempts), 300)` seconds
- Maximum retry attempts configurable via `MAX_TASK_ATTEMPTS` (default: 3)
- Jitter added to prevent retry storms

**5. Watchdog System**
- Periodic stale task detection (default: every 30 seconds)
- Requeues tasks with expired leases or dead owners
- Marks tasks as failed after maximum attempts exceeded
- Uses grace period (90 seconds) for heartbeat staleness

**6. Router-Based Execution**
- Abstract router interface for task routing
- Default router: `coordinator_http` (HTTP-based coordinator)
- Router handles task-to-organ mapping and execution
- Timeout protection (default: 120 seconds) for router calls

**7. Memory Management**
- Periodic garbage collection (every `FORCE_GC_EVERY_N` tasks, default: 2000)
- Soft memory limit enforcement (`DISPATCHER_MEMORY_SOFT_LIMIT_MB`)
- Result size truncation if configured (`RESULT_MAX_BYTES`)
- Process recycling after task count threshold (`RECYCLE_AFTER_TASKS`)

#### GraphDispatcher Features

**1. HGNN-Aware Node Resolution**
Supports multiple entity types with automatic node mapping:
- **Core Entities**: `start_task_ids`, `start_agent_ids`, `start_organ_ids`
- **Facts System**: `start_fact_ids` (Migration 009)
- **Resources**: `start_artifact_ids`, `start_capability_ids`, `start_memory_cell_ids` (Migration 007)
- **Agent Layer**: `start_model_ids`, `start_policy_ids`, `start_service_ids`, `start_skill_ids` (Migration 008)
- **Legacy Support**: `start_node_ids`, `start_ids` (numeric node IDs)

**2. Dual Embedding System**
- **GraphEmbedder**: SAGE-based graph embeddings from Neo4j
- **NimRetrievalEmbedder**: NIM-based retrieval embeddings from PostgreSQL
- Automatic actor lifecycle management (detached, namespaced)

**3. Chunked Processing**
- Configurable chunk size via `GRAPH_EMBED_BATCH_CHUNK`
- Automatic chunking for large node batches
- Prevents timeout on large embedding operations

**4. Heartbeat Threading**
- Background heartbeat thread extends lease during long operations
- Configurable heartbeat interval (`GRAPH_HEARTBEAT_PING_S`, default: 5s)
- Automatic cleanup on task completion/failure

**5. Task Processing Flow**

**Graph Embed Operations** (`graph_embed`, `graph_embed_v2`):
1. Resolve start node IDs (from UUIDs/text IDs to numeric node_ids)
2. Compute embeddings via GraphEmbedder (with optional chunking)
3. Upsert embeddings to `graph_embeddings` table
4. Return embedding statistics and node metadata

**Graph RAG Query Operations** (`graph_rag_query`, `graph_rag_query_v2`):
1. Resolve start node IDs
2. Compute seed embeddings
3. Compute centroid from seed embeddings
4. Vector similarity search in `graph_embeddings` table
5. Return top-k neighbors with scores

**NIM Task Embed Operations** (`nim_task_embed`):
1. Fetch task text content from PostgreSQL
2. Resolve task UUIDs to node_ids via `graph_node_map`
3. Embed text content via NimRetrievalEmbedder
4. Upsert embeddings with content hash and model metadata
5. Return embedding statistics

**Fact Operations** (`graph_fact_embed`, `graph_fact_query`):
- Similar to graph embed/query but specifically for facts
- Uses fact-specific node resolution
- Supports fact-based similarity search

#### Task Routing Architecture

**Router Factory Pattern**:
- Configurable router type via `DISPATCHER_ROUTER_TYPE` (default: `coordinator_http`)
- Abstract router interface enables pluggable routing strategies
- Supports HTTP-based, direct actor, or future routing implementations

**Coordinator HTTP Router**:
- Routes tasks to coordinator service via HTTP
- Handles task-to-organ mapping
- Returns unified result envelope with metadata
- Implements timeout and error handling

**Result Schema**:
Tasks receive unified result envelopes from router:
```python
{
    "kind": "task_result",
    "payload": {...},              # Actual result data
    "success": bool,
    "version": str,
    "metadata": {...},
    "created_at": timestamp
}
```

#### Environment Configuration

**QueueDispatcher Configuration**:
```bash
DISPATCHER_COUNT=2                    # Number of dispatcher instances
CLAIM_BATCH_SIZE=8                    # Tasks claimed per iteration
DISPATCHER_CONCURRENCY=16             # Max concurrent tasks per dispatcher
EMPTY_SLEEP_SECONDS=0.05              # Sleep when no tasks available
LEASE_SECONDS=90                      # Base lease duration
TASK_LEASE_S=600                      # Running task lease duration
USE_LISTEN_NOTIFY=0                   # Enable PostgreSQL LISTEN/NOTIFY
WATCHDOG_INTERVAL=30                  # Watchdog check interval (seconds)
DISPATCHER_MEMORY_SOFT_LIMIT_MB=0     # Soft memory limit (0 = disabled)
DISPATCHER_FORCE_GC_EVERY_N=2000      # GC every N tasks
DISPATCHER_RECYCLE_AFTER_TASKS=0      # Recycle after N tasks (0 = disabled)
DISPATCHER_RESULT_MAX_BYTES=0         # Max result size (0 = disabled)
SERVE_CALL_TIMEOUT_S=120              # Router call timeout
MAX_TASK_ATTEMPTS=3                   # Maximum retry attempts
```

**GraphDispatcher Configuration**:
```bash
GRAPH_EMBED_TIMEOUT_S=600             # Embedding operation timeout
GRAPH_UPSERT_TIMEOUT_S=600            # Upsert operation timeout
GRAPH_HEARTBEAT_PING_S=5              # Heartbeat interval (seconds)
GRAPH_LEASE_EXTENSION_S=600           # Lease extension per heartbeat
GRAPH_DB_POOL_SIZE=5                  # SQLAlchemy connection pool size
GRAPH_DB_MAX_OVERFLOW=5               # Connection pool overflow limit
GRAPH_DB_POOL_RECYCLE_S=600           # Connection pool recycle interval
GRAPH_TASK_POLL_INTERVAL_S=1.0        # Task polling interval
GRAPH_EMBED_BATCH_CHUNK=0             # Chunk size (0 = disabled)
GRAPH_STRICT_JSON_RESULT=true         # Enforce JSON-serializable results
NIM_RETRIEVAL_MODEL=nvidia/nv-embedqa-e5-v5  # NIM model identifier
```

#### Performance Optimizations

**1. Database Indexing**
- Composite index on `(status, run_after)` for efficient task claiming
- Index on `created_at` for chronological ordering
- Indexes on `type` and `domain` for filtering
- GIN index on `params` JSONB for parameter queries

**2. Connection Pooling**
- QueueDispatcher: AsyncPG pool with bounded size and idle lifetime
- GraphDispatcher: SQLAlchemy pool with recycling and pre-ping
- Automatic pool health monitoring and recreation on failure

**3. Concurrent Execution**
- QueueDispatcher: Semaphore-based bounded concurrency
- Independent task workers with separate database connections
- Non-blocking task processing prevents cascade failures

**4. Batch Operations**
- Batch task claiming reduces database round-trips
- Chunked embedding processing prevents timeouts
- Bulk upsert operations for graph embeddings

**5. Memory Management**
- Periodic garbage collection prevents memory leaks
- Result size limiting prevents excessive memory usage
- Process recycling for long-running dispatchers

#### Monitoring & Observability

**Prometheus Metrics** (QueueDispatcher):
- `seedcore_tasks_claimed_total`: Counter for claimed tasks
- `seedcore_tasks_completed_total`: Counter for completed tasks
- `seedcore_tasks_failed_total`: Counter for failed tasks
- `seedcore_tasks_retried_total`: Counter for retried tasks
- `seedcore_dispatcher_inflight`: Gauge for current inflight tasks
- `seedcore_dispatcher_process_rss_bytes`: Gauge for memory usage

**Health Checks**:
- `ping()`: Simple responsiveness check
- `heartbeat()`: Detailed health status with component checks
- `status()`: Comprehensive status with pool information
- `get_metrics()`: Task processing statistics (GraphDispatcher)

**Logging**:
- Structured logging with task IDs for traceability
- Debug logging for task processing details
- Warning logs for stuck tasks and lease expiration
- Error logs with full exception tracebacks

### 3. Task Schema Enhancements (Migration 007)

#### JSONB Conversion
```sql
-- Convert JSON to JSONB for better performance and querying
ALTER TABLE tasks
  ALTER COLUMN params TYPE JSONB USING params::jsonb,
  ALTER COLUMN result TYPE JSONB USING result::jsonb;
```

#### Enhanced Indexing Strategy
```sql
-- New index naming convention for consistency
CREATE INDEX ix_tasks_status_runafter ON tasks (status, run_after);
CREATE INDEX ix_tasks_created_at_desc ON tasks (created_at);
CREATE INDEX ix_tasks_type ON tasks (type);
CREATE INDEX ix_tasks_domain ON tasks (domain);

-- GIN index for efficient JSONB parameter queries
CREATE INDEX ix_tasks_params_gin ON tasks USING gin (params);
```

#### Data Integrity Constraints
```sql
-- Ensure attempts is always non-negative
ALTER TABLE tasks
ADD CONSTRAINT ck_tasks_attempts_nonneg CHECK (attempts >= 0);
```

#### Key Benefits
- **Performance**: JSONB provides better query performance than JSON
- **Querying**: GIN indexes enable efficient parameter filtering
- **Consistency**: Standardized index naming convention
- **Integrity**: Check constraints prevent invalid data
- **Maintainability**: Clear schema structure for future enhancements

### 4. HGNN Architecture (Migrations 008-009)

#### Two-Layer Graph Structure

**Layer 1: Task Layer**
- Tasks, Artifacts, Capabilities, Memory Cells
- Task dependencies, resource usage, memory operations

**Layer 2: Agent/Organ Layer**  
- Agents, Organs, Models, Policies, Services, Skills
- Agent-organ relationships, collaboration patterns, capability bindings

#### Node Mapping System
```sql
-- Canonical node-id mapping for DGL integration
CREATE TABLE graph_node_map (
    node_id BIGSERIAL PRIMARY KEY,
    node_type TEXT NOT NULL,        -- 'task', 'agent', 'organ', etc.
    ext_table TEXT NOT NULL,        -- Source table name
    ext_uuid UUID NULL,             -- For UUID-based rows
    ext_text_id TEXT NULL,          -- For TEXT-based IDs
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### Edge Relationships
- **Task Layer**: `task__depends_on__task`, `task__produces__artifact`, `task__uses__capability`
- **Cross-Layer**: `task__executed_by__organ`, `task__owned_by__agent`
- **Agent Layer**: `agent__member_of__organ`, `agent__collab__agent`, `organ__provides__skill`

#### Graph Embeddings
```sql
-- Vector embeddings with ANN indexing
CREATE TABLE graph_embeddings (
    node_id BIGINT PRIMARY KEY,
    label TEXT NULL,
    props JSONB NULL,
    emb VECTOR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ANN index for similarity search
CREATE INDEX idx_graph_embeddings_emb ON graph_embeddings
USING ivfflat (emb vector_l2_ops) WITH (lists = 100);
```

### 5. Facts Management System (Migrations 010-011)

#### Facts Schema
```sql
CREATE TABLE facts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    text TEXT NOT NULL,
    tags TEXT[] DEFAULT '{}',
    meta_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
```

#### Key Features
- **Full-Text Search**: GIN indexes for efficient text search
- **Tag-Based Categorization**: Array-based tagging system
- **Metadata Support**: JSONB for flexible fact properties
- **Task Integration**: `task__reads__fact`, `task__produces__fact` relationships

### 6. Runtime Registry System (Migrations 012-013)

#### Instance Management
```sql
CREATE TABLE registry_instance (
    instance_id UUID PRIMARY KEY,
    logical_id TEXT NOT NULL,           -- 'cognitive_organ_1'
    cluster_epoch UUID NOT NULL,
    status InstanceStatus NOT NULL DEFAULT 'starting',
    actor_name TEXT,                    -- For named actors
    serve_route TEXT,                   -- For Serve/HTTP routes
    node_id TEXT,
    ip_address INET,
    pid INT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stopped_at TIMESTAMPTZ,
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### Cluster Coordination
```sql
CREATE TABLE cluster_metadata (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    current_epoch UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### Key Features
- **Epoch-Based Coordination**: Prevents split-brain scenarios
- **Heartbeat Monitoring**: Automatic stale instance detection
- **Status Tracking**: `starting`, `alive`, `draining`, `dead`
- **Advisory Locks**: Safe epoch rotation with `pg_try_advisory_lock()`

### 7. Unified Graph View

The `hgnn_edges` view provides a flattened representation of all graph relationships for DGL export:

```sql
CREATE VIEW hgnn_edges AS
    -- Task layer edges
    SELECT ensure_task_node(d.src_task_id) AS src_node_id,
           ensure_task_node(d.dst_task_id) AS dst_node_id,
           'task__depends_on__task'::TEXT AS edge_type
    FROM task_depends_on_task d
    UNION ALL
    -- Cross-layer edges
    SELECT ensure_task_node(e.task_id),
           ensure_organ_node(e.organ_id),
           'task__executed_by__organ'
    FROM task_executed_by_organ e
    UNION ALL
    -- Agent layer edges
    SELECT ensure_agent_node(a.agent_id),
           ensure_organ_node(a.organ_id),
           'agent__member_of__organ'
    FROM agent_member_of_organ a
    -- ... (additional unions for all edge types)
;
```

## 🔄 Service Interactions

### Data Flow
1. **State Collection**: State Service collects data from Ray actors and memory managers
2. **State Query**: OrganismManager and telemetry endpoints query state service
3. **Energy Calculation**: Energy Service consumes state data for computations
4. **Energy Query**: Telemetry endpoints query energy service for metrics

### API Endpoints

#### State Service (`/state`)
- `GET /health` - Health check
- `GET /status` - Service status
- `POST /unified-state` - Get unified state (with options)
- `GET /unified-state` - Simplified unified state query

#### Energy Service (`/energy`)
- `GET /health` - Health check
- `GET /status` - Service status
- `POST /compute-energy` - Compute energy metrics
- `POST /optimize-agents` - Optimize agent selection
- `GET /energy-from-state` - Get energy from current state

#### Telemetry Integration
- `GET /ops/state/unified_state` - Delegates to state service (migrated to /ops)
- `POST /ops/energy/compute-energy` - Delegates to energy service (migrated to /ops)
- `POST /ops/energy/optimize-agents` - Delegates to energy service (migrated to /ops)

## 🚀 Benefits Achieved

### 1. **Separation of Concerns**
- **State Service**: Pure data collection and aggregation
- **Energy Service**: Pure computational service
- **OrganismManager**: Focuses on organism lifecycle management
- **Database Schema**: Clear separation between task management, graph operations, and runtime coordination

### 2. **Independent Scaling**
- State collection can scale independently from energy calculations
- Each service can be scaled based on its specific workload
- Resource allocation optimized per service type
- Database operations optimized with targeted indexes and views

### 3. **Reusability**
- State service can be used by other subsystems (monitoring, debugging, visualization)
- Energy service can be used anywhere `UnifiedState` data is available
- Services are not locked into organism-specific concerns
- Graph schema supports multiple AI/ML workloads beyond organism management

### 4. **Maintainability**
- Clear boundaries between services
- Easier to test and debug individual components
- Simpler to add new features to specific services
- Database schema evolution through controlled migrations

### 5. **Fault Tolerance**
- Service failures are isolated
- Graceful degradation when services are unavailable
- Independent health monitoring
- Database-level lease management prevents task conflicts

### 6. **Advanced Capabilities**
- **Graph-Based AI**: HGNN architecture supports complex relationship modeling
- **Vector Search**: Efficient similarity search with ANN indexing
- **Facts Management**: Full-text search and semantic fact storage
- **Runtime Coordination**: Epoch-based cluster management prevents split-brain scenarios
- **Task Orchestration**: Sophisticated task queue with retry logic and drift scoring

## 📊 Resource Allocation

| Service | CPU | Memory | Replicas | Purpose |
|---------|-----|--------|----------|---------|
| State Service | 0.5 | 1GB | 1 | Data collection |
| Energy Service | 1.0 | 1GB | 1 | Energy calculations |
| Organism Manager | 0.5 | 2GB | 1 | Organism lifecycle |

## 🗄️ Database Performance & Monitoring

### Index Strategy
- **Task Queries**: 
  - `ix_tasks_status_runafter`: Composite index for efficient task claiming
  - `ix_tasks_created_at_desc`: Optimized chronological ordering
  - `ix_tasks_type`: Fast task type filtering
  - `ix_tasks_domain`: Domain-based task routing
  - `ix_tasks_params_gin`: GIN index for JSONB parameter queries
- **Graph Operations**: GIN indexes on JSONB fields and array columns for fast lookups
- **Vector Search**: IVFFlat indexes on embeddings for sub-linear similarity search
- **Full-Text Search**: GIN indexes on text vectors for semantic fact retrieval

### Query Optimization
- **Unified Views**: `hgnn_edges` and `task_embeddings` provide optimized data access patterns
- **Helper Functions**: `ensure_*_node()` functions provide idempotent node creation
- **Batch Operations**: Bulk insert/update patterns for graph construction

### Monitoring Capabilities
- **Task Health**: `cleanup_stale_running_tasks()` for automatic recovery
- **Instance Health**: `active_instances` and `active_instance` views for runtime monitoring
- **Graph Analytics**: Edge counting and relationship analysis through unified views

## 🔧 Configuration

### Environment Variables
- `STATE_MAX_ONGOING_REQUESTS=32` - State service concurrency
- `STATE_NUM_CPUS=0.5` - State service CPU allocation
- `STATE_MEMORY=1073741824` - State service memory (1GB)
- `ENERGY_MAX_ONGOING_REQUESTS=16` - Energy service concurrency
- `ENERGY_NUM_CPUS=1.0` - Energy service CPU allocation
- `ENERGY_MEMORY=1073741824` - Energy service memory (1GB)

### Ray Namespace
All services use the `seedcore-dev` namespace for actor communication.

## 🧪 Testing

### Service Health Checks
- Each service provides `/health` and `/status` endpoints
- Health checks verify service connectivity and initialization
- Graceful error handling for service unavailability

### Backward Compatibility
- Existing `OrganismManager.get_unified_state()` method maintained
- Telemetry endpoints maintain existing API contracts
- Gradual migration path for existing consumers

## 🔮 Future Enhancements

### 1. **Service Discovery**
- Implement service registry for dynamic service discovery
- Health monitoring and automatic failover
- Integration with runtime registry system

### 2. **Caching Layer**
- Add Redis or similar caching for frequently accessed state data
- Reduce load on state service for repeated queries
- Graph embedding caching for similarity search

### 3. **Load Balancing**
- Implement load balancing for multiple service replicas
- Auto-scaling based on service metrics
- Database connection pooling optimization

### 4. **Monitoring Integration**
- Add Prometheus metrics for service monitoring
- Distributed tracing for request flow analysis
- Database performance monitoring and alerting

### 5. **Graph Analytics**
- Real-time graph analytics and visualization
- Graph-based recommendation systems
- Advanced graph algorithms (PageRank, community detection)

### 6. **AI/ML Integration**
- Automated graph embedding updates
- Graph neural network training pipelines
- Fact-based knowledge graph completion

### 7. **Database Optimization**
- Partitioning for large-scale task tables
- Read replicas for analytics workloads
- Automated index optimization based on query patterns

## 📝 Migration Notes

### Breaking Changes
- None - all existing APIs maintained

### Dependencies
- State service depends on organism manager for Ray actor access
- Energy service depends on state service for data
- Telemetry endpoints depend on both services

### Deployment Order
1. Deploy state service first
2. Deploy energy service second
3. Deploy organism manager (updated)
4. Deploy telemetry (updated)

## ✅ Validation

The implementation successfully achieves the recommended architecture:

### Service Architecture
- ✅ **State aggregation decoupled** from organism subsystem
- ✅ **Energy calculations decoupled** from state collection
- ✅ **Independent Ray Serve applications** for each service
- ✅ **Clear service boundaries** and responsibilities
- ✅ **Backward compatibility** maintained
- ✅ **Scalability** enabled through independent services
- ✅ **Reusability** of services across subsystems

### Database Schema
- ✅ **Task Management**: Complete coordinator-dispatcher system with lease management
- ✅ **Task Schema Enhancements**: JSONB conversion, check constraints, and optimized indexing
- ✅ **HGNN Architecture**: Two-layer graph schema with cross-layer relationships
- ✅ **Graph Embeddings**: Vector-based similarity search with ANN indexing
- ✅ **Facts System**: Full-text search and semantic fact storage
- ✅ **Runtime Registry**: Epoch-based cluster coordination and instance management
- ✅ **Performance Optimization**: Comprehensive indexing strategy for all query patterns
- ✅ **Data Integrity**: Foreign key constraints, check constraints, and referential integrity maintained

### Integration Points
- ✅ **Graph-Task Integration**: Seamless task-to-graph node mapping
- ✅ **Facts-Task Integration**: Task-fact relationships for knowledge management
- ✅ **Runtime-Task Integration**: Instance-aware task execution tracking
- ✅ **Vector Search Integration**: Graph embeddings accessible through unified views

This architecture provides a solid foundation for future enhancements while maintaining system stability and performance. The database schema evolution enables advanced AI/ML capabilities while preserving the core service architecture benefits.



