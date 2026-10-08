"""Constrained experiment drafts for agents; no executable code or authority."""

from __future__ import annotations

import math
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Number = Annotated[float, Field(strict=True)]


class DraftModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class LinkSpec(DraftModel):
    length_m: Number = Field(default=0.2, ge=0.02, le=1.0)
    mass_kg: Number = Field(default=0.2, ge=0.001, le=5.0)
    radius_m: Number = Field(default=0.015, ge=0.002, le=0.1)
    axis: Literal["x", "y", "z"] = "y"
    lower_rad: Number = Field(default=-2.5, ge=-math.pi, le=math.pi)
    upper_rad: Number = Field(default=2.5, ge=-math.pi, le=math.pi)
    damping: Number = Field(default=0.1, ge=0.0, le=5.0)
    torque_limit_nm: Number = Field(default=2.0, ge=0.001, le=10.0)

    @model_validator(mode="after")
    def geometry_and_range(self) -> Self:
        if self.lower_rad >= self.upper_rad:
            raise ValueError("joint lower bound must be below upper bound")
        if self.radius_m > self.length_m / 2:
            raise ValueError("link radius must not exceed half its length")
        return self


class RobotSpec(DraftModel):
    """A primitive serial mechanism, optionally with a floating box base.

    An empty chain with a floating base is a free-body contact experiment.
    This is an authoring subset, not a general MJCF/URDF importer.
    """

    name: str = Field(default="mini-robot", pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    links: tuple[LinkSpec, ...] = Field(default=(LinkSpec(), LinkSpec()), max_length=6)
    floating_base: bool = Field(default=False, strict=True)
    base_height_m: Number = Field(default=0.5, ge=0.05, le=2.0)
    base_mass_kg: Number = Field(default=0.5, ge=0.01, le=10.0)
    base_half_size_m: Number = Field(default=0.04, ge=0.01, le=0.1)
    gravity_m_s2: Number = Field(default=9.81, ge=0.0, le=20.0)
    timestep_s: Number = Field(default=0.002, ge=0.0005, le=0.005)
    friction: Number = Field(default=0.8, ge=0.0, le=2.0)

    @model_validator(mode="after")
    def body_present(self) -> Self:
        if not self.links and not self.floating_base:
            raise ValueError("a fixed-base robot needs at least one link")
        if self.base_height_m <= self.base_half_size_m:
            raise ValueError("base must initially be above the floor")
        return self


class ControllerSpec(DraftModel):
    mode: Literal["passive", "torque", "position"] = "passive"
    values: tuple[Number, ...] = Field(default=(), max_length=6)
    kp: Number = Field(default=12.0, ge=0.0, le=100.0)
    kd: Number = Field(default=1.0, ge=0.0, le=20.0)


class ExperimentCriteria(DraftModel):
    final_joint_error_rad: Number | None = Field(default=None, ge=0.001, le=math.pi)
    max_joint_speed_rad_s: Number | None = Field(default=None, gt=0.0, le=100.0)
    max_contact_points: int | None = Field(default=None, ge=0, le=256, strict=True)


class ExperimentSpec(DraftModel):
    robot: RobotSpec = RobotSpec()
    controller: ControllerSpec = ControllerSpec()
    initial_joint_angles_rad: tuple[Number, ...] = Field(default=(), max_length=6)
    initial_joint_velocities_rad_s: tuple[Number, ...] = Field(default=(), max_length=6)
    steps: int = Field(default=1000, ge=1, le=10000, strict=True)
    sample_every: int = Field(default=10, ge=1, le=10000, strict=True)
    criteria: ExperimentCriteria = ExperimentCriteria()

    @model_validator(mode="after")
    def validate_recipe(self) -> Self:
        n = len(self.robot.links)
        if self.steps * self.robot.timestep_s > 20:
            raise ValueError("experiment duration must not exceed 20 simulated seconds")
        if math.ceil(self.steps / self.sample_every) > 1000:
            raise ValueError("at most 1001 trace samples, including the initial state")
        for values, label in (
            (self.initial_joint_angles_rad, "initial angles"),
            (self.initial_joint_velocities_rad_s, "initial velocities"),
        ):
            if values and len(values) != n:
                raise ValueError(f"{label} must match link count")
        for angle, link in zip(
            self.initial_joint_angles_rad or (0.0,) * n, self.robot.links
        ):
            if not link.lower_rad <= angle <= link.upper_rad:
                raise ValueError("initial joint angle outside model range")
        if any(abs(v) > 100 for v in self.initial_joint_velocities_rad_s):
            raise ValueError("initial joint velocity exceeds experiment limit")
        if self.controller.mode == "passive":
            if self.controller.values:
                raise ValueError("passive control has no values")
        elif len(self.controller.values) != n or not n:
            raise ValueError("controller values must match a nonempty chain")
        for value, link in zip(self.controller.values, self.robot.links):
            if (
                self.controller.mode == "position"
                and not link.lower_rad <= value <= link.upper_rad
            ):
                raise ValueError("position target outside model range")
            if self.controller.mode == "torque" and abs(value) > link.torque_limit_nm:
                raise ValueError("torque request outside model limit")
        if (
            self.criteria.final_joint_error_rad is not None
            and self.controller.mode != "position"
        ):
            raise ValueError("joint error criterion requires position control")
        return self


class ComparisonSpec(DraftModel):
    baseline: ExperimentSpec
    candidate: ExperimentSpec

    @model_validator(mode="after")
    def matching_experiment(self) -> Self:
        # A design/controller can change; the initial task and acceptance must not.
        for name in (
            "steps",
            "sample_every",
            "initial_joint_angles_rad",
            "initial_joint_velocities_rad_s",
            "criteria",
        ):
            if getattr(self.baseline, name) != getattr(self.candidate, name):
                raise ValueError(f"comparison must preserve {name}")
        for name in (
            "timestep_s",
            "gravity_m_s2",
            "floating_base",
            "base_height_m",
            "friction",
        ):
            if getattr(self.baseline.robot, name) != getattr(
                self.candidate.robot, name
            ):
                raise ValueError(f"comparison must preserve {name}")
        if len(self.baseline.robot.links) != len(self.candidate.robot.links):
            raise ValueError("comparison must preserve joint count")
        if (self.baseline.controller.mode, self.baseline.controller.values) != (
            self.candidate.controller.mode,
            self.candidate.controller.values,
        ):
            raise ValueError("comparison must preserve the control task")
        return self
