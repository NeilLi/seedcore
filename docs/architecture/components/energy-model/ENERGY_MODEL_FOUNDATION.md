# Energy Model Foundation

## Overview

The Energy Model Foundation implements the core energy-aware agent selection and optimization system as defined by the Cognitive Organism Architecture (COA). This system uses the Unified Energy Function to make intelligent decisions about agent selection and task allocation.

## Architecture

### Core Components

1. **Energy Calculator** (`src/seedcore/energy/calculator.py`)
   - Implements the Unified Energy Function with all five core energy terms
   - Calculates pairwise collaboration, entropy, regularization, and memory energy
   - **NEW**: EnergyLedger for incremental updates and event-driven energy tracking
   - **NEW**: Event handlers for real-time energy updates

2. **Energy Optimizer** (`src/seedcore/energy/optimizer.py`)
   - Provides energy-aware agent selection using gradient proxies
   - Implements task complexity estimation and role mapping
   - **NEW**: Enhanced scoring with memory utilization and state complexity penalties

3. **Agent Energy Tracking** (`src/seedcore/agents/ray_actor.py`)
   - Tracks energy state and role probabilities for each agent
   - Provides methods for energy state updates and retrieval
   - **NEW**: AgentState dataclass with capability and memory utility tracking
   - **NEW**: Real-time energy event emission for ledger updates

4. **Tier0 Manager Integration** (`src/seedcore/agents/tier0_manager.py`)
   - Integrates energy-aware selection into agent management
   - Provides `execute_task_on_best_agent()` method
   - **NEW**: Fallback to random selection if energy optimizer fails

## Energy Terms

### 1. Pair Energy (E_pair)
**Formula**: `-∑(wij * sim(hi, hj))`

Rewards stable and successful agent collaborations by calculating cosine similarity between agent state embeddings.

### 2. Entropy Energy (E_entropy)
**Formula**: `-α * H(p)`

Maintains role diversity for exploration by calculating entropy of role probability distributions.

### 3. Regularization Energy (E_reg)
**Formula**: `λ_reg * ||s||₂²`

Penalizes overall state complexity to prevent overfitting and maintain system stability.

### 4. Memory Energy (E_mem)
**Formula**: `β_mem * CostVQ(M)`

Accounts for memory pressure and information loss using the CostVQ function from the memory system.

### 5. Hyper Energy (E_hyper)
**Formula**: Currently stubbed as 0.0

Future implementation for complex pattern tracking and hypergraph-based energy calculations.

## Agent Selection Process

### Suitability Scoring
The system calculates agent suitability scores using the formula:
```
score_i = w_pair * E_pair_delta(i,t) + w_hyper * E_hyper_delta(i,t) - w_explore * ΔH + w_mem * mem_penalty + w_state * state_penalty
```

### Task-Role Mapping
- **Optimization tasks** → Specialist agents (S)
- **Exploration tasks** → Explorer agents (E)
- **Analysis tasks** → Specialist agents (S)
- **Discovery tasks** → Explorer agents (E)
- **General tasks** → Explorer agents (E) by default

### Selection Criteria
1. **Capability Score**: Higher capability reduces energy cost
2. **Role Match**: Better role match for task type
3. **Current Energy State**: Considers agent's current energy contribution
4. **Task Complexity**: Adjusts scoring based on task difficulty
5. **Memory Utilization**: Penalizes high memory pressure
6. **State Complexity**: Penalizes high state vector norms

## Usage

### Basic Energy Calculation
```python
from src.seedcore.energy.calculator import calculate_total_energy

# Calculate total system energy
energy_data = calculate_total_energy(agents, memory_system, weights)
print(f"Total Energy: {energy_data['total']}")
```

### Energy-Aware Task Execution
```python
from src.seedcore.agents.tier0_manager import Tier0MemoryManager

# Create manager and execute task with energy optimization
tier0_manager = Tier0MemoryManager()
result = tier0_manager.execute_task_on_best_agent(task_data)
```

### Agent Suitability Scoring
```python
from src.seedcore.energy.optimizer import calculate_agent_suitability_score

# Score an agent for a specific task
score = calculate_agent_suitability_score(agent, task_data, weights)
```

### Energy Ledger Management
```python
from src.seedcore.energy.calculator import EnergyLedger, on_pair_success

# Create and update energy ledger
ledger = EnergyLedger()
event = {'type': 'pair_success', 'agents': ['agent1', 'agent2'], 'success': 0.8, 'sim': 0.7}
on_pair_success(event, ledger)
print(f"Total Energy: {ledger.get_total()}")
```

## Configuration

### Energy Weights
Default weights for energy terms:
```python
weights = {
    'alpha': 0.1,        # Entropy energy weight
    'lambda_reg': 0.01,  # Regularization weight
    'beta_mem': 0.05,    # Memory energy weight
    'w_pair': 1.0,       # Pair energy weight in selection
    'w_hyper': 1.0,      # Hyper energy weight in selection
    'w_explore': 0.2,    # Exploration weight in selection
    'w_mem': 0.3,        # Memory penalty weight
    'w_state': 0.01      # State complexity weight
}
```

### Task Complexity Factors
- **Task Type**: optimization (+0.3), exploration (+0.2)
- **Task Size**: large (+0.2), small (-0.1)
- **Urgency**: urgent (+0.1)

## Testing

### Basic Test Suite
Run the comprehensive test suite:
```bash
docker compose exec seedcore-api python -m scripts.test_energy_model
```

### Energy Calibration
Run energy calibration to optimize weights:
```bash
docker compose exec seedcore-api python -m scripts.test_energy_calibration
```

The tests validate:
- Energy calculation accuracy
- Agent selection logic
- Task execution with energy optimization
- Ray integration and remote calls
- Energy ledger functionality
- Event-driven energy updates
- Weight optimization

## Performance Considerations

### Ray Integration
- All agent interactions use Ray remote calls
- Energy calculations are distributed across the cluster
- State embeddings and heartbeats are retrieved asynchronously
- **NEW**: Runtime context guards prevent duplicate bootstrap calls

### Memory Usage
- Energy state tracking adds minimal overhead per agent
- Memory energy calculations integrate with existing memory system
- Regularization prevents unbounded state growth
- **NEW**: Incremental ledger updates reduce computation overhead

### Scalability
- Energy calculations scale with number of agents O(n²) for pair energy
- Agent selection scales linearly O(n) with number of agents
- Ray distribution allows horizontal scaling
- **NEW**: Event-driven updates improve real-time performance

## Health Monitoring

### Health Check Endpoint
```bash
curl http://localhost:8000/healthz/energy
```

Returns:
```json
{
  "status": "healthy",
  "message": "Energy system operational",
  "timestamp": 1234567890.123,
  "energy_snapshot": {
    "ts": 1234567890.123,
    "E_terms": {...},
    "deltaE_last": 0.0,
    "pair_stats_count": 5,
    "hyper_stats_count": 0,
    "role_entropy_count": 0,
    "mem_stats_count": 0
  },
  "checks": {
    "energy_calculation": "pass",
    "ledger_accessible": "pass",
    "pair_stats_count": 5,
    "hyper_stats_count": 0,
    "role_entropy_count": 0,
    "mem_stats_count": 0
  }
}
```

### Energy Gradient Endpoint
```bash
curl http://localhost:8000/energy/gradient
```

## Troubleshooting

### Common Issues

1. **Ray Remote Call Errors**
   - Ensure all agent method calls use `.remote()`
   - Check Ray cluster connectivity
   - **NEW**: Verify runtime context guards are working

2. **Memory System Integration**
   - Verify memory system has required attributes (Mw, Mlt, bytes_used, hit_count, datastore)
   - Check CostVQ function availability
   - **NEW**: Ensure energy events are being emitted correctly

3. **Energy Calculation Errors**
   - Validate agent state embeddings are 128-dimensional
   - Ensure role probabilities sum to 1.0
   - **NEW**: Check ledger event handlers are functioning

4. **Duplicate Bootstrap Messages**
   - **NEW**: Runtime context guards should prevent worker process bootstrapping
   - Check Ray cluster configuration
   - Verify actor namespace settings

5. **Docker Compose Warnings**
   - **FIXED**: PYTHONPATH warnings eliminated by using direct environment variable assignment
   - Use `PYTHONPATH: /app:/app/src` instead of `- PYTHONPATH=/app:/app/src:${PYTHONPATH}`
   - This prevents variable substitution warnings when PYTHONPATH is not set on the host
   - **Best Practice**: Always use explicit values in docker-compose.yml for deterministic builds

### Debug Mode
Enable debug logging for detailed energy calculations:
```python
import logging
logging.getLogger('src.seedcore.energy').setLevel(logging.DEBUG)
```

### Performance Monitoring
Monitor energy trends over time:
```bash
# Run calibration test
docker compose exec seedcore-api python -m scripts.test_energy_calibration

# Check health status
curl http://localhost:8000/healthz/energy
```

## Future Enhancements

### Planned Features
1. **Hyper Energy Implementation**: Complex pattern tracking using hypergraphs
2. **Dynamic Weight Adaptation**: Learning optimal energy weights over time
3. **Energy History Tracking**: Temporal energy patterns and trends
4. **Advanced Role Mapping**: Machine learning-based task-role assignment
5. **Energy Forecasting**: Predictive energy modeling for proactive optimization
6. **Memory-Aware Pruning**: Hook β_mem * CostVQ into the optimizer
7. **Hyper-Term Back-Prop**: Implement Newton step for role rotation

### Integration Opportunities
1. **Meta-Controller Integration**: Energy-aware system-level decisions
2. **Memory Loop Enhancement**: Deeper integration with adaptive memory compression
3. **Performance Analytics**: Energy-based performance metrics and dashboards
4. **Multi-Objective Optimization**: Balancing energy with other system objectives

## References

- **Cognitive Organism Architecture (COA)**: Unified Energy Function specification
- **Ray Documentation**: Distributed computing framework
- **Energy Gradient Proxies**: Agent selection optimization theory
- **Memory Systems**: CostVQ and compression algorithms 