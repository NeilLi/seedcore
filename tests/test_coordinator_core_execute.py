"""
Unit tests for coordinator.core.execute module.

Tests execution orchestration for fast path, planner path, and HGNN path.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies

import pytest
from unittest.mock import Mock, AsyncMock
from typing import Any, Optional

from seedcore.models.result_schema import ResultKind
from seedcore.coordinator.core.execute import (
    route_and_execute,
    RouteConfig,
    ExecutionConfig,
    HGNNConfig,
)


class FakeSurpriseComputer:
    """Lightweight stub mimicking SurpriseComputer interface."""

    def __init__(
        self,
        *,
        return_value: dict[str, Any] | None = None,
        side_effect: Optional[Exception] = None,
        tau_fast: float = 0.35,
        tau_plan: float = 0.6,
        w_hat: Optional[list[float]] = None,
    ) -> None:
        self._return_value = return_value or {}
        self._side_effect = side_effect
        self.tau_fast = tau_fast
        self.tau_plan = tau_plan
        self.w_hat = w_hat or [0.25, 0.20, 0.15, 0.20, 0.10, 0.10]
        self.last_signals: Optional[dict[str, Any]] = None

    def compute(self, signals: dict[str, Any]) -> dict[str, Any]:
        self.last_signals = signals
        if self._side_effect:
            raise self._side_effect
        return self._return_value


@pytest.mark.asyncio
class TestRouteAndExecute:
    """Tests for route_and_execute function."""
    
    async def test_route_and_execute_fast_path(self):
        """Test route and execute for fast path decision."""
        # Mock task
        task = {"id": "task-123", "type": "test", "description": "test task"}
        
        # Mock surprise computer
        surprise_computer = FakeSurpriseComputer(return_value={
            "S": 0.2,  # Low surprise -> fast path
            "x": [0.1, 0.1, 0.1, 0.1, 0.1, 0.1],
            "weights": [0.25, 0.20, 0.15, 0.20, 0.10, 0.10],
            "decision": "fast",
            "ocps": {"S_t": 0.1, "h": 0.5, "flag_on": False},
        })

        route_config = RouteConfig(
            surprise_computer=surprise_computer,
            tau_fast_exit=0.38,
            tau_plan_exit=0.57,
            evaluate_pkg_func=AsyncMock(return_value={"tasks": [], "edges": []}),
            ood_to01=lambda x: x,
            pkg_timeout_s=2,
        )
        
        # Mock execution config
        organism_execute = AsyncMock(return_value={
            "success": True,
            "result": {"output": "test result"},
        })

        execution_config = ExecutionConfig(
            normalize_task_dict=lambda t: (dict(t), {"task_id": t.get("id")}),
            extract_agent_id=lambda t: None,
            compute_drift_score=AsyncMock(return_value=0.1),
            organism_execute=organism_execute,
            graph_task_repo=Mock(),
            ml_client=Mock(),
            predicate_router=Mock(),
            metrics=Mock(),
            cid="test-cid",
            resolve_route_cached=AsyncMock(return_value="organ-123"),
            static_route_fallback=lambda t, d: "organ-123",
            normalize_type=lambda x: x.lower() if x else "unknown",
            normalize_domain=lambda x: x.lower() if x else None,
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
        
        assert result["kind"] == ResultKind.FAST_PATH
        assert result["payload"]["metadata"]["decision"] == "fast"
        organism_execute.assert_not_called()
    
    async def test_route_and_execute_planner_path(self):
        """Test route and execute for planner path decision."""
        task = {"id": "task-123", "type": "test", "description": "test task"}
        
        surprise_computer = FakeSurpriseComputer(return_value={
            "S": 0.5,  # Medium surprise -> planner
            "x": [0.2, 0.2, 0.2, 0.2, 0.2, 0.2],
            "weights": [0.25, 0.20, 0.15, 0.20, 0.10, 0.10],
            "decision": "planner",
            "ocps": {"S_t": 0.3, "h": 0.5, "flag_on": False}
        })

        route_config = RouteConfig(
            surprise_computer=surprise_computer,
            tau_fast_exit=0.38,
            tau_plan_exit=0.57,
            evaluate_pkg_func=AsyncMock(return_value={
                "tasks": [{"organ_id": "organ-1", "task": {"type": "test"}}],
                "edges": [],
            }),
            ood_to01=lambda x: x,
            pkg_timeout_s=2,
        )

        organism_execute = AsyncMock(return_value={
            "success": True,
            "result": {"output": "planner result"},
        })

        execution_config = ExecutionConfig(
            normalize_task_dict=lambda t: (dict(t), {"task_id": t.get("id")}),
            extract_agent_id=lambda t: None,
            compute_drift_score=AsyncMock(return_value=0.3),
            organism_execute=organism_execute,
            graph_task_repo=Mock(),
            ml_client=Mock(),
            predicate_router=Mock(),
            metrics=Mock(),
            cid="test-cid",
            resolve_route_cached=AsyncMock(return_value="organ-123"),
            static_route_fallback=lambda t, d: "organ-123",
            normalize_type=lambda x: x.lower() if x else "unknown",
            normalize_domain=lambda x: x.lower() if x else None,
        )
        
        result = await route_and_execute(
            task=task,
            fact_dao=None,
            eventizer_helper=None,
            routing_config=route_config,
            execution_config=execution_config,
            hgnn_config=None
        )
        
        assert result["kind"] == ResultKind.COGNITIVE
        assert result["payload"]["result"]["proto_plan"]
    
    async def test_route_and_execute_hgnn_path(self):
        """Test route and execute for HGNN path decision."""
        task = {"id": "task-123", "type": "test", "description": "test task"}
        
        surprise_computer = FakeSurpriseComputer(return_value={
            "S": 0.8,  # High surprise -> HGNN
            "x": [0.4, 0.4, 0.4, 0.4, 0.4, 0.4],
            "weights": [0.25, 0.20, 0.15, 0.20, 0.10, 0.10],
            "decision": "hgnn",
            "ocps": {"S_t": 0.6, "h": 0.5, "flag_on": True}
        })

        route_config = RouteConfig(
            surprise_computer=surprise_computer,
            tau_fast_exit=0.38,
            tau_plan_exit=0.57,
            evaluate_pkg_func=AsyncMock(return_value={"tasks": [], "edges": []}),
            ood_to01=lambda x: x,
            pkg_timeout_s=2,
        )
        
        hgnn_decompose = AsyncMock(return_value=[
            {"organ_id": "organ-1", "task": {"type": "test1"}},
            {"organ_id": "organ-2", "task": {"type": "test2"}}
        ])
        
        bulk_resolve_func = AsyncMock(return_value={0: "organ-1", 1: "organ-2"})
        
        persist_plan_func = AsyncMock()
        
        hgnn_config = HGNNConfig(
            hgnn_decompose=hgnn_decompose,
            bulk_resolve_func=bulk_resolve_func,
            persist_plan_func=persist_plan_func,
        )
        
        organism_execute = AsyncMock(return_value={
            "success": True,
            "result": {"output": "hgnn result"},
        })

        execution_config = ExecutionConfig(
            normalize_task_dict=lambda t: (dict(t), {"task_id": t.get("id")}),
            extract_agent_id=lambda t: None,
            compute_drift_score=AsyncMock(return_value=0.6),
            organism_execute=organism_execute,
            graph_task_repo=Mock(),
            ml_client=Mock(),
            predicate_router=Mock(),
            metrics=Mock(),
            cid="test-cid",
            resolve_route_cached=AsyncMock(return_value="organ-123"),
            static_route_fallback=lambda t, d: "organ-123",
            normalize_type=lambda x: x.lower() if x else "unknown",
            normalize_domain=lambda x: x.lower() if x else None,
        )
        
        result = await route_and_execute(
            task=task,
            fact_dao=None,
            eventizer_helper=None,
            routing_config=route_config,
            execution_config=execution_config,
            hgnn_config=hgnn_config
        )
        
        assert result["path"] == "hgnn"
        assert organism_execute.await_count == 2
        hgnn_decompose.assert_awaited_once()
        bulk_resolve_func.assert_awaited_once()
    
    async def test_route_and_execute_handles_missing_hgnn_config(self):
        """Ensure HGNN decision returns metadata when config is unavailable."""
        task = {"id": "task-123", "type": "test"}
        
        surprise_computer = FakeSurpriseComputer(return_value={
            "S": 0.95,
            "x": [0.9, 0.9, 0.9, 0.9, 0.9, 0.9],
            "weights": [0.25, 0.20, 0.15, 0.20, 0.10, 0.10],
            "decision": "unknown",
            "ocps": {"S_t": 0.9, "h": 0.8, "flag_on": True},
        })

        route_config = RouteConfig(
            surprise_computer=surprise_computer,
            tau_fast_exit=0.38,
            tau_plan_exit=0.57,
            evaluate_pkg_func=AsyncMock(side_effect=Exception("PKG error")),
            ood_to01=lambda x: x,
            pkg_timeout_s=2,
        )

        execution_config = ExecutionConfig(
            normalize_task_dict=lambda t: (dict(t), {"task_id": t.get("id")}),
            extract_agent_id=lambda t: None,
            compute_drift_score=AsyncMock(return_value=0.1),
            organism_execute=AsyncMock(return_value={"success": True}),
            graph_task_repo=Mock(),
            ml_client=Mock(),
            predicate_router=Mock(),
            metrics=Mock(),
            cid="test-cid",
            resolve_route_cached=AsyncMock(return_value="organ-123"),
            static_route_fallback=lambda t, d: "organ-123",
            normalize_type=lambda x: x.lower() if x else "unknown",
            normalize_domain=lambda x: x.lower() if x else None,
        )

        result = await route_and_execute(
            task=task,
            fact_dao=None,
            eventizer_helper=None,
            routing_config=route_config,
            execution_config=execution_config,
            hgnn_config=None
        )
        
        assert result["kind"] == ResultKind.ESCALATED
        assert result["payload"]["metadata"]["decision"] == "hgnn"

