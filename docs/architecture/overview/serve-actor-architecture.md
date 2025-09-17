# Serve ↔ Actor Architecture Overview

This document provides a comprehensive overview of the SeedCore system architecture, specifically focusing on the mapping between Ray Serve applications and Ray Actors, and how they work together to form a distributed, intelligent organism.

## Table of Contents

- [System Overview](#system-overview)
- [Serve Applications (Logical Apps)](#serve-applications-logical-apps)
- [Serve Deployments → Ray Actors](#serve-deployments--ray-actors)
- [Control Plane Actors](#control-plane-actors)
- [System Relationships](#system-relationships)
- [Architecture Diagram](#architecture-diagram)
- [Health Indicators](#health-indicators)
- [Scaling and Distribution](#scaling-and-distribution)
 - [Task Taxonomy and Routing](#task-taxonomy-and-routing)
 - [HGNN Graph and GraphDispatcher](#hgnn-graph-and-graphdispatcher)
 - [Graph Embeddings Pipeline](#graph-embeddings-pipeline)
 - [Facts, Resources, and Agent Layer Integration](#facts-resources-and-agent-layer-integration)
 - [Resiliency: Drift Detection and Circuit Breakers](#resiliency-drift-detection-and-circuit-breakers)
 - [Data Layer and Migrations](#data-layer-and-migrations)
 - [Verification Workflow](#verification-workflow)

## System Overview

SeedCore implements a distributed, intelligent organism architecture using Ray Serve for service orchestration and Ray Actors for distributed computation. The system is designed to be scalable, fault-tolerant, and capable of handling complex cognitive workloads.

The architecture follows a **microservices pattern** where each logical service is deployed as a Ray Serve application, which in turn spawns one or more Ray Actors to handle the actual computation and state management.

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

### 2. Cognitive → CognitiveService

- **ServeDeployment**: `CognitiveService`
- **Actors**: `ServeReplica:cognitive:CognitiveService`
- **Replicas**: `2 RUNNING`
- **Ray Actor IDs**: Actor 1 and Actor 4
- **Purpose**: Parallel workers for reasoning and planning tasks
- **Distribution**: Replicas are distributed across different Ray nodes for redundancy

### 3. Coordinator → Coordinator

- **ServeDeployment**: `Coordinator`
- **Replicas**: `1 RUNNING`
- **Ray Actor ID**: Actor 5
- **Purpose**: Global coordination, task routing, OCPS valve, and HGNN escalation
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

### 6. Organism → OrganismManager

- **ServeDeployment**: `OrganismManager`
- **Replicas**: `1 RUNNING`
- **Ray Actor ID**: Actor 8
- **Purpose**: Local organ management, agent distribution, and direct task execution
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

#### Coordinator & OrganismManager
- **Coordinator** (Actor 5) handles global task routing and coordination
- Uses OCPS valve for drift detection and escalation decisions
- Routes tasks to **OrganismManager** for local execution
- **OrganismManager** (Actor 8) manages organ lifecycle and agent distribution

#### CognitiveService Integration
- **CognitiveService** (Actors 1 & 4) provides reasoning and planning capabilities
- Called by **Coordinator** for HGNN decomposition and escalation
- Serves as the "Cognitive organ" for complex task planning

#### Coordinator Service Flow
- Receives tasks from Queue Dispatcher
- Applies OCPS valve for fast-path vs escalation decisions
- Routes simple tasks directly to OrganismManager
- Escalates complex tasks through CognitiveService for planning

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

**Routing Decision**: Coordinator determines task routing based on:
- OCPS valve drift detection (fast-path vs escalation)
- Task type and complexity
- Current system load and escalation capacity
- Available organs and agent capabilities

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
Coordinator Service
├─ OCPS Valve Check (fast-path vs escalation)
│
├─ Fast Path: Direct to OrganismManager
│   └─ Organ (container) → Tier0MemoryManager → RayAgent
│
└─ Escalation Path: CognitiveService → OrganismManager
   ├─ HGNN decomposition (CognitiveService)
   ├─ Plan validation and execution
   └─ Organ (container) → Tier0MemoryManager → RayAgent
       ├─ Execute task
       │    ├─ Memory lookup: Mw → Mlt → Mfb
       │    ├─ Cognitive reasoning (optional)
       │    └─ Produce result
       │
       ├─ Update performance + energy metrics
       ├─ Emit heartbeat
       └─ Possibly archive/log to Mlt & Mfb
```

### Key Architectural Points

- **Coordinator** = Global coordination, OCPS valve, routing decisions, HGNN escalation
- **OrganismManager** = Local organ management, agent distribution, direct execution
- **Tier0MemoryManager** = Registry/selector utility, not a Ray actor
- **Organ** = Wrapper container, creates and supervises RayAgents
- **RayAgent** = Real worker, stateful, owns private memory, cognitive access, telemetry
- **Memory Layers**:
  - **Mw** = Fast, volatile working memory
  - **Mlt** = Durable long-term store
  - **Mfb** = Rare, high-salience flashbulb events

## Architecture Diagram

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

## Task Taxonomy and Routing

SeedCore routes tasks based on type, complexity, and drift signals. The `Coordinator` maintains a minimal `RoutingDirectory` that maps task types to the appropriate organ/dispatcher. Recent migrations introduced graph, facts, resources, and agent-layer task families.

### Routing Directory (selected rules)

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
- Reset semantics: accumulator resets only on escalation to avoid under-escalation and to build evidence over time.
- Concurrency controls and latency SLOs guide escalation throughput.

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

## Data Layer and Migrations

Summary of relevant changes:

- **007 HGNN Graph Schema**: Functions `create_graph_embed_task_v2` and `create_graph_rag_task_v2` accept optional agent/organ IDs. Parameter names changed to `p_agent_id`/`p_organ_id` to remove ambiguity with column names in `ON CONFLICT` clauses.
- **008 Agent Layer**: Registries for models, policies, services, and skills with corresponding management tasks.
- **009 Facts System**: Fact entities and graph integration; fact-centric graph tasks and utilities.
- **Embeddings Upsert**: `graph_embeddings` accepts `emb` vectors via JSONB→vector cast; props stored as JSONB, with conflict updates keeping existing values when new values are null.

## Verification Workflow

The script `scripts/host/verify_seedcore_architecture.py` validates end-to-end health and new capabilities:

- Confirms Serve apps and dispatcher actors, with improved compatibility for Ray 2.32+ handle responses.
- Verifies schema (migrations applied), HGNN graph structure, and facts system.
- Submits optional HGNN graph task scenario via DB function `create_graph_rag_task_v2`; controlled by `VERIFY_HGNN_TASK`.
- Enhancements include latency/heartbeat metrics, lease-aware task status checks, and safer coordinator debugging calls.
