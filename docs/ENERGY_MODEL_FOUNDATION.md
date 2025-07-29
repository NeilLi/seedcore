# Energy Model Foundation

## Overview

The Energy Model Foundation implements the core energy-aware agent selection and optimization system as defined by the Cognitive Organism Architecture (COA). This system uses the Unified Energy Function to make intelligent decisions about agent selection and task allocation.

## Architecture

### Core Components

1. **Energy Calculator** (`src/seedcore/energy/calculator.py`)
   - Implements the Unified Energy Function with all five core energy terms
   - Calculates pairwise collaboration, entropy, regularization, and memory energy

2. **Energy Optimizer** (`src/seedcore/energy/optimizer.py`)
   - Provides energy-aware agent selection using gradient proxies
   - Implements task complexity estimation and role mapping

3. **Agent Energy Tracking** (`src/seedcore/agents/ray_actor.py`)
   - Tracks energy state and role probabilities for each agent
   - Provides methods for energy state updates and retrieval

4. **Tier0 Manager Integration** (`src/seedcore/agents/tier0_manager.py`)
   - Integrates energy-aware selection into agent management
   - Provides `execute_task_on_best_agent()` method

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
score_i = w_pair * E_pair_delta(i,t) + w_hyper * E_hyper_delta(i,t) - w_explore * entropy-gain(i)
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

## Configuration

### Energy Weights
Default weights for energy terms:
```python
weights = {
    'alpha': 0.5,        # Entropy energy weight
    'lambda_reg': 0.01,  # Regularization weight
    'beta_mem': 0.2,     # Memory energy weight
    'w_pair': 1.0,       # Pair energy weight in selection
    'w_hyper': 1.0,      # Hyper energy weight in selection
    'w_explore': 0.2     # Exploration weight in selection
}
```

### Task Complexity Factors
- **Task Type**: optimization (+0.3), exploration (+0.2)
- **Task Size**: large (+0.2), small (-0.1)
- **Urgency**: urgent (+0.1)

## Testing

Run the comprehensive test suite:
```bash
docker compose exec seedcore-api python -m scripts.test_energy_model
```

The test validates:
- Energy calculation accuracy
- Agent selection logic
- Task execution with energy optimization
- Ray integration and remote calls

## Performance Considerations

### Ray Integration
- All agent interactions use Ray remote calls
- Energy calculations are distributed across the cluster
- State embeddings and heartbeats are retrieved asynchronously

### Memory Usage
- Energy state tracking adds minimal overhead per agent
- Memory energy calculations integrate with existing memory system
- Regularization prevents unbounded state growth

### Scalability
- Energy calculations scale with number of agents O(n²) for pair energy
- Agent selection scales linearly O(n) with number of agents
- Ray distribution allows horizontal scaling

## Future Enhancements

### Planned Features
1. **Hyper Energy Implementation**: Complex pattern tracking using hypergraphs
2. **Dynamic Weight Adaptation**: Learning optimal energy weights over time
3. **Energy History Tracking**: Temporal energy patterns and trends
4. **Advanced Role Mapping**: Machine learning-based task-role assignment
5. **Energy Forecasting**: Predictive energy modeling for proactive optimization

### Integration Opportunities
1. **Meta-Controller Integration**: Energy-aware system-level decisions
2. **Memory Loop Enhancement**: Deeper integration with adaptive memory compression
3. **Performance Analytics**: Energy-based performance metrics and dashboards
4. **Multi-Objective Optimization**: Balancing energy with other system objectives

## Troubleshooting

### Common Issues

1. **Ray Remote Call Errors**
   - Ensure all agent method calls use `.remote()`
   - Check Ray cluster connectivity

2. **Memory System Integration**
   - Verify memory system has required attributes (Mw, Mlt, bytes_used, hit_count, datastore)
   - Check CostVQ function availability

3. **Energy Calculation Errors**
   - Validate agent state embeddings are 128-dimensional
   - Ensure role probabilities sum to 1.0

### Debug Mode
Enable debug logging for detailed energy calculations:
```python
import logging
logging.getLogger('src.seedcore.energy').setLevel(logging.DEBUG)
```

## References

- **Cognitive Organism Architecture (COA)**: Unified Energy Function specification
- **Ray Documentation**: Distributed computing framework
- **Energy Gradient Proxies**: Agent selection optimization theory
- **Memory Systems**: CostVQ and compression algorithms 