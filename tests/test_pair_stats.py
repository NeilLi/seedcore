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
Tests for pair statistics tracking functionality.
"""

import numpy as np
from seedcore.energy.pair_stats import PairStats, PairStatsTracker
from seedcore.agents.base import Agent

def test_pair_stats_initialization():
    """Test that PairStats initializes with correct default values."""
    stats = PairStats()
    
    assert stats.w == 1.0
    assert stats.success_count == 0
    assert stats.trial_count == 0

def test_pair_stats_update_weight_success():
    """Test weight update on successful task."""
    stats = PairStats()
    initial_weight = stats.w
    
    stats.update_weight(success=True, learning_rate=0.1)
    
    # Weight should increase (move toward 1.0)
    assert stats.w > initial_weight
    assert stats.success_count == 1
    assert stats.trial_count == 1

def test_pair_stats_update_weight_failure():
    """Test weight update on failed task."""
    stats = PairStats()
    initial_weight = stats.w
    
    stats.update_weight(success=False, learning_rate=0.1)
    
    # Weight should decrease (move toward 0.0)
    assert stats.w < initial_weight
    assert stats.success_count == 0
    assert stats.trial_count == 1

def test_pair_stats_tracker_initialization():
    """Test that PairStatsTracker initializes correctly."""
    tracker = PairStatsTracker()
    
    assert len(tracker.pair_stats) == 0

def test_pair_stats_tracker_get_pair():
    """Test getting pair statistics, creating if doesn't exist."""
    tracker = PairStatsTracker()
    
    # Get pair that doesn't exist yet
    pair_stats = tracker.get_pair("agent1", "agent2")
    
    assert isinstance(pair_stats, PairStats)
    assert len(tracker.pair_stats) == 1
    
    # Get the same pair again (should return existing)
    same_pair_stats = tracker.get_pair("agent1", "agent2")
    assert same_pair_stats is pair_stats
    assert len(tracker.pair_stats) == 1

def test_pair_stats_tracker_consistency():
    """Test that pair keys are consistent regardless of order."""
    tracker = PairStatsTracker()
    
    # Create pair in one order
    pair1 = tracker.get_pair("agent1", "agent2")
    
    # Create pair in reverse order
    pair2 = tracker.get_pair("agent2", "agent1")
    
    # Should be the same object
    assert pair1 is pair2
    assert len(tracker.pair_stats) == 1

def test_pair_stats_tracker_update():
    """Test updating pair statistics."""
    tracker = PairStatsTracker()
    
    # Update a pair
    tracker.update_on_task_complete("agent1", "agent2", success=True)
    
    # Check that the pair was created and updated
    pair_stats = tracker.get_pair("agent1", "agent2")
    assert pair_stats.success_count == 1
    assert pair_stats.trial_count == 1
    assert pair_stats.w > 1.0  # Should increase from initial 1.0

def test_pair_stats_tracker_reset():
    """Test resetting the tracker."""
    tracker = PairStatsTracker()
    
    # Add some pairs
    tracker.update_on_task_complete("agent1", "agent2", success=True)
    tracker.update_on_task_complete("agent3", "agent4", success=False)
    
    assert len(tracker.pair_stats) == 2
    
    # Reset
    tracker.reset()
    
    assert len(tracker.pair_stats) == 0

def test_pair_stats_tracker_get_all_stats():
    """Test getting all statistics as dictionary."""
    tracker = PairStatsTracker()
    
    # Add some pairs
    tracker.update_on_task_complete("agent1", "agent2", success=True)
    tracker.update_on_task_complete("agent1", "agent2", success=False)
    tracker.update_on_task_complete("agent3", "agent4", success=True)
    
    stats = tracker.get_all_stats()
    
    assert len(stats) == 2
    assert "agent1-agent2" in stats
    assert "agent3-agent4" in stats
    
    # Check structure of stats
    pair1_stats = stats["agent1-agent2"]
    assert "weight" in pair1_stats
    assert "success_count" in pair1_stats
    assert "trial_count" in pair1_stats
    assert "success_rate" in pair1_stats
    
    assert pair1_stats["trial_count"] == 2
    assert pair1_stats["success_count"] == 1
    assert pair1_stats["success_rate"] == 0.5

def test_agent_personality_vector():
    """Test that agents have personality vectors."""
    agent = Agent(agent_id="test_agent")
    
    assert hasattr(agent, 'h')
    assert isinstance(agent.h, np.ndarray)
    assert len(agent.h) == 8

def test_agent_custom_personality():
    """Test creating agent with custom personality vector."""
    custom_vector = np.array([1.0, 0.5, 0.3, 0.8, 0.2, 0.9, 0.1, 0.7])
    agent = Agent(agent_id="test_agent", h=custom_vector)
    
    assert np.array_equal(agent.h, custom_vector)

def test_cosine_similarity_calculation():
    """Test cosine similarity calculation between agent personalities."""
    # Create agents with known personality vectors
    agent1 = Agent(agent_id="agent1", h=np.array([1.0, 0.0, 0.0, 0.0]))
    agent2 = Agent(agent_id="agent2", h=np.array([1.0, 0.0, 0.0, 0.0]))
    agent3 = Agent(agent_id="agent3", h=np.array([0.0, 1.0, 0.0, 0.0]))
    
    # Calculate similarities
    sim_same = np.dot(agent1.h, agent2.h) / (np.linalg.norm(agent1.h) * np.linalg.norm(agent2.h))
    sim_different = np.dot(agent1.h, agent3.h) / (np.linalg.norm(agent1.h) * np.linalg.norm(agent3.h))
    
    # Same vectors should have similarity 1.0
    assert abs(sim_same - 1.0) < 0.001
    
    # Orthogonal vectors should have similarity 0.0
    assert abs(sim_different - 0.0) < 0.001 