"""Versioned, data-only contracts for offline robot model ingestion."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Number = Annotated[float, Field(strict=True)]
Name = Annotated[str, Field(strict=True, min_length=1, max_length=128)]
Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]


def package_path(value: str) -> str:
    """Portable, canonical relative paths only; no URI or traversal semantics."""
    parts = value.split("/")
    if (
        not value
        or len(value) > 240
        or any(part in {"", ".", ".."} for part in parts)
        or any(c in value for c in "\\:\x00")
        or PurePosixPath(value).is_absolute()
    ):
        raise ValueError(f"unsafe package path: {value!r}")
    return value


class PackageContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ModelSource(PackageContract):
    repository_url: str = Field(strict=True, pattern=r"^https://", max_length=2048)
    revision: str = Field(strict=True, pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    source_path: str = Field(strict=True)
    license: Name
    cad_url: str | None = Field(
        default=None, strict=True, pattern=r"^https://", max_length=2048
    )
    cad_revision: Name | None = None
    exporter: Name | None = None

    _path = field_validator("source_path")(package_path)


class ModelFile(PackageContract):
    path: str = Field(strict=True)
    sha256: Digest
    size_bytes: int = Field(strict=True, gt=0, le=64 * 1024 * 1024)
    role: Literal[
        "model", "mesh", "texture", "heightfield", "skin", "license", "provenance"
    ]

    _path = field_validator("path")(package_path)


class JointContract(PackageContract):
    name: Name
    body: Name
    type: Literal["free", "ball", "slide", "hinge"]
    # Radians for hinge/ball, metres for slide; null means unlimited.
    range: tuple[Number, Number] | None = None

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if self.range is not None and self.range[0] >= self.range[1]:
            raise ValueError("joint range must be increasing")
        if self.type == "free" and self.range is not None:
            raise ValueError("free joints have no scalar limit range")
        return self


class ActuatorContract(PackageContract):
    name: Name
    joint: Name
    gear: tuple[Number, Number, Number, Number, Number, Number]
    control_range: tuple[Number, Number] | None = None
    force_range: tuple[Number, Number] | None = None

    @model_validator(mode="after")
    def valid_ranges(self) -> Self:
        for value in (self.control_range, self.force_range):
            if value is not None and value[0] >= value[1]:
                raise ValueError("actuator ranges must be increasing")
        return self


class BodyContract(PackageContract):
    name: Name
    parent: Name


class ModelParity(PackageContract):
    total_mass_kg: Number = Field(gt=0, le=1000)
    mass_tolerance_kg: Number = Field(default=1e-6, ge=0, le=0.01)
    nq: int = Field(strict=True, ge=0, le=256)
    nv: int = Field(strict=True, ge=0, le=256)
    timestep_s: Number = Field(ge=0.0005, le=0.005)
    bodies: tuple[BodyContract, ...] = Field(min_length=1, max_length=256)
    joints: tuple[JointContract, ...] = Field(max_length=128)
    actuators: tuple[ActuatorContract, ...] = Field(max_length=128)

    @model_validator(mode="after")
    def valid_tree_and_mapping(self) -> Self:
        for values in (self.bodies, self.joints, self.actuators):
            if len({v.name for v in values}) != len(values):
                raise ValueError("body, joint and actuator names must each be unique")
        seen = {"world"}
        for body in self.bodies:
            if body.name in seen or body.parent not in seen:
                raise ValueError("bodies must form a parent-first tree rooted at world")
            seen.add(body.name)
        joints = {joint.name for joint in self.joints}
        if any(joint.body not in seen - {"world"} for joint in self.joints):
            raise ValueError("joint references unknown body")
        if any(actuator.joint not in joints for actuator in self.actuators):
            raise ValueError("actuator references unknown joint")
        return self


class ModelPackage(PackageContract):
    schema_version: Literal["seedcore.model-package.v1"]
    package_id: str = Field(strict=True, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    version: str = Field(
        strict=True, pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.-]+)?$"
    )
    format: Literal["mjcf", "urdf"]
    engine: Literal["mujoco"]
    engine_version: Literal["3.15.0"]
    entrypoint: str = Field(strict=True)
    source: ModelSource
    files: tuple[ModelFile, ...] = Field(min_length=2, max_length=512)
    parity: ModelParity

    _path = field_validator("entrypoint")(package_path)

    @model_validator(mode="after")
    def inventory(self) -> Self:
        paths = {file.path: file for file in self.files}
        if len(paths) != len(self.files):
            raise ValueError("file inventory contains duplicate paths")
        if self.entrypoint not in paths or paths[self.entrypoint].role != "model":
            raise ValueError("entrypoint must be an inventoried model file")
        if not any(file.role == "license" for file in self.files):
            raise ValueError("a packaged license file is required")
        if sum(file.size_bytes for file in self.files) > 128 * 1024 * 1024:
            raise ValueError("package exceeds 128 MiB")
        return self
