# SeedCore Documentation

## Project Overview

SeedCore is a multi-tier memory system implementing the Collective Organic Architecture (COA) specification. The system provides stateful Ray-based agents with distributed memory management across multiple tiers.

## Architecture Overview

### Memory Tiers Implementation Status

| Tier | Name | Purpose | Status | Implementation |
|------|------|---------|--------|----------------|
| **Tier 0** | **Ma** | Per-Agent Memory | ✅ **COMPLETE** | Ray Actors with 128-dim state vectors |
| **Tier 1** | **Mw** | Working Memory | ✅ **COMPLETE** | In-memory with capacity limits |
| **Tier 2** | **Mlt** | Long-Term Memory | ✅ **COMPLETE** | In-memory with larger capacity |
| **Tier 3** | **Mfb** | Flashbulb Memory | ✅ **COMPLETE** | MySQL-backed for high-salience events |

### Infrastructure Status

| Component | Status | Details |
|-----------|--------|---------|
| **Ray Cluster** | ✅ **RUNNING** | Head + Worker nodes for distributed computing |
| **PostgreSQL** | ✅ **RUNNING** | Primary relational database |
| **Neo4j** | ✅ **RUNNING** | Graph database for relationships |
| **Redis** | ✅ **RUNNING** | In-memory cache and pub/sub |
| **MySQL** | ✅ **RUNNING** | Flashbulb Memory storage |
| **FastAPI** | ✅ **RUNNING** | REST API server on port 80 |

## Current Implementation Details

### Tier 0: Per-Agent Memory (Ma) ✅

**Location**: `src/seedcore/agents/ray_actor.py`

**Features**:
- Stateful Ray actors with private memory
- 128-dimensional state vectors (h)
- Performance tracking (success_rate, quality_score, capability_score)
- EWMA-smoothed capability scores
- Memory utilization tracking
- Heartbeat system for monitoring
- Role probability distributions (E/S/O)

**API Endpoints**:
- `POST /tier0/agents/create` - Create new agent
- `GET /tier0/agents/{id}/heartbeat` - Get agent heartbeat
- `POST /tier0/agents/{id}/execute` - Execute task on agent
- `GET /tier0/summary` - System summary

### Tier 1: Working Memory (Mw) ✅

**Location**: `src/seedcore/memory/system.py`

**Features**:
- In-memory storage with capacity limits
- Fast access for active data
- Automatic overflow to long-term memory
- Hit/miss tracking

### Tier 2: Long-Term Memory (Mlt) ✅

**Location**: `src/seedcore/memory/system.py`

**Features**:
- Larger capacity than working memory
- Slower access but persistent storage
- Compression and optimization
- Integration with PostgreSQL backend

### Tier 3: Flashbulb Memory (Mfb) ✅

**Location**: `src/seedcore/memory/flashbulb_memory.py`

**Features**:
- MySQL-backed storage for high-salience events
- JSON event data storage
- Salience score tracking
- Time-based and threshold-based queries
- Durable long-term archiving

**API Endpoints**:
- `POST /mfb/incidents` - Log high-salience incident
- `GET /mfb/incidents/{id}` - Retrieve incident
- `GET /mfb/incidents` - Query incidents by time/salience
- `GET /mfb/stats` - System statistics

## File Structure

```
seedcore/
├── docker/
│   ├── docker-compose.yml          # Multi-service orchestration
│   ├── setup/
│   │   └── init_mysql.sql         # MySQL initialization
│   └── requirements-minimal.txt    # Python dependencies
├── src/seedcore/
│   ├── agents/
│   │   ├── ray_actor.py           # Tier 0 Ray agents
│   │   ├── tier0_manager.py       # Agent management
│   │   └── __init__.py
│   ├── memory/
│   │   ├── system.py              # Memory tier implementation
│   │   ├── flashbulb_memory.py    # Flashbulb memory (Mfb)
│   │   ├── long_term_memory.py    # Long-term memory (Mlt)
│   │   └── __init__.py
│   ├── telemetry/
│   │   ├── server.py              # FastAPI server
│   │   ├── stats.py               # Statistics collection
│   │   └── __init__.py
│   └── __init__.py
├── scripts/
│   ├── scenario_1_knowledge_gap.py # Collaborative task scenario
│   ├── populate_mlt.py            # Pre-populate long-term memory
│   └── write_to_mw.py             # Working memory operations
├── tests/
└── docs/
```

## Scenarios and Examples

### Scenario 1: Collaborative Task with Knowledge Gap ✅

**Purpose**: Demonstrates the multi-tier memory system's ability to handle cache misses and knowledge retrieval across memory tiers.

**Objective**: Two agents collaborate on a task requiring knowledge that is initially missing from fast-access memory, demonstrating the Mw → Mlt escalation pattern.

#### Scenario Flow

1. **Task Assignment**: A collaborative task is assigned requiring two agents
2. **Knowledge Gap**: Agent B needs information (`fact_X_uuid`) not in its local memory
3. **Cache Miss**: Agent B queries Mw (Working Memory) but gets a cache miss
4. **Memory Escalation**: The query escalates to Mlt (Long-Term Memory)
5. **Knowledge Retrieval**: Agent B successfully finds the required information in Mlt
6. **Cache Population**: The retrieved knowledge is cached in Mw for future use
7. **Task Completion**: Both agents successfully complete the collaborative task
8. **Performance Update**: Agents update their internal Ma with performance metrics

#### What It Validates

- ✅ **Cache Miss Handling**: System correctly handles Mw miss and escalates to Mlt
- ✅ **Mlt Integration**: Agents can effectively query and retrieve data from Long-Term Memory
- ✅ **Knowledge Caching**: Read-through cache pattern works (retrieved knowledge populates Mw)
- ✅ **Performance Tracking**: Agents update their internal Ma with performance metrics
- ✅ **Collaborative Execution**: Multiple agents can work on the same task

#### Running the Scenario

```bash
# 1. Ensure all services are running
docker-compose ps

# 2. Pre-populate Long-Term Memory (if needed)
docker-compose exec seedcore-api python scripts/populate_mlt.py

# 3. Run the scenario
docker-compose exec seedcore-api python -m scripts.scenario_1_knowledge_gap
```

#### Expected Output

```
🚀 Starting Scenario 1: Collaborative Task with Knowledge Gap
================================================================================
✅ Ray initialized successfully
🤖 Creating agents for collaborative task...
✅ Agents created successfully

📋 Task Definition:
   - Name: Launch Sequence Alpha
   - Required Fact: fact_X_uuid
   - Complexity: 0.8

============================================================
🔄 PHASE 1: First Attempt (Cache Miss Expected)
============================================================
📤 Assigning task to Agent-B (who has the knowledge gap)...
📊 Result from first attempt:
   - Agent: Agent-B
   - Task: Launch Sequence Alpha
   - Success: True
   - Quality: 0.900
   - Knowledge Found: True

============================================================
🔄 PHASE 2: Second Attempt (Cache Hit Expected)
============================================================
📤 Assigning the same task again to Agent-B...
   Expected: Cache hit in Mw this time!
📊 Result from second attempt:
   - Agent: Agent-B
   - Task: Launch Sequence Alpha
   - Success: True
   - Quality: 0.900
   - Knowledge Found: True

============================================================
🔄 PHASE 3: Agent-A Collaboration
============================================================
📤 Assigning task to Agent-A for collaboration...
📊 Result from Agent-A:
   - Agent: Agent-A
   - Task: Launch Sequence Alpha
   - Success: True
   - Quality: 0.900
   - Knowledge Found: True

============================================================
📈 SCENARIO ANALYSIS
============================================================
🔍 Comparing Phase 1 vs Phase 2:
   - Phase 1 Success: True
   - Phase 2 Success: True
   - Phase 1 Quality: 0.900
   - Phase 2 Quality: 0.900

✅ Cache behavior detected: Knowledge availability changed between attempts

================================================================================
✅ SCENARIO 1 COMPLETED SUCCESSFULLY!
================================================================================
```

#### Technical Implementation

**Key Components**:
- **RayAgent**: Stateful Ray actors with memory management capabilities
- **MwManager**: Working Memory manager with Redis backend
- **LongTermMemoryManager**: Long-term memory with PgVector and Neo4j backends
- **Memory Escalation Logic**: Automatic fallback from Mw to Mlt on cache misses

**Memory Interaction Flow**:
```
Agent Task Request → Mw Query → Cache Miss → Mlt Query → Knowledge Retrieval → Mw Cache Update → Task Completion
```

#### Troubleshooting

**Common Issues**:
1. **ModuleNotFoundError**: Ensure all dependencies are installed in Ray containers
2. **Connection Errors**: Verify all services (Redis, PostgreSQL, Neo4j) are running
3. **Agent Initialization Failures**: Check Ray cluster status and memory manager connections

**Debug Commands**:
```bash
# Check service status
docker-compose ps

# View Ray logs
docker-compose logs ray-head ray-worker

# Test memory manager connections
docker-compose exec seedcore-api python -c "from src.seedcore.memory.mw_manager import MwManager; print('MwManager OK')"
```

## Quick Start Guide

### 1. Start the System
```bash
cd docker
docker-compose up -d
```

### 2. Verify Services
```bash
# Check all services are running
docker-compose ps

# Test API health
curl http://localhost/health
```

### 3. Test Tier 0 (Agent Memory)
```bash
# Create an agent
curl -X POST http://localhost/tier0/agents/create \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "test_agent", "role_probs": {"E": 0.7, "S": 0.2, "O": 0.1}}'

# Get agent heartbeat
curl http://localhost/tier0/agents/test_agent/heartbeat

# Execute a task
curl -X POST http://localhost/tier0/agents/test_agent/execute \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_1", "type": "analysis", "complexity": 0.8}'
```

### 4. Test Tier 3 (Flashbulb Memory)
```bash
# Log a high-salience incident
curl -X POST http://localhost/mfb/incidents \
  -H "Content-Type: application/json" \
  -d '{"event_data": {"type": "security_alert", "severity": "high"}, "salience_score": 0.9}'

# Get system statistics
curl http://localhost/mfb/stats
```

## Configuration

### Environment Variables (.env)
```bash
# MySQL Configuration
MYSQL_ROOT_PASSWORD=rootpassword
MYSQL_DATABASE=seedcore
MYSQL_USER=seedcore
MYSQL_PASSWORD=password
MYSQL_PORT=3306
MYSQL_HOST=seedcore-mysql

# PostgreSQL Configuration
PG_DSN=postgresql+psycopg2://postgres:password@postgres:5432/postgres

# Ray Configuration
RAY_HEAD_HOST=ray-head
RAY_HEAD_PORT=10001
```

## Development Status

### ✅ Completed Features
1. **Tier 0 (Ma)**: Full Ray actor implementation with performance tracking
2. **Tier 1 (Mw)**: Working memory with capacity management
3. **Tier 2 (Mlt)**: Long-term memory with compression
4. **Tier 3 (Mfb)**: MySQL-backed flashbulb memory
5. **API Layer**: RESTful endpoints for all tiers
6. **Docker Infrastructure**: Complete multi-service setup
7. **Database Integration**: PostgreSQL, Neo4j, Redis, MySQL

### 🔄 In Progress
- Performance optimization and monitoring
- Advanced compression algorithms
- Cross-tier data migration policies

### 📋 Next Steps

#### Immediate (Next 1-2 weeks)
1. **Energy Model Integration**
   - Implement energy-aware agent selection
   - Add energy consumption tracking
   - Create energy optimization algorithms

2. **Advanced Monitoring**
   - Add Prometheus metrics
   - Create Grafana dashboards
   - Implement alerting system

3. **Performance Testing**
   - Load testing with multiple agents
   - Memory tier performance benchmarks
   - Scalability testing

#### Medium Term (Next 1-2 months)
1. **Machine Learning Integration**
   - Implement salience scoring algorithms
   - Add pattern recognition for flashbulb events
   - Create predictive models for agent performance

2. **Advanced Memory Management**
   - Implement adaptive compression
   - Add memory tier optimization
   - Create intelligent data migration

3. **Distributed Coordination**
   - Implement agent-to-agent communication
   - Add distributed consensus mechanisms
   - Create fault tolerance and recovery

#### Long Term (Next 3-6 months)
1. **Production Readiness**
   - Security hardening
   - Performance optimization
   - Monitoring and alerting
   - Documentation and training

2. **Advanced Features**
   - Multi-tenant support
   - Advanced analytics
   - Integration with external systems

## Troubleshooting

### Common Issues

1. **Ray Worker Not Starting**
   ```bash
   docker-compose logs ray-worker
   # Check for port conflicts or resource issues
   ```

2. **MySQL Connection Issues**
   ```bash
   # Test MySQL connection
   mysql -h 127.0.0.1 -P 3306 -u seedcore -ppassword seedcore
   ```

3. **API Endpoints Not Responding**
   ```bash
   # Check API logs
   docker-compose logs seedcore-api
   # Verify all dependencies are running
   docker-compose ps
   ```

### Debug Commands
```bash
# View all logs
docker-compose logs

# Restart specific service
docker-compose restart seedcore-api

# Clean restart
docker-compose down -v && docker-compose up -d --build
```

## Contributing

1. Follow the existing code structure
2. Add tests for new features
3. Update documentation
4. Use conventional commit messages
5. Test with Docker before submitting

## License

Apache License 2.0 - See LICENSE file for details. 