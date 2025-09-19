# Graph-Aware Tier 0 Memory Manager

The Tier 0 Memory Manager has been enhanced with graph-aware capabilities that allow it to reconcile Ray agents against a canonical graph (Neo4j, etc.) rather than relying on ad-hoc calls.

## Key Features

### 1. Desired-State → Actual-State Reconciliation

The manager can now maintain agents based on specifications defined in your graph:

- **AgentSpec**: Defines agent capabilities, resources, and metadata
- **OrganSpec**: Defines organ capabilities and policies
- **GraphClient**: Abstract interface for graph operations

### 2. Skill/Model/Policy-Aware Task Routing

Tasks are now routed based on agent capabilities defined in the graph:

- **Skills**: Agents must have required skills (e.g., "image_processing", "text_analysis")
- **Models**: Agents must have required models (e.g., "yolo_v8", "bert-base")
- **Policies**: Agents must satisfy policy requirements (e.g., "no_external_egress")
- **Organs**: Tasks can be routed to specific organs via `organ_id`

### 3. Policy Guardrails

Simple policy enforcement before task execution:

- Block tasks requiring external network if agent has "no_external_egress" policy
- Extensible for more complex policy engines (OPA/Rego)

## Usage

### Basic Setup

```python
from seedcore.tier0.tier0_manager import get_tier0_manager
from seedcore.tier0.specs import AgentSpec, MockGraphClient

# Get manager instance
manager = get_tier0_manager()

# Create agent specifications
agent_specs = [
    AgentSpec(
        agent_id="vision_agent_1",
        organ_id="vision_organ",
        skills=["image_processing", "object_detection"],
        models=["yolo_v8", "resnet50"],
        resources={"num_cpus": 2.0, "num_gpus": 1.0},
        metadata={"policies": "privacy_policy,data_retention_policy"}
    )
]

# Attach graph client
graph_client = MockGraphClient(agent_specs)
manager.attach_graph(graph_client)

# Run reconciliation
manager.reconcile_from_graph()
```

### Graph-Aware Task Routing

```python
# Task with specific requirements
task_data = {
    "task_type": "image_analysis",
    "required_skills": ["image_processing", "object_detection"],
    "required_models": ["yolo_v8"],
    "organ_id": "vision_organ",
    "data": {"image_path": "/path/to/image.jpg"}
}

# Route to best qualified agent
result = manager.execute_task_on_graph_best(task_data)
```

### Periodic Reconciliation

```python
# Start automatic reconciliation every 15 seconds
manager.start_graph_reconciler(interval=15)
```

## Configuration

### Environment Variables

- `TIER0_STRICT_RECONCILE`: Set to "true" to automatically archive unmanaged agents
- `SEEDCORE_NS`: Preferred Ray namespace (defaults to "seedcore-dev")
- `RAY_NAMESPACE`: Fallback Ray namespace

### Graph Client Implementation

Implement the `GraphClient` interface for your graph database:

```python
class Neo4jGraphClient(GraphClient):
    def __init__(self, uri, user, password):
        # Initialize Neo4j connection
        pass
    
    def list_agent_specs(self) -> List[AgentSpec]:
        # Query Neo4j for agent specifications
        pass
    
    def list_organ_specs(self) -> List[OrganSpec]:
        # Query Neo4j for organ specifications
        pass
```

## Graph Schema

### Agent Node
```cypher
(agent:Agent {
  id: "agent_1",
  organ_id: "vision_organ",
  skills: ["image_processing", "object_detection"],
  models: ["yolo_v8", "resnet50"],
  resources: {num_cpus: 2.0, num_gpus: 1.0},
  policies: "privacy_policy,data_retention_policy"
})
```

### Organ Node
```cypher
(organ:Organ {
  id: "vision_organ",
  provides_skills: ["image_processing", "object_detection"],
  uses_services: ["camera_service", "storage_service"],
  governed_by_policies: ["privacy_policy", "data_retention_policy"]
})
```

### Relationships
- `(agent)-[:MEMBER_OF]->(organ)`
- `(organ)-[:PROVIDES]->(skill)`
- `(agent)-[:USES]->(model)`
- `(organ)-[:GOVERNED_BY]->(policy)`

## Example

See `examples/graph_aware_example.py` for a complete working example demonstrating:

- Creating agent and organ specifications
- Attaching a graph client
- Running reconciliation
- Testing graph-aware task routing
- Policy enforcement

## Migration from Ad-Hoc Management

1. **Define your graph schema** with agents, organs, skills, models, and policies
2. **Implement a GraphClient** for your graph database
3. **Attach the client** to the manager: `manager.attach_graph(graph_client)`
4. **Run reconciliation** to create agents: `manager.reconcile_from_graph()`
5. **Use graph-aware routing** for tasks: `manager.execute_task_on_graph_best(task_data)`
6. **Enable periodic reconciliation** for ongoing sync: `manager.start_graph_reconciler()`

This approach provides a more robust, scalable, and maintainable way to manage your Ray agents based on your canonical data layer.
