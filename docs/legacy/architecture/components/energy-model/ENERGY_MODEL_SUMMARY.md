# Energy Model Foundation - Quick Summary

## 🎯 What Was Implemented

The Energy Model Foundation adds **intelligent energy-aware agent selection** to your cognitive architecture, enabling the system to choose the most suitable agents for tasks based on energy optimization principles.

## 📁 Files Added/Modified

### New Files
- `src/seedcore/energy/calculator.py` - Energy calculation engine
- `src/seedcore/energy/optimizer.py` - Agent selection optimizer
- `src/seedcore/energy/__init__.py` - Package exports
- `scripts/test_energy_model.py` - Comprehensive test suite
- `docs/ENERGY_MODEL_FOUNDATION.md` - Detailed documentation

### Modified Files
- `src/seedcore/agents/ray_actor.py` - Added energy state tracking
- `src/seedcore/agents/tier0_manager.py` - Added energy-aware task execution
- `README.md` - Updated with Energy Model Foundation overview

## ⚡ Key Features

### Energy Calculation
- **Pair Energy**: Collaboration similarity between agents
- **Entropy Energy**: Role diversity maintenance
- **Regularization Energy**: State complexity control
- **Memory Energy**: Memory pressure and information loss
- **Hyper Energy**: Complex pattern tracking via HGNN pattern shim (bounded `E_patterns`)

### Agent Selection
- **Energy Gradient Proxies**: Intelligent suitability scoring
- **Task-Role Mapping**: Automatic role assignment
- **Complexity Estimation**: Dynamic task difficulty assessment
- **Ray Integration**: Distributed calculations

## 🚀 Usage

### Basic Energy-Aware Task Execution
```python
from src.seedcore.agents.tier0_manager import Tier0MemoryManager

tier0_manager = Tier0MemoryManager()
result = tier0_manager.execute_task_on_best_agent(task_data)
```

### Energy Calculation
Prefer the explicit unified-state API:
```python
import numpy as np
from src.seedcore.energy.weights import EnergyWeights
from src.seedcore.energy.calculator import compute_energy
from seedcore.hgnn.pattern_shim import SHIM

H = unified_state.H_matrix()
P = unified_state.P_matrix()
E_sel, _ = SHIM.get_E_patterns()
w = EnergyWeights.default(W_pair=np.ones((H.shape[0], H.shape[0])), W_hyper=np.ones_like(E_sel))
total, breakdown = compute_energy(H, P, w, memory_stats, E_sel=E_sel, s_norm=float(np.linalg.norm(H)))
```

### Gradients API (for controllers)
```python
from src.seedcore.energy.calculator import energy_and_grad, role_entropy_grad

breakdown, grad = energy_and_grad(
    state={
        'h_agents': H,
        'P_roles': P,
        'hyper_sel': E_sel,
        's_norm': float(np.linalg.norm(H)),
    },
    weights=w,
    memory_stats=memory_stats,
)
```

### Agent Scoring
```python
from src.seedcore.energy.optimizer import calculate_agent_suitability_score

score = calculate_agent_suitability_score(agent, task_data, weights)
```

## 🧪 Testing

Run the test suite:
```bash
docker compose exec seedcore-api python -m scripts.test_energy_model
```

**Expected Results:**
- ✅ Energy calculations working correctly
- ✅ Specialist agents selected for optimization tasks
- ✅ Energy-aware task execution successful
- ✅ All Ray integration working properly

## 🎯 Benefits

1. **Intelligent Selection**: Agents chosen based on energy optimization
2. **Role Awareness**: Tasks automatically mapped to suitable agent roles
3. **System Efficiency**: Minimizes energy while maximizing performance
4. **Scalability**: Distributed calculations across Ray cluster
5. **Integration**: Seamlessly works with existing cognitive architecture

## 🔧 Configuration

Default energy weights:
```python
weights = {
    'alpha': 0.5,        # Entropy energy
    'lambda_reg': 0.01,  # Regularization
    'beta_mem': 0.2,     # Memory energy
    'w_pair': 1.0,       # Pair energy in selection
    'w_hyper': 1.0,      # Hyper energy in selection
    'w_explore': 0.2     # Exploration weight
}
```

## 🚀 Next Steps

The Energy Model Foundation is now ready for:
- Integration with meta-controller for system-level decisions
- Advanced hyper energy implementation
- Dynamic weight adaptation
- Energy forecasting and predictive optimization

---

**Status**: ✅ **FULLY IMPLEMENTED AND TESTED**
**Commit**: `877c235` - "feat: Implement Energy Model Foundation for intelligent agent selection"

## Ledger Persistence and Slow Loop (Addendum)

- Energy ledger persistence is available via `src/seedcore/energy/energy_persistence.py` using `EnergyLedgerStore` and `EnergyTx`.
- Default backend is MySQL through the shared `CheckpointStore`; FS/S3-style stores are supported with newline-delimited JSON.
- Enable via environment:

```bash
ENERGY_LEDGER_ENABLED=true
ENERGY_LEDGER_BACKEND=mysql   # or fs
# If fs backend is used:
ENERGY_LEDGER_ROOT=/app/data
```

- A background slow loop exists at `src/seedcore/energy/control_loops.py` (`SlowPSOLoop`) to tune roles and `lambda_reg` over time, with helpers `start_slow_psoloop()` and `stop_slow_psoloop()`.

## Unified State and Telemetry Notes (August 2025)

- Telemetry uses `UnifiedState` to assemble agent snapshots and reads `E_patterns` from the HGNN shim.
- Energy endpoints format responses using `EnergyLedger.terms` for compatibility with existing consumers.

Implementation notes:
- To avoid circular imports, the calculator only imports `RayAgent` under `TYPE_CHECKING` and treats it as `Any` at runtime.

Contractivity guard used in telemetry:

```python
L_tot = min(0.999, (p_fast * 1.0 + (1.0 - p_fast) * beta_meta) * rho * beta_mem)
```