"""Composable world object that binds runtime + robot model."""

from __future__ import annotations

from .pybullet_runtime import PyBulletRuntime
from .robot_model import RobotModel


class RobotWorld:
    """Owns runtime + robot lifecycle for behavior execution."""

    def __init__(self, runtime: PyBulletRuntime, robot: RobotModel):
        self.runtime = runtime
        self.robot = robot

    @classmethod
    def create_pybullet(
        cls,
        *,
        gui: bool = True,
        urdf: str = "r2d2.urdf",
        position: list[float] | None = None,
    ) -> "RobotWorld":
        runtime = PyBulletRuntime(gui=gui)
        robot = RobotModel(runtime=runtime, urdf=urdf, position=position)
        return cls(runtime=runtime, robot=robot)

    def step(self, steps: int = 240) -> None:
        self.runtime.step(steps=steps)

    def get_pose(self):
        return self.robot.get_pose()

    def shutdown(self) -> None:
        self.runtime.shutdown()
