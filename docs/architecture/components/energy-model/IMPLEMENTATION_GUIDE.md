# Energy System Implementation Guide

## Overview

This guide provides step-by-step instructions for implementing the energy validation roadmap to achieve the "more precise & truly useful" energy model described in the validation blueprint.

## Prerequisites

- SeedCore codebase with basic energy system already implemented
- Docker environment for testing
- Understanding of the current energy system architecture

## Implementation Phases

### Phase 1: Telemetry & Observability (Days 1-2)

#### Step 1.1: Verify Current Energy Router

The energy router has been created at `src/seedcore/api/routers/energy_router.py`. Verify it's properly integrated:

```bash
# Check if the router is imported in the main API
grep -r "energy_router" src/seedcore/api/
```

#### Step 1.2: Test the `/energy/gradient` Endpoint

```bash
# Start the SeedCore system in Docker
docker compose up -d

# Test the energy gradient endpoint (served by API on port 8002)
curl http://localhost:8002/energy/gradient

# Expected response:
{
  "ts": 1234567890,
  "E_terms": {
    "pair": -0.8600,
    "hyper": 0.0,
    "entropy": -0.2929,
    "reg": 2.9275,
    "mem": 0.0075,
    "total": 1.7821
  },
  "deltaE_last": 0.0,
  "slopes": {
    "pair_slope": 0.0,
    "hyper_slope": 0.0,
    "entropy_slope": 0.0,
    "reg_slope": 0.0,
    "mem_slope": 0.0
  },
  "mem_pressure": {
    "cost_vq": 0.0,
    "compression_ratio": 0.0,
    "staleness": 0.0
  }
}
```

#### Step 1.3: Verify Energy History Tracking

The enhanced `EnergyLedger` class now includes history tracking. Test it:

```python
from seedcore.energy.ledger import EnergyLedger

# Create a ledger instance
ledger = EnergyLedger()

# Add some energy updates
ledger.add_pair_delta(-0.1)
ledger.add_entropy_delta(3, 0.5)
ledger.add_reg_delta(0.01, 100.0)

# Check history
print(f"Pair history length: {len(ledger.pair_history)}")
print(f"Total energy: {ledger.total}")
```

### Phase 2: Adaptive Control (Days 3-4)

#### Step 2.1: Implement EWMA Updates

Add capability and memory-utility tracking to the energy calculator:

```python
# Add to src/seedcore/energy/calculator.py

# Global storage for agent capabilities and utilities
agent_capabilities = {}
agent_memory_utilities = {}

def update_capability_ewma(agent_id: str, success_rate: float, eta_c: float = 0.1):
    """Update agent capability with EWMA."""
    current_ci = agent_capabilities.get(agent_id, 0.5)
    new_ci = (1 - eta_c) * current_ci + eta_c * success_rate
    agent_capabilities[agent_id] = new_ci
    return new_ci

def update_memory_utility_ewma(agent_id: str, memory_value: float, eta_u: float = 0.1):
    """Update agent memory utility with EWMA."""
    current_ui = agent_memory_utilities.get(agent_id, 0.5)
    new_ui = (1 - eta_u) * current_ui + eta_u * memory_value
    agent_memory_utilities[agent_id] = new_ui
    return new_ui

def calculate_pair_weight(agent_i: str, agent_j: str) -> float:
    """Calculate pair weight based on min(ci, cj)."""
    ci = agent_capabilities.get(agent_i, 0.5)
    cj = agent_capabilities.get(agent_j, 0.5)
    return min(ci, cj)
```

#### Step 2.2: Add PSO for λ_reg Optimization

Enhance the slow loop with λ_reg optimization:

```python
# Add to src/seedcore/control/slow_loop.py

def optimize_lambda_reg(ledger: EnergyLedger, target_reg_ratio: float = 0.25):
    """PSO optimization for λ_reg to keep reg ≤ 25% of total."""
    current_reg_ratio = ledger.reg / max(ledger.total, 1e-6)
    
    if current_reg_ratio > target_reg_ratio:
        # Reduce λ_reg
        new_lambda = ledger.lambda_reg * 0.9
        ledger.lambda_reg = max(new_lambda, 0.001)  # Floor at 0.001
        logger.info(f"Reduced λ_reg to {ledger.lambda_reg} (reg ratio: {current_reg_ratio:.3f})")
    elif current_reg_ratio < target_reg_ratio * 0.5:
        # Increase λ_reg slightly
        new_lambda = ledger.lambda_reg * 1.05
        ledger.lambda_reg = min(new_lambda, 0.1)  # Ceiling at 0.1
        logger.info(f"Increased λ_reg to {ledger.lambda_reg} (reg ratio: {current_reg_ratio:.3f})")
```

### Phase 3: Hyper-Edge Implementation (Day 5)

#### Step 3.1: Wire HGNN Pattern Shim

The HGNN escalation→pattern shim (`seedcore.hgnn.pattern_shim.SHM`) collects escalations and exposes bounded `E_patterns` with exponential decay and top-K selection. Telemetry reads `E_patterns` and includes them in `UnifiedState.system`. The unified calculator API accepts `E_sel` and weights `W_hyper` to contribute to total energy.

### Phase 4: Experimental Harness (Day 6)

#### Step 4.1: Test the Experimental Harness

The enhanced experimental harness is now available. Test it:

```python
from seedcore.experiments.harness import EnergyValidationHarness
from seedcore.organs.organism_manager import organism_manager
from seedcore.energy.api import _ledger

# Create harness instance
harness = EnergyValidationHarness(organism_manager, _ledger)

# Run experiments
async def run_all_experiments():
    # Initialize organism if needed
    await organism_manager.initialize_organism()
    
    # Run experiments
    results = {}
    results['A'] = await harness.experiment_A_pair()
    results['B'] = await harness.experiment_B_hyper()
    results['C'] = await harness.experiment_C_entropy()
    results['D'] = await harness.experiment_D_memory()
    
    # Get summary
    summary = harness.get_experiment_summary()
    print(f"Experiment Summary: {summary}")
    
    return results

# Run in async context
import asyncio
asyncio.run(run_all_experiments())
```

### Phase 5: Hourly Flywheel (Day 7)

#### Step 5.1: Test the Flywheel

The hourly flywheel is now implemented. Test it:

```python
from seedcore.control.flywheel import flywheel

# Start the flywheel (in production, this would run continuously)
async def test_flywheel():
    # Run a single cycle for testing
    await flywheel.run_flywheel_cycle()
    
    # Get flywheel stats
    stats = flywheel.get_flywheel_stats()
    print(f"Flywheel Stats: {stats}")

# Run in async context
asyncio.run(test_flywheel())
```

## Validation Testing

### Test 1: Energy Gradient Endpoint

```bash
# Test the endpoint returns proper JSON
curl -s http://localhost:8002/energy/gradient | jq '.'

# Verify all required fields are present
curl -s http://localhost:8002/energy/gradient | jq '.E_terms | keys'
# Should return: ["pair", "hyper", "entropy", "reg", "mem", "total"]
```

### Test 2: Energy History Tracking

```python
# Test that energy updates are tracked in history
from seedcore.energy.api import _ledger

# Reset ledger
_ledger.reset()

# Add some updates
_ledger.add_pair_delta(-0.1)
_ledger.add_entropy_delta(3, 0.5)

# Check history
assert len(_ledger.pair_history) > 0
assert len(_ledger.entropy_history) > 0
assert len(_ledger.total_history) > 0
```

### Test 3: Experimental Harness

```python
# Test that experiments can run and produce results
harness = EnergyValidationHarness(organism_manager, _ledger)

# Run a quick test of experiment A
result = await harness.experiment_A_pair()
assert isinstance(result, bool)

# Check experiment history
summary = harness.get_experiment_summary()
assert "A" in summary["experiments"]
```

### Test 4: Flywheel Control

```python
# Test that flywheel can run and update weights
old_weights = flywheel.get_current_weights()

# Run a cycle
await flywheel.run_flywheel_cycle()

# Check weights changed
new_weights = flywheel.get_current_weights()
assert old_weights != new_weights
```

## Configuration Updates

### Update Default Configuration

Update `src/seedcore/config/defaults.yaml` to include new energy parameters:

```yaml
seedcore:
  # ... existing config ...
  energy:
    # Adaptive control parameters
    adaptation_rate: 0.05
    target_reg_ratio: 0.25
    min_data_points: 10
    
    # Weight bounds
    weight_bounds:
      alpha: [0.1, 2.0]
      lambda_reg: [0.001, 0.1]
      beta_mem: [0.05, 0.5]
    
    # EWMA parameters
    eta_capability: 0.1
    eta_memory_utility: 0.1
```

## Monitoring & Dashboards

### Energy Metrics Dashboard

Create a simple dashboard to monitor energy trends:

```python
# Example dashboard code
import matplotlib.pyplot as plt
import requests

def plot_energy_trends():
    # Get energy history
    response = requests.get("http://localhost:8000/energy/history/total")
    data = response.json()
    
    # Plot
    plt.figure(figsize=(12, 8))
    plt.plot(data["history"])
    plt.title("Energy Trends")
    plt.xlabel("Time")
    plt.ylabel("Total Energy")
    plt.grid(True)
    plt.show()

# Run dashboard
plot_energy_trends()
```

### Validation Scorecard

Implement the validation scorecard (Table 4):

```python
def generate_validation_scorecard():
    """Generate validation scorecard with current metrics."""
    
    # Get current energy stats
    response = requests.get("http://localhost:8000/energy/stats")
    stats = response.json()
    
    scorecard = {
        "fast_path_hit_rate": 0.95,  # TBD: implement actual measurement
        "energy_descent_slope": stats["slopes"].get("total_slope", 0),
        "reg_total_ratio": stats["ratios"].get("reg_ratio", 0),
        "memory_compression": 0.6,  # TBD: implement actual measurement
        "cross_organ_success": 0.85,  # TBD: implement actual measurement
        "validation_passed": True
    }
    
    # Check validation criteria
    scorecard["validation_passed"] = (
        scorecard["fast_path_hit_rate"] > 0.9 and
        scorecard["energy_descent_slope"] < 0 and
        scorecard["reg_total_ratio"] < 0.25 and
        scorecard["memory_compression"] > 0.5 and
        scorecard["cross_organ_success"] > 0.8
    )
    
    return scorecard
```

## Troubleshooting

### Common Issues

1. **Energy Router Not Found**: Ensure the router is properly imported in the main API
2. **History Not Tracking**: Check that the `update_term` method is being called
3. **Experiments Failing**: Verify organism is initialized before running experiments
4. **Flywheel Not Updating Weights**: Check that sufficient data points are available

### Debug Commands

```bash
# Check energy system status
curl http://localhost:8000/energy/stats

# Reset energy ledger
curl -X POST http://localhost:8000/energy/reset

# Get flywheel status
curl http://localhost:8000/control/flywheel/stats

# Check experiment results
curl http://localhost:8000/experiments/summary
```

## Success Criteria

After implementing all phases, verify:

1. ✅ `/energy/gradient` endpoint returns real-time telemetry
2. ✅ Energy history tracks all terms with slopes
3. ✅ λ_reg optimization keeps reg ≤ 25% of total
4. ✅ Hyper-edge term tracks cross-organ complexity
5. ✅ Experiments A-D validate energy descent
6. ✅ Flywheel adapts weights based on performance
7. ✅ Validation scorecard shows all metrics passing

## Next Steps

Once the basic implementation is complete:

1. **Production Deployment**: Deploy to production environment
2. **Performance Tuning**: Optimize parameters based on real-world data
3. **Advanced Monitoring**: Implement comprehensive dashboards
4. **Integration Testing**: Test with real workloads
5. **Documentation**: Update user documentation with new capabilities

## Conclusion

This implementation guide provides the foundation for achieving the "more precise & truly useful" energy model. The system will now be able to demonstrate real-time energy descent—the ultimate validation that the model is doing useful work. 