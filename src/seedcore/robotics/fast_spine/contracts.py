from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_PAYLOAD = 4096
MAX_EVENTS = 2048
MAX_SEQUENCE = 2**32 - 1
Scalar = Annotated[float, Field(allow_inf_nan=False, ge=-10, le=10)]
Vector = Annotated[tuple[Scalar, ...], Field(min_length=1, max_length=3)]


def canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SessionSpec(Contract):
    schema_version: Literal["seedcore.fast-spine.session.v1"] = (
        "seedcore.fast-spine.session.v1"
    )
    profile: Literal["simulation_only"] = "simulation_only"
    session_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    endpoint_id: str = Field(pattern=r"^spine_sim://[a-zA-Z0-9._/-]{1,128}$")
    boot_nonce: str = Field(pattern=r"^[a-f0-9]{32}$")
    principal_id: str = Field(pattern=r"^[a-zA-Z0-9._-]{1,64}$")
    policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    duration_ms: int = Field(strict=True, ge=100, le=5000)
    command_timeout_ms: int = Field(strict=True, ge=20, le=500)
    heartbeat_timeout_ms: int = Field(strict=True, ge=20, le=1000)
    authority_timeout_ms: int = Field(strict=True, ge=20, le=500)
    lower_rad: Vector
    upper_rad: Vector
    initial_rad: Vector
    max_velocity_rad_s: float = Field(gt=0, le=2, allow_inf_nan=False)
    max_acceleration_rad_s2: float = Field(gt=0, le=40, allow_inf_nan=False)
    max_jerk_rad_s3: float = Field(gt=0, le=2000, allow_inf_nan=False)

    @model_validator(mode="after")
    def envelope(self):
        if not len(self.lower_rad) == len(self.upper_rad) == len(self.initial_rad):
            raise ValueError("joint dimensions disagree")
        if any(
            not low <= q <= high or low >= high
            for low, q, high in zip(
                self.lower_rad, self.initial_rad, self.upper_rad, strict=True
            )
        ):
            raise ValueError("invalid initial pose/envelope")
        if (
            max(
                self.command_timeout_ms,
                self.heartbeat_timeout_ms,
                self.authority_timeout_ms,
            )
            > self.duration_ms
        ):
            raise ValueError("freshness windows exceed session duration")
        return self

    @property
    def sha256(self):
        return digest(self.model_dump(mode="json"))


class Waypoint(Contract):
    at_ms: int = Field(strict=True, ge=10, le=5000)
    positions_rad: Vector


class CommandChunk(Contract):
    session_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    endpoint_id: str = Field(pattern=r"^spine_sim://[a-zA-Z0-9._/-]{1,128}$")
    boot_nonce: str = Field(pattern=r"^[a-f0-9]{32}$")
    token_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sequence: int = Field(strict=True, ge=1, le=MAX_SEQUENCE)
    generated_at_ms: int = Field(strict=True, ge=0, le=5000)
    waypoints: tuple[Waypoint, ...] = Field(min_length=1, max_length=32)


class ControlMessage(Contract):
    session_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    endpoint_id: str = Field(pattern=r"^spine_sim://[a-zA-Z0-9._/-]{1,128}$")
    boot_nonce: str = Field(pattern=r"^[a-f0-9]{32}$")
    token_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sequence: int = Field(strict=True, ge=1, le=MAX_SEQUENCE)


class SessionOpen(Contract):
    spec: SessionSpec
    execution_token: dict


SCHEMAS = {
    "session": SessionSpec,
    "open": SessionOpen,
    "chunk": CommandChunk,
    "control": ControlMessage,
}
