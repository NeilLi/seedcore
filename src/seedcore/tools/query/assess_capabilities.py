#!/usr/bin/env python
# seedcore/tools/query/assess_capabilities.py
"""
Tool for assessing agent capabilities and suggesting improvements.
"""

from __future__ import annotations
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class AssessCapabilitiesTool:
    """
    Tool for assessing agent capabilities and suggesting improvements.
    """

    def __init__(
        self,
        cognitive_client: Any,
        agent_id: str,
        get_performance_data: callable,
        get_agent_capabilities: callable,
        normalize_cog_resp: callable,
    ):
        """
        Initialize the AssessCapabilitiesTool.

        Args:
            cognitive_client: CognitiveServiceClient instance
            agent_id: ID of the agent using this tool
            get_performance_data: Function that returns performance data dict
            get_agent_capabilities: Function that returns agent capabilities dict
            normalize_cog_resp: Function that normalizes cognitive service responses
        """
        self._cog = cognitive_client
        self.agent_id = agent_id
        self._get_performance_data = get_performance_data
        self._get_agent_capabilities = get_agent_capabilities
        self._normalize_cog_resp = normalize_cog_resp

    @property
    def name(self) -> str:
        return "cognitive.assess_capabilities"

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Assess agent capabilities and suggest improvements.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_capabilities": {
                        "type": "object",
                        "description": "Target capabilities to assess against",
                    },
                },
            },
        }

    async def execute(
        self, target_capabilities: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Assess capabilities.

        Args:
            target_capabilities: Optional target capabilities to assess against

        Returns:
            Assessment results dictionary
        """
        if not self._cog:
            return {"success": False, "reason": "Cognitive service not available."}

        try:
            # Call cognitive service via HTTP client
            resp = await self._cog.assess_capabilities(
                agent_id=self.agent_id,
                performance_data=self._get_performance_data(),
                current_capabilities=self._get_agent_capabilities(),
                target_capabilities=target_capabilities or {},
            )

            norm = self._normalize_cog_resp(resp)
            payload = norm["payload"]

            return {
                "success": True,
                "agent_id": self.agent_id,
                "capability_gaps": payload.get("capability_gaps", ""),
                "improvement_plan": payload.get("improvement_plan", ""),
                "priority_recommendations": payload.get("priority_recommendations", ""),
                "meta": norm["meta"],
                "error": norm["error"],
            }
        except Exception as e:
            logger.error(
                f"Error in capability assessment for agent {self.agent_id}: {e}"
            )
            return {"success": False, "agent_id": self.agent_id, "error": str(e)}

