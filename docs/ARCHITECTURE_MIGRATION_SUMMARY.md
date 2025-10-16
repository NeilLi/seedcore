# Architecture Migration Summary: State and Energy Services + Database Schema Evolution

## Overview

This document summarizes the implementation of **Option C** from the architectural recommendation: creating two standalone Ray Serve applications for state aggregation and energy calculations, decoupling them from the organism subsystem. Additionally, it documents the comprehensive database schema evolution including task management, HGNN (Heterogeneous Graph Neural Network) architecture, facts management, and runtime registry systems.

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

7. **Database Schema Evolution** (12 migrations)
   - **Task Management System**: Complete coordinator-dispatcher task queue with lease management
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

The database schema has evolved through 12 comprehensive migrations, establishing a robust foundation for distributed task management, graph-based AI, and runtime coordination:

| Migration | Purpose | Key Components |
|-----------|---------|----------------|
| 001-006 | **Task Management** | Task queue, status tracking, lease management |
| 007-008 | **HGNN Architecture** | Two-layer graph schema, node mapping, edge relationships |
| 009-010 | **Facts System** | Text-based fact storage, task-fact integration |
| 011-012 | **Runtime Registry** | Instance management, cluster coordination |

### 1. Task Management System (Migrations 001-006)

#### Core Task Schema
```sql
-- Tasks table with comprehensive status tracking
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
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
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
- **Performance Indexes**: Optimized for coordinator-dispatcher queries

### 2. HGNN Architecture (Migrations 007-008)

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

### 3. Facts Management System (Migrations 009-010)

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

### 4. Runtime Registry System (Migrations 011-012)

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

### 5. Unified Graph View

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
- **Task Queries**: Composite indexes on `(status, run_after, created_at)` for efficient task claiming
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
- ✅ **HGNN Architecture**: Two-layer graph schema with cross-layer relationships
- ✅ **Graph Embeddings**: Vector-based similarity search with ANN indexing
- ✅ **Facts System**: Full-text search and semantic fact storage
- ✅ **Runtime Registry**: Epoch-based cluster coordination and instance management
- ✅ **Performance Optimization**: Comprehensive indexing strategy for all query patterns
- ✅ **Data Integrity**: Foreign key constraints and referential integrity maintained

### Integration Points
- ✅ **Graph-Task Integration**: Seamless task-to-graph node mapping
- ✅ **Facts-Task Integration**: Task-fact relationships for knowledge management
- ✅ **Runtime-Task Integration**: Instance-aware task execution tracking
- ✅ **Vector Search Integration**: Graph embeddings accessible through unified views

This architecture provides a solid foundation for future enhancements while maintaining system stability and performance. The database schema evolution enables advanced AI/ML capabilities while preserving the core service architecture benefits.



