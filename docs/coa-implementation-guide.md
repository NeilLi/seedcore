# Cognitive Organism Architecture (COA) Implementation Guide

## Overview

This document provides a comprehensive guide to the Cognitive Organism Architecture (COA) implementation in SeedCore, including the 3-organ, 3-agent system based on "The Cognitive Organism" principles.

## Architecture Overview

### COA Principles

The Cognitive Organism Architecture implements a "swarm-of-swarms" model with:

- **Organs**: Specialized containers for pools of agents
- **Agents**: Ray actors with private memory and performance tracking
- **OrganismManager**: Central coordinator for organ and agent lifecycle

### System Structure

```
OrganismManager (Central Coordinator)
├── Cognitive Organ (Reasoning & Planning)
│   └── 1 Cognitive Agent
├── Actuator Organ (Action Execution)
│   └── 1 Actuator Agent
└── Utility Organ (System Management)
    └── 1 Utility Agent
```

## Implementation Details

### Configuration

The COA system is configured in `src/seedcore/config/defaults.yaml`:

```yaml
seedcore:
  # ... existing configuration ...
  
  # COA Organism Configuration
  organism:
    organ_types:
      - id: "cognitive_organ_1"
        type: "Cognitive"
        description: "Handles reasoning, planning, and complex task decomposition."
        agent_count: 1
      - id: "actuator_organ_1"
        type: "Actuator"
        description: "Executes actions and interacts with external APIs."
        agent_count: 1
      - id: "utility_organ_1"
        type: "Utility"
        description: "Manages memory, health checks, and internal system tasks."
        agent_count: 1
```

### Core Components

#### 1. Organ Class (`src/seedcore/organs/base.py`)

The `Organ` class is enhanced to be a stateful Ray actor:

```python
@ray.remote
class Organ:
    def __init__(self, organ_id: str, organ_type: str):
        self.organ_id = organ_id
        self.organ_type = organ_type
        self.agents = {}
        self.agent_handles = {}
    
    async def register_agent(self, agent_id: str, agent_handle):
        """Register an agent with this organ."""
        self.agents[agent_id] = agent_handle
        self.agent_handles[agent_id] = agent_handle
    
    async def get_agent_count(self) -> int:
        """Get the number of agents in this organ."""
        return len(self.agents)
    
    async def select_agent(self, task_type: str = None):
        """Select an appropriate agent for a task."""
        if not self.agents:
            return None
        # Simple round-robin selection
        agent_id = list(self.agents.keys())[0]
        return self.agents[agent_id]
    
    async def run_task(self, task_description: str, **kwargs):
        """Run a task using an agent in this organ."""
        agent = await self.select_agent()
        if not agent:
            return {"error": "No agents available"}
        
        try:
            result = await agent.process_task.remote(task_description, **kwargs)
            return {"success": True, "result": result}
        except Exception as e:
            return {"error": str(e)}
    
    async def get_status(self):
        """Get the status of this organ."""
        return {
            "organ_id": self.organ_id,
            "organ_type": self.organ_type,
            "agent_count": len(self.agents),
            "agent_ids": list(self.agents.keys())
        }
    
    async def get_agent_handles(self):
        """Get all agent handles in this organ."""
        return self.agent_handles
    
    async def remove_agent(self, agent_id: str):
        """Remove an agent from this organ."""
        if agent_id in self.agents:
            del self.agents[agent_id]
        if agent_id in self.agent_handles:
            del self.agent_handles[agent_id]
```

#### 2. OrganismManager (`src/seedcore/organs/organism_manager.py`)

The central coordinator for the COA system:

```python
class OrganismManager:
    def __init__(self):
        self.organs = {}
        self.agent_to_organ_map = {}
        self.organ_configs = []
    
    def load_config(self):
        """Load organ configuration from defaults.yaml."""
        # Loads configuration from src/seedcore/config/defaults.yaml
    
    async def initialize_organism(self):
        """Initialize the complete COA organism."""
        self.load_config()
        await self._create_organs()
        await self._create_and_distribute_agents()
    
    async def _create_organs(self):
        """Create organ actors with persistence handling."""
        for config in self.organ_configs:
            organ_id = config['id']
            organ_type = config['type']
            
            if organ_id not in self.organs:
                try:
                    # Try to get existing organ first
                    try:
                        existing_organ = ray.get_actor(organ_id)
                        self.organs[organ_id] = existing_organ
                    except ValueError:
                        # Create new organ if it doesn't exist
                        self.organs[organ_id] = Organ.options(
                            name=organ_id, 
                            lifetime="detached"
                        ).remote(
                            organ_id=organ_id,
                            organ_type=organ_type
                        )
                except Exception as e:
                    raise
    
    async def _create_and_distribute_agents(self):
        """Create agents and register them with organs."""
        for organ_config in self.organ_configs:
            organ_id = organ_config['id']
            num_agents = organ_config['agent_count']
            organ_handle = self.organs.get(organ_id)
            
            # Get existing agents and manage count
            existing_agent_handles = await organ_handle.get_agent_handles.remote()
            existing_agent_ids = list(existing_agent_handles.keys())
            
            # Remove excess agents if needed
            if len(existing_agent_ids) > num_agents:
                agents_to_remove = existing_agent_ids[num_agents:]
                for agent_id_to_remove in agents_to_remove:
                    await organ_handle.remove_agent.remote(agent_id_to_remove)
            
            # Create new agents or reuse existing ones
            for i in range(num_agents):
                agent_id = f"{organ_id}_agent_{i}"
                
                if agent_id in existing_agent_ids:
                    # Reuse existing agent
                    self.agent_to_organ_map[agent_id] = organ_id
                    continue
                
                # Create new agent
                initial_role_probs = self._get_role_probs_for_organ_type(organ_config['type'])
                agent_handle = RayAgent.remote(
                    agent_id=agent_id,
                    initial_role_probs=initial_role_probs
                )
                
                await organ_handle.register_agent.remote(agent_id, agent_handle)
                self.agent_to_organ_map[agent_id] = organ_id
    
    def _get_role_probs_for_organ_type(self, organ_type: str):
        """Get initial role probabilities based on organ type."""
        if organ_type == "Cognitive":
            return {"reasoning": 0.6, "planning": 0.3, "learning": 0.1}
        elif organ_type == "Actuator":
            return {"action": 0.7, "api_interaction": 0.2, "monitoring": 0.1}
        elif organ_type == "Utility":
            return {"memory": 0.4, "health_check": 0.3, "system_task": 0.3}
        else:
            return {"general": 1.0}
    
    async def get_organism_status(self):
        """Get comprehensive status of the organism."""
        organ_statuses = {}
        total_agents = 0
        
        for organ_id, organ_handle in self.organs.items():
            status = await organ_handle.get_status.remote()
            organ_statuses[organ_id] = status
            total_agents += status['agent_count']
        
        return {
            "organs": organ_statuses,
            "total_agents": total_agents,
            "agent_to_organ_map": self.agent_to_organ_map
        }
    
    async def execute_task_on_organ(self, organ_id: str, task_description: str, **kwargs):
        """Execute a task on a specific organ."""
        if organ_id not in self.organs:
            return {"error": f"Organ {organ_id} not found"}
        
        organ_handle = self.organs[organ_id]
        return await organ_handle.run_task.remote(task_description, **kwargs)
    
    async def execute_task_random_organ(self, task_description: str, **kwargs):
        """Execute a task on a random organ."""
        if not self.organs:
            return {"error": "No organs available"}
        
        import random
        organ_id = random.choice(list(self.organs.keys()))
        return await self.execute_task_on_organ(organ_id, task_description, **kwargs)
```

#### 3. FastAPI Integration (`src/seedcore/telemetry/server.py`)

The FastAPI server integrates the OrganismManager:

```python
from src.seedcore.organs import organism_manager

@app.on_event("startup")
async def startup_event():
    """Initialize Ray and COA organism on startup."""
    # Initialize Ray
    if not ray.is_initialized():
        ray.init(
            address=os.getenv("RAY_ADDRESS", "ray://ray-head:10001"),
            namespace="seedcore"
        )
    
    # Initialize COA organism
    await organism_manager.initialize_organism()

# COA API Endpoints
@app.get("/organism/status")
async def get_organism_status():
    """Get the status of the COA organism."""
    return await organism_manager.get_organism_status()

@app.post("/organism/execute/{organ_id}")
async def execute_task_on_organ(organ_id: str, task: dict):
    """Execute a task on a specific organ."""
    return await organism_manager.execute_task_on_organ(
        organ_id, 
        task["description"], 
        **task.get("parameters", {})
    )

@app.post("/organism/execute/random")
async def execute_task_random_organ(task: dict):
    """Execute a task on a random organ."""
    return await organism_manager.execute_task_random_organ(
        task["description"], 
        **task.get("parameters", {})
    )

@app.get("/organism/summary")
async def get_organism_summary():
    """Get a summary of the organism."""
    status = await organism_manager.get_organism_status()
    return {
        "total_organs": len(status["organs"]),
        "total_agents": status["total_agents"],
        "organ_types": [config["type"] for config in organism_manager.organ_configs]
    }

@app.post("/organism/initialize")
async def initialize_organism():
    """Manually initialize the organism."""
    await organism_manager.initialize_organism()
    return {"message": "Organism initialized successfully"}

@app.post("/organism/shutdown")
async def shutdown_organism():
    """Shutdown the organism (cleanup)."""
    # Implementation for graceful shutdown
    return {"message": "Organism shutdown initiated"}
```

## Usage Examples

### Basic Usage

```python
# Initialize the organism
from src.seedcore.organs import organism_manager

await organism_manager.initialize_organism()

# Get organism status
status = await organism_manager.get_organism_status()
print(f"Total agents: {status['total_agents']}")

# Execute a task
result = await organism_manager.execute_task_on_organ(
    "cognitive_organ_1",
    "Analyze the given data and provide insights"
)
```

### API Usage

```bash
# Get organism status
curl -X GET "http://localhost:8000/organism/status"

# Execute task on specific organ
curl -X POST "http://localhost:8000/organism/execute/cognitive_organ_1" \
  -H "Content-Type: application/json" \
  -d '{"description": "Plan the next action", "parameters": {"priority": "high"}}'

# Execute task on random organ
curl -X POST "http://localhost:8000/organism/execute/random" \
  -H "Content-Type: application/json" \
  -d '{"description": "Process the request"}'
```

## Testing

### Test Script

Use the provided test script to verify COA functionality:

```bash
# Copy test script to container
docker cp test_organism.py seedcore-api:/tmp/

# Run tests
docker exec -it seedcore-api python3 /tmp/test_organism.py
```

### Verification Steps

1. **Check Organ Status**: Verify all 3 organs are active
2. **Check Agent Distribution**: Confirm 1 agent per organ
3. **Test Task Execution**: Execute tasks on different organs
4. **Verify Persistence**: Restart and check organ persistence

## Troubleshooting

### Common Issues

1. **Organ Creation Failures**
   - Check Ray cluster status
   - Verify configuration file syntax
   - Check for naming conflicts

2. **Agent Distribution Issues**
   - Verify agent count configuration
   - Check organ availability
   - Review error logs

3. **Persistence Problems**
   - Use cleanup script for fresh start
   - Check detached actor status
   - Verify Ray namespace

### Cleanup Script

For complete system reset:

```bash
# Copy cleanup script
docker cp cleanup_organs.py seedcore-api:/tmp/

# Execute cleanup
docker exec -it seedcore-api python3 /tmp/cleanup_organs.py

# Restart API container
docker compose restart seedcore-api
```

## Best Practices

1. **Configuration Management**
   - Use YAML configuration for flexibility
   - Validate configuration on startup
   - Document organ types and purposes

2. **Error Handling**
   - Implement graceful error recovery
   - Log all organ and agent operations
   - Provide meaningful error messages

3. **Resource Management**
   - Monitor agent memory usage
   - Implement agent lifecycle management
   - Use appropriate Ray actor lifetimes

4. **Testing and Validation**
   - Test organ initialization
   - Validate agent distribution
   - Verify task execution

## Future Enhancements

1. **Dynamic Scaling**: Add/remove agents based on workload
2. **Load Balancing**: Implement intelligent task distribution
3. **Health Monitoring**: Add comprehensive health checks
4. **Metrics Collection**: Track performance and usage metrics
5. **Advanced Scheduling**: Implement priority-based task scheduling

## Conclusion

The COA implementation provides a robust foundation for distributed cognitive computing. The 3-organ, 3-agent system demonstrates the principles of specialized organ functions while maintaining simplicity and manageability.

For more information, refer to:
- [Ray Cluster Diagnostics](../docs/ray-cluster-diagnostics.md)
- [Docker Compose Configuration](../docker/docker-compose.yml)
- [Ray Documentation](https://docs.ray.io/) 