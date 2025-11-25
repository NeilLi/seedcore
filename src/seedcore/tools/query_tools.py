# seedcore/tools/query_tools_v2.py
"""
QueryTools (TaskPayload v2)
Lightweight cognitive caller for agents.
No compatibility logic. No legacy fallbacks.
No PersistentAgent duplication.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, List, Tuple
import asyncio
import logging

from ..models.cognitive import CognitiveType, DecisionKind

logger = logging.getLogger(__name__)


class GeneralQueryTool:
    """
    Minimal, deterministic, TaskPayload v2 compliant QueryTool.
    """

    def __init__(self, cognitive_client, agent_id: str):
        self._cog = cognitive_client
        self._available = cognitive_client is not None
        self.agent_id = agent_id

        # Minimal in-flight deduplication
        self._inflight = {}
        self._lock = asyncio.Lock()

    @property
    def name(self):
        return "general_query"

    def schema(self):
        return {
            "name": self.name,
            "description": "General queries or chat through CognitiveCore (TaskPayload v2).",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "task_data": {"type": "object"},
                },
                "required": ["description"],
            },
        }

    def _normalize(self, resp: Dict[str, Any]):
        if not resp or not isinstance(resp, dict):
            return None
        if not resp.get("success"):
            return None
        payload = resp.get("result") or resp.get("payload")
        if not isinstance(payload, dict):
            return None
        meta = resp.get("meta") or resp.get("metadata") or {}
        return payload, meta

    async def execute(
        self,
        description: str,
        task_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        task_data = task_data or {}
        params = task_data.get("params", {}) or {}

        # --------------------------------------------------------
        # 1. Determine mode from interaction envelope (canonical)
        # --------------------------------------------------------
        interaction = params.get("interaction", {})
        is_chat = interaction.get("mode") == "agent_tunnel"

        # Read-only history (provided by PersistentAgent)
        chat_env = params.get("chat", {})
        history = chat_env.get("history") or []

        # --------------------------------------------------------
        # 2. Choose cognitive mode
        # --------------------------------------------------------
        if is_chat:
            cog_type = CognitiveType.CHAT
            decision = DecisionKind.FAST_PATH  # always fast unless explicitly overridden
        else:
            cog_type = CognitiveType.PROBLEM_SOLVING
            decision = DecisionKind.FAST_PATH   # default
            if params.get("force_deep_reasoning"):
                decision = DecisionKind.COGNITIVE

        if not self._available:
            return {
                "success": False,
                "reason": "cognitive service unavailable",
                "result": {},
            }

        # --------------------------------------------------------
        # 3. Construct TaskPayload v2 envelopes
        # --------------------------------------------------------

        # 3A Chat mode envelope
        if is_chat:
            params["chat"] = {
                **chat_env,
                "message": description,
                "history": history,
            }

            params.setdefault("interaction", interaction)

            params["cognitive"] = {
                "agent_id": self.agent_id,
                "cog_type": cog_type.value,
                "decision_kind": decision.value,
            }

            task_data["conversation_history"] = history
            task_data["type"] = "chat"
            task_data["message"] = description
            task_data["skip_retrieval"] = not params.get("force_rag")

        # 3B Problem solving envelope
        else:
            params["query"] = {
                "problem_statement": description,
            }
            params["cognitive"] = {
                "agent_id": self.agent_id,
                "cog_type": cog_type.value,
                "decision_kind": decision.value,
            }
            task_data["type"] = "general_query"

        task_data["params"] = params

        # --------------------------------------------------------
        # 4. In-flight dedup
        # --------------------------------------------------------
        request_key = task_data.get("task_id") or description[:50]

        async with self._lock:
            if request_key in self._inflight:
                return await self._inflight[request_key]

            fut = asyncio.create_task(self._cog.execute_async(
                agent_id=self.agent_id,
                cog_type=cog_type,
                decision_kind=decision,
                task=task_data,
            ))
            self._inflight[request_key] = fut

        try:
            resp = await fut
        finally:
            async with self._lock:
                self._inflight.pop(request_key, None)

        normalized = self._normalize(resp)
        if not normalized:
            return {
                "success": False,
                "reason": "invalid cognitive response",
                "result": {},
            }

        payload, meta = normalized

        # --------------------------------------------------------
        # 5. Return transformed results
        # --------------------------------------------------------
        if is_chat:
            return {
                "success": True,
                "query_type": "agent_chat",
                "message": description,
                "response": payload.get("response", ""),
                "confidence": payload.get("confidence", 0.0),
                "conversation_history": history,
                "meta": meta,
            }

        # non-chat
        return {
            "success": True,
            "query_type": "general_query",
            "query": description,
            "plan": payload.get("solution_steps", []),
            "thought": payload.get("thought", ""),
            "meta": meta,
        }
