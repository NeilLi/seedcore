"""Governance-gated execution gateway for robot behaviors."""

from __future__ import annotations

from typing import Any

from ..evidence.evidence_builder import EvidenceBuilder


class ActuatorAdapter:
    """Executes registered behaviors only when governance token is valid."""

    def __init__(self, runtime: Any, robot: Any, registry: Any, endpoint_id: str = "pybullet_r2d2_01"):
        self.runtime = runtime
        self.robot = robot
        self.registry = registry
        self.endpoint_id = endpoint_id
        self._evidence_builder = EvidenceBuilder()

    def execute(self, token: Any, behavior_name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not token or not getattr(token, "is_valid", lambda: False)():
            raise PermissionError("Execution blocked: invalid ExecutionToken")

        behavior = self.registry.get(behavior_name)
        if behavior is None:
            raise ValueError(f"Unknown behavior: {behavior_name}")

        result = behavior.execute(self.robot, self.runtime, **(params or {}))
        return self._evidence_builder.build(
            token_id=getattr(token, "id", "unknown_token"),
            actuator=self.endpoint_id,
            behavior=behavior_name,
            result=result,
        )
