#!/usr/bin/env python3
import os
import sys
from typing import Any, Dict

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from seedcore.agents.base import BaseAgent
from seedcore.agents.roles import Specialization, RoleProfile, RoleRegistry
from seedcore.agents.behaviors import (
    AgentBehavior,
    create_behavior_registry,
)


@pytest.mark.asyncio
async def test_advertise_capabilities_reflects_role_profile():
    """
    Test that BaseAgent.advertise_capabilities() correctly reflects the role profile.
    
    This test works with both static and dynamic specializations.
    """
    # Create a custom role registry with a profile that has specific routing tags
    custom_registry = RoleRegistry()
    profile = RoleProfile(
        name=Specialization.GENERALIST,
        default_skills={"test_skill": 0.5},
        allowed_tools={"test.tool"},
        routing_tags={"guest_relations", "vip"},
        safety_policies={},
    )
    custom_registry.register(profile)
    
    # Create agent with the custom registry
    agent = BaseAgent(
        agent_id="agent-test",
        specialization=Specialization.GENERALIST,
        role_registry=custom_registry,
    )

    advertisement = agent.advertise_capabilities()

    assert advertisement["agent_id"] == "agent-test"
    assert advertisement["specialization"] == Specialization.GENERALIST.value
    assert set(advertisement["routing_tags"]) == {"guest_relations", "vip"}
    assert 0.0 <= advertisement["capability"] <= 1.0
    assert 0.0 <= advertisement["mem_util"] <= 1.0


@pytest.mark.asyncio
async def test_advertise_capabilities_with_dynamic_specialization():
    """
    Test that BaseAgent works correctly with dynamic specializations.
    """
    from seedcore.agents.roles.specialization import (
        SpecializationManager,
        DynamicSpecialization,
    )
    
    # Reset singleton for clean test
    SpecializationManager._instance = None
    
    # Register a dynamic specialization
    manager = SpecializationManager.get_instance()
    dynamic_spec = manager.register_dynamic(
        value="test_dynamic_spec",
        name="Test Dynamic Spec",
        metadata={"test": True},
    )
    
    # Create a role profile for the dynamic specialization
    custom_registry = RoleRegistry()
    profile = RoleProfile(
        name=dynamic_spec,
        default_skills={"dynamic_skill": 0.7},
        allowed_tools={"dynamic.tool"},
        routing_tags={"dynamic_tag"},
        safety_policies={},
    )
    custom_registry.register(profile)
    
    # Create agent with dynamic specialization (can pass as string)
    agent = BaseAgent(
        agent_id="agent-dynamic",
        specialization="test_dynamic_spec",  # String form - will be resolved
        role_registry=custom_registry,
    )

    advertisement = agent.advertise_capabilities()

    assert advertisement["agent_id"] == "agent-dynamic"
    assert advertisement["specialization"] == "test_dynamic_spec"
    assert "dynamic_tag" in advertisement["routing_tags"]
    assert 0.0 <= advertisement["capability"] <= 1.0
    assert 0.0 <= advertisement["mem_util"] <= 1.0
    
    # Verify the agent's specialization is a DynamicSpecialization instance
    assert isinstance(agent.specialization, DynamicSpecialization)
    assert agent.specialization.value == "test_dynamic_spec"


@pytest.mark.asyncio
async def test_extract_salience_features_merges_system_and_error_context(monkeypatch: pytest.MonkeyPatch):
    agent = BaseAgent(agent_id="agent-salience")

    async def fake_heartbeat() -> Dict[str, Any]:
        return {"performance_metrics": {"capability_score_c": 0.7, "mem_util": 0.3}}

    monkeypatch.setattr(agent, "get_heartbeat", fake_heartbeat)
    monkeypatch.setattr(agent, "_get_agent_load_estimate", lambda: 0.9)
    monkeypatch.setattr(agent, "_get_agent_memory_usage", lambda: 0.4)
    monkeypatch.setattr(agent, "_get_agent_cpu_usage", lambda: 0.45)
    monkeypatch.setattr(agent, "_get_agent_response_time", lambda: 0.12)
    monkeypatch.setattr(agent, "_get_agent_error_rate", lambda: 0.02)

    features = await agent._extract_salience_features(
        task_info={"risk": 0.8, "complexity": 0.6, "user_impact": 0.9},
        error_context={"reason": "Network timeout", "code": 503},
    )

    assert pytest.approx(features["agent_capability"]) == 0.7
    assert pytest.approx(features["agent_memory_util"]) == 0.3
    assert features["error_type"] == "timeout"
    assert pytest.approx(features["agent_load"]) == 0.9
    assert pytest.approx(features["agent_cpu_usage"]) == 0.45
    assert features["error_code"] == 503


@pytest.mark.asyncio
async def test_calculate_ml_salience_score_prefers_ml_response(monkeypatch: pytest.MonkeyPatch):
    agent = BaseAgent(agent_id="agent-ml")

    async def fake_extract(task_info: Dict[str, Any], error_context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "task_risk": 0.9,
            "failure_severity": 1.0,
            "user_impact": 0.8,
            "business_criticality": 0.7,
            "agent_capability": 0.5,
            "agent_memory_util": 0.3,
            "agent_load": 0.2,
            "agent_cpu_usage": 0.1,
            "agent_response_time": 0.05,
            "agent_error_rate": 0.01,
            "error_code": 500,
            "error_type": "timeout",
        }

    class FakeMlClient:
        async def compute_salience_score(self, *, text: str, context: Dict[str, Any]) -> Dict[str, Any]:
            assert "task_risk" in context
            return {"score": 0.85}

    # _get_ml_client is synchronous, not async
    def fake_get_ml_client():
        return FakeMlClient()

    monkeypatch.setattr(agent, "_extract_salience_features", fake_extract)
    monkeypatch.setattr(agent, "_get_ml_client", fake_get_ml_client)

    salience = await agent._calculate_ml_salience_score(
        task_info={"task": "abc", "risk": 0.9},
        error_context={"reason": "planner timeout"},
    )

    assert pytest.approx(salience, rel=1e-5) == 0.85


@pytest.mark.asyncio
async def test_base_agent_with_behaviors():
    """
    Test that BaseAgent initializes behaviors correctly from RoleProfile defaults.
    """
    # Create a role profile with default behaviors
    custom_registry = RoleRegistry()
    profile = RoleProfile(
        name=Specialization.GENERALIST,
        default_skills={"test_skill": 0.5},
        allowed_tools={"test.tool"},
        routing_tags={"test"},
        safety_policies={},
        default_behaviors=["chat_history", "task_filter"],
        behavior_config={
            "chat_history": {"limit": 30},
            "task_filter": {"allowed_types": ["test.task"]},
        },
    )
    custom_registry.register(profile)
    
    # Create agent with behaviors from RoleProfile
    agent = BaseAgent(
        agent_id="agent-behaviors",
        specialization=Specialization.GENERALIST,
        role_registry=custom_registry,
    )
    
    # Behaviors should be initialized on first execute_task call
    # But we can check that they're configured
    assert hasattr(agent, "_behaviors")
    assert hasattr(agent, "_behaviors_to_init")
    assert "chat_history" in agent._behaviors_to_init["names"]
    assert "task_filter" in agent._behaviors_to_init["names"]
    assert agent._behaviors_to_init["configs"]["chat_history"]["limit"] == 30


@pytest.mark.asyncio
async def test_base_agent_behaviors_override():
    """
    Test that explicit behaviors override RoleProfile defaults.
    """
    # Create a role profile with default behaviors
    custom_registry = RoleRegistry()
    profile = RoleProfile(
        name=Specialization.GENERALIST,
        default_skills={},
        allowed_tools=set(),
        routing_tags=set(),
        safety_policies={},
        default_behaviors=["chat_history"],  # Default behavior
        behavior_config={"chat_history": {"limit": 50}},  # Default config
    )
    custom_registry.register(profile)
    
    # Create agent with explicit behaviors that override defaults
    agent = BaseAgent(
        agent_id="agent-override",
        specialization=Specialization.GENERALIST,
        role_registry=custom_registry,
        behaviors=["task_filter"],  # Override: use task_filter instead of chat_history
        behavior_config={"task_filter": {"allowed_types": ["custom.task"]}},  # Override config
    )
    
    # Explicit behaviors should override RoleProfile defaults
    assert "task_filter" in agent._behaviors_to_init["names"]
    assert "chat_history" not in agent._behaviors_to_init["names"]  # Overridden
    assert agent._behaviors_to_init["configs"]["task_filter"]["allowed_types"] == ["custom.task"]


@pytest.mark.asyncio
async def test_base_agent_behavior_initialization():
    """
    Test that behaviors are initialized lazily on first execute_task call.
    """
    agent = BaseAgent(
        agent_id="agent-lazy-init",
        behaviors=["chat_history"],
        behavior_config={"chat_history": {"limit": 25}},
    )
    
    # Behaviors should not be initialized yet
    assert not agent._behaviors_initialized
    assert len(agent._behaviors) == 0
    
    # Create a simple task to trigger behavior initialization
    from seedcore.models import TaskPayload
    
    task = TaskPayload(
        task_id="test-task-1",
        type="test",
        description="Test task",
        params={},
    )
    
    # Execute task - this should initialize behaviors
    await agent.execute_task(task)
    
    # Behaviors should now be initialized
    assert agent._behaviors_initialized
    assert len(agent._behaviors) > 0
    # Check that ChatHistoryBehavior was created
    behavior_names = [b.__class__.__name__ for b in agent._behaviors]
    assert "ChatHistoryBehavior" in behavior_names


@pytest.mark.asyncio
async def test_base_agent_behavior_hooks():
    """
    Test that behavior hooks (execute_task_pre, execute_task_post) are called.
    """
    # Create a custom behavior for testing
    class TestBehavior(AgentBehavior):
        def __init__(self, agent, config=None):
            super().__init__(agent, config)
            self.pre_called = False
            self.post_called = False
        
        async def initialize(self):
            self._initialized = True
        
        async def execute_task_pre(self, task, task_dict):
            self.pre_called = True
            # Modify task_dict to test hook works
            task_dict["modified_by_behavior"] = True
            return task_dict
        
        async def execute_task_post(self, task, task_dict, result):
            self.post_called = True
            # Modify result to test hook works
            result["modified_by_behavior"] = True
            return result
    
    # Register test behavior
    registry = create_behavior_registry()
    registry.register("test_behavior", TestBehavior)
    
    # Create agent with test behavior
    agent = BaseAgent(
        agent_id="agent-hooks",
        behaviors=["test_behavior"],
        behavior_registry=registry,
    )
    
    # Create a simple task
    from seedcore.models import TaskPayload
    
    task = TaskPayload(
        task_id="test-task-2",
        type="test",
        description="Test task",
        params={},
    )
    
    # Execute task
    result = await agent.execute_task(task)
    
    # Find the test behavior
    test_behavior = None
    for behavior in agent._behaviors:
        if isinstance(behavior, TestBehavior):
            test_behavior = behavior
            break
    
    assert test_behavior is not None
    assert test_behavior.pre_called, "execute_task_pre hook should have been called"
    assert test_behavior.post_called, "execute_task_post hook should have been called"
    assert result.get("modified_by_behavior") is True


@pytest.mark.asyncio
async def test_base_agent_shutdown_behaviors():
    """
    Test that behaviors are properly shut down when agent shuts down.
    """
    # Create a custom behavior that tracks shutdown
    class ShutdownTrackingBehavior(AgentBehavior):
        def __init__(self, agent, config=None):
            super().__init__(agent, config)
            self.shutdown_called = False
        
        async def initialize(self):
            self._initialized = True
        
        async def shutdown(self):
            self.shutdown_called = True
    
    # Register test behavior
    registry = create_behavior_registry()
    registry.register("shutdown_tracker", ShutdownTrackingBehavior)
    
    # Create agent with test behavior
    agent = BaseAgent(
        agent_id="agent-shutdown",
        behaviors=["shutdown_tracker"],
        behavior_registry=registry,
    )
    
    # Initialize behaviors by executing a task
    from seedcore.models import TaskPayload
    task = TaskPayload(
        task_id="test-task-3",
        type="test",
        description="Test task",
        params={},
    )
    await agent.execute_task(task)
    
    # Find the shutdown tracking behavior
    shutdown_behavior = None
    for behavior in agent._behaviors:
        if isinstance(behavior, ShutdownTrackingBehavior):
            shutdown_behavior = behavior
            break
    
    assert shutdown_behavior is not None
    assert not shutdown_behavior.shutdown_called
    
    # Shutdown agent
    await agent.shutdown()
    
    # Behavior should have been shut down
    assert shutdown_behavior.shutdown_called
    assert len(agent._behaviors) == 0

