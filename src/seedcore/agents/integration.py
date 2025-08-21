from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from ray import serve
import ray
from ray.exceptions import RayActorError

# SOLUTION: Define custom exceptions for clear error handling by the caller.
class CognitiveCoreError(RuntimeError):
    """Base exception for failures when communicating with the Cognitive Core."""

class CognitiveCoreNotAvailableError(CognitiveCoreError):
    """Raised when the cognitive core application handle cannot be retrieved."""


class RayAgentCognitiveIntegration:
    """
    Thin integration layer for agents running inside the Ray cluster.

    This client runs inside Ray actors or tasks and makes direct, efficient calls
    to the Ray Serve application, bypassing HTTP. It assumes Ray is already
    initialized in its environment.
    """

    def __init__(self, app_name: str = "sc_cognitive") -> None:
        self._handle: Optional[serve.handle.DeploymentHandle] = None
        self._app_name = app_name

    def _get_handle(self) -> serve.handle.DeploymentHandle:
        """
        Get the Ray Serve handle for the cognitive core application.
        Caches the handle on first successful retrieval.
        """
        # SOLUTION: This method now raises a clear exception on failure instead of
        # returning None, which makes the client's state unambiguous.
        if self._handle is None:
            try:
                self._handle = serve.get_app_handle(self._app_name)
            except (ValueError, AssertionError) as e:
                # Catch specific, expected errors when the app isn't found or accessible.
                raise CognitiveCoreNotAvailableError(
                    f"Failed to get handle for Ray Serve app '{self._app_name}'. "
                    "Ensure the app is deployed and accessible from within the Ray cluster."
                ) from e
        return self._handle

    async def ensure_ready(self, timeout_s: float = 6.0) -> bool:
        """Check if the cognitive core is ready and its health endpoint is responsive."""
        try:
            # The health check implicitly uses _get_handle, so it also tests handle access.
            health_status = await self.health(timeout_s=timeout_s)
            return health_status.get("status") == "healthy"
        except CognitiveCoreError:
            return False

    # SOLUTION: A single, private helper method to centralize RPC logic,
    # error handling, and timeouts, reducing code duplication.
    async def _call_method(self, method_name: str, *args, timeout_s: float = 30.0) -> Dict[str, Any]:
        """A single helper to call any method on the Serve handle with robust error handling."""
        try:
            handle = self._get_handle()
            method_to_call = getattr(handle, method_name)
            remote_call = method_to_call.remote(*args)
            return await asyncio.wait_for(remote_call, timeout=timeout_s)
        except CognitiveCoreNotAvailableError:
            # Re-raise the specific error from _get_handle.
            raise
        except (asyncio.TimeoutError, RayActorError) as e:
            # Convert low-level Ray/asyncio errors into a consistent, high-level exception.
            raise CognitiveCoreError(f"Call to '{method_name}' failed: {type(e).__name__}") from e

    # ---- Public API Methods ----
    # SOLUTION: All public methods are now clean, simple wrappers around _call_method.
    # They no longer contain redundant try/except blocks and will propagate clear exceptions.

    async def health(self, timeout_s: float = 6.0) -> Dict[str, Any]:
        """Check the health of the cognitive core service."""
        return await self._call_method("health", timeout_s=timeout_s)

    async def failure_analysis(self, agent_id: str, incident_context: Dict[str, Any]) -> Dict[str, Any]:
        return await self._call_method("reason_about_failure", agent_id, incident_context)

    async def plan(self, agent_id: str, task_description: str, agent_capabilities: Dict[str, Any], available_resources: Dict[str, Any]) -> Dict[str, Any]:
        return await self._call_method("plan_task", agent_id, task_description, agent_capabilities, available_resources)

    async def decide(self, agent_id: str, decision_context: Dict[str, Any], historical_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._call_method("make_decision", agent_id, decision_context, historical_data or {})

    async def solve(self, agent_id: str, problem_statement: str, constraints: Dict[str, Any], available_tools: Dict[str, Any]) -> Dict[str, Any]:
        return await self._call_method("solve_problem", agent_id, problem_statement, constraints, available_tools)

    async def synthesize(self, agent_id: str, memory_fragments: list, synthesis_goal: str) -> Dict[str, Any]:
        return await self._call_method("synthesize_memory", agent_id, memory_fragments, synthesis_goal)

    async def assess(self, agent_id: str, performance_data: Dict[str, Any], current_capabilities: Dict[str, Any], target_capabilities: Dict[str, Any]) -> Dict[str, Any]:
        return await self._call_method("assess_capabilities", agent_id, performance_data, current_capabilities, target_capabilities)


