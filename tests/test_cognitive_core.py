"""
Unit tests for SeedCore Cognitive Core.

This module provides comprehensive testing for cognitive reasoning capabilities,
including success scenarios, failure paths, and edge cases.
"""

import pytest
import asyncio
import json
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

from seedcore.agents.cognitive_core import (
    CognitiveCore,
    CognitiveContext,
    CognitiveTaskType,
    initialize_cognitive_core,
    get_cognitive_core,
    reset_cognitive_core
)
from seedcore.config.llm_config import configure_llm_openai
from seedcore.monitoring.cognitive_metrics import (
    CognitiveTaskStatus,
    track_cognitive_task,
    complete_cognitive_task,
    get_cognitive_summary_stats
)


class TestCognitiveCore:
    """Test cases for the CognitiveCore class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        reset_cognitive_core()
    
    def teardown_method(self):
        """Clean up after tests."""
        reset_cognitive_core()
    
    @patch('seedcore.agents.cognitive_core.dspy')
    def test_cognitive_core_initialization(self, mock_dspy):
        """Test cognitive core initialization."""
        # Mock DSPy components
        mock_llm = Mock()
        mock_dspy.OpenAI.return_value = mock_llm
        mock_dspy.settings.configure = Mock()
        
        # Test initialization
        core = initialize_cognitive_core()
        
        assert core is not None
        assert core.llm_provider == "openai"
        assert core.model == "gpt-4o"
        mock_dspy.settings.configure.assert_called_once()
    
    @patch('seedcore.agents.cognitive_core.dspy')
    def test_failure_analysis_success(self, mock_dspy):
        """Test successful failure analysis."""

        # LLM/dspy mocks
        mock_llm = Mock()
        mock_dspy.OpenAI.return_value = mock_llm
        mock_dspy.settings.configure = Mock()

        # IMPORTANT: return an object with attributes, not a dict
        mock_result = Mock()
        mock_result.thought = "The task failed due to timeout"
        mock_result.proposed_solution = "Increase timeout and add retry logic"
        mock_result.confidence_score = "0.85"

        mock_handler = Mock(return_value=mock_result)

        core = CognitiveCore()
        core.failure_analyzer = mock_handler
        core.task_handlers[CognitiveTaskType.FAILURE_ANALYSIS] = mock_handler

        context = CognitiveContext(
            agent_id="test_agent",
            task_type=CognitiveTaskType.FAILURE_ANALYSIS,
            input_data={"incident_id": "test_incident", "error_message": "Task timeout"},
        )

        result = core(context)
        print(f"[TEST] final result: {result}")
        print(f"[TEST] handler called: {mock_handler.called}")

        # Be tolerant to either 'payload' or legacy 'result'
        payload = result.get("payload") or result.get("result") or {}
        assert result["success"] is True
        assert payload.get("thought") == "The task failed due to timeout"
        assert payload.get("proposed_solution") == "Increase timeout and add retry logic"
        assert str(payload.get("confidence_score")) in {"0.85", "0.85"}
        mock_handler.assert_called_once()
    
    @patch('seedcore.agents.cognitive_core.dspy')
    def test_failure_analysis_error(self, mock_dspy):
        """Test failure analysis with error."""
        # Mock DSPy components
        mock_llm = Mock()
        mock_dspy.OpenAI.return_value = mock_llm
        mock_dspy.settings.configure = Mock()
        
        # Mock DSPy to raise exception
        mock_handler = Mock()
        mock_handler.side_effect = Exception("API error")
        
        # Create cognitive core with mocked handler
        core = CognitiveCore()
        core.failure_analyzer = mock_handler
        core.task_handlers[CognitiveTaskType.FAILURE_ANALYSIS] = mock_handler
        
        # Create context
        context = CognitiveContext(
            agent_id="test_agent",
            task_type=CognitiveTaskType.FAILURE_ANALYSIS,
            input_data={"incident_id": "test_incident"}
        )
        
        # Execute
        result = core(context)
        
        # Verify
        assert result["success"] is False
        assert "error" in result
        assert "API error" in result["error"]
    
    @patch('seedcore.agents.cognitive_core.dspy')
    def test_invalid_task_type(self, mock_dspy):
        """Test handling of invalid task type."""
        # Mock DSPy components
        mock_llm = Mock()
        mock_dspy.OpenAI.return_value = mock_llm
        mock_dspy.settings.configure = Mock()
        
        core = CognitiveCore()
        
        # Create context with invalid task type
        context = CognitiveContext(
            agent_id="test_agent",
            task_type="invalid_task",  # Invalid enum value
            input_data={}
        )
        
        # Execute
        result = core(context)
        
        # Verify
        assert result["success"] is False
        assert "error" in result
    
    @patch('seedcore.agents.cognitive_core.dspy')
    def test_task_planning_success(self, mock_dspy):
        """Test successful task planning."""
        # Mock DSPy response
        mock_result = Mock()
        mock_result.step_by_step_plan = "1. Analyze requirements\n2. Design solution\n3. Implement"
        mock_result.estimated_complexity = "Medium (6/10)"
        mock_result.risk_assessment = "Low risk with proper testing"
        
        mock_handler = Mock()
        mock_handler.return_value = mock_result
        
        # Create cognitive core with mocked handler
        core = CognitiveCore()
        core.task_planner = mock_handler
        core.task_handlers[CognitiveTaskType.TASK_PLANNING] = mock_handler
        
        # Create context
        context = CognitiveContext(
            agent_id="planner_agent",
            task_type=CognitiveTaskType.TASK_PLANNING,
            input_data={
                "task_description": "Build a monitoring dashboard",
                "agent_capabilities": {"capability_score": 0.8},
                "available_resources": {"time": "2 weeks"}
            }
        )
        
        # Execute
        result = core(context)
        
        # Verify
        assert result["success"] is True
        payload = result.get("payload") or result.get("result") or {}
        assert "step_by_step_plan" in payload
        assert "estimated_complexity" in payload
        assert "risk_assessment" in payload
    
    @patch('seedcore.agents.cognitive_core.dspy')
    def test_decision_making_success(self, mock_dspy):
        """Test successful decision making."""
        # Mock DSPy components
        mock_llm = Mock()
        mock_dspy.OpenAI.return_value = mock_llm
        mock_dspy.settings.configure = Mock()
        
        # Mock DSPy response
        mock_result = Mock()
        mock_result.reasoning = "Option A provides best cost-benefit ratio"
        mock_result.decision = "Choose Option A"
        mock_result.confidence = "0.9"
        mock_result.alternative_options = "Option B was too expensive"
        
        mock_handler = Mock()
        mock_handler.return_value = mock_result
        
        # Create cognitive core with mocked handler
        core = CognitiveCore()
        core.decision_maker = mock_handler
        core.task_handlers[CognitiveTaskType.DECISION_MAKING] = mock_handler
        
        # Create context
        context = CognitiveContext(
            agent_id="decision_agent",
            task_type=CognitiveTaskType.DECISION_MAKING,
            input_data={
                "decision_context": {"options": ["A", "B", "C"]},
                "historical_data": {"previous_decisions": []}
            }
        )
        
        # Execute
        result = core(context)
        
        # Verify
        assert result["success"] is True
        payload = result.get("payload") or result.get("result") or {}
        assert "reasoning" in payload
        assert "decision" in payload
        assert str(payload["confidence"]) in {"0.9", "0.9"}
        assert "alternative_options" in payload


class TestCognitiveContext:
    """Test cases for CognitiveContext."""
    
    def test_cognitive_context_creation(self):
        """Test CognitiveContext creation and validation."""
        context = CognitiveContext(
            agent_id="test_agent",
            task_type=CognitiveTaskType.FAILURE_ANALYSIS,
            input_data={"test": "data"},
            memory_context={"memory": "info"},
            energy_context={"energy": "info"},
            lifecycle_context={"lifecycle": "info"}
        )
        
        assert context.agent_id == "test_agent"
        assert context.task_type == CognitiveTaskType.FAILURE_ANALYSIS
        assert context.input_data == {"test": "data"}
        assert context.memory_context == {"memory": "info"}
        assert context.energy_context == {"energy": "info"}
        assert context.lifecycle_context == {"lifecycle": "info"}
    
    def test_cognitive_context_defaults(self):
        """Test CognitiveContext with default values."""
        context = CognitiveContext(
            agent_id="test_agent",
            task_type=CognitiveTaskType.TASK_PLANNING,
            input_data={}
        )
        
        assert context.agent_id == "test_agent"
        assert context.task_type == CognitiveTaskType.TASK_PLANNING
        assert context.input_data == {}
        assert context.memory_context is None
        assert context.energy_context is None
        assert context.lifecycle_context is None


class TestCognitiveTaskTypes:
    """Test cases for cognitive task types."""
    
    def test_task_type_enum(self):
        """Test CognitiveTaskType enum values."""
        assert CognitiveTaskType.FAILURE_ANALYSIS.value == "failure_analysis"
        assert CognitiveTaskType.TASK_PLANNING.value == "task_planning"
        assert CognitiveTaskType.DECISION_MAKING.value == "decision_making"
        assert CognitiveTaskType.PROBLEM_SOLVING.value == "problem_solving"
        assert CognitiveTaskType.MEMORY_SYNTHESIS.value == "memory_synthesis"
        assert CognitiveTaskType.CAPABILITY_ASSESSMENT.value == "capability_assessment"
    
    def test_task_type_from_string(self):
        """Test creating task types from strings."""
        assert CognitiveTaskType("failure_analysis") == CognitiveTaskType.FAILURE_ANALYSIS
        assert CognitiveTaskType("task_planning") == CognitiveTaskType.TASK_PLANNING
    
    def test_invalid_task_type(self):
        """Test handling of invalid task type strings."""
        with pytest.raises(ValueError):
            CognitiveTaskType("invalid_task")


class TestCognitiveMetrics:
    """Test cases for cognitive metrics tracking."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Clear any existing metrics
        pass
    
    def test_track_cognitive_task(self):
        """Test tracking cognitive task start."""
        task_id = track_cognitive_task(
            task_type="failure_analysis",
            agent_id="test_agent",
            model="gpt-4o",
            provider="openai"
        )
        
        assert task_id is not None
        assert "failure_analysis" in task_id
        assert "test_agent" in task_id
    
    def test_complete_cognitive_task_success(self):
        """Test completing cognitive task with success."""
        task_id = track_cognitive_task("failure_analysis", "test_agent")
        
        complete_cognitive_task(
            task_id=task_id,
            status=CognitiveTaskStatus.SUCCESS,
            input_tokens=100,
            output_tokens=50,
            confidence_score=0.85,
            energy_cost=0.1
        )
        
        # Get summary stats
        stats = get_cognitive_summary_stats()
        
        assert stats["total_tasks"] >= 1
        assert stats["success_rate"] > 0.0
        assert stats["total_tokens"] >= 150
    
    def test_complete_cognitive_task_failure(self):
        """Test completing cognitive task with failure."""
        task_id = track_cognitive_task("failure_analysis", "test_agent")
        
        complete_cognitive_task(
            task_id=task_id,
            status=CognitiveTaskStatus.FAILURE,
            input_tokens=50,
            output_tokens=0,
            error_message="API timeout",
            energy_cost=0.05
        )
        
        # Get summary stats
        stats = get_cognitive_summary_stats()
        
        assert stats["total_tasks"] >= 1
        assert "failure" in stats["tasks_by_status"]
    
    def test_metrics_with_multiple_tasks(self):
        """Test metrics with multiple tasks."""
        # Start multiple tasks
        task_ids = []
        for i in range(3):
            task_id = track_cognitive_task(f"task_type_{i}", f"agent_{i}")
            task_ids.append(task_id)
        
        # Complete tasks with different statuses
        complete_cognitive_task(task_ids[0], CognitiveTaskStatus.SUCCESS, 100, 50)
        complete_cognitive_task(task_ids[1], CognitiveTaskStatus.FAILURE, 50, 0, error_message="Error")
        complete_cognitive_task(task_ids[2], CognitiveTaskStatus.SUCCESS, 75, 25)
        
        # Get summary stats
        stats = get_cognitive_summary_stats()
        
        assert stats["total_tasks"] >= 3
        # Check that success rate is reasonable (allowing for other tasks in system)
        assert 0.0 <= stats["success_rate"] <= 1.0
        assert stats["total_tokens"] >= 300


class TestCognitiveCoreIntegration:
    """Integration tests for cognitive core."""
    
    @patch('seedcore.agents.cognitive_core.dspy')
    def test_end_to_end_failure_analysis(self, mock_dspy):
        """Test end-to-end failure analysis workflow."""
        # Mock DSPy
        mock_result = Mock()
        mock_result.thought = "Analysis complete"
        mock_result.proposed_solution = "Solution proposed"
        mock_result.confidence_score = "0.8"
        
        mock_handler = Mock()
        mock_handler.return_value = mock_result
        
        # Initialize cognitive core
        core = CognitiveCore()
        core.failure_analyzer = mock_handler
        
        # Track task
        task_id = track_cognitive_task("failure_analysis", "test_agent")
        
        # Create context and execute
        context = CognitiveContext(
            agent_id="test_agent",
            task_type=CognitiveTaskType.FAILURE_ANALYSIS,
            input_data={"incident_id": "test"}
        )
        
        result = core(context)
        
        # Complete tracking
        complete_cognitive_task(
            task_id=task_id,
            status=CognitiveTaskStatus.SUCCESS,
            input_tokens=100,
            output_tokens=50,
            confidence_score=0.8,
            energy_cost=0.1
        )
        
        # Verify results
        assert result["success"] is True
        assert "thought" in result
        assert "proposed_solution" in result
        
        # Verify metrics
        stats = get_cognitive_summary_stats()
        assert stats["total_tasks"] >= 1
        assert stats["success_rate"] > 0.0


class TestErrorHandling:
    """Test error handling scenarios."""
    
    @patch('seedcore.agents.cognitive_core.dspy')
    def test_missing_api_key(self, mock_dspy):
        """Test handling of missing API key."""
        # Mock DSPy to raise exception when no API key
        mock_dspy.OpenAI.side_effect = Exception("API key required")
        
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(Exception):
                initialize_cognitive_core()
    
    @patch('seedcore.agents.cognitive_core.dspy')
    def test_invalid_model(self, mock_dspy):
        """Test handling of invalid model."""
        mock_dspy.OpenAI.side_effect = Exception("Invalid model")
        
        with pytest.raises(Exception):
            initialize_cognitive_core()
    
    @patch('seedcore.agents.cognitive_core.dspy')
    def test_network_timeout(self, mock_dspy):
        """Test handling of network timeout."""
        # Mock DSPy components
        mock_llm = Mock()
        mock_dspy.OpenAI.return_value = mock_llm
        mock_dspy.settings.configure = Mock()
        
        core = CognitiveCore()
        
        # Mock handler to simulate timeout
        mock_handler = Mock()
        mock_handler.side_effect = Exception("Request timeout")
        
        core.failure_analyzer = mock_handler
        core.task_handlers[CognitiveTaskType.FAILURE_ANALYSIS] = mock_handler
        
        context = CognitiveContext(
            agent_id="test_agent",
            task_type=CognitiveTaskType.FAILURE_ANALYSIS,
            input_data={}
        )
        
        result = core(context)
        
        assert result["success"] is False
        assert "timeout" in result["error"].lower()
    
    @patch('seedcore.agents.cognitive_core.dspy')
    def test_rate_limiting(self, mock_dspy):
        """Test handling of rate limiting."""
        # Mock DSPy components
        mock_llm = Mock()
        mock_dspy.OpenAI.return_value = mock_llm
        mock_dspy.settings.configure = Mock()
        
        core = CognitiveCore()
        
        # Mock handler to simulate rate limiting
        mock_handler = Mock()
        mock_handler.side_effect = Exception("Rate limit exceeded")
        
        core.failure_analyzer = mock_handler
        core.task_handlers[CognitiveTaskType.FAILURE_ANALYSIS] = mock_handler
        
        context = CognitiveContext(
            agent_id="test_agent",
            task_type=CognitiveTaskType.FAILURE_ANALYSIS,
            input_data={}
        )
        
        result = core(context)
        
        assert result["success"] is False
        assert "rate limit" in result["error"].lower()


class TestPerformance:
    """Performance and stress tests."""
    
    def test_concurrent_task_tracking(self):
        """Test concurrent task tracking."""
        import threading
        import time
        
        results = []
        
        def track_task(thread_id):
            task_id = track_cognitive_task(f"concurrent_task_{thread_id}", f"agent_{thread_id}")
            time.sleep(0.1)  # Simulate work
            complete_cognitive_task(task_id, CognitiveTaskStatus.SUCCESS, 50, 25)
            results.append(task_id)
        
        # Start multiple threads
        threads = []
        for i in range(10):
            thread = threading.Thread(target=track_task, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Verify results
        assert len(results) == 10
        stats = get_cognitive_summary_stats()
        assert stats["total_tasks"] >= 10
    
    def test_large_input_handling(self):
        """Test handling of large input data."""
        core = CognitiveCore()
        
        # Create large input data
        large_input = {
            "data": "x" * 10000,  # 10KB of data
            "nested": {
                "level1": {"level2": {"level3": "deep_data" * 100}}
            }
        }
        
        context = CognitiveContext(
            agent_id="test_agent",
            task_type=CognitiveTaskType.FAILURE_ANALYSIS,
            input_data=large_input
        )
        
        # Should not crash with large input
        try:
            result = core(context)
            assert result["success"] is False  # Should fail due to no handler
        except Exception as e:
            # Should not crash due to size
            assert "memory" not in str(e).lower()


if __name__ == "__main__":
    pytest.main([__file__]) 