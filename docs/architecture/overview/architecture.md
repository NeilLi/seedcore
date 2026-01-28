# Serve ↔ Actor Architecture Overview

This document provides a comprehensive overview of the SeedCore system architecture, specifically focusing on the mapping between Ray Serve applications and Ray Actors, and how they work together to form a distributed, intelligent organism.

## Table of Contents

- [System Overview](#system-overview)
- [Architecture Diagrams](#architecture-diagrams)
- [Runtime Registry and Actor Lifecycle](#runtime-registry-and-actor-lifecycle)
- [Serve Applications (Logical Apps)](#serve-applications-logical-apps)
- [Serve Deployments → Ray Actors](#serve-deployments--ray-actors)
- [Control Plane Actors](#control-plane-actors)
- [System Relationships](#system-relationships)
- [Task Workflow Across Actors](#task-workflow-across-actors)
- [Task Taxonomy and Routing](#task-taxonomy-and-routing)
- [Task Dispatcher Architecture](#task-dispatcher-architecture)
- [TaskPayload v2.5+ Architecture](#taskpayload-v25-architecture)
- [HGNN Graph and GraphDispatcher](#hgnn-graph-and-graphdispatcher)
- [Graph Embeddings Pipeline](#graph-embeddings-pipeline)
- [Facts, Resources, and Agent Layer Integration](#facts-resources-and-agent-layer-integration)
- [PKG Policy Governance System](#pkg-policy-governance-system)
- [Unified Cortex Memory](#unified-cortex-memory)
- [Task Outbox Hardening](#task-outbox-hardening)
- [Task Router Telemetry](#task-router-telemetry)
- [State and Energy Services](#state-and-energy-services)
- [Memory Architecture](#memory-architecture)
- [RayAgent Lifecycle Management](#rayagent-lifecycle-management)
- [Performance and Energy Tracking](#performance-and-energy-tracking-enhanced-with-sharedcacheshard)
- [Resiliency: Drift Detection and Circuit Breakers](#resiliency-drift-detection-and-circuit-breakers)
- [Data Layer and Migrations](#data-layer-and-migrations)
- [Health Indicators](#health-indicators)
- [Scaling and Distribution](#scaling-and-distribution)
- [Monitoring and Observability](#monitoring-and-observability-enhanced-with-sharedcacheshard)
- [Verification Workflow](#verification-workflow)

## System Overview

SeedCore implements a distributed, intelligent organism architecture using Ray Serve for service orchestration and Ray Actors for distributed computation. The system is designed to be scalable, fault-tolerant, and capable of handling complex cognitive workloads.

The architecture follows a **microservices pattern** where each logical service is deployed as a Ray Serve application, which in turn spawns one or more Ray Actors to handle the actual computation and state management.

For a comprehensive overview of recent architectural changes and migrations, see the [Architecture Migration Summary](../architecture_migration_summary.md).


## Runtime Registry and Actor Lifecycle

SeedCore implements a robust **epoch-based runtime registry** system that provides comprehensive actor lifecycle management, cluster coordination, and fault tolerance. This system ensures reliable actor discovery, health monitoring, and graceful handling of cluster changes.

### Epoch-Based Cluster Management

The runtime registry uses **cluster epochs** (UUIDs) to track cluster state changes and prevent split-brain scenarios:

#### Cluster Metadata
- **Single-row cluster metadata** with advisory-locked epoch updates
- **Advisory locking** prevents concurrent epoch changes during cluster rotation
- **Automatic epoch creation** for new clusters or missing metadata

#### Epoch Rotation Process
1. **Advisory Lock Acquisition**: System acquires exclusive lock (key=42) for epoch updates
2. **Epoch Update**: Updates `cluster_metadata.current_epoch` with new UUID
3. **Instance Registration**: New instances register with current epoch
4. **Stale Cleanup**: Old epoch instances are marked as dead during rotation

### Instance Registry Schema

The `registry_instance` table tracks all active Ray actors and Serve deployments:

```sql
CREATE TABLE registry_instance (
  instance_id    UUID PRIMARY KEY,           -- Unique actor instance identifier
  logical_id     TEXT NOT NULL,              -- Logical service name (e.g., 'cognitive_organ_1')
  cluster_epoch  UUID NOT NULL,              -- Current cluster epoch
  status         InstanceStatus NOT NULL,    -- starting|alive|draining|dead
  actor_name     TEXT,                       -- Ray actor name for named actors
  serve_route    TEXT,                       -- Serve deployment route
  node_id        TEXT,                       -- Ray node identifier
  ip_address     INET,                       -- Instance IP address
  pid            INT,                        -- Process ID
  started_at     TIMESTAMPTZ NOT NULL,       -- Registration timestamp
  stopped_at     TIMESTAMPTZ,                -- Termination timestamp
  last_heartbeat TIMESTAMPTZ NOT NULL        -- Last heartbeat timestamp
);
```

### Actor Lifecycle Management

#### 1. Instance Registration (`Organ.start()`)

When an Organ actor starts:

```python
async def start(self) -> Dict[str, Any]:
    # Generate unique instance ID
    self.instance_id = uuid.uuid4().hex
    
    # Register in 'starting' status
    await repo.register_instance(
        instance_id=self.instance_id,
        logical_id=self.organ_id,
        cluster_epoch=await repo.get_current_cluster_epoch(),
        actor_name=self.organ_id,
        serve_route=self.serve_route,
        node_id=os.getenv("RAY_NODE_ID"),
        ip_address=socket.gethostbyname(socket.gethostname()),
        pid=os.getpid(),
    )
    
    # Mark alive after readiness checks
    await repo.set_instance_status(self.instance_id, "alive")
    
    # Start heartbeat loop
    self._hb_task = asyncio.create_task(self._heartbeat_loop())
```

#### 2. Heartbeat Management

**Jittered Heartbeats with Bounded Backoff**:

```python
async def _heartbeat_loop(self):
    backoff = 0.5  # Initial backoff
    while not self._closing.is_set():
        try:
            await repo.beat(self.instance_id)
            backoff = 0.5  # Reset on success
        except Exception as e:
            # Bounded exponential backoff on failures
            backoff = min(backoff * 2, HB_BACKOFF_MAX)
            await asyncio.sleep(backoff)
        
        # Jittered sleep: HB_BASE + random(0, HB_JITTER)
        await asyncio.wait_for(
            self._closing.wait(), 
            timeout=HB_BASE + random.random() * HB_JITTER
        )
```

**Configuration**:
- `RUNTIME_HB_BASE_S=3.0`: Base heartbeat interval
- `RUNTIME_HB_JITTER_S=2.0`: Random jitter range
- `RUNTIME_HB_BACKOFF_S=10.0`: Maximum backoff on failures

#### 3. Graceful Shutdown (`Organ.close()`)

```python
async def close(self) -> Dict[str, Any]:
    self._closing.set()  # Signal shutdown
    
    # Cancel heartbeat task
    if self._hb_task:
        self._hb_task.cancel()
        await self._hb_task
    
    # Mark as dead in registry
    await repo.set_instance_status(self.instance_id, "dead")
    
    return {"status": "dead", "instance_id": self.instance_id}
```

### Runtime Registry Views

#### Active Instances Monitoring
```sql
-- All alive instances in current epoch with recent heartbeats
CREATE VIEW active_instances AS
SELECT ri.*
FROM registry_instance ri
JOIN cluster_metadata cm ON ri.cluster_epoch = cm.current_epoch
WHERE ri.status = 'alive'
  AND ri.last_heartbeat > (now() - INTERVAL '15 seconds');
```

#### Best Instance Selection
```sql
-- One best instance per logical_id (for named actors)
CREATE VIEW active_instance AS
SELECT DISTINCT ON (ri.logical_id)
  ri.*
FROM registry_instance ri
JOIN cluster_metadata cm ON ri.cluster_epoch = cm.current_epoch
WHERE ri.status = 'alive'
  AND ri.last_heartbeat > (now() - INTERVAL '15 seconds')
ORDER BY ri.logical_id, ri.last_heartbeat DESC;
```

### Stale Instance Cleanup

**Automatic Expiration**:
```sql
-- Mark stale instances as dead
CREATE FUNCTION expire_stale_instances(timeout_seconds INT DEFAULT 15)
RETURNS INT AS $$
  UPDATE registry_instance
  SET status = 'dead', stopped_at = COALESCE(stopped_at, now())
  WHERE status = 'alive' 
    AND last_heartbeat < (now() - INTERVAL '1 second' * timeout_seconds);
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RETURN cnt;
$$;
```

### Database Integration

The runtime registry integrates with the existing database schema through:

#### Migration Sequence
1. **Migration 011**: Creates `cluster_metadata` and `registry_instance` tables
2. **Migration 012**: Implements registry functions and views
3. **Database Initialization**: `init_full_db.sh` applies all migrations

#### Repository Pattern
- **`AgentGraphRepository`**: Async repository with connection pooling
- **Lazy Initialization**: Connection pools created on first use
- **Error Handling**: Comprehensive error handling with detailed logging
- **Transaction Safety**: All operations wrapped in proper transactions

### Fault Tolerance Features

#### 1. Split-Brain Prevention
- **Advisory locking** prevents concurrent epoch changes
- **Epoch-based registration** ensures instances only see current cluster state
- **Stale cleanup** removes instances from previous epochs

#### 2. Network Partition Handling
- **Bounded backoff** prevents thundering herd on network issues
- **Jittered heartbeats** reduce synchronization effects
- **Graceful degradation** with circuit breaker patterns

#### 3. Process Lifecycle Management
- **SIGTERM handling** for graceful shutdown
- **Process ID tracking** for debugging and monitoring
- **Node ID correlation** for Ray cluster topology awareness

### Monitoring and Observability

#### Health Indicators
- **Instance Status**: `starting` → `alive` → `draining` → `dead`
- **Heartbeat Frequency**: Configurable with jitter and backoff
- **Stale Detection**: 15-second timeout for heartbeat expiration
- **Epoch Tracking**: Cluster-wide epoch consistency monitoring

#### Metrics Collection
- **Instance Counts**: Per-logical-id and per-status counts
- **Heartbeat Latency**: Database write performance monitoring
- **Epoch Rotation**: Cluster change frequency and timing
- **Stale Cleanup**: Dead instance detection and cleanup rates

## Serve Applications (Logical Apps)

From `serve status`, the system runs 6 main applications:

| Application | Purpose | Status | Replicas |
|-------------|---------|---------|----------|
| **ml_service** | ML inference and model serving | Running | 1 |
| **cognitive** | Reasoning, planning, and cognitive tasks | Running | 2 |
| **coordinator** | Global coordination, routing, and escalation | Running | 1 |
| **state** | Centralized state aggregation and memory management | Running | 1 |
| **energy** | Energy tracking and performance metrics | Running | 1 |
| **organism** | Local organ management and task execution | Running | 1 |

Each application represents a logical service namespace that can contain multiple deployments and replicas. The **cognitive** service runs with 2 replicas for distributed reasoning capabilities, while the **coordinator** handles global task routing and escalation decisions.

## Serve Deployments → Ray Actors

Every deployment spawns one or more **`ServeReplica` actors**, plus global actors for control and proxying:

### 1. ML Service → MLService

- **ServeDeployment**: `MLService`
- **Actor**: `ServeReplica:ml_service:MLService`
- **Replicas**: `1 RUNNING`
- **Ray Actor ID**: Actor 2
- **Purpose**: Dedicated ML inference service for model serving

### 2. Cognitive → CognitiveService (Planner-Only)

- **ServeDeployment**: `CognitiveService`
- **Actors**: `ServeReplica:cognitive:CognitiveService`
- **Replicas**: `2 RUNNING`
- **Ray Actor IDs**: Actor 1 and Actor 4
- **Purpose**: Pure planner that generates abstract task steps with `{"task": {...}}` format
- **Key Features**:
  - **No routing decisions**: Enforced by guardrails against organ_id/instance_id
  - **Normalized domains**: Standard taxonomy ("graph", "facts", "management", "utility")
  - **Planning API**: Wraps steps into solution_steps with rich metadata
  - **Meta data**: escalate_hint, sufficiency, confidence, planner_timings_ms
  - **Cache optimization**: 10-minute TTL for sufficiency-bearing results
- **Distribution**: Replicas are distributed across different Ray nodes for redundancy

### 3. Coordinator → Coordinator (Governor)

- **ServeDeployment**: `Coordinator`
- **Replicas**: `1 RUNNING`
- **Ray Actor ID**: Actor 5
- **Purpose**: Global coordination, routing orchestration, OCPS valve, and bulk resolution
- **Key Features**:
  - **Route resolution**: Fast-path via Organism with TTL cache + single-flight
  - **Bulk resolution**: HGNN plans resolved in single call to Organism
  - **Plan validation**: Accepts abstract steps, auto-stamps step_id
  - **Meta data ingestion**: Feeds Cognitive hints into predicate signals
  - **Static fallback**: Resilient fallback when Organism unavailable
- **Route Prefix**: `/pipeline`

### 4. State → StateService

- **ServeDeployment**: `StateService`
- **Replicas**: `1 RUNNING`
- **Ray Actor ID**: Actor 9
- **Purpose**: Centralized state aggregation and memory management
- **Memory**: 1GB allocated for state collection and caching

### 5. Energy → EnergyService

- **ServeDeployment**: `EnergyService`
- **Replicas**: `1 RUNNING`
- **Ray Actor ID**: Actor 10
- **Purpose**: Energy tracking and performance metrics collection
- **Memory**: 1GB allocated for energy state management

### 6. Organism → OrganismManager (Dispatcher)

- **ServeDeployment**: `OrganismManager`
- **Replicas**: `1 RUNNING`
- **Ray Actor ID**: Actor 8
- **Purpose**: Dispatcher that owns routing directory and resolves abstract steps to specific organs
- **Key Features**:
  - **Routing Directory**: Migrated from Coordinator, integrated with runtime registry
  - **Bulk Resolve API**: `/resolve-route` and `/resolve-routes` endpoints
  - **Rule Management**: CRUD operations for routing rules with cache refresh
  - **Epoch Awareness**: Invalidates cache on cluster epoch rotation
  - **Active Instance Validation**: Queries runtime registry with health checks
- **Memory**: 2GB allocated for organism state management
- **Route Prefix**: `/organism`

## Control Plane Actors

Besides service replicas, Serve maintains several control plane actors:

| Actor | Purpose | Status |
|-------|---------|---------|
| **ServeController (Actor 3)** | Central brain of Serve, manages deployments and replicas | Running |
| **ProxyActors (Actor 6 & 7)** | Handle HTTP/GRPC ingress, route to correct deployment | Running |
| **StatusActor (Actor 0)** | Ray Dashboard integration, tracks job/actor status | Running |

## System Relationships

### 1. Serve → Actors Mapping

- Each Serve deployment represents **one logical service**
- It owns **N `ServeReplica` actors** (workers), distributed across Ray nodes
- Scale is reflected in `replica_states.RUNNING`
- Replicas can be scaled independently based on workload requirements

### 2. Actors → Nodes Distribution

- Replicas are distributed between nodes for fault tolerance
- Example: CognitiveService has 2 replicas on different nodes:
  - Actor 1 on node `f7d...`
  - Actor 4 on node `34d...`
- This provides redundancy and parallelism

### 3. Core Service Interactions

#### Runtime Registry Integration
- **All Ray actors** register with the runtime registry on startup
- **Epoch-based coordination** ensures cluster consistency
- **Heartbeat monitoring** provides real-time health status
- **Graceful shutdown** ensures clean actor termination

#### Three-Tier Routing Architecture

**Cognitive Service (Planner-Only)**:
- **CognitiveService** (Actors 1 & 4) generates abstract task steps with `{"task": {...}}` format
- **No routing decisions**: Enforced by guardrails against organ_id/instance_id
- **Planning API**: Wraps steps into solution_steps with rich metadata
- **Meta data**: Provides escalate_hint, sufficiency, confidence, planner_timings_ms

**Coordinator Service (Governor)**:
- **Coordinator** (Actor 5) orchestrates routing decisions and system coordination
- **Fast Path**: Resolves single routes via Organism with TTL cache + single-flight
- **HGNN Path**: Bulk resolves all plan steps in one call to Organism
- **Plan validation**: Accepts abstract steps, auto-stamps step_id
- **Meta data ingestion**: Feeds Cognitive hints into predicate signals

**Organism Manager (Dispatcher)**:
- **OrganismManager** (Actor 8) owns routing directory and resolves abstract steps to organs
- **Bulk Resolve API**: `/resolve-route` and `/resolve-routes` endpoints
- **Runtime registry integration**: Queries active instances with health validation
- **Epoch awareness**: Invalidates cache on cluster epoch rotation

#### Service Flow Patterns

**Fast Path Flow**:
- Task → Coordinator → OCPS Valve → Organism (resolve route) → Organ (execute)

**Escalation Path Flow**:
- Task → Coordinator → OCPS Valve → Cognitive (plan) → Coordinator (bulk resolve) → Organism (execute)

#### MLService Integration
- Independent ML-focused endpoint
- Can be called by Coordinator for anomaly detection and ML inference
- Supports various ML model types and inference patterns

#### StateService Integration
- Centralized state aggregation from distributed Ray actors
- Collects agent snapshots, organ states, and system metrics
- Provides unified state view for monitoring and decision making

#### EnergyService Integration
- Tracks performance metrics and energy consumption
- Monitors capability scores and memory utilization
- Provides energy state information for system optimization

## Task Workflow Across Actors

The SeedCore system implements a sophisticated task workflow that moves through multiple layers of Ray actors and supporting systems. This section describes how tasks flow from arrival to completion.

### 1. Task Arrival and Routing

**Source**: Tasks originate from multiple sources:
- **Queue Dispatcher** - Primary task coordinator and batch processing
- **External APIs** - Direct task submission via HTTP/GRPC
- **Coordinator Service** - Global task routing and escalation
- **OrganismManager** - Local organ management and execution

**Runtime Registry Integration**: Before task processing:
- **Actor Discovery**: Query `active_instances` view for available organs
- **Health Validation**: Verify target actors have recent heartbeats
- **Epoch Consistency**: Ensure all actors are in current cluster epoch
- **Load Balancing**: Select best available instance per logical_id

**Routing Decision**: Coordinator determines task routing based on:
- OCPS valve drift detection (fast-path vs escalation)
- Task type and complexity
- Current system load and escalation capacity
- Available organs and agent capabilities (from runtime registry)
- Actor health status and heartbeat freshness

### 2. Agent Selection and Memory Management

**Tier0MemoryManager** (utility instance, not a Ray actor) facilitates agent selection:
- Maintains registry of all RayAgent handles across organs
- Implements `get_agent()` for single agent selection
- Implements `execute_task_on_best_of()` for optimal agent routing
- Tracks agent capabilities and current workload

**Organ Supervision**: Each Organ actor supervises its RayAgent workers:
- Creates and manages agent instances (`*_agent_0`, `*_agent_1`, etc.)
- Monitors agent health and performance
- Handles agent lifecycle management

### 3. Task Execution in RayAgent

When `RayAgent.execute_task(task_data)` is called:

#### Logging and Dispatch
- Logs "🤖 Agent X executing task" for traceability
- Determines task type (general_query, simulation, collaborative, high-stakes, etc.)
- Routes to appropriate handler based on task classification

#### Task Handling
- **general_query** → `_handle_general_query` (time/date/system/math/status)
- **simulation** → `_simulate_task_execution` with specialized logic
- **collaborative** → `execute_collaborative_task` with Mw → Mlt escalation
- **high-stakes** → `execute_high_stakes_task` with Flashbulb memory logging

#### Memory Integration
- **AgentPrivateMemory (Ma)**: Maintains 128-D embedding vector for agent state
- **Working Memory (Mw)**: Fast, volatile cache for recent information
- **Long-Term Memory (Mlt)**: Durable store for persistent knowledge
- **Flashbulb Memory (Mfb)**: Rare, high-salience event storage

**Memory Flow**:
1. Query Mw first for cached results
2. On cache miss, escalate to Mlt for persistent data
3. Cache successful results back to Mw
4. For high-salience events, log to Mfb

#### Cognitive Core Integration
When enabled, agents can call into cognitive_core for:
- Failure reasoning and analysis
- Task planning and decomposition
- Decision making and optimization
- Memory synthesis and knowledge integration
- Capability assessment and learning

### 4. Performance and Energy Update

After task completion, the system updates multiple metrics:

#### Capability Tracking
- Updates capability score `c` using EWMA (Exponentially Weighted Moving Average)
- Tracks success/failure rates and quality scores
- Maintains task history for learning and optimization

#### Memory Utilization
- Updates memory utility `mem_util` based on cache hit rates
- Tracks memory efficiency and access patterns
- Optimizes memory allocation across tiers

#### Energy State Management
- Updates `energy_state` with expected contribution and entropy
- Tracks computational cost and resource consumption
- Maintains energy balance across the system

#### Private Memory Update
- Updates agent's private memory vector `h` (128-D embedding)
- Incorporates new knowledge and experience
- Maintains agent state representation

### 5. Heartbeat and Telemetry

**Heartbeat Generation**: `get_heartbeat()` bundles comprehensive telemetry:
- State embedding and current capabilities
- Performance metrics and success rates
- Memory metrics and utilization
- Lifecycle state and health status
- Energy state and resource consumption

**Telemetry Loop**: `start_heartbeat_loop()` periodically emits:
- Real-time system state for monitoring
- Performance data for optimization
- Health status for fault detection
- Metrics for system analysis

### 6. Archival and Lifecycle Management

**Idle/Termination Handling**:
- `_export_tier0_summary` stores agent state in Mlt
- Evicts agent from Mw working memory
- Optionally logs incidents to Mfb for future reference
- Sets lifecycle state to "Archived"

**Memory Cleanup**:
- Preserves important state in long-term storage
- Cleans up volatile working memory
- Maintains system efficiency and resource utilization

### High-Level Workflow Summary

```
Task Arrival (Queue Dispatcher)
     ↓
Coordinator Service (Governor)
├─ Runtime Registry Query (active_instances)
├─ Health Validation (heartbeat freshness)
├─ OCPS Valve Check (fast-path vs escalation)
│
├─ Fast Path: Organism Resolution → Direct Execution
│   ├─ Route Resolution: Organism (resolve-route) + TTL Cache
│   ├─ Static Fallback: If Organism unavailable
│   └─ Organ (container) → Tier0MemoryManager → RayAgent
│       ├─ Runtime Registry: Register instance
│       ├─ Heartbeat Loop: Jittered + backoff
│       └─ Graceful Shutdown: Mark dead on close
│
└─ Escalation Path: Cognitive Planning → Bulk Resolution → Execution
   ├─ Cognitive Service (Planner-Only)
   │   ├─ Generate abstract plan: {"task": {...}} format
   │   ├─ Meta data: escalate_hint, sufficiency, confidence
   │   └─ Planning API: solution_steps with timings
   │
   ├─ Coordinator (Bulk Resolution)
   │   ├─ Plan validation: abstract steps only
   │   ├─ Bulk resolve: Organism (resolve-routes) + TTL Cache
   │   ├─ Stamp organ_id: Into each plan step
   │   └─ Static fallback: Per-step if resolution fails
   │
   └─ Organism Manager (Dispatcher)
       └─ Organ (container) → Tier0MemoryManager → RayAgent
           ├─ Runtime Registry: Instance lifecycle
           ├─ Execute task
           │    ├─ Memory lookup: Mw → Mlt → Mfb
           │    ├─ Cognitive reasoning (optional)
           │    └─ Produce result
           │
           ├─ Update performance + energy metrics
           ├─ Emit heartbeat (via runtime registry)
           └─ Possibly archive/log to Mlt & Mfb
```

### Key Architectural Points

- **Cognitive Service** = Pure planner, generates abstract task steps, no routing decisions
- **Coordinator Service** = Governor, OCPS valve, routing orchestration, bulk resolution
- **Organism Manager** = Dispatcher, owns routing directory, resolves abstract steps to organs
- **Tier0MemoryManager** = Registry/selector utility, not a Ray actor
- **Organ** = Wrapper container, creates and supervises RayAgents
- **RayAgent** = Real worker, stateful, owns private memory, cognitive access, telemetry
- **Memory Layers**:
  - **Mw** = Fast, volatile working memory
  - **Mlt** = Durable long-term store
  - **Mfb** = Rare, high-salience flashbulb events

### Routing Architecture Benefits

- **Clean Separation**: Planner, Governor, and Dispatcher have distinct responsibilities
- **Bulk Efficiency**: Single bulk resolve call instead of N individual route lookups
- **Resilient Fallbacks**: Multiple layers of fallback ensure system availability
- **Cache Optimization**: TTL cache with single-flight prevents thundering herd
- **Epoch Awareness**: Cache invalidation on cluster changes maintains consistency

## Recent Architecture Refactors

### Refactor 1: Routing Directory Migration (Commit d31699ee)

**Migration**: `RoutingDirectory` moved from `Coordinator` → `OrganismManager`

**Key Changes**:
- **Runtime Registry Integration**: Routing now queries active instances with health validation
- **Bulk Resolve API**: Added `/resolve-route` and `/resolve-routes` endpoints
- **Rule Management**: CRUD operations for routing rules with cache refresh
- **Epoch Awareness**: Cache invalidation on cluster epoch rotation
- **Coordinator TTL Cache**: 3-second TTL with jitter, single-flight, epoch-aware

**Benefits**:
- **Centralized Routing**: All routing decisions owned by Organism Manager
- **Performance**: Bulk resolve reduces N network calls → 1 per HGNN plan
- **Resilience**: Coordinator-side cache with static fallback ensures availability

### Refactor 2: Cognitive Planner-Only Architecture (Commit 9920006a)

**Cognitive Service Changes**:
- **Handler Format**: All handlers return `{"task": {...}, "confidence_score": ...}` format
- **No Routing Awareness**: Guardrails prevent organ_id/instance_id in outputs
- **Domain Normalization**: Standard taxonomy ("graph", "facts", "management", "utility")
- **Planning API**: Wraps single/multi steps into solution_steps with rich metadata
- **Cache Optimization**: 10-minute TTL for sufficiency-bearing results

**Coordinator Service Changes**:
- **Plan Validation**: Accepts abstract steps with only `{"task": {...}}` format
- **Route Resolution**: Fast-path and HGNN both resolve via Organism
- **Bulk Resolution**: Single call to Organism for all plan steps
- **Meta Data Ingestion**: Feeds Cognitive hints into predicate signals
- **Static Fallback**: Resilient fallback when Organism unavailable

**Architecture Impact**:
- **Clean Separation**: Cognitive (planner), Coordinator (governor), Organism (dispatcher)
- **Bulk Efficiency**: 1 bulk resolve call instead of N individual lookups
- **Resilient Design**: Multiple fallback layers ensure system availability
- **Performance**: TTL cache with single-flight prevents thundering herd

## Architecture Diagrams

The SeedCore architecture is visualized through several key diagrams that illustrate different aspects of the system:

### System Architecture Overview

![Architecture Overview](../architecture_overview.png)

The architecture overview diagram shows the complete Ray cluster structure, including:
- **Serve Applications**: ml_service, cognitive, coordinator, state, energy, organism
- **Ray Actors**: All actor instances and their relationships
- **Control Plane**: ServeController, ProxyActors, StatusActor
- **Memory Architecture**: L0/L1/L2 cache hierarchy and memory tiers

### PKG Core Architecture

![PKG Core Architecture](../architecture_pkg_core.png)

The PKG core architecture diagram illustrates:
- **Policy Snapshots**: Versioned policy management
- **Rule Evaluation**: Policy rule processing and emissions
- **Canary Deployments**: Gradual rollout mechanisms
- **Validation System**: Policy testing and promotion workflows

### Architecture Workflow

![Architecture Workflow](../architecture_workflow.png)

The workflow diagram shows end-to-end task processing:
- **Task Arrival**: Queue dispatcher and task claiming
- **Routing Flow**: Fast-path vs escalation decision making
- **Execution Path**: Organ selection and agent execution
- **Memory Integration**: Multi-tier memory access patterns

### Text-Based Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              Ray Cluster                                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐            │
│  │   Serve Proxy   │    │   Serve Proxy   │    │ ServeController │            │
│  │   (Actor 6)     │    │   (Actor 7)     │    │   (Actor 3)     │            │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘            │
│           │                       │                       │                    │
│           └───────────────────────┼───────────────────────┘                    │
│                                   │                                            │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                        Serve Applications                               │   │
│  │                                                                         │   │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ │   │
│  │  │ml_service│ │cognitive│ │coordinator│ │  state  │ │ energy  │ │organism │ │   │
│  │  │         │ │         │ │         │ │         │ │         │ │         │ │   │
│  │  │MLService│ │Cognitive│ │Coordinator│ │StateSvc │ │EnergySvc│ │OrganismMgr│ │   │
│  │  │(Actor 2)│ │(Actor 1,4)│ │(Actor 5)│ │(Actor 9)│ │(Actor 10)│ │(Actor 8)│ │   │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                          Ray Actors                                     │   │
│  │                                                                         │   │
│  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐     │   │
│  │  │A 0  │ │A 1  │ │A 2  │ │A 3  │ │A 4  │ │A 5  │ │A 6  │ │A 7  │     │   │
│  │  │Status│ │Cogn │ │ML   │ │Ctrl │ │Cogn │ │Coord│ │Proxy│ │Proxy│     │   │
│  │  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘     │   │
│  │                                                                         │   │
│  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐                                     │   │
│  │  │A 8  │ │A 9  │ │A 10 │ │A 11 │                                     │   │
│  │  │Org  │ │State│ │Energy│ │Tier0│                                     │   │
│  │  │Mgr  │ │Svc  │ │Svc  │ │Mem  │                                     │   │
│  │  └─────┘ └─────┘ └─────┘ └─────┘                                     │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                    Memory Architecture (Enhanced)                      │   │
│  │                                                                         │   │
│  │  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐              │   │
│  │  │   L0    │    │   L1    │    │   L2    │    │   Mw    │              │   │
│  │  │Organ-Local│   │Node Cache│   │SharedCache│   │ Working │              │   │
│  │  │  Cache  │    │         │    │  Shard  │    │ Memory  │              │   │
│  │  │(Per-Agent)│   │(Per-Node)│   │(Cluster)│    │(Volatile)│              │   │
│  │  └─────────┘    └─────────┘    └─────────┘    └─────────┘              │   │
│  │       │              │              │              │                   │   │
│  │       └──────────────┼──────────────┼──────────────┘                   │   │
│  │                      │              │                                  │   │
│  │  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐              │   │
│  │  │   Mlt   │    │   Mfb   │    │   Ma    │    │MwManager│              │   │
│  │  │Long-Term│    │Flashbulb│    │Private  │    │(Enhanced)│              │   │
│  │  │ Memory  │    │ Memory  │    │ Memory  │    │         │              │   │
│  │  │(Persistent)│ │(Rare)  │    │(128-D)  │    │• CAS Ops│              │   │
│  │  └─────────┘    └─────────┘    └─────────┘    │• Compress│              │   │
│  │                                                │• Telemetry│              │   │
│  │                                                └─────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Task Dispatcher Architecture

SeedCore implements a **dual-dispatcher architecture** that separates graph-related tasks from general task processing, enabling specialized handling and optimization for different workload types.

### Dispatcher Types

**1. QueueDispatcher** (`queue_dispatcher.py`):
- Handles all **non-graph tasks** (excludes graph-specific task types)
- Uses async PostgreSQL connection pooling with `asyncpg`
- Implements concurrent task processing with bounded concurrency
- Routes tasks through a configurable router system (default: `coordinator_http`)
- Provides automatic lease renewal for long-running tasks
- Implements watchdog for stuck task recovery

**2. GraphDispatcher** (`graph_dispatcher.py`):
- Handles **graph-specific tasks** exclusively
- Manages graph embedding operations (SAGE/Neo4j integration)
- Manages NIM retrieval embedding operations (PostgreSQL integration)
- Uses synchronous SQLAlchemy for database operations
- Supports HGNN-aware node resolution across multiple entity types
- Implements chunked embedding processing for large batches

### Task Type Classification

**Graph Task Types** (handled by GraphDispatcher):
- All tasks with `type="graph"` (from `TaskType.GRAPH` enum)
- The specific graph operation is determined by `TaskPayload.graph_op` field:
  - `embed` - Graph embedding operations (legacy numeric node IDs + HGNN-aware UUID/text IDs)
  - `rag_query` - Similarity search over graph embeddings
  - `fact_embed` - Facts system embeddings
  - `fact_query` - Fact-based similarity search
  - `nim_embed` - NIM retrieval embeddings (task texts)
  - `sync_nodes` - Maintenance: sync graph_node_map

**General Task Types** (handled by QueueDispatcher):
- All tasks with types from `TaskType` enum (except `GRAPH`):
  - `chat` - Conversational agent-tunnel tasks
  - `query` - Ask/answer, reasoning, planning, search
  - `action` - Tool execution, system operations
  - `maintenance` - Health checks, telemetry, background operations
  - `unknown` - Fallback for unrecognized task types
- All custom task types not in the `TaskType` enum
- Routed through coordinator service for execution

### QueueDispatcher Features

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

### GraphDispatcher Features

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

## Task Taxonomy and Routing

SeedCore implements a **three-tier routing architecture** that cleanly separates planning, routing, and execution responsibilities. The system routes tasks based on type, complexity, and drift signals through a sophisticated coordination between Cognitive (planner), Coordinator (governor), and Organism (dispatcher).

### Architecture Overview

The routing system follows a **Governor → Dispatcher → Planner** pattern:

- **Cognitive Service**: Pure planner that generates abstract task steps with `{"task": {...}}` format
- **Coordinator Service**: Governor that decides fast-path vs escalation and orchestrates routing
- **Organism Manager**: Dispatcher that resolves abstract steps to specific organs and executes tasks

### Routing Flow

#### 1. Fast Path (Simple Tasks)
```
Task → Coordinator → OCPS Valve → Organism (resolve route) → Organ (execute)
```

#### 2. Escalation Path (Complex Tasks)
```
Task → Coordinator → OCPS Valve → Cognitive (plan) → Coordinator (bulk resolve) → Organism (execute)
```

### Cognitive Service (Planner-Only)

The Cognitive service has been refactored to be **planner-only** with no routing or execution decisions:

#### Handler Output Format
- **All handlers** return `{"task": {...}, "confidence_score": ...}` format
- **No organ_id or instance_id** in outputs (enforced by guardrails)
- **Normalized domains**: `"graph"`, `"facts"`, `"management"`, `"utility"`
- **Planning API**: Wraps single/multi steps into `solution_steps` with rich metadata

#### Planning Metadata
- **escalate_hint**: Boolean suggestion for escalation
- **sufficiency**: Retrieval sufficiency data for routing decisions
- **confidence**: Confidence score for plan quality
- **planner_timings_ms**: Performance metrics for observability

### Coordinator Service (Governor)

The Coordinator orchestrates routing decisions and maintains system-wide coordination:

#### Route Resolution
- **Fast Path**: Resolves single routes via Organism with TTL cache + single-flight
- **HGNN Path**: Bulk resolves all plan steps in one call to Organism
- **Static Fallback**: Provides resilient fallback when Organism is unavailable
- **Cache Strategy**: 3-second TTL with jitter, epoch-aware invalidation

#### Plan Validation
- **Abstract Steps**: Accepts plans with only `{"task": {...}}` format
- **Auto-stamping**: Generates stable `step_id` if missing
- **Domain Normalization**: Ensures consistent domain taxonomy

### Organism Manager (Dispatcher)

The Organism Manager owns all routing and execution decisions:

#### Routing Directory
- **Runtime Registry Integration**: Queries active instances with health validation
- **Bulk Resolve API**: `/resolve-route` and `/resolve-routes` endpoints
- **Rule Management**: CRUD operations for routing rules with cache refresh
- **Epoch Awareness**: Invalidates cache on cluster epoch rotation

#### Selected Routing Rules
- **general_query → utility_organ_1**
- **health_check → utility_organ_1**
- **execute → actuator_organ_1**
- **graph_embed | graph_rag_query | graph_embed_v2 | graph_rag_query_v2 | graph_sync_nodes → graph_dispatcher**
- **graph_fact_embed | graph_fact_query → graph_dispatcher**
- **fact_store | fact_search → utility_organ_1**
- **artifact_manage | capability_manage | memory_cell_manage → utility_organ_1**
- **model_manage | policy_manage | service_manage | skill_manage → utility_organ_1**

### Fast Path vs Escalation

- The `OCPSValve` applies a neural-CUSUM style accumulation of drift to decide fast-path execution vs escalation to `CognitiveService` (HGNN planning).
- **Reset semantics**: accumulator resets only on escalation to avoid under-escalation and to build evidence over time.
- **Concurrency controls** and latency SLOs guide escalation throughput.
- **Meta data ingestion**: Cognitive's escalation hints feed back into predicate signals for improved decision-making.

## Health Indicators

The current system shows **healthy** status across all components:

✅ **All deployments are RUNNING**
✅ **Cognitive has 2 replicas** for distributed reasoning
✅ **OrganismManager is alive** and ready to manage organs
✅ **No DEAD actors** left hanging
✅ **Proper replica distribution** across nodes

## Memory Architecture

The SeedCore system implements a sophisticated multi-tier memory architecture with SharedCacheShard optimization that supports both real-time processing and long-term knowledge retention. This architecture is designed to optimize performance while maintaining system efficiency through L0/L1/L2 cache hierarchy, atomic operations, and intelligent memory management.

### Memory Tiers Overview

| Tier | Name | Type | Purpose | Characteristics |
|------|------|------|---------|-----------------|
| **L0** | Organ-Local Cache | Volatile | Per-agent fastest access | In-memory, agent-specific |
| **L1** | Node Cache | Volatile | Node-wide shared cache | Per-node, TTL-managed |
| **L2** | SharedCacheShard | Volatile | Cluster-wide distributed cache | Sharded, LRU eviction, TTL |
| **Mw** | Working Memory | Volatile | Fast access to recent information | High-speed cache, limited capacity |
| **Mlt** | Long-Term Memory | Persistent | Durable knowledge storage | Large capacity, slower access |
| **Mfb** | Flashbulb Memory | Persistent | High-salience events | Rare, critical events only |
| **Ma** | Agent Private Memory | Volatile | Agent state representation | 128-D embedding vector |

### SharedCacheShard Architecture

The SharedCacheShard system implements a sophisticated L0/L1/L2 cache hierarchy that provides enterprise-grade caching with atomic operations, compression, and intelligent memory management.

#### L0/L1/L2 Cache Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│                    SharedCacheShard Architecture               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐        │
│  │     L0      │    │     L1      │    │     L2      │        │
│  │Organ-Local  │    │ Node Cache  │    │SharedCache  │        │
│  │   Cache     │    │             │    │   Shard     │        │
│  │             │    │             │    │             │        │
│  │• Per-agent  │    │• Per-node   │    │• Cluster-wide│        │
│  │• Fastest    │    │• TTL-managed│    │• Sharded     │        │
│  │• In-memory  │    │• Shared     │    │• LRU eviction│        │
│  └─────────────┘    └─────────────┘    └─────────────┘        │
│           │                   │                   │            │
│           └───────────────────┼───────────────────┘            │
│                               │                                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                Write-Through Strategy                   │   │
│  │                                                         │   │
│  │  set_global_item() → L0 + L1 + L2 (all levels)         │   │
│  │  get_item() → L0 → L1 → L2 (hierarchical lookup)       │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

#### Key Features

##### 1. Atomic Operations
- **CAS (Compare-And-Swap)**: `setnx()` for atomic sentinel operations
- **Single-Flight Guards**: Prevents thundering herd on cache misses
- **Race Condition Prevention**: Atomic operations ensure data consistency

##### 2. Unified Cache Key Schema
- **Global Keys**: `global:item:{kind}:{scope}:{id}`
- **Organ Keys**: `organ:{organ_id}:item:{kind}:{id}`
- **Consistent Naming**: Audit-friendly, hierarchical key structure
- **Examples**:
  - `global:item:fact:global:user_123`
  - `organ:agent_1:item:synopsis:task_456`

##### 3. Compression and Size Management
- **Automatic Compression**: Values >16KB compressed with zlib
- **Size Limits**: 256KB maximum value size with intelligent truncation
- **Envelope Format**: Safe serialization with versioning
- **JSON Safety**: Truncation preserves JSON structure

##### 4. Negative Caching and TTL
- **Negative Cache**: 30s TTL for cache misses to prevent stampedes
- **TTL Management**: Configurable TTL per cache level
- **Explicit Deletion**: Proper cleanup with multi-level deletion
- **Stale Prevention**: Negative cache cleared on successful writes

##### 5. Hot-Item Prewarming
- **Telemetry**: Tracks access patterns and hot items
- **Prewarming**: Promotes hot items to L0 during heartbeats
- **Rate Limiting**: 10 prewarm operations per minute per agent
- **Jitter**: Prevents cluster-wide prewarm bursts

#### Performance Characteristics

| Level | Access Time | Capacity | Persistence | Distribution |
|-------|-------------|----------|-------------|--------------|
| **L0** | ~1ms | Limited | Volatile | Per-agent |
| **L1** | ~5ms | Medium | Volatile | Per-node |
| **L2** | ~10-50ms | Large | Volatile | Cluster-wide |

#### Security and Safety

##### Compression Security
- **Zip Bomb Protection**: 2MB decompression limit
- **Safe Deserialization**: Only trusted envelope format
- **Error Handling**: Graceful fallbacks for corrupted data

##### Data Integrity
- **Schema Versioning**: `_v: "v1"` for future compatibility
- **Truncation Safety**: JSON structure preservation
- **Atomic Operations**: Race condition prevention

### Memory Flow and Access Patterns

#### 1. Working Memory (Mw)
- **Purpose**: Fast, volatile cache for recent information and active tasks
- **Characteristics**: 
  - High-speed access for real-time processing
  - Limited capacity requiring intelligent eviction
  - Volatile - data lost on system restart
- **Usage**: First-tier lookup for all memory queries
- **Management**: LRU eviction with priority-based retention

#### 2. Long-Term Memory (Mlt)
- **Purpose**: Durable storage for persistent knowledge and learned patterns
- **Characteristics**:
  - Large capacity for extensive knowledge storage
  - Slower access but persistent across restarts
  - Structured storage with indexing and search capabilities
- **Usage**: Fallback when Mw cache misses occur
- **Management**: Hierarchical organization with semantic indexing

#### 3. Flashbulb Memory (Mfb)
- **Purpose**: Storage for rare, high-salience events and critical incidents
- **Characteristics**:
  - Very selective - only stores exceptional events
  - High-fidelity preservation of important moments
  - Used for learning from significant experiences
- **Usage**: Incident logging and critical event preservation
- **Management**: Strict criteria for inclusion, long-term retention

#### 4. Agent Private Memory (Ma)
- **Purpose**: Individual agent state representation and personal knowledge
- **Characteristics**:
  - 128-dimensional embedding vector
  - Captures agent's current state and capabilities
  - Updated continuously based on experience
- **Usage**: Agent identity and capability assessment
- **Management**: Continuous updates via EWMA (Exponentially Weighted Moving Average)

### Memory Access Flow

```
Task Query
    ↓
1. Check L0 (Organ-Local Cache) - Fastest lookup (~1ms)
    ↓ (cache miss)
2. Check L1 (Node Cache) - Node-wide shared cache (~5ms)
    ↓ (cache miss)
3. Check L2 (SharedCacheShard) - Cluster-wide distributed cache (~10-50ms)
    ↓ (cache miss)
4. Query Mlt (Long-Term Memory) - Persistent storage
    ↓ (success)
5. Write-through to L2 → L1 → L0 (all levels)
    ↓ (high-salience event)
6. Optionally log to Mfb (Flashbulb Memory)

Enhanced Flow with Optimizations:
    ↓
• Negative Cache Check (30s TTL for misses)
• Single-Flight Sentinel (atomic CAS operation)
• Hot-Item Prewarming (promote to L0)
• Compression (automatic for >16KB values)
• Rate Limiting (10 prewarm ops/minute)
```

### MwManager (Enhanced with SharedCacheShard)

The **MwManager** is a per-organ facade that provides enterprise-grade caching with L0/L1/L2 hierarchy, atomic operations, and intelligent memory management.

#### Key Responsibilities (Enhanced)
- **L0/L1/L2 Coordination**: Manages hierarchical cache access patterns
- **Atomic Operations**: Provides CAS-based sentinel operations
- **Compression Management**: Handles automatic compression and decompression
- **Telemetry Collection**: Tracks hit/miss ratios and performance metrics
- **Rate Limiting**: Prevents cache stampedes and prewarm storms

#### Enhanced Memory Management Functions
- **Write-Through Strategy**: `set_global_item()` writes to all cache levels
- **Hierarchical Lookup**: `get_item()` checks L0 → L1 → L2 in sequence
- **Atomic Sentinels**: `try_set_inflight()` prevents thundering herd
- **Negative Caching**: `set_negative_cache()` prevents repeated misses
- **Hot-Item Prewarming**: Promotes frequently accessed data to L0
- **Compression**: Automatic zlib compression for large values
- **Size Management**: 256KB limits with JSON-safe truncation

#### API Enhancements
```python
# Unified cache key schema
mw.set_global_item_typed("fact", "global", "user_123", data, ttl_s=1800)
mw.get_item_typed_async("fact", "global", "user_123")

# Atomic operations
sentinel_acquired = await mw.try_set_inflight("fact:global:user_123", ttl_s=5)
await mw.del_global_key("fact:global:user_123")

# Compression and size management
mw.set_global_item_compressed("large_data", big_dict, ttl_s=3600)
data = await mw.get_item_compressed_async("large_data")

# Telemetry
stats = mw.get_telemetry()  # Hit ratios, access patterns, performance
```

### Tier0MemoryManager

The **Tier0MemoryManager** is a utility class (not a Ray actor) that orchestrates memory operations:

#### Key Responsibilities
- **Agent Registry**: Maintains handles to all RayAgent instances across organs
- **Memory Coordination**: Manages data flow between memory tiers
- **Agent Selection**: Implements `get_agent()` and `execute_task_on_best_of()` methods
- **Performance Optimization**: Balances memory access patterns for efficiency

#### Memory Management Functions
- **Batch Operations**: Efficiently processes multiple memory queries
- **Cache Management**: Optimizes Mw utilization and eviction policies
- **State Aggregation**: Collects agent states for system-wide analysis
- **Memory Analytics**: Tracks usage patterns and performance metrics

### Memory Integration with Services

#### StateService Integration
- **Collection**: Aggregates memory states from distributed agents
- **Caching**: Implements smart caching strategies for state queries
- **Persistence**: Manages long-term storage of system state snapshots

#### EnergyService Integration
- **Metrics**: Tracks memory utilization and access patterns
- **Optimization**: Monitors memory efficiency for energy optimization
- **Performance**: Measures memory-related performance impacts

#### CognitiveService Integration
- **Reasoning**: Uses memory context for cognitive processing
- **Learning**: Updates memory based on reasoning outcomes
- **Planning**: Leverages memory for task planning and decision making

### Memory Performance Characteristics

#### Access Latency (Enhanced with SharedCacheShard)
- **L0 (Organ-Local)**: ~1ms (in-memory, per-agent)
- **L1 (Node Cache)**: ~5ms (in-memory, per-node)
- **L2 (SharedCacheShard)**: ~10-50ms (distributed, cluster-wide)
- **Mw (Working Memory)**: ~1-10ms (in-memory access)
- **Mlt (Long-Term)**: ~10-100ms (persistent storage)
- **Mfb (Flashbulb)**: ~5-50ms (indexed lookup)
- **Ma (Private Memory)**: ~1-5ms (vector operations)

#### Capacity Management
- **L0**: Limited per-agent (configurable)
- **L1**: Medium per-node (TTL-managed)
- **L2**: Large cluster-wide (sharded, LRU eviction)
- **Mw**: Dynamic sizing based on available memory
- **Mlt**: Scalable storage with configurable limits
- **Mfb**: Fixed capacity with strict admission criteria
- **Ma**: Fixed 128-D vector per agent

#### Optimization Strategies (Enhanced)
- **L0/L1/L2 Hierarchy**: Multi-level caching with write-through
- **Atomic Operations**: CAS-based sentinels prevent race conditions
- **Negative Caching**: 30s TTL prevents cache stampedes
- **Hot-Item Prewarming**: Promotes frequently accessed data to L0
- **Compression**: Automatic zlib compression for values >16KB
- **Rate Limiting**: Prevents prewarm storms (10 ops/minute)
- **Predictive Caching**: Pre-load frequently accessed data
- **Intelligent Eviction**: LRU with priority-based retention
- **Batch Processing**: Group memory operations for efficiency
- **Size Management**: 256KB limits with JSON-safe truncation

## RayAgent Lifecycle Management

The SeedCore system implements comprehensive lifecycle management for RayAgent instances, ensuring optimal resource utilization and system health monitoring.

### Agent Lifecycle States

| State | Description | Characteristics |
|-------|-------------|-----------------|
| **Initializing** | Agent startup and configuration | Loading models, initializing memory |
| **Active** | Normal operation, processing tasks | Healthy, responsive, learning |
| **Idle** | No active tasks, maintaining state | Low resource usage, ready for work |
| **Degraded** | Performance issues, reduced capability | Needs attention, may require restart |
| **Archived** | End of lifecycle, state preserved | Exported to long-term memory |

### Heartbeat and Telemetry System

#### Heartbeat Generation
The `get_heartbeat()` method provides comprehensive agent telemetry:

```python
def get_heartbeat(self) -> Dict[str, Any]:
    return {
        "agent_id": self.agent_id,
        "state_embedding": self.h,  # 128-D private memory vector
        "capability_score": self.c,  # Current capability rating
        "memory_utilization": self.mem_util,  # Memory efficiency
        "lifecycle_state": self.lifecycle_state,
        "energy_state": self.energy_state,
        "task_history": self.task_history[-10:],  # Recent tasks
        "performance_metrics": {
            "success_rate": self.success_rate,
            "avg_response_time": self.avg_response_time,
            "memory_hit_rate": self.memory_hit_rate
        }
    }
```

#### Telemetry Loop
The `start_heartbeat_loop()` method implements periodic telemetry emission:

- **Frequency**: Configurable interval (default: 30 seconds)
- **Content**: Agent state, performance metrics, health status
- **Recipients**: StateService, EnergyService, monitoring systems
- **Purpose**: Real-time monitoring and system optimization

### Agent State Management

#### Private Memory Vector (h)
- **Dimension**: 128-dimensional embedding
- **Purpose**: Captures agent's current state and knowledge
- **Update**: Continuous via EWMA based on experience
- **Persistence**: Stored in Ma (Agent Private Memory)

#### Capability Score (c)
- **Range**: 0.0 to 1.0 (normalized)
- **Update**: EWMA based on task success/failure
- **Factors**: Task complexity, success rate, response time
- **Usage**: Agent selection and load balancing

#### Memory Utilization (mem_util)
- **Metric**: Cache hit rate and memory efficiency
- **Update**: EWMA based on memory access patterns
- **Optimization**: Guides memory allocation decisions
- **Monitoring**: Tracks memory performance trends

### Performance Tracking

#### Task History
- **Storage**: Rolling buffer of recent tasks (configurable size)
- **Content**: Task type, duration, success/failure, quality score
- **Purpose**: Learning, optimization, and debugging
- **Retention**: Recent tasks in memory, older in Mlt

#### Success Rate Calculation
```python
def update_success_rate(self, task_success: bool, quality_score: float):
    alpha = 0.1  # EWMA smoothing factor
    self.success_rate = (alpha * (1.0 if task_success else 0.0) + 
                        (1 - alpha) * self.success_rate)
```

#### Response Time Tracking
- **Measurement**: End-to-end task execution time
- **Averaging**: EWMA for smooth trends
- **SLO**: Monitored against Fast Path Latency SLO (1000ms)
- **Alerting**: Triggers when thresholds exceeded

### Energy State Management

#### Energy Tracking
- **Expected Contribution**: Predicted value based on capabilities
- **Entropy**: Measure of uncertainty and learning potential
- **Consumption**: Resource usage and computational cost
- **Balance**: System-wide energy distribution

#### Energy Update Process
```python
def update_energy_state(self, task_result: TaskResult):
    # Update expected contribution based on task success
    self.energy_state.expected_contribution *= (1 + task_result.quality_score * 0.1)
    
    # Update entropy based on learning
    self.energy_state.entropy *= (1 - task_result.learning_rate)
    
    # Update consumption metrics
    self.energy_state.consumption += task_result.resource_cost
```

### Archival and Cleanup

#### Archival Process
When an agent reaches end-of-life or becomes idle:

1. **State Export**: `_export_tier0_summary()` stores agent state in Mlt
2. **Memory Cleanup**: Evicts agent from Mw working memory
3. **Incident Logging**: Optionally logs to Mfb for critical events
4. **Lifecycle Update**: Sets state to "Archived"

#### Memory Cleanup
- **Mw Eviction**: Removes agent from working memory cache
- **State Preservation**: Critical state saved to long-term storage
- **Resource Release**: Frees up memory and computational resources
- **Cleanup Logging**: Records archival for audit purposes

### Health Monitoring

#### Health Indicators
- **Response Time**: Task execution latency
- **Success Rate**: Task completion success percentage
- **Memory Health**: Cache hit rates and utilization
- **Resource Usage**: CPU, memory, and energy consumption

#### Degradation Detection
- **Thresholds**: Configurable limits for each health metric
- **Trends**: EWMA-based trend analysis
- **Alerts**: Automatic notification of degradation
- **Recovery**: Automatic or manual intervention triggers

#### Recovery Mechanisms
- **Restart**: Graceful restart with state preservation
- **Resource Adjustment**: Dynamic resource allocation
- **Load Reduction**: Temporary task load reduction
- **Escalation**: Handoff to more capable agents

### Integration with Services

#### StateService Integration
- **Collection**: Regular heartbeat collection and aggregation
- **Storage**: Long-term storage of agent state snapshots
- **Analysis**: System-wide state analysis and trends

#### EnergyService Integration
- **Metrics**: Energy consumption and efficiency tracking
- **Optimization**: Energy-aware agent selection and scheduling
- **Balancing**: System-wide energy distribution management

#### OrganismManager Integration
- **Coordination**: Agent lifecycle coordination across organs
- **Scheduling**: Task assignment based on agent capabilities
- **Management**: Agent creation, monitoring, and cleanup

## Performance and Energy Tracking (Enhanced with SharedCacheShard)

The SeedCore system implements comprehensive performance and energy tracking with SharedCacheShard optimizations to optimize system efficiency and ensure optimal resource utilization.

### SharedCacheShard Performance Improvements

#### Cache Performance Metrics

| Metric | Description | Measurement | Target | Improvement |
|--------|-------------|-------------|---------|-------------|
| **L0 Hit Rate** | Organ-local cache hit ratio | L0 hits / total requests | >60% | ~1ms access |
| **L1 Hit Rate** | Node cache hit ratio | L1 hits / total requests | >30% | ~5ms access |
| **L2 Hit Rate** | SharedCacheShard hit ratio | L2 hits / total requests | >20% | ~10-50ms access |
| **Cache Stampede Prevention** | Single-flight sentinel success rate | Successful CAS operations | >95% | Prevents thundering herd |
| **Negative Cache Effectiveness** | Miss prevention via negative cache | Negative cache hits | >80% | Reduces Mlt queries |
| **Compression Ratio** | Space savings from compression | (Original - Compressed) / Original | >30% | For values >16KB |
| **Prewarm Effectiveness** | Hot-item promotion success | L0 promotions / prewarm ops | >70% | Proactive optimization |

#### Enhanced Performance Indicators

| Metric | Description | Measurement | Target |
|--------|-------------|-------------|---------|
| **Task Success Rate** | Percentage of successfully completed tasks | EWMA over time window | >95% |
| **Response Time** | End-to-end task execution latency | P50, P95, P99 percentiles | <1000ms (SLO) |
| **Memory Hit Rate** | Cache hit ratio in working memory | Hit/(Hit+Miss) ratio | >80% |
| **Throughput** | Tasks processed per unit time | Tasks/second | Variable by service |
| **Resource Utilization** | CPU, memory, energy consumption | Percentage of allocated resources | <80% |
| **Cache Latency P95** | 95th percentile cache access time | L0+L1+L2 combined | <50ms |
| **Compression Efficiency** | Bytes saved per compressed value | Compression ratio | >30% |
| **Atomic Operation Success** | CAS operation success rate | Successful setnx / total attempts | >95% |

#### Capability Score Calculation

The capability score `c` is a normalized metric (0.0 to 1.0) that represents an agent's current performance:

```python
def update_capability_score(self, task_result: TaskResult):
    # Base success factor
    success_factor = 1.0 if task_result.success else 0.0
    
    # Quality factor (0.0 to 1.0)
    quality_factor = task_result.quality_score
    
    # Complexity factor (higher complexity = higher reward)
    complexity_factor = min(task_result.complexity / 10.0, 1.0)
    
    # Response time factor (faster = better)
    time_factor = max(0.0, 1.0 - (task_result.duration / self.slo_threshold))
    
    # Combined score
    combined_score = (success_factor * 0.4 + 
                     quality_factor * 0.3 + 
                     complexity_factor * 0.2 + 
                     time_factor * 0.1)
    
    # Update with EWMA
    alpha = 0.1  # Smoothing factor
    self.c = alpha * combined_score + (1 - alpha) * self.c
```

#### Memory Utilization Tracking

Memory utilization `mem_util` tracks the efficiency of memory access patterns:

```python
def update_memory_utilization(self, cache_hit: bool, access_time: float):
    # Cache hit rate
    hit_rate = 1.0 if cache_hit else 0.0
    
    # Access efficiency (faster access = better)
    efficiency = max(0.0, 1.0 - (access_time / self.expected_access_time))
    
    # Combined memory utilization
    combined_util = (hit_rate * 0.7 + efficiency * 0.3)
    
    # Update with EWMA
    alpha = 0.05  # Slower adaptation for memory patterns
    self.mem_util = alpha * combined_util + (1 - alpha) * self.mem_util
```

### Energy Management System

#### Energy State Components

| Component | Description | Purpose |
|-----------|-------------|---------|
| **Expected Contribution** | Predicted value based on capabilities | Load balancing and scheduling |
| **Entropy** | Measure of uncertainty and learning potential | Learning and adaptation |
| **Consumption** | Actual resource usage | Cost optimization |
| **Balance** | System-wide energy distribution | Fair resource allocation |

#### Energy Update Algorithm

```python
def update_energy_state(self, task_result: TaskResult):
    # Update expected contribution
    contribution_delta = (task_result.quality_score * 
                         task_result.complexity * 
                         self.energy_state.expected_contribution * 0.1)
    self.energy_state.expected_contribution += contribution_delta
    
    # Update entropy (learning reduces uncertainty)
    learning_rate = min(task_result.learning_rate, 0.1)
    self.energy_state.entropy *= (1 - learning_rate)
    
    # Update consumption
    resource_cost = (task_result.cpu_time * 0.5 + 
                    task_result.memory_usage * 0.3 + 
                    task_result.network_io * 0.2)
    self.energy_state.consumption += resource_cost
    
    # Normalize energy state
    self.energy_state.normalize()
```

#### Energy Optimization Strategies

1. **Load Balancing**: Distribute tasks based on energy efficiency
2. **Resource Scaling**: Adjust resources based on energy consumption
3. **Agent Selection**: Prefer agents with better energy efficiency
4. **Scheduling**: Optimize task scheduling for energy conservation

### Performance Monitoring and Alerting

#### Real-time Monitoring

The system continuously monitors performance metrics and triggers alerts when thresholds are exceeded:

```python
def check_performance_thresholds(self):
    alerts = []
    
    # Response time SLO violation
    if self.avg_response_time > self.slo_threshold:
        alerts.append({
            "type": "SLO_VIOLATION",
            "metric": "response_time",
            "value": self.avg_response_time,
            "threshold": self.slo_threshold
        })
    
    # Success rate degradation
    if self.success_rate < 0.95:
        alerts.append({
            "type": "SUCCESS_RATE_DEGRADATION",
            "metric": "success_rate",
            "value": self.success_rate,
            "threshold": 0.95
        })
    
    # Memory efficiency issues
    if self.mem_util < 0.8:
        alerts.append({
            "type": "MEMORY_EFFICIENCY",
            "metric": "memory_utilization",
            "value": self.mem_util,
            "threshold": 0.8
        })
    
    return alerts
```

#### Performance Trends Analysis

The system analyzes performance trends to predict potential issues:

- **Trend Detection**: EWMA-based trend analysis
- **Anomaly Detection**: Statistical outlier detection
- **Predictive Alerts**: Early warning of potential issues
- **Capacity Planning**: Resource requirement forecasting

### Service-Specific Performance Metrics

#### CognitiveService Metrics
- **Reasoning Latency**: Time for cognitive processing
- **Planning Accuracy**: Quality of generated plans
- **Learning Rate**: Adaptation speed to new patterns
- **Memory Synthesis**: Effectiveness of knowledge integration

#### StateService Metrics
- **Aggregation Latency**: Time to collect and aggregate state
- **Cache Efficiency**: State query cache hit rates
- **Storage Utilization**: Long-term memory usage patterns
- **Query Performance**: State retrieval response times

#### EnergyService Metrics
- **Energy Efficiency**: Work per unit energy consumed
- **Resource Utilization**: CPU, memory, network usage
- **Cost Optimization**: Resource cost per task
- **Balance Metrics**: Energy distribution across agents

#### MLService Metrics
- **Inference Latency**: Model prediction time
- **Model Accuracy**: Prediction quality scores
- **Throughput**: Predictions per second
- **Resource Usage**: GPU/CPU utilization for inference

### Performance Optimization Strategies

#### Adaptive Resource Allocation
- **Dynamic Scaling**: Adjust replicas based on load
- **Resource Tuning**: Optimize CPU/memory allocation
- **Load Balancing**: Distribute work efficiently
- **Priority Scheduling**: Handle high-priority tasks first

#### Memory Optimization
- **Predictive Caching**: Pre-load frequently accessed data
- **Intelligent Eviction**: Smart cache eviction policies
- **Compression**: Optimize storage efficiency
- **Batch Processing**: Group operations for efficiency

#### Energy Optimization
- **Efficient Scheduling**: Minimize energy consumption
- **Resource Sharing**: Share resources across agents
- **Sleep Modes**: Reduce energy during idle periods
- **Load Consolidation**: Group tasks for efficiency

### Integration with Monitoring Systems

#### Metrics Export
- **Prometheus**: Time-series metrics for monitoring
- **Grafana**: Visualization and dashboards
- **AlertManager**: Alert routing and notification
- **Custom Dashboards**: Service-specific monitoring

#### Logging and Tracing
- **Structured Logging**: JSON-formatted logs for analysis
- **Distributed Tracing**: Request flow tracking
- **Performance Profiling**: Detailed performance analysis
- **Error Tracking**: Comprehensive error monitoring

## Scaling and Distribution

### Horizontal Scaling
- **CognitiveService**: Currently 2 replicas, can scale based on reasoning workload
- **Other services**: Single replica, can be scaled as needed
- **Load balancing**: Automatic across replicas via Serve proxy

### Fault Tolerance
- **Multi-node distribution**: Replicas spread across different Ray nodes
- **Automatic failover**: Serve handles replica failures and restarts
- **State management**: Actor state preserved across failures

### Performance Characteristics
- **Parallel processing**: Multiple CognitiveService replicas handle concurrent reasoning tasks
- **Low latency**: Direct actor-to-actor communication within Ray cluster
- **High throughput**: Distributed processing across multiple nodes

## Monitoring and Observability (Enhanced with SharedCacheShard)

### Key Metrics to Monitor

#### System Health Metrics
- **Replica health**: All replicas should be in RUNNING state
- **Actor distribution**: Ensure replicas are distributed across nodes
- **Response times**: Monitor service latency and throughput
- **Resource utilization**: CPU, memory, and GPU usage across nodes

#### SharedCacheShard Metrics
- **Cache Hit Ratios**: L0, L1, L2 hit rates per agent and cluster-wide
- **Cache Latency**: P50, P95, P99 access times for each cache level
- **Atomic Operations**: CAS success rate and contention metrics
- **Compression Efficiency**: Space savings and compression ratio trends
- **Negative Cache Effectiveness**: Miss prevention and TTL utilization
- **Prewarm Performance**: Hot-item promotion success and rate limiting
- **Memory Utilization**: Cache size, eviction rates, and TTL distribution

#### Enhanced Telemetry
```python
# MwManager telemetry example
telemetry = mw.get_telemetry()
{
    "organ_id": "agent_1",
    "total_requests": 1500,
    "hits": 1200,
    "misses": 300,
    "hit_ratio": 0.8,
    "l0_hits": 800,      # ~1ms access
    "l1_hits": 300,      # ~5ms access  
    "l2_hits": 100,      # ~10-50ms access
    "l0_hit_ratio": 0.53,
    "l1_hit_ratio": 0.20,
    "l2_hit_ratio": 0.07,
    "compression_savings": 0.35,  # 35% space saved
    "negative_cache_hits": 45,    # Miss prevention
    "setnx_contention": 0.05      # 5% CAS contention
}
```

#### Performance Dashboards
- **Cache Performance**: Hit ratios, latency, and efficiency trends
- **Atomic Operations**: CAS success rates and contention patterns
- **Compression Analytics**: Space savings and compression ratios
- **Hot-Item Tracking**: Prewarm effectiveness and access patterns
- **Memory Health**: Cache utilization and eviction patterns

### Troubleshooting
- **Actor failures**: Check Ray logs for actor crash details
- **Service unavailability**: Verify Serve proxy routing and deployment status
- **Performance issues**: Monitor replica distribution and resource allocation

## Future Considerations

### Potential Enhancements

#### SharedCacheShard Optimizations
- **Adaptive TTL**: Dynamic TTL adjustment based on access patterns
- **Predictive Prewarming**: ML-based hot-item prediction for proactive caching
- **Cross-Region Replication**: L2 cache replication across geographic regions
- **Advanced Compression**: LZ4 or Zstandard for better compression ratios
- **Cache Warming**: Bulk preloading of critical data during startup

#### System Enhancements
- **Auto-scaling**: Implement dynamic replica scaling based on load
- **Multi-region**: Extend to multiple Ray clusters for geographic distribution
- **Advanced routing**: Implement intelligent request routing based on actor load
- **State persistence**: Add persistent state storage for critical actor state

#### Monitoring and Analytics
- **Real-time Dashboards**: Live cache performance monitoring
- **Anomaly Detection**: ML-based detection of cache performance issues
- **Capacity Planning**: Predictive analytics for cache sizing
- **Cost Optimization**: Resource usage optimization based on cache patterns

### Integration Points
- **External APIs**: REST/GRPC endpoints for external system integration
- **Event streaming**: Integration with message queues for asynchronous processing
- **Monitoring**: Integration with observability platforms (Prometheus, Grafana)
- **Security**: Authentication and authorization for service-to-service communication

---

*This document provides a comprehensive overview of the SeedCore architecture. For detailed implementation specifics, refer to the individual component documentation in the `docs/architecture/components/` directory.*

## HGNN Graph and GraphDispatcher

The graph execution path is handled by a dedicated `GraphDispatcher` actor and supporting graph utilities. It processes graph embedding and RAG queries, synchronizes nodes, and integrates with facts/resources/agent-layer entities.

### Responsibilities

- Resolve start nodes from rich params: `start_node_ids`, `start_fact_ids`, `start_artifact_ids`, `start_capability_ids`, `start_memory_cell_ids`, `start_model_ids`, `start_policy_ids`, `start_service_ids`, `start_skill_ids`.
- Ensure presence of entities in the graph store via `_ensure_*_nodes` methods (creates nodes if needed according to migration semantics).
- Dispatch compute to `GraphEmbedder` and persist results.
- Handle fact-oriented graph tasks: `graph_fact_embed`, `graph_fact_query`.

### Task Types (graph)

- **graph_embed / graph_embed_v2**: compute embeddings for a k-hop neighborhood.
- **graph_rag_query / graph_rag_query_v2**: retrieve graph-augmented context and answers.
- **graph_sync_nodes**: reconcile external entities into graph nodes.
- **graph_fact_embed | graph_fact_query**: fact-centric graph operations.

## Graph Embeddings Pipeline

End-to-end flow from Neo4j to Postgres vectors:

1. `GraphLoader.load_k_hop(start_ids, k)`
   - Queries Neo4j for k-hop subgraph, builds a homogeneous DGL graph, returns `(g, idx_map, X)` where `X` are deterministic 128-dim features.
2. `GraphEmbedder.compute_embeddings(node_ids, k)`
   - Runs the HGNN to produce `Z`; returns a mapping `{node_id: list[float]}` with robust error handling and logging.
3. `upsert_embeddings(emb_map, label_map, props_map)`
   - Bulk upsert into `graph_embeddings` using SQLAlchemy `executemany`.
   - Parameters are normalized in Python: `props` always a JSON string (default `'{}'`), `vec` as JSON list string; SQL casts use `(:vec)::jsonb::vector` and `(:props)::jsonb` to avoid placeholder parsing ambiguity.

This pipeline eliminates previous `NoneType` unpack errors and `psycopg2` syntax errors near placeholders, and provides stable embeddings persistence.

## Facts, Resources, and Agent Layer Integration

Recent migrations added first-class entities and tasks:

- **Facts system (Migration 009)**: Facts become addressable graph nodes; tasks `graph_fact_embed`, `graph_fact_query`, plus utility tasks `fact_store`, `fact_search`.
- **Resources (Migration 007)**: `artifact_manage`, `capability_manage`, `memory_cell_manage` for resource governance.
- **Agent layer (Migration 008)**: `model_manage`, `policy_manage`, `service_manage`, `skill_manage` to orchestrate agent capabilities.

Updates span `Coordinator` routing, `OrganismManager` task handlers, and `CognitiveService` enums/handlers with tailored token budgets, cache TTLs, and query building.

## Resiliency: Drift Detection and Circuit Breakers

- **Drift Detection (OCPSValve)**: Uses cumulative drift with thresholds to choose fast-path vs HGNN escalation; drift score sourced from ML service.
- **Timeout Handling**: Service clients define circuit breakers with `expected_exception=(httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TimeoutException)`; timeouts are treated as expected and metered, not fatal.
- **Metrics**: `PredicateMetrics.record_circuit_breaker_event(service, event_type)` records breaker events. Drift computation logs latency and falls back to a heuristic score when ML times out.

These measures prevent cascading failures and provide consistent behavior under transient outages.

## TaskPayload v2.5+ Architecture

### Overview

TaskPayload v2.5+ introduces a **stable contract** for task instance routing and execution with **envelope isolation** and **future-proof evolution** without schema migrations. The design separates **type-level capabilities** (from `pkg_subtask_types.default_params`) from **instance-level routing signals** (from `tasks.params`).

### Core Concepts

#### Capability vs Task Instance

**Capability Definition (Type-Level)**:
- Stored in `pkg_subtask_types.default_params`
- Declares what a *task type* requires/prefers: specialization, behaviors, tools, routing tags, default skills
- Provides guardrails and defaults

**TaskPayload (Instance-Level)**:
- Stored in `tasks.params` (JSONB)
- Declares what a *specific task instance* needs: routing constraints, cognitive flags, tool calls, multimodal metadata
- Provides execution-time intent

**Key Principle**: *Type-level defaults provide guardrails; instance-level payloads provide execution-time intent.*

### End-to-End Runtime Flow

```
pkg_subtask_types (Database)
    ↓
CapabilityRegistry (loads + caches, builds canonical task definition)
    ↓
CapabilityMonitor (hash polling, detects changes)
    ↓
SpecializationManager (static enums + runtime dynamic specializations)
    ↓
RoleProfile (skills, behaviors, tools, routing_tags, behavior_config)
    ↓
BaseAgent (materializes skills, initializes behaviors, enforces RBAC)
    ↓
Router / Coordinator (selects best Organ/Agent using routing inbox)
```

### Envelope Isolation (Non-Negotiable)

TaskPayload v2.5+ uses strict envelope isolation to prevent conflicts and enable independent evolution:

- `params.routing` — **Router Inbox** (read-only input)
- `params._router` — **Router Output** (system generated, write-only)
- `params.cognitive` — cognitive execution controls
- `params.chat` — chat message window/context
- `params.risk` — upstream classification (audit + protocols)
- `params.graph` — graph ops payload when applicable
- `params.multimodal` — voice/vision metadata (v2.5)
- `params.tool_calls` — executable tool invocations (structured)
- `params.interaction` — interaction mode (e.g., `agent_tunnel`, `coordinator_routed`)

### Router Inbox: `params.routing`

#### Canonical Format

```jsonc
{
  "routing": {
    "required_specialization": "SecurityMonitoring",  // HARD constraint
    "specialization": "SecurityMonitoring",           // SOFT preference
    "skills": {"threat_assessment": 0.9},             // 0.0–1.0
    "tools": ["alerts.raise", "sensors.read_all"],    // REQUIRED tool NAMES (strings)
    "routing_tags": ["security", "monitoring"],
    "hints": {
      "priority": 7,
      "deadline_at": "2025-11-25T14:35:00Z",
      "ttl_seconds": 60
    }
  }
}
```

#### Semantics

- `required_specialization`: Must match (routing fails otherwise)
- `specialization`: Prefer, but may fall back
- `skills`: Used for scoring and selection within candidates (0.0–1.0)
- `tools`: Required capabilities by name (RBAC + selection signals) - **strings only**
- `routing_tags`: Tag matching / structured routing intent
- `hints`: Scheduling metadata (priority/deadline/TTL)

#### Tunnel Mode Bypass

If `params.interaction.mode == "agent_tunnel"`, router is skipped and `params.routing` is ignored.

### Router Output: `params._router`

```jsonc
{
  "_router": {
    "is_high_stakes": true,
    "agent_id": "agent_security_001",
    "organ_id": "organ_security",
    "reason": "Matched required specialization and priority constraints"
  }
}
```

**Write-only rule**: Upstream components must never write `_router`.

### Tool Calls: `params.tool_calls`

Separates **tool permission requirements** (`routing.tools`) from **execution requests** (`tool_calls`):

- `routing.tools` = list of **required tool names** (strings)
- `tool_calls` = list of **tool invocation objects**

```jsonc
{
  "tool_calls": [
    {"name": "iot.control", "args": {"device": "lights", "location": "lobby", "action": "off"}}
  ]
}
```

### Cognitive Envelope: `params.cognitive`

Controls inference style, memory I/O, and model routing:

```jsonc
{
  "cognitive": {
    "agent_id": "agent_security_001",
    "cog_type": "task_planning",
    "decision_kind": "planner",
    "llm_provider_override": "openai",
    "llm_model_override": "gpt-4o",
    "skip_retrieval": false,
    "disable_memory_write": false,
    "force_rag": false,
    "force_deep_reasoning": false
  }
}
```

**Key note**: `agent_id` is usually populated after routing, derived from `_router.agent_id`.

### Multimodal Envelope: `params.multimodal`

Stores metadata only. Media binaries live externally. Embeddings live in dedicated tables:

```jsonc
{
  "multimodal": {
    "source": "vision",
    "media_uri": "s3://.../camera_101.mp4",
    "scene_description": "Person detected near Room 101",
    "confidence": 0.92,
    "detected_objects": [{"class": "person", "bbox": [100,200,150,300]}],
    "timestamp": "2025-11-25T14:30:22Z",
    "camera_id": "camera_101",
    "location_context": "room_101_corridor",
    "is_real_time": true,
    "ttl_seconds": 60,
    "parent_stream_id": "stream_camera_101_20251125"
  }
}
```

**Embedding Storage Strategy**:
- `task_multimodal_embeddings`: Direct FK to `tasks.id` (fast "Living System" recall)
- `graph_embeddings_128/1024`: Indirect via `graph_node_map` (HGNN/structural memory)

### Priority Order (Canonical)

#### Behaviors (highest → lowest)
1. Constructor `behaviors`
2. `executor.behaviors` (type-level)
3. Legacy `agent_behavior` (type-level)
4. `RoleProfile.default_behaviors` (registries)

#### Skills (highest → lowest)
1. Learned deltas (SkillVector)
2. `routing.skills` (type-level or instance-level routing inbox)
3. `RoleProfile.default_skills` (registries)

#### Tools
1. `executor.tools + routing.tools` (union)
2. Static registry `RoleProfile.allowed_tools`

**Note**: Execution requests live in `params.tool_calls` and are not part of RBAC/scoring.

### Precedence Rules: Task Instance vs Task Type

When resolving routing inputs, apply:

1. **Task instance** (`tasks.params.routing`) overrides all defaults
2. Else **task type** (`pkg_subtask_types.default_params`) provides defaults
3. Else **organ defaults / generalist fallback**

**Operational recommendation**: `_router.reason` must state whether constraints came from instance vs type.

### Result Provenance: `result.meta`

Store routing decision snapshots, execution telemetry, and cognitive traces:

```jsonc
{
  "routing_decision": {
    "selected_agent_id": "agent_security_001",
    "selected_organ_id": "organ_security",
    "router_score": 0.95,
    "routed_at": "2025-11-25T14:30:25Z"
  },
  "exec": {"latency_ms": 16000, "attempt": 1},
  "cognitive_trace": {"chosen_model": "gpt-4o", "decision_path": "PLANNER_PATH"}
}
```

## PKG Policy Governance System

The Policy Knowledge Graph (PKG) system provides versioned policy snapshots with rule-based task emission, enabling dynamic policy management and governance without service restarts.

### PKG Core (Migration 013)

The PKG system provides versioned policy snapshots with rule-based task emission:

**Snapshots**:
```sql
CREATE TABLE pkg_snapshots (
  id SERIAL PRIMARY KEY,
  version TEXT NOT NULL UNIQUE,
  env pkg_env NOT NULL DEFAULT 'prod',
  entrypoint TEXT DEFAULT 'data.pkg',
  checksum TEXT NOT NULL CHECK (length(checksum)=64),
  is_active BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Subtask Types**:
- Stores capability definitions with `default_params` JSONB
- Links to snapshot for versioning
- Defines executor specialization, behaviors, tools, routing tags

**Policy Rules**:
- Rule-based policy evaluation (Rego/WASM)
- Conditions: TAG, SIGNAL, VALUE, FACT
- Emissions: links rules to subtask types with relationship types (EMITS, ORDERS, GATE)

**Artifacts**:
- WASM/Rego bundles stored as BYTEA
- SHA256 checksums for integrity verification

### PKG Operations (Migration 014)

**Canary Deployments**:
- Targeted deployments by router/edge class
- Percentage-based rollout (0-100%)
- Region-aware deployment lanes

**Validation System**:
- Fixtures for policy testing
- Validation runs with success/failure tracking
- JSONB reports for detailed results

**Promotion Audit**:
- Track snapshot promotions and rollbacks
- Actor attribution and reason tracking
- Metrics storage (p95 latency, validation summaries)

**Device Version Tracking**:
- Edge device heartbeat monitoring
- Version compliance tracking
- Region-based device grouping

### PKG Views & Functions (Migration 015)

**Helper Views**:
- `pkg_active_artifact`: Active artifact per environment
- `pkg_rules_expanded`: Flattened rules with emissions
- `pkg_deployment_coverage`: Device coverage analysis

**Helper Functions**:
- `pkg_active_snapshot_id(env)`: Get active snapshot ID
- `pkg_promote_snapshot(snapshot_id, env, actor, reason)`: Promote snapshot
- `pkg_check_integrity()`: Validate cross-snapshot integrity

### Fact-PKG Integration (Migration 016)

**Foreign Key Constraints**:
- Facts linked to PKG snapshots via `snapshot_id`
- PKG-governed facts require snapshot reference

**Temporal Modeling**:
- `valid_from` defaulted to `created_at` for temporal queries
- Enables "what was true yesterday?" queries
- Expired fact cleanup functions

**Structured Triple Conversion**:
- Automatic conversion of text-only facts to structured triples
- Pattern-based extraction (e.g., "X is a Y" → subject=X, predicate=hasType)
- Preserves original text in `object_data` metadata

### PKG Snapshot Scoping (Migration 017)

**Snapshot Isolation**:
- `snapshot_id` added to `tasks`, `graph_embeddings_1024`, `graph_node_map`
- Enables reproducible runs, multi-world isolation, time travel debugging
- Foreign key constraints to `pkg_snapshots` with `ON DELETE SET NULL`

**Backfill Strategy**:
- Phase 1: Add nullable columns (non-breaking)
- Phase 2: Backfill with active snapshot
- Phase 3: Add foreign key constraints
- Phase 4: Add performance indexes
- Phase 5: Enforce NOT NULL on tasks (after backfill)

**Performance Indexes**:
- `idx_tasks_snapshot_id`: Snapshot-scoped task queries
- `idx_tasks_snapshot_status`: Composite index for status queries
- `idx_graph_embeddings_1024_snapshot_id`: Snapshot-scoped embeddings
- `idx_graph_node_map_snapshot_id`: Snapshot-scoped node queries

**Critical Constraint**:
- PKG-governed facts (`pkg_rule_id IS NOT NULL`) must have `snapshot_id`
- Ensures policy traceability and governance

## Unified Cortex Memory

The Unified Cortex Memory system provides a three-tier memory architecture with snapshot-aware semantic search, enabling efficient knowledge retrieval across event working memory, knowledge base, and world memory.

### Three-Tier Memory Architecture

The Unified Cortex Memory view (`v_unified_cortex_memory`) merges three memory tiers with snapshot-aware scoping:

**TIER 1: Event Working Memory** (`event_working`):
- Multimodal task events (voice, vision, sensor)
- Direct FK to `tasks` table for fast "Living System" recall
- Excludes tasks promoted to knowledge graph (TIER 2)
- Snapshot-aware via `tasks.snapshot_id`

**TIER 2: Knowledge Base** (`knowledge_base`):
- Tasks linked through `graph_node_map` to `graph_embeddings_1024`
- Structural knowledge and task relationships
- Includes promoted tasks from TIER 1
- Snapshot-aware via COALESCE from tasks/embeddings/node_map

**TIER 3: World Memory** (`world_memory`):
- General graph entities (agents, organs, artifacts, etc.)
- Broader knowledge base context
- Excludes `task.primary` labels to avoid TIER 2 duplication
- Snapshot-aware via `graph_embeddings_1024.snapshot_id`

### Embedding Views

**128d Embeddings** (Fast HGNN Routing):
- `task_embeddings_primary_128`: Primary task embeddings
- `tasks_missing_embeddings_128`: Tasks needing embeddings
- `task_embeddings_stale_128`: Stale embedding detection via SHA256 hash

**1024d Embeddings** (Deep Semantic Understanding):
- `task_embeddings_primary_1024`: Primary task embeddings with memory tier/label
- `tasks_missing_embeddings_1024`: Tasks needing embeddings
- `task_embeddings_stale_1024`: Stale embedding detection
- `tasks_missing_any_embedding_1024`: Tasks missing multimodal OR graph embeddings

### Semantic Search Function

```sql
unified_cortex_semantic_search(
    query_vector vector(1024),
    snapshot_id INTEGER,
    similarity_threshold FLOAT DEFAULT 0.8,
    limit_results INTEGER DEFAULT 10,
    memory_tier_filter TEXT DEFAULT NULL
)
```

- Snapshot-aware semantic search across unified memory
- Enforces similarity threshold to prevent low-quality matches
- Optional memory tier filtering (event_working, knowledge_base, world_memory)
- Returns results ordered by similarity (highest first)

### Performance Optimizations

**Partial GIN Index**:
- `idx_tasks_multimodal_fast`: Only indexes tasks with `params.multimodal`
- Dramatically reduces index size (500MB+ → 10-50MB at 1M+ rows)
- Improves query times (200-500ms → 5-15ms)

**Functional Index**:
- `idx_tasks_content_hash_1024`: Pre-computes content hashes for stale detection
- Uses IMMUTABLE function with `params::text` (compact JSON)
- Note: Index hash differs from view hash (which uses `jsonb_pretty` for exact Python matching)

### Deduplication Strategy

- TIER 1 excludes tasks with `graph_embeddings_1024` entries (`label='task.primary'`)
- TIER 2 includes all tasks with `graph_embeddings_1024` entries (`label='task.primary'`)
- TIER 3 excludes `label='task.primary'` to avoid duplication with TIER 2
- Ensures each task appears in exactly one tier based on promotion status

## Task Outbox Hardening

The Task Outbox system implements a transactional outbox pattern for reliable event publishing with exactly-once semantics.

### Transactional Outbox Pattern

Reliable event publishing with exactly-once semantics:

```sql
CREATE TABLE task_outbox (
  id BIGSERIAL PRIMARY KEY,
  task_id UUID NOT NULL,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  dedupe_key TEXT UNIQUE,
  available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Key Features

**Availability Scheduling**:
- `available_at` column enables backoff and delayed processing
- Exponential backoff via `available_at` updates
- Dead-letter logic after max attempts

**Retry Tracking**:
- `attempts` counter for exponential backoff
- Check constraint: `attempts >= 0`
- Automatic `updated_at` trigger

**Indexes**:
- `idx_task_outbox_available`: Efficient `FOR UPDATE SKIP LOCKED` queries
- `idx_task_outbox_event_type`: Event type routing
- `idx_task_outbox_task_id`: Task lookup

## Task Router Telemetry

The Task Router Telemetry system stores router telemetry snapshots for coordinator routing decisions, enabling observability and optimization of routing behavior.

### OCPS Signal Tracking

Stores router telemetry snapshots for coordinator routing decisions:

```sql
CREATE TABLE task_router_telemetry (
    id BIGSERIAL PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    surprise_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    x_vector JSONB NOT NULL DEFAULT '[]'::jsonb,
    weights JSONB NOT NULL DEFAULT '[]'::jsonb,
    ocps_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    chosen_route TEXT NOT NULL DEFAULT 'unknown',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Key Components

**Surprise Score** (`surprise_score`):
- Cumulative surprise score (S_t) from OCPS
- Higher values indicate more novel/unexpected events

**Surprise Vector** (`x_vector`):
- Six-component vector: cache_novelty, semantic_drift, multimodal_anomaly, graph_context_drift, logic_uncertainty, cost_risk

**Feature Weights** (`weights`):
- Array of floats corresponding to x_vector components
- Used in routing decision scoring

**OCPS Metadata** (`ocps_metadata`):
- OCPS state: S_t (cumulative sum), h_threshold (valve threshold), drift_flag, etc.
- GIN index for efficient JSONB queries

**Chosen Route** (`chosen_route`):
- Route decision: `fast` (deterministic), `planner` (deep analysis), `hgnn` (graph-based routing)

### Indexes

- `idx_task_router_telemetry_task_id`: Fast task lookups
- `idx_task_router_telemetry_chosen_route`: Route analysis
- `idx_task_router_telemetry_created_at`: Time-series queries
- `idx_task_router_telemetry_route_created`: Composite route + time analysis
- `idx_task_router_telemetry_ocps_metadata`: GIN index for JSONB queries

## State and Energy Services

SeedCore implements standalone State and Energy services as independent Ray Serve applications, decoupling state aggregation and energy calculations from the organism subsystem.

### State Service

The State Service provides centralized state collection from distributed Ray actors and memory managers:

**Key Features**:
- Extracted `StateAggregator` functionality into a dedicated Ray Serve application
- Provides centralized state collection from distributed Ray actors and memory managers
- Implements Paper §3.1 requirements for light aggregators
- RESTful API with endpoints for unified state queries

**API Endpoints**:
- `GET /health` - Health check
- `GET /status` - Service status
- `POST /unified-state` - Get unified state (with options)
- `GET /unified-state` - Simplified unified state query

**Resource Allocation**:
- CPU: 0.5
- Memory: 1GB
- Replicas: 1

### Energy Service

The Energy Service provides pure computational service that consumes `UnifiedState` data:

**Key Features**:
- Pure computational service that consumes `UnifiedState` data
- Provides energy calculations, gradients, and agent optimization
- No state collection responsibilities - purely computational
- RESTful API with endpoints for energy computation and optimization

**API Endpoints**:
- `GET /health` - Health check
- `GET /status` - Service status
- `POST /compute-energy` - Compute energy metrics
- `POST /optimize-agents` - Optimize agent selection
- `GET /energy-from-state` - Get energy from current state

**Resource Allocation**:
- CPU: 1.0
- Memory: 1GB
- Replicas: 1

### Service Integration

**Data Flow**:
1. **State Collection**: State Service collects data from Ray actors and memory managers
2. **State Query**: OrganismManager and telemetry endpoints query state service
3. **Energy Calculation**: Energy Service consumes state data for computations
4. **Energy Query**: Telemetry endpoints query energy service for metrics

**Benefits**:
- **Separation of Concerns**: State aggregation and energy calculations are decoupled
- **Independent Scaling**: Each service can scale independently based on workload
- **Reusability**: Services can be used by other subsystems
- **Fault Tolerance**: Service failures are isolated with graceful degradation

## Data Layer and Migrations

The SeedCore system uses a comprehensive database schema that supports both traditional task management and advanced graph-based operations. The database layer is designed to be scalable, maintainable, and capable of handling complex relationships between tasks, agents, organs, and resources.

### Migration Overview

The database schema has evolved through 19 comprehensive migrations, establishing a robust foundation for distributed task management, graph-based AI, runtime coordination, policy governance, and unified memory systems:

| Migration | Purpose | Key Components |
|-----------|---------|----------------|
| 001-006 | **Task Management** | Task queue, status tracking, lease management |
| 007 | **Task Schema Enhancements** | JSONB conversion, check constraints, optimized indexing |
| 008-009 | **HGNN Architecture** | Two-layer graph schema, node mapping, edge relationships |
| 010-011 | **Facts System** | Text-based fact storage, task-fact integration |
| 012 | **Runtime Registry** | Instance management, cluster coordination |
| 013 | **PKG Core** | Policy snapshots, subtask types, rules, conditions, emissions, artifacts |
| 014 | **PKG Operations** | Canary deployments, validation, promotions, device coverage |
| 015 | **PKG Views & Functions** | Helper views, integrity checks, promotion functions |
| 016 | **Fact-PKG Integration** | Foreign keys, temporal modeling, structured triple conversion |
| 017 | **PKG Snapshot Scoping** | Snapshot_id columns, reproducible runs, multi-world isolation |
| 117 | **Unified Cortex Memory** | Unified memory view, embedding views, snapshot-aware semantic search |
| 118 | **Task Outbox Hardening** | Availability scheduling, retry tracking, exponential backoff |
| 119 | **Task Router Telemetry** | OCPS signals, surprise scores, routing decision tracking |

### Runtime Registry Database Schema

The runtime registry extends the existing database schema with two new tables:

#### Cluster Metadata Table
```sql
CREATE TABLE cluster_metadata (
  id            INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  current_epoch UUID NOT NULL,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### Instance Registry Table
```sql
CREATE TABLE registry_instance (
  instance_id    UUID PRIMARY KEY,
  logical_id     TEXT NOT NULL,
  cluster_epoch  UUID NOT NULL,
  status         InstanceStatus NOT NULL DEFAULT 'starting',
  actor_name     TEXT,
  serve_route    TEXT,
  node_id        TEXT,
  ip_address     INET,
  pid            INT,
  started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  stopped_at     TIMESTAMPTZ,
  last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Migration Process

The runtime registry is integrated through a systematic migration process:

#### Migration 011: Runtime Registry Tables
- Creates `cluster_metadata` table for epoch management
- Creates `registry_instance` table for actor tracking
- Defines `InstanceStatus` enum type
- Creates indexes for performance optimization
- Implements monitoring views (`active_instances`, `active_instance`)

#### Migration 012: Runtime Registry Functions
- Implements `set_current_epoch()` with advisory locking
- Implements `register_instance()` for actor registration
- Implements `set_instance_status()` for lifecycle management
- Implements `beat()` for heartbeat updates
- Implements `expire_stale_instances()` for cleanup

#### Database Initialization Script
The `init_full_db.sh` script orchestrates the complete database setup:

```bash
# Migration 011: Runtime registry tables & views
echo "⚙️  Running migration 011: Runtime registry tables & views..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_011" "$POSTGRES_POD:/tmp/011_add_runtime_registry.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/011_add_runtime_registry.sql"

# Migration 012: Runtime registry functions
echo "⚙️  Running migration 012: Runtime registry functions..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_012" "$POSTGRES_POD:/tmp/012_runtime_registry_functions.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/012_runtime_registry_functions.sql"
```

### Repository Integration

The runtime registry integrates with the existing repository pattern:

#### AgentGraphRepository
- **Async Connection Pooling**: Uses `asyncpg` for high-performance database access
- **Lazy Initialization**: Connection pools created on first use
- **Error Handling**: Comprehensive error handling with detailed logging
- **Transaction Safety**: All operations wrapped in proper transactions

#### Database Connection Management
- **Connection Pooling**: Min 1, max 10 connections per repository
- **DSN Configuration**: Uses `PG_DSN` from `database.py` configuration
- **Health Monitoring**: Connection health tracked via heartbeat operations
- **Graceful Degradation**: Bounded backoff on connection failures

### Schema Verification

The initialization script includes comprehensive schema verification:

```bash
echo "📊 Runtime registry tables:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ cluster_metadata"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ registry_instance"

echo "📊 Runtime registry views:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ active_instances"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ active_instance"

echo "📊 Runtime registry functions:"
for fn in set_current_epoch register_instance set_instance_status beat expire_stale_instances expire_old_epoch_instances
do
  kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\df+ $fn" || true
done
```

### Task Management System (Migrations 001-006)

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

### Task Schema Enhancements (Migration 007)

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

### HGNN Architecture (Migrations 008-009)

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

### Facts Management System (Migrations 010-011)

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

### Summary of Relevant Changes

- **001-006 Task Management**: Complete coordinator-dispatcher task queue with lease management, retry logic, and drift scoring
- **007 Task Schema Enhancements**: JSONB conversion, check constraints, and optimized indexing for performance
- **008-009 HGNN Architecture**: Two-layer graph schema with node mapping and vector embeddings with ANN indexing
- **010-011 Facts System**: Text-based fact storage with full-text search capabilities and task integration
- **012 Runtime Registry**: Epoch-based cluster management with actor lifecycle tracking and heartbeat monitoring
- **013-017 PKG Policy Governance**: Versioned policy snapshots, rule-based emissions, canary deployments, validation system, and snapshot scoping
- **117 Unified Cortex Memory**: Three-tier memory architecture with snapshot-aware semantic search
- **118 Task Outbox Hardening**: Transactional outbox pattern with availability scheduling and retry tracking
- **119 Task Router Telemetry**: OCPS signal tracking, surprise scores, and routing decision observability
- **Embeddings Upsert**: `graph_embeddings` accepts `emb` vectors via JSONB→vector cast; props stored as JSONB, with conflict updates keeping existing values when new values are null

## Verification Workflow

The script `scripts/host/verify_seedcore_architecture.py` validates end-to-end health and new capabilities:

- Confirms Serve apps and dispatcher actors, with improved compatibility for Ray 2.32+ handle responses.
- Verifies schema (migrations applied), HGNN graph structure, and facts system.
- Submits optional HGNN graph task scenario via DB function `create_graph_rag_task_v2`; controlled by `VERIFY_HGNN_TASK`.
- Enhancements include latency/heartbeat metrics, lease-aware task status checks, and safer coordinator debugging calls.
