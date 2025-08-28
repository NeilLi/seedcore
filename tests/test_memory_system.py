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
Tests for the comprehensive memory system implementation.
"""

import pytest
import numpy as np
from seedcore.memory.system import MemoryTier, SharedMemorySystem
from seedcore.memory.adaptive_loop import (
    calculate_dynamic_mem_util, 
    calculate_cost_vq, 
    get_memory_metrics
)
from seedcore.agents.base import Agent
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

def test_memory_tier_initialization():
    """Test that MemoryTier initializes correctly."""
    tier = MemoryTier("test_tier")
    
    assert tier.name == "test_tier"
    assert len(tier.datastore) == 0
    assert tier.bytes_used == 0
    assert tier.hit_count == 0
    assert tier.max_capacity == 1000

def test_memory_tier_add_data():
    """Test adding data to a memory tier."""
    tier = MemoryTier("test_tier", max_capacity=50)
    
    # Add data successfully
    success = tier.add_data("data1", "agent1", 10)
    assert success is True
    assert tier.bytes_used == 10
    assert tier.datastore["data1"] == "agent1"
    
    # Try to add data that exceeds capacity
    success = tier.add_data("data2", "agent2", 50)
    assert success is False
    assert tier.bytes_used == 10  # Should not change

def test_memory_tier_get_data_author():
    """Test retrieving data author from memory tier."""
    tier = MemoryTier("test_tier")
    tier.add_data("data1", "agent1", 10)
    
    author = tier.get_data_author("data1")
    assert author == "agent1"
    
    # Test non-existent data
    author = tier.get_data_author("nonexistent")
    assert author is None

def test_shared_memory_system_initialization():
    """Test that SharedMemorySystem initializes correctly."""
    system = SharedMemorySystem()
    
    assert system.Mw.name == "Mw"
    assert system.Mlt.name == "Mlt"
    assert system.Mw.max_capacity == 100
    assert system.Mlt.max_capacity == 1000

def test_shared_memory_system_write():
    """Test writing data to the shared memory system."""
    system = SharedMemorySystem()
    agent = Agent(agent_id="test_agent")
    
    # Write to Mw
    success = system.write(agent, "data1", "Mw", 10)
    assert success is True
    assert agent.memory_writes == 1
    assert system.Mw.bytes_used == 10
    
    # Write to Mlt
    success = system.write(agent, "data2", "Mlt", 20)
    assert success is True
    assert agent.memory_writes == 2
    assert system.Mlt.bytes_used == 20

def test_shared_memory_system_read():
    """Test reading data from the shared memory system."""
    system = SharedMemorySystem()
    writer_agent = Agent(agent_id="writer")
    reader_agent = Agent(agent_id="reader")
    
    # Write data first
    system.write(writer_agent, "data1", "Mw", 10)
    
    # Read the data
    author_id = system.read(reader_agent, "data1")
    assert author_id == "writer"
    assert system.Mw.hit_count == 1
    
    # Try to read non-existent data
    author_id = system.read(reader_agent, "nonexistent")
    assert author_id is None

def test_shared_memory_system_log_salient_event():
    """Test logging salient events."""
    system = SharedMemorySystem()
    agent = Agent(agent_id="test_agent")
    
    initial_count = agent.salient_events_logged
    system.log_salient_event(agent)
    assert agent.salient_events_logged == initial_count + 1

def test_calculate_dynamic_mem_util():
    """Test dynamic memory utility calculation."""
    agent = Agent(agent_id="test_agent")
    agent.memory_writes = 5
    agent.memory_hits_on_writes = 3
    agent.salient_events_logged = 2
    
    mem_util = calculate_dynamic_mem_util(agent)
    
    # Expected: (0.6 * 3 + 0.4 * 2) / 5 = (1.8 + 0.8) / 5 = 2.6 / 5 = 0.52
    expected = (0.6 * 3 + 0.4 * 2) / 5
    assert abs(mem_util - expected) < 0.001

def test_calculate_cost_vq():
    """Test CostVQ calculation."""
    system = SharedMemorySystem()
    agent = Agent(agent_id="test_agent")
    
    # Add some data to create a realistic scenario
    system.write(agent, "data1", "Mw", 10)
    system.write(agent, "data2", "Mlt", 20)
    system.read(agent, "data1")  # Create a hit
    
    cost_data = calculate_cost_vq(system, 0.5)
    
    assert 'cost_vq' in cost_data
    assert 'bytes_used' in cost_data
    assert 'recon_loss' in cost_data
    assert 'staleness' in cost_data
    assert cost_data['bytes_used'] == 30
    assert cost_data['recon_loss'] == 0.5  # 1.0 - 0.5

def test_get_memory_metrics():
    """Test memory metrics calculation across agents."""
    organ = DummyOrgan(organ_id="test_organ")
    agent1 = Agent(agent_id="agent1")
    agent2 = Agent(agent_id="agent2")
    
    # Set up some memory activity
    agent1.memory_writes = 3
    agent1.memory_hits_on_writes = 2
    agent1.salient_events_logged = 1
    
    agent2.memory_writes = 2
    agent2.memory_hits_on_writes = 1
    agent2.salient_events_logged = 0
    
    organ.register(agent1)
    organ.register(agent2)
    
    metrics = get_memory_metrics([organ])
    
    assert metrics['agent_count'] == 2
    assert metrics['total_memory_writes'] == 5
    assert metrics['total_memory_hits'] == 3
    assert metrics['total_salient_events'] == 1
    assert 'average_mem_util' in metrics
    assert 'individual_mem_utils' in metrics 