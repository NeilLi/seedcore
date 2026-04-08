# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Cognitive package exports with lazy loading for optional DSPy dependencies."""

from __future__ import annotations

from importlib import import_module
from typing import Any, Dict, Tuple

from .dspy_client import DSpyCognitiveClient

_LAZY_EXPORTS: Dict[str, Tuple[str, str]] = {
    "CognitiveCore": (".cognitive_core", "CognitiveCore"),
    "CognitiveContext": (".cognitive_core", "CognitiveContext"),
    "cognitive_signature": (".cognitive_registry", "cognitive_signature"),
    "cognitive_handler": (".cognitive_registry", "cognitive_handler"),
    "cognitive_validator": (".cognitive_registry", "cognitive_validator"),
    "CognitiveRegistry": (".cognitive_registry", "CognitiveRegistry"),
    "CognitiveAdvisoryContractBuilder": (
        ".advisory",
        "CognitiveAdvisoryContractBuilder",
    ),
}


def for_env() -> DSpyCognitiveClient:
    """Factory function that applies env-based namespacing automatically."""
    return DSpyCognitiveClient.for_env()


def __getattr__(name: str) -> Any:
    if name == "for_env":
        return for_env

    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    try:
        module = import_module(module_name, __name__)
    except ModuleNotFoundError as exc:
        if exc.name == "dspy":
            raise ModuleNotFoundError(
                f"{name} requires the optional 'dspy' dependency. "
                "Install DSPy to use SeedCore cognitive-core exports."
            ) from exc
        raise

    value = getattr(module, attr_name)
    globals()[name] = value
    return value


__all__ = [
    "DSpyCognitiveClient",
    "for_env",
    "CognitiveCore",
    "CognitiveContext",
    "cognitive_signature",
    "cognitive_handler",
    "cognitive_validator",
    "CognitiveRegistry",
    "CognitiveAdvisoryContractBuilder",
]
