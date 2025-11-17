#!/usr/bin/env python
# seedcore/tools/query/make_decision.py
"""
Tool for making decisions using cognitive reasoning.
"""

from __future__ import annotations
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class MakeDecisionTool:
    """
    Tool for making decisions using cognitive reasoning.
    """

    def __init__(
        self,
        cognitive_client: Any,
        agent_id: str,
        get_memory_context: callable,
        normalize_cog_resp: callable,
    ):
        """
        Initialize the MakeDecisionTool.

        Args:
            cognitive_client: CognitiveServiceClient instance
            agent_id: ID of the agent using this tool
            get_memory_context: Function that returns memory context dict
            normalize_cog_resp: Function that normalizes cognitive service responses
        """
        self._cog = cognitive_client
        self.agent_id = agent_id
        self._get_memory_context = get_memory_context
        self._normalize_cog_resp = normalize_cog_resp

    @property
    def name(self) -> str:
        return "cognitive.make_decision"

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Make decisions using cognitive reasoning.",
            "parameters": {
                "type": "object",
                "properties": {
                    "decision_context": {
                        "type": "object",
                        "description": "Context for the decision",
                    },
                    "historical_data": {
                        "type": "object",
                        "description": "Historical data to inform the decision",
                    },
                },
                "required": ["decision_context"],
            },
        }

    async def execute(
        self, decision_context: Dict[str, Any], historical_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Make a decision.

        Args:
            decision_context: Context for the decision
            historical_data: Optional historical data

        Returns:
            Decision results dictionary
        """
        if not self._cog:
            return {"success": False, "reason": "Cognitive service not available."}

        try:
            # Call cognitive service via HTTP client
            resp = await self._cog.make_decision(
                agent_id=self.agent_id,
                decision_context=decision_context,
                historical_data=historical_data or {},
                knowledge_context=self._get_memory_context(),
            )

            norm = self._normalize_cog_resp(resp)
            payload = norm["payload"]

            return {
                "success": True,
                "agent_id": self.agent_id,
                "reasoning": payload.get("reasoning", ""),
                "decision": payload.get("decision", ""),
                "confidence": payload.get("confidence", 0.0),
                "meta": norm["meta"],
                "error": norm["error"],
                "alternative_options": payload.get("alternative_options", ""),
            }
        except Exception as e:
            logger.error(f"Error in decision making for agent {self.agent_id}: {e}")
            return {"success": False, "agent_id": self.agent_id, "error": str(e)}

