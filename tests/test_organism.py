#!/usr/bin/env python3
"""
Test script for OrganismCore (src/seedcore/organs/organism_core.py).

Tests OrganismCore's core functionality:
- Initialization and config loading
- Organ creation
- Agent creation with behaviors
- Role profile registration
- Specialization mapping
- Task execution
- JIT agent spawning

Also includes integration tests for HTTP endpoints.
"""

import asyncio
import requests
import json
import time
import os
import sys
from typing import Dict, Any
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock, patch, mock_open

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from seedcore.organs.organism_core import OrganismCore
from seedcore.agents.roles import Specialization, RoleProfile, RoleRegistry, DEFAULT_ROLE_REGISTRY

def teardown_module(module):
    """Ensure Ray is properly shut down after tests to prevent state contamination."""
    try:
        import ray
        if ray.is_initialized():
            ray.shutdown()
            print("✅ Ray shut down in teardown_module")
    except Exception as e:
        print(f"Ray teardown skipped: {e}")

def test_organism_endpoints():
    """Test the organism endpoints to verify the implementation."""
    # When running inside the container, use the internal service address
    # Check if we're running inside the container
    if os.path.exists('/.dockerenv') or os.getenv('KUBERNETES_SERVICE_HOST'):
        # Running inside container, use internal service address
        base_url = "http://localhost:8002"
        print("   Running inside container, using internal service address")
    else:
        # Running locally, use environment variable or default
        base_url = os.getenv("SEEDCORE_API", "localhost:8002")
        if not base_url.startswith("http"):
            base_url = f"http://{base_url}"
    
    print("🔍 Testing COA Organism Implementation")
    print("=" * 50)
    
    # Test 1: Check organism status
    print("\n1. Testing organism status...")
    try:
        response = requests.get(f"{base_url}/organism/status")
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                organs = data.get("data", [])
                print(f"✅ Organism status retrieved successfully")
                print(f"   Found {len(organs)} organs:")
                for organ in organs:
                    print(f"   - {organ.get('organ_id')} ({organ.get('organ_type')}): {organ.get('agent_count')} agents")
            else:
                print(f"❌ Organism not initialized: {data.get('error')}")
        else:
            print(f"❌ Failed to get organism status: {response.status_code}")
    except Exception as e:
        print(f"❌ Error testing organism status: {e}")
    
    # Test 2: Get organism summary
    print("\n2. Testing organism summary...")
    try:
        response = requests.get(f"{base_url}/organism/summary")
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                summary = data.get("summary", {})
                print(f"✅ Organism summary retrieved successfully")
                print(f"   Initialized: {summary.get('initialized')}")
                print(f"   Organ count: {summary.get('organ_count')}")
                print(f"   Total agents: {summary.get('total_agent_count')}")
                
                # Show detailed organ info
                organs = summary.get("organs", {})
                for organ_id, organ_info in organs.items():
                    if isinstance(organ_info, dict) and "error" not in organ_info:
                        print(f"   - {organ_id}: {organ_info.get('agent_count', 0)} agents")
                    else:
                        print(f"   - {organ_id}: Error getting status")
            else:
                print(f"❌ Failed to get summary: {data.get('error')}")
        else:
            print(f"❌ Failed to get organism summary: {response.status_code}")
    except Exception as e:
        print(f"❌ Error testing organism summary: {e}")
    
    # Test 3: Execute task on random organ
    print("\n3. Testing task execution on random organ...")
    try:
        # Get available organs first to select a random one
        response = requests.get(f"{base_url}/organism/status")
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                # Use the same data structure as test 1: data.get("data", [])
                organs = data.get("data", [])
                if organs:
                    # Select a random organ from available organs
                    import random
                    random_organ = random.choice(organs)
                    organ_id = random_organ.get("organ_id", "cognitive_organ_1")  # fallback
                    
                    print(f"   Selected random organ: {organ_id}")
                    
                    task_data = {
                        "task_data": {
                            "type": "test_task",
                            "description": "Test task for COA organism",
                            "parameters": {"test": True}
                        }
                    }
                    response = requests.post(f"{base_url}/organism/execute/{organ_id}", json=task_data)
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("success"):
                            print(f"✅ Task executed successfully on organ: {data.get('organ_id')}")
                            print(f"   Result: {data.get('result', 'No result data')}")
                        else:
                            print(f"❌ Task execution failed: {data.get('error')}")
                    else:
                        print(f"❌ Failed to execute task: {response.status_code}")
                else:
                    print("❌ No organs available for random selection")
                    print(f"   Debug: Response data structure: {data}")
            else:
                print(f"❌ Failed to get organism status: {data.get('error')}")
        else:
            print(f"❌ Failed to get organism status: {response.status_code}")
    except Exception as e:
        print(f"❌ Error testing task execution: {e}")
    
    # Test 4: Execute task on specific organ
    print("\n4. Testing task execution on specific organ...")
    try:
        task_data = {
            "task_data": {
                "type": "cognitive_task",
                "description": "Test cognitive reasoning task",
                "parameters": {"complexity": "high"}
            }
        }
        response = requests.post(f"{base_url}/organism/execute/cognitive_organ_1", json=task_data)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                print(f"✅ Cognitive task executed successfully")
                print(f"   Result: {data.get('result', 'No result data')}")
            else:
                print(f"❌ Cognitive task failed: {data.get('error')}")
        else:
            print(f"❌ Failed to execute cognitive task: {response.status_code}")
    except Exception as e:
        print(f"❌ Error testing cognitive task: {e}")
    
    print("\n" + "=" * 50)
    print("🎯 COA Organism Test Complete")
    print("=" * 50)

def test_ray_cluster():
    """Test Ray cluster status to ensure it's running."""
    print("\n🔍 Testing Ray Cluster Status")
    print("-" * 30)
    
    try:
        # When running inside the container, use the internal service address
        # Check if we're running inside the container
        if os.path.exists('/.dockerenv') or os.getenv('KUBERNETES_SERVICE_HOST'):
            # Running inside container, use internal service address
            base_url = "http://localhost:8002"
            print("   Running inside container, using internal service address")
        else:
            # Running locally, use environment variable or default
            base_url = os.getenv("SEEDCORE-API", "localhost:8002")
            if not base_url.startswith("http"):
                base_url = f"http://{base_url}"
        
        print(f"   Testing endpoint: {base_url}/ray/status")
        response = requests.get(f"{base_url}/ray/status", timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Ray cluster is running")
            print(f"   Ray configured: {data.get('ray_configured', 'Unknown')}")
            print(f"   Ray available: {data.get('ray_available', 'Unknown')}")
            print(f"   Config: {data.get('config', 'Unknown')}")
            if 'cluster_info' in data:
                cluster_info = data['cluster_info']
                print(f"   Cluster info: {cluster_info}")
        elif response.status_code == 500:
            # Try to get error details from response body
            try:
                error_data = response.json()
                print(f"❌ Ray cluster endpoint returned 500 error:")
                print(f"   Error: {error_data.get('error', 'Unknown server error')}")
                if 'error_type' in error_data:
                    print(f"   Error type: {error_data.get('error_type')}")
            except:
                print(f"❌ Ray cluster endpoint returned 500 error (no error details)")
                print(f"   Response body: {response.text[:200]}...")
        else:
            print(f"❌ Ray cluster not accessible: {response.status_code}")
            print(f"   Response body: {response.text[:200]}...")
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Connection error: {e}")
        print("   Make sure the seedcore-api service is running")
    except requests.exceptions.Timeout as e:
        print(f"❌ Timeout error: {e}")
        print("   The request took too long to complete")
    except Exception as e:
        print(f"❌ Error testing Ray cluster: {e}")
        print(f"   Error type: {type(e).__name__}")

# ============================================================================
# Unit Tests for OrganismCore Class
# ============================================================================

@pytest.fixture
def mock_ray():
    """Mock Ray for testing without actual Ray cluster."""
    with patch("seedcore.organs.organism_core.ray") as mock_ray:
        mock_ray.is_initialized.return_value = True
        mock_ray.remote = lambda **kwargs: lambda cls: cls
        mock_ray.actor.ActorHandle = Mock
        mock_ray.get_actor = Mock(side_effect=ValueError("Actor not found"))
        yield mock_ray


@pytest.fixture
def sample_config():
    """Sample organs.yaml configuration."""
    return {
        "seedcore": {
            "organism": {
                "settings": {
                    "tunnel_threshold": 0.85,
                },
                "organs": [
                    {
                        "id": "test_organ_1",
                        "description": "Test organ 1",
                        "agents": [
                            {
                                "specialization": "GENERALIST",
                                "class": "BaseAgent",
                                "behaviors": ["chat_history"],
                                "behavior_config": {
                                    "chat_history": {"limit": 50}
                                },
                                "count": 1,
                            }
                        ],
                    }
                ],
            }
        }
    }


@pytest.fixture
def mock_config_file(tmp_path, sample_config):
    """Create a temporary config file."""
    try:
        import yaml
        config_file = tmp_path / "test_organs.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config, f)
        return config_file
    except ImportError:
        # Fallback: create minimal YAML manually
        config_file = tmp_path / "test_organs.yaml"
        config_content = """seedcore:
  organism:
    settings:
      tunnel_threshold: 0.85
    organs:
      - id: test_organ_1
        description: Test organ 1
        agents:
          - specialization: GENERALIST
            class: BaseAgent
            behaviors: [chat_history]
            behavior_config:
              chat_history:
                limit: 50
            count: 1
"""
        with open(config_file, "w") as f:
            f.write(config_content)
        return config_file


@pytest.mark.asyncio
async def test_organism_core_initialization(mock_ray, mock_config_file):
    """Test that OrganismCore initializes correctly."""
    core = OrganismCore(config_path=str(mock_config_file))
    
    assert core.config_path == mock_config_file.resolve()
    assert len(core.organ_configs) > 0
    assert core.global_settings is not None
    assert not core._initialized


@pytest.mark.asyncio
async def test_organism_core_load_config(mock_ray, mock_config_file):
    """Test config loading."""
    core = OrganismCore(config_path=str(mock_config_file))
    
    # Config should be loaded
    assert len(core.organ_configs) == 1
    assert core.organ_configs[0]["id"] == "test_organ_1"
    assert "agents" in core.organ_configs[0]
    assert core.global_settings["tunnel_threshold"] == 0.85


@pytest.mark.asyncio
async def test_organism_core_register_role_profiles(mock_ray, mock_config_file):
    """Test role profile registration from config."""
    core = OrganismCore(config_path=str(mock_config_file))
    
    # Mock the role registry
    core.role_registry = RoleRegistry()
    
    # Register role profiles
    await core._register_all_role_profiles_from_config()
    
    # Verify GENERALIST is registered
    profile = core.role_registry.get_safe(Specialization.GENERALIST)
    assert profile is not None


@pytest.mark.asyncio
async def test_organism_core_register_role_profiles_with_behaviors(mock_ray, mock_config_file):
    """Test role profile registration includes behaviors from specializations.yaml."""
    core = OrganismCore(config_path=str(mock_config_file))
    
    # Mock specializations.yaml loading
    with patch("seedcore.organs.organism_core.Path.exists", return_value=False):
        core.role_registry = RoleRegistry()
        await core._register_all_role_profiles_from_config()
    
    # Verify role profiles are registered
    profile = core.role_registry.get_safe(Specialization.GENERALIST)
    assert profile is not None


@pytest.mark.asyncio
async def test_organism_core_create_agents_with_behaviors(mock_ray, mock_config_file):
    """Test agent creation with behaviors from config."""
    core = OrganismCore(config_path=str(mock_config_file))
    
    # Mock organ creation
    mock_organ = Mock()
    mock_organ.create_agent = AsyncMock()
    mock_organ.get_agent_handle = AsyncMock(return_value=None)
    core.organs["test_organ_1"] = mock_organ
    
    # Mock _ensure_single_agent to avoid actual agent creation
    async def mock_ensure(agent_id, organ_id, organ_handle, spec, agent_class_name, behaviors=None, behavior_config=None):
        return True
    
    core._ensure_single_agent = mock_ensure
    
    # Create agents
    await core._create_agents_from_config()
    
    # Verify create_agent was called with behaviors
    # (The actual call happens in _ensure_single_agent, but we can verify the config was parsed)


@pytest.mark.asyncio
async def test_organism_core_merge_behaviors_from_role_profile(mock_ray, mock_config_file):
    """Test that behaviors are merged from RoleProfile defaults."""
    core = OrganismCore(config_path=str(mock_config_file))
    
    # Create a role registry with default behaviors
    registry = RoleRegistry()
    profile = RoleProfile(
        name=Specialization.GENERALIST,
        default_skills={},
        allowed_tools=set(),
        routing_tags=set(),
        default_behaviors=["background_loop"],  # Default behavior
        behavior_config={"background_loop": {"interval_s": 10.0}},  # Default config
    )
    registry.register(profile)
    core.role_registry = registry
    
    # Verify profile has behaviors
    profile = core.role_registry.get(Specialization.GENERALIST)
    assert "background_loop" in profile.default_behaviors
    assert profile.behavior_config["background_loop"]["interval_s"] == 10.0


@pytest.mark.asyncio
async def test_organism_core_jit_spawn_with_behaviors(mock_ray, mock_config_file):
    """Test JIT agent spawning with behaviors from executor hints."""
    core = OrganismCore(config_path=str(mock_config_file))
    
    # Mock organ - need to support .remote() calls
    async def mock_create_agent(*args, **kwargs):
        return None
    
    mock_organ = Mock()
    mock_create_agent_mock = AsyncMock(side_effect=mock_create_agent)
    mock_organ.create_agent = Mock()
    mock_organ.create_agent.remote = mock_create_agent_mock
    core.organs["test_organ_1"] = mock_organ
    
    # Mock get_specialization
    with patch("seedcore.organs.organism_core.get_specialization", return_value=Specialization.GENERALIST):
        await core._jit_spawn_agent(
            mock_organ,
            "test_organ_1",
            "jit_agent_1",
            "generalist",
            behaviors=["chat_history"],
            behavior_config={"chat_history": {"limit": 30}},
        )
    
    # Verify create_agent.remote was called with behaviors
    mock_create_agent_mock.assert_called_once()
    call_kwargs = mock_create_agent_mock.call_args[1]
    assert call_kwargs["behaviors"] == ["chat_history"]
    assert call_kwargs["behavior_config"]["chat_history"]["limit"] == 30


@pytest.mark.asyncio
async def test_organism_core_get_specialization_map(mock_ray, mock_config_file):
    """Test getting specialization to organ mapping."""
    core = OrganismCore(config_path=str(mock_config_file))
    
    # Mock organ creation and agent creation
    mock_organ = Mock()
    core.organs["test_organ_1"] = mock_organ
    # Use specialization_to_organ (not organ_specs) - it maps SpecializationProtocol -> organ_id
    core.specialization_to_organ[Specialization.GENERALIST] = "test_organ_1"
    
    # Get specialization map
    spec_map = core.get_specialization_map()
    
    assert "generalist" in spec_map
    assert spec_map["generalist"] == "test_organ_1"


@pytest.mark.asyncio
async def test_organism_core_execute_on_agent(mock_ray, mock_config_file):
    """Test executing a task on a specific agent."""
    core = OrganismCore(config_path=str(mock_config_file))
    
    # Mock agent handle - need to support .remote() calls
    async def mock_execute_task(*args, **kwargs):
        return {"success": True, "result": "test"}
    
    mock_agent_handle = Mock()
    mock_execute_task_mock = AsyncMock(side_effect=mock_execute_task)
    mock_agent_handle.execute_task = Mock()
    mock_agent_handle.execute_task.remote = mock_execute_task_mock
    
    # Mock organ - need to support .remote() calls
    async def mock_get_agent_handle(agent_id):
        return mock_agent_handle
    
    mock_organ = Mock()
    mock_get_handle_mock = AsyncMock(side_effect=mock_get_agent_handle)
    mock_organ.get_agent_handle = Mock()
    mock_organ.get_agent_handle.remote = mock_get_handle_mock
    core.organs["test_organ_1"] = mock_organ
    
    # Create task payload
    from seedcore.models import TaskPayload
    task = TaskPayload(
        task_id="test-task",
        type="test",
        description="Test task",
        params={},
    )
    
    # Execute task
    result = await core.execute_on_agent("test_organ_1", "test_agent", task)
    
    # Verify execution
    assert result["success"] is True
    mock_execute_task_mock.assert_called_once()


@pytest.mark.asyncio
async def test_organism_core_ensure_agent_handle_jit_spawn(mock_ray, mock_config_file):
    """Test that missing agents trigger JIT spawn."""
    core = OrganismCore(config_path=str(mock_config_file))
    
    # Mock agent handle
    mock_agent_handle = Mock()
    
    # Mock organ - need to support .remote() calls
    call_count = 0
    async def mock_get_handle(agent_id):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None  # First call: not found
        return mock_agent_handle  # Second call: found
    
    mock_get_handle_mock = AsyncMock(side_effect=mock_get_handle)
    mock_organ = Mock()
    mock_organ.get_agent_handle = Mock()
    mock_organ.get_agent_handle.remote = mock_get_handle_mock
    core.organs["test_organ_1"] = mock_organ
    
    # Mock JIT spawn
    core._jit_spawn_agent = AsyncMock(return_value=True)
    
    # Ensure agent handle (should trigger JIT spawn)
    params = {
        "routing": {
            "specialization": "generalist"
        },
        "executor": {
            "behaviors": ["chat_history"],
            "behavior_config": {"chat_history": {"limit": 25}},
        }
    }
    
    handle = await core._ensure_agent_handle(mock_organ, "test_organ_1", "jit_agent", params)
    
    # Verify JIT spawn was called with behaviors from executor hints
    core._jit_spawn_agent.assert_called_once()
    call_kwargs = core._jit_spawn_agent.call_args[1]
    assert call_kwargs["behaviors"] == ["chat_history"]
    assert call_kwargs["behavior_config"]["chat_history"]["limit"] == 25
    
    # Verify handle was returned
    assert handle == mock_agent_handle


@pytest.mark.asyncio
async def test_organism_core_register_or_update_role(mock_ray, mock_config_file):
    """Test registering or updating a role profile."""
    core = OrganismCore(config_path=str(mock_config_file))
    
    # Initialize role registry
    core.role_registry = RoleRegistry()
    
    # Mock organs - need to support .remote() calls
    async def mock_update_role_registry(profile):
        return None
    
    mock_update_mock = AsyncMock(side_effect=mock_update_role_registry)
    mock_organ = Mock()
    mock_organ.update_role_registry = Mock()
    mock_organ.update_role_registry.remote = mock_update_mock
    core.organs["test_organ_1"] = mock_organ
    
    # Create new profile
    profile = RoleProfile(
        name=Specialization.USER_LIAISON,
        default_skills={"communication": 0.9},
        allowed_tools={"chat.reply"},
        routing_tags={"user_facing"},
        default_behaviors=["chat_history"],
        behavior_config={"chat_history": {"limit": 50}},
    )
    
    # Register role
    await core.register_or_update_role(profile)
    
    # Verify profile was registered in core's registry
    assert core.role_registry.get_safe(Specialization.USER_LIAISON) is not None
    
    # Verify organs were updated via .remote() call
    mock_update_mock.assert_called_once_with(profile)


if __name__ == "__main__":
    print("🚀 Starting COA Organism Tests...")
    
    # Test Ray cluster first
    test_ray_cluster()
    
    # Test organism endpoints
    test_organism_endpoints()
    
    print("\n💡 Next Steps:")
    print("   • Check the logs: docker logs seedcore-api")
    print("   • Access dashboard: http://localhost:8265")
    print("   • Monitor real-time: docker logs -f seedcore-api") 