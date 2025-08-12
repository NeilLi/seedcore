from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import ray
from ray import serve


def _ns() -> str:
    return os.getenv("SEEDCORE_NS", "seedcore")


def _stage() -> str:
    return os.getenv("SEEDCORE_STAGE", "dev")


def _serve_app_name(base: str = "cognitive_core") -> str:
    # Namespaced app name: e.g., seedcore-dev-cognitive_core
    return f"{_ns()}-{_stage()}-{base}" if os.getenv("SEEDCORE_NS") or os.getenv("SEEDCORE_STAGE") else base


class DSpyCognitiveClient:
    """Shared client for Ray Serve Cognitive Core deployments.

    - Names are derived from SEEDCORE_NS/SEEDCORE_STAGE for isolation across envs
    - Provides a readiness gate before first RPC
    - Mirrors the 6 cognitive tasks exposed by the Serve deployment
    """

    def __init__(self, app_base_name: str = "cognitive_core") -> None:
        self.app_name = _serve_app_name(app_base_name)
        # Ensure we are connected to the running Serve controller
        if not ray.is_initialized():
            try:
                # Respect RAY_ADDRESS if present; otherwise local
                address = os.getenv("RAY_ADDRESS", "auto")
                ray.init(address=address, ignore_reinit_error=True, namespace=_ns())
            except Exception:
                # Best-effort local init
                ray.init(ignore_reinit_error=True, namespace=_ns())
        try:
            serve.connect()
        except Exception:
            # If no controller exists yet, this will raise on handle fetch anyway
            pass
        self._handle = None

    def _get_handle(self):
        if self._handle is None:
            self._handle = serve.get_app_handle(self.app_name)
        return self._handle

    def ready(self, timeout_s: float = 6.0) -> bool:
        """Readiness gate based on Ray Serve application status.

        Returns True when the application exists and is RUNNING or has at least one RUNNING replica.
        """
        deadline = time.time() + max(0.0, timeout_s)
        while time.time() < deadline:
            try:
                status = serve.status()
                app = status.applications.get(self.app_name)
                if not app:
                    time.sleep(0.3)
                    continue
                # Consider RUNNING sufficient
                app_status_str = str(getattr(app, "status", ""))
                if "RUNNING" in app_status_str:
                    return True
                # Fallback: any deployment with RUNNING replicas
                deployments = getattr(app, "deployments", {}) or {}
                for info in deployments.values():
                    replica_states = getattr(info, "replica_states", {}) or {}
                    if int(replica_states.get("RUNNING", 0)) >= 1:
                        return True
            except Exception:
                # transient errors while Serve is starting
                pass
            time.sleep(0.3)
        return False

    # ---- Health ----
    def health(self) -> Dict[str, Any]:
        """Synchronous health check (best-effort). Prefer health_async in async contexts."""
        handle = self._get_handle()
        try:
            # Some environments allow blocking .result() on the deployment response
            resp = handle.health.remote()
            result_getter = getattr(resp, "result", None)
            if callable(result_getter):
                return result_getter()
            # Fallback to ray.get if supported
            return ray.get(resp)
        except Exception:
            # Indicate that async path should be used by the caller
            return {"status": "async_required", "message": "Use health_async in async context"}

    async def health_async(self) -> Dict[str, Any]:
        """Async health check that awaits the Serve deployment method."""
        handle = self._get_handle()
        return await handle.health.remote()

    # ---- Cognitive Tasks ----
    async def assess(self, agent_id: str, performance_data: Dict[str, Any], current_capabilities: Dict[str, Any] | None = None, target_capabilities: Dict[str, Any] | None = None) -> Dict[str, Any]:
        handle = self._get_handle()
        return await handle.assess_capabilities.remote(agent_id, performance_data, current_capabilities or {}, target_capabilities or {})

    async def plan(self, agent_id: str, task_description: str, agent_capabilities: Dict[str, Any], available_resources: Dict[str, Any]) -> Dict[str, Any]:
        handle = self._get_handle()
        return await handle.plan_task.remote(agent_id, task_description, agent_capabilities, available_resources)

    async def decide(self, agent_id: str, decision_context: Dict[str, Any], historical_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        handle = self._get_handle()
        return await handle.make_decision.remote(agent_id, decision_context, historical_data or {})

    async def solve(self, agent_id: str, problem_statement: str, constraints: Dict[str, Any], available_tools: Dict[str, Any]) -> Dict[str, Any]:
        handle = self._get_handle()
        return await handle.solve_problem.remote(agent_id, problem_statement, constraints, available_tools)

    async def synthesize(self, agent_id: str, memory_fragments: list, synthesis_goal: str) -> Dict[str, Any]:
        handle = self._get_handle()
        return await handle.synthesize_memory.remote(agent_id, memory_fragments, synthesis_goal)

    async def analyze_failure(self, agent_id: str, incident_context: Dict[str, Any]) -> Dict[str, Any]:
        handle = self._get_handle()
        return await handle.reason_about_failure.remote(agent_id, incident_context)


def for_env() -> DSpyCognitiveClient:
    """Factory that applies env-based namespacing automatically."""
    return DSpyCognitiveClient(app_base_name="cognitive_core")


