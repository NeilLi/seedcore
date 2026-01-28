#!/usr/bin/env python3
"""
Comprehensive Unit Tests for SeedCore Agent Behaviors

Tests all behavior implementations:
- ChatHistoryBehavior
- TaskFilterBehavior
- BackgroundLoopBehavior
- DedupBehavior
- ToolRegistrationBehavior
- SafetyCheckBehavior (with 2026 enhancements)
- ToolAutoInjectionBehavior
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any

from seedcore.agents.base import BaseAgent
from seedcore.agents.behaviors import (
    ChatHistoryBehavior,
    TaskFilterBehavior,
    BackgroundLoopBehavior,
    DedupBehavior,
    ToolRegistrationBehavior,
    SafetyCheckBehavior,
    ToolAutoInjectionBehavior,
)
from seedcore.agents.behaviors.task_filter import TaskRejectedError
from seedcore.agents.behaviors.dedup import TaskDedupedError
from seedcore.agents.behaviors.safety_check import SafetyCheckFailedError
from seedcore.agents.roles import Specialization, RoleProfile, RoleRegistry
from seedcore.models import TaskPayload


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def mock_agent():
    """Create a mock agent for behavior testing."""
    agent = Mock(spec=BaseAgent)
    agent.agent_id = "test_agent_001"
    agent.tool_handler = None
    agent.cognitive_client = None
    agent.ml_client = None
    return agent


@pytest.fixture
def real_agent():
    """Create a real BaseAgent instance for integration testing."""
    registry = RoleRegistry()
    return BaseAgent(
        agent_id="test_agent_real",
        specialization=Specialization.GENERALIST,
        role_registry=registry,
    )


# ============================================================================
# ChatHistoryBehavior Tests
# ============================================================================

class TestChatHistoryBehavior:
    """Tests for ChatHistoryBehavior."""

    @pytest.mark.asyncio
    async def test_chat_history_initialization(self, mock_agent):
        """Test chat history behavior initialization."""
        behavior = ChatHistoryBehavior(mock_agent, {"limit": 30})
        await behavior.initialize()
        
        assert behavior._initialized
        assert behavior._history_limit == 30
        assert len(behavior._chat_history) == 0

    @pytest.mark.asyncio
    async def test_chat_history_default_limit(self, mock_agent):
        """Test default limit is 50."""
        behavior = ChatHistoryBehavior(mock_agent)
        await behavior.initialize()
        
        assert behavior._history_limit == 50

    @pytest.mark.asyncio
    async def test_add_user_message(self, mock_agent):
        """Test adding user messages to history."""
        behavior = ChatHistoryBehavior(mock_agent, {"limit": 5})
        await behavior.initialize()
        
        behavior.add_user_message("Hello")
        behavior.add_user_message("How are you?")
        
        history = behavior.get_chat_history()
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello"
        assert history[1]["content"] == "How are you?"

    @pytest.mark.asyncio
    async def test_add_assistant_message(self, mock_agent):
        """Test adding assistant messages to history."""
        behavior = ChatHistoryBehavior(mock_agent, {"limit": 5})
        await behavior.initialize()
        
        behavior.add_assistant_message("I'm doing well!")
        
        history = behavior.get_chat_history()
        assert len(history) == 1
        assert history[0]["role"] == "assistant"
        assert history[0]["content"] == "I'm doing well!"

    @pytest.mark.asyncio
    async def test_ring_buffer_limit(self, mock_agent):
        """Test that ring buffer maintains limit."""
        behavior = ChatHistoryBehavior(mock_agent, {"limit": 3})
        await behavior.initialize()
        
        # Add 5 messages
        for i in range(5):
            behavior.add_user_message(f"Message {i}")
        
        history = behavior.get_chat_history()
        assert len(history) == 3  # Should only keep last 3
        assert history[0]["content"] == "Message 2"
        assert history[2]["content"] == "Message 4"

    @pytest.mark.asyncio
    async def test_get_recent_conversation_window(self, mock_agent):
        """Test windowed history retrieval."""
        behavior = ChatHistoryBehavior(mock_agent, {"limit": 20})
        await behavior.initialize()
        
        # Add 10 messages
        for i in range(10):
            if i % 2 == 0:
                behavior.add_user_message(f"User {i}")
            else:
                behavior.add_assistant_message(f"Assistant {i}")
        
        # Get last 4 turns
        recent = behavior.get_recent_conversation_window(max_turns=4)
        assert len(recent) == 4
        assert recent[-1]["content"] == "Assistant 9"

    @pytest.mark.asyncio
    async def test_execute_task_pre_injects_history(self, mock_agent):
        """Test that execute_task_pre injects chat history."""
        behavior = ChatHistoryBehavior(mock_agent, {"limit": 10})
        await behavior.initialize()
        
        behavior.add_user_message("Previous message")
        behavior.add_assistant_message("Previous response")
        
        task_dict = {
            "params": {
                "interaction": {"mode": "agent_tunnel"},
                "chat": {"message": "New message"},
            }
        }
        
        result = await behavior.execute_task_pre(None, task_dict)
        
        assert result is not None
        assert "history" in result["params"]["chat"]
        # History includes the 2 previous messages + the new one added during execute_task_pre
        assert len(result["params"]["chat"]["history"]) == 3
        assert result["params"]["interaction"]["assigned_agent_id"] == "test_agent_001"

    @pytest.mark.asyncio
    async def test_execute_task_pre_respects_disable_memory_write(self, mock_agent):
        """Test that disable_memory_write prevents history updates."""
        behavior = ChatHistoryBehavior(mock_agent, {"limit": 10})
        await behavior.initialize()
        
        initial_count = len(behavior._chat_history)
        
        task_dict = {
            "params": {
                "interaction": {"mode": "agent_tunnel"},
                "chat": {"message": "New message"},
                "cognitive": {"disable_memory_write": True},
            }
        }
        
        await behavior.execute_task_pre(None, task_dict)
        
        # History should not have been updated
        assert len(behavior._chat_history) == initial_count

    @pytest.mark.asyncio
    async def test_execute_task_post_extracts_assistant_message(self, mock_agent):
        """Test that execute_task_post extracts and stores assistant message."""
        behavior = ChatHistoryBehavior(mock_agent, {"limit": 10})
        await behavior.initialize()
        
        task_dict = {
            "params": {
                "interaction": {"mode": "agent_tunnel"},
            }
        }
        
        result = {
            "payload": {
                "result": {
                    "response": "Assistant response here"
                }
            }
        }
        
        await behavior.execute_task_post(None, task_dict, result)
        
        history = behavior.get_chat_history()
        assert len(history) == 1
        assert history[0]["role"] == "assistant"
        assert history[0]["content"] == "Assistant response here"

    @pytest.mark.asyncio
    async def test_shutdown_clears_history(self, mock_agent):
        """Test that shutdown clears chat history."""
        behavior = ChatHistoryBehavior(mock_agent)
        await behavior.initialize()
        
        behavior.add_user_message("Test")
        assert len(behavior._chat_history) > 0
        
        await behavior.shutdown()
        assert len(behavior._chat_history) == 0


# ============================================================================
# TaskFilterBehavior Tests
# ============================================================================

class TestTaskFilterBehavior:
    """Tests for TaskFilterBehavior."""

    @pytest.mark.asyncio
    async def test_task_filter_initialization(self, mock_agent):
        """Test task filter initialization."""
        behavior = TaskFilterBehavior(
            mock_agent,
            {"allowed_types": ["env.tick", "environment.tick"]}
        )
        await behavior.initialize()
        
        assert behavior._initialized
        assert "env.tick" in behavior._allowed_types
        assert "environment.tick" in behavior._allowed_types

    @pytest.mark.asyncio
    async def test_task_filter_allows_matching_type(self, mock_agent):
        """Test that matching task types are allowed."""
        behavior = TaskFilterBehavior(
            mock_agent,
            {"allowed_types": ["env.tick", "test.task"]}
        )
        await behavior.initialize()
        
        task = TaskPayload(
            task_id="test-1",
            type="env.tick",
            description="Test",
            params={}
        )
        task_dict = {"task_id": "test-1", "type": "env.tick"}
        
        # Should not raise
        result = await behavior.execute_task_pre(task, task_dict)
        assert result is None  # No modification, task allowed

    @pytest.mark.asyncio
    async def test_task_filter_rejects_non_matching_type(self, mock_agent):
        """Test that non-matching task types are rejected."""
        behavior = TaskFilterBehavior(
            mock_agent,
            {"allowed_types": ["env.tick"]}
        )
        await behavior.initialize()
        
        task = TaskPayload(
            task_id="test-2",
            type="user.query",
            description="Test",
            params={}
        )
        task_dict = {"task_id": "test-2", "type": "user.query"}
        
        # Should raise TaskRejectedError
        with pytest.raises(TaskRejectedError) as exc_info:
            await behavior.execute_task_pre(task, task_dict)
        
        assert exc_info.value.rejection_result["success"] is False
        assert "not allowed" in exc_info.value.rejection_result["error"].lower()

    @pytest.mark.asyncio
    async def test_task_filter_allows_all_when_empty(self, mock_agent):
        """Test that empty allowed_types allows all tasks."""
        behavior = TaskFilterBehavior(mock_agent, {"allowed_types": []})
        await behavior.initialize()
        
        task_dict = {"type": "any.task"}
        result = await behavior.execute_task_pre(None, task_dict)
        assert result is None  # No filtering

    @pytest.mark.asyncio
    async def test_task_filter_case_insensitive(self, mock_agent):
        """Test that task type matching is case-insensitive."""
        behavior = TaskFilterBehavior(
            mock_agent,
            {"allowed_types": ["ENV.TICK"]}
        )
        await behavior.initialize()
        
        task = TaskPayload(
            task_id="test-case",
            type="env.tick",
            description="Test",
            params={}
        )
        task_dict = {"task_id": "test-case", "type": "env.tick"}
        result = await behavior.execute_task_pre(task, task_dict)
        assert result is None  # Should match despite case difference

    @pytest.mark.asyncio
    async def test_task_filter_disabled(self, mock_agent):
        """Test that disabled filter allows all tasks."""
        behavior = TaskFilterBehavior(
            mock_agent,
            {"enabled": False, "allowed_types": ["env.tick"]}
        )
        await behavior.initialize()
        
        task_dict = {"type": "user.query"}
        result = await behavior.execute_task_pre(None, task_dict)
        assert result is None  # Filter disabled, should allow


# ============================================================================
# BackgroundLoopBehavior Tests
# ============================================================================

class TestBackgroundLoopBehavior:
    """Tests for BackgroundLoopBehavior."""

    @pytest.mark.asyncio
    async def test_background_loop_initialization(self, mock_agent):
        """Test background loop initialization."""
        mock_method = Mock()
        mock_agent.control_tick = mock_method
        
        behavior = BackgroundLoopBehavior(
            mock_agent,
            {"interval_s": 0.1, "method": "control_tick", "auto_start": False}
        )
        await behavior.initialize()
        
        assert behavior._initialized
        assert behavior._method_name == "control_tick"
        assert behavior._interval_s == 0.1

    @pytest.mark.asyncio
    async def test_background_loop_warns_on_missing_method(self, mock_agent):
        """Test that missing method logs warning."""
        behavior = BackgroundLoopBehavior(
            mock_agent,
            {"method": "nonexistent_method", "auto_start": False}
        )
        await behavior.initialize()
        
        assert behavior._method is None

    @pytest.mark.asyncio
    async def test_background_loop_start_stop(self, mock_agent):
        """Test starting and stopping background loop."""
        call_count = 0
        
        def mock_tick():
            nonlocal call_count
            call_count += 1
        
        mock_agent.test_tick = mock_tick
        
        behavior = BackgroundLoopBehavior(
            mock_agent,
            {"interval_s": 0.05, "method": "test_tick", "auto_start": False}
        )
        await behavior.initialize()
        
        # Start loop
        await behavior.start()
        assert behavior._loop_task is not None
        assert not behavior._loop_task.done()
        
        # Wait a bit
        await asyncio.sleep(0.15)
        
        # Stop loop
        await behavior.stop()
        
        # Verify method was called
        assert call_count > 0

    @pytest.mark.asyncio
    async def test_background_loop_error_handling(self, mock_agent):
        """Test that errors don't crash the loop immediately."""
        error_count = 0
        
        def failing_tick():
            nonlocal error_count
            error_count += 1
            raise ValueError("Test error")
        
        mock_agent.failing_tick = failing_tick
        
        behavior = BackgroundLoopBehavior(
            mock_agent,
            {"interval_s": 0.05, "method": "failing_tick", "max_errors": 3, "auto_start": False}
        )
        await behavior.initialize()
        
        await behavior.start()
        await asyncio.sleep(0.2)  # Let it run a bit
        await behavior.stop()
        
        # Should have tried multiple times before stopping
        assert error_count >= 3

    @pytest.mark.asyncio
    async def test_background_loop_circuit_breaker(self, mock_agent):
        """Test that loop stops after max_errors."""
        call_count = 0
        
        def failing_tick():
            nonlocal call_count
            call_count += 1
            raise ValueError("Persistent error")
        
        mock_agent.failing_tick = failing_tick
        
        behavior = BackgroundLoopBehavior(
            mock_agent,
            {"interval_s": 0.05, "method": "failing_tick", "max_errors": 2, "auto_start": False}
        )
        await behavior.initialize()
        
        await behavior.start()
        # Wait for circuit breaker (need enough time for multiple errors)
        # Each iteration takes ~0.05s, so 0.2s should give us at least 2-3 iterations
        await asyncio.sleep(0.25)
        
        # Loop should have stopped due to max errors (circuit breaker trips after 2 errors)
        assert call_count >= 2, f"Expected at least 2 calls, got {call_count}"
        # Wait a bit more to ensure loop has exited
        await asyncio.sleep(0.1)
        # Loop should be done (circuit breaker should have stopped it)
        assert behavior._loop_task.done(), "Loop should have stopped due to circuit breaker"

    @pytest.mark.asyncio
    async def test_background_loop_sync_method(self, mock_agent):
        """Test that sync methods work correctly."""
        call_count = 0
        
        def sync_tick():
            nonlocal call_count
            call_count += 1
        
        mock_agent.sync_tick = sync_tick
        
        behavior = BackgroundLoopBehavior(
            mock_agent,
            {"interval_s": 0.05, "method": "sync_tick", "auto_start": False}
        )
        await behavior.initialize()
        
        await behavior.start()
        await asyncio.sleep(0.15)
        await behavior.stop()
        
        assert call_count > 0


# ============================================================================
# DedupBehavior Tests
# ============================================================================

class TestDedupBehavior:
    """Tests for DedupBehavior."""

    @pytest.mark.asyncio
    async def test_dedup_initialization(self, mock_agent):
        """Test dedup behavior initialization."""
        behavior = DedupBehavior(mock_agent, {"ttl_s": 30.0})
        await behavior.initialize()
        
        assert behavior._initialized
        assert behavior._ttl_s == 30.0

    @pytest.mark.asyncio
    async def test_dedup_mark_and_check(self, mock_agent):
        """Test marking and checking seen keys."""
        behavior = DedupBehavior(mock_agent, {"ttl_s": 1.0})
        await behavior.initialize()
        
        # Mark key as seen
        await behavior.mark_seen("test_key_1")
        
        # Should be seen recently
        assert await behavior.seen_recently("test_key_1") is True
        assert await behavior.seen_recently("test_key_2") is False

    @pytest.mark.asyncio
    async def test_dedup_ttl_expiration(self, mock_agent):
        """Test that TTL expiration works."""
        behavior = DedupBehavior(mock_agent, {"ttl_s": 0.1})
        await behavior.initialize()
        
        await behavior.mark_seen("expiring_key")
        assert await behavior.seen_recently("expiring_key") is True
        
        # Wait for expiration
        await asyncio.sleep(0.15)
        
        # Should no longer be seen (expired)
        assert await behavior.seen_recently("expiring_key") is False

    @pytest.mark.asyncio
    async def test_dedup_execute_task_pre_blocks_duplicate(self, mock_agent):
        """Test that execute_task_pre blocks duplicate tasks."""
        behavior = DedupBehavior(mock_agent, {"ttl_s": 10.0})
        await behavior.initialize()
        
        task_dict = {"task_id": "duplicate_task_1"}
        
        # First execution - should mark as seen
        result1 = await behavior.execute_task_pre(None, task_dict)
        assert result1 is None  # First time, allowed
        
        # Second execution - should raise TaskDedupedError
        with pytest.raises(TaskDedupedError) as exc_info:
            await behavior.execute_task_pre(None, task_dict)
        
        assert exc_info.value.dedup_result["success"] is True
        assert exc_info.value.dedup_result["payload"]["dedup"] is True

    @pytest.mark.asyncio
    async def test_dedup_extracts_command_id(self, mock_agent):
        """Test that dedup extracts command_id if task_id not present."""
        behavior = DedupBehavior(mock_agent, {"ttl_s": 10.0})
        await behavior.initialize()
        
        task_dict = {"command_id": "cmd_123"}
        
        # First execution
        await behavior.execute_task_pre(None, task_dict)
        
        # Second execution should be deduplicated
        with pytest.raises(TaskDedupedError):
            await behavior.execute_task_pre(None, task_dict)

    @pytest.mark.asyncio
    async def test_dedup_disabled(self, mock_agent):
        """Test that disabled dedup allows all tasks."""
        behavior = DedupBehavior(mock_agent, {"enabled": False, "ttl_s": 10.0})
        await behavior.initialize()
        
        task_dict = {"task_id": "test_task"}
        
        # Should not raise even on duplicates
        result1 = await behavior.execute_task_pre(None, task_dict)
        result2 = await behavior.execute_task_pre(None, task_dict)
        
        assert result1 is None
        assert result2 is None


# ============================================================================
# ToolRegistrationBehavior Tests
# ============================================================================

class TestToolRegistrationBehavior:
    """Tests for ToolRegistrationBehavior."""

    @pytest.mark.asyncio
    async def test_tool_registration_initialization(self, mock_agent):
        """Test tool registration initialization."""
        behavior = ToolRegistrationBehavior(
            mock_agent,
            {"tools": ["tool1", "tool2"], "register_on_init": False}
        )
        await behavior.initialize()
        
        assert behavior._initialized
        assert "tool1" in behavior._tools
        assert "tool2" in behavior._tools

    @pytest.mark.asyncio
    async def test_tool_registration_single_tool_string(self, mock_agent):
        """Test that single tool string is handled."""
        behavior = ToolRegistrationBehavior(
            mock_agent,
            {"tools": "single_tool", "register_on_init": False}
        )
        await behavior.initialize()
        
        assert len(behavior._tools) == 1
        assert behavior._tools[0] == "single_tool"

    @pytest.mark.asyncio
    async def test_tool_registration_calls_register(self, mock_agent):
        """Test that tools are registered on initialization."""
        mock_tool_handler = Mock()
        mock_tool_handler.register_tool = AsyncMock()
        mock_agent.tool_handler = mock_tool_handler
        mock_agent._ensure_tool_handler = AsyncMock()
        
        behavior = ToolRegistrationBehavior(
            mock_agent,
            {"tools": ["test.tool1", "test.tool2"], "register_on_init": True}
        )
        await behavior.initialize()
        
        # Should have called register_tool for each tool
        assert mock_tool_handler.register_tool.call_count == 2
        mock_tool_handler.register_tool.assert_any_call("test.tool1")
        mock_tool_handler.register_tool.assert_any_call("test.tool2")

    @pytest.mark.asyncio
    async def test_tool_registration_sharded_handler(self, mock_agent):
        """Test registration with sharded tool handler."""
        mock_shard1 = Mock()
        mock_shard1.register_tool = AsyncMock()
        mock_shard2 = Mock()
        mock_shard2.register_tool = AsyncMock()
        
        mock_agent.tool_handler = [mock_shard1, mock_shard2]
        mock_agent._ensure_tool_handler = AsyncMock()
        
        behavior = ToolRegistrationBehavior(
            mock_agent,
            {"tools": ["sharded.tool"], "register_on_init": True}
        )
        await behavior.initialize()
        
        # Should register in both shards
        assert mock_shard1.register_tool.remote.call_count == 1
        assert mock_shard2.register_tool.remote.call_count == 1

    @pytest.mark.asyncio
    async def test_tool_registration_no_handler_graceful(self, mock_agent):
        """Test that missing tool handler is handled gracefully."""
        mock_agent.tool_handler = None
        
        behavior = ToolRegistrationBehavior(
            mock_agent,
            {"tools": ["test.tool"], "register_on_init": True}
        )
        
        # Should not raise, just log warning
        await behavior.initialize()
        assert behavior._initialized


# ============================================================================
# SafetyCheckBehavior Tests (2026 Enhanced)
# ============================================================================

class TestSafetyCheckBehavior:
    """Tests for SafetyCheckBehavior with 2026 enhancements."""

    @pytest.mark.asyncio
    async def test_safety_check_initialization(self, mock_agent):
        """Test safety check initialization."""
        behavior = SafetyCheckBehavior(
            mock_agent,
            {
                "enabled": True,
                "deny_patterns": ["dangerous", "delete"],
                "guardrail_enabled": True,
                "guardrail_model": "meta-llama/Llama-Guard-3-Robot",
                "risk_threshold": 0.8,
                "joint_limit_check": True,
                "safety_level_estop": 0.95,
            }
        )
        await behavior.initialize()
        
        assert behavior._initialized
        assert behavior._enabled
        assert "dangerous" in behavior._deny_patterns
        assert behavior._guardrail_enabled
        assert behavior._joint_limit_check

    @pytest.mark.asyncio
    async def test_safety_check_pattern_matching(self, mock_agent):
        """Test pattern-based safety checks."""
        behavior = SafetyCheckBehavior(
            mock_agent,
            {"deny_patterns": ["delete", "destroy"]}
        )
        await behavior.initialize()
        
        # Should reject dangerous action
        dangerous_obj = {"action": "delete_all_data"}
        assert await behavior.check(dangerous_obj) is False
        
        # Should allow safe action
        safe_obj = {"action": "read_data"}
        assert await behavior.check(safe_obj) is True

    @pytest.mark.asyncio
    async def test_safety_check_extracts_safety_level(self, mock_agent):
        """Test extraction of safety_level from params.risk."""
        behavior = SafetyCheckBehavior(
            mock_agent,
            {"guardrail_enabled": False, "safety_level_estop": 0.95}
        )
        await behavior.initialize()
        
        obj = {
            "params": {
                "risk": {
                    "level": 0.8,
                    "safety_level": 0.92,
                }
            }
        }
        
        safety_level = behavior._extract_safety_level(obj)
        assert safety_level == 0.92

    @pytest.mark.asyncio
    async def test_safety_check_estop_on_high_safety_level(self, mock_agent):
        """Test E-STOP triggered by high safety_level."""
        behavior = SafetyCheckBehavior(
            mock_agent,
            {
                "guardrail_enabled": True,  # E-STOP check only happens when guardrail is enabled
                "safety_level_estop": 0.95,
            }
        )
        await behavior.initialize()
        
        obj = {
            "params": {
                "risk": {
                    "safety_level": 0.97,  # Above E-STOP threshold
                }
            },
            "action": "move_arm",
        }
        
        # Should trigger E-STOP (return False)
        assert await behavior.check(obj) is False

    @pytest.mark.asyncio
    async def test_safety_check_joint_limits(self, mock_agent):
        """Test joint limit validation."""
        behavior = SafetyCheckBehavior(
            mock_agent,
            {"joint_limit_check": True, "guardrail_enabled": False}
        )
        await behavior.initialize()
        
        # Valid joint angles
        valid_obj = {
            "tool_calls": [
                {
                    "tool": "reachy.motion.move",
                    "params": {
                        "shoulder_pitch": 45.0,
                        "elbow_pitch": 90.0,
                    }
                }
            ]
        }
        assert await behavior._check_joint_limits(valid_obj) is True
        
        # Invalid joint angle (outside limits)
        invalid_obj = {
            "tool_calls": [
                {
                    "tool": "reachy.motion.move",
                    "params": {
                        "shoulder_pitch": 200.0,  # Outside -180 to 180 range
                    }
                }
            ]
        }
        assert await behavior._check_joint_limits(invalid_obj) is False

    @pytest.mark.asyncio
    async def test_safety_check_execute_task_pre_blocks_unsafe(self, mock_agent):
        """Test that execute_task_pre blocks unsafe commands."""
        behavior = SafetyCheckBehavior(
            mock_agent,
            {"deny_patterns": ["delete"]}
        )
        await behavior.initialize()
        
        task_dict = {
            "task_id": "test-1",
            "params": {
                "commands": [{"action": "delete_all"}]
            }
        }
        
        # Should raise SafetyCheckFailedError
        with pytest.raises(SafetyCheckFailedError) as exc_info:
            await behavior.execute_task_pre(None, task_dict)
        
        assert exc_info.value.safety_result["success"] is False
        assert "safety_check_failed" in exc_info.value.safety_result["error_type"]

    @pytest.mark.asyncio
    async def test_safety_check_guardrail_integration(self, mock_agent):
        """Test guardrail model integration."""
        behavior = SafetyCheckBehavior(
            mock_agent,
            {
                "guardrail_enabled": True,
                "risk_threshold": 0.8,
                "escalate_to_remote": False,
            }
        )
        await behavior.initialize()
        
        # Mock guardrail client
        behavior._guardrail_client = {"model_id": "test-guardrail"}
        
        # High-risk content
        obj = {
            "action": "force_override",
            "params": {},
        }
        
        # Should be blocked by guardrail
        result = await behavior.check(obj)
        # Heuristic should detect high-risk keywords
        assert result is False  # Should be blocked

    @pytest.mark.asyncio
    async def test_safety_check_disabled_allows_all(self, mock_agent):
        """Test that disabled safety check allows all."""
        behavior = SafetyCheckBehavior(
            mock_agent,
            {"enabled": False, "deny_patterns": ["delete"]}
        )
        await behavior.initialize()
        
        obj = {"action": "delete_all"}
        assert await behavior.check(obj) is True  # Should allow when disabled


# ============================================================================
# ToolAutoInjectionBehavior Tests
# ============================================================================

class TestToolAutoInjectionBehavior:
    """Tests for ToolAutoInjectionBehavior."""

    @pytest.mark.asyncio
    async def test_tool_auto_injection_initialization(self, mock_agent):
        """Test tool auto-injection initialization."""
        behavior = ToolAutoInjectionBehavior(
            mock_agent,
            {"auto_add_general_query": True}
        )
        await behavior.initialize()
        
        assert behavior._initialized

    @pytest.mark.asyncio
    async def test_tool_auto_injection_adds_general_query(self, mock_agent):
        """Test that general_query tool is auto-added."""
        behavior = ToolAutoInjectionBehavior(
            mock_agent,
            {"auto_add_general_query": True}
        )
        await behavior.initialize()
        
        task_dict = {
            "type": "chat",
            "params": {
                "interaction": {"mode": "agent_tunnel"},
                "chat": {"message": "Hello"},
                "routing": {}
            }
        }
        
        result = await behavior.execute_task_pre(None, task_dict)
        
        assert result is not None
        tools = result["params"]["routing"].get("tools", [])
        assert "general_query" in tools


# ============================================================================
# Integration Tests
# ============================================================================

class TestBehaviorIntegration:
    """Integration tests for multiple behaviors working together."""

    @pytest.mark.asyncio
    async def test_chat_history_and_task_filter(self):
        """Test chat history and task filter working together."""
        from seedcore.agents.behaviors import create_behavior_registry
        
        # Create a proper role registry with GENERALIST registered
        registry = RoleRegistry()
        profile = RoleProfile(
            name=Specialization.GENERALIST,
            default_skills={"test_skill": 0.5},
            allowed_tools={"test.tool"},
            routing_tags={"test"},
            safety_policies={},
        )
        registry.register(profile)
        
        # Create real agent with proper registry
        real_agent = BaseAgent(
            agent_id="test_agent_integration",
            specialization=Specialization.GENERALIST,
            role_registry=registry,
        )
        
        behavior_registry = create_behavior_registry()
        real_agent._behavior_registry = behavior_registry
        
        # Add behaviors
        real_agent._behaviors_to_init = {
            "names": ["chat_history", "task_filter"],
            "configs": {
                "chat_history": {"limit": 10},
                "task_filter": {"allowed_types": ["test.task"]},
            }
        }
        
        # Initialize behaviors
        await real_agent._initialize_behaviors()
        
        # Create task
        task = TaskPayload(
            task_id="test-integration",
            type="test.task",
            description="Test integration",
            params={
                "interaction": {"mode": "agent_tunnel"},
                "chat": {"message": "Hello"},
            }
        )
        
        # Execute - should work (task type allowed)
        result = await real_agent.execute_task(task)
        assert result is not None

    @pytest.mark.asyncio
    async def test_safety_check_and_dedup_chain(self, mock_agent):
        """Test safety check and dedup working in sequence."""
        safety_behavior = SafetyCheckBehavior(
            mock_agent,
            {"deny_patterns": ["delete"]}
        )
        await safety_behavior.initialize()
        
        dedup_behavior = DedupBehavior(mock_agent, {"ttl_s": 10.0})
        await dedup_behavior.initialize()
        
        task_dict = {
            "task_id": "test-chain",
            "action": "read_data",  # Safe action
        }
        
        # Should pass safety check
        assert await safety_behavior.check(task_dict) is True
        
        # First dedup check should pass
        result1 = await dedup_behavior.execute_task_pre(None, task_dict)
        assert result1 is None
        
        # Second dedup check should block
        with pytest.raises(TaskDedupedError):
            await dedup_behavior.execute_task_pre(None, task_dict)

    @pytest.mark.asyncio
    async def test_background_loop_with_safety_check(self, mock_agent):
        """Test background loop calling method that uses safety check."""
        call_history = []
        
        def safe_tick():
            call_history.append("tick")
            # Simulate safety check (sync version)
            # Note: In real usage, safety checks would be async, but for this test
            # we use a sync method to avoid coroutine issues
        
        mock_agent.safe_tick = safe_tick
        
        behavior = BackgroundLoopBehavior(
            mock_agent,
            {"interval_s": 0.05, "method": "safe_tick", "auto_start": False}
        )
        await behavior.initialize()
        
        await behavior.start()
        await asyncio.sleep(0.15)
        await behavior.stop()
        
        assert len(call_history) > 0


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================

class TestBehaviorEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_chat_history_empty_message(self, mock_agent):
        """Test handling of empty messages."""
        behavior = ChatHistoryBehavior(mock_agent)
        await behavior.initialize()
        
        behavior.add_user_message("")
        behavior.add_assistant_message("   ")  # Whitespace only
        
        history = behavior.get_chat_history()
        assert len(history) == 2  # Should still add them

    @pytest.mark.asyncio
    async def test_task_filter_missing_type(self, mock_agent):
        """Test task filter with missing type field."""
        behavior = TaskFilterBehavior(
            mock_agent,
            {"allowed_types": ["test.task"]}
        )
        await behavior.initialize()
        
        task = TaskPayload(
            task_id="test-no-type",
            type="",  # Empty type
            description="Test",
            params={}
        )
        task_dict = {"task_id": "test-no-type", "type": ""}  # Empty type
        
        # Empty type should be rejected if not in allowed_types
        with pytest.raises(TaskRejectedError):
            await behavior.execute_task_pre(task, task_dict)

    @pytest.mark.asyncio
    async def test_dedup_missing_key(self, mock_agent):
        """Test dedup with missing task_id/command_id."""
        behavior = DedupBehavior(mock_agent)
        await behavior.initialize()
        
        task_dict = {}  # No key fields
        
        # Should not raise, just return None
        result = await behavior.execute_task_pre(None, task_dict)
        assert result is None

    @pytest.mark.asyncio
    async def test_safety_check_malformed_risk(self, mock_agent):
        """Test safety check with malformed risk structure."""
        behavior = SafetyCheckBehavior(
            mock_agent,
            {"guardrail_enabled": True}  # Enable guardrail so _extract_safety_level is called
        )
        await behavior.initialize()
        
        obj = {
            "action": "test_action",  # Need an action to pass initial checks
            "params": {
                "risk": "not_a_dict"  # Malformed
            }
        }
        
        # The check method should handle this gracefully (catches exceptions)
        # When risk is malformed, _extract_safety_level will handle it gracefully
        # (now checks isinstance(risk, dict) before calling .get())
        result = await behavior.check(obj)
        # Should return True (malformed risk is handled gracefully, returns 0.0)
        # The guardrail check will proceed with safety_level=0.0
        assert result is True  # No safety issues detected

    @pytest.mark.asyncio
    async def test_background_loop_method_exception_handling(self, mock_agent):
        """Test background loop handles method exceptions."""
        call_count = 0
        
        def exception_tick():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Test exception")
        
        mock_agent.exception_tick = exception_tick
        
        behavior = BackgroundLoopBehavior(
            mock_agent,
            {"interval_s": 0.05, "method": "exception_tick", "max_errors": 2, "auto_start": False}
        )
        await behavior.initialize()
        
        await behavior.start()
        await asyncio.sleep(0.2)
        await behavior.stop()
        
        # Should have handled exceptions without crashing
        assert call_count > 0  # Method was called at least once
        assert behavior._err_streak >= 1  # At least one error recorded


# ============================================================================
# Performance Tests
# ============================================================================

class TestBehaviorPerformance:
    """Performance tests for behaviors."""

    @pytest.mark.asyncio
    async def test_chat_history_ring_buffer_performance(self, mock_agent):
        """Test that ring buffer maintains performance with many messages."""
        behavior = ChatHistoryBehavior(mock_agent, {"limit": 100})
        await behavior.initialize()
        
        # Add 1000 messages
        start_time = time.perf_counter()
        for i in range(1000):
            behavior.add_user_message(f"Message {i}")
        elapsed = time.perf_counter() - start_time
        
        # Should complete quickly (< 1 second)
        assert elapsed < 1.0
        # Should only keep last 100
        assert len(behavior._chat_history) == 100

    @pytest.mark.asyncio
    async def test_dedup_cache_cleanup_performance(self, mock_agent):
        """Test that dedup cache cleanup is efficient."""
        behavior = DedupBehavior(mock_agent, {"ttl_s": 0.1})
        await behavior.initialize()
        
        # Add many keys
        for i in range(100):
            await behavior.mark_seen(f"key_{i}")
        
        # Wait for expiration
        await asyncio.sleep(0.15)
        
        # Check should trigger cleanup
        start_time = time.perf_counter()
        await behavior.seen_recently("key_0")
        elapsed = time.perf_counter() - start_time
        
        # Cleanup should be fast (< 0.1s)
        assert elapsed < 0.1
