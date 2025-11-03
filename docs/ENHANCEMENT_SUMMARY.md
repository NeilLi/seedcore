# SeedCore Enhancement Summary - Complete System Evolution

## ✅ What We've Accomplished

### 1. Enhanced bootstrap.py
- **Race-safe actor creation** with `get_if_exists=True` support
- **Auto Ray initialization** when needed
- **Consistent namespace handling** across all actor operations
- **Better error handling and logging**
- **Fixed function names**: `get_mv_store()` → `get_mw_store()`

### 2. Enhanced working_memory.py
- **Robust MwManager** with resilient actor lookups
- **Async-safe operations** using threadpool for Ray calls
- **Configurable behavior** via environment variables
- **Retry logic with backoff** for startup race conditions
- **Optional auto-creation** of missing actors
- **Better error messages** and structured logging

### 3. Updated Import Patterns
- **Centralized imports** from `src.seedcore.bootstrap`
- **Consistent namespace usage** across all actor lookups
- **Fixed all call sites** to use the new import pattern

### 4. Database Schema Evolution (12 Migrations)
- **Task Management System**: Complete coordinator-dispatcher task queue with lease management
- **HGNN Architecture**: Two-layer heterogeneous graph with task and agent/organ layers
- **Graph Embeddings**: Vector-based graph embeddings with ANN indexing
- **Facts Management**: Text-based fact storage with full-text search capabilities
- **Runtime Registry**: Instance management and cluster coordination system

### 5. Ray Serve Client Architecture
- **Comprehensive Service Client System**: Base client with circuit breaker, retry logic, and resource management
- **Service Client Registry**: Factory pattern for all service clients (ML, Coordinator, State, Energy, Cognitive, Organism)
- **Circuit Breaker Pattern**: Automatic failure detection and recovery with configurable thresholds
- **Exponential Backoff Retry**: Jittered retry logic with configurable delays
- **Resource Management**: Rate limiting and concurrency control

### 6. Cognitive Core v2 Enhancements
- **DSPy Integration**: Enhanced cognitive reasoning with OCPS integration
- **RRF Fusion & MMR Diversity**: Better retrieval and diversification algorithms
- **Dynamic Token Budgeting**: OCPS-informed budgeting and escalation hints
- **Enhanced Fact Schema**: Provenance, trust, and policy flags
- **Post-condition Checks**: DSPy output validation and sanitization
- **Cache Governance**: TTL per task type with hardened cache management

## 🔧 Key Improvements

### Database Architecture Enhancements
- **12 Comprehensive Migrations**: Complete database schema evolution
- **Task Management**: Coordinator-dispatcher task queue with lease management and retry logic
- **HGNN Integration**: Two-layer heterogeneous graph neural network architecture
- **Vector Search**: PgVector integration with IVFFlat indexes for fast similarity search
- **Facts System**: Full-text search with GIN indexes and metadata support
- **Runtime Registry**: Instance management with cluster coordination and health monitoring

### Service Communication Architecture
- **Centralized Ray Connection**: Single source of truth for all Ray operations
- **Service Discovery**: Automatic endpoint discovery via centralized gateway
- **Circuit Breaker Pattern**: Fault tolerance with configurable failure thresholds
- **Resource Management**: Advanced rate limiting and concurrency control
- **Retry Logic**: Exponential backoff with jitter for resilient communication

### Cognitive Intelligence Enhancements
- **DSPy v2 Integration**: Enhanced cognitive reasoning with OCPS fast/planner path routing (planner path uses deep LLM profile)
- **Advanced Retrieval**: RRF fusion and MMR diversification for better context
- **Dynamic Budgeting**: OCPS-informed token allocation and escalation hints
- **Fact Management**: Comprehensive fact schema with provenance and trust scoring
- **Cache Optimization**: TTL per task type with hardened cache governance

### Namespace Consistency
- All actor lookups now use the same namespace logic
- Prevents the "Failed to look up actor with name 'mw'" error
- Supports both explicit `RAY_NAMESPACE` and runtime context

### Resilience
- **12 retries with 0.5s backoff** for actor lookups
- **Race-safe creation** using `get_if_exists=True`
- **Graceful fallbacks** when actors are missing

### Configuration
- **Environment-driven** behavior control
- **AUTO_CREATE=1** for automatic actor creation
- **Configurable retry behavior** and timeouts

## 🏗️ New Architecture Components

### Database Schema Evolution
The system now includes a comprehensive database schema with 12 migrations:

#### **Task Management System (Migrations 001-006)**
- **Tasks Table**: Complete coordinator-dispatcher task queue with status tracking
- **Lease Management**: Task locking with `locked_by` and `locked_at` columns
- **Retry Logic**: `attempts` counter and `run_after` scheduling
- **Performance Indexes**: Optimized queries for task claiming and status updates

#### **HGNN Architecture (Migrations 007-008)**
- **Graph Schema**: Two-layer heterogeneous graph with task and agent/organ layers
- **Node Mapping**: `graph_nodes` table with type-specific node definitions
- **Edge Relationships**: `graph_edges` table with relationship metadata
- **Vector Embeddings**: PgVector integration with IVFFlat indexes

#### **Facts Management (Migrations 009-010)**
- **Facts Table**: Text-based fact storage with full-text search
- **Metadata Support**: JSONB columns for flexible fact attributes
- **Search Optimization**: GIN indexes for tags and full-text search
- **Task Integration**: Fact-task relationship mapping

#### **Runtime Registry (Migrations 011-012)**
- **Instance Management**: `registry_instance` table for service instances
- **Cluster Coordination**: `cluster_metadata` with epoch tracking
- **Health Monitoring**: Heartbeat tracking and status management
- **Service Discovery**: Active instance views for load balancing

### Ray Serve Client Architecture
Comprehensive service communication system:

#### **Base Service Client**
```python
class BaseServiceClient:
    - Circuit breaker pattern with configurable thresholds
    - Exponential backoff retry with jitter
    - Resource management and rate limiting
    - Centralized error handling and logging
```

#### **Service Client Registry**
```python
SERVICE_CLIENTS = {
    "ml_service": MLServiceClient,
    "coordinator": CoordinatorServiceClient,
    "state": StateServiceClient,
    "energy": EnergyServiceClient,
    "cognitive": CognitiveServiceClient,
    "organism": OrganismServiceClient,
}
```

#### **Circuit Breaker Configuration**
- **Failure Threshold**: 5 consecutive failures
- **Recovery Timeout**: 30 seconds
- **Half-Open State**: Limited requests during recovery
- **Automatic Recovery**: Gradual traffic increase

### Cognitive Core v2 Enhancements
Advanced AI reasoning capabilities:

#### **DSPy Integration**
- **OCPS Fast/Planner Routing**: Intelligent path selection based on complexity (planner path uses deep LLM profile)
- **RRF Fusion**: Reciprocal Rank Fusion for better retrieval
- **MMR Diversity**: Maximal Marginal Relevance for diverse results
- **Dynamic Token Budgeting**: OCPS-informed allocation

#### **Enhanced Fact Schema**
```python
@dataclass
class Fact:
    text: str
    provenance: str
    trust: float
    policy_flags: List[str]
    created_at: datetime
    updated_at: datetime
```

#### **Cache Governance**
- **TTL per Task Type**: Different cache lifetimes for different operations
- **Hardened Security**: Input validation and sanitization
- **Post-condition Checks**: DSPy output validation
- **Conflict Detection**: Fact conflict resolution

## 🚀 Next Steps

### 1. Set Environment Variables
Ensure consistent environment across all services:

```bash
# Required
export RAY_NAMESPACE=seedcore-dev

# Optional but recommended
export RAY_ADDRESS=auto
export AUTO_CREATE=1  # If you want missing actors auto-created

# New database configuration
export DATABASE_URL=postgresql://user:pass@host:port/dbname
export PGVECTOR_INDEX_TYPE=ivfflat
export PGVECTOR_INDEX_LISTS=100
```

### 2. Update Service Startup
Early in your service startup (e.g., in `serve_entrypoint.py` or main app):

```python
from src.seedcore.bootstrap import bootstrap_actors
from src.seedcore.serve import get_all_service_clients

# Ensure all singleton actors exist
bootstrap_actors()  # Creates 'mw', 'miss_tracker', 'shared_cache' as detached

# Initialize service clients
clients = get_all_service_clients()
```

### 3. Database Migration
Run the database migrations to set up the new schema:

```bash
# From the docker directory
./init_full_db.sh  # Runs all 12 migrations
```

### 4. Restart Services
- **Restart your seedcore-api container** to pick up the code changes
- **Verify bootstrap process** runs successfully during startup
- **Check that the 'mw' actor** is now accessible
- **Verify database schema** is properly migrated

### 5. Test the Fix
The error should no longer occur:
```
❌ Before: Failed to look up actor with name 'mw'
✅ After: ✅ MwManager for organ='utility_organ_1_agent_0' ready
```

## 🔍 Verification

### Check Actor Status
```bash
# From ray-head container
python -m scripts.monitor_actors

# Or check directly
python -c "
import ray
ray.init(address='ray://ray-head:10001', namespace='seedcore-dev')
print('✅ Ray initialized')
print('🎭 Actors:', ray.list_named_actors())
"
```

### Expected Output
```
📊 Singleton Actors Status:
🎭 MissTracker: ✅ Running
🎭 SharedCache: ✅ Running  
🎭 MwStore: ✅ Running
```

## 🎯 Benefits

### Core System Benefits
1. **No more namespace mismatches** - consistent actor lookups
2. **Faster startup** - race-safe actor creation
3. **Better debugging** - structured error messages
4. **Async compatibility** - non-blocking Ray operations
5. **Configurable behavior** - environment-driven settings
6. **Resilient operation** - retry logic and fallbacks

### Database Architecture Benefits
7. **Scalable Task Management** - Coordinator-dispatcher pattern with lease management
8. **Advanced Graph Processing** - HGNN architecture for complex relationship modeling
9. **Efficient Vector Search** - PgVector with IVFFlat indexes for fast similarity search
10. **Comprehensive Fact Management** - Full-text search with metadata support
11. **Runtime Coordination** - Instance management and cluster health monitoring

### Service Communication Benefits
12. **Fault Tolerance** - Circuit breaker pattern prevents cascading failures
13. **Service Discovery** - Automatic endpoint discovery and configuration
14. **Resource Management** - Advanced rate limiting and concurrency control
15. **Retry Logic** - Exponential backoff with jitter for resilient communication
16. **Centralized Configuration** - Single source of truth for all service settings

### Cognitive Intelligence Benefits
17. **Enhanced Reasoning** - DSPy v2 with OCPS fast/planner path routing (planner path uses deep LLM profile)
18. **Better Retrieval** - RRF fusion and MMR diversification for improved context
19. **Dynamic Optimization** - OCPS-informed token allocation and escalation
20. **Fact Management** - Comprehensive fact schema with provenance and trust
21. **Cache Optimization** - TTL per task type with hardened security

## 🚨 Troubleshooting

### If actors still can't be found:
1. **Check namespace consistency**: Ensure `RAY_NAMESPACE` is set the same everywhere
2. **Verify bootstrap ran**: Look for "Ray initialized" and "Bootstrapped actors" logs
3. **Check Ray cluster health**: Ensure Ray is running and accessible
4. **Enable auto-create**: Set `AUTO_CREATE=1` for automatic actor creation

### Database Issues:
1. **Migration failures**: Check database connection and permissions
2. **Schema conflicts**: Ensure all 12 migrations ran successfully
3. **Index performance**: Verify PgVector and GIN indexes are created
4. **Connection pooling**: Check database connection limits

### Service Communication Issues:
1. **Circuit breaker open**: Check service health and reduce load
2. **Service discovery failures**: Verify gateway configuration
3. **Retry exhaustion**: Check service availability and network connectivity
4. **Resource limits**: Monitor rate limiting and concurrency controls

### Cognitive Core Issues:
1. **DSPy initialization**: Check LLM provider configuration
2. **OCPS integration**: Verify OCPS client configuration
3. **Cache failures**: Check cache TTL and storage configuration
4. **Fact conflicts**: Review fact schema and conflict resolution

### Common Issues:
- **Namespace mismatch**: Different services using different namespaces
- **Bootstrap not called**: Actors never created during startup
- **Ray not initialized**: Service trying to use Ray before initialization
- **Permission issues**: Ray cluster access problems
- **Database connectivity**: PostgreSQL connection and migration issues
- **Service discovery**: Gateway configuration and endpoint resolution
- **Circuit breaker**: Service health and fault tolerance configuration

## 📚 Additional Resources

### Core Documentation
- **Ray Namespace Documentation**: https://docs.ray.io/en/latest/ray-core/actors/namespaces.html
- **KubeRay Best Practices**: https://ray-project.github.io/kuberay/
- **Actor Lifecycle Management**: https://docs.ray.io/en/latest/ray-core/actors/actor-lifecycle.html

### Database & Architecture
- **PostgreSQL Documentation**: https://www.postgresql.org/docs/
- **PgVector Extension**: https://github.com/pgvector/pgvector
- **Ray Serve Documentation**: https://docs.ray.io/en/latest/serve/
- **Circuit Breaker Pattern**: https://martinfowler.com/bliki/CircuitBreaker.html

### Cognitive Intelligence
- **DSPy Documentation**: https://dspy-docs.vercel.app/
- **OCPS Integration**: Internal SeedCore documentation
- **Vector Search Best Practices**: https://docs.pinecone.io/docs/vector-similarity-search

## 📝 Summary

The SeedCore system has evolved significantly with comprehensive enhancements across multiple architectural layers:

### **Database Evolution**
- **12 comprehensive migrations** establishing robust task management, HGNN architecture, facts system, and runtime registry
- **Advanced indexing** with PgVector and GIN indexes for optimal performance
- **Scalable schema** supporting complex graph operations and vector search

### **Service Architecture**
- **Centralized Ray connection** management eliminating cascading errors
- **Comprehensive service client system** with circuit breakers and retry logic
- **Service discovery** and resource management for production-ready deployment

### **Cognitive Intelligence**
- **DSPy v2 integration** with OCPS fast/planner path routing (planner path uses deep LLM profile)
- **Advanced retrieval** using RRF fusion and MMR diversification
- **Enhanced fact management** with provenance, trust, and conflict resolution

### **Production Readiness**
- **Fault tolerance** with circuit breakers and graceful degradation
- **Resource management** with rate limiting and concurrency control
- **Comprehensive monitoring** and health checking across all components

This evolution provides a solid foundation for scalable, intelligent, and resilient distributed systems while maintaining backward compatibility and ease of deployment.

