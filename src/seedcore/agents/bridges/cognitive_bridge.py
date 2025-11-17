# agents/bridges/cognitive_bridge.py

import asyncio
from typing import Dict, Any, Optional
from ...serve.cognitive_client import CognitiveServiceClient


class CognitiveBridge:
    """
    Wraps CognitiveServiceClient with:
    - lazy initialization
    - inflight request tracking
    - normalized responses
    """

    def __init__(self, cognitive_client: Optional[CognitiveServiceClient] = None, agent_id: str = None):
        self.agent_id = agent_id

        self.client: Optional[CognitiveServiceClient] = None
        self.available = False

        # inflight tasks + lock for cancellation/tracking
        self.inflight: Dict[str, asyncio.Task] = {}
        self.lock = asyncio.Lock()

        self._initialize(cognitive_client)

    # ------------------------------------------------------------------
    def _initialize(self, cognitive_client: Optional[CognitiveServiceClient] = None):
        """Initialize the cognitive client (non-async)."""
        try:
            if cognitive_client is not None:
                self.client = cognitive_client
            else:
                self.client = CognitiveServiceClient()
            self.available = True
        except Exception:
            self.available = False
            self.client = None

    # ------------------------------------------------------------------
    def normalize(self, resp: Any) -> Dict[str, Any]:
        """Normalize cognitive responses into consistent structure."""
        if not isinstance(resp, dict):
            return {
                "success": False,
                "payload": {},
                "meta": {},
                "error": "Invalid response",
            }

        payload = resp.get("result") or resp.get("payload") or {}
        meta = resp.get("meta") or resp.get("metadata") or {}

        return {
            "success": bool(resp.get("success", bool(payload))),
            "payload": payload,
            "meta": meta,
            "error": resp.get("error"),
        }

    # ------------------------------------------------------------------
    async def register_inflight(self, key: str, task: asyncio.Task):
        """Register a new inflight task."""
        async with self.lock:
            self.inflight[key] = task

    async def remove_inflight(self, key: str):
        async with self.lock:
            self.inflight.pop(key, None)

    # ------------------------------------------------------------------
    async def shutdown(self):
        """Cancel inflight tasks + close client."""
        # cancel inflight
        async with self.lock:
            for t in self.inflight.values():
                try:
                    t.cancel()
                except Exception:
                    pass
            self.inflight.clear()

        # clean shutdown
        if self.client and hasattr(self.client, "aclose"):
            try:
                await self.client.aclose()
            except Exception:
                pass
