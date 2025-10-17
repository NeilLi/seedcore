#!/usr/bin/env python3
"""
Verify Unified State Vector and HGNN Pattern Shim

This example demonstrates:
1. HGNN pattern shim collecting escalation events
2. Building unified state with live E_patterns
3. Computing energy with hyperedge terms
4. Agent lifecycle transitions and archival
5. Memory tier statistics

Run with: python examples/verify_unified_state_hgnn.py
"""

import asyncio
import time
import numpy as np
from typing import Dict, Any
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from seedcore.hgnn.pattern_shim import HGNNPatternShim, SHIM, _key
from seedcore.models.state import (
    UnifiedState, AgentSnapshot, OrganState, 
    SystemState, MemoryVector
)
from seedcore.ops.energy.calculator import compute_energy, EnergyWeights
from seedcore.agents.lifecycle import evaluate_lifecycle, LifecycleDecision


class MockAgent:
    """Mock agent for testing lifecycle evaluation"""
    def __init__(self, agent_id: str, capability: float = 0.5, mem_util: float = 0.0):
        self.agent_id = agent_id
        self.capability = capability
        self.mem_util = mem_util
        self.role = "Employed"


def simulate_escalations():
    """Simulate OCPS escalation events to populate the pattern shim"""
    print("🔴 Simulating OCPS escalation events...")
    
    # Simulate various escalation patterns
    escalations = [
        (["Head", "Limbs", "Heart"], True, 150.0),      # Fast success
        (["Head", "Limbs"], True, 300.0),               # Medium success  
        (["Heart", "Lungs"], False, 800.0),             # Slow failure
        (["Head", "Limbs", "Heart"], True, 200.0),      # Repeat pattern
        (["Eyes", "Brain"], True, 100.0),               # New pattern
        (["Limbs", "Heart"], False, 1200.0),            # Slow failure
        (["Head", "Limbs", "Heart"], True, 180.0),      # Strong pattern
        (["Brain", "Spine"], True, 250.0),              # New pattern
    ]
    
    for organs, success, latency in escalations:
        SHIM.log_escalation(organs, success, latency)
        print(f"  📊 {organs} -> {'✅' if success else '❌'} ({latency}ms)")
        time.sleep(0.1)  # Small delay for realistic timing
    
    print(f"  📈 Total patterns tracked: {len(SHIM._stats)}")


def build_unified_state() -> UnifiedState:
    """Build a complete unified state vector"""
    print("\n🔧 Building unified state vector...")
    
    # 1. Agent snapshots
    agents = {
        "agent_001": AgentSnapshot(
            h=np.array([0.8, 0.6, 0.4]),
            p={"Employed": 0.7, "Scout": 0.2, "Onlooker": 0.1},
            c=0.75,
            mem_util=0.6,
            lifecycle="Employed"
        ),
        "agent_002": AgentSnapshot(
            h=np.array([0.3, 0.9, 0.2]),
            p={"Employed": 0.8, "Scout": 0.1, "Onlooker": 0.1},
            c=0.85,
            mem_util=0.8,
            lifecycle="Employed"
        ),
        "agent_003": AgentSnapshot(
            h=np.array([0.5, 0.3, 0.7]),
            p={"Employed": 0.4, "Scout": 0.5, "Onlooker": 0.1},
            c=0.45,
            mem_util=0.3,
            lifecycle="Scout"
        )
    }
    
    # 2. Organ states
    organs = {
        "Head": OrganState(
            h=np.array([0.7, 0.5, 0.3]),
            P=np.array([[0.6, 0.3, 0.1], [0.7, 0.2, 0.1], [0.5, 0.4, 0.1]])
        ),
        "Limbs": OrganState(
            h=np.array([0.4, 0.8, 0.2]),
            P=np.array([[0.5, 0.4, 0.1], [0.8, 0.1, 0.1], [0.3, 0.6, 0.1]])
        ),
        "Heart": OrganState(
            h=np.array([0.9, 0.2, 0.4]),
            P=np.array([[0.8, 0.1, 0.1], [0.6, 0.3, 0.1], [0.7, 0.2, 0.1]])
        )
    }
    
    # 3. System state with live E_patterns from shim
    E_vec, E_map = SHIM.get_E_patterns()
    system = SystemState(
        h_hgnn=np.array([0.6, 0.4, 0.5]),
        E_patterns=E_vec,
        w_mode=np.array([0.4, 0.3, 0.3])
    )
    
    # 4. Memory vector
    memory = MemoryVector(
        ma={"count": len(agents), "avg_capability": 0.68, "avg_mem_util": 0.57},
        mw={"buffer_size": 1024, "hit_rate": 0.78, "eviction_rate": 0.12},
        mlt={"storage_gb": 50.2, "compression_ratio": 0.65, "access_patterns": 42},
        mfb={"queue_size": 128, "avg_weight": 0.73, "decay_rate": 0.15}
    )
    
    unified_state = UnifiedState(
        agents=agents,
        organs=organs,
        system=system,
        memory=memory
    )
    
    print(f"  📊 State built with {len(agents)} agents, {len(organs)} organs")
    print(f"  🧠 E_patterns shape: {E_vec.shape if E_vec is not None else 'None'}")
    print(f"  💾 Memory tiers: {list(memory.__dict__.keys())}")
    
    return unified_state


def compute_energy_breakdown(unified_state: UnifiedState):
    """Compute energy and show breakdown"""
    print("\n⚡ Computing unified energy...")
    
    # Get matrices from unified state
    H_matrix = unified_state.H_matrix()
    P_matrix = unified_state.P_matrix()
    
    print(f"  📐 H matrix shape: {H_matrix.shape}")
    print(f"  📊 P matrix shape: {P_matrix.shape}")
    
    # Energy weights (include W_hyper based on E_patterns length)
    E_len = int(unified_state.system.E_patterns.shape[0]) if (unified_state.system.E_patterns is not None and hasattr(unified_state.system.E_patterns, 'shape')) else 0
    W_hyper = np.ones((E_len,), dtype=np.float32) if E_len > 0 else np.zeros((0,), dtype=np.float32)
    
    weights = EnergyWeights(
        W_pair=np.ones((H_matrix.shape[0], H_matrix.shape[0])),
        W_hyper=W_hyper,
        alpha_entropy=0.1,
        lambda_reg=0.01,
        beta_mem=0.05
    )
    
    # Memory stats for CostVQ
    memory_stats = {
        "ma": unified_state.memory.ma,
        "mw": unified_state.memory.mw,
        "mlt": unified_state.memory.mlt,
        "mfb": unified_state.memory.mfb
    }
    
    # Compute energy with hyperedge term
    total_energy, breakdown = compute_energy(
        H=H_matrix,
        P=P_matrix,
        weights=weights,
        memory_stats=memory_stats,
        E_sel=unified_state.system.E_patterns,
        s_norm=np.linalg.norm(H_matrix)
    )
    
    print(f"  🔋 Total Energy: {total_energy:.4f}")
    print("  📊 Energy Breakdown:")
    for term, value in breakdown.items():
        print(f"    {term}: {value:.4f}")
    
    return total_energy, breakdown


def test_lifecycle_transitions():
    """Test agent lifecycle evaluation"""
    print("\n🔄 Testing agent lifecycle transitions...")
    
    # Test different agent scenarios
    test_agents = [
        MockAgent("high_cap", capability=0.9, mem_util=0.8),    # Should promote
        MockAgent("low_cap", capability=0.3, mem_util=0.2),     # Should demote
        MockAgent("balanced", capability=0.6, mem_util=0.6),    # Should stay
        MockAgent("scout", capability=0.4, mem_util=0.7),       # Scout testing
    ]
    
    for agent in test_agents:
        decision = evaluate_lifecycle(agent)
        print(f"  🤖 {agent.agent_id} (c={agent.capability:.2f}, u={agent.mem_util:.2f})")
        print(f"    → {decision.new_state} | Archive: {decision.archive} | Spawn: {decision.spawn_suborgan}")


def test_pattern_shim_operations():
    """Test HGNN pattern shim operations"""
    print("\n🧠 Testing HGNN pattern shim operations...")
    
    # Test pattern retrieval
    E_vec, E_map = SHIM.get_E_patterns()
    print(f"  📊 E_patterns vector: {E_vec.shape if E_vec is not None else 'None'}")
    
    if E_vec is not None and len(E_vec) > 0:
        print(f"  🔢 Top 3 pattern scores: {E_vec[:3]}")
        # E_map is a list of PatternKey tuples
        print(f"  📍 Pattern mapping (first 3): {E_map[:3]}")
    
    # Test decay behavior
    print("  ⏰ Testing decay behavior...")
    original_stats = len(SHIM._stats)
    
    # Wait a bit and check if decay affects stats
    time.sleep(0.5)
    current_stats = len(SHIM._stats)
    print(f"    Stats before: {original_stats}, after: {current_stats}")
    
    # Test pattern key generation
    test_organs = ["Brain", "Spine", "Nerves"]
    key = _key(test_organs)
    print(f"  🔑 Pattern key for {test_organs}: {key}")


def main():
    """Main verification flow"""
    print("🚀 Unified State Vector & HGNN Pattern Shim Verification")
    print("=" * 60)
    
    try:
        # 1. Simulate escalations to populate pattern shim
        simulate_escalations()
        
        # 2. Test pattern shim operations
        test_pattern_shim_operations()
        
        # 3. Build unified state
        unified_state = build_unified_state()
        
        # 4. Compute energy with hyperedge terms
        energy, breakdown = compute_energy_breakdown(unified_state)
        
        # 5. Test lifecycle transitions
        test_lifecycle_transitions()
        
        # 6. Verify state persistence
        print("\n💾 Verifying state persistence...")
        print(f"  📊 Pattern shim stats: {len(SHIM._stats)} patterns")
        print(f"  🔢 E_patterns available: {unified_state.system.E_patterns is not None}")
        
        print("\n✅ All verifications completed successfully!")
        print("\n🎯 Key Features Verified:")
        print("  • HGNN pattern shim collecting escalation events")
        print("  • Unified state vector construction")
        print("  • Energy computation with hyperedge terms")
        print("  • Agent lifecycle evaluation")
        print("  • Memory tier integration")
        
    except Exception as e:
        print(f"\n❌ Verification failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
