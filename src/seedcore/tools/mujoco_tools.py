"""Internal agent tools for ephemeral MuJoCo experiments; never physical control."""

from __future__ import annotations

import asyncio
import os

from seedcore.robotics.mujoco_workbench.contracts import (
    ComparisonSpec,
    ExperimentSpec,
    RobotSpec,
)
from seedcore.robotics.mujoco_workbench.runtime import (
    ENGINE_VERSION,
    PROFILE,
    compare_experiments,
    inspect_robot,
    require_engine,
    run_experiment,
)


class MuJoCoDevelopmentTool:
    def __init__(self, operation: str, budget: asyncio.Semaphore):
        self.operation = operation
        self.name = f"simulation.mujoco.{operation}"
        self._budget = budget
        self._operations = {
            "build": (RobotSpec, inspect_robot),
            "run": (ExperimentSpec, run_experiment),
            "compare": (ComparisonSpec, compare_experiments),
        }
        self._contract, self._compute = self._operations[operation]

    def schema(self) -> dict:
        contract = self._contract.model_json_schema()
        definitions = contract.pop("$defs", {})
        parameters = {
            "type": "object",
            "properties": {"spec": contract},
            "required": ["spec"],
            "additionalProperties": False,
        }
        if definitions:
            parameters["$defs"] = definitions
        descriptions = {
            "build": "Build and inspect a primitive robot draft as MJCF using MuJoCo. Returns model hash, dimensions and sensors.",
            "run": "Run a bounded headless robot experiment. Returns simulated traces, contacts, tracking metrics and explicit criteria outcomes.",
            "compare": "Compare two designs/controllers under the same joint task, timing, initial state and criteria. Returns both measured runs.",
        }
        return {
            "name": self.name,
            "description": descriptions[self.operation]
            + " Offline development only. Results do not authorize hardware, certify safety or promote a policy.",
            "parameters": parameters,
        }

    def governance_contract(self):
        # Computation in fresh mjModel/mjData; no persistent or external mutation.
        return None

    async def execute(self, spec: dict) -> dict:
        draft = self._contract.model_validate(spec)
        async with self._budget:
            # Do not block the agent's event loop during native physics work.
            work = asyncio.create_task(asyncio.to_thread(self._compute, draft))
            try:
                return await asyncio.shield(work)
            except asyncio.CancelledError:
                # A Python cancellation does not interrupt native computation.
                # Retain the concurrency slot until the bounded job has ended.
                while not work.done():
                    try:
                        await asyncio.shield(work)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                # Consume any native failure while preserving the cancellation.
                if not work.cancelled():
                    work.exception()
                raise


async def register_mujoco_tools(manager) -> dict:
    """Explicit developer registration. An unavailable engine is an error."""
    require_engine()
    budget = asyncio.Semaphore(1)
    for operation in ("build", "run", "compare"):
        tool = MuJoCoDevelopmentTool(operation, budget)
        await manager.register(tool.name, tool)
    await manager.add_capability("simulation.mujoco.development")
    return {
        "profile": PROFILE,
        "engine_version": ENGINE_VERSION,
        "tools": [f"simulation.mujoco.{op}" for op in ("build", "run", "compare")],
    }


async def register_mujoco_tools_if_enabled(handler) -> bool:
    """Opt-in registration for a local manager or an existing Ray tool shard."""
    if os.getenv("SEEDCORE_ENABLE_MUJOCO_TOOLS", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        return False
    if hasattr(handler, "register_mujoco_tools"):
        await handler.register_mujoco_tools.remote()
    else:
        await register_mujoco_tools(handler)
    return True
