# Energy Validation Analysis & Implementation Roadmap

## Executive Summary

This document analyzes the current SeedCore energy system implementation against the validation blueprint and provides a concrete roadmap for achieving the "more precise & truly useful" energy model described in the specification.

## Current State Analysis

### ✅ What's Working

1. **Energy Ledger Foundation**: The `EnergyLedger` class correctly implements the five-term structure (pair, hyper, entropy, reg, mem) with proper total calculation
2. **Basic Energy Calculation**: Core energy terms are implemented in `calculator.py` with proper mathematical formulations
3. **Control Loop Structure**: Fast loop (200ms) and slow loop (2s) frameworks exist in `control/` directory
4. **Telemetry Infrastructure**: Prometheus metrics are set up for energy monitoring
5. **Organism Architecture**: COA organ-based structure is properly implemented

### ❌ Critical Gaps Identified

#### 1. Missing `/energy/gradient` Endpoint
- **Current**: Only CLI prints and basic API functions
- **Required**: Real-time JSON payload for every task with per-term ΔE and slopes
- **Impact**: No programmatic access for dashboards or RL loops

#### 2. Regularization Dominance (164% of positive energy)
- **Current**: λ_reg = 0.01 in config, but embeddings are bloating the objective
- **Required**: Dynamic λ_reg adjustment via PSO loop
- **Impact**: System is over-regularized, masking true performance

#### 3. Hyper-Edge Term Wiring via HGNN Shim
- **Now**: HGNN pattern shim provides bounded `E_patterns` from escalations; telemetry includes them in unified state
- **Next**: Learn or configure `W_hyper` and use unified calculator API to contribute hyper term to total energy

#### 4. Static Capability & Memory-Utility
- **Current**: Hard-coded capability values, no EWMA updates
- **Required**: Dynamic ci & ui updates driving pair weight scaling
- **Impact**: Pair weights never adapt to performance

#### 5. No Experimental Harness
- **Current**: One-shot unit tests only
- **Required**: Synthetic workloads A-D for stress testing
- **Impact**: Cannot validate energy descent slopes or stability

## Detailed Gap Analysis

### Current Energy Values vs. Expected Behavior

| Term | Current Value | Expected Behavior | Gap |
|------|---------------|-------------------|-----|
| **Pair** | -0.8600 | Should trend ↓ with cooperation | ✅ Working correctly |
| **Entropy** | -0.2929 | Should trend ↓ with specialization | ✅ Working correctly |
| **Regularization** | +2.9275 | Should be <25% of total | ❌ **164% of positive energy** |
| **Memory** | +0.0075 | Should reflect compression/staleness | ❌ Essentially noise |
| **Hyper** | 0.0 | Should track cross-organ complexity | ❌ **Completely missing** |

### Missing Control Loops

1. **Fast Loop (200ms)**: ✅ Implemented but not energy-aware
2. **Slow Loop (2s)**: ✅ Basic PSO exists but no λ_reg optimization
3. **Hourly Flywheel**: ❌ **Missing** - no global weight adaptation

### Missing Observability

1. **Real-time Gradients**: ❌ No `/energy/gradient` endpoint
2. **Slope Tracking**: ❌ No windowed ΔE calculations
3. **Memory Pressure**: ❌ No CostVQ integration
4. **Validation Scorecard**: ❌ No Table 4 metrics

## Implementation Roadmap

### Phase 1: Telemetry & Observability (Days 1-2)

#### 1.1 Implement `/energy/gradient` Endpoint

```python
# Add to src/seedcore/api/routers/energy_router.py
@router.get("/energy/gradient")
async def get_energy_gradient():
    """Real-time energy gradient telemetry endpoint."""
    return {
        "ts": time.time(),
        "E_terms": {
            "pair": ledger.terms.pair,
            "hyper": ledger.terms.hyper,
            "entropy": ledger.terms.entropy,
            "reg": ledger.terms.reg,
            "mem": ledger.terms.mem,
            "total": ledger.get_total()
        },
        "deltaE_last": ledger.last_delta,
        "slopes": {
            "pair_slope": calculate_slope(ledger.pair_history, window=100),
            "hyper_slope": calculate_slope(ledger.hyper_history, window=100),
            "entropy_slope": calculate_slope(ledger.entropy_history, window=100),
            "reg_slope": calculate_slope(ledger.reg_history, window=100),
            "mem_slope": calculate_slope(ledger.mem_history, window=100)
        },
        "mem_pressure": {
            "cost_vq": memory_system.get_cost_vq(),
            "compression_ratio": memory_system.get_compression_ratio(),
            "staleness": memory_system.get_average_staleness()
        }
    }
```

#### 1.2 Add Energy History Tracking

```python
# Enhance src/seedcore/energy/ledger.py
class EnergyLedger:
    def __init__(self):
        self.terms = EnergyTerms()
        self.pair_history = deque(maxlen=1000)
        self.hyper_history = deque(maxlen=1000)
        self.entropy_history = deque(maxlen=1000)
        self.reg_history = deque(maxlen=1000)
        self.mem_history = deque(maxlen=1000)
        self.last_delta = 0.0
    
    def update_term(self, term: str, delta: float):
        """Update term with history tracking."""
        setattr(self.terms, term, getattr(self.terms, term) + delta)
        getattr(self, f"{term}_history").append(getattr(self.terms, term))
        self.last_delta = delta
```

### Phase 2: Adaptive Control (Days 3-4)

#### 2.1 Implement EWMA Updates for Capability & Memory-Utility

```python
# Add to src/seedcore/energy/calculator.py
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

#### 2.2 Add PSO for λ_reg Optimization

```python
# Add to src/seedcore/control/slow_loop.py
def optimize_lambda_reg(ledger: EnergyLedger, target_reg_ratio: float = 0.25):
    """PSO optimization for λ_reg to keep reg ≤ 25% of total."""
    current_reg_ratio = ledger.terms.reg / max(ledger.get_total(), 1e-6)
    
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

#### 3.1 Implement Cross-Organ Task Tracking

```python
# Add to src/seedcore/energy/calculator.py
def on_hyper_exec(event: Dict[str, Any], ledger: EnergyLedger):
    """Update hyper energy term after cross-organ task."""
    source_organ = event['source_organ']
    target_organ = event['target_organ']
    complexity = event['complexity']
    precision = event['precision']
    
    # Hyper energy increases with complexity, decreases with precision
    delta = complexity - precision
    
    # Scale by organ distance (more distant = higher cost)
    organ_distance = calculate_organ_distance(source_organ, target_organ)
    scaled_delta = delta * (1 + 0.1 * organ_distance)
    
    ledger.terms.hyper += scaled_delta
    ledger.hyper_history.append(ledger.terms.hyper)
    
    logger.info(f"Hyper edge: {source_organ}→{target_organ}, Δ={scaled_delta:.4f}")
```

#### 3.2 Add Organ Distance Calculation

```python
# Add to src/seedcore/organs/organism_manager.py
def calculate_organ_distance(organ1_id: str, organ2_id: str) -> int:
    """Calculate distance between organs in the organism graph."""
    # Simple distance based on organ types
    organ1_type = self.get_organ_type(organ1_id)
    organ2_type = self.get_organ_type(organ2_id)
    
    if organ1_type == organ2_type:
        return 0
    elif (organ1_type, organ2_type) in [("Cognitive", "Actuator"), ("Actuator", "Utility")]:
        return 1
    else:
        return 2  # Cognitive ↔ Utility
```

### Phase 4: Experimental Harness (Day 6)

#### 4.1 Implement Synthetic Workloads A-D

```python
# Add to src/seedcore/experiments/harness.py
class EnergyValidationHarness:
    def __init__(self, organism_manager, energy_ledger):
        self.organism = organism_manager
        self.ledger = energy_ledger
        self.results = []
    
    async def experiment_A_pair(self):
        """Synthetic same-organ dual-agent tasks → expect pair slope < 0."""
        logger.info("Running Experiment A: Pair Energy Validation")
        
        # Create synthetic tasks for same-organ agents
        cognitive_organ = self.organism.get_organ_handle("cognitive_organ_1")
        
        for i in range(50):
            task = {
                "type": "collaborative_reasoning",
                "complexity": 0.5 + 0.1 * i,
                "agents_required": 2
            }
            
            result = await cognitive_organ.run_task.remote(task)
            self.results.append({
                "experiment": "A",
                "step": i,
                "energy": self.ledger.get_total(),
                "pair_energy": self.ledger.terms.pair
            })
        
        # Calculate slope
        pair_slope = self.calculate_slope([r["pair_energy"] for r in self.results])
        logger.info(f"Experiment A complete. Pair slope: {pair_slope:.4f}")
        return pair_slope < 0  # Should be negative
    
    async def experiment_B_hyper(self):
        """Force escalations across two organs to train hyper-edge weights."""
        logger.info("Running Experiment B: Hyper-Edge Validation")
        
        for i in range(30):
            # Create cross-organ escalation task
            task = {
                "type": "cross_organ_escalation",
                "source_organ": "cognitive_organ_1",
                "target_organ": "actuator_organ_1",
                "complexity": 0.7,
                "precision": 0.3
            }
            
            result = await self.organism.execute_task_on_organ("cognitive_organ_1", task)
            self.results.append({
                "experiment": "B",
                "step": i,
                "energy": self.ledger.get_total(),
                "hyper_energy": self.ledger.terms.hyper
            })
        
        hyper_slope = self.calculate_slope([r["hyper_energy"] for r in self.results])
        logger.info(f"Experiment B complete. Hyper slope: {hyper_slope:.4f}")
        return hyper_slope > 0  # Should be positive (complexity > precision)
    
    async def experiment_C_entropy(self):
        """Lock roles to collapse entropy, then release; watch entropy/pair spikes drop."""
        logger.info("Running Experiment C: Entropy Validation")
        
        # Phase 1: Lock roles (low entropy)
        await self.lock_agent_roles()
        for i in range(20):
            task = {"type": "standard_task"}
            await self.organism.execute_task_on_random_organ(task)
            self.results.append({
                "experiment": "C",
                "phase": "locked",
                "step": i,
                "entropy": self.ledger.terms.entropy
            })
        
        # Phase 2: Release roles (high entropy)
        await self.release_agent_roles()
        for i in range(20):
            task = {"type": "standard_task"}
            await self.organism.execute_task_on_random_organ(task)
            self.results.append({
                "experiment": "C",
                "phase": "released",
                "step": i,
                "entropy": self.ledger.terms.entropy
            })
        
        # Calculate entropy change
        locked_entropy = np.mean([r["entropy"] for r in self.results if r["phase"] == "locked"])
        released_entropy = np.mean([r["entropy"] for r in self.results if r["phase"] == "released"])
        
        logger.info(f"Experiment C complete. Entropy change: {released_entropy - locked_entropy:.4f}")
        return released_entropy > locked_entropy
    
    async def experiment_D_memory(self):
        """Sweep VQ-VAE compression threshold; plot mem-term vs staleness."""
        logger.info("Running Experiment D: Memory Validation")
        
        compression_thresholds = [0.1, 0.3, 0.5, 0.7, 0.9]
        
        for threshold in compression_thresholds:
            # Set compression threshold
            await self.set_memory_compression_threshold(threshold)
            
            # Run tasks and measure memory energy
            for i in range(10):
                task = {"type": "memory_intensive_task"}
                await self.organism.execute_task_on_random_organ(task)
                self.results.append({
                    "experiment": "D",
                    "threshold": threshold,
                    "step": i,
                    "mem_energy": self.ledger.terms.mem,
                    "staleness": self.get_memory_staleness()
                })
        
        # Plot results
        self.plot_memory_experiment_results()
        logger.info("Experiment D complete. Check plots for memory vs staleness.")
    
    def calculate_slope(self, values: List[float], window: int = 10) -> float:
        """Calculate slope of recent values using linear regression."""
        if len(values) < window:
            return 0.0
        
        recent_values = values[-window:]
        x = np.arange(len(recent_values))
        slope, _ = np.polyfit(x, recent_values, 1)
        return slope
```

### Phase 5: Hourly Flywheel (Day 7)

#### 5.1 Implement Global Weight Adaptation

```python
# Add to src/seedcore/control/flywheel.py
class HourlyFlywheel:
    def __init__(self, organism_manager, energy_ledger):
        self.organism = organism_manager
        self.ledger = energy_ledger
        self.weight_history = []
    
    async def run_flywheel_cycle(self):
        """Hourly global weight adaptation using windowed metrics."""
        logger.info("Running hourly flywheel cycle...")
        
        # Calculate windowed performance metrics
        window_size = 3600  # 1 hour of data points
        recent_energy = self.ledger.get_recent_energy(window_size)
        
        if len(recent_energy) < 10:  # Need minimum data points
            logger.warning("Insufficient data for flywheel cycle")
            return
        
        # Calculate adaptive formula from §21.1
        delta_spec = self.calculate_delta_spec(recent_energy)
        delta_acc = self.calculate_delta_acc(recent_energy)
        delta_smart = self.calculate_delta_smart(recent_energy)
        delta_reason = self.calculate_delta_reason(recent_energy)
        
        # Update global weights
        self.update_global_weights(delta_spec, delta_acc, delta_smart, delta_reason)
        
        # Log results
        self.weight_history.append({
            "timestamp": time.time(),
            "delta_spec": delta_spec,
            "delta_acc": delta_acc,
            "delta_smart": delta_smart,
            "delta_reason": delta_reason,
            "weights": self.get_current_weights()
        })
        
        logger.info(f"Flywheel cycle complete. Weight updates applied.")
    
    def update_global_weights(self, delta_spec, delta_acc, delta_smart, delta_reason):
        """Update global weights based on performance deltas."""
        # Adaptive weight updates based on §21.1 formula
        if delta_spec > 0:  # Specialization improving
            self.ledger.alpha *= 1.05  # Increase entropy weight
        else:
            self.ledger.alpha *= 0.95  # Decrease entropy weight
        
        if delta_acc > 0:  # Accuracy improving
            self.ledger.lambda_reg *= 0.95  # Reduce regularization
        else:
            self.ledger.lambda_reg *= 1.05  # Increase regularization
        
        if delta_smart > 0:  # Smartness improving
            self.ledger.beta_mem *= 1.05  # Increase memory weight
        else:
            self.ledger.beta_mem *= 0.95  # Decrease memory weight
        
        # Clamp weights to reasonable ranges
        self.ledger.alpha = np.clip(self.ledger.alpha, 0.1, 2.0)
        self.ledger.lambda_reg = np.clip(self.ledger.lambda_reg, 0.001, 0.1)
        self.ledger.beta_mem = np.clip(self.ledger.beta_mem, 0.05, 0.5)
```

## Validation Scorecard (Table 4)

### Target Metrics

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| **Fast Path Hit Rate** | >90% | TBD | ❌ Not measured |
| **Energy Descent Slope** | <0 | TBD | ❌ Not measured |
| **Reg/Total Ratio** | <25% | 164% | ❌ **Critical** |
| **Memory Compression** | >50% | TBD | ❌ Not measured |
| **Cross-Organ Success** | >80% | TBD | ❌ Not measured |

### Success Criteria

1. **Total Energy Descends**: E_total should trend downward over time
2. **Reg ≤ 25%**: Regularization should not dominate the objective
3. **Pair Slope < 0**: Cooperation should reduce energy
4. **Hyper Slope > 0**: Cross-organ complexity should be tracked
5. **Memory Efficiency**: Compression should reduce memory energy

## Implementation Checklist

### Week 1 Sprint (7 days)

- [ ] **Day 1-2**: Implement `/energy/gradient` endpoint & energy history tracking
- [ ] **Day 3-4**: Add EWMA updates for ci, ui; implement pair-weight scaling
- [ ] **Day 5**: Add PSO λ_reg optimizer; expose λ_reg control knob
- [ ] **Day 6**: Implement synthetic workloads A-D; add auto-plotting
- [ ] **Day 7**: Add hourly flywheel; tune λ_reg until reg ≤ 25% of total

### Week 2 Validation

- [ ] Run all experiments A-D and validate slopes
- [ ] Implement validation scorecard (Table 4)
- [ ] Create energy descent dashboards
- [ ] Document performance improvements
- [ ] Update configuration defaults

## Expected Outcomes

After implementing this roadmap:

1. **Real-time Observability**: `/energy/gradient` provides live energy telemetry
2. **Adaptive Control**: PSO and flywheel loops optimize system performance
3. **Validated Energy Model**: Experiments prove the unified energy principle
4. **Production Readiness**: System can demonstrate energy descent in real-time

## Conclusion

The current SeedCore energy system has a solid foundation but lacks the adaptive control and validation mechanisms needed for production use. By implementing the telemetry, control loops, and experimental harness described above, the system will achieve the "more precise & truly useful" energy model that can demonstrate real-time energy descent—the ultimate validation that the model is doing useful work. 