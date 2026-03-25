from __future__ import annotations

import pytest

from seedcore.hal.robot_sim.actuator.actuator_adapter import ActuatorAdapter
from seedcore.hal.robot_sim.actuator.execution_registry import ExecutionRegistry
from seedcore.hal.robot_sim.behaviors.base_behavior import RobotBehavior


class DummyRuntime:
    def step(self, steps: int = 0) -> None:
        return None


class DummyRobot:
    def get_pose(self) -> dict[str, object]:
        return {"position": [0.0, 0.0, 0.5], "orientation": [0.0, 0.0, 0.0, 1.0]}


class DummyBehavior(RobotBehavior):
    name = "move_forward"

    def execute(self, robot, runtime, **params):
        runtime.step(params.get("steps", 1))
        return {
            "status": "success",
            "distance": params.get("distance", 1),
            "pose": robot.get_pose(),
        }


def _build_adapter() -> ActuatorAdapter:
    registry = ExecutionRegistry()
    registry.register(DummyBehavior())
    return ActuatorAdapter(runtime=DummyRuntime(), robot=DummyRobot(), registry=registry)


def test_execute_blocks_without_token() -> None:
    adapter = _build_adapter()

    with pytest.raises(PermissionError, match="invalid ExecutionToken"):
        adapter.execute(None, "move_forward", {"distance": 1})


def test_execute_blocks_inactive_token() -> None:
    adapter = _build_adapter()
    token = {"id": ""}

    with pytest.raises(PermissionError, match="invalid ExecutionToken"):
        adapter.execute(token, "move_forward", {"distance": 1})


def test_execute_blocks_unknown_behavior() -> None:
    adapter = _build_adapter()
    token = {"id": "tok-2"}

    with pytest.raises(ValueError, match="Unknown behavior"):
        adapter.execute(token, "does_not_exist", {})


def test_execute_returns_evidence_envelope() -> None:
    adapter = _build_adapter()
    token = {"token_id": "tok-3"}

    envelope = adapter.execute(token, "move_forward", {"distance": 2})

    assert envelope["token_id"] == "tok-3"
    assert envelope["behavior"] == "move_forward"
    assert envelope["result"]["status"] == "success"
    assert isinstance(envelope["result_hash"], str)
    assert len(envelope["result_hash"]) == 64
