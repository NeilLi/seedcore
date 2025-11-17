#!/usr/bin/env python
# seedcore/tools/query/synthesize_memory.py
"""
Tool for synthesizing information from multiple memory sources.
"""

from __future__ import annotations
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class SynthesizeMemoryTool:
    """
    Tool for synthesizing information from multiple memory sources.
    """

    def __init__(
        self,
        cognitive_client: Any,
        agent_id: str,
        normalize_cog_resp: callable,
    ):
        """
        Initialize the SynthesizeMemoryTool.

        Args:
            cognitive_client: CognitiveServiceClient instance
            agent_id: ID of the agent using this tool
            normalize_cog_resp: Function that normalizes cognitive service responses
        """
        self._cog = cognitive_client
        self.agent_id = agent_id
        self._normalize_cog_resp = normalize_cog_resp

    @property
    def name(self) -> str:
        return "cognitive.synthesize_memory"

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Synthesize information from multiple memory sources.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_fragments": {
                        "type": "array",
                        "description": "List of memory fragments to synthesize",
                    },
                    "synthesis_goal": {
                        "type": "string",
                        "description": "Goal of the synthesis",
                    },
                },
                "required": ["memory_fragments", "synthesis_goal"],
            },
        }

    async def execute(
        self, memory_fragments: List[Dict[str, Any]], synthesis_goal: str
    ) -> Dict[str, Any]:
        """
        Synthesize memory fragments.

        Args:
            memory_fragments: List of memory fragments to synthesize
            synthesis_goal: Goal of the synthesis

        Returns:
            Synthesis results dictionary
        """
        if not self._cog:
            return {"success": False, "reason": "Cognitive service not available."}

        try:
            # Call cognitive service via HTTP client
            resp = await self._cog.synthesize_memory(
                agent_id=self.agent_id,
                memory_fragments=memory_fragments,
                synthesis_goal=synthesis_goal,
            )

            norm = self._normalize_cog_resp(resp)
            payload = norm["payload"]

            return {
                "success": True,
                "agent_id": self.agent_id,
                "synthesized_insight": payload.get("synthesized_insight", ""),
                "confidence_level": payload.get("confidence_level", 0.0),
                "related_patterns": payload.get("related_patterns", ""),
                "meta": norm["meta"],
                "error": norm["error"],
            }
        except Exception as e:
            logger.error(f"Error in memory synthesis for agent {self.agent_id}: {e}")
            return {"success": False, "agent_id": self.agent_id, "error": str(e)}

