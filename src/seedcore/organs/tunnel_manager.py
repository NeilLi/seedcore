import logging
from typing import Dict, Optional
import redis.asyncio as redis  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)


class TunnelManager:
    """
    Maintains server-side conversation→agent affinity (Sticky Sessions).

    Modes:
      1. Redis Mode: If 'redis_url' is provided. Distributed, persistent, TTL-supported.
      2. Memory Mode: If 'redis_url' is None. Fast, local-only, resets on restart.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self._local_store: Dict[str, str] = {}  # For local mode only
        self.redis: Optional[redis.Redis] = None

        if redis_url:
            try:
                # decode_responses=True ensures we get strings back, not bytes
                self.redis = redis.from_url(
                    redis_url, encoding="utf-8", decode_responses=True
                )
                logger.info(f"[{self.__class__.__name__}] 🔗 Connected to Redis")
            except Exception as e:
                logger.error(f"[{self.__class__.__name__}] ❌ Redis init failed: {e}")

    async def get_assigned_agent(self, conversation_id: str) -> Optional[str]:
        """
        Retrieves the agent bound to this conversation.
        """
        if not conversation_id:
            return None

        # A. Redis Mode
        if self.redis:
            try:
                return await self.redis.get(self._get_key(conversation_id))
            except Exception as e:
                logger.warning(f"Tunnel lookup failed (Redis): {e}")
                return None

        # B. Memory Mode
        return self._local_store.get(conversation_id)

    async def assign(self, conversation_id: str, agent_id: str, ttl: int = 3600):
        """
        Binds a conversation to an agent for a specific duration (default 1 hour).
        """
        if not conversation_id or not agent_id:
            return

        # A. Redis Mode
        if self.redis:
            try:
                await self.redis.set(self._get_key(conversation_id), agent_id, ex=ttl)
            except Exception as e:
                logger.error(f"Tunnel bind failed (Redis): {e}")

        # B. Memory Mode
        else:
            self._local_store[conversation_id] = agent_id

    async def release(self, conversation_id: str):
        """
        Explicitly clears the sticky session (e.g. task completed).
        """
        if not conversation_id:
            return

        # A. Redis Mode
        if self.redis:
            try:
                await self.redis.delete(self._get_key(conversation_id))
            except Exception as e:
                logger.error(f"Tunnel release failed (Redis): {e}")

        # B. Memory Mode
        else:
            self._local_store.pop(conversation_id, None)

    async def list_active(self) -> Dict[str, str]:
        """
        Debug utility.
        Note: In Redis mode, listing all keys is expensive, so we return a placeholder.
        """
        if self.redis:
            return {"mode": "redis", "status": "scan_disabled"}
        return dict(self._local_store)

    def _get_key(self, conversation_id: str) -> str:
        """Standardizes Redis key format."""
        return f"sticky:v2:{conversation_id}"
