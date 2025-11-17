#!/usr/bin/env python
# seedcore/tools/query/reason_about_failure.py
"""
Tool for analyzing agent failures using cognitive reasoning.
"""

from __future__ import annotations
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class ReasonAboutFailureTool:
    """
    Tool for analyzing agent failures using cognitive reasoning.
    """

    def __init__(
        self,
        cognitive_client: Any,
        mfb_client: Any,
        agent_id: str,
        get_memory_context: callable,
        normalize_cog_resp: callable,
        get_energy_state: callable,
        update_energy_state: callable,
    ):
        """
        Initialize the ReasonAboutFailureTool.

        Args:
            cognitive_client: CognitiveServiceClient instance
            mfb_client: FlashbulbClient instance
            agent_id: ID of the agent using this tool
            get_memory_context: Function that returns memory context dict
            normalize_cog_resp: Function that normalizes cognitive service responses
            get_energy_state: Function that returns current energy state
            update_energy_state: Function that updates energy state
        """
        self._cog = cognitive_client
        self.mfb_client = mfb_client
        self.agent_id = agent_id
        self._get_memory_context = get_memory_context
        self._normalize_cog_resp = normalize_cog_resp
        self._get_energy_state = get_energy_state
        self._update_energy_state = update_energy_state

    @property
    def name(self) -> str:
        return "cognitive.reason_about_failure"

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Analyze agent failures using cognitive reasoning.",
            "parameters": {
                "type": "object",
                "properties": {
                    "incident_id": {
                        "type": "string",
                        "description": "ID of the incident to analyze",
                    }
                },
                "required": ["incident_id"],
            },
        }

    async def execute(self, incident_id: str) -> Dict[str, Any]:
        """
        Analyze a failure incident.

        Args:
            incident_id: ID of the incident to analyze

        Returns:
            Analysis results dictionary
        """
        if not self._cog:
            return {"success": False, "reason": "Cognitive service not available."}
        if not self.mfb_client:
            return {"success": False, "reason": "Memory client not available."}

        try:
            # Get incident context from memory
            incident_context_dict = self.mfb_client.get_incident(incident_id)
            if not incident_context_dict:
                return {"success": False, "reason": "Incident not found."}

            # Call cognitive service via HTTP client
            resp = await self._cog.reason_about_failure(
                agent_id=self.agent_id,
                incident_context=incident_context_dict,
                knowledge_context=self._get_memory_context(),
            )

            norm = self._normalize_cog_resp(resp)
            payload = norm["payload"]

            # Calculate energy cost for reasoning
            reg_delta = 0.01 * len(str(payload.get("thought", "")))

            # Update energy state
            current_energy = self._get_energy_state()
            current_energy["cognitive_cost"] = (
                current_energy.get("cognitive_cost", 0.0) + reg_delta
            )
            self._update_energy_state(current_energy)

            return {
                "success": True,
                "agent_id": self.agent_id,
                "incident_id": incident_id,
                "thought_process": payload.get("thought", ""),
                "proposed_solution": payload.get("proposed_solution", ""),
                "confidence_score": payload.get("confidence_score", 0.0),
                "energy_cost": reg_delta,
                "meta": norm["meta"],
                "error": norm["error"],
            }
        except Exception as e:
            logger.error(f"Error in failure reasoning for agent {self.agent_id}: {e}")
            return {
                "success": False,
                "agent_id": self.agent_id,
                "incident_id": incident_id,
                "error": str(e),
            }

