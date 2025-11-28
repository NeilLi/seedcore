## State + Energy + ML Unified Loop

SeedCore v2 implements a **continuous, self-regulating cognitive loop** built on three distinct planes: perception (StateService), cognition (ML Service), and optimization (EnergyService). EnergyService acts as the **brainstem driver**, running a 5-second control loop that orchestrates the entire flywheel mechanism.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│            ENERGY SERVICE (THE BRAINSTEM)                   │
│                                                              │
│  Background Sampler Loop (every 5 seconds):                 │
│    pull → compute → decide → feedback → ledger              │
└─────────────────────────────────────────────────────────────┘
                    │              │              │
          ┌─────────┘              └─────────┐    │
          ▼                                   ▼    │
┌──────────────┐                      ┌────────────┐
│ StateService │                      │ ML Service │
│ (Passive)    │                      │ (Stateless)│
└──────────────┘                      └────────────┘
```

---

## 1. Energy Service = The Brainstem Driver

EnergyService runs a **proactive background sampler** (`_background_sampler()`) that executes every 5 seconds. This is the **only process driving the entire flywheel** — it's the control loop, analogous to a nervous system reflex arc.

**The Control Loop:**
```
loop every 5 seconds:
    1. Pull metrics from StateService
    2. Request ML predictions
    3. Compute Hamiltonian energy (H_total)
    4. Calculate delta_E (energy change)
    5. Provide feedback to ML Service (adjust temperature)
    6. Write results to ledger
```

EnergyService is the **single source of truth for system stability** — it performs physics-inspired stability computation, makes policy decisions, and steers ML behavior through feedback.

---

## 2. Energy → State Service (Pull Metrics)

EnergyService calls:
```python
metrics = await state_client.get_system_metrics()
```

StateService returns a **lightweight distilled vector set**:

### Memory Distilled
- `ma` = aggregated agent metrics (total_agents, avg_capability, avg_memory_util, lifecycle_distribution, system_specialization_vector)
- `mw` = moving windows
- `mlt` = lifecycle table

### System Distilled
- `h_hgnn_norm` = system embedding norm
- `E_patterns` = hyperedge selection patterns
- `w_mode` = system mode weights
- `avg_role` = pre-computed role distribution {"E": float, "S": float, "O": float}
- `avg_capability` = aggregated capability
- `load_factor` = derived load metric
- `scaling_score` (optional) = pre-computed scaling signal
- `memory_anomaly_score` (optional) = pre-computed memory anomaly

**No raw agent snapshots.** StateService provides only pre-aggregated numbers.

**🏁 State Service = Passive Producer**
- Does not think
- Does not make decisions
- Only provides compressed, distilled metrics

---

## 3. Energy → ML Service (Predictive Models)

EnergyService sends the exact metrics it received:
```python
ml_stats = await ml_client.predict_all(metrics)
```

MLService runs **actual ML models** (no business logic):

### ML Model Inference
- **Neural CUSUM Drift Detector** — detects distribution shifts
- **Anomaly Score Combiner** — fuses drift + memory anomaly signals
- **XGBoost Scaling Model** (future) — predicts scaling needs

### MLService Returns
- `drift` = drift score (0-1)
- `drift_meta` = drift metadata (confidence, model_version, etc.)
- `anomaly` = anomaly score (0-1)
- `scaling_score` = scaling prediction (0-1)
- `p_pred` = role predictions {"E": float, "S": float, "O": float}
- `adaptive_params` = ML-only tuning parameters (e.g., `scaling_temperature`)

**🏁 ML Service = Stateless Math Machine**
- Does no business logic
- Uses no heuristics
- Stores nothing except snapshot for fallback
- Only runs model inference

---

## 4. Energy Service Computes Hamiltonian

EnergyService performs the physics-inspired stability computation:

```python
result = compute_energy_unified(
    unified_state,
    SystemParameters(
        weights=weights,
        memory_stats=memory_data,
        ml_stats=ml_stats,
    ),
)

total_energy = result.breakdown["total"]
```

The Hamiltonian includes:
- **T** = kinetic terms (pair interactions)
- **V** = potential terms (hyperedge patterns)
- **Entropy** = system disorder
- **Memory** = memory pressure
- **Drift term** = λ_drift × drift_score (ML-derived)
- **Anomaly term** = μ_anomaly × anomaly_score (ML-derived)

Then calculates:
```python
delta_E = E_current - E_previous
```

**Positive delta_E** = Energy is rising (bad/entropy increasing)  
**Negative delta_E** = Energy is falling (good/optimization happening)

**🏁 Energy Service = The Only "Thinking" Service**
- Performs physics-inspired stability computation
- Makes policy decisions
- Provides feedback to ML Service

---

## 5. Energy → ML Service Feedback Loop (The Flywheel)

This is the **closed-loop control mechanism** — the flywheel.

Based on `delta_E`, EnergyService adjusts ML Service behavior:

### If Energy is Worsening (delta_E > 0.05)
```
increase scaling_temperature → smoother predictions → more conservative behavior
```

**Scientific Explanation:**
High Temperature ($T \uparrow$) increases entropy in the probability distribution. It prevents the model from being "over-confident" about anomalies or scaling spikes, effectively acting as a **low-pass filter against noise**. This smooths out predictions and makes the system more conservative.

- System getting chaotic
- Smooth out ML predictions
- "Cool down" agent behavior
- Acts as a low-pass filter to reduce noise sensitivity

### If Energy is Improving (delta_E < -0.05)
```
decrease scaling_temperature → sharper predictions → allow riskier decisions
```

**Scientific Explanation:**
Low Temperature ($T \downarrow$) decreases entropy in the probability distribution, making the model more confident and allowing sharper, more decisive predictions. This enables the system to take calculated risks when energy is optimizing.

- System optimizing
- Allow sharper/riskier predictions
- "Sharpen" agent behavior
- Enables more decisive action when system is stable

EnergyService calls:
```python
await ml_client.update_adaptive_params({
    "scaling_temperature": new_temp
})
```

MLService updates its single tuning parameter (`scaling_temperature`), which affects future scaling predictions.

**🏁 This closes the "Flywheel Loop"**
- Analog to PID damping
- Smooths system oscillations
- Stabilizes ML predictive behavior
- Prevents feedback explosion

---

## 6. Energy Writes to Ledger (The Memory of the System)

EnergyService stores everything in the `EnergyLedger`:

- `E_total` = current total energy
- `delta_E` = energy change
- `drift` = drift score
- `anomaly` = anomaly score
- `scaling_score` = scaling prediction
- `scaling_temperature` = current ML tuning parameter
- Timestamps = temporal tracking

This makes every query **instant** — the ledger is the fast cache for all system stability metrics.

---

## 7. Coordinator Consumes Results (Decision Maker)

The **Coordinator** (Router/OrganismCore) is the primary consumer of the flywheel loop results. It reads from the Energy Ledger at O(1) speed to make routing and scaling decisions:

```python
# Fast read from ledger (no computation needed)
energy = await energy_client.get_metrics()
ml_stats = energy.get("ml_stats")  # Cached from last loop iteration

# Decision logic
if energy["drift"] > threshold:
    decision = "HGNN"  # Escalate to deep reasoning
elif energy["scaling_score"] > spawn_threshold:
    decision = "SPAWN"  # Scale up agents
else:
    decision = "FAST"  # Standard routing
```

**🏁 Coordinator = Decision Maker**
- Reads pre-computed results from ledger (O(1))
- Makes routing decisions (FAST/PLAN/HGNN)
- Executes scaling actions (spawn/kill agents)
- Posts flywheel results back to EnergyService for learning

---

## Complete Architecture Diagram

```mermaid
flowchart TD
    subgraph STATE["State Service (Passive Aggregator)"]
        S1[Aggregated Agent Metrics (ma)]
        S2[System Metrics (h_hgnn, E_patterns)]
        S3[Load, Capability, Roles]
        S4[Baseline Memory]
    end

    subgraph ENERGY["Energy Service (Driver + Physics Engine)"]
        E0[Background Sampler (5s loop)]
        E1[Pull Metrics from State]
        E2[Call ML /predict_all]
        E3[Compute H, ΔE]
        E4[Adjust Temperature]
        E5[Write Ledger]
    end

    subgraph ML["ML Service (Stateless Predictive Machine)"]
        M1[Drift Model]
        M2[Anomaly Combiner]
        M3[Scaling Model (future XGBoost)]
        M4[Adaptive Params: scaling_temperature]
    end

    subgraph CONSUMER["Coordinator (Decision Maker)"]
        C1[Read Ledger (O(1))]
        C2[Execute HGNN/Spawn/Kill]
    end

    E0 --> E1
    E1 --> S1
    E1 --> S2
    E1 --> S3
    E1 --> S4

    E1 --> E2
    E2 --> M1
    E2 --> M2
    E2 --> M3

    M1 --> E2
    M2 --> E2
    M3 --> E2

    E2 --> E3
    E3 --> E4
    E4 --> M4

    E3 --> E5
    E5 -.->|Fast Read| C1
    C1 --> C2
```

---

## Why This Architecture Is "Engineered Right"

### ✅ Separation of Responsibilities
- **State Service** = aggregation only (passive)
- **ML Service** = predictions only (stateless)
- **Energy Service** = physics, policy, steering (active driver)

### ✅ Stateless ML
- Ensures deterministic behavior
- No implicit coupling
- Pure function inputs → outputs

### ✅ Energy = Single Source of Truth
- Controls ML damping
- Controls system stability
- Makes all policy decisions

### ✅ No On-Demand Heavy Computation
- Background loop pre-computes everything
- User requests return instantly from ledger
- O(1) read performance

### ✅ Fully Automated Flywheel Loop
- System "automatically stabilizes itself"
- Continuous, self-regulating
- No manual intervention required

### ✅ Scales to Clusters
- Stateless design
- Clear boundaries
- No shared mutable state

---

## Implementation Details

### Background Sampler Flow

```python
async def _background_sampler():
    while True:
        # 1. Pull metrics from StateService
        metrics = await state_client.get_system_metrics()
        
        # 2. Request ML predictions
        ml_stats = await ml_client.predict_all(metrics)
        
        # 3. Compute energy
        unified_state = UnifiedState.from_payload(metrics)
        result = compute_energy_unified(unified_state, SystemParameters(ml_stats=ml_stats))
        total_energy = result.breakdown["total"]
        
        # 4. Execute flywheel feedback (calculate delta_E, adjust temperature)
        delta_E = await _execute_flywheel_feedback(total_energy, ml_stats)
        
        # 5. Write to ledger
        state.ledger.log_step(
            breakdown=result.breakdown,
            extra={"delta_E": delta_E, "drift": ml_stats["drift"], ...}
        )
        
        await asyncio.sleep(5.0)
```

### Flywheel Feedback Implementation

```python
async def _execute_flywheel_feedback(current_total_energy: float, ml_stats: Dict[str, Any]) -> float:
    # Get previous energy
    prev_total = state.ledger.total
    
    # Calculate delta_E
    delta_E = current_total_energy - prev_total
    
    # Adjust temperature based on energy change
    if delta_E > 0.05:  # Energy spiking
        new_temp = min(2.0, current_temp * 1.05)  # More conservative
    elif delta_E < -0.05:  # Energy optimizing
        new_temp = max(0.5, current_temp * 0.95)  # Sharper predictions
    
    # Send feedback to ML Service
    await ml_client.update_adaptive_params({"scaling_temperature": new_temp})
    
    return delta_E
```

---

## Evolution: From Request-Driven to Continuous Loop

This architecture represents the evolution from:

### ❌ Request-Driven AI
- User request → compute → response
- No continuous optimization
- No self-regulation

### ✅ Continuous, Self-Regulating Cognitive Loop
- Background control loop (every 5 seconds)
- Automatic stability adjustment
- Energy-driven optimization
- Same evolution seen in industrial autonomous control systems

---

## API Reference

### StateService
```python
# Get pre-computed, distilled metrics
metrics = await state_client.get_system_metrics()
# Returns: {"success": True, "metrics": {"memory": {...}, "system": {...}}}
```

### MLService
```python
# Unified ML inference
ml_stats = await ml_client.predict_all(metrics)
# Returns: {"ml_stats": {"drift": ..., "anomaly": ..., "scaling_score": ..., ...}}

# Update adaptive parameters (flywheel feedback)
await ml_client.update_adaptive_params({"scaling_temperature": 1.2})
```

### EnergyService
```python
# Fast read from ledger (O(1))
energy = await energy_client.get_metrics()
# Returns: {"total": ..., "drift_term": ..., "anomaly_term": ..., "delta_E": ...}

# On-demand computation (slower)
energy = await energy_client.compute_energy_from_state()
```

---

## Future Enhancements

### XGBoost Scaling Model
- Replace heuristic scaling prediction with trained XGBoost model
- Use distilled episodes for training
- Energy-based promotion gates

### Coordinator Integration
- Coordinator consumes Energy + ML metrics for routing decisions
- Uses drift for escalation thresholds
- Uses scaling_score for spawn decisions

### Automated Retraining
- Schedule `/xgboost/train_distilled` when drift exceeds threshold
- Use `/xgboost/promote` when delta_E improves consistently

---

## References

[^state-client]: `StateServiceClient.get_system_metrics()` — O(1) hot metrics endpoint  
[^ml-service]: ML Service endpoints — `/integrations/predict_all`, `/integrations/adaptive_params`  
[^energy-sampler]: `_background_sampler()` — 5-second control loop driver  
[^energy-client]: `EnergyServiceClient.get_metrics()` — fast ledger read  
[^flywheel]: `_execute_flywheel_feedback()` — closed-loop control mechanism
