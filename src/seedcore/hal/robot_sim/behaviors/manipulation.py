"""Manipulation behavior placeholders."""

from __future__ import annotations

from typing import Any

from .base_behavior import RobotBehavior


class PickObject(RobotBehavior):
    """Reference manipulation behavior for extension."""

    name = "pick_object"

    def execute(self, robot: Any, runtime: Any, **params: Any) -> dict[str, Any]:
        object_id = params.get("object_id", "unknown")
        runtime.step(int(params.get("steps", 60)))
        return {
            "status": "success",
            "behavior": self.name,
            "object_id": object_id,
            "pose": robot.get_pose(),
        }
