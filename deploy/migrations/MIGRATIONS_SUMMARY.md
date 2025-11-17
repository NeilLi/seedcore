# Database Migrations Summary

## Overview

This document summarizes the current state of database migrations for SeedCore, providing a comprehensive view of the schema evolution and helping plan future feature development.

**Total Migrations**: 15  
**Last Updated**: Migration 018  
**Database System**: PostgreSQL with extensions (vector, pgvector, pgcrypto)

---

## Migration Timeline

### Phase 1: Core Task Management (001-002)

#### 001_create_tasks_table.sql
**Purpose**: Foundation for Coordinator + Dispatcher system  
**Key Components**:
- `tasks` table with UUID primary key
- `taskstatus` enum (created, queued, running, completed, failed, cancelled, retry)
- Core columns: status, attempts, locked_by, locked_at, run_after, type, domain, drift_score
- Lease columns: owner_id, lease_expires_at, last_heartbeat
- JSONB columns: params, result
- Indexes for performance (status, type, domain, routing, lease tracking)
- Routing-specific JSONB path indexes for filtering
- `graph_tasks` view for monitoring graph-related tasks
- Helper functions: `create_graph_embed_task()`, `create_graph_rag_task()` (with optional agent/organ parameters)
- `cleanup_stale_running_tasks()` function for emergency recovery
- Auto-update trigger for `updated_at`

**Dependencies**: None  
**Used By**: All subsequent task-related migrations

**Note**: This migration consolidates functionality from previous migrations 003-006, including:
- Graph task types and helper functions
- Task lease columns and stale task recovery
- Task schema enhancements and routing indexes

---

#### 002_graph_embeddings.sql
**Purpose**: Enable vector similarity search with separate dimension tables  
**Key Components**:
- Requires `vector` and `pgcrypto` extensions
- `graph_embeddings_128` table with VECTOR(128) embeddings
- `graph_embeddings_1024` table with VECTOR(1024) embeddings
- IVFFlat indexes for ANN search on both tables
- node_id as BIGINT (DGL-compatible)
- Supports labels and properties as JSONB
- Migration logic from old `graph_embeddings` table (if exists)
- Triggers for auto-updating `updated_at` timestamps

**Dependencies**: PostgreSQL vector extension  
**Used By**: 007 (HGNN integration), 017 (task embedding support)

---

### Phase 2: HGNN (Heterogeneous Graph Neural Network) Schema (007-010)

#### 007_hgnn_graph_schema.sql
**Purpose**: Two-layer HGNN architecture (Task + Agent/Organ layers)  
**Key Components**:

**Node Mapping Infrastructure**:
- `graph_node_map` - Canonical BIGINT→UUID/TEXT mapping for DGL
- Node types: task, agent, organ, artifact, capability, memory_cell
- Helper functions: `ensure_task_node()`, `ensure_agent_node()`, `ensure_organ_node()`

**Registries**:
- `agent_registry` - Agent metadata (TEXT keys)
- `organ_registry` - Organ metadata with agent references

**Task-Layer Resources**:
- `artifact` - Files, S3 objects, vectors, blobs
- `capability` - Named capabilities (summarize, embed, plan-route)
- `memory_cell` - Scoped memory with versioning

**Task-Layer Edges**:
- `task_depends_on_task` - Task dependencies
- `task_produces_artifact` - Task outputs
- `task_uses_capability` - Required capabilities
- `task_reads_memory` - Memory reads
- `task_writes_memory` - Memory writes

**Agent-Layer Edges**:
- `organ_provides_capability` - Organ capabilities
- `agent_owns_memory_cell` - Agent memory ownership

**Cross-Layer Edges**:
- `task_executed_by_organ` - Task execution assignment
- `task_owned_by_agent` - Task ownership

**Views**:
- `task_embeddings_128` - Join tasks with 128d embeddings via graph_node_map
- `task_embeddings_1024` - Join tasks with 1024d embeddings via graph_node_map
- `hgnn_edges` - Flattened heterogeneous edges for DGL export

**Enhanced Task Functions**:
- `create_graph_embed_task()` - With optional agent/organ binding parameters
- `create_graph_rag_task()` - With optional agent/organ binding parameters
- `backfill_task_nodes()` - Populate node map

**Dependencies**: 001, 002 (graph_embeddings)  
**Used By**: 008, 010

---

#### 008_hgnn_agent_layer.sql
**Purpose**: Complete agent-layer node types and relationships  
**Key Components**:

**New Dimension Tables**:
- `model` - LLM/ML models (TEXT keys)
- `policy` - Governance policies
- `service` - External services
- `skill` - Agent skills/capabilities

**Agent-Layer Relationships**:
- `agent_member_of_organ` - Agent-organ membership
- `agent_collab_agent` - Agent collaboration edges
- `organ_provides_skill` - Skill provision
- `organ_uses_service` - Service dependencies
- `organ_governed_by_policy` - Policy governance
- `agent_uses_model` - Model usage

**Helper Functions**:
- `ensure_model_node()`
- `ensure_policy_node()`
- `ensure_service_node()`
- `ensure_skill_node()`

**Extended Views**:
- Updates `hgnn_edges` with 8 new edge types

**Dependencies**: 007  
**Used By**: 010

---

#### 009_create_facts_table.sql
**Purpose**: Knowledge base for fact management  
**Key Components**:
- `facts` table with UUID keys
- Full-text search on `text` column (GIN index)
- `tags` array with GIN index
- `meta_data` JSONB with GIN index
- Sample facts for testing

**Dependencies**: None  
**Used By**: 010

---

#### 010_task_fact_integration.sql
**Purpose**: Integrate facts into HGNN (memory-action loop completion)  
**Key Components**:
- `ensure_fact_node()` helper function
- `task_reads_fact` - Task reads from facts
- `task_produces_fact` - Task generates facts
- Updates `hgnn_edges` view with 2 new fact edge types

**Dependencies**: 007, 008, 009  
**Used By**: Fact-aware task processing

---

### Phase 3: Runtime Registry (011-012)

#### 011_add_runtime_registry.sql
**Purpose**: Cluster instance tracking and service discovery  
**Key Components**:

**Cluster Management**:
- `cluster_metadata` - Single-row epoch tracking
- `InstanceStatus` enum (starting, alive, draining, dead)

**Instance Registry**:
- `registry_instance` - Runtime instance tracking
- Fields: instance_id, logical_id, cluster_epoch, status, actor_name, serve_route
- Node metadata: node_id, ip_address, pid
- Heartbeat tracking: started_at, stopped_at, last_heartbeat

**Views**:
- `active_instances` - All alive instances in current epoch
- `active_instance` - Best instance per logical_id (for named actors)

**Indexes**:
- logical_id, epoch+status, status+heartbeat, logical+status+epoch

**Dependencies**: None  
**Used By**: 012

---

#### 012_runtime_registry_functions.sql
**Purpose**: Runtime registry operations  
**Key Components**:

**Epoch Management**:
- `set_current_epoch()` - Advisory lock-protected epoch rotation

**Instance Lifecycle**:
- `register_instance()` - Register/upsert instance with heartbeat
- `set_instance_status()` - Update instance status
- `beat()` - Lightweight heartbeat update

**Cleanup Functions**:
- `expire_stale_instances()` - Mark stale instances as dead (15s default)
- `expire_old_epoch_instances()` - Clean up old epoch instances

**Dependencies**: 011  
**Used By**: Runtime service discovery, health monitoring

---

### Phase 4: PKG (Package) System (013-016)

#### 013_pkg_core.sql
**Purpose**: PKG core catalog system for package snapshots and policy rules  
**Key Components**:
- `pkg_snapshots` - Package snapshots with environment tracking
- `pkg_subtask_types` - Subtask type definitions
- `pkg_policy_rules` - Policy rules for governance
- `pkg_rule_conditions` - Rule conditions with operators
- `pkg_rule_emissions` - Rule emissions/outputs
- `pkg_snapshot_artifacts` - Artifacts associated with snapshots
- Enums: `pkg_env`, `pkg_engine`, `pkg_condition_type`, `pkg_operator`, `pkg_relation`, `pkg_artifact_type`

**Dependencies**: None  
**Used By**: 014, 015, 016

---

#### 014_pkg_ops.sql
**Purpose**: PKG operations and deployment tracking  
**Key Components**:
- `pkg_deployments` - Deployment tracking
- `pkg_facts` - PKG-related facts
- `pkg_validation_fixtures` - Validation test fixtures
- `pkg_validation_runs` - Validation run results
- `pkg_promotions` - Snapshot promotion tracking
- `pkg_device_versions` - Device version tracking

**Dependencies**: 013  
**Used By**: 015, 016

---

#### 015_pkg_views_functions.sql
**Purpose**: PKG views and helper functions  
**Key Components**:
- `pkg_active_artifact` view - Active artifact per environment
- `pkg_rules_expanded` view - Rules with expanded conditions and emissions
- `pkg_deployment_coverage` view - Deployment coverage tracking
- `pkg_check_integrity()` - Integrity validation function
- `pkg_active_snapshot_id()` - Get active snapshot ID
- `pkg_promote_snapshot()` - Promote snapshot function

**Dependencies**: 013, 014  
**Used By**: 016

---

#### 016_fact_pkg_integration.sql
**Purpose**: Integrate facts system with PKG for temporal facts and policy governance  
**Key Components**:
- Enhanced `facts` table with PKG integration fields
- Temporal fact support with validity periods
- Policy governance integration
- Eventizer support for fact processing
- `active_temporal_facts` view for efficient temporal queries
- Helper functions: `get_facts_by_subject()`, `cleanup_expired_facts()`, `get_fact_statistics()`

**Dependencies**: 009, 013, 014, 015  
**Used By**: Fact-aware task processing with PKG governance

---

### Phase 5: Task Embedding & Outbox (017-018)

#### 017_task_embedding_support.sql
**Purpose**: Support for task embeddings with separate 128d and 1024d tables  
**Key Components**:
- Views: `task_embeddings_primary_128`, `task_embeddings_primary_1024`
- Views: `task_embeddings_stale_128`, `task_embeddings_stale_1024`
- Views: `tasks_missing_embeddings_128`, `tasks_missing_embeddings_1024`
- Backfill functions for populating embeddings
- Integration with `graph_node_map` for node ID mapping

**Dependencies**: 001, 002, 007  
**Used By**: Task embedding workflows

---

#### 018_task_outbox_hardening.sql
**Purpose**: Enhance task outbox pattern with availability tracking  
**Key Components**:
- `available_at` column for task availability scheduling
- Enhanced `attempts` tracking
- Indexes for outbox queries
- Improved task scheduling support

**Dependencies**: 001  
**Used By**: Task outbox pattern implementations

---

## Schema Architecture Summary

### Core Node Types

| Node Type | Table | ID Type | Purpose |
|-----------|-------|---------|---------|
| task | tasks | UUID | Work units in the system |
| agent | agent_registry | TEXT | Autonomous agents |
| organ | organ_registry | TEXT | Agent sub-components |
| artifact | artifact | UUID | Data/files produced by tasks |
| capability | capability | UUID | Named capabilities/skills |
| memory_cell | memory_cell | UUID | Versioned memory storage |
| fact | facts | UUID | Knowledge base entries |
| model | model | TEXT | LLM/ML models |
| policy | policy | TEXT | Governance rules |
| service | service | TEXT | External services |
| skill | skill | TEXT | Agent skills |
| instance | registry_instance | UUID | Runtime instances |

### Edge Types (HGNN)

#### Task Layer (Intra-layer)
- `task → task` (depends_on) - Task dependencies
- `task → artifact` (produces) - Outputs
- `task → capability` (uses) - Required capabilities
- `task → memory_cell` (reads/writes) - Memory access
- `task → fact` (reads/produces) - Knowledge access

#### Agent Layer (Intra-layer)
- `agent → agent` (collab) - Collaboration
- `agent → organ` (member_of) - Membership
- `organ → skill` (provides) - Skill provision
- `organ → service` (uses) - Service dependencies
- `organ → policy` (governed_by) - Governance
- `organ → capability` (provides) - Capability provision
- `agent → model` (uses) - Model usage
- `agent → memory_cell` (owns) - Memory ownership

#### Cross-Layer
- `task → organ` (executed_by) - Execution assignment
- `task → agent` (owned_by) - Task ownership

### Key Views

| View | Purpose | Dependencies |
|------|---------|--------------|
| graph_tasks | Monitor graph task types | tasks |
| task_embeddings_128 | Join tasks with 128d embeddings | tasks + graph_node_map + graph_embeddings_128 |
| task_embeddings_1024 | Join tasks with 1024d embeddings | tasks + graph_node_map + graph_embeddings_1024 |
| task_embeddings_primary_128 | Primary 128d embeddings for tasks | tasks + graph_node_map + graph_embeddings_128 |
| task_embeddings_primary_1024 | Primary 1024d embeddings for tasks | tasks + graph_node_map + graph_embeddings_1024 |
| task_embeddings_stale_128 | Stale 128d embeddings | tasks + graph_node_map + graph_embeddings_128 |
| task_embeddings_stale_1024 | Stale 1024d embeddings | tasks + graph_node_map + graph_embeddings_1024 |
| tasks_missing_embeddings_128 | Tasks missing 128d embeddings | tasks + graph_node_map + graph_embeddings_128 |
| tasks_missing_embeddings_1024 | Tasks missing 1024d embeddings | tasks + graph_node_map + graph_embeddings_1024 |
| hgnn_edges | Flattened edges for DGL | All edge tables + node mapping |
| active_instances | Current alive instances | registry_instance + cluster_metadata |
| active_instance | Best instance per logical_id | registry_instance + cluster_metadata |
| active_temporal_facts | Active temporal facts | facts |
| pkg_active_artifact | Active PKG artifact per env | pkg_snapshots + pkg_snapshot_artifacts |
| pkg_rules_expanded | PKG rules with conditions/emissions | pkg_policy_rules + pkg_rule_conditions + pkg_rule_emissions |
| pkg_deployment_coverage | PKG deployment coverage | pkg_deployments |

---

## Database Features & Extensions

### Required Extensions
- `vector` (pgvector) - Vector similarity search
- `pgcrypto` - UUID generation and cryptographic functions
- Advisory locks - Epoch management coordination

### Index Types Used
- B-tree - Standard indexes (timestamps, UUIDs, status)
- GIN - Full-text search, JSONB, arrays, tags
- IVFFlat - Vector ANN search (with lists parameter)

### Advanced Features
- JSONB for flexible metadata
- Array types for tags
- Vector embeddings (128 and 1024 dimensions)
- Full-text search (tsvector)
- Triggers for auto-timestamp updates
- Enum types for type safety (taskstatus, InstanceStatus, PKG enums)
- Views for common queries
- Foreign key constraints with CASCADE/RESTRICT
- Composite indexes for complex queries
- Partial indexes with WHERE clauses
- Advisory locks for distributed coordination
- Temporal fact support with validity periods

---

## Dependency Graph

```
001 (tasks - consolidated)
├── 002 (graph_embeddings - separate 128d/1024d tables)
│   ├── 007 (HGNN schema)
│   │   ├── 008 (agent layer)
│   │   │   └── 010 (fact integration)
│   │   └── 010 (fact integration)
│   └── 017 (task embedding support)
│
009 (facts)
└── 010 (fact integration)
    └── 016 (fact PKG integration)

011 (runtime registry)
└── 012 (runtime functions)

013 (PKG core)
├── 014 (PKG ops)
│   └── 015 (PKG views/functions)
│       └── 016 (fact PKG integration)
└── 015 (PKG views/functions)

018 (task outbox hardening)
└── 001 (tasks)
```

---

## Recommendations for New Features

### 1. When Adding New Node Types
- Add to appropriate registry table with TEXT or UUID keys
- Create `ensure_<node_type>_node()` function in `graph_node_map`
- Add relevant edge tables
- Update `hgnn_edges` view to include new edges
- Consider indexes for common traversal patterns

### 2. When Adding New Task Types
- Use existing `tasks` table structure
- Add task type to `type` column
- Optionally create convenience functions like `create_*_task()`
- Consider adding to `graph_tasks` view filter if graph-related

### 3. When Adding New Relationships
- Create edge table with composite unique index
- Add foreign keys with appropriate ON DELETE behavior
- Add indexes for both directions of traversal
- Update `hgnn_edges` view with new edge type
- Use naming convention: `<src>_<relation>_<dst>`

### 4. When Adding New Registry Types
- Follow the pattern from `agent_registry`/`organ_registry`
- Include: created_at, updated_at, props (JSONB)
- Add update trigger for updated_at
- Consider TEXT vs UUID keys based on natural naming

### 5. Migration Best Practices
- Use `IF NOT EXISTS` for idempotency
- Use `DO $$` blocks for conditional logic
- Add COMMENT ON for documentation
- Include rollback strategy (BEGIN/COMMIT blocks)
- Test against existing data
- Add NOTICE messages for debugging
- Number migrations sequentially (013, 014, etc.)

### 6. Performance Considerations
- Add indexes for foreign keys used in JOINs
- Use composite indexes for multi-column WHERE clauses
- Consider partial indexes with WHERE clauses for filtered queries
- Monitor `hgnn_edges` view performance (may need materialization)
- Use EXPLAIN ANALYZE to validate query plans

### 7. HGNN Extension Opportunities
**Potential new node types**:
- `user` - End users
- `resource` - Compute/storage resources
- `event` - System events
- `metric` - Monitoring metrics
- `workflow` - Predefined workflows
- `dataset` - Training/inference data

**Potential new edge types**:
- `task → resource` (allocates) - Resource allocation
- `agent → user` (serves) - User association
- `workflow → task` (contains) - Workflow steps
- `fact → fact` (derives_from) - Fact provenance
- `model → dataset` (trained_on) - Training data

### 8. Runtime Registry Extensions
**Potential additions**:
- Resource capacity tracking (CPU, memory, GPU)
- Instance groups/replicas for scaling
- Health check status and failure reasons
- Performance metrics per instance
- Version tracking for rolling updates
- Configuration snapshots

---

## Schema Statistics (as of Migration 018)

| Category | Count | Notes |
|----------|-------|-------|
| Tables | 35+ | Including dimension tables, PKG tables, edge tables |
| Views | 15+ | Monitoring, DGL export, PKG views, embedding views |
| Functions | 30+ | Helpers, lifecycle, cleanup, PKG functions, fact functions |
| Triggers | 15+ | Auto-update timestamps |
| Indexes | 80+ | B-tree, GIN, IVFFlat, composite, partial |
| Enum Types | 8+ | taskstatus, InstanceStatus, PKG enums (env, engine, condition_type, operator, relation, artifact_type) |
| Edge Tables | 16 | HGNN relationships |

---

## Next Migration Planning (019+)

### Potential Future Migrations

#### 019: Task Priority & Scheduling Enhancement
- Add priority levels (critical, high, normal, low)
- Scheduling constraints (time windows, resource requirements)
- Task pools/queues for different dispatcher types

#### 020: Observability & Metrics
- Task execution metrics (duration, resource usage)
- Agent performance tracking
- Fact quality scores
- Embedding quality metrics

#### 021: Workflow Templates
- Predefined task workflows
- Workflow versioning
- Workflow execution tracking

#### 022: Resource Management
- Resource capacity tracking
- Resource reservation
- Resource usage accounting

#### 023: Advanced Fact Features
- Fact versioning
- Fact conflicts and resolution
- Fact sources and provenance chains
- Fact confidence scores

#### 024: Agent Capabilities Enhancement
- Capability requirements (min versions)
- Capability discovery
- Dynamic capability registration

#### 025: Audit & Compliance
- Audit log table
- Change tracking
- Compliance policy enforcement

#### 026: Multi-tenancy Support
- Tenant isolation
- Tenant-scoped resources
- Tenant quotas and limits

---

## Migration Application Guide

### Initial Setup
```bash
# From project root
cd deploy/migrations

# Apply all migrations in order
for file in *.sql; do
  psql -h localhost -U seedcore -d seedcore_db -f "$file"
done
```

### Single Migration
```bash
psql -h localhost -U seedcore -d seedcore_db -f 018_task_outbox_hardening.sql
```

### Verification Queries
```sql
-- Check all tables
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'public' ORDER BY table_name;

-- Check HGNN edge types
SELECT DISTINCT edge_type FROM hgnn_edges;

-- Check task status distribution
SELECT status, COUNT(*) FROM tasks GROUP BY status;

-- Check active instances
SELECT * FROM active_instances;

-- Check node type distribution
SELECT node_type, COUNT(*) FROM graph_node_map GROUP BY node_type;
```

---

## Contacts & Resources

- **Architecture Docs**: `/docs/ARCHITECTURE/`
- **Operation Manual**: `/docs/OPERATION-MANUAL.MD`
- **Migration Source**: `/deploy/migrations/`
- **Test Setup**: `setup_test_env.sh`

---

*Last Updated: December 2024*  
*Migration Version: 018*



