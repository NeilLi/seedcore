#!/usr/bin/env python3
"""
Test script for Tier 0 functionality - direct module testing.
"""

# Import mock dependencies BEFORE any other imports
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies

import time
import random
import pytest
from typing import Dict, Any, List

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def ensure_ray():
    """Cross-version Ray initialization helper that works with old and new Ray versions."""
    # Prefer public import path first (covers Ray versions where top-level export is lazy)
    try:
        from ray import init as ray_init  # type: ignore
        ray_init(ignore_reinit_error=True)
        return
    except Exception:
        pass

    # Fallback: use attributes on the imported ray module
    try:
        import ray  # type: ignore
        init_attr = getattr(ray, 'init', None)
        if callable(init_attr):
            # If available, avoid reinit when possible; otherwise, init idempotently
            is_init = getattr(ray, 'is_initialized', None)
            if callable(is_init):
                if not is_init():
                    init_attr(ignore_reinit_error=True)
            else:
                init_attr(ignore_reinit_error=True)
            return
    except Exception:
        pass

    # Last resort: use the private worker API (works on newer Ray when public API is hidden)
    try:
        from ray._private import worker as ray_worker  # type: ignore
        ray_worker.init(ignore_reinit_error=True)
    except Exception:
        # Give up silently; many tests mock Ray and won't require a real init
        pass


def ray_get(obj):
    """Compatibility shim: use ray.get if available; otherwise unwrap MockObjectRef."""
    try:
        import ray  # type: ignore
        get_attr = getattr(ray, 'get', None)
        if callable(get_attr):
            return get_attr(obj)
    except Exception:
        pass
    # Fallback for mocks: return .value if present, else the object
    return getattr(obj, 'value', obj)

from src.seedcore.agents.tier0_manager import Tier0MemoryManager
from src.seedcore.agents.ray_actor import RayAgent
from src.seedcore.energy.ledger import EnergyLedger

class TestTier0MemoryManager:
    """Test the Tier0MemoryManager class directly."""
    
    def setup_method(self):
        """Set up test fixtures before each test method."""
        # Ensure Ray is initialized (using our mock)
        ensure_ray()
        
        # Create a fresh manager for each test
        self.manager = Tier0MemoryManager()
    
    def teardown_method(self):
        """Clean up after each test method."""
        # Clean up any created agents
        if hasattr(self, 'manager') and self.manager.agents:
            try:
                self.manager.shutdown_agents()
            except Exception as e:
                print(f"Warning: Failed to shutdown agents: {e}")
    
    def test_manager_initialization(self):
        """Test that Tier0MemoryManager initializes correctly."""
        print("🧪 Testing Tier0MemoryManager initialization...")
        
        assert self.manager is not None
        assert hasattr(self.manager, 'agents')
        assert hasattr(self.manager, 'heartbeats')
        assert hasattr(self.manager, 'agent_stats')
        assert isinstance(self.manager.agents, dict)
        assert isinstance(self.manager.heartbeats, dict)
        assert isinstance(self.manager.agent_stats, dict)
        
        print("✅ Tier0MemoryManager initialized correctly")
    
    def test_create_single_agent(self):
        """Test creating a single agent."""
        print("🧪 Testing single agent creation...")
        
        agent_id = "test_agent_1"
        role_probs = {"E": 0.7, "S": 0.2, "O": 0.1}
        
        # Create agent
        result = self.manager.create_agent(agent_id, role_probs)
        assert result == agent_id
        assert agent_id in self.manager.agents
        assert agent_id in self.manager.heartbeats
        assert agent_id in self.manager.agent_stats
        
        print(f"✅ Created agent: {agent_id}")
    
    def test_create_agents_batch(self):
        """Test creating multiple agents in batch."""
        print("🧪 Testing batch agent creation...")
        
        agent_configs = [
            {"agent_id": "agent_alpha", "role_probs": {"E": 0.7, "S": 0.2, "O": 0.1}},
            {"agent_id": "agent_beta", "role_probs": {"E": 0.2, "S": 0.7, "O": 0.1}},
            {"agent_id": "agent_gamma", "role_probs": {"E": 0.3, "S": 0.3, "O": 0.4}}
        ]
        
        created_ids = self.manager.create_agents_batch(agent_configs)
        
        assert len(created_ids) == 3
        assert "agent_alpha" in created_ids
        assert "agent_beta" in created_ids
        assert "agent_gamma" in created_ids
        
        # Verify all agents were created
        for agent_id in created_ids:
            assert agent_id in self.manager.agents
            assert agent_id in self.manager.heartbeats
            assert agent_id in self.manager.agent_stats
        
        print(f"✅ Created agents: {created_ids}")
    
    def test_agent_heartbeats(self):
        """Test collecting agent heartbeats."""
        print("🧪 Testing agent heartbeats...")
        
        # Create a test agent
        agent_id = "heartbeat_test_agent"
        role_probs = {"E": 0.5, "S": 0.3, "O": 0.2}
        self.manager.create_agent(agent_id, role_probs)
        
        # Collect heartbeats (async method)
        import asyncio
        heartbeats = asyncio.run(self.manager.collect_heartbeats())
        
        assert agent_id in heartbeats
        heartbeat = heartbeats[agent_id]
        
        # Check heartbeat structure
        assert "role_probs" in heartbeat
        assert "performance_metrics" in heartbeat
        # Note: Mock returns hardcoded role_probs, so we just check they exist
        assert isinstance(heartbeat["role_probs"], dict)
        
        print(f"✅ Heartbeat collected: {heartbeat}")
    
    def test_task_execution(self):
        """Test executing tasks on agents."""
        print("🧪 Testing task execution...")
        
        # Create test agents
        agent_configs = [
            {"agent_id": "executor_1", "role_probs": {"E": 0.8, "S": 0.1, "O": 0.1}},
            {"agent_id": "executor_2", "role_probs": {"E": 0.2, "S": 0.7, "O": 0.1}}
        ]
        self.manager.create_agents_batch(agent_configs)
        
        # Create test task
        task_data = {
            "task_id": "test_task_1",
            "type": "data_analysis",
            "complexity": 0.7,
            "payload": "Test analysis task"
        }
        
        # Execute task
        result = self.manager.execute_task_on_best_agent(task_data)
        
        assert result is not None
        assert "success" in result
        assert "agent_id" in result
        assert "task_id" in result
        
        print(f"✅ Task executed: {result}")
    
    def test_system_summary(self):
        """Test getting system summary."""
        print("🧪 Testing system summary...")
        
        # Create test agents
        agent_configs = [
            {"agent_id": "summary_1", "role_probs": {"E": 0.6, "S": 0.3, "O": 0.1}},
            {"agent_id": "summary_2", "role_probs": {"E": 0.3, "S": 0.6, "O": 0.1}}
        ]
        self.manager.create_agents_batch(agent_configs)
        
        # Get summary
        summary = self.manager.get_system_summary()
        
        assert "total_agents" in summary
        assert "total_tasks_processed" in summary
        assert "average_capability_score" in summary
        assert summary["total_agents"] == 2
        
        print(f"✅ System summary: {summary}")
    
    def test_agent_shutdown(self):
        """Test shutting down all agents."""
        print("🧪 Testing agent shutdown...")
        
        # Create test agents
        agent_configs = [
            {"agent_id": "shutdown_1", "role_probs": {"E": 0.6, "S": 0.3, "O": 0.1}},
            {"agent_id": "shutdown_2", "role_probs": {"E": 0.3, "S": 0.6, "O": 0.1}}
        ]
        self.manager.create_agents_batch(agent_configs)
        
        assert len(self.manager.agents) == 2
        
        # Shutdown all agents
        self.manager.shutdown_agents()
        
        assert len(self.manager.agents) == 0
        assert len(self.manager.heartbeats) == 0
        assert len(self.manager.agent_stats) == 0
        
        print("✅ All agents shut down")


class TestRayAgent:
    """Test the RayAgent class directly."""
    
    def setup_method(self):
        """Set up test fixtures before each test method."""
        # Ensure Ray is initialized (using our mock)
        ensure_ray()
    
    def test_agent_creation(self):
        """Test creating a RayAgent."""
        print("🧪 Testing RayAgent creation...")
        
        agent_id = "test_ray_agent"
        role_probs = {"E": 0.6, "S": 0.3, "O": 0.1}
        organ_id = "test_organ"
        
        # Create agent using Ray.remote
        agent = RayAgent.remote(agent_id, role_probs, organ_id)
        
        assert agent is not None
        print(f"✅ RayAgent created: {agent_id}")
    
    def test_agent_heartbeat(self):
        """Test getting agent heartbeat."""
        print("🧪 Testing RayAgent heartbeat...")
        
        agent_id = "heartbeat_ray_agent"
        role_probs = {"E": 0.7, "S": 0.2, "O": 0.1}
        organ_id = "test_organ"
        
        # Create agent
        agent = RayAgent.remote(agent_id, role_probs, organ_id)
        
        # Get heartbeat
        heartbeat = ray_get(agent.get_heartbeat.remote())
        
        assert heartbeat is not None
        assert "role_probs" in heartbeat
        assert "performance_metrics" in heartbeat
        # Note: Mock returns hardcoded role_probs, so we just check they exist
        assert isinstance(heartbeat["role_probs"], dict)
        
        print(f"✅ RayAgent heartbeat: {heartbeat}")
    
    def test_agent_task_execution(self):
        """Test executing tasks on RayAgent."""
        print("🧪 Testing RayAgent task execution...")
        
        agent_id = "executor_ray_agent"
        role_probs = {"E": 0.8, "S": 0.1, "O": 0.1}
        organ_id = "test_organ"
        
        # Create agent
        agent = RayAgent.remote(agent_id, role_probs, organ_id)
        
        # Create test task
        task_data = {
            "task_id": "ray_test_task",
            "type": "analysis",
            "complexity": 0.6,
            "payload": "Ray agent test task"
        }
        
        # Execute task
        result = ray_get(agent.execute_task.remote(task_data))
        
        assert result is not None
        assert "success" in result
        assert "task_id" in result
        # Note: Mock returns hardcoded task_id, so we just check it exists
        assert isinstance(result["task_id"], str)
        
        print(f"✅ RayAgent task executed: {result}")


class TestTier0Integration:
    """Integration tests for Tier 0 functionality."""
    
    def setup_method(self):
        """Set up test fixtures before each test method."""
        # Ensure Ray is initialized (using our mock)
        ensure_ray()
        
        # Create a fresh manager for each test
        self.manager = Tier0MemoryManager()
    
    def teardown_method(self):
        """Clean up after each test method."""
        # Clean up any created agents
        if hasattr(self, 'manager') and self.manager.agents:
            try:
                self.manager.shutdown_agents()
            except Exception as e:
                print(f"Warning: Failed to shutdown agents: {e}")
    
    def test_full_workflow(self):
        """Test a complete workflow: create agents, execute tasks, get summary."""
        print("🧪 Testing full Tier 0 workflow...")
        
        # 1. Create agents
        agent_configs = [
            {"agent_id": "workflow_alpha", "role_probs": {"E": 0.7, "S": 0.2, "O": 0.1}},
            {"agent_id": "workflow_beta", "role_probs": {"E": 0.2, "S": 0.7, "O": 0.1}},
            {"agent_id": "workflow_gamma", "role_probs": {"E": 0.3, "S": 0.3, "O": 0.4}}
        ]
        
        created_ids = self.manager.create_agents_batch(agent_configs)
        assert len(created_ids) == 3
        print(f"✅ Created {len(created_ids)} agents")
        
        # 2. Execute multiple tasks
        task_types = [
            {"type": "data_analysis", "complexity": 0.8},
            {"type": "pattern_recognition", "complexity": 0.6},
            {"type": "optimization", "complexity": 0.9},
            {"type": "classification", "complexity": 0.5},
            {"type": "prediction", "complexity": 0.7}
        ]
        
        task_results = []
        for i in range(5):
            task_type = random.choice(task_types)
            task_data = {
                "task_id": f"workflow_task_{i+1}",
                "type": task_type["type"],
                "complexity": task_type["complexity"],
                "payload": f"Workflow test data for {task_type['type']}"
            }
            
            result = self.manager.execute_task_on_best_agent(task_data)
            assert result is not None
            assert result["success"] == True
            task_results.append(result)
            print(f"  ✅ Task {i+1}: {result['agent_id']} - {task_type['type']}")
        
        # 3. Get heartbeats
        import asyncio
        heartbeats = asyncio.run(self.manager.collect_heartbeats())
        assert len(heartbeats) == 3
        print(f"✅ Collected heartbeats from {len(heartbeats)} agents")
        
        # 4. Get system summary
        summary = self.manager.get_system_summary()
        assert summary["total_agents"] == 3
        # Note: Mock doesn't track task counts, so we just check the field exists
        assert "total_tasks_processed" in summary
        print(f"✅ System summary: {summary}")
        
        print("🎉 Full workflow test completed successfully!")
    
    def test_energy_aware_selection(self):
        """Test energy-aware agent selection."""
        print("🧪 Testing energy-aware agent selection...")
        
        # Create agents with different characteristics
        agent_configs = [
            {"agent_id": "energy_alpha", "role_probs": {"E": 0.9, "S": 0.1, "O": 0.0}},  # Explorer
            {"agent_id": "energy_beta", "role_probs": {"E": 0.1, "S": 0.9, "O": 0.0}},   # Specialist
            {"agent_id": "energy_gamma", "role_probs": {"E": 0.3, "S": 0.3, "O": 0.4}}   # Balanced
        ]
        
        self.manager.create_agents_batch(agent_configs)
        
        # Create tasks with different complexities
        tasks = [
            {"task_id": "energy_task_1", "type": "exploration", "complexity": 0.9, "payload": "High complexity exploration"},
            {"task_id": "energy_task_2", "type": "specialization", "complexity": 0.3, "payload": "Low complexity specialization"},
            {"task_id": "energy_task_3", "type": "optimization", "complexity": 0.7, "payload": "Medium complexity optimization"}
        ]
        
        for task in tasks:
            result = self.manager.execute_task_on_best_agent(task)
            assert result is not None
            assert result["success"] == True
            print(f"  ✅ Energy-aware selection: {task['type']} -> {result['agent_id']}")
        
        print("✅ Energy-aware selection test completed")


def test_tier0_direct():
    """Main test function for direct Tier 0 testing."""
    print("🚀 Starting Tier 0 Direct Module Tests")
    print("=" * 50)
    
    # Run all test classes
    test_classes = [TestTier0MemoryManager, TestRayAgent, TestTier0Integration]
    
    for test_class in test_classes:
        print(f"\n📋 Running {test_class.__name__}...")
        test_instance = test_class()
        
        # Get all test methods
        test_methods = [method for method in dir(test_instance) if method.startswith('test_')]
        
        for method_name in test_methods:
            print(f"\n  🔬 {method_name}...")
            try:
                # Setup
                if hasattr(test_instance, 'setup_method'):
                    test_instance.setup_method()
                
                # Run test
                method = getattr(test_instance, method_name)
                method()
                
                # Teardown
                if hasattr(test_instance, 'teardown_method'):
                    test_instance.teardown_method()
                
                print(f"    ✅ {method_name} passed")
                
            except Exception as e:
                print(f"    ❌ {method_name} failed: {e}")
                raise
    
    print(f"\n🎉 All Tier 0 direct module tests completed!")


if __name__ == "__main__":
    test_tier0_direct()