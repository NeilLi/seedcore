
from typing import Any, Dict

from .holon_fabric import HolonFabric
from ..models.holon import Holon, HolonType, HolonScope


class HolonClient:
    """Persists promoted cognitive outcomes into semantic (Holon) memory.

    Task outcomes are stored as :class:`HolonType.EPISODE` records per the
    normalized holon vocabulary (not a separate TASK_EVENT type).
    """

    def __init__(self, fabric: HolonFabric, embedder):
        self.fabric = fabric
        self.embedder = embedder

    async def persist_holon(self, *, fact: Dict[str, Any]) -> str:
        hid = fact["task"]["id"]

        summary = fact["outcome"]["result_preview"] or fact["task"]["description"]
        embedding = self.embedder.embed(summary)

        holon = Holon(
            id=hid,
            type=HolonType.EPISODE,
            scope=HolonScope.GLOBAL,
            summary=summary,
            content=fact,
            embedding=embedding,
            confidence=fact["outcome"]["confidence"] or 1.0,
            decay_rate=0.1,
            links=[
                {
                    "rel": "GENERATED_BY",
                    "target_id": fact["src"]["agent_id"],
                }
            ],
        )

        await self.fabric.insert_holon(holon)

        return hid
