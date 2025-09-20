# Kubernetes Database Initialization Guide

## Problem
The SeedCore API is failing to start because the required database tables don't exist:
```
asyncpg.exceptions.UndefinedTableError: relation "holons" does not exist
```

## Solution
You need to initialize the database schemas by running the initialization scripts in your running database pods. The system now includes comprehensive database migrations and advanced schema features.

## Database Architecture Overview

The SeedCore system now includes a comprehensive database architecture with:

### **Core Tables**
- **holons**: Vector-based holon storage with HNSW indexing
- **tasks**: Complete coordinator-dispatcher task queue with lease management
- **facts**: Text-based fact storage with full-text search capabilities

### **HGNN (Heterogeneous Graph Neural Network) Architecture**
- **graph_node_map**: Node ID mapping for graph operations
- **agent_registry**: Agent node definitions and metadata
- **organ_registry**: Organ node definitions and metadata
- **Resource tables**: artifact, capability, memory_cell
- **Edge tables**: task_* relationships for complex graph operations

### **Runtime Registry System**
- **cluster_metadata**: Cluster epoch tracking
- **registry_instance**: Instance management and health monitoring
- **Active views**: Real-time instance status and load balancing

## Quick Fix (Manual Steps)

### 1. Initialize PostgreSQL with Full Migration Suite (Recommended)

```bash
# Find your PostgreSQL pod
kubectl get pods -n seedcore-dev -l app=postgresql

# Run the comprehensive database initialization
cd /path/to/seedcore
./deploy/init_full_db.sh

# Or specify a different namespace
NAMESPACE=your-namespace ./deploy/init_full_db.sh
```

### 2. Initialize PostgreSQL with Basic Setup (Legacy)

```bash
# Find your PostgreSQL pod
kubectl get pods -n seedcore-dev -l app=postgresql

# Copy the basic initialization script to the pod
kubectl cp docker/setup/init_pgvector.sql seedcore-dev/[POSTGRES_POD_NAME]:/tmp/init_pgvector.sql

# Run the basic initialization script
kubectl exec -n seedcore-dev [POSTGRES_POD_NAME] -- psql -U postgres -d postgres -f /tmp/init_pgvector.sql
```

### 3. Initialize MySQL (Optional)

```bash
# Find your MySQL pod
kubectl get pods -n seedcore-dev -l app=mysql

# Copy the initialization script to the pod
kubectl cp docker/setup/init_mysql.sql seedcore-dev/[MYSQL_POD_NAME]:/tmp/init_mysql.sql

# Run the initialization script
kubectl exec -n seedcore-dev [MYSQL_POD_NAME] -- mysql -u seedcore -ppassword seedcore < /tmp/init_mysql.sql
```

### 4. Initialize Neo4j (Optional)

```bash
# Find your Neo4j pod
kubectl get pods -n seedcore-dev -l app=neo4j

# Copy the initialization script to the pod
kubectl cp docker/setup/init_neo4j.cypher seedcore-dev/[NEO4J_POD_NAME]:/tmp/init_neo4j.cypher

# Run the initialization script
kubectl exec -n seedcore-dev [NEO4J_POD_NAME] -- cypher-shell -u neo4j -p password -f /tmp/init_neo4j.cypher
```

## Automated Fix

### Full Database Initialization (Recommended)

Use the comprehensive migration-based script:

```bash
# Run the full database initialization with all 12 migrations
cd /path/to/seedcore
./deploy/init_full_db.sh

# Or specify a different namespace
NAMESPACE=your-namespace ./deploy/init_full_db.sh

# Or set environment variables
export NAMESPACE=your-namespace
export DB_NAME=your-db-name
export DB_USER=your-db-user
export DB_PASS=your-db-password
./deploy/init_full_db.sh
```

### Basic Database Initialization (Legacy)

Use the basic initialization script:

```bash
# Run the basic initialization script
./deploy/init_basic_db.sh

# Or specify a different namespace
./deploy/init_basic_db.sh your-namespace
```

## Database Migration System

The full initialization script runs 12 comprehensive migrations:

### **Migration 001-006: Task Management System**
- **001**: Create tasks table with status tracking
- **002**: Graph embeddings with vector support
- **003**: Graph task types and helper functions
- **004**: Fix taskstatus enum to match code expectations
- **005**: Consolidate and fix task schema (CRITICAL FIX)
- **006**: Add task lease columns for stale task recovery

### **Migration 007-008: HGNN Architecture**
- **007**: HGNN base graph schema (task layer)
- **008**: HGNN agent/organ layer + relations

### **Migration 009-010: Facts Management**
- **009**: Create facts table with full-text search
- **010**: Task-Fact integration + view update

### **Migration 011-012: Runtime Registry**
- **011**: Runtime registry tables & views
- **012**: Runtime registry functions

## What the Scripts Create

### PostgreSQL (Full Migration Suite)

#### **Core Extensions**
- **pgcrypto**: For UUID generation and cryptographic functions
- **vector**: For vector similarity search and embeddings

#### **Core Tables**
- **holons**: Vector-based holon storage with HNSW indexing
  - `id`: Serial primary key
  - `uuid`: Unique UUID for each holon
  - `embedding`: 768-dimensional vector for similarity search
  - `meta`: JSONB metadata
  - `created_at`: Timestamp
- **tasks**: Complete coordinator-dispatcher task queue
  - `id`: UUID primary key
  - `status`: Task status enum (created, queued, running, completed, failed, cancelled, retry)
  - `attempts`: Retry counter
  - `locked_by`: Task lease management
  - `locked_at`: Lease timestamp
  - `run_after`: Scheduled execution time
  - `type`: Task type classification
  - `params`: JSONB task parameters
  - `result`: JSONB task results
  - `error`: Error messages
- **facts**: Text-based fact storage with full-text search
  - `id`: UUID primary key
  - `text`: Fact content
  - `tags`: Array of tags
  - `meta_data`: JSONB metadata
  - `created_at`/`updated_at`: Timestamps

#### **HGNN (Heterogeneous Graph Neural Network) Architecture**
- **graph_node_map**: Node ID mapping for graph operations
- **agent_registry**: Agent node definitions and metadata
- **organ_registry**: Organ node definitions and metadata
- **Resource tables**: artifact, capability, memory_cell
- **Edge tables**: Complex relationship modeling
  - `task_depends_on_task`: Task dependencies
  - `task_produces_artifact`: Task output artifacts
  - `task_uses_capability`: Task capability requirements
  - `task_reads_memory`/`task_writes_memory`: Memory operations
  - `task_executed_by_organ`/`task_owned_by_agent`: Task ownership
  - `organ_provides_capability`: Organ capability mapping
  - `agent_owns_memory_cell`: Agent memory ownership
  - `task_reads_fact`/`task_produces_fact`: Fact operations

#### **Runtime Registry System**
- **cluster_metadata**: Cluster epoch tracking
- **registry_instance**: Instance management and health monitoring
- **Active views**: Real-time instance status and load balancing

#### **Advanced Indexing**
- **HNSW indexes**: Vector similarity search optimization
- **GIN indexes**: JSONB and array column optimization
- **Composite indexes**: Multi-column query optimization
- **Full-text search**: Text content search optimization

### MySQL (`init_mysql.sql`)
- Creates the `seedcore` database
- Creates example tables
- Creates `flashbulb_incidents` table for memory management

### Neo4j (`init_neo4j.cypher`)
- Creates constraints and indexes
- Creates sample Holon nodes
- Creates sample relationships

## Verification

After running the initialization scripts, verify the tables exist:

### **PostgreSQL Verification**

```bash
# Check core tables
kubectl exec -n seedcore-dev [POSTGRES_POD_NAME] -- psql -U postgres -d seedcore -c "SELECT COUNT(*) FROM holons;"
kubectl exec -n seedcore-dev [POSTGRES_POD_NAME] -- psql -U postgres -d seedcore -c "SELECT COUNT(*) FROM tasks;"
kubectl exec -n seedcore-dev [POSTGRES_POD_NAME] -- psql -U postgres -d seedcore -c "SELECT COUNT(*) FROM facts;"

# Check HGNN architecture
kubectl exec -n seedcore-dev [POSTGRES_POD_NAME] -- psql -U postgres -d seedcore -c "SELECT COUNT(*) FROM graph_node_map;"
kubectl exec -n seedcore-dev [POSTGRES_POD_NAME] -- psql -U postgres -d seedcore -c "SELECT COUNT(*) FROM agent_registry;"
kubectl exec -n seedcore-dev [POSTGRES_POD_NAME] -- psql -U postgres -d seedcore -c "SELECT COUNT(*) FROM organ_registry;"

# Check runtime registry
kubectl exec -n seedcore-dev [POSTGRES_POD_NAME] -- psql -U postgres -d seedcore -c "SELECT COUNT(*) FROM cluster_metadata;"
kubectl exec -n seedcore-dev [POSTGRES_POD_NAME] -- psql -U postgres -d seedcore -c "SELECT COUNT(*) FROM registry_instance;"

# Check views
kubectl exec -n seedcore-dev [POSTGRES_POD_NAME] -- psql -U postgres -d seedcore -c "SELECT COUNT(*) FROM graph_tasks;"
kubectl exec -n seedcore-dev [POSTGRES_POD_NAME] -- psql -U postgres -d seedcore -c "SELECT COUNT(*) FROM active_instances;"

# Check extensions
kubectl exec -n seedcore-dev [POSTGRES_POD_NAME] -- psql -U postgres -d seedcore -c "SELECT * FROM pg_extension WHERE extname IN ('vector', 'pgcrypto');"
```

### **MySQL Verification**

```bash
# Check MySQL
kubectl exec -n seedcore-dev [MYSQL_POD_NAME] -- mysql -u seedcore -ppassword seedcore -e "SHOW TABLES;"
```

### **Neo4j Verification**

```bash
# Check Neo4j
kubectl exec -n seedcore-dev [NEO4J_POD_NAME] -- cypher-shell -u neo4j -p password -c "MATCH (h:Holon) RETURN COUNT(h) as count;"
```

### **Quick Start Examples**

After successful initialization, you can test the system with these examples:

```sql
-- Create a graph embedding task (legacy)
SELECT create_graph_embed_task(ARRAY[123], 2, 'Embed neighborhood around node 123');

-- Create a graph embedding task with ownership (HGNN v2)
SELECT create_graph_embed_task_v2(ARRAY[123], 2, 'Embed with ownership', 'agent_main', 'utility_organ_1');

-- Ensure tasks are mapped to numeric node ids
SELECT backfill_task_nodes();

-- Explore edges for DGL ingest
SELECT * FROM hgnn_edges LIMIT 20;

-- Pull task embeddings joined to numeric node ids
SELECT task_id, node_id, emb[1:8] AS emb_head FROM task_embeddings LIMIT 5;

-- Monitor graph tasks
SELECT * FROM graph_tasks ORDER BY updated_at DESC LIMIT 10;

-- Test facts table
SELECT * FROM facts LIMIT 5;
```

## Next Steps

1. **Restart your seedcore-api pod** to pick up the new database schema
2. **Check the logs** to ensure no more database errors
3. **Verify the application** is working correctly

## Troubleshooting

### If the script fails:
- Make sure your database pods are running and healthy
- Check that you have the correct namespace
- Verify that kubectl has access to your cluster
- Check the pod labels match what the script expects
- Ensure all migration files exist in the `deploy/migrations/` directory
- Check database connection parameters (DB_NAME, DB_USER, DB_PASS)

### If tables still don't exist:
- Check the database pod logs for errors
- Verify the initialization scripts ran successfully
- Ensure the database credentials are correct
- Check if there are permission issues
- Verify that all 12 migrations ran successfully
- Check for migration conflicts or rollback issues

### Migration-specific issues:
- **Migration 005**: Critical schema consolidation - ensure this runs successfully
- **Migration 007-008**: HGNN schema - check for graph table creation
- **Migration 009-010**: Facts system - verify full-text search indexes
- **Migration 011-012**: Runtime registry - check instance management tables

### Performance issues:
- Check that vector and GIN indexes are created properly
- Verify HNSW index configuration for vector similarity search
- Monitor database connection limits and query performance
- Check for missing composite indexes on frequently queried columns

### Common error messages:
- `relation "holons" does not exist`: Run the full initialization script
- `extension "vector" does not exist`: Ensure PgVector is installed
- `permission denied`: Check database user permissions
- `migration failed`: Check migration file syntax and dependencies

## Notes

### **Required Components**
- The `holons` table is **required** for the application to start
- The `tasks` table is **required** for coordinator-dispatcher functionality
- The `facts` table is **required** for fact management system
- PostgreSQL with vector extension is **required** for full functionality

### **Optional Components**
- MySQL is **optional** but recommended for flashbulb memory
- Neo4j is **optional** but recommended for graph operations
- HGNN architecture is **optional** but recommended for advanced graph processing
- Runtime registry is **optional** but recommended for production deployments

### **Migration Safety**
- All scripts use `IF NOT EXISTS` so they're safe to run multiple times
- Migrations are idempotent and can be re-run safely
- Sample data is inserted to help with testing
- Database extensions are created with `IF NOT EXISTS` for safety

### **Performance Considerations**
- HNSW indexes provide fast vector similarity search
- GIN indexes optimize JSONB and array column queries
- Composite indexes optimize multi-column queries
- Full-text search indexes enable efficient text searching

## Summary

The SeedCore database initialization system has evolved significantly:

### **Migration-Based Architecture**
- **12 comprehensive migrations** covering all system components
- **Idempotent operations** safe for repeated execution
- **Progressive enhancement** from basic to advanced features

### **Advanced Schema Features**
- **HGNN architecture** for complex graph operations
- **Vector search** with PgVector and HNSW indexing
- **Facts management** with full-text search capabilities
- **Runtime registry** for instance management and coordination

### **Production Readiness**
- **Comprehensive error handling** and troubleshooting guides
- **Performance optimization** with advanced indexing
- **Scalable architecture** supporting complex workloads
- **Monitoring and verification** tools for system health

This evolution provides a robust foundation for scalable, intelligent, and resilient distributed systems while maintaining ease of deployment and operation.
