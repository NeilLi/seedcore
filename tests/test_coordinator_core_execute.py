"""
Unit tests for coordinator.core.execute module.

Tests execution orchestration for fast path, planner path, and HGNN path.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
from dataclasses import dataclass
from typing import Any, Dict, Optional
from seedcore.coordinator.core.execute import (
    route_and_execute,
    RouteConfig,
    ExecutionConfig,
    HGNNConfig,
)


# Mock classes for testing
@dataclass
class MockRouteConfig:
    surprise_computer: Any
    tau_fast_exit: float
    tau_plan_exit: float
    evaluate_pkg_func: Any
    ood_to01: Any
    pkg_timeout_s: int


@dataclass
class MockExecutionConfig:
    normalize_task_dict: Any
    extract_agent_id: Any
    compute_drift_score: Any
    organism_execute: Any
    graph_task_repo: Any
    ml_client: Any
    predicate_router: Any
    metrics: Any
    cid: str
    resolve_route_cached: Any
    static_route_fallback: Any
    normalize_type: Any
    normalize_domain: Any


@dataclass
class MockHGNNConfig:
    hgnn_decompose: Any
    bulk_resolve_func: Any
    persist_plan_func: Any


@pytest.mark.asyncio
class TestRouteAndExecute:
    """Tests for route_and_execute function."""
    
    async def test_route_and_execute_fast_path(self):
        """Test route and execute for fast path decision."""
        # Mock task
        task = {"id": "task-123", "type": "test", "description": "test task"}
        
        # Mock surprise computer
        surprise_computer = Mock()
        surprise_computer.compute = Mock(return_value={
            "S": 0.2,  # Low surprise -> fast path
            "x": [0.1, 0.1, 0.1, 0.1, 0.1, 0.1],
            "weights": [0.25, 0.20, 0.15, 0.20, 0.10, 0.10],
            "decision": "fast",
            "ocps": {"S_t": 0.1, "h": 0.5, "flag_on": False}
        })
        
        # Mock route config
        route_config = MockRouteConfig(
            surprise_computer=surprise_computer,
            tau_fast_exit=0.38,
            tau_plan_exit=0.57,
            evaluate_pkg_func=AsyncMock(return_value={"tasks": [], "edges": []}),
            ood_to01=lambda x: x,
            pkg_timeout_s=2
        )
        
        # Mock execution config
        organism_execute = AsyncMock(return_value={
            "success": True,
            "result": {"output": "test result"}
        })
        
        execution_config = MockExecutionConfig(
            normalize_task_dict=lambda t: (t.get("id"), t),
            extract_agent_id=lambda t: None,
            compute_drift_score=AsyncMock(return_value=0.1),
            organism_execute=organism_execute,
            graph_task_repo=None,
            ml_client=Mock(),
            predicate_router=Mock(),
            metrics=Mock(),
            cid="test-cid",
            resolve_route_cached=AsyncMock(return_value="organ-123"),
            static_route_fallback=lambda t, d: "organ-123",
            normalize_type=lambda x: x.lower() if x else "unknown",
            normalize_domain=lambda x: x.lower() if x else None
        )
        
        # Call route_and_execute
        result = await route_and_execute(
            task=task,
            fact_dao=None,
            eventizer_helper=None,
            routing_config=route_config,
            execution_config=execution_config,
            hgnn_config=None
        )
        
        # Verify result structure
        assert "success" in result or "kind" in result
        organism_execute.assert_called_once()
    
    async def test_route_and_execute_planner_path(self):
        """Test route and execute for planner path decision."""
        task = {"id": "task-123", "type": "test", "description": "test task"}
        
        surprise_computer = Mock()
        surprise_computer.compute = Mock(return_value={
            "S": 0.5,  # Medium surprise -> planner
            "x": [0.2, 0.2, 0.2, 0.2, 0.2, 0.2],
            "weights": [0.25, 0.20, 0.15, 0.20, 0.10, 0.10],
            "decision": "planner",
            "ocps": {"S_t": 0.3, "h": 0.5, "flag_on": False}
        })
        
        route_config = MockRouteConfig(
            surprise_computer=surprise_computer,
            tau_fast_exit=0.38,
            tau_plan_exit=0.57,
            evaluate_pkg_func=AsyncMock(return_value={
                "tasks": [{"organ_id": "organ-1", "task": {"type": "test"}}],
                "edges": []
            }),
            ood_to01=lambda x: x,
            pkg_timeout_s=2
        )
        
        organism_execute = AsyncMock(return_value={
            "success": True,
            "result": {"output": "planner result"}
        })
        
        execution_config = MockExecutionConfig(
            normalize_task_dict=lambda t: (t.get("id"), t),
            extract_agent_id=lambda t: None,
            compute_drift_score=AsyncMock(return_value=0.3),
            organism_execute=organism_execute,
            graph_task_repo=None,
            ml_client=Mock(),
            predicate_router=Mock(),
            metrics=Mock(),
            cid="test-cid",
            resolve_route_cached=AsyncMock(return_value="organ-123"),
            static_route_fallback=lambda t, d: "organ-123",
            normalize_type=lambda x: x.lower() if x else "unknown",
            normalize_domain=lambda x: x.lower() if x else None
        )
        
        result = await route_and_execute(
            task=task,
            fact_dao=None,
            eventizer_helper=None,
            routing_config=route_config,
            execution_config=execution_config,
            hgnn_config=None
        )
        
        assert "success" in result or "kind" in result
    
    async def test_route_and_execute_hgnn_path(self):
        """Test route and execute for HGNN path decision."""
        task = {"id": "task-123", "type": "test", "description": "test task"}
        
        surprise_computer = Mock()
        surprise_computer.compute = Mock(return_value={
            "S": 0.8,  # High surprise -> HGNN
            "x": [0.4, 0.4, 0.4, 0.4, 0.4, 0.4],
            "weights": [0.25, 0.20, 0.15, 0.20, 0.10, 0.10],
            "decision": "hgnn",
            "ocps": {"S_t": 0.6, "h": 0.5, "flag_on": True}
        })
        
        route_config = MockRouteConfig(
            surprise_computer=surprise_computer,
            tau_fast_exit=0.38,
            tau_plan_exit=0.57,
            evaluate_pkg_func=AsyncMock(return_value={"tasks": [], "edges": []}),
            ood_to01=lambda x: x,
            pkg_timeout_s=2
        )
        
        hgnn_decompose = AsyncMock(return_value=[
            {"organ_id": "organ-1", "task": {"type": "test1"}},
            {"organ_id": "organ-2", "task": {"type": "test2"}}
        ])
        
        bulk_resolve_func = AsyncMock(return_value={0: "organ-1", 1: "organ-2"})
        
        persist_plan_func = AsyncMock()
        
        hgnn_config = MockHGNNConfig(
            hgnn_decompose=hgnn_decompose,
            bulk_resolve_func=bulk_resolve_func,
            persist_plan_func=persist_plan_func
        )
        
        organism_execute = AsyncMock(return_value={
            "success": True,
            "result": {"output": "hgnn result"}
        })
        
        execution_config = MockExecutionConfig(
            normalize_task_dict=lambda t: (t.get("id"), t),
            extract_agent_id=lambda t: None,
            compute_drift_score=AsyncMock(return_value=0.6),
            organism_execute=organism_execute,
            graph_task_repo=None,
            ml_client=Mock(),
            predicate_router=Mock(),
            metrics=Mock(),
            cid="test-cid",
            resolve_route_cached=AsyncMock(return_value="organ-123"),
            static_route_fallback=lambda t, d: "organ-123",
            normalize_type=lambda x: x.lower() if x else "unknown",
            normalize_domain=lambda x: x.lower() if x else None
        )
        
        result = await route_and_execute(
            task=task,
            fact_dao=None,
            eventizer_helper=None,
            routing_config=route_config,
            execution_config=execution_config,
            hgnn_config=hgnn_config
        )
        
        assert "success" in result or "kind" in result
        hgnn_decompose.assert_called_once()
        bulk_resolve_func.assert_called_once()
    
    async def test_route_and_execute_error_handling(self):
        """Test route and execute error handling."""
        task = {"id": "task-123", "type": "test"}
        
        surprise_computer = Mock()
        surprise_computer.compute = Mock(side_effect=Exception("Surprise computation error"))
        
        route_config = MockRouteConfig(
            surprise_computer=surprise_computer,
            tau_fast_exit=0.38,
            tau_plan_exit=0.57,
            evaluate_pkg_func=AsyncMock(return_value={"tasks": [], "edges": []}),
            ood_to01=lambda x: x,
            pkg_timeout_s=2
        )
        
        execution_config = MockExecutionConfig(
            normalize_task_dict=lambda t: (t.get("id"), t),
            extract_agent_id=lambda t: None,
            compute_drift_score=AsyncMock(return_value=0.1),
            organism_execute=AsyncMock(return_value={"success": True}),
            graph_task_repo=None,
            ml_client=Mock(),
            predicate_router=Mock(),
            metrics=Mock(),
            cid="test-cid",
            resolve_route_cached=AsyncMock(return_value="organ-123"),
            static_route_fallback=lambda t, d: "organ-123",
            normalize_type=lambda x: x.lower() if x else "unknown",
            normalize_domain=lambda x: x.lower() if x else None
        )
        
        result = await route_and_execute(
            task=task,
            fact_dao=None,
            eventizer_helper=None,
            routing_config=route_config,
            execution_config=execution_config,
            hgnn_config=None
        )
        
        # Should return error result
        assert "error" in result or "kind" in result

