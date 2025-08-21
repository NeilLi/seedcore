from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from ..cognitive import for_env


class RayAgentCognitiveIntegration:
    """Thin integration layer to call DSPy Serve from agents.

    Agents should compose an instance of this class and delegate calls to it
    rather than importing Serve/RPC logic directly.
    """

    def __init__(self) -> None:
        self._client = for_env()

    async def ensure_ready(self, timeout_s: float = 6.0) -> bool:
        return self._client.ready(timeout_s=timeout_s)

    async def failure_analysis(self, agent_id: str, incident_context: Dict[str, Any]) -> Dict[str, Any]:
        return await asyncio.wait_for(self._client.analyze_failure(agent_id, incident_context), timeout=30.0)

    async def plan(self, agent_id: str, task_description: str, agent_capabilities: Dict[str, Any], available_resources: Dict[str, Any]) -> Dict[str, Any]:
        return await asyncio.wait_for(self._client.plan(agent_id, task_description, agent_capabilities, available_resources), timeout=30.0)

    async def decide(self, agent_id: str, decision_context: Dict[str, Any], historical_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await asyncio.wait_for(self._client.decide(agent_id, decision_context, historical_data or {}), timeout=30.0)

    async def solve(self, agent_id: str, problem_statement: str, constraints: Dict[str, Any], available_tools: Dict[str, Any]) -> Dict[str, Any]:
        return await asyncio.wait_for(self._client.solve(agent_id, problem_statement, constraints, available_tools), timeout=30.0)

    async def synthesize(self, agent_id: str, memory_fragments: list, synthesis_goal: str) -> Dict[str, Any]:
        return await asyncio.wait_for(self._client.synthesize(agent_id, memory_fragments, synthesis_goal), timeout=30.0)

    async def assess(self, agent_id: str, performance_data: Dict[str, Any], current_capabilities: Dict[str, Any], target_capabilities: Dict[str, Any]) -> Dict[str, Any]:
        return await asyncio.wait_for(self._client.assess(agent_id, performance_data, current_capabilities, target_capabilities), timeout=30.0)


