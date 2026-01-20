#!/usr/bin/env python3
"""
ChatHistoryBehavior: Manages conversation history ring buffer.

This behavior provides chat history management capabilities:
- Ring buffer for recent messages
- Windowed history for CognitiveCore
- Respects cognitive.disable_memory_write flag
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base import AgentBehavior

logger = logging.getLogger(__name__)


class ChatHistoryBehavior(AgentBehavior):
    """
    Manages conversation history as a ring buffer.
    
    Configuration:
        limit: Maximum number of messages to keep (default: 50)
    """

    def __init__(self, agent: Any, config: Optional[Dict[str, Any]] = None):
        super().__init__(agent, config)
        self._chat_history: List[Dict[str, str]] = []
        self._history_limit = self.get_config("limit", 50)

    async def initialize(self) -> None:
        """Initialize chat history ring buffer."""
        self._chat_history = []
        logger.debug(
            f"[{self.agent.agent_id}] ChatHistoryBehavior initialized (limit={self._history_limit})"
        )
        self._initialized = True

    def add_user_message(self, content: str) -> None:
        """Add a user message to chat history."""
        if not self.is_enabled():
            return
        self._chat_history.append({"role": "user", "content": content})
        # Maintain ring buffer size
        if len(self._chat_history) > self._history_limit:
            self._chat_history = self._chat_history[-self._history_limit :]

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant message to chat history."""
        if not self.is_enabled():
            return
        self._chat_history.append({"role": "assistant", "content": content})
        # Maintain ring buffer size
        if len(self._chat_history) > self._history_limit:
            self._chat_history = self._chat_history[-self._history_limit :]

    def get_chat_history(self) -> List[Dict[str, str]]:
        """Get a shallow copy of the full chat history."""
        return list(self._chat_history)

    def get_recent_conversation_window(self, max_turns: int = 6) -> List[Dict[str, str]]:
        """
        Get a windowed subset of recent chat history for CognitiveCore.
        
        Args:
            max_turns: Maximum number of recent turns to return (default: 6)
            
        Returns:
            List of recent chat history entries (last max_turns turns)
        """
        return list(self._chat_history[-max_turns:])

    async def execute_task_pre(
        self, task: Any, task_dict: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Inject chat history into task before execution.
        
        Handles agent_tunnel mode and injects windowed history.
        """
        if not self.is_enabled():
            return None

        params = task_dict.setdefault("params", {})
        interaction = params.setdefault("interaction", {})
        chat = params.setdefault("chat", {})
        cognitive = params.get("cognitive", {})

        is_tunnel = interaction.get("mode") == "agent_tunnel"
        disable_memory_write = cognitive.get("disable_memory_write", False)

        if is_tunnel:
            # Extract incoming message
            incoming_msg = (
                task_dict.get("message")
                or task_dict.get("description")
                or chat.get("message")
            )

            if incoming_msg:
                # Write to local episodic memory (respects cognitive flags)
                if not disable_memory_write:
                    self.add_user_message(incoming_msg)
                else:
                    logger.debug(
                        f"[{self.agent.agent_id}] Skipping user message write (disable_memory_write=true)"
                    )

                # Always set message in chat envelope (regardless of memory flags)
                chat["message"] = incoming_msg

            # Inject windowed history for CognitiveCore
            recent_history = self.get_recent_conversation_window(max_turns=6)
            chat["history"] = recent_history
            task_dict["conversation_history"] = recent_history  # Legacy compatibility

            # Set interaction mode if not present
            if "mode" not in interaction:
                interaction["mode"] = "agent_tunnel"
            interaction.setdefault("assigned_agent_id", self.agent.agent_id)

        return task_dict

    async def execute_task_post(
        self, task: Any, task_dict: Dict[str, Any], result: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Extract assistant message from result and add to history.
        """
        if not self.is_enabled():
            return None

        params = task_dict.get("params", {})
        interaction = params.get("interaction", {})
        cognitive = params.get("cognitive", {})

        is_tunnel = interaction.get("mode") == "agent_tunnel"
        disable_memory_write = cognitive.get("disable_memory_write", False)

        if is_tunnel:
            assistant_msg = None

            # Extract assistant output from result
            try:
                if isinstance(result, dict):
                    payload = result.get("payload") or {}
                    if isinstance(payload, dict):
                        nested_result = payload.get("result") or payload.get("data") or payload
                        if isinstance(nested_result, dict):
                            assistant_msg = (
                                nested_result.get("response")
                                or nested_result.get("assistant_reply")
                                or nested_result.get("message")
                            )
                        elif isinstance(nested_result, str):
                            assistant_msg = nested_result

                    if not assistant_msg:
                        res = result.get("result") or result
                        if isinstance(res, dict):
                            assistant_msg = (
                                res.get("response")
                                or res.get("assistant_reply")
                                or res.get("message")
                            )
                        elif isinstance(res, str):
                            assistant_msg = res
            except Exception:
                pass

            # Write assistant message (respects cognitive flags)
            if isinstance(assistant_msg, str) and assistant_msg.strip():
                if not disable_memory_write:
                    self.add_assistant_message(assistant_msg)
                else:
                    logger.debug(
                        f"[{self.agent.agent_id}] Skipping assistant message write (disable_memory_write=true)"
                    )

        return None  # No result modification needed

    async def shutdown(self) -> None:
        """Cleanup on shutdown."""
        self._chat_history.clear()
        logger.debug(f"[{self.agent.agent_id}] ChatHistoryBehavior shutdown")
