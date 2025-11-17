# agents/bridges/memory_bridge.py

import json
import time
import hashlib
import numpy as np
from typing import Dict, Any


class MemoryBridge:
    """
    Handles post-task memory actions for a RayAgent:
    - Writes artifacts to Mw (local + global)
    - LTM promotion for high-quality or salient tasks
    - Telemetry summary helper
    """

    def __init__(self, agent_id: str, mw_manager, ltm_manager, state):
        self.agent_id = agent_id
        self.mw = mw_manager
        self.ltm = ltm_manager
        self.state = state

    # ----------------------------------------------------------------------
    async def handle_post_task(self, task: Dict[str, Any], result: Dict[str, Any]):
        """Create artifact + write to Mw + promote to LTM if appropriate."""
        if not isinstance(task, dict):
            # Gracefully handle unexpected task formats.
            task_type = getattr(task, "type", "unknown")
        else:
            task_type = task.get("type", "unknown")

        task_id = result.get("task_id", "unknown")
        artifact_key = f"task:{task_id}"

        artifact = {
            "agent_id": self.agent_id,
            "type": task_type,
            "ts": time.time(),
            "result": result.get("results"),
            "success": result.get("success", False),
            "quality": result.get("quality", 0.5),
        }

        # Mw Layer writes
        self._mw_put_local(artifact_key, artifact)
        self._mw_put_global("task_artifact", "global", artifact_key, artifact)

        # LTM promotion threshold
        promote = (
            artifact["success"] and artifact["quality"] >= 0.8
        )

        salience = result.get("salience")
        if salience is not None:
            promote = promote or (not artifact["success"] and salience >= 0.7)

        if promote and self.ltm:
            await self._promote_to_ltm(artifact_key, artifact)

    # ----------------------------------------------------------------------
    # Internal Mw helpers
    # ----------------------------------------------------------------------
    def _mw_put_local(self, key: str, obj: Dict[str, Any]):
        if not self.mw:
            return
        try:
            self.mw.set_item(key, json.dumps(obj))
            self.state.memory_writes += 1
        except Exception:
            pass

    def _mw_put_global(
        self, kind: str, scope: str, item_id: str, obj: Dict[str, Any], ttl_s: int = 600
    ):
        if not self.mw:
            return

        try:
            payload = (
                obj
                if isinstance(obj, (dict, list, str, int, float, bool, type(None)))
                else str(obj)
            )
            self.mw.set_global_item_typed(kind, scope, item_id, payload, ttl_s=ttl_s)
            self.state.memory_writes += 1
        except Exception:
            pass

    # ----------------------------------------------------------------------
    # LTM Promotion helpers
    # ----------------------------------------------------------------------
    async def _promote_to_ltm(self, key: str, obj: Dict[str, Any]):
        """Create a compressed representation + fake embedding for LTM."""
        try:
            payload = self._compress(obj)
            embedding = self._hash_embedding(payload)

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

            await self.ltm.insert_holon_async(holon_data)
        except Exception:
            pass

    def _compress(self, obj: Dict[str, Any]) -> Dict[str, Any]:
        """Simple compression: remove large fields + add previews."""
        pruned = {k: v for k, v in obj.items() if k not in ("raw", "tokens", "trace", "result")}
        if "result" in obj:
            pruned["result_preview"] = str(obj["result"])[:200]
        return pruned

    def _hash_embedding(self, payload: Dict[str, Any]) -> np.ndarray:
        text = json.dumps(payload, sort_keys=True)
        digest = hashlib.md5(text.encode()).digest()
        vec = np.frombuffer(digest, dtype=np.uint8).astype(np.float32)
        return np.pad(vec, (0, 768 - len(vec)), mode="constant")

    # ----------------------------------------------------------------------
    # Summary telemetry
    # ----------------------------------------------------------------------
    def summary(self, state) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "tasks_processed": state.tasks_processed,
            "memory_writes": state.memory_writes,
        }
