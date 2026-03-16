"""Behavior contract for pluggable robot capabilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class RobotBehavior(ABC):
    """Base contract for all simulator behaviors."""

    name = "base"

    @abstractmethod
    def execute(self, robot: Any, runtime: Any, **params: Any) -> dict[str, Any]:
        raise NotImplementedError
