# SeedCore: Dynamic Cognitive Architecture

A stateful, interactive cognitive architecture system with persistent organs, agents, and energy-based control loops.

## Features

### 🧠 Persistent State Management
- **Organ Registry**: Centralized state management with `OrganRegistry`
- **Persistent Organs & Agents**: System maintains state across API calls
- **Energy Ledger**: Multi-term energy accounting (pair, hyper, entropy, reg, mem)
- **Role Evolution**: Dynamic agent role probability adjustment

### 🔄 Control Loops
- **Fast Loop**: Real-time agent selection and task execution
- **Slow Loop**: Energy-aware role evolution with learning rate control
- **Memory Loop**: Adaptive compression and memory utilization control

### 📊 Comprehensive Telemetry
- Energy gradient monitoring
- Role performance metrics
- Memory utilization tracking
- System status endpoints

## Quick Start

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

# Run a simulation step (legacy)
curl http://localhost:8000/run_simulation_step

# Run fast loop (new)
curl -X POST http://localhost:8000/actions/run_fast_loop

# Reset energy ledger
curl http://localhost:8000/reset_energy
# or
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
# Get system status
curl http://localhost:8000/system/status

# Get agent states
curl http://localhost:8000/agents/state
```

## API Endpoints

### Energy Management
- `GET /energy/gradient` - Get current energy state
- `GET /run_simulation_step` - Legacy: Execute one simulation step
- `POST /actions/run_fast_loop` - New: Execute fast loop with agent selection
- `GET /reset_energy` - Legacy: Reset energy ledger
- `POST /actions/reset` - New: Reset energy ledger

### Control Loops
- `GET /run_slow_loop` - Legacy: Energy-aware role evolution
- `POST /actions/run_slow_loop` - New: Energy-aware role evolution
- `GET /run_slow_loop_simple` - Simple role strengthening
- `GET /run_memory_loop` - Adaptive memory control
- `GET /run_all_loops` - Execute all control loops

### System Status
- `GET /system/status` - Get comprehensive system state
- `GET /agents/state` - Get detailed agent states

## Architecture Components

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
- **pair**: Pairwise interaction energy
- **hyper**: Complexity-precision tradeoff energy
- **entropy**: Choice availability and uncertainty energy
- **reg**: Regularization and model complexity energy
- **mem**: Memory usage and compression energy

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
- Adaptive compression control via dE/dCostVQ estimation
- Memory utilization optimization
- Compression knob adjustment based on memory efficiency

### Agent Roles
Each agent has three role types with probabilities:
- **E (Explorer)**: Seeks new solutions and opportunities
- **S (Specialist)**: Focuses on specific tasks and optimization
- **O (Optimizer)**: Balances exploration and exploitation

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
- Memory management and compression
- OrganRegistry integration
- Integration tests for all components

## Development

### Project Structure
```
seedcore/
├── src/seedcore/
│   ├── agents/          # Agent implementations
│   ├── control/         # Control loops (fast, slow, memory)
│   ├── energy/          # Energy ledger and calculations
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

## Energy Calculation Examples

### Pair Energy
```python
# Pair energy increases with interaction weight and similarity
ledger.add_pair_delta(weight=2.0, similarity=1.5)  # Adds 3.0 to pair energy
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
| `GET /run_simulation_step` | `POST /actions/run_fast_loop` | Fast loop execution |
| `GET /run_slow_loop` | `POST /actions/run_slow_loop` | Slow loop execution |
| `GET /reset_energy` | `POST /actions/reset` | Reset energy ledger |
| `GET /system_status` | `GET /system/status` | System status |

## Next Steps

This implementation provides a solid foundation for a dynamic cognitive architecture. Future enhancements could include:

1. **Advanced Energy Models**: More sophisticated energy calculations
2. **Multi-Organ Coordination**: Inter-organ communication and coordination
3. **Learning Mechanisms**: Reinforcement learning for role optimization
4. **External Integrations**: Connect with external AI services and databases
5. **Visualization**: Real-time system state visualization
6. **Performance Optimization**: Caching and parallel processing

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
