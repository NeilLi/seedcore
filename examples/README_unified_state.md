# Unified State Vector & HGNN Pattern Shim Examples

This directory contains examples that verify the implementation of the unified state vector, HGNN pattern shim, and energy calculations as described in the COA (Cognitive Organism Architecture) minimal model.

## Examples Overview

### 1. `verify_unified_state_hgnn.py` - Comprehensive Verification
**Purpose**: Full end-to-end test of all unified state components
**Features**:
- Simulates OCPS escalation events
- Builds complete unified state vector
- Computes energy with hyperedge terms
- Tests agent lifecycle transitions
- Verifies memory tier integration

**Run with**:
```bash
cd examples
python verify_unified_state_hgnn.py
```

### 2. `test_hgnn_shim_simple.py` - Pattern Shim Focus
**Purpose**: Quick verification of HGNN pattern shim functionality
**Features**:
- Basic escalation logging
- Pattern retrieval and decay
- Edge case handling
- Minimal dependencies

**Run with**:
```bash
cd examples
python test_hgnn_shim_simple.py
```

## What These Examples Verify

### ✅ Unified State Vector Structure
- **Agent-level**: Embeddings (h), role distributions (p), capability scores (c), memory utility
- **Organ-level**: Aggregated role distributions and performance metrics
- **System-level**: Global patterns (hyperedges), HGNN embeddings, mode weights
- **Memory-level**: Statistics for all four memory tiers (Ma, Mw, Mlt, Mfb)

### ✅ HGNN Pattern Shim
- Collects escalation events as hyperedges
- Tracks success/failure with exponential decay
- Produces bounded E_patterns vector ∈ [0,1]^K
- Maintains contractivity (∥αₑ∥≤1) for energy stability

### ✅ Energy Function Integration
- **Pair term**: Agent similarity interactions
- **Hyper term**: Hyperedge pattern contributions (NEW)
- **Entropy term**: Role diversity maintenance
- **Regularization**: State norm control
- **Memory term**: CostVQ for memory efficiency

### ✅ Agent Lifecycle Management
- **Scout → Employed → Specialist → Archived** transitions
- Capability and memory utility thresholds
- Archive semantics preserving historical data
- Suborgan spawning decisions

## Expected Output

### Successful Run
```
🚀 Unified State Vector & HGNN Pattern Shim Verification
============================================================
🔴 Simulating OCPS escalation events...
  📊 ['Head', 'Limbs', 'Heart'] -> ✅ (150.0ms)
  📊 ['Head', 'Limbs'] -> ✅ (300.0ms)
  📊 ['Heart', 'Lungs'] -> ❌ (800.0ms)
  📈 Total patterns tracked: 8

🧠 Testing HGNN pattern shim operations...
  📊 E_patterns vector: (8,)
  🔢 Top 3 pattern scores: [0.85, 0.72, 0.68]
  📍 Pattern mapping: [('Brain', 'Spine'), ('Eyes', 'Brain'), ('Head', 'Limbs')]

🔧 Building unified state vector...
  📊 State built with 3 agents, 3 organs
  🧠 E_patterns shape: (8,)
  💾 Memory tiers: ['ma', 'mw', 'mlt', 'mfb']

⚡ Computing unified energy...
  📐 H matrix shape: (3, 3)
  📊 P matrix shape: (3, 3)
  🔋 Total Energy: -2.8473
  📊 Energy Breakdown:
    pair: -1.2345
    hyper: -0.9876
    entropy: -0.3456
    reg: 0.1234
    mem: -0.4030

🔄 Testing agent lifecycle transitions...
  🤖 high_cap (c=0.90, u=0.80)
    → Specialist | Archive: False | Spawn: True
  🤖 low_cap (c=0.30, u=0.20)
    → Scout | Archive: False | Spawn: False

✅ All verifications completed successfully!
```

### Error Cases
- **Import errors**: Check that `src/seedcore` is in Python path
- **Missing dependencies**: Install required packages (numpy, etc.)
- **Module not found**: Verify all patched files exist

## Architecture Notes

### Memory Tiers
- **Ma (Tier-0)**: Per-agent summaries, lightweight
- **Mw (Tier-1)**: Working buffers, hot caches
- **Mlt (Tier-2)**: Long-term storage statistics
- **Mfb (Tier-3)**: Flashbulb queue for high-impact events

### Pattern Decay
- Exponential decay with configurable half-life (default: 900s)
- Prevents unbounded memory growth
- Approximates online template learning

### Energy Stability
- Bounded hyperedge weights ensure contractivity
- Gradient signals available for control systems
- Memory cost function prevents resource exhaustion

## Troubleshooting

### Common Issues
1. **Import errors**: Ensure working directory is correct
2. **Path issues**: Check `sys.path.insert()` in examples
3. **Missing modules**: Verify all patches were applied correctly
4. **Dependencies**: Install numpy and other required packages

### Debug Mode
Add debug prints to see intermediate values:
```python
print(f"Debug: E_vec = {E_vec}")
print(f"Debug: H_matrix = {H_matrix}")
```

## Next Steps

After verifying these examples work:
1. **Integration**: Connect to real OCPS escalation logs
2. **Scaling**: Test with larger agent populations
3. **Persistence**: Add database storage for patterns
4. **Monitoring**: Build dashboards for energy metrics
5. **Control**: Implement feedback loops using energy gradients
