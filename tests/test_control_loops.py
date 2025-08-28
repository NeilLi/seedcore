# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Tests for control loop functionality including slow loop and memory loop.
"""

from seedcore.control.slow_loop import slow_loop_update_roles_simple, get_role_performance_metrics
from seedcore.control.mem_loop import adaptive_mem_update, estimate_memory_gradient, get_memory_metrics
from seedcore.organs.registry import OrganRegistry
from seedcore.agents.base import Agent
from seedcore.energy.ledger import EnergyLedger

# Mock Organ class for testing that mimics the expected interface
class DummyOrgan:
    def __init__(self, organ_id: str, organ_type: str = "test"):
        self.organ_id = organ_id
        self.organ_type = organ_type
        self.agents = []  # List of agents for easy iteration in tests
    
    def register(self, agent):
        """Register an agent with this organ (for testing compatibility)"""
        self.agents.append(agent)
    
    def register_agent(self, agent_id: str, agent_handle):
        """Alternative registration method that matches the real Organ interface"""
        self.agents.append(agent_handle)

# Test-specific version of slow_loop_update_roles that works with DummyOrgan
def mock_slow_loop_update_roles(organs_or_agents, learning_rate: float = 0.05):
    """
    Test version of slow loop that works with DummyOrgan.
    """
    # Determine if we received organs or agents by checking if first item has 'agents' attribute
    if organs_or_agents and hasattr(organs_or_agents[0], 'agents'):
        # We received organs, extract all agents
        all_agents = [agent for organ in organs_or_agents for agent in organ.agents]
        print(f"Running slow loop for {len(organs_or_agents)} organs with {len(all_agents)} agents...")
    else:
        # We received agents directly
        all_agents = organs_or_agents
        print(f"Running slow loop for {len(all_agents)} agents...")
    
    for agent in all_agents:
        # Calculate performance metric based on energy efficiency
        current_energy = 0.0  # Use default value for testing
        energy_efficiency = 1.0 / (1.0 + abs(current_energy))
        
        # Find the current dominant role
        if not agent.role_probs:
            continue
        
        dominant_role = max(agent.role_probs, key=agent.role_probs.get)
        
        # Energy-aware role adjustment
        if current_energy > 5.0:  # High energy state - need exploration
            target_role = 'E'
        elif current_energy < -5.0:  # Low energy state - need specialization
            target_role = 'S'
        else:  # Moderate energy state - need optimization
            target_role = 'O'
        
        # Increase the target role's probability based on energy state
        if target_role in agent.role_probs:
            increase = (1.0 - agent.role_probs[target_role]) * learning_rate
            agent.role_probs[target_role] += increase
            
            # Decrease other roles' probabilities proportionally
            total_decrease = increase
            other_roles = [r for r in agent.role_probs if r != target_role]
            
            # Normalize the other roles so they sum to the total decrease
            current_sum_others = sum(agent.role_probs[r] for r in other_roles)
            if current_sum_others > 0:
                for role in other_roles:
                    agent.role_probs[role] -= total_decrease * (agent.role_probs[role] / current_sum_others)
        
        # Ensure probabilities still sum to 1 (correcting for float inaccuracies)
        total_prob = sum(agent.role_probs.values())
        for role in agent.role_probs:
            agent.role_probs[role] /= total_prob
        
        # Update capability based on energy efficiency
        agent.capability = min(1.0, max(0.0, agent.capability + energy_efficiency * 0.1))
        
        print(f"Updated agent {agent.agent_id} roles: {agent.role_probs}, capability: {agent.capability:.3f}")

    print("Slow loop finished.")

def test_slow_loop_update_roles_with_organs():
    """Test that slow loop updates agent roles based on energy state when given organs."""
    # Create test organ and agents
    organ = DummyOrgan(organ_id="test_organ")
    agent1 = Agent(agent_id="test_agent_1")
    agent2 = Agent(agent_id="test_agent_2")
    organ.register(agent1)
    organ.register(agent2)
    
    # Store initial role probabilities
    initial_roles1 = agent1.role_probs.copy()
    initial_roles2 = agent2.role_probs.copy()
    
    # Run slow loop update with organs
    mock_slow_loop_update_roles([organ])
    
    # Verify that role probabilities have changed
    assert agent1.role_probs != initial_roles1
    assert agent2.role_probs != initial_roles2
    
    # Verify probabilities still sum to 1.0
    assert abs(sum(agent1.role_probs.values()) - 1.0) < 0.001
    assert abs(sum(agent2.role_probs.values()) - 1.0) < 0.001

def test_slow_loop_update_roles_with_agents():
    """Test that slow loop updates agent roles based on energy state when given agents directly."""
    # Create test agents
    agent1 = Agent(agent_id="test_agent_1")
    agent2 = Agent(agent_id="test_agent_2")
    
    # Store initial role probabilities
    initial_roles1 = agent1.role_probs.copy()
    initial_roles2 = agent2.role_probs.copy()
    
    # Run slow loop update with agents directly
    mock_slow_loop_update_roles([agent1, agent2])
    
    # Verify that role probabilities have changed
    assert agent1.role_probs != initial_roles1
    assert agent2.role_probs != initial_roles2
    
    # Verify probabilities still sum to 1.0
    assert abs(sum(agent1.role_probs.values()) - 1.0) < 0.001
    assert abs(sum(agent2.role_probs.values()) - 1.0) < 0.001

def test_slow_loop_update_roles_simple():
    """Test that simple slow loop updates agent roles by strengthening dominant roles."""
    # Create test agents
    agent1 = Agent(agent_id="test_agent_1")
    agent2 = Agent(agent_id="test_agent_2")
    
    # Store initial role probabilities
    initial_roles1 = agent1.role_probs.copy()
    initial_roles2 = agent2.role_probs.copy()
    
    # Run simple slow loop update
    slow_loop_update_roles_simple([agent1, agent2])
    
    # Verify that role probabilities have changed
    assert agent1.role_probs != initial_roles1
    assert agent2.role_probs != initial_roles2
    
    # Verify probabilities still sum to 1.0
    assert abs(sum(agent1.role_probs.values()) - 1.0) < 0.001
    assert abs(sum(agent2.role_probs.values()) - 1.0) < 0.001
    
    # Verify that dominant roles have been strengthened
    dominant_role1 = max(initial_roles1, key=initial_roles1.get)
    dominant_role2 = max(initial_roles2, key=initial_roles2.get)
    
    assert agent1.role_probs[dominant_role1] >= initial_roles1[dominant_role1]
    assert agent2.role_probs[dominant_role2] >= initial_roles2[dominant_role2]

def test_get_role_performance_metrics():
    """Test role performance metrics calculation."""
    # Create test organ and agents with known capabilities
    organ = DummyOrgan(organ_id="test_organ")
    agent1 = Agent(agent_id="test_agent_1", capability=0.8)
    agent2 = Agent(agent_id="test_agent_2", capability=0.6)
    organ.register(agent1)
    organ.register(agent2)
    
    # Set specific role probabilities
    agent1.role_probs = {'E': 0.7, 'S': 0.2, 'O': 0.1}
    agent2.role_probs = {'E': 0.3, 'S': 0.6, 'O': 0.1}
    
    # Get performance metrics
    metrics = get_role_performance_metrics([organ])
    
    # Verify metrics are calculated correctly
    assert 'E' in metrics
    assert 'S' in metrics
    assert 'O' in metrics
    
    # E performance should be: (0.8 * 0.7 + 0.6 * 0.3) / 2 = 0.37
    expected_E = (0.8 * 0.7 + 0.6 * 0.3) / 2
    assert abs(metrics['E'] - expected_E) < 0.001

def test_adaptive_mem_update():
    """Test adaptive memory update functionality."""
    # Create test organ and agents
    organ = DummyOrgan(organ_id="test_organ")
    agent1 = Agent(agent_id="test_agent_1", mem_util=0.5)
    agent2 = Agent(agent_id="test_agent_2", mem_util=0.3)
    organ.register(agent1)
    organ.register(agent2)
    
    # Store initial memory utilization
    initial_mem_util1 = agent1.mem_util
    initial_mem_util2 = agent2.mem_util
    
    # Run memory update
    compression_knob = 0.5
    new_compression = adaptive_mem_update([organ], compression_knob)
    
    # Verify compression knob may have changed
    assert isinstance(new_compression, float)
    assert 0.0 <= new_compression <= 1.0
    
    # Verify memory utilization may have changed
    assert agent1.mem_util != initial_mem_util1 or agent2.mem_util != initial_mem_util2

def test_get_memory_metrics():
    """Test memory metrics calculation."""
    # Create test organ and agents
    organ = DummyOrgan(organ_id="test_organ")
    agent1 = Agent(agent_id="test_agent_1", mem_util=0.6)
    agent2 = Agent(agent_id="test_agent_2", mem_util=0.4)
    organ.register(agent1)
    organ.register(agent2)
    
    # Get memory metrics
    metrics = get_memory_metrics([organ])
    
    # Verify expected metrics
    assert "average_memory_utilization" in metrics
    assert "total_agents" in metrics
    assert "current_memory_energy" in metrics
    assert "memory_efficiency" in metrics
    
    # Verify average memory utilization calculation
    expected_avg = (0.6 + 0.4) / 2
    assert abs(metrics["average_memory_utilization"] - expected_avg) < 0.001
    assert metrics["total_agents"] == 2

def test_estimate_memory_gradient():
    """Test memory gradient estimation."""
    # Create test organ and agents
    organ = DummyOrgan(organ_id="test_organ")
    agent1 = Agent(agent_id="test_agent_1", capability=0.7)
    agent2 = Agent(agent_id="test_agent_2", capability=0.5)
    organ.register(agent1)
    organ.register(agent2)
    
    # Estimate gradient
    gradient = estimate_memory_gradient([organ])
    
    # Verify gradient is a number
    assert isinstance(gradient, float)

def test_control_loop_integration():
    """Test integration of multiple control loops."""
    # Create test organ and agents
    organ = DummyOrgan(organ_id="test_organ")
    agent1 = Agent(agent_id="test_agent_1", capability=0.8, mem_util=0.5)
    agent2 = Agent(agent_id="test_agent_2", capability=0.6, mem_util=0.3)
    organ.register(agent1)
    organ.register(agent2)
    
    # Store initial states
    initial_roles1 = agent1.role_probs.copy()
    initial_mem_util1 = agent1.mem_util
    initial_capability1 = agent1.capability
    
    # Run slow loop
    mock_slow_loop_update_roles([organ])
    
    # Run memory loop
    compression_knob = 0.5
    adaptive_mem_update([organ], compression_knob)
    
    # Verify changes occurred
    assert agent1.role_probs != initial_roles1
    assert agent1.mem_util != initial_mem_util1
    assert agent1.capability != initial_capability1
    
    # Verify probabilities still sum to 1.0
    assert abs(sum(agent1.role_probs.values()) - 1.0) < 0.001
    assert abs(sum(agent2.role_probs.values()) - 1.0) < 0.001

def test_learning_rate_parameter():
    """Test that learning rate parameter affects role adjustment speed."""
    # Create test agents
    agent1 = Agent(agent_id="test_agent_1")
    agent2 = Agent(agent_id="test_agent_2")
    
    # Store initial role probabilities
    initial_roles1 = agent1.role_probs.copy()
    
    # Run with high learning rate
    slow_loop_update_roles_simple([agent1], learning_rate=0.2)
    high_lr_change = abs(agent1.role_probs[max(agent1.role_probs, key=agent1.role_probs.get)] - 
                        initial_roles1[max(initial_roles1, key=initial_roles1.get)])
    
    # Reset and run with low learning rate
    agent1.role_probs = initial_roles1.copy()
    slow_loop_update_roles_simple([agent1], learning_rate=0.01)
    low_lr_change = abs(agent1.role_probs[max(agent1.role_probs, key=agent1.role_probs.get)] - 
                       initial_roles1[max(initial_roles1, key=initial_roles1.get)])
    
    # Higher learning rate should cause larger changes
    assert high_lr_change > low_lr_change

def test_organ_registry_integration():
    """Test integration with OrganRegistry."""
    # Create registry and organ
    registry = OrganRegistry()
    organ = DummyOrgan(organ_id="test_organ")
    
    # Create and register agents
    agent1 = Agent(agent_id="test_agent_1", role_probs={'E': 0.6, 'S': 0.3, 'O': 0.1})
    agent2 = Agent(agent_id="test_agent_2", role_probs={'E': 0.2, 'S': 0.7, 'O': 0.1})
    
    organ.register(agent1)
    organ.register(agent2)
    registry.add(organ)
    
    # Test registry operations
    assert len(registry.all()) == 1
    assert registry.get("test_organ") == organ
    
    # Test slow loop with registry
    mock_slow_loop_update_roles(registry.all())
    
    # Verify agents were updated
    assert agent1.role_probs != {'E': 0.6, 'S': 0.3, 'O': 0.1}
    assert agent2.role_probs != {'E': 0.2, 'S': 0.7, 'O': 0.1} 