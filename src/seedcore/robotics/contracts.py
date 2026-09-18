"""Advisory team contracts. None of these objects grants execution authority."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^\S+$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def digest(value: BaseModel | dict) -> str:
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


class RobotBinding(Contract):
    """Operator-configured identity/capabilities, never supplied by a planner."""

    robot_id: Identifier
    agent_id: Identifier
    organ_id: Identifier
    endpoint_id: Identifier
    tool_name: Identifier
    profile: Literal["simulation", "hardware"]
    skills: frozenset[Identifier] = Field(min_length=1)
    max_duration_ms: int = Field(default=1000, ge=1, le=10000)
    # Always held, even if the model omits resource claims.
    exclusive_resources: frozenset[Identifier] = frozenset()


class TeamMission(Contract):
    mission_id: Identifier
    organ_id: Identifier
    objective: str = Field(min_length=1, max_length=4000)
    mode: Literal["cooperative", "competitive"] = "cooperative"
    bindings: tuple[RobotBinding, ...] = Field(min_length=2, max_length=32)
    roles: dict[Identifier, str]
    max_observation_age_s: float = Field(default=2, gt=0, le=60)
    planning_timeout_s: float = Field(default=1, gt=0, le=60)
    execution_timeout_s: float = Field(default=10, gt=0, le=300)

    @model_validator(mode="after")
    def unique_roster(self):
        for key in ("robot_id", "agent_id", "endpoint_id"):
            values = [getattr(b, key) for b in self.bindings]
            if len(set(values)) != len(values):
                raise ValueError(f"duplicate {key} in team")
        if any(b.organ_id != self.organ_id for b in self.bindings):
            raise ValueError("all bindings must belong to the mission organ")
        if set(self.roles) != {b.agent_id for b in self.bindings}:
            raise ValueError("roles must cover exactly the team agents")
        if len({b.profile for b in self.bindings}) != 1:
            raise ValueError("simulation and hardware cannot share a mission")
        return self


class TeamObservation(Contract):
    mission_id: Identifier
    sequence: int = Field(ge=0)
    observed_at: float = Field(gt=0)
    # Pose, velocity, ball/object states, health etc. are data, not instructions.
    robots: dict[Identifier, dict[str, JsonValue]]
    world: dict[str, JsonValue] = Field(default_factory=dict)


class RobotProposal(Contract):
    """The entire model output vocabulary: no routing, tokens, or tool names."""

    observation_sequence: int = Field(ge=0)
    skill: Identifier
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    duration_ms: int = Field(ge=1, le=10000)
    # Additional reservations; cannot remove operator-configured claims.
    exclusive_resources: frozenset[Identifier] = frozenset()


class ActionClosure(Contract):
    """Returned by a trusted RESULT_VERIFIER bridge, never by the LLM/driver."""

    task_id: Identifier
    mission_id: Identifier
    round_id: Identifier
    robot_id: Identifier
    agent_id: Identifier
    endpoint_id: Identifier
    observation_sequence: int = Field(ge=0)
    command_hash: Identifier
    execution_token_id: Identifier
    verifier_record_id: Identifier
    evidence_refs: tuple[Identifier, ...] = Field(min_length=1)
    verified: bool


class RoundResult(Contract):
    mission_id: Identifier
    round_id: Identifier
    observation_sequence: int
    status: Literal["verified", "halted"]
    closures: dict[str, ActionClosure] = Field(default_factory=dict)
    failures: dict[str, str] = Field(default_factory=dict)
    halt_acknowledged: bool = False

