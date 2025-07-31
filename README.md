# SeedCore: Dynamic Cognitive Architecture

A stateful, interactive cognitive architecture system with persistent organs, agents, and energy-based control loops featuring realistic agent collaboration learning.

## Features

### 🧠 Persistent State Management
- **Organ Registry**: Centralized state management with `OrganRegistry`
- **Persistent Organs & Agents**: System maintains state across API calls
- **Energy Ledger**: Multi-term energy accounting (pair, hyper, entropy, reg, mem)
- **Role Evolution**: Dynamic agent role probability adjustment

### 🤖 Agent Personality System
- **Personality Vectors**: Each agent has an 8-dimensional personality embedding (`h`)
- **Cosine Similarity**: Calculates compatibility between agent personalities
- **Collaboration Learning**: Tracks historical success rates between agent pairs
- **Adaptive Weights**: Learns which agent combinations work best together

### 🔄 Control Loops
- **Fast Loop**: Real-time agent selection and task execution
- **Slow Loop**: Energy-aware role evolution with learning rate control
- **Memory Loop**: Adaptive compression and memory utilization control
- **Energy Model Foundation**: Intelligent energy-aware agent selection and optimization

### 📊 Comprehensive Telemetry
- Energy gradient monitoring
- Role performance metrics
- Memory utilization tracking
- Pair collaboration statistics
- System status endpoints

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Python 3.10 (for local development)

### 1. Clone and Setup
```bash
git clone <repository-url>
cd seedcore
```

### 2. Start Services
```bash
cd docker
./start-cluster.sh
```

**⚠️ Important**: Always use `./start-cluster.sh` instead of `docker compose up -d` to ensure proper service startup order and dependency management. Individual service restarts may fail due to Ray cluster state dependencies.

**Note**: The Docker Compose configuration has been optimized to eliminate PYTHONPATH warnings and ensure clean builds.

### 3. Verify Installation
```bash
# Check Ray dashboard
curl http://localhost:8265/api/version

# Check API health
curl http://localhost:8000/health

# Check energy system
curl http://localhost:8000/healthz/energy
```

### 4. Run Tests
```bash
# Test energy model
docker compose exec seedcore-api python -m scripts.test_energy_model

# Run energy calibration
docker compose exec seedcore-api python -m scripts.test_energy_calibration
```

### 1. Install Dependencies
```bash
cd seedcore
pip install -r requirements.txt
```

### 2. Run the Server
```bash
uvicorn src.seedcore.telemetry.server:app --reload --host 0.0.0.0 --port 8000
```

### 3. Test the System

#### Basic Energy Operations
```bash
# Check current energy state
curl http://localhost:8000/energy/gradient

# Run a realistic two-agent task (NEW!)
curl -X POST http://localhost:8000/actions/run_two_agent_task

# Run a simulation step (legacy)
curl http://localhost:8000/run_simulation_step

# Reset energy ledger and pair statistics
curl -X POST http://localhost:8000/actions/reset
```

#### Control Loop Operations
```bash
# Run slow loop (energy-aware role evolution)
curl http://localhost:8000/run_slow_loop
# or
curl -X POST http://localhost:8000/actions/run_slow_loop

# Run simple slow loop (strengthen dominant roles)
curl http://localhost:8000/run_slow_loop_simple

# Run memory loop (adaptive compression)
curl http://localhost:8000/run_memory_loop

# Run all loops in sequence
curl http://localhost:8000/run_all_loops
```

#### System Monitoring
```bash
# Get system status (includes pair statistics)
curl http://localhost:8000/system/status

# Get agent states (includes personality vectors)
curl http://localhost:8000/agents/state

# Get pair collaboration statistics
curl http://localhost:8000/pair_stats
```

## API Endpoints

### Energy Management
- `GET /energy/gradient` - Get current energy state
- `POST /actions/run_two_agent_task` - **NEW**: Run realistic two-agent collaboration
- `GET /run_simulation_step` - Legacy: Execute one simulation step
- `GET /reset_energy` - Legacy: Reset energy ledger
- `POST /actions/reset` - New: Reset energy ledger and pair statistics

### Control Loops
- `GET /run_slow_loop` - Legacy: Energy-aware role evolution
- `POST /actions/run_slow_loop` - New: Energy-aware role evolution
- `GET /run_slow_loop_simple` - Simple role strengthening
- `GET /run_memory_loop` - Adaptive memory control
- `GET /run_all_loops` - Execute all control loops

### System Status
- `GET /system/status` - Get comprehensive system state
- `GET /agents/state` - Get detailed agent states (includes personality vectors)
- `GET /pair_stats` - **NEW**: Get pair collaboration statistics

## Architecture Components

### Agent Personality System
Each agent has a personality vector that influences collaboration:

```python
# Agent with personality vector
agent = Agent(
    agent_id="agent_alpha",
    h=np.array([0.8, 0.6, 0.4, 0.2, 0.1, 0.3, 0.5, 0.7])  # 8D personality
)

# Calculate similarity between agents
similarity = cosine_similarity(agent1.h, agent2.h)
```

### Pair Statistics Tracking
The system learns which agent pairs work best together:

```python
# Track collaboration success
pair_stats = PAIR_TRACKER.get_pair("agent1", "agent2")
pair_stats.update_weight(success=True, learning_rate=0.1)

# Get historical performance
stats = PAIR_TRACKER.get_all_stats()
# Returns: {"agent1-agent2": {"weight": 0.85, "success_rate": 0.75, ...}}
```

### Organ Registry
The system uses a centralized `OrganRegistry` for state management:
```python
# Initialize registry
registry = OrganRegistry()

# Create and register organs
organ = Organ(organ_id="cognitive_organ_1")
registry.add(organ)

# Access organs
organ = registry.get("cognitive_organ_1")
all_organs = registry.all()
```

### Energy Ledger
The system tracks five energy terms:
- **pair**: Pairwise interaction energy (now with realistic learning)
- **hyper**: Complexity-precision tradeoff energy
- **entropy**: Choice availability and uncertainty energy
- **reg**: Regularization and model complexity energy
- **mem**: Memory usage and compression energy

### Energy Model Foundation
The system implements intelligent energy-aware agent selection and optimization:

```python
# Energy-aware task execution
from src.seedcore.agents.tier0_manager import Tier0MemoryManager

tier0_manager = Tier0MemoryManager()
result = tier0_manager.execute_task_on_best_agent(task_data)
```

**Key Features:**
- **Unified Energy Function**: Five-term energy calculation (pair, entropy, reg, mem, hyper)
- **Energy Gradient Proxies**: Intelligent agent suitability scoring
- **Task-Role Mapping**: Automatic mapping of tasks to optimal agent roles
- **Ray Integration**: Distributed energy calculations across the cluster

**Energy Terms:**
- **Pair Energy**: Collaboration similarity between agents
- **Entropy Energy**: Role diversity maintenance
- **Regularization Energy**: State complexity control
- **Memory Energy**: Memory pressure and information loss
- **Hyper Energy**: Complex pattern tracking (future)

### Control Loops

#### Fast Loop
- Real-time agent selection based on energy gradients
- Task execution and energy updates
- Runs on every simulation step

#### Slow Loop
- **Energy-aware**: Adjusts roles based on current energy state
  - High energy → Increase Explorer (E) role
  - Low energy → Increase Specialist (S) role
  - Moderate energy → Increase Optimizer (O) role
- **Simple**: Strengthens dominant roles without energy context
- Configurable learning rate for adjustment speed
- **Flexible**: Works with both organ lists and agent lists

#### Memory Loop
- **Comprehensive Tiered Memory System**: Implements working memory (Mw) and long-term memory (Mlt)
- **Dynamic Memory Utility**: Calculates agent mem_util based on actual memory interactions
- **CostVQ Calculation**: Trade-off between memory usage, reconstruction loss, and staleness
- **Adaptive Compression Control**: Gradient-based optimization of compression knob
- **Memory Activity Simulation**: Realistic write/read cycles with feedback loops

### Agent Roles
Each agent has three role types with probabilities:
- **E (Explorer)**: Seeks new solutions and opportunities
- **S (Specialist)**: Focuses on specific tasks and optimization
- **O (Optimizer)**: Balances exploration and exploitation

## Realistic Simulation Features

### Two-Agent Task Simulation
The new `/actions/run_two_agent_task` endpoint provides realistic collaboration:

1. **Random Agent Selection**: Picks two agents randomly
2. **Personality Compatibility**: Calculates cosine similarity between personality vectors
3. **Historical Learning**: Uses past collaboration success rates
4. **Capability Integration**: Combines agent capabilities with historical weights
5. **Energy Calculation**: Updates pair energy based on `-w_effective * similarity`
6. **Success Simulation**: Task success probability based on similarity
7. **Learning Update**: Updates pair statistics for future collaborations

### Example Task Response
```json
{
  "message": "Two-agent task completed between agent_alpha and agent_beta",
  "agents": {
    "agent1": {
      "id": "agent_alpha",
      "capability": 0.5,
      "personality": [0.8, 0.6, 0.4, 0.2, 0.1, 0.3, 0.5, 0.7]
    },
    "agent2": {
      "id": "agent_beta", 
      "capability": 0.5,
      "personality": [0.7, 0.5, 0.3, 0.1, 0.2, 0.4, 0.6, 0.8]
    }
  },
  "calculations": {
    "cosine_similarity": 0.92,
    "historical_weight": 1.0,
    "effective_weight": 0.25,
    "energy_delta": -0.23
  },
  "task_result": {
    "successful": true,
    "success_probability": 0.92
  },
  "new_energy_state": {...},
  "pair_stats": {...}
}
```

## Comprehensive Memory System

### Tiered Memory Architecture
The system implements a sophisticated tiered memory structure as described in the energy validation document:

#### Memory Tiers
- **Mw (Working Memory)**: Fast, small-capacity memory for active processing
- **Mlt (Long-term Memory)**: Slower, large-capacity memory for persistent storage

#### Memory Operations
```python
# Write data to memory
success = MEMORY_SYSTEM.write(agent, "data_id", "Mw", data_size=10)

# Read data from memory (searches Mw first, then Mlt)
author_id = MEMORY_SYSTEM.read(reader_agent, "data_id")

# Log salient events
MEMORY_SYSTEM.log_salient_event(agent)
```

### Dynamic Memory Utility Calculation
Agent memory utility is now calculated based on actual memory interactions:

```python
# Calculate mem_util based on memory interactions
mem_util = calculate_dynamic_mem_util(agent, weights={
    'w_hit': 0.6,      # Weight for memory hits on writes
    'w_salience': 0.4   # Weight for salient events
})

# Formula: (w_hit * memory_hits_on_writes + w_salience * salient_events_logged) / memory_writes
```

### CostVQ Energy Calculation
The memory energy term is calculated using the CostVQ function:

```python
cost_vq_data = calculate_cost_vq(memory_system, compression_knob)

# Components:
# - bytes_used: Total memory usage across tiers
# - recon_loss: Information loss due to compression (1.0 - compression_knob)
# - staleness: Based on hit rate (1.0 / (1.0 + hit_rate))
# - cost_vq: Weighted sum of components
```

### Memory Loop Operation
The comprehensive memory loop performs these steps:

1. **Write Phase**: Randomly select agents to write data to memory tiers
2. **Read Phase**: Simulate agents reading data, creating feedback loops
3. **Utility Calculation**: Calculate dynamic mem_util for all agents
4. **Energy Update**: Calculate and update memory energy using CostVQ
5. **Compression Optimization**: Update compression knob using gradient descent
6. **Metrics Collection**: Gather comprehensive memory statistics

### Example Memory Loop Response
```json
{
  "message": "Comprehensive memory loop completed successfully!",
  "compression_knob": 0.65,
  "average_mem_util": 0.42,
  "individual_mem_utils": {
    "agent_alpha": 0.38,
    "agent_beta": 0.45,
    "agent_gamma": 0.43
  },
  "memory_metrics": {
    "average_mem_util": 0.42,
    "total_memory_writes": 15,
    "total_memory_hits": 8,
    "total_salient_events": 3
  },
  "cost_vq_breakdown": {
    "cost_vq": 0.23,
    "bytes_used": 150,
    "recon_loss": 0.35,
    "staleness": 0.12,
    "hit_rate": 0.53
  },
  "memory_energy": 0.23,
  "memory_system_stats": {
    "Mw": {"bytes_used": 50, "hit_count": 5, "data_count": 3},
    "Mlt": {"bytes_used": 100, "hit_count": 3, "data_count": 7}
  }
}
```

### Agent Memory Tracking
Each agent now tracks detailed memory interactions:

```python
agent = Agent(agent_id="test_agent")
# Memory interaction fields:
agent.memory_writes = 5          # Number of memory writes
agent.memory_hits_on_writes = 3  # Times this agent's data was read
agent.salient_events_logged = 2  # Number of salient events
agent.total_compression_gain = 0.0  # Compression benefits
agent.mem_util = 0.52           # Calculated memory utility
```

## Testing

Run the test suite:
```bash
cd seedcore
python -m pytest tests/ -v
```

### Test Coverage
- Energy ledger operations and calculations
- Control loop functionality (both organ and agent inputs)
- Role evolution and performance metrics
- **NEW**: Comprehensive tiered memory system
- **NEW**: Dynamic memory utility calculations
- **NEW**: CostVQ energy calculations
- **NEW**: Memory activity simulation and feedback loops
- **NEW**: Pair statistics tracking and learning
- **NEW**: Agent personality vectors and similarity
- OrganRegistry integration
- Integration tests for all components

## Docker & Deployment Improvements (2024)

### Optimized Docker Image
- **Multi-stage Dockerfile**: Now uses a multi-stage build for smaller, more secure images.
- **Minimal requirements**: Production images use `requirements-minimal.txt` (excludes unused ML libraries like DGL).
- **.dockerignore**: Now excludes dev, data, and build artifacts for smaller build context.
- **Alpine variant**: Optional `Dockerfile.alpine` for ultra-small images (experimental).
- **Image size reduced**: From 1.7GB to 749MB for the API server.

### Usage

**Build optimized image:**
```bash
docker build -f docker/Dockerfile -t seedcore-api:optimized .
```

**(Optional) Build Alpine image:**
```bash
docker build -f docker/Dockerfile.alpine -t seedcore-api:alpine .
```

**Run:**
```bash
docker run --rm -p 8000:8000 seedcore-api:optimized
```

**For development:**  
- Use the standard image and `requirements.txt` for full-featured dev environment.
- Use volume mounts in `docker-compose.yml` for live code reload.

**For production:**  
- Use the optimized image and `requirements-minimal.txt` for fast, secure deployment.

### Image Analysis
A new script is provided to analyze image size and bloat:
```bash
bash docker/analyze-image.sh
```

### Development Workflow
- **Development:** Use the normal image for rapid iteration, debugging, and testing.
- **Release:** Use the optimized image for deployment to minimize size and attack surface.

### Other Notable Changes
- **Redis, Prometheus, asyncpg, Ray**: All dependencies are now managed for both dev and prod.
- **Improved error handling and logging** in the API server and memory consolidation logic.
- **Runtime tuning endpoints** and health checks added.
- **Docker Compose**: Now references the correct Dockerfile and context for builds.

### Quick Migration
- If you want to use the new optimized image in Compose, set:
  ```yaml
  image: seedcore-api:optimized
  ```
  Or keep the build section with the correct context and Dockerfile path.

## Development

### Project Structure
```
seedcore/
├── src/seedcore/
│   ├── agents/          # Agent implementations (with personality vectors)
│   ├── control/         # Control loops (fast, slow, memory)
│   ├── energy/          # Energy ledger, calculations, and pair statistics
│   ├── memory/          # NEW: Tiered memory system and adaptive loops
│   ├── organs/          # Organ implementations and registry
│   └── telemetry/       # API server and monitoring
├── tests/               # Test suite
├── examples/            # Usage examples
└── docs/               # Documentation
```

### Adding New Features
1. **Energy Terms**: Add new methods to `EnergyLedger` class
2. **Control Loops**: Implement new loop logic in `control/` directory
3. **Agents**: Extend `Agent` base class with new capabilities
4. **API Endpoints**: Add new routes to `telemetry/server.py`
5. **Registry**: Use `OrganRegistry` for state management
6. **Personality**: Extend personality vectors or add new similarity metrics

## Energy Calculation Examples

### Pair Energy (Enhanced)
```python
# Pair energy with realistic learning
# -w_effective * similarity where w_effective = w_historical * capability1 * capability2
ledger.add_pair_delta(w_effective=0.25, similarity=0.92)  # Adds -0.23 to pair energy
```

### Hyper Energy
```python
# Hyper energy based on complexity vs precision tradeoff
ledger.add_hyper_delta(complexity=0.8, precision=0.3)  # Adds 0.5 to hyper energy
```

### Entropy Energy
```python
# Entropy energy increases with choice availability and uncertainty
ledger.add_entropy_delta(choice_count=5, uncertainty=0.6)  # Adds 0.3 to entropy energy
```

### Memory Energy
```python
# Memory energy based on usage vs compression
ledger.add_mem_delta(memory_usage=0.7, compression_ratio=0.4)  # Adds 0.3 to mem energy
```

## Migration from Legacy Endpoints

The system now supports both legacy and new API endpoints:

| Legacy | New | Description |
|--------|-----|-------------|
| `GET /run_simulation_step` | `POST /actions/run_two_agent_task` | **NEW**: Realistic two-agent collaboration |
| `GET /run_slow_loop` | `POST /actions/run_slow_loop` | Slow loop execution |
| `GET /reset_energy` | `POST /actions/reset` | Reset energy ledger and pair stats |
| `GET /system_status` | `GET /system/status` | System status (includes pair stats) |

## Next Steps

This implementation provides a solid foundation for a dynamic cognitive architecture. Future enhancements could include:

1. **Advanced Energy Models**: More sophisticated energy calculations
2. **Multi-Organ Coordination**: Inter-organ communication and coordination
3. **Learning Mechanisms**: Reinforcement learning for role optimization
4. **External Integrations**: Connect with external AI services and databases
5. **Visualization**: Real-time system state visualization
6. **Performance Optimization**: Caching and parallel processing
7. **Advanced Personality Models**: More sophisticated personality representations
8. **Team Formation**: Automatic team composition based on personality compatibility

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

This project is licensed under the Apache License, Version 2.0 - see the [LICENSE](LICENSE) file for details.

Copyright 2024 SeedCore Contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
