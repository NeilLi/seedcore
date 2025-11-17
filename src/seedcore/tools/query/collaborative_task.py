#!/usr/bin/env python
# seedcore/tools/query/collaborative_task.py
"""
Tool for executing collaborative tasks that may require finding knowledge.
This tool implements the core logic for collaborative task execution with knowledge finding integration.
"""

from __future__ import annotations
from typing import Dict, Any
import logging
import json
import time
import hashlib
import numpy as np

from .find_knowledge import FindKnowledgeTool

logger = logging.getLogger(__name__)


class CollaborativeTaskTool:
    """
    Tool for executing collaborative tasks that may require finding knowledge.
    This tool implements the core logic for collaborative task execution with knowledge finding integration.
    """

    def __init__(
        self,
        find_knowledge_tool: FindKnowledgeTool,
        mw_manager: Any,
        ltm_manager: Any,
        agent_id: str,
        get_energy_slice: callable,
    ):
        """
        Initialize the CollaborativeTaskTool.

        Args:
            find_knowledge_tool: FindKnowledgeTool instance for knowledge finding
            mw_manager: MwManager instance for artifact storage
            ltm_manager: LongTermMemoryManager instance for promotion
            agent_id: ID of the agent using this tool
            get_energy_slice: Function that returns current energy slice value
        """
        self.find_knowledge_tool = find_knowledge_tool
        self.mw_manager = mw_manager
        self.mlt_manager = ltm_manager
        self.agent_id = agent_id
        self._get_energy_slice = get_energy_slice

    @property
    def name(self) -> str:
        return "task.collaborative"

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Executes a collaborative task that may require finding knowledge. Returns task execution result with success status and details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_info": {
                        "type": "object",
                        "description": "Dictionary containing task information including name, required_fact, complexity, etc.",
                    }
                },
                "required": ["task_info"],
            },
        }

    async def _promote_to_mlt(
        self, key: str, obj: Dict[str, Any], compression: bool = True
    ) -> bool:
        """Promote an object to Mlt by creating a Holon."""
        if not self.mlt_manager:
            return False

        try:
            payload = obj
            if compression and isinstance(obj, dict):
                # Simple "compression": drop large fields
                pruned = {
                    k: v
                    for k, v in obj.items()
                    if k not in ("raw", "tokens", "trace", "result")
                }
                if "raw" in obj:
                    pruned["raw_size"] = len(str(obj["raw"]))
                if "result" in obj:
                    pruned["result_preview"] = str(obj["result"])[:200]
                payload = pruned

            # Create a placeholder embedding
            text_to_embed = json.dumps(payload, sort_keys=True)
            hash_bytes = hashlib.md5(text_to_embed.encode()).digest()
            vec = np.frombuffer(hash_bytes, dtype=np.uint8).astype(np.float32)
            vec = np.pad(vec, (0, 768 - len(vec)), mode="constant")
            embedding = vec / (np.linalg.norm(vec) + 1e-6)

            # Build the holon dict for the LTM manager
            holon_data = {
                "vector": {
                    "id": key,
                    "embedding": embedding,
                    "meta": payload,
                },
                "graph": {
                    "src_uuid": key,
                    "rel": "GENERATED_BY",
                    "dst_uuid": self.agent_id,
                },
            }

            return await self.mlt_manager.insert_holon_async(holon_data)
        except Exception as e:
            logger.debug(f"[{self.agent_id}] Mlt promote failed for {key}: {e}")
            return False

    def _mw_put_json_local(self, key: str, obj: Dict[str, Any]) -> bool:
        """L0 only (organ-local)."""
        if not self.mw_manager:
            return False
        try:
            self.mw_manager.set_item(key, json.dumps(obj))
            return True
        except Exception as e:
            logger.debug(f"[{self.agent_id}] Mw L0 put failed for {key}: {e}")
            return False

    def _mw_put_json_global(
        self,
        kind: str,
        scope: str,
        item_id: str,
        obj: Dict[str, Any],
        ttl_s: int = 600,
    ) -> bool:
        """Write-through L0/L1/L2 using normalized global key."""
        if not self.mw_manager:
            return False
        try:
            payload = (
                obj
                if isinstance(obj, (dict, list, str, int, float, bool, type(None)))
                else str(obj)
            )
            self.mw_manager.set_global_item_typed(
                kind, scope, item_id, payload, ttl_s=ttl_s
            )
            return True
        except Exception as e:
            logger.debug(
                f"[{self.agent_id}] Mw global put failed for {kind}:{scope}:{item_id}: {e}"
            )
            return False

    async def execute(self, task_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a collaborative task.

        Args:
            task_info: Dictionary containing task information including required_fact

        Returns:
            Task execution result with success status and details
        """
        task_name = task_info.get("name", "Unknown Task")
        required_fact = task_info.get("required_fact")

        logger.info(
            f"[{self.agent_id}] 🚀 Starting collaborative task '{task_name}'..."
        )

        # Capture energy before task execution
        E_before = self._get_energy_slice()

        knowledge = None
        if required_fact:
            logger.info(f"[{self.agent_id}] 📚 Task requires fact: {required_fact}")
            knowledge = await self.find_knowledge_tool.execute(required_fact)

        # Determine task success based on knowledge availability
        if required_fact and not knowledge:
            success = False
            quality = 0.1
            logger.error(
                f"[{self.agent_id}] 🚨 Task failed: could not find required fact '{required_fact}'."
            )
        else:
            success = True
            quality = 0.9 if knowledge else 0.7  # Higher quality if knowledge was found

        logger.info(f"[{self.agent_id}] ✅ Task completed successfully.")
        if knowledge:
            logger.info(
                f"[{self.agent_id}] 📖 Used knowledge: {knowledge.get('content', 'Unknown content')}"
            )

        # Calculate energy after task execution
        E_after = self._get_energy_slice()
        delta_e = E_after - E_before

        result = {
            "agent_id": self.agent_id,
            "task_name": task_name,
            "task_processed": True,
            "success": success,
            "quality": quality,
            "knowledge_found": knowledge is not None,
            "knowledge_content": knowledge.get("content", None) if knowledge else None,
            "delta_e_realized": delta_e,
            "E_before": E_before,
            "E_after": E_after,
        }

        # --- Mw/Mlt write path and promotion ---
        artifact_key = f"task:{task_info.get('task_id', task_name)}"
        artifact = {
            "agent_id": self.agent_id,
            "type": "collab_task",
            "ts": time.time(),
            "required_fact": required_fact,
            "knowledge_found": knowledge is not None,
            "knowledge_content": knowledge.get("content") if knowledge else None,
            "success": success,
            "quality": quality,
        }

        # Use normalized helpers
        self._mw_put_json_local(artifact_key, artifact)  # L0 for immediate local use
        self._mw_put_json_global(
            "collab_task", "global", artifact_key, artifact, ttl_s=900
        )

        if success and quality >= 0.8:
            await self._promote_to_mlt(artifact_key, artifact, compression=True)

        return result

