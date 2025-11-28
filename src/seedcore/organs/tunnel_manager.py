# src/seedcore/organism/tunnel_manager.py

from ast import Dict
from typing import Optional


class TunnelManager:
    """
    Maintains server-side conversation→agent affinity.
    Stateless clients simply pass conversation_id on each request.
    """

    def __init__(self):
        self._tunnels: Dict[str, str] = {}  # conv_id -> agent_id

    async def get_assigned_agent(self, conversation_id: str) -> Optional[str]:
        return self._tunnels.get(conversation_id)

    async def assign(self, conversation_id: str, agent_id: str):
        self._tunnels[conversation_id] = agent_id
        return True

    async def release(self, conversation_id: str):
        self._tunnels.pop(conversation_id, None)

    async def list_active(self) -> Dict[str, str]:
        return dict(self._tunnels)
