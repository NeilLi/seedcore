"""Registry for behavior plugins."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from types import ModuleType
from typing import Dict, Iterable

from ..behaviors.base_behavior import RobotBehavior


class ExecutionRegistry:
    """Stores and resolves behavior plugins by name."""

    def __init__(self):
        self.behaviors: Dict[str, RobotBehavior] = {}

    def register(self, behavior: RobotBehavior) -> None:
        self.behaviors[behavior.name] = behavior

    def register_many(self, behaviors: Iterable[RobotBehavior]) -> None:
        for behavior in behaviors:
            self.register(behavior)

    def get(self, name: str) -> RobotBehavior | None:
        return self.behaviors.get(name)

    def auto_register_from_behaviors(self) -> list[str]:
        """
        Discover and register behavior classes from the behaviors package.

        Returns:
            A sorted list of discovered behavior names.
        """
        package_name = "seedcore.hal.robot_sim.behaviors"
        package = importlib.import_module(package_name)
        discovered_modules = [package]
        discovered_modules.extend(self._discover_modules(package))

        for module in discovered_modules:
            for _, candidate in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(candidate, RobotBehavior)
                    and candidate is not RobotBehavior
                    and not inspect.isabstract(candidate)
                ):
                    try:
                        self.register(candidate())
                    except TypeError:
                        # Skip behaviors requiring constructor args.
                        continue
        return sorted(self.behaviors.keys())

    def _discover_modules(self, package: ModuleType) -> list[ModuleType]:
        modules: list[ModuleType] = []
        package_path = getattr(package, "__path__", None)
        if not package_path:
            return modules
        prefix = f"{package.__name__}."
        for module_info in pkgutil.iter_modules(package_path, prefix=prefix):
            module = importlib.import_module(module_info.name)
            modules.append(module)
        return modules
