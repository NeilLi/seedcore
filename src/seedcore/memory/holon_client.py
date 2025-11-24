
from typing import Any, Dict
from seedcore.memory.holon_fabric import HolonFabric
from seedcore.models.holon import Holon, HolonType, HolonScope

class HolonClient:
    def __init__(self, fabric: HolonFabric, embedder):
        self.fabric = fabric
        self.embedder = embedder

    async def persist_holon(self, *, fact: Dict[str, Any]) -> str:
        # 1. Build Holon
        hid = fact["task"]["id"]

        # 2. Build embedding from summary or result
        summary = fact["outcome"]["result_preview"] or fact["task"]["description"]
        embedding = self.embedder.embed(summary)

        holon = Holon(
            id=hid,
            type=HolonType.TASK_EVENT,
            scope=HolonScope.GLOBAL,  # or ORGAN/ENTITY depending on policy
            summary=summary,
            content=fact,
            embedding=embedding,
            confidence=fact["outcome"]["confidence"] or 1.0,
            decay_rate=0.1,
            links=[{
                "rel": "GENERATED_BY",
                "target_id": fact["src"]["agent_id"],
            }]
        )

        # 3. Persist using Fabric (dual-write)
        await self.fabric.insert_holon(holon)

        return hid
