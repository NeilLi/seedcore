# SeedCore API Reference

## Base URL
```
http://localhost
```

## Authentication
Currently, no authentication is required for API endpoints.

## Response Format
All API responses follow this format:
```json
{
  "success": true|false,
  "data": {...},
  "message": "Optional message"
}
```

## Tier 0: Per-Agent Memory (Ma) Endpoints

### Create Agent
**POST** `/tier0/agents/create`

Creates a new Ray agent actor with private memory.

**Request Body:**
```json
{
  "agent_id": "string",
  "role_probs": {
    "E": 0.7,
    "S": 0.2,
    "O": 0.1
  }
}
```

**Response:**
```json
{
  "success": true,
  "agent_id": "test_agent_1",
  "message": "Agent test_agent_1 created"
}
```

### Create Multiple Agents
**POST** `/tier0/agents/create_batch`

Creates multiple agents in batch.

**Request Body:**
```json
{
  "agent_configs": [
    {
      "agent_id": "agent_1",
      "role_probs": {"E": 0.7, "S": 0.2, "O": 0.1}
    },
    {
      "agent_id": "agent_2", 
      "role_probs": {"E": 0.2, "S": 0.7, "O": 0.1}
    }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "created_ids": ["agent_1", "agent_2"],
  "message": "Created 2 agents in batch"
}
```

### List Agents
**GET** `/tier0/agents`

Returns list of all agent IDs.

**Response:**
```json
{
  "success": true,
  "agents": ["agent_1", "agent_2", "test_agent_1"]
}
```

### Execute Task on Specific Agent
**POST** `/tier0/agents/{agent_id}/execute`

Executes a task on a specific agent.

**Request Body:**
```json
{
  "task_id": "task_1",
  "type": "data_analysis",
  "complexity": 0.8,
  "payload": "Sample data for analysis"
}
```

**Response:**
```json
{
  "success": true,
  "result": {
    "agent_id": "test_agent_1",
    "task_processed": true,
    "success": true,
    "quality": 0.5757745938882686,
    "capability_score": 0.5330309837555307,
    "mem_util": 0.05
  }
}
```

### Execute Task on Random Agent
**POST** `/tier0/agents/execute_random`

Executes a task on a randomly selected agent.

**Request Body:** Same as specific agent execution.

**Response:** Same format as specific agent execution.

### Get Agent Heartbeat
**GET** `/tier0/agents/{agent_id}/heartbeat`

Returns the current state and performance metrics of an agent.

**Response:**
```json
{
  "success": true,
  "heartbeat": {
    "timestamp": 1753414292.2324848,
    "agent_id": "test_agent_1",
    "state_embedding_h": [0.4247836486852156, ...],
    "role_probs": {"E": 0.7, "S": 0.2, "O": 0.1},
    "performance_metrics": {
      "success_rate": 1.0,
      "quality_score": 0.5757745938882686,
      "capability_score_c": 0.5330309837555307,
      "mem_util": 0.05,
      "tasks_processed": 1,
      "successful_tasks": 1
    },
    "memory_metrics": {
      "memory_writes": 0,
      "memory_hits_on_writes": 0,
      "salient_events_logged": 0,
      "total_compression_gain": 0.0
    },
    "local_state": {
      "skill_deltas": {},
      "peer_interactions": {},
      "recent_quality_scores": []
    },
    "lifecycle": {
      "created_at": 1753414287.6963117,
      "last_heartbeat": 1753414287.6963127,
      "uptime": 4.536195755004883
    }
  }
}
```

### Get All Agent Heartbeats
**GET** `/tier0/agents/heartbeats`

Returns heartbeats from all agents.

**Response:**
```json
{
  "success": true,
  "heartbeats": {
    "agent_1": {...},
    "agent_2": {...}
  }
}
```

### Get System Summary
**GET** `/tier0/summary`

Returns a summary of the entire Tier 0 system.

**Response:**
```json
{
  "success": true,
  "summary": {
    "total_agents": 3,
    "total_tasks_processed": 15,
    "average_capability_score": 0.623,
    "average_memory_utilization": 0.12,
    "total_memory_writes": 45,
    "total_peer_interactions": 23,
    "last_heartbeat_collection": 1753414292.2324848,
    "collection_interval": 5.0,
    "status": "active"
  }
}
```

### Reset Agent Metrics
**POST** `/tier0/agents/{agent_id}/reset`

Resets all performance metrics for a specific agent.

**Response:**
```json
{
  "success": true,
  "message": "Metrics reset for agent test_agent_1"
}
```

### Shutdown All Agents
**POST** `/tier0/agents/shutdown`

Shuts down all agent actors.

**Response:**
```json
{
  "success": true,
  "message": "All agents shut down"
}
```

## Tier 3: Flashbulb Memory (Mfb) Endpoints

### Log Incident
**POST** `/mfb/incidents`

Logs a high-salience incident to flashbulb memory.

**Request Body:**
```json
{
  "event_data": {
    "type": "security_alert",
    "severity": "high",
    "source": "firewall",
    "details": "Unauthorized access attempt detected"
  },
  "salience_score": 0.9
}
```

**Response:**
```json
{
  "success": true,
  "incident_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Incident logged successfully"
}
```

### Get Incident
**GET** `/mfb/incidents/{incident_id}`

Retrieves a specific incident by ID.

**Response:**
```json
{
  "success": true,
  "incident": {
    "incident_id": "550e8400-e29b-41d4-a716-446655440000",
    "salience_score": 0.9,
    "event_data": {
      "type": "security_alert",
      "severity": "high",
      "source": "firewall",
      "details": "Unauthorized access attempt detected"
    },
    "created_at": "2024-01-15T10:30:00Z"
  }
}
```

### Query Incidents
**GET** `/mfb/incidents`

Query incidents with optional filters.

**Query Parameters:**
- `start_time` (optional): ISO format start time
- `end_time` (optional): ISO format end time  
- `salience_threshold` (optional): Minimum salience score (default: 0.8)

**Example:**
```
GET /mfb/incidents?start_time=2024-01-15T00:00:00Z&salience_threshold=0.7
```

**Response:**
```json
{
  "success": true,
  "incidents": [
    {
      "incident_id": "550e8400-e29b-41d4-a716-446655440000",
      "salience_score": 0.9,
      "event_data": {...},
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "total_count": 1
}
```

### Get System Statistics
**GET** `/mfb/stats`

Returns flashbulb memory system statistics.

**Response:**
```json
{
  "success": true,
  "stats": {
    "total_incidents": 15,
    "average_salience": 0.75,
    "high_salience_incidents": 8,
    "incidents_last_24h": 3,
    "storage_usage_bytes": 1024000
  }
}
```

### Delete Incident
**DELETE** `/mfb/incidents/{incident_id}`

Deletes a specific incident.

**Response:**
```json
{
  "success": true,
  "message": "Incident deleted successfully"
}
```

## Health Check

### System Health
**GET** `/health`

Returns overall system health status.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",
  "services": {
    "ray": "healthy",
    "postgresql": "healthy", 
    "neo4j": "healthy",
    "redis": "healthy",
    "mysql": "healthy"
  }
}
```

## Error Responses

### 400 Bad Request
```json
{
  "success": false,
  "error": "Invalid request parameters",
  "details": "agent_id is required"
}
```

### 404 Not Found
```json
{
  "success": false,
  "error": "Resource not found",
  "details": "Agent test_agent_999 not found"
}
```

### 500 Internal Server Error
```json
{
  "success": false,
  "error": "Internal server error",
  "details": "Database connection failed"
}
```

## Rate Limiting

Currently, no rate limiting is implemented. Consider implementing rate limiting for production use.

## Scenarios

### Scenario 1: Collaborative Task with Knowledge Gap

This scenario demonstrates the multi-tier memory system's ability to handle cache misses and knowledge retrieval across memory tiers.

#### Prerequisites

1. **Services Running**: Ensure all Docker services are healthy
2. **Memory Population**: Pre-populate Long-Term Memory with test data
3. **Ray Cluster**: Verify Ray head and worker nodes are operational

#### Memory Manager Endpoints

The scenario utilizes the following memory management components:

**Working Memory (Mw)**
- **Backend**: Redis
- **Purpose**: Fast-access cache for active data
- **TTL**: 45 seconds (configurable)
- **Capacity**: Limited by Redis memory

**Long-Term Memory (Mlt)**
- **Backend**: PostgreSQL (PgVector) + Neo4j
- **Purpose**: Persistent storage for knowledge retrieval
- **Query Types**: Vector similarity + graph relationships
- **Capacity**: Limited by database storage

#### Agent Memory Integration

**RayAgent Memory Methods**:
```python
# Knowledge retrieval with automatic escalation
def find_knowledge(self, fact_id: str) -> Optional[Dict[str, Any]]:
    # 1. Query Mw first (fast access)
    # 2. On cache miss, escalate to Mlt
    # 3. Cache retrieved knowledge in Mw
    # 4. Return knowledge to agent

# Collaborative task execution
def execute_collaborative_task(self, task_info: Dict[str, Any]) -> Dict[str, Any]:
    # 1. Extract required knowledge from task
    # 2. Retrieve knowledge using find_knowledge()
    # 3. Execute task with retrieved knowledge
    # 4. Update performance metrics in Ma
    # 5. Return task results
```

#### Memory Interaction Flow

```
Task Request
    ↓
Agent Memory Check (Ma)
    ↓
Working Memory Query (Mw)
    ↓
Cache Hit? → Yes → Use Cached Data
    ↓ No
Long-Term Memory Query (Mlt)
    ↓
Knowledge Found? → Yes → Cache in Mw → Use Data
    ↓ No
Task Failure (Knowledge Not Available)
```

#### Performance Metrics

The scenario tracks the following metrics:

- **Cache Hit Rate**: Percentage of Mw queries that result in hits
- **Escalation Rate**: Percentage of queries that escalate to Mlt
- **Retrieval Success Rate**: Percentage of Mlt queries that find knowledge
- **Task Success Rate**: Percentage of tasks completed successfully
- **Response Time**: Time from task request to completion

#### Monitoring and Debugging

**Key Log Messages**:
```
✅ WorkingMemoryManager for Organ 'organ_for_Agent-X' connected to Redis.
✅ LongTermMemoryManager initialized.
🔍 Querying holon by ID: fact_X_uuid
✅ Found holon: fact_X_uuid
❌ Failed to initialize memory managers for Agent-X: No module named 'redis'
```

**Health Check Commands**:
```bash
# Check memory manager connections
docker-compose exec seedcore-api python -c "
from src.seedcore.memory.mw_manager import MwManager
from src.seedcore.memory.long_term_memory import LongTermMemoryManager
print('Memory managers OK')
"

# Test Ray agent initialization
docker-compose exec ray-head python -c "
from src.seedcore.agents.ray_actor import RayAgent
print('RayAgent OK')
"
```

## Testing Examples

### Using curl

```bash
# Create an agent
curl -X POST http://localhost/tier0/agents/create \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "test_agent", "role_probs": {"E": 0.7, "S": 0.2, "O": 0.1}}'

# Execute a task
curl -X POST http://localhost/tier0/agents/test_agent/execute \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_1", "type": "analysis", "complexity": 0.8}'

# Log a flashbulb incident
curl -X POST http://localhost/mfb/incidents \
  -H "Content-Type: application/json" \
  -d '{"event_data": {"type": "alert"}, "salience_score": 0.9}'
```

### Using Python requests

```python
import requests

# Create agent
response = requests.post('http://localhost/tier0/agents/create', json={
    'agent_id': 'test_agent',
    'role_probs': {'E': 0.7, 'S': 0.2, 'O': 0.1}
})

# Execute task
response = requests.post('http://localhost/tier0/agents/test_agent/execute', json={
    'task_id': 'task_1',
    'type': 'analysis',
    'complexity': 0.8
})

# Get heartbeat
response = requests.get('http://localhost/tier0/agents/test_agent/heartbeat')
``` 