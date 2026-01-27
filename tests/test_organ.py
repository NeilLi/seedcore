#!/usr/bin/env python3
"""
Unit tests for Organ class (src/seedcore/organs/organ.py).

Tests Organ's core functionality:
- Agent creation with behaviors
- Agent registry management
- Role registry updates
- Health checks
- Agent lifecycle (create, remove, respawn)
"""

import os
import sys
from typing import Any, Dict
from unittest.mock import Mock, AsyncMock, MagicMock, patch

import pytest

# CRITICAL: Patch ray in sys.modules BEFORE any imports to prevent @ray.remote from wrapping classes
def _mock_ray_remote(*args, **kwargs):
    """Mock ray.remote decorator - returns class unchanged for direct instantiation."""
    if args and callable(args[0]):
        # Called as @ray.remote decorator
        cls = args[0]
        # Add .remote() and .options() methods for compatibility
        def remote_method(*r_args, **r_kwargs):
            return cls(*r_args, **r_kwargs)
        cls.remote = staticmethod(remote_method)
        def options_method(**opts):
            return cls
        cls.options = staticmethod(options_method)
        return cls
    else:
        # Called as @ray.remote(...) with kwargs or no args
        def decorator(cls):
            def remote_method(*r_args, **r_kwargs):
                return cls(*r_args, **r_kwargs)
            cls.remote = staticmethod(remote_method)
            def options_method(**opts):
                return cls
            cls.options = staticmethod(options_method)
            return cls
        return decorator

# Create mock ray module
import types
_mock_ray_module = types.ModuleType('ray')
# Make it behave like a package
_mock_ray_module.__path__ = []
_mock_ray_module.is_initialized = Mock(return_value=True)
_mock_ray_module.remote = _mock_ray_remote
_mock_ray_module.actor = Mock()
_mock_ray_module.actor.ActorHandle = Mock
_mock_ray_module.get_actor = Mock(side_effect=ValueError("Actor not found"))
_mock_ray_module.kill = Mock()

# Stub ray.dag.* modules to prevent import errors during shutdown
ray_dag = types.ModuleType('ray.dag')
ray_dag_compiled_dag_node = types.ModuleType('ray.dag.compiled_dag_node')
sys.modules['ray.dag'] = ray_dag
sys.modules['ray.dag.compiled_dag_node'] = ray_dag_compiled_dag_node

# Patch ray in sys.modules BEFORE importing anything that uses ray
sys.modules['ray'] = _mock_ray_module

# Now import after patching sys.modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from seedcore.agents.roles import Specialization, RoleProfile, RoleRegistry, DEFAULT_ROLE_REGISTRY
from seedcore.organs.organ import Organ, AgentIDFactory


@pytest.fixture(autouse=True)
def mock_ray():
    """Auto-use fixture to ensure ray is mocked for all tests."""
    # Ensure ray stays mocked
    sys.modules['ray'] = _mock_ray_module
    with patch("seedcore.organs.organ.ray", _mock_ray_module):
        yield _mock_ray_module


@pytest.fixture
def mock_role_registry():
    """Create a mock role registry."""
    registry = RoleRegistry()
    profile = RoleProfile(
        name=Specialization.GENERALIST,
        default_skills={"test": 0.5},
        allowed_tools={"test.tool"},
        routing_tags={"test"},
        default_behaviors=["chat_history"],
        behavior_config={"chat_history": {"limit": 50}},
    )
    registry.register(profile)
    return registry


@pytest.fixture
def organ_config():
    """Basic organ configuration."""
    return {
        "holon_fabric_config": {"pg": {"dsn": "postgresql://test"}, "neo4j": {"uri": "bolt://test"}},
        "cognitive_client_cfg": {"base_url": "http://test"},
        "ml_client_cfg": {"base_url": "http://test"},
    }


@pytest.mark.asyncio
async def test_organ_initialization(mock_ray, mock_role_registry, organ_config):
    """Test that Organ initializes correctly."""
    # Use Organ.remote() to match Ray actor pattern (even though mocked)
    organ = Organ.remote(
        organ_id="test_organ",
        role_registry=mock_role_registry,
        **organ_config,
    )
    
    assert organ.organ_id == "test_organ"
    assert organ.role_registry == mock_role_registry
    assert len(organ.agents) == 0
    assert len(organ.agent_info) == 0


@pytest.mark.asyncio
async def test_organ_create_agent_with_behaviors(mock_ray, mock_role_registry, organ_config):
    """Test creating an agent with behaviors."""
    organ = Organ.remote(
        organ_id="test_organ",
        role_registry=mock_role_registry,
        **organ_config,
    )
    
    # Mock the agent class and Ray remote
    mock_agent_class = Mock()
    mock_agent_instance = Mock()
    mock_agent_class.options.return_value.remote = Mock(return_value=mock_agent_instance)
    
    with patch("seedcore.organs.organ._load_agent_class", return_value=Mock):
        with patch("seedcore.organs.organ._ensure_ray_actor_class", return_value=mock_agent_class):
            await organ.create_agent(
                agent_id="test_agent_1",
                specialization=Specialization.GENERALIST,
                organ_id="test_organ",
                agent_class_name="BaseAgent",
                behaviors=["chat_history", "task_filter"],
                behavior_config={
                    "chat_history": {"limit": 30},
                    "task_filter": {"allowed_types": ["test.task"]},
                },
            )
    
    assert "test_agent_1" in organ.agents
    assert "test_agent_1" in organ.agent_info
    agent_info = organ.agent_info["test_agent_1"]
    assert agent_info["specialization"] == "generalist"
    assert agent_info["class"] == "BaseAgent"


@pytest.mark.asyncio
async def test_organ_create_agent_inherits_role_profile_behaviors(mock_ray, mock_role_registry, organ_config):
    """Test that agent creation inherits behaviors from RoleProfile."""
    # Create a role registry with default behaviors
    registry = RoleRegistry()
    profile = RoleProfile(
        name=Specialization.USER_LIAISON,
        default_skills={},
        allowed_tools=set(),
        routing_tags=set(),
        default_behaviors=["chat_history", "tool_auto_injection"],
        behavior_config={
            "chat_history": {"limit": 50},
            "tool_auto_injection": {"auto_add_general_query": True},
        },
    )
    registry.register(profile)
    
    organ = Organ.remote(
        organ_id="test_organ",
        role_registry=registry,
        **organ_config,
    )
    
    mock_agent_class = Mock()
    mock_agent_instance = Mock()
    mock_agent_class.options.return_value.remote = Mock(return_value=mock_agent_instance)
    
    with patch("seedcore.organs.organ._load_agent_class", return_value=Mock):
        with patch("seedcore.organs.organ._ensure_ray_actor_class", return_value=mock_agent_class):
            # Create agent without explicit behaviors - should inherit from RoleProfile
            await organ.create_agent(
                agent_id="test_agent_2",
                specialization=Specialization.USER_LIAISON,
                organ_id="test_organ",
                agent_class_name="BaseAgent",
            )
    
    # Verify agent was created (behaviors will be handled by BaseAgent.__init__)
    assert "test_agent_2" in organ.agents


@pytest.mark.asyncio
async def test_organ_get_agent_handle(mock_ray, mock_role_registry, organ_config):
    """Test getting agent handle."""
    organ = Organ.remote(
        organ_id="test_organ",
        role_registry=mock_role_registry,
        **organ_config,
    )
    
    # Add a mock agent handle
    mock_handle = Mock()
    organ.agents["test_agent_3"] = mock_handle
    
    handle = await organ.get_agent_handle("test_agent_3")
    assert handle == mock_handle
    
    # Test non-existent agent
    handle = await organ.get_agent_handle("non_existent")
    assert handle is None


@pytest.mark.asyncio
async def test_organ_list_agents(mock_ray, mock_role_registry, organ_config):
    """Test listing agents."""
    organ = Organ.remote(
        organ_id="test_organ",
        role_registry=mock_role_registry,
        **organ_config,
    )
    
    # Add mock agents
    organ.agents["agent_1"] = Mock()
    organ.agents["agent_2"] = Mock()
    
    agents = await organ.list_agents()
    assert set(agents) == {"agent_1", "agent_2"}


@pytest.mark.asyncio
async def test_organ_get_agent_info(mock_ray, mock_role_registry, organ_config):
    """Test getting agent info."""
    organ = Organ.remote(
        organ_id="test_organ",
        role_registry=mock_role_registry,
        **organ_config,
    )
    
    # Add agent info
    organ.agent_info["test_agent_4"] = {
        "agent_id": "test_agent_4",
        "specialization": "generalist",
        "class": "BaseAgent",
        "status": "ready",
    }
    
    info = await organ.get_agent_info("test_agent_4")
    assert info["agent_id"] == "test_agent_4"
    assert info["specialization"] == "generalist"
    
    # Test non-existent agent - returns error dict
    info = await organ.get_agent_info("non_existent")
    assert info == {"error": "not_found"}


@pytest.mark.asyncio
async def test_organ_remove_agent(mock_ray, mock_role_registry, organ_config):
    """Test removing an agent."""
    organ = Organ.remote(
        organ_id="test_organ",
        role_registry=mock_role_registry,
        **organ_config,
    )
    
    # Add a mock agent
    mock_handle = Mock()
    organ.agents["test_agent_5"] = mock_handle
    organ.agent_info["test_agent_5"] = {"agent_id": "test_agent_5"}
    
    result = await organ.remove_agent("test_agent_5")
    
    assert result is True
    assert "test_agent_5" not in organ.agents
    assert "test_agent_5" not in organ.agent_info
    mock_ray.kill.assert_called_once_with(mock_handle, no_restart=True)


@pytest.mark.asyncio
async def test_organ_update_role_registry(mock_ray, mock_role_registry, organ_config):
    """Test updating role registry and propagating to agents."""
    organ = Organ.remote(
        organ_id="test_organ",
        role_registry=mock_role_registry,
        **organ_config,
    )
    
    # Create awaitable mock coroutines for remote refs
    async def mock_coro():
        return None
    
    mock_handle_1 = Mock()
    mock_handle_1.update_role_profile = Mock()
    # Make remote() return a coroutine that can be awaited (call mock_coro each time)
    mock_handle_1.update_role_profile.remote = Mock(side_effect=lambda *args, **kwargs: mock_coro())
    organ.agents["agent_generalist_1"] = mock_handle_1
    organ.agent_info["agent_generalist_1"] = {
        "specialization": "generalist",
    }
    
    mock_handle_2 = Mock()
    mock_handle_2.update_role_profile = Mock()
    mock_handle_2.update_role_profile.remote = Mock(side_effect=lambda *args, **kwargs: mock_coro())
    organ.agents["agent_other"] = mock_handle_2
    organ.agent_info["agent_other"] = {
        "specialization": "other",
    }
    
    # Update role profile
    new_profile = RoleProfile(
        name=Specialization.GENERALIST,
        default_skills={"updated": 0.8},
        allowed_tools={"updated.tool"},
        routing_tags={"updated"},
        default_behaviors=["updated_behavior"],
        behavior_config={"updated_behavior": {"config": "value"}},
    )
    
    await organ.update_role_registry(new_profile)
    
    # Verify only matching agent received update
    mock_handle_1.update_role_profile.remote.assert_called_once_with(new_profile)
    mock_handle_2.update_role_profile.remote.assert_not_called()


@pytest.mark.asyncio
async def test_organ_health_check(mock_ray, mock_role_registry, organ_config):
    """Test health check."""
    organ = Organ.remote(
        organ_id="test_organ",
        role_registry=mock_role_registry,
        **organ_config,
    )
    
    # Mock the dependencies that health_check requires
    mock_tool_handler = Mock()
    mock_skill_store = Mock()
    
    # Mock the _ensure methods to set up dependencies
    async def mock_ensure_holon_fabric():
        pass
    
    async def mock_ensure_tool_handler():
        organ._tool_handler = mock_tool_handler
        organ._skill_store = mock_skill_store
    
    with patch.object(organ, "_ensure_holon_fabric", side_effect=mock_ensure_holon_fabric):
        with patch.object(organ, "_ensure_tool_handler", side_effect=mock_ensure_tool_handler):
            # Health check should pass when dependencies are initialized
            health = await organ.health_check()
            assert health is True


@pytest.mark.asyncio
async def test_organ_ping(mock_ray, mock_role_registry, organ_config):
    """Test ping method."""
    organ = Organ.remote(
        organ_id="test_organ",
        role_registry=mock_role_registry,
        **organ_config,
    )
    
    result = await organ.ping()
    assert result is True


@pytest.mark.asyncio
async def test_organ_respawn_agent(mock_ray, mock_role_registry, organ_config):
    """Test respawning a dead agent."""
    organ = Organ.remote(
        organ_id="test_organ",
        role_registry=mock_role_registry,
        **organ_config,
    )
    
    # Store agent info for respawn
    organ.agent_info["test_agent_6"] = {
        "agent_id": "test_agent_6",
        "specialization": "generalist",
        "class": "BaseAgent",
        "status": "ready",
    }
    
    mock_agent_class = Mock()
    mock_agent_instance = Mock()
    mock_agent_class.options.return_value.remote = Mock(return_value=mock_agent_instance)
    
    with patch("seedcore.organs.organ._load_agent_class", return_value=Mock):
        with patch("seedcore.organs.organ._ensure_ray_actor_class", return_value=mock_agent_class):
            await organ.respawn_agent("test_agent_6")
    
    # Verify agent was respawned
    assert "test_agent_6" in organ.agents
    assert organ.agent_info["test_agent_6"]["status"] == "respawned"


@pytest.mark.asyncio
async def test_organ_respawn_agent_missing_info(mock_ray, mock_role_registry, organ_config):
    """Test respawning agent with missing info raises error."""
    organ = Organ.remote(
        organ_id="test_organ",
        role_registry=mock_role_registry,
        **organ_config,
    )
    
    # Try to respawn non-existent agent
    with pytest.raises(ValueError, match="Cannot respawn"):
        await organ.respawn_agent("non_existent")


@pytest.mark.asyncio
async def test_organ_create_agent_duplicate_id(mock_ray, mock_role_registry, organ_config):
    """Test that creating agent with duplicate ID is handled."""
    organ = Organ.remote(
        organ_id="test_organ",
        role_registry=mock_role_registry,
        **organ_config,
    )
    
    # Add existing agent
    mock_handle = Mock()
    organ.agents["duplicate_agent"] = mock_handle
    
    # Try to create duplicate - should return early without error
    await organ.create_agent(
        agent_id="duplicate_agent",
        specialization=Specialization.GENERALIST,
        organ_id="test_organ",
    )
    
    # Agent should still exist (no replacement)
    assert "duplicate_agent" in organ.agents


@pytest.mark.asyncio
async def test_organ_create_agent_organ_id_mismatch(mock_ray, mock_role_registry, organ_config):
    """Test that creating agent with wrong organ_id raises error."""
    organ = Organ.remote(
        organ_id="test_organ",
        role_registry=mock_role_registry,
        **organ_config,
    )
    
    # Try to create agent with mismatched organ_id
    with pytest.raises(ValueError, match="ID Mismatch"):
        await organ.create_agent(
            agent_id="test_agent",
            specialization=Specialization.GENERALIST,
            organ_id="wrong_organ",  # Mismatch!
        )


def test_agent_id_factory():
    """Test AgentIDFactory generates agent IDs with correct format."""
    factory = AgentIDFactory()
    
    id1 = factory.new("organ_1", Specialization.GENERALIST)
    id2 = factory.new("organ_1", Specialization.GENERALIST)
    
    # IDs should have correct format: agent_{organ_id}_{spec}_{unique12}
    assert id1.startswith("agent_organ_1_")
    assert id2.startswith("agent_organ_1_")
    
    # IDs should be different (they contain random UUID component)
    assert id1 != id2
    
    # Different organ should generate different prefix
    id3 = factory.new("organ_2", Specialization.GENERALIST)
    assert id3.startswith("agent_organ_2_")
    assert id1 != id3
    
    # Different specialization should generate different ID
    id4 = factory.new("organ_1", Specialization.USER_LIAISON)
    assert id4.startswith("agent_organ_1_")
    assert "user_liaison" in id4 or "USER_LIAISON" in id4.upper()
    assert id1 != id4
    
    # Verify format: should have 3 parts separated by underscores
    parts = id1.split("_")
    assert len(parts) >= 3
    assert parts[0] == "agent"


@pytest.mark.asyncio
async def test_organ_get_status(mock_ray, mock_role_registry, organ_config):
    """Test getting organ status."""
    organ = Organ.remote(
        organ_id="test_organ",
        role_registry=mock_role_registry,
        **organ_config,
    )
    
    # Add some agents
    organ.agents["agent_1"] = Mock()
    organ.agents["agent_2"] = Mock()
    organ.agent_info["agent_1"] = {"status": "ready"}
    organ.agent_info["agent_2"] = {"status": "ready"}
    
    status = await organ.get_status()
    
    assert status["organ_id"] == "test_organ"
    assert status["agent_count"] == 2
    assert "agents" in status


@pytest.mark.asyncio
async def test_organ_get_summary(mock_ray, mock_role_registry, organ_config):
    """Test getting organ summary."""
    organ = Organ.remote(
        organ_id="test_organ",
        role_registry=mock_role_registry,
        **organ_config,
    )
    
    # Mock collect_agent_stats to return empty (no agents)
    with patch.object(organ, "collect_agent_stats", return_value={}):
        summary = await organ.get_summary()
        
        assert summary["organ_id"] == "test_organ"
        assert summary["agent_count"] == 0
        assert summary["status"] == "no_agents"
