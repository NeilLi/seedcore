"""Robot model abstraction used by behaviors."""

from __future__ import annotations

from typing import Any


class RobotModel:
    """Thin robot container that delegates state to the runtime backend."""

    def __init__(
        self,
        runtime: Any,
        urdf: str = "r2d2.urdf",
        position: list[float] | None = None,
    ):
        self._runtime = runtime
        self.robot_id = runtime.load_urdf(urdf, position or [0.0, 0.0, 0.5])

    def get_pose(self) -> dict[str, Any]:
        return self._runtime.get_base_pose(self.robot_id)
