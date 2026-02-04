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

from seedcore.models.cognitive import DecisionKind
from seedcore.models.task_payload import TaskPayload
from seedcore.coordinator.core.execute import (
    execute_task,
    RouteConfig,
    ExecutionConfig,
)
from seedcore.coordinator.core.ocps_valve import NeuralCUSUMValve
from seedcore.coordinator.core.policies import SurpriseComputer


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
class TestExecuteTask:
    """Tests for execute_task function."""
    
    async def test_execute_task_fast_path(self):
        """Test execute_task for fast path decision."""
        # Create task payload with HIGH authority so coordinator can choose fast path
        # (LOW authority cannot force FAST - see _determine_decision_kind)
        task = TaskPayload(
            task_id="task-123",
            type="test",
            description="test task",
            params={
                "cognitive": {
                    "metadata": {"intent_class": {"authority": "HIGH"}},
                },
            },
        )
        
        # Mock surprise computer (decision_kind used by _evaluate_surprise_signals)
        surprise_computer = FakeSurpriseComputer(return_value={
            "S": 0.2,  # Low surprise -> fast path
            "x": [0.1, 0.1, 0.1, 0.1, 0.1, 0.1],
            "weights": [0.25, 0.20, 0.15, 0.20, 0.10, 0.10],
            "decision": "fast",
            "decision_kind": "fast",
            "ocps": {"S_t": 0.1, "h": 0.5, "flag_on": False},
        })

        # Create OCPS valve
        ocps_valve = NeuralCUSUMValve(
            expected_baseline=0.1,
            min_detectable_change=0.2,
            threshold=2.5,
            sigma=0.15,
        )

        # PKG must return non-empty result so we don't escalate to cognitive (empty PKG -> is_pkg_escalated)
        route_config = RouteConfig(
            surprise_computer=surprise_computer,
            ocps_valve=ocps_valve,
            tau_fast_exit=0.38,
            tau_plan_exit=0.57,
            evaluate_pkg_func=AsyncMock(return_value={
                "steps": [{"task": {"type": "test", "id": "step-1"}}],
            }),
            ood_to01=lambda x: x,
            pkg_timeout_s=2,
        )
        
        # Mock execution config
        organism_execute = AsyncMock(return_value={
            "success": True,
            "result": {"output": "test result"},
        })

        execution_config = ExecutionConfig(
            compute_drift_score=AsyncMock(return_value=0.1),
            organism_execute=organism_execute,
            graph_task_repo=Mock(),
            ml_client=Mock(),
            metrics=Mock(),
            cid="test-cid",
            normalize_domain=lambda x: x.lower() if x else None,
        )
        
        # Call execute_task
        result = await execute_task(
            task=task,
            route_config=route_config,
            execution_config=execution_config,
        )
        
        assert result["decision_kind"] == DecisionKind.FAST_PATH.value
        # Fast path should delegate to organism_execute
        organism_execute.assert_called()
    
    async def test_execute_task_cognitive_path(self):
        """Test execute_task for cognitive path decision."""
        task = TaskPayload(
            task_id="task-123",
            type="test",
            description="test task",
        )
        
        surprise_computer = FakeSurpriseComputer(return_value={
            "S": 0.5,  # Medium surprise -> planner
            "x": [0.2, 0.2, 0.2, 0.2, 0.2, 0.2],
            "weights": [0.25, 0.20, 0.15, 0.20, 0.10, 0.10],
            "decision": "planner",
            "ocps": {"S_t": 0.3, "h": 0.5, "flag_on": False}
        })

        # Create OCPS valve that will breach to route to cognitive path
        ocps_valve = NeuralCUSUMValve(
            expected_baseline=0.1,
            min_detectable_change=0.2,
            threshold=0.5,  # Lower threshold to trigger breach
            sigma=0.15,
        )
        # Pre-accumulate drift to trigger breach
        ocps_valve.S = 0.4

        route_config = RouteConfig(
            surprise_computer=surprise_computer,
            ocps_valve=ocps_valve,
            tau_fast_exit=0.38,
            tau_plan_exit=0.57,
            evaluate_pkg_func=AsyncMock(return_value={
                "steps": [{"task": {"type": "test", "id": "step-1"}}],
                "metadata": {"evaluated": True},
            }),
            ood_to01=lambda x: x,
            pkg_timeout_s=2,
        )

        organism_execute = AsyncMock(return_value={
            "success": True,
            "result": {"output": "planner result"},
        })

        cognitive_client = Mock()
        cognitive_client.execute_async = AsyncMock(return_value={
            "success": True,
            "result": {
                "solution_steps": [{"task": {"type": "test"}}],
                "proto_plan": {"steps": [{"task": {"type": "test"}}]},
            },
        })

        execution_config = ExecutionConfig(
            compute_drift_score=AsyncMock(return_value=0.5),  # Higher drift to trigger breach
            organism_execute=organism_execute,
            graph_task_repo=Mock(),
            ml_client=Mock(),
            metrics=Mock(),
            cid="test-cid",
            normalize_domain=lambda x: x.lower() if x else None,
            cognitive_client=cognitive_client,
        )
        
        result = await execute_task(
            task=task,
            route_config=route_config,
            execution_config=execution_config,
        )
        
        assert result["decision_kind"] == DecisionKind.COGNITIVE.value
    
    async def test_execute_task_handles_escalated_path(self):
        """Test execute_task handles escalated path when OCPS is breached."""
        task = TaskPayload(
            task_id="task-123",
            type="test",
            description="test task",
        )
        
        surprise_computer = FakeSurpriseComputer(return_value={
            "S": 0.95,
            "x": [0.9, 0.9, 0.9, 0.9, 0.9, 0.9],
            "weights": [0.25, 0.20, 0.15, 0.20, 0.10, 0.10],
            "decision": "unknown",
            "ocps": {"S_t": 0.9, "h": 0.8, "flag_on": True},
        })

        # Create OCPS valve that will breach
        ocps_valve = NeuralCUSUMValve(
            expected_baseline=0.1,
            min_detectable_change=0.2,
            threshold=0.5,  # Lower threshold to trigger breach
            sigma=0.15,
        )
        # Pre-accumulate drift to trigger breach
        ocps_valve.S = 0.4

        route_config = RouteConfig(
            surprise_computer=surprise_computer,
            ocps_valve=ocps_valve,
            tau_fast_exit=0.38,
            tau_plan_exit=0.57,
            evaluate_pkg_func=AsyncMock(side_effect=Exception("PKG error")),
            ood_to01=lambda x: x,
            pkg_timeout_s=2,
        )

        # Mock cognitive client for escalated path - must return valid planner output
        # (_validate_planner_output requires DAG or solution_steps with routing hints)
        cognitive_client = Mock()
        cognitive_client.execute_async = AsyncMock(return_value={
            "success": True,
            "result": {
                "solution_steps": [
                    {
                        "id": "step-1",
                        "type": "action",
                        "params": {"routing": {"specialization": "Generalist"}},
                        "depends_on": [],
                    }
                ],
                "proto_plan": {},
            },
        })

        execution_config = ExecutionConfig(
            compute_drift_score=AsyncMock(return_value=0.8),  # High drift to trigger breach
            organism_execute=AsyncMock(return_value={"success": True}),
            graph_task_repo=Mock(),
            ml_client=Mock(),
            metrics=Mock(),
            cid="test-cid",
            normalize_domain=lambda x: x.lower() if x else None,
            cognitive_client=cognitive_client,
        )

        result = await execute_task(
            task=task,
            route_config=route_config,
            execution_config=execution_config,
        )
        
        # When OCPS is breached, should route to cognitive path
        assert result["decision_kind"] == DecisionKind.COGNITIVE.value
