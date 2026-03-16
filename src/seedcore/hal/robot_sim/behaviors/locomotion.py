"""Locomotion behavior implementations."""

from __future__ import annotations

from typing import Any

from .base_behavior import RobotBehavior


class MoveForward(RobotBehavior):
    name = "move_forward"

    def execute(self, robot: Any, runtime: Any, **params: Any) -> dict[str, Any]:
        distance = float(params.get("distance", 1.0))
        runtime.step(int(params.get("steps", 120)))
        return {
            "status": "success",
            "behavior": self.name,
            "distance": distance,
            "pose": robot.get_pose(),
        }


class Rotate(RobotBehavior):
    name = "rotate"

    def execute(self, robot: Any, runtime: Any, **params: Any) -> dict[str, Any]:
        angle = float(params.get("angle", 90.0))
        runtime.step(int(params.get("steps", 120)))
        return {
            "status": "success",
            "behavior": self.name,
            "rotation": angle,
            "pose": robot.get_pose(),
        }


class ActuatePose(RobotBehavior):
    """
    Compatibility behavior to accept HAL pose targets in simulation mode.
    """

    name = "actuate_pose"

    def execute(self, robot: Any, runtime: Any, **params: Any) -> dict[str, Any]:
        target = params.get("target", {}) if isinstance(params.get("target"), dict) else {}
        pose_type = str(params.get("pose_type") or "head")
        runtime.step(int(params.get("steps", 30)))
        return {
            "status": "success",
            "behavior": self.name,
            "pose_type": pose_type,
            "target": target,
            "pose": robot.get_pose(),
        }
