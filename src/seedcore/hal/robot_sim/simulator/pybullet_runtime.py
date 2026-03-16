"""PyBullet runtime wrapper with a narrow API for simulation behaviors."""

from __future__ import annotations

from typing import Any


class PyBulletRuntime:
    """Minimal runtime adapter around PyBullet lifecycle and stepping."""

    def __init__(self, gui: bool = True):
        try:
            import pybullet as p  # type: ignore
            import pybullet_data  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on local optional deps
            raise RuntimeError(
                "PyBulletRuntime requires optional dependency 'pybullet'."
            ) from exc

        self._p = p
        mode = p.GUI if gui else p.DIRECT
        self.client = p.connect(mode)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setGravity(0, 0, -9.81)

    def load_urdf(self, urdf: str, position: list[float]) -> int:
        return int(self._p.loadURDF(urdf, position))

    def get_base_pose(self, robot_id: int) -> dict[str, Any]:
        pos, ori = self._p.getBasePositionAndOrientation(robot_id)
        return {"position": list(pos), "orientation": list(ori)}

    def step(self, steps: int = 240) -> None:
        for _ in range(steps):
            self._p.stepSimulation()

    def shutdown(self) -> None:
        self._p.disconnect()
