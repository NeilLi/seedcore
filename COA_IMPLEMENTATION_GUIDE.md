# COA 3-Organ, 20-Agent Implementation Guide

## Overview

This document describes the implementation of the Cognitive Organism Architecture (COA) framework with 3 organs and 20 agents, as specified in the theoretical documents. The implementation follows the "swarm-of-swarms" model where organs act as specialized containers for pools of agents.

## Architecture

### Organ Types

1. **Cognitive Organ** (`cognitive_organ_1`)
   - **Purpose**: Handles reasoning, planning, and complex task decomposition
   - **Agent Count**: 8 agents
   - **Role Distribution**: High S (reasoning) focus: `{'E': 0.3, 'S': 0.6, 'O': 0.1}`

2. **Actuator Organ** (`actuator_organ_1`)
   - **Purpose**: Executes actions and interacts with external APIs
   - **Agent Count**: 6 agents
   - **Role Distribution**: High E (action) focus: `{'E': 0.7, 'S': 0.2, 'O': 0.1}`

3. **Utility Organ** (`utility_organ_1`)
   - **Purpose**: Manages memory, health checks, and internal system tasks
   - **Agent Count**: 6 agents
   - **Role Distribution**: High O (observation) focus: `{'E': 0.2, 'S': 0.3, 'O': 0.5}`

### Total: 20 Agents (8 + 6 + 6)

## Implementation Details

### 1. Configuration (`src/seedcore/config/defaults.yaml`)

The organism configuration is defined in the YAML config file:

```yaml
seedcore:
  # ... existing configuration ...
  
  # COA Organism Configuration
  organism:
    organ_types:
      - id: "cognitive_organ_1"
        type: "Cognitive"
        description: "Handles reasoning, planning, and complex task decomposition."
        agent_count: 8
      - id: "actuator_organ_1"
        type: "Actuator"
        description: "Executes actions and interacts with external APIs."
        agent_count: 6
      - id: "utility_organ_1"
        type: "Utility"
        description: "Manages memory, health checks, and internal system tasks."
        agent_count: 6
```

### 2. Enhanced Organ Class (`src/seedcore/organs/base.py`)

The `Organ` class has been enhanced to be a Ray actor with stateful management:

```python
@ray.remote
class Organ:
    def __init__(self, organ_id: str, organ_type: str):
        self.organ_id = organ_id
        self.organ_type = organ_type
        self.agents: Dict[str, 'RayAgent'] = {}

    def register_agent(self, agent_id: str, agent_handle: 'RayAgent'):
        """Registers a Ray agent actor with this organ."""
        self.agents[agent_id] = agent_handle

    async def run_task(self, task):
        """Selects an agent and executes a task, returning the result."""
        agent = self.select_agent(task)
        result_ref = agent.execute_task.remote(task)
        return await result_ref
```

### 3. OrganismManager (`src/seedcore/organs/organism_manager.py`)

The `OrganismManager` orchestrates the entire organism:

```python
class OrganismManager:
    def __init__(self, config_path: str = "src/seedcore/config/defaults.yaml"):
        self.organs: Dict[str, ray.actor.ActorHandle] = {}
        self.agent_to_organ_map: Dict[str, str] = {}
        self.organ_configs: List[Dict[str, Any]] = []
        self._load_config(config_path)
        self._initialized = False

    async def initialize_organism(self):
        """Creates all organs and populates them with agents based on the config."""
        self._create_organs()
        await self._create_and_distribute_agents()
        self._initialized = True
```

### 4. API Integration (`src/seedcore/telemetry/server.py`)

The FastAPI server has been extended with organism endpoints:

- `GET /organism/status` - Get status of all organs
- `GET /organism/summary` - Get detailed organism summary
- `POST /organism/execute/{organ_id}` - Execute task on specific organ
- `POST /organism/execute/random` - Execute task on random organ
- `POST /organism/initialize` - Manually initialize organism
- `POST /organism/shutdown` - Shutdown organism

## Usage

### Starting the System

1. **Start the Docker containers**:
   ```bash
   docker-compose up -d --build
   ```

2. **Check initialization logs**:
   ```bash
   docker logs seedcore-api
   ```

3. **Verify organism status**:
   ```bash
   curl http://localhost/organism/status | jq
   ```

### Testing the Implementation

Run the test script to verify everything is working:

```bash
python3 test_organism.py
```

### API Examples

#### Get Organism Status
```bash
curl http://localhost/organism/status
```

Expected response:
```json
{
  "success": true,
  "data": [
    {
      "organ_id": "cognitive_organ_1",
      "organ_type": "Cognitive",
      "agent_count": 8,
      "agent_ids": ["cognitive_organ_1_agent_0", "cognitive_organ_1_agent_1", ...]
    },
    {
      "organ_id": "actuator_organ_1",
      "organ_type": "Actuator",
      "agent_count": 6,
      "agent_ids": ["actuator_organ_1_agent_0", "actuator_organ_1_agent_1", ...]
    },
    {
      "organ_id": "utility_organ_1",
      "organ_type": "Utility",
      "agent_count": 6,
      "agent_ids": ["utility_organ_1_agent_0", "utility_organ_1_agent_1", ...]
    }
  ]
}
```

#### Execute Task on Cognitive Organ
```bash
curl -X POST http://localhost/organism/execute/cognitive_organ_1 \
  -H "Content-Type: application/json" \
  -d '{
    "task_data": {
      "type": "reasoning_task",
      "description": "Analyze complex problem",
      "parameters": {"complexity": "high"}
    }
  }'
```

#### Execute Task on Random Organ
```bash
curl -X POST http://localhost/organism/execute/random \
  -H "Content-Type: application/json" \
  -d '{
    "task_data": {
      "type": "general_task",
      "description": "Process general task",
      "parameters": {"priority": "medium"}
    }
  }'
```

## Monitoring

### Ray Dashboard
Access the Ray dashboard at: http://localhost:8265

### Real-time Logs
```bash
docker logs -f seedcore-api
```

### Cluster Status
```bash
curl http://localhost/ray/status
```

## Key Features

### 1. Stateful Ray Actors
- Each organ is a persistent Ray actor with `lifetime="detached"`
- Agents are Ray actors managed by their respective organs
- State persists across API calls and system restarts

### 2. Role-Based Agent Distribution
- Agents are created with role probabilities based on their organ type
- Cognitive agents have high S (reasoning) probability
- Actuator agents have high E (action) probability
- Utility agents have high O (observation) probability

### 3. Task Execution
- Tasks can be executed on specific organs or randomly selected organs
- Each organ selects an appropriate agent for task execution
- Results are returned asynchronously

### 4. Health Monitoring
- Comprehensive status endpoints for monitoring organism health
- Detailed summaries including agent counts and organ status
- Error handling and graceful degradation

## Theoretical Alignment

This implementation directly reflects the COA framework principles:

1. **Swarm-of-Swarms Model**: Organs contain pools of agents, creating a hierarchical swarm structure
2. **Specialized Organs**: Each organ has a distinct type and role in the cognitive system
3. **Energy-Aware Selection**: Framework is in place for energy-aware agent selection (TODO: implement full scoring proxy)
4. **Scalable Architecture**: Ray-based implementation allows for horizontal scaling

## Future Enhancements

1. **Energy-Aware Scoring Proxy**: Implement the full energy-aware agent selection algorithm
2. **Dynamic Agent Creation**: Allow runtime creation of new agents based on workload
3. **Organ Communication**: Implement inter-organ communication protocols
4. **Advanced Monitoring**: Add detailed performance metrics and health checks
5. **Load Balancing**: Implement intelligent load balancing across organs

## Troubleshooting

### Common Issues

1. **Organism not initialized**
   - Check Ray cluster status: `curl http://localhost/ray/status`
   - Verify Ray is running: `docker ps | grep ray`
   - Check logs: `docker logs seedcore-api`

2. **Agent creation failures**
   - Verify Ray cluster has sufficient resources
   - Check for Ray actor creation errors in logs
   - Ensure configuration file is properly formatted

3. **Task execution failures**
   - Verify organism is initialized
   - Check agent availability in target organ
   - Review task format and parameters

### Debug Commands

```bash
# Check organism status
curl http://localhost/organism/status

# Get detailed summary
curl http://localhost/organism/summary

# Check Ray cluster
curl http://localhost/ray/status

# View logs
docker logs seedcore-api

# Test specific organ
curl -X POST http://localhost/organism/execute/cognitive_organ_1 \
  -H "Content-Type: application/json" \
  -d '{"task_data": {"type": "test"}}'
```

## Conclusion

This implementation provides a robust foundation for the COA framework with 3 organs and 20 agents. The system is production-ready with comprehensive monitoring, error handling, and API endpoints. The architecture is scalable and can be extended with additional organs and agents as needed. 