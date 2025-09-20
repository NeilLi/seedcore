# MW Actor Bootstrap Fix Summary - Complete Architecture Reference

## 🚨 Problem Identified

The error `Failed to look up actor 'mw' in namespace 'seedcore-dev'` occurred because:

1. **RayAgent initialization** was trying to create `MwManager` instances
2. **MwManager initialization** was trying to connect to the `mw` actor
3. **The `mw` actor didn't exist** because `bootstrap_actors()` was never called
4. **The organism manager** was creating agents without ensuring prerequisite actors existed

## 🏗️ Current Architecture Overview

The SeedCore system now features a sophisticated multi-tier architecture with advanced agent management, energy optimization, and cognitive integration:

### **Tier0MemoryManager Architecture**
- **Centralized Agent Management**: Manages Ray agent actors with comprehensive lifecycle control
- **Energy-Aware Task Routing**: Intelligent agent selection based on energy optimization
- **Graph-Aware Reconciliation**: Desired-state management with graph-based agent specifications
- **Advanced Discovery**: Multi-source agent discovery (registry + Ray cluster)
- **Health Monitoring**: Continuous heartbeat collection and agent health tracking

### **RayAgent Advanced Features**
- **Stateful Memory Management**: 128-dimensional state vectors with private memory systems
- **Cognitive Integration**: Advanced reasoning capabilities via cognitive service
- **Energy System Integration**: Real-time energy tracking and optimization
- **Memory Tier Integration**: Working memory (Mw) and long-term memory (Mlt) management
- **Flashbulb Memory**: Incident logging and high-stakes task handling
- **Performance Tracking**: Comprehensive metrics and capability scoring

## 🏗️ Detailed Architecture Components

### **Tier0MemoryManager - Central Agent Orchestration**

The `Tier0MemoryManager` serves as the central orchestrator for all Ray agents in the system:

#### **Core Responsibilities**
- **Agent Lifecycle Management**: Create, attach, monitor, and archive agents
- **Energy-Aware Task Routing**: Select optimal agents based on energy optimization algorithms
- **Health Monitoring**: Continuous heartbeat collection and agent health tracking
- **Graph-Aware Reconciliation**: Ensure agents match desired state from graph specifications
- **Multi-Source Discovery**: Discover agents from runtime registry and Ray cluster

#### **Advanced Features**
```python
class Tier0MemoryManager:
    def __init__(self):
        self.agents: Dict[str, Any] = {}  # agent_id -> Ray actor handle
        self.heartbeats: Dict[str, Dict[str, Any]] = {}  # Latest heartbeat data
        self.agent_stats: Dict[str, Dict[str, Any]] = {}  # Performance statistics
        self._ping_failures: Dict[str, int] = {}  # Failure tracking
        self._graph: Optional[GraphClient] = None  # Graph reconciliation
```

#### **Energy-Aware Task Execution**
- **`execute_task_on_best_agent()`**: Uses energy optimization to select optimal agent
- **`execute_task_on_best_of()`**: Constrained selection from candidate set
- **`execute_task_on_organ_best()`**: Organ-specific agent selection
- **`execute_task_on_graph_best()`**: Graph-filtered agent selection

#### **Agent Discovery Mechanisms**
1. **Registry Discovery**: Queries PostgreSQL runtime registry for active instances
2. **Ray Cluster Scan**: Scans Ray cluster for existing RayAgent actors
3. **Environment Attachment**: Attaches actors specified in `TIER0_ATTACH_ACTORS`
4. **Graph Reconciliation**: Creates agents based on graph specifications

### **RayAgent - Advanced Stateful Agents**

The `RayAgent` represents the core computational unit with sophisticated capabilities:

#### **Memory Architecture**
```python
@dataclass
class AgentState:
    h: Any  # 128-dimensional embedding vector
    p: Dict[str, float]  # Role probabilities
    c: float = 0.5  # Capability score
    mem_util: float = 0.0  # Memory utilization
```

#### **Advanced Capabilities**
- **Private Memory Management**: 128-dimensional state vectors with telemetry
- **Cognitive Integration**: Advanced reasoning via cognitive service client
- **Energy Tracking**: Real-time energy state monitoring and optimization
- **Memory Tier Integration**: Working memory (Mw) and long-term memory (Mlt)
- **Flashbulb Memory**: High-stakes incident logging and analysis
- **Performance Metrics**: Comprehensive tracking and capability scoring

#### **Task Execution Framework**
- **General Query Handling**: Time, date, system status, mathematical queries
- **Collaborative Tasks**: Knowledge finding with Mw → Mlt escalation
- **High-Stakes Tasks**: Failure handling with salience scoring and incident logging
- **Cognitive Reasoning**: Failure analysis, task planning, decision making

### **Memory Management Integration**

#### **Working Memory (Mw)**
- **Distributed Caching**: Cluster-wide caching with TTL support
- **Negative Caching**: Prevents stampede on cache misses
- **Single-Flight Guards**: Prevents duplicate requests for same data
- **Hot Item Prewarming**: Proactive cache warming for frequently accessed items

#### **Long-Term Memory (Mlt)**
- **Persistent Storage**: Long-term knowledge storage and retrieval
- **Compression Support**: Data compression for storage optimization
- **Holon Management**: Structured data storage and querying

#### **Flashbulb Memory (Mfb)**
- **Incident Logging**: High-stakes event recording with salience scoring
- **Salience Calculation**: ML-based importance scoring for events
- **Context Preservation**: Full agent state capture during incidents

## 🔍 Root Cause Analysis

### Missing Bootstrap Call
The `organism_manager.py` was creating agents that needed memory managers, but it wasn't calling `bootstrap_actors()` to ensure the required singleton actors existed first.

### Required Singleton Actors
The system needs these actors to be created before agents can initialize:
- **`mw`** - MwStore for working memory management
- **`miss_tracker`** - MissTracker for tracking cache misses
- **`shared_cache`** - SharedCache for cluster-wide caching

### Configuration Issue
The `working_memory.py` module has `CONFIG.auto_create = False` by default, which means it won't automatically create missing actors. This requires explicit bootstrap.

## ⚡ Energy System Integration

### **Energy-Aware Agent Selection**

The system now features sophisticated energy optimization for agent selection:

#### **Energy Optimization Algorithm**
```python
def execute_task_on_best_agent(self, task_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Executes a task on the most suitable agent based on energy optimization."""
    agent_handles = list(self.agents.values())
    best_agent, predicted_delta_e = select_best_agent(agent_handles, task_data)
    result = ray.get(best_agent.execute_task.remote(task_data))
    return result
```

#### **Energy State Tracking**
- **Real-time Energy Monitoring**: Continuous tracking of agent energy states
- **Delta Energy Calculation**: Before/after task execution energy measurement
- **Energy Proxy Calculation**: Local energy estimation using state vectors
- **Energy State Updates**: Dynamic energy state management

#### **Energy-Aware Features**
- **Lipschitz Cap Validation**: Model promotion with energy constraints
- **Energy Guard**: Delta energy validation for task execution
- **Rollback Mechanisms**: Automatic rollback on energy constraint violations
- **Energy Cost Tracking**: Cognitive reasoning energy cost calculation

### **Cognitive Integration Architecture**

#### **Cognitive Service Client**
```python
class RayAgent:
    def __init__(self, ...):
        self._cog = CognitiveServiceClient()  # Cognitive reasoning client
        self._cog_available = self._cog is not None
```

#### **Advanced Reasoning Capabilities**
- **Failure Analysis**: `reason_about_failure()` - Analyze agent failures using cognitive reasoning
- **Task Planning**: `plan_complex_task()` - Plan complex tasks with resource constraints
- **Decision Making**: `make_decision()` - Make decisions with historical context
- **Memory Synthesis**: `synthesize_memory()` - Synthesize information from multiple sources
- **Capability Assessment**: `assess_capabilities()` - Assess and improve agent capabilities

#### **Cognitive Context Management**
- **Memory Context**: Agent memory utilization and performance data
- **Lifecycle Context**: Agent lifecycle state and performance history
- **Performance Data**: Comprehensive performance metrics for reasoning
- **Agent Capabilities**: Current capabilities and skill deltas

### **Advanced Task Execution Framework**

#### **Task Types and Handlers**
1. **General Queries**: Time, date, system status, mathematical calculations
2. **Collaborative Tasks**: Knowledge finding with Mw → Mlt escalation
3. **High-Stakes Tasks**: Failure handling with salience scoring
4. **Cognitive Tasks**: Advanced reasoning and decision making

#### **Knowledge Finding System**
```python
async def find_knowledge(self, fact_id: str) -> Optional[Dict[str, Any]]:
    """Attempts to find knowledge with Mw -> Mlt escalation."""
    # 1. Check negative cache (avoid stampede)
    # 2. Try Working Memory (Mw) first
    # 3. Escalate to Long-Term Memory (Mlt)
    # 4. Cache result back to Mw
    # 5. Set negative cache on miss
```

#### **High-Stakes Task Handling**
- **Salience Scoring**: ML-based importance calculation for incidents
- **Flashbulb Memory**: High-stakes incident logging with full context
- **Error Classification**: Intelligent error type classification
- **Incident Context**: Complete agent state capture during failures

## ✅ Fix Implemented

### 1. Added Bootstrap Call to Organism Manager

**File**: `src/seedcore/organs/organism_manager.py`

**Location**: After Ray initialization, before creating agents

**Code Added**:
```python
# Bootstrap required singleton actors (mw, miss_tracker, shared_cache)
try:
    from ..bootstrap import bootstrap_actors
    logger.info("🚀 Bootstrapping required singleton actors...")
    bootstrap_actors()
    logger.info("✅ Singleton actors bootstrapped successfully")
except Exception as e:
    logger.warning(f"⚠️ Failed to bootstrap singleton actors: {e}")
    logger.warning("⚠️ Agents may have limited functionality without memory managers")
```

### 2. What This Fix Does

1. **Ensures prerequisite actors exist** before any agents are created
2. **Creates the `mw` actor** in the correct namespace (`seedcore-dev`)
3. **Creates `miss_tracker` and `shared_cache` actors** for complete functionality
4. **Provides graceful fallback** if bootstrap fails (agents continue with limited functionality)

## 📊 Performance Monitoring & Health Management

### **Comprehensive Health Monitoring**

#### **Heartbeat Collection System**
```python
async def collect_heartbeats(self) -> Dict[str, Dict[str, Any]]:
    """Collect heartbeats from all agents (non-blocking with timeouts)."""
    timeout = float(os.getenv("TIER0_HEARTBEAT_TIMEOUT", "2.0"))
    tasks = [_aget(handle.get_heartbeat.remote(), timeout=timeout) for _, handle in items]
    results = await asyncio.gather(*tasks, return_exceptions=True)
```

#### **Agent Statistics Collection**
- **Performance Metrics**: Success rate, quality scores, capability scores
- **Memory Metrics**: Memory writes, hits, compression gains
- **Lifecycle Data**: Uptime, idle ticks, archive status
- **Energy State**: Current energy contribution and state

#### **System Summary Analytics**
```python
def get_system_summary(self) -> Dict[str, Any]:
    """Get a summary of the entire Tier 0 memory system."""
    return {
        "total_agents": total_agents,
        "total_tasks_processed": total_tasks,
        "average_capability_score": avg_capability,
        "average_memory_utilization": avg_mem_util,
        "total_memory_writes": total_memory_writes,
        "total_peer_interactions": total_peer_interactions
    }
```

### **Advanced Agent Lifecycle Management**

#### **Agent Creation & Attachment**
- **Idempotent Creation**: Reuses existing named actors when possible
- **Resource Configuration**: CPU, GPU, memory, and custom resource allocation
- **Namespace Management**: Consistent namespace handling across components
- **Graceful Fallback**: Continues operation even with partial failures

#### **Agent Discovery & Reconciliation**
- **Multi-Source Discovery**: Registry + Ray cluster + environment variables
- **Graph-Aware Reconciliation**: Ensures agents match desired state
- **Policy-Based Filtering**: Task routing based on agent capabilities and policies
- **Health-Aware Pruning**: Removes dead agents after consecutive failures

#### **Agent Archival & Cleanup**
- **Graceful Archival**: Moves agent summaries to long-term memory
- **Resource Cleanup**: Evicts agent data from working memory
- **Incident Logging**: Records archival events in flashbulb memory
- **State Preservation**: Maintains agent state for analysis

### **Memory Management Architecture**

#### **Multi-Tier Memory System**
1. **Private Memory (Ma)**: Agent-specific 128-dimensional state vectors
2. **Working Memory (Mw)**: Distributed cluster-wide caching
3. **Long-Term Memory (Mlt)**: Persistent knowledge storage
4. **Flashbulb Memory (Mfb)**: High-stakes incident recording

#### **Memory Integration Features**
- **Automatic Escalation**: Mw → Mlt knowledge finding
- **Negative Caching**: Prevents cache stampede on misses
- **Single-Flight Guards**: Prevents duplicate requests
- **Hot Item Prewarming**: Proactive cache optimization
- **Compression Support**: Storage optimization for long-term memory

#### **Memory Telemetry & Monitoring**
- **Cache Hit Rates**: Performance tracking for memory tiers
- **Compression Gains**: Storage optimization metrics
- **Memory Utilization**: Agent memory usage tracking
- **Peer Interactions**: Inter-agent communication patterns

## 🔧 How the Fix Works

### Bootstrap Sequence
1. **Ray initialization** - Ensures Ray is running in the correct namespace
2. **Bootstrap actors** - Creates `mw`, `miss_tracker`, `shared_cache` as detached actors
3. **Agent creation** - Agents can now successfully connect to memory managers
4. **Memory manager initialization** - `MwManager` can connect to the `mw` actor

### Actor Creation Details
```python
def bootstrap_actors():
    """Ensure all singleton actors exist; return handles as a tuple."""
    miss_tracker = _get_or_create(MissTracker, "miss_tracker")
    shared_cache = _get_or_create(SharedCache, "shared_cache")
    mw_store = _get_or_create(MwStore, "mw")
    return miss_tracker, shared_cache, mw_store
```

## 🧪 Testing

### Test Script Created
- **File**: `scripts/test_bootstrap_fix.py`
- **Purpose**: Verify that the bootstrap fix resolves the mw actor error
- **Tests**:
  1. Environment configuration check
  2. Bootstrap actors functionality
  3. MW actor availability verification
  4. MwManager initialization
  5. RayAgent memory manager initialization

### Running Tests
```bash
# Set environment variables
export SEEDCORE_NS=seedcore-dev
export RAY_NAMESPACE=seedcore-dev

# Run the test script
python3 scripts/test_bootstrap_fix.py
```

## 🚀 Expected Results After Fix

### Before Fix
```
ERROR:src.seedcore.agents.tier0_manager:❌ Failed to initialize Ray: name 'os' is not defined
ERROR:src.seedcore.agents.ray_actor:⚠️ Failed to initialize memory managers for cognitive_organ_1_agent_0: Failed to look up actor 'mw' in namespace 'seedcore-dev'
```

### After Fix
```
INFO:src.seedcore.organs.organism_manager:✅ Ray initialized locally with namespace: seedcore-dev
INFO:src.seedcore.organs.organism_manager:🚀 Bootstrapping required singleton actors...
INFO:src.seedcore.organs.organism_manager:✅ Singleton actors bootstrapped successfully
INFO:src.seedcore.agents.ray_actor:✅ Agent cognitive_organ_1_agent_0 initialized with memory managers
```

## 🔍 Verification Commands

### Check Actor Availability
```bash
# List actors in the correct namespace
ray list actors --namespace seedcore-dev

# Check specific actors
ray get-actor mw --namespace seedcore-dev
ray get-actor miss_tracker --namespace seedcore-dev
ray get-actor shared_cache --namespace seedcore-dev
```

### Check Ray Dashboard
```bash
# Check actor tables in Ray dashboard
curl -s http://localhost:8265/api/v0/actors | jq '.data.result.result | map(select(.state=="ALIVE")) | length'
```

## 🎯 Key Benefits of the Fix

1. **Eliminates the mw actor error** - Agents can now initialize memory managers
2. **Ensures proper startup sequence** - Prerequisites are created before dependencies
3. **Maintains namespace consistency** - All actors are created in `seedcore-dev`
4. **Provides graceful degradation** - System continues even if some actors fail
5. **Improves reliability** - No more "Failed to look up actor" errors

## 🚨 Important Notes

### Environment Variables Required
Make sure these are set in your deployment:
```bash
export SEEDCORE_NS=seedcore-dev
export RAY_NAMESPACE=seedcore-dev  # Optional, will use SEEDCORE_NS if not set
```

### Deployment Order
1. **Ray cluster** must be running
2. **Environment variables** must be set
3. **Organism manager** will bootstrap actors automatically
4. **Agents** can then be created successfully

### Monitoring
After deployment, verify:
- `bootstrap_actors()` is called successfully
- `mw`, `miss_tracker`, `shared_cache` actors are visible
- Agents initialize without memory manager errors
- No more "Failed to look up actor 'mw'" errors

## 🔄 Alternative Solutions

### Option 1: Enable AUTO_CREATE
```bash
export AUTO_CREATE=1
```
This would let the working_memory module create actors automatically, but bootstrap is preferred for explicit control.

### Option 2: Manual Actor Creation
```python
# Create actors manually before creating agents
from seedcore.bootstrap import bootstrap_actors
bootstrap_actors()
```

### Option 3: Lazy Initialization
Modify MwManager to handle missing actors gracefully, but this reduces functionality.

## 📚 Related Documentation

- [Namespace Fix Summary](./NAMESPACE_FIX_SUMMARY.md)
- [Ray Configuration Pattern](../RAY_CONFIGURATION_PATTERN.md)
- [Working Memory Architecture](../memory/working_memory.py)
- [Bootstrap Module](../bootstrap.py)

## 🚀 Advanced System Capabilities

### **Production-Ready Features**

#### **Robust Error Handling**
- **Graceful Degradation**: System continues operation with partial failures
- **Circuit Breaker Patterns**: Prevents cascade failures in service calls
- **Comprehensive Logging**: Detailed error tracking and debugging information
- **Fallback Mechanisms**: Multiple fallback strategies for critical operations

#### **Scalability & Performance**
- **Distributed Architecture**: Ray-based distributed agent management
- **Resource Optimization**: Intelligent resource allocation and management
- **Concurrent Processing**: Async task execution with timeout handling
- **Memory Efficiency**: Optimized memory usage with compression and caching

#### **Monitoring & Observability**
- **Real-time Metrics**: Continuous performance and health monitoring
- **System Analytics**: Comprehensive system-wide statistics and insights
- **Agent Telemetry**: Detailed agent performance and behavior tracking
- **Energy Monitoring**: Real-time energy state and optimization tracking

### **Integration Capabilities**

#### **Service Integration**
- **Cognitive Service**: Advanced reasoning and decision-making capabilities
- **ML Service**: Salience scoring and drift detection integration
- **Energy System**: Real-time energy optimization and constraint validation
- **Registry System**: Runtime registry integration for service discovery

#### **Memory System Integration**
- **Multi-Tier Memory**: Seamless integration across memory tiers
- **Knowledge Management**: Intelligent knowledge finding and synthesis
- **Incident Handling**: High-stakes event logging and analysis
- **Data Persistence**: Robust data storage and retrieval mechanisms

## 🎉 Summary

The SeedCore system now features a **sophisticated multi-tier architecture** with advanced agent management, energy optimization, and cognitive integration. The original bootstrap fix has evolved into a comprehensive system that provides:

### **Core Achievements**
✅ **Eliminates Actor Errors** - Prerequisite actors created before agent initialization  
✅ **Advanced Agent Management** - Sophisticated lifecycle and health monitoring  
✅ **Energy-Aware Optimization** - Intelligent agent selection and task routing  
✅ **Cognitive Integration** - Advanced reasoning and decision-making capabilities  
✅ **Multi-Tier Memory** - Comprehensive memory management across all tiers  
✅ **Production Readiness** - Robust error handling and monitoring capabilities  

### **Architecture Highlights**
- **Tier0MemoryManager**: Central orchestration with energy-aware task routing
- **RayAgent**: Advanced stateful agents with cognitive capabilities
- **Memory Integration**: Seamless Mw → Mlt → Mfb memory tier management
- **Energy System**: Real-time optimization with constraint validation
- **Cognitive Services**: Advanced reasoning, planning, and decision-making
- **Health Monitoring**: Comprehensive performance and system analytics

### **Key Benefits**
1. **Reliability**: Robust error handling and graceful degradation
2. **Scalability**: Distributed architecture with intelligent resource management
3. **Intelligence**: Advanced cognitive capabilities and energy optimization
4. **Observability**: Comprehensive monitoring and performance analytics
5. **Flexibility**: Multi-source discovery and graph-aware reconciliation
6. **Production-Ready**: Enterprise-grade features and monitoring capabilities

This comprehensive architecture represents a significant evolution from the original bootstrap fix, providing a sophisticated foundation for advanced AI agent management and cognitive computing capabilities.
