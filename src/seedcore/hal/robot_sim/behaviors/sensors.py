"""Sensor behavior placeholders."""

from __future__ import annotations

from typing import Any

from .base_behavior import RobotBehavior


class ScanEnvironment(RobotBehavior):
    """Reference sensor behavior for extension."""

    name = "scan_environment"

    def execute(self, robot: Any, runtime: Any, **params: Any) -> dict[str, Any]:
        runtime.step(int(params.get("steps", 30)))
        return {
            "status": "success",
            "behavior": self.name,
            "scan_mode": params.get("mode", "lidar"),
            "pose": robot.get_pose(),
        }
