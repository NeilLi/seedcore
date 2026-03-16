"""
Robot Simulation Execution Driver
================================
HAL-compatible driver backed by the extensible robot_sim execution framework.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from ..interfaces import BaseRobotDriver, ProprioceptionState, RobotCapabilities, RobotState
from ..robot_sim.actuator.actuator_adapter import ActuatorAdapter
from ..robot_sim.actuator.execution_registry import ExecutionRegistry
from ..robot_sim.governance.execution_token import ExecutionToken as SimExecutionToken
from ..robot_sim.simulator.robot_model import RobotModel

logger = logging.getLogger(__name__)


class _InMemoryRuntime:
    """Fallback runtime when PyBullet is unavailable or disabled."""

    def __init__(self):
        self._robot_counter = 0
        self._poses: Dict[int, Dict[str, Any]] = {}

    def load_urdf(self, urdf: str, position: list[float]) -> int:
        self._robot_counter += 1
        robot_id = self._robot_counter
        self._poses[robot_id] = {
            "position": list(position),
            "orientation": [0.0, 0.0, 0.0, 1.0],
            "urdf": urdf,
        }
        return robot_id

    def get_base_pose(self, robot_id: int) -> dict[str, Any]:
        state = self._poses.get(robot_id, {})
        return {
            "position": list(state.get("position", [0.0, 0.0, 0.5])),
            "orientation": list(state.get("orientation", [0.0, 0.0, 0.0, 1.0])),
        }

    def step(self, steps: int = 240) -> None:
        return None

    def shutdown(self) -> None:
        self._poses.clear()


class RobotSimExecutionDriver(BaseRobotDriver):
    """HAL BaseRobotDriver implementation for pluggable robot_sim behaviors."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._runtime: Any = None
        self._robot: Optional[RobotModel] = None
        self._registry = ExecutionRegistry()
        self._adapter: Optional[ActuatorAdapter] = None
        self._last_execution: Dict[str, Any] = {}
        self._endpoint_id = str((self.config or {}).get("endpoint_id") or "robot_sim://pybullet_r2d2_01")
        self._current_state: Dict[str, Any] = {
            "head": {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "pitch": 0.0, "roll": 0.0},
            "antennas": [0.0, 0.0],
            "body_yaw": 0.0,
        }

    def _initialize_capabilities(self) -> RobotCapabilities:
        return RobotCapabilities(
            has_arms=False,
            has_head=True,
            has_base=True,
            has_camera=False,
            has_microphone=False,
            supported_pose_types=["head", "antennas", "body", "behavior"],
        )

    def connect(self) -> bool:
        runtime_mode = str((self.config or {}).get("runtime") or "in_memory").strip().lower()
        if runtime_mode == "pybullet":
            try:
                from ..robot_sim.simulator.pybullet_runtime import PyBulletRuntime

                self._runtime = PyBulletRuntime(gui=bool((self.config or {}).get("gui", False)))
            except Exception as exc:
                logger.warning("Falling back to in-memory robot_sim runtime: %s", exc)
                self._runtime = _InMemoryRuntime()
        else:
            self._runtime = _InMemoryRuntime()

        self._robot = RobotModel(
            runtime=self._runtime,
            urdf=str((self.config or {}).get("urdf") or "r2d2.urdf"),
            position=(self.config or {}).get("position") or [0.0, 0.0, 0.5],
        )
        self._registry.auto_register_from_behaviors()
        self._adapter = ActuatorAdapter(
            runtime=self._runtime,
            robot=self._robot,
            registry=self._registry,
            endpoint_id=self._endpoint_id,
        )
        self._state = RobotState.CONNECTED
        return True

    def disconnect(self) -> None:
        if self._runtime is not None:
            try:
                self._runtime.shutdown()
            except Exception as exc:
                logger.warning("robot_sim runtime shutdown error: %s", exc)
        self._runtime = None
        self._robot = None
        self._adapter = None
        self._state = RobotState.DISCONNECTED

    def emergency_stop(self) -> None:
        self._state = RobotState.EMERGENCY_STOP

    def get_current_pose(self, pose_type: str = "head") -> Dict[str, Any]:
        if pose_type == "head":
            return dict(self._current_state.get("head", {}))
        if pose_type == "antennas":
            antennas = self._current_state.get("antennas", [0.0, 0.0])
            return {"left": float(antennas[0]), "right": float(antennas[1])}
        if pose_type in {"body", "body_yaw"}:
            return {"yaw": float(self._current_state.get("body_yaw", 0.0))}
        return {"pose": self._robot.get_pose() if self._robot else {}}

    def move_instant(self, target: Dict[str, Any], pose_type: str = "head", **kwargs) -> None:
        self._apply_target_state(target)
        self._state = RobotState.CONNECTED

    def move_smooth(
        self,
        target: Dict[str, Any],
        duration: Optional[float] = None,
        pose_type: str = "head",
        method: str = "minjerk",
        **kwargs,
    ) -> bool:
        self._apply_target_state(target)
        if self._runtime is not None:
            self._runtime.step(int(max(1, (duration or 0.2) * 120)))
        self._state = RobotState.CONNECTED
        return True

    def move_to_pose(
        self,
        pose: Dict[str, Any],
        pose_type: str = "head",
        duration: Optional[float] = None,
        **kwargs,
    ) -> bool:
        return self.move_smooth(pose, duration=duration, pose_type=pose_type, **kwargs)

    def move_joints(
        self,
        joints: List[float],
        arm_id: Optional[str] = None,
        duration: Optional[float] = None,
        **kwargs,
    ) -> bool:
        raise NotImplementedError("robot_sim execution driver does not expose articulated arm joints")

    def is_moving(self) -> bool:
        return self._state == RobotState.MOVING

    def wait_for_motion_complete(self, timeout: Optional[float] = None) -> bool:
        return True

    def get_latest_frame(self) -> Optional[np.ndarray]:
        return None

    def play_audio(self, samples: np.ndarray, samplerate: int = 44100, **kwargs) -> None:
        return None

    def get_proprioception(self) -> ProprioceptionState:
        return ProprioceptionState(
            joint_positions={},
            ee_pose={},
            imu_data={},
            is_moving=self.is_moving(),
            timestamp=datetime.now(timezone.utc).timestamp(),
        )

    def execute_behavior(
        self,
        *,
        behavior_name: str,
        behavior_params: Optional[Dict[str, Any]] = None,
        execution_token: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if self._adapter is None:
            raise RuntimeError("robot_sim driver is not connected")
        if not isinstance(execution_token, dict):
            raise PermissionError("Execution blocked: invalid ExecutionToken")

        token = self._to_sim_token(execution_token)
        self._state = RobotState.MOVING
        envelope = self._adapter.execute(token, behavior_name, behavior_params or {})
        self._state = RobotState.CONNECTED
        self._last_execution = envelope

        behavior_target = (behavior_params or {}).get("target")
        if isinstance(behavior_target, dict):
            self._apply_target_state(behavior_target)
        return envelope

    def get_state(self) -> Dict[str, Any]:
        return {
            "head": dict(self._current_state.get("head", {})),
            "antennas": list(self._current_state.get("antennas", [0.0, 0.0])),
            "body_yaw": float(self._current_state.get("body_yaw", 0.0)),
            "last_execution": self._last_execution,
        }

    def _apply_target_state(self, target: Dict[str, Any]) -> None:
        if not isinstance(target, dict):
            return
        if isinstance(target.get("head"), dict):
            self._current_state["head"].update(target["head"])
        if isinstance(target.get("antennas"), list) and len(target["antennas"]) >= 2:
            self._current_state["antennas"] = [float(target["antennas"][0]), float(target["antennas"][1])]
        if target.get("body_yaw") is not None:
            self._current_state["body_yaw"] = float(target["body_yaw"])

    def _to_sim_token(self, token: Dict[str, Any]) -> SimExecutionToken:
        token_id = str(token.get("token_id") or "missing-token")
        valid_until_raw = token.get("valid_until")
        valid_until = None
        if isinstance(valid_until_raw, str) and valid_until_raw.strip():
            valid_until = datetime.fromisoformat(valid_until_raw.replace("Z", "+00:00"))
        return SimExecutionToken(id=token_id, status="active", valid_until=valid_until)
