# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Tier 0 (Ma): Per-Agent Memory Implementation
Ray actor-based stateful agents with private memory and performance tracking.

Refactored to inherit from BaseAgent.
"""

import os
import ray
import numpy as np
import time
import asyncio
import json
import random
import ast
import operator
import hashlib
from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING, Union
from dataclasses import dataclass

# --- REFACTOR: Import all new BaseAgent components ---
from .base import BaseAgent
from .roles import (
    Specialization,
    RoleRegistry,
    DEFAULT_ROLE_REGISTRY,
    SkillStoreProtocol,
    NullSkillStore,
)
from .checkpoint import CheckpointStoreFactory, CheckpointStore
from ..memory.flashbulb_client import FlashbulbClient
from ..serve.cognitive_client import CognitiveServiceClient
from ..models.cognitive import CognitiveType, DecisionKind
from ..models import TaskPayload

# --- End REFACTOR ---

if TYPE_CHECKING:
    from ..memory.mw_manager import MwManager
    from ..memory.long_term_memory import LongTermMemoryManager
    from ..tools.manager import ToolManager

from seedcore.logging_setup import ensure_serve_logger

logger = ensure_serve_logger("seedcore.agents.ray_agent", level="DEBUG")

REQUEST_TIMEOUT_S = 5.0
MAX_TEXT_LEN = 4096
MAX_IN_FLIGHT_SALIENCE = 20

# Safe arithmetic evaluator to replace unsafe eval()
_ALLOWED_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval_arith(expr: str) -> float:
    """
    Evaluate simple arithmetic safely via AST (no names, no calls).
    Supports + - * / // % ** and unary +/- on numbers.
    """

    def _eval(node):
        if isinstance(node, ast.Num):  # py<3.8
            return node.n
        if isinstance(node, ast.Constant):  # py>=3.8
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("Only numeric constants allowed")
        if isinstance(node, ast.BinOp):
            op = _ALLOWED_OPS.get(type(node.op))
            if not op:
                raise ValueError("Operator not allowed")
            return op(_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            op = _ALLOWED_OPS.get(type(node.op))
            if not op:
                raise ValueError("Unary operator not allowed")
            return op(_eval(node.operand))
        raise ValueError("Unsupported expression")

    tree = ast.parse(expr, mode="eval")
    return float(_eval(tree.body))


@dataclass
class LegacyAgentState:
    """Holds legacy state parts (h, p) for backward compatibility."""

    h: Any  # Embedding (kept JSON-safe as Python list)
    p: Dict[str, float]  # Role probabilities


@ray.remote(max_restarts=2, max_task_retries=0, max_concurrency=1)
class RayAgent(BaseAgent):
    """
    Stateful Ray actor for Tier 0 per-agent memory (Ma).

    This class inherits from BaseAgent to get modern state management,
    RBAC, and salience, but maintains its legacy methods and memory
    I/O for backward compatibility.
    """

    def __init__(
        self,
        agent_id: str,
        *,
        specialization: Specialization = Specialization.GENERALIST,
        role_registry: Optional[RoleRegistry] = None,
        skill_store: Optional[SkillStoreProtocol] = None,
        tool_manager: Optional["ToolManager"] = None,
        cognitive_base_url: Optional[str] = None,
        organ_id: Optional[str] = None,
        mw_manager: Optional["MwManager"] = None,
        ltm_manager: Optional["LongTermMemoryManager"] = None,
        checkpoint_cfg: Optional[Dict[str, Any]] = None,
        initial_role_probs: Optional[Dict[str, float]] = None,
        **legacy_kwargs: Any,
    ):
        if legacy_kwargs:
            logger.debug(
                "RayAgent %s received legacy kwargs: %s", agent_id, legacy_kwargs
            )

        super().__init__(
            agent_id=agent_id,
            tool_manager=tool_manager,
            specialization=specialization,
            role_registry=role_registry or DEFAULT_ROLE_REGISTRY,
            skill_store=skill_store or NullSkillStore(),
            cognitive_base_url=cognitive_base_url,
            initial_capability=0.5,
            initial_mem_util=0.0,
            organ_id=organ_id,
        )

        # Legacy state shim (embedding + role probabilities)
        self._legacy_state = LegacyAgentState(
            h=[0.0] * 128,
            p=initial_role_probs or {"E": 0.9, "S": 0.1, "O": 0.0},
        )

        # Legacy metrics / history surfaces
        self._legacy_quality_scores: List[float] = []
        self._legacy_successful_tasks: int = 0
        self.task_history: List[Dict[str, Any]] = []
        self.smoothing_factor: float = 0.1

        # Legacy counters (some duplicated in AgentState for telemetry)
        self.memory_writes: int = 0
        self.memory_hits_on_writes: int = 0
        self.salient_events_logged: int = 0
        self.total_compression_gain: float = 0.0

        # Legacy peer / lifecycle trackers
        self.peer_interactions: Dict[str, int] = {}
        self.created_at = time.time()
        self.last_heartbeat = self.created_at
        self.energy_state: Dict[str, float] = {}
        self.lifecycle_state: str = "Employed"
        self.idle_ticks: int = 0
        self.max_idle: int = 1000
        self._archived: bool = False

        # Working/long-term memory managers (lazy init when not injected)
        self.mw_manager = mw_manager
        self.mlt_manager = ltm_manager

        if self.mw_manager is None:
            try:
                from ..memory.mw_manager import (
                    MwManager,
                )  # lazy import to avoid circular deps

                self.mw_manager = MwManager(organ_id=self.agent_id)
                logger.info("✅ %s: MwManager created in-actor", self.agent_id)
            except Exception as exc:  # pragma: no cover - best effort
                logger.warning(
                    "⚠️ %s: failed to create MwManager in-actor: %s", self.agent_id, exc
                )

        if self.mlt_manager is None:
            try:
                from ..memory.long_term_memory import LongTermMemoryManager

                self.mlt_manager = LongTermMemoryManager()
                try:
                    loop = asyncio.get_event_loop()
                    loop.create_task(self.mlt_manager.initialize())
                except Exception as inner_exc:
                    logger.debug(
                        "LTM async initialize scheduling failed: %s", inner_exc
                    )
                logger.info(
                    "✅ %s: LongTermMemoryManager created in-actor", self.agent_id
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "⚠️ %s: failed to create LongTermMemoryManager in-actor: %s",
                    self.agent_id,
                    exc,
                )

        self.mfb_client = None

        # Legacy cognitive client handles (BaseAgent already tracks ML client)
        self._cog = None
        self._cog_available = False

        # Track in-flight cognitive requests to prevent duplicates
        self._cog_inflight: Dict[str, asyncio.Task] = {}
        self._cog_inflight_lock = asyncio.Lock()

        # Checkpointing uses BaseAgent._privmem
        self._ckpt_cfg = checkpoint_cfg or {"enabled": False}
        self._ckpt_store: CheckpointStore = CheckpointStoreFactory.from_config(
            self._ckpt_cfg
        )
        self._ckpt_key = f"{self.organ_id}/{self.agent_id}"
        self._maybe_restore()

        try:
            logger.info(
                "✅ RayAgent %s created with BaseAgent core state", self.agent_id
            )
            self._initialize_memory_managers()
            self._initialize_cognitive_systems()
            self._initialize_registry_reporting()
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "⚠️ RayAgent %s created with limited functionality: %s",
                self.agent_id,
                exc,
            )

        logger.info(
            "✅ RayAgent %s (%s) is online. Cog=%s, ML=%s",
            self.agent_id,
            self.specialization.value,
            self._cog_available,
            self._ml_client is not None,
        )

    # ============================================================================
    # Backward compatibility shims
    # ============================================================================

    @property
    def agent_role(self) -> str:
        """Shim for legacy agent_role attribute."""
        return self.specialization.value

    @property
    def state_embedding(self) -> np.ndarray:
        """Legacy accessor that returns the private memory vector as ndarray."""
        return self._privmem.get_vector()

    @state_embedding.setter
    def state_embedding(self, value: np.ndarray) -> None:
        if value.shape != (128,):
            raise ValueError(f"Invalid embedding shape: {value.shape}, expected (128,)")
        self._privmem.set_vector(value.astype(np.float32, copy=True))
        self._legacy_state.h = value.astype(float).tolist()

    @property
    def role_probs(self) -> Dict[str, float]:
        """Legacy role probability dict."""
        return self._legacy_state.p

    @role_probs.setter
    def role_probs(self, new_probs: Dict[str, float]) -> None:
        self._legacy_state.p = dict(new_probs)

    @property
    def capability_score(self) -> float:
        return float(self.state.c)

    @capability_score.setter
    def capability_score(self, value: float) -> None:
        self.state.c = float(value)

    @property
    def mem_util(self) -> float:
        return float(self.state.mem_util)

    @mem_util.setter
    def mem_util(self, value: float) -> None:
        self.state.mem_util = float(value)

    @property
    def tasks_processed(self) -> int:
        return int(self.state.tasks_processed)

    @tasks_processed.setter
    def tasks_processed(self, value: int) -> None:
        self.state.tasks_processed = int(value)

    @property
    def successful_tasks(self) -> int:
        return int(self._legacy_successful_tasks)

    @successful_tasks.setter
    def successful_tasks(self, value: int) -> None:
        self._legacy_successful_tasks = int(value)

    @property
    def quality_scores(self) -> List[float]:
        return self._legacy_quality_scores

    @property
    def skill_deltas(self) -> Dict[str, float]:
        return self.skills.deltas

    def _initialize_memory_managers(self):
        """
        Verifies injected memory managers and initializes FlashbulbClient.
        """
        if self.mw_manager:
            logger.info(f"✅ Agent {self.agent_id} attached to MwManager")
        else:
            logger.warning(f"⚠️ Agent {self.agent_id} has no MwManager")

        if self.mlt_manager:
            logger.info(f"✅ Agent {self.agent_id} attached to LongTermMemoryManager")
        else:
            logger.warning(f"⚠️ Agent {self.agent_id} has no LongTermMemoryManager")

        # Initialize Flashbulb Client
        try:
            self.mfb_client = FlashbulbClient()
            logger.info(f"✅ Agent {self.agent_id} initialized with FlashbulbClient")
        except Exception as e:
            logger.warning(
                f"⚠️ Failed to initialize FlashbulbClient for {self.agent_id}: {e}"
            )
            self.mfb_client = None

    def _initialize_cognitive_systems(self):
        """
        Wire this agent to the centralized CognitiveService.
        Do not silently swallow failures — expose degraded mode via _cog_available.
        """
        try:
            # Allow explicit base URL injection; otherwise default discovery
            if self._cog_base_url:
                self._cog = CognitiveServiceClient(base_url=self._cog_base_url)
            else:
                self._cog = CognitiveServiceClient()
            self._cog_available = True
            logger.info(f"🧠 {self.agent_id}: bound to central CognitiveServiceClient")
        except Exception as e:
            self._cog = None
            self._cog_available = False
            logger.error(
                f"❌ {self.agent_id}: failed to bind CognitiveServiceClient: {e}. Agent will run in DEGRADED mode."
            )

    def _initialize_registry_reporting(self):
        """Initialize optional registry reporting with graceful fallback."""
        self._registry = None
        if os.getenv("ENABLE_RUNTIME_REGISTRY", "true").lower() in ("1", "true", "yes"):
            try:
                from ..registry import RegistryClient

                # Get actor name if available (Ray actors can have names)
                actor_name = getattr(self, "_name", None) or self.agent_id
                self._registry = RegistryClient(
                    logical_id=self.agent_id,
                    actor_name=actor_name,
                    serve_route=None,
                    cluster_epoch=os.getenv("CLUSTER_EPOCH"),  # optional
                )
                logger.info(
                    f"✅ Agent {self.agent_id} initialized with registry reporting"
                )
            except Exception as e:
                logger.debug(f"Registry reporting disabled for {self.agent_id}: {e}")
                self._registry = None

    def _normalize_cog_resp(self, resp: dict) -> dict:
        """Normalize cognitive service response to consistent format."""
        if not isinstance(resp, dict):
            return {
                "success": False,
                "payload": {},
                "meta": {},
                "error": "Invalid response",
            }
        payload = resp.get("result") or resp.get("payload") or {}
        meta = resp.get("metadata") or resp.get("meta") or {}
        return {
            "success": bool(resp.get("success", True if payload else False)),
            "payload": payload,
            "meta": meta,
            "error": resp.get("error"),
        }

    async def shutdown(self):
        """Clean shutdown of the actor and its resources."""
        try:
            if self._cog and hasattr(self._cog, "aclose"):
                await self._cog.aclose()
        except Exception as e:
            logger.warning(f"Error during cognitive client shutdown: {e}")
        logger.info(f"Agent {self.agent_id} shutdown complete")

    def _mw_put_json_local(self, key: str, obj: Dict[str, Any]) -> bool:
        """L0 only (organ-local)."""
        if not self.mw_manager:
            return False
        try:
            self.mw_manager.set_item(key, json.dumps(obj))
            self.memory_writes += 1
            self._mw_puts = getattr(self, "_mw_puts", 0) + 1
            return True
        except Exception as e:
            logger.debug(f"[{self.agent_id}] Mw L0 put failed for {key}: {e}")
            return False

    def _mw_put_json_global(
        self, kind: str, scope: str, item_id: str, obj: Dict[str, Any], ttl_s: int = 600
    ) -> bool:
        """Write-through L0/L1/L2 using normalized global key; compressed when large."""
        if not self.mw_manager:
            return False
        try:
            # Ensure payload is JSON-serializable
            payload = (
                obj
                if isinstance(obj, (dict, list, str, int, float, bool, type(None)))
                else str(obj)
            )
            # Use typed API to avoid double-prefixing
            self.mw_manager.set_global_item_typed(
                kind, scope, item_id, payload, ttl_s=ttl_s
            )
            self.memory_writes += 1
            self._mw_puts = getattr(self, "_mw_puts", 0) + 1
            return True
        except Exception as e:
            logger.debug(
                f"[{self.agent_id}] Mw global put failed for {kind}:{scope}:{item_id}: {e}"
            )
            return False

    # --- Simple Mw → Mlt workflow helper ---
    async def fetch_with_cache(self, item_id: str) -> Optional[Dict[str, Any]]:
        """
        Implements the Mw→Mlt workflow:
          1) Try Mw (L0/L1/L2) via MwManager.get_item_async
          2) On miss, query LTM via LongTermMemoryManager.query_holon_by_id_async
          3) If found, write back to Mw via set_global_item_typed
        """
        try:
            if not self.mw_manager or not self.mlt_manager:
                return None

            # Step 1: Check cache (fast)
            # get_item_async (via _unwrap_value) handles JSON decompression
            cached = await self.mw_manager.get_item_async(item_id)
            if cached is not None:
                return cached

            # Step 2: Check LTM (slow)
            data = await self.mlt_manager.query_holon_by_id_async(item_id)

            # Step 3: Write-back (fire-and-forget)
            if data:
                try:
                    # Use typed, compression-aware setter for global cache
                    self.mw_manager.set_global_item_typed(
                        "fact", "global", item_id, data, ttl_s=900
                    )
                except Exception as e:
                    logger.warning(f"Failed to write-back cache for {item_id}: {e}")
            return data
        except Exception:
            return None

    def cache_task_row(self, task_row: Dict[str, Any]) -> None:
        """Lifecycle-aware Mw caching for a task row via MwManager.cache_task."""
        if not self.mw_manager:
            return
        try:
            self.mw_manager.cache_task(
                task_row
            )  # derives TTL from status/lease/run_after
        except Exception as e:
            logger.debug(f"[{self.agent_id}] cache_task failed: {e}")

    def invalidate_task_cache(self, task_id: str) -> None:
        """Evict all Mw tiers for a task when status/lease changes."""
        if not self.mw_manager:
            return
        try:
            # Clear the global (L2/L1) copy using exact key that cache_task sets
            gk = f"global:item:task:by_id:{task_id}"
            self.mw_manager.del_global_key_sync(gk)
        except Exception as e:
            logger.debug(f"[{self.agent_id}] Failed to delete global task cache: {e}")
        try:
            # Clear L0 copy
            self.mw_manager.delete_organ_item(f"task:by_id:{task_id}")
        except Exception as e:
            logger.debug(f"[{self.agent_id}] Failed to delete L0 task cache: {e}")

    async def get_task_cached(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Read a task via typed global key, respecting your double-prefix guard."""
        if not self.mw_manager:
            return None
        try:
            # Use the new get_task_async method with negative cache support
            return await self.mw_manager.get_task_async(task_id)
        except Exception as e:
            logger.debug(f"[{self.agent_id}] get_task_cached failed: {e}")
            return None

    async def _promote_to_mlt(
        self, key: str, obj: Dict[str, Any], compression: bool = True
    ) -> bool:
        """
        Asynchronously promote an object to Mlt by creating a Holon.
        """
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
                self.total_compression_gain += max(
                    0.0, len(str(obj)) - len(str(pruned))
                )

            # Create a placeholder embedding
            text_to_embed = json.dumps(payload, sort_keys=True)
            hash_bytes = hashlib.md5(text_to_embed.encode()).digest()
            vec = np.frombuffer(hash_bytes, dtype=np.uint8).astype(np.float32)
            vec = np.pad(vec, (0, 768 - len(vec)), mode="constant")
            embedding = vec / (np.linalg.norm(vec) + 1e-6)

            # Build the holon dict for the LTM manager
            holon_data = {
                "vector": {
                    "id": key,  # Use the task artifact key as the UUID
                    "embedding": embedding,
                    "meta": payload,
                },
                "graph": {  # Link the artifact to this agent
                    "src_uuid": key,
                    "rel": "GENERATED_BY",
                    "dst_uuid": self.agent_id,
                },
            }

            success = await self.mlt_manager.insert_holon_async(holon_data)

            if success:
                self._mlt_promotions = getattr(self, "_mlt_promotions", 0) + 1
                return True
            return False
        except Exception as e:
            logger.debug(f"[{self.agent_id}] Mlt promote failed for {key}: {e}")
            return False

    def _energy_slice(self) -> float:
        """A simple local scalar we can use as 'E' proxy: norm(h) + capability + 0.1*mem_util."""
        try:
            norm = float(np.linalg.norm(self.state_embedding))
        except Exception:
            norm = float(
                np.linalg.norm(np.array(self._legacy_state.h, dtype=np.float32))
            )
        return norm + float(self.capability_score) + 0.1 * float(self.mem_util)

    def build_memory_fragments(
        self, *, anomalies=None, reason=None, decision=None
    ) -> List[Dict[str, Any]]:
        """
        Return canonical fragments for best-effort synthesis. Pure data; no I/O.
        """
        frags = []
        if anomalies is not None:
            frags.append({"anomalies": anomalies})
        if reason is not None:
            frags.append({"reason": reason})
        if decision is not None:
            frags.append({"decision": decision})
        # include a tiny local context snapshot
        frags.append(
            {
                "agent_snapshot": {
                    "agent_id": self.agent_id,
                    "capability": self.capability_score,
                    "mem_util": self.mem_util,
                    "h_norm": float(np.linalg.norm(self.state_embedding)),
                    "ts": time.time(),
                }
            }
        )
        return frags

    def get_id(self) -> str:
        """Returns the agent's ID."""
        return self.agent_id

    def get_state_embedding(self) -> np.ndarray:
        """Returns the current state embedding vector."""
        return self.state_embedding.copy()

    def update_energy_state(self, energy_data: Dict[str, float]):
        """Updates the agent's knowledge of its energy contribution."""
        self.energy_state = energy_data.copy()

    def get_energy_state(self) -> Dict[str, float]:
        """Returns the current energy state."""
        return self.energy_state.copy()

    def ping(self) -> Dict[str, Any]:
        """Cheap liveness RPC used by Tier-0 to detect/prune dead handles."""
        return {"id": self.agent_id, "ts": time.time()}

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive status information for the agent."""
        current_time = time.time()
        uptime = current_time - self.created_at

        return {
            "agent_id": self.agent_id,
            "agent_role": getattr(self, "agent_role", "unknown"),
            "organ_id": self.organ_id,
            "instance_id": self.instance_id,
            "uptime_s": round(uptime, 3),
            "status": "healthy",
            "lifecycle_state": self.lifecycle_state,
            "capability_score": round(self.capability_score, 3),
            "memory_utilization": round(self.mem_util, 3),
            "tasks_processed": self.tasks_processed,
            "successful_tasks": self.successful_tasks,
            "success_rate": round(
                self.successful_tasks / max(self.tasks_processed, 1), 3
            ),
            "role_probabilities": self.role_probs.copy(),
            "energy_state": self.energy_state.copy(),
            "memory_writes": self.memory_writes,
            "memory_hits_on_writes": self.memory_hits_on_writes,
            "salient_events_logged": self.salient_events_logged,
            "idle_ticks": self.idle_ticks,
            "archived": self._archived,
            "last_heartbeat": self.last_heartbeat,
            "created_at": self.created_at,
            # Cognitive binding surface
            "cognitive_available": self._cog_available,
            "cognitive_bound_url": getattr(self._cog, "base_url", None)
            if self._cog
            else None,
        }

    def update_role_probs(self, new_role_probs: Dict[str, float]):
        """Updates the agent's role probabilities."""
        # Validate that probabilities sum to 1.0
        total_prob = sum(new_role_probs.values())
        if abs(total_prob - 1.0) > 1e-6:
            logger.warning(
                f"Role probabilities don't sum to 1.0 (sum={total_prob}), normalizing"
            )
            # Normalize
            for role in new_role_probs:
                new_role_probs[role] /= total_prob

        self.role_probs = new_role_probs.copy()
        logger.debug(
            f"Agent {self.agent_id} role probabilities updated: {self.role_probs}"
        )

    def update_local_metrics(self, success: float, quality: float, mem_hits: int):
        """
        Update capability and memory utility using EWMA after a task.
        """
        alpha = 0.1
        new_cap = (1 - alpha) * self.capability_score + alpha * (
            0.6 * float(success) + 0.4 * float(quality)
        )
        new_mem = (1 - alpha) * self.mem_util + alpha * float(mem_hits)

        self.capability_score = new_cap
        self.mem_util = max(0.0, min(1.0, new_mem))

        logger.debug(
            "Agent %s metrics updated - capability: %.3f, mem_util: %.3f",
            self.agent_id,
            self.capability_score,
            self.mem_util,
        )

    def get_energy_proxy(self) -> Dict[str, float]:
        """
        Returns the agent's expected contribution to energy terms.
        This is a lightweight local estimate.
        """
        return {
            "capability": self.capability_score,
            "entropy_contribution": -sum(
                p * np.log2(p + 1e-9) for p in self.role_probs.values()
            ),
            "mem_util": self.mem_util,
            "state_norm": np.linalg.norm(self._legacy_state.h),
        }

    def update_state_embedding(self, new_embedding: np.ndarray):
        """Updates the state embedding vector."""
        try:
            self.state_embedding = new_embedding
            logger.debug("Agent %s state embedding updated", self.agent_id)
        except ValueError as exc:
            logger.warning("Invalid embedding shape for %s: %s", self.agent_id, exc)

    def update_performance(
        self, success: bool, quality: float, task_metadata: Optional[Dict] = None
    ):
        """
        Updates the agent's performance metrics after a task.

        Args:
            success: Whether the task was successful
            quality: Quality score (0.0 to 1.0)
            task_metadata: Optional metadata about the task
        """
        self._legacy_quality_scores.append(quality)
        if len(self._legacy_quality_scores) > 20:
            self._legacy_quality_scores.pop(0)

        if success:
            self._legacy_successful_tasks += 1

        task_record = {
            "timestamp": time.time(),
            "success": success,
            "quality": quality,
            "metadata": task_metadata or {},
        }
        self.task_history.append(task_record)
        if len(self.task_history) > 100:
            self.task_history.pop(0)

        self.state.record_task_outcome(
            success=success,
            quality=quality,
            salience=(task_metadata or {}).get("salience"),
            duration_s=(task_metadata or {}).get("duration_s"),
        )

        if task_metadata and "memory_stats" in task_metadata:
            mem_hits = task_metadata["memory_stats"].get("hits", 0)
            self.update_local_metrics(float(success), quality, mem_hits)

        task_record["capability_score"] = self.capability_score
        task_record["mem_util"] = self.mem_util

        logger.info(
            "📈 Agent %s performance updated: Capability=%.3f, MemUtil=%.3f",
            self.agent_id,
            self.capability_score,
            self.mem_util,
        )

    async def execute_task(self, task_data: Union[TaskPayload, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Execute a task and update performance metrics with energy tracking.

        Args:
            task_data: Task information and payload

        Returns:
            Task execution result with performance metrics
        """
        payload, normalized_task = self._normalize_task_payload(task_data)

        logger.info(
            "🤖 %s execute_task(%s) type=%s agent_role=%s cog=%s",
            self.agent_id,
            payload.task_id or "?",
            payload.type,
            getattr(self, "agent_role", "unknown"),
            self._cog_available,
        )

        # Capture energy before task execution
        E_before = self._energy_slice()

        # --- TASK EXECUTION LOGIC ---
        task_type = payload.type or normalized_task.get("type", "unknown")
        task_description = payload.description or normalized_task.get("description", "")

        # Handle specific task types with real implementations
        if task_type == "general_query":
            result = await self._handle_general_query(task_description, normalized_task)
        else:
            # Fallback to simulation for other task types
            result = self._simulate_task_execution(normalized_task)

        # Update memory utilization based on task complexity
        task_complexity = normalized_task.get("complexity", 0.5)
        self.mem_util = min(1.0, self.mem_util + task_complexity * 0.1)

        # Update memory interaction tracking
        self.memory_writes += 1
        if random.random() < 0.3:  # 30% chance of being read by others
            self.memory_hits_on_writes += 1

        # Update local metrics using the new energy-aware method
        self.update_local_metrics(
            result.get("success", False),
            result.get("quality", 0.5),
            result.get("mem_hits", 0),
        )

        success_flag = bool(result.get("success", False))
        quality_score = float(result.get("quality", 0.5))
        salience_score = result.get("salience_score")
        duration_s = result.get("duration_s")

        self._legacy_quality_scores.append(quality_score)
        if len(self._legacy_quality_scores) > 20:
            self._legacy_quality_scores.pop(0)

        if success_flag:
            self._legacy_successful_tasks += 1

        task_record = {
            "timestamp": time.time(),
            "task_id": payload.task_id,
            "success": success_flag,
            "quality": quality_score,
            "metadata": normalized_task,
        }
        self.task_history.append(task_record)
        if len(self.task_history) > 100:
            self.task_history.pop(0)

        self.state.record_task_outcome(
            success=success_flag,
            quality=quality_score,
            salience=salience_score,
            duration_s=duration_s,
        )

        # Calculate energy after task execution
        E_after = self._energy_slice()
        delta_e = E_after - E_before
        result["delta_e_realized"] = delta_e
        result["E_before"] = E_before
        result["E_after"] = E_after

        # --- Mw/Mlt write path and promotion ---
        artifact_key = f"task:{payload.task_id or 'unknown'}"
        artifact = {
            "agent_id": self.agent_id,
            "type": task_type,
            "ts": time.time(),
            "result": result.get("result"),
            "success": result.get("success", False),
            "quality": result.get("quality", 0.5),
        }
        # Use new normalized helpers
        self._mw_put_json_local(artifact_key, artifact)  # L0 for immediate local use
        # Also cache globally for cross-agent reuse
        self._mw_put_json_global(
            "task_artifact", "global", artifact_key, artifact, ttl_s=600
        )

        # simple policy: promote successes with quality>=0.8, or failures with salience >= 0.7 (if present)
        should_promote = artifact["success"] and artifact["quality"] >= 0.8
        sal = result.get("salience_score")
        if sal is not None:
            should_promote = should_promote or (not artifact["success"] and sal >= 0.7)
        if should_promote:
            await self._promote_to_mlt(artifact_key, artifact, compression=True)

        return result

    async def _handle_general_query(
        self, description: str, task_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle all general_query tasks by routing them to the Cognitive Service.

        1. Determines the required profile (fast/deep) based on task heuristics.
        2. Calls the central cognitive service (via unified execute endpoint).
        3. Normalizes the response or handles errors.

        All logic, including for simple queries (time, math), is deferred
        to the CognitiveCore, which will use the appropriate signature.
        """

        # --- Helper functions (no change) ---
        def _extract_formatted(payload: Dict[str, Any]) -> str:
            formatted = payload.get("formatted_response")
            if not formatted:
                steps = payload.get("solution_steps")
                if isinstance(steps, list) and steps:
                    first_step = steps[0]
                    if isinstance(first_step, dict):
                        formatted = first_step.get("description")
            if not formatted:
                formatted = f"Cognitive analysis: {description}"
            return formatted

        def _normalize_cog_v2_response(
            cog_response: Dict[str, Any],
        ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
            if not isinstance(cog_response, dict):
                return None
            if not cog_response.get("success"):
                return None
            payload = cog_response.get("result") or cog_response.get("payload")
            if not isinstance(payload, dict):
                return None
            metadata = cog_response.get("metadata") or cog_response.get("meta") or {}
            return payload, metadata

        # --- Main execution path ---
        try:
            description_lower = description.lower()

            # --- 1. Unified Cognitive Service Path ---
            # All local fast-paths (time, date, status, math) have been removed.
            # We now determine the profile and call the cognitive service for ALL queries.

            params = task_data.get("params", {}) or {}
            needs_ml_fallback = params.get("needs_ml_fallback", False)

            if isinstance(params.get("confidence"), dict):
                confidence = params["confidence"].get("overall_confidence", 1.0)
            else:
                confidence = (
                    params.get("confidence", 1.0)
                    if isinstance(params.get("confidence"), (int, float))
                    else 1.0
                )

            criticality = params.get("criticality", task_data.get("criticality", 0.5))
            drift_score = task_data.get("drift_score", 0.0)

            # Heuristic for determining profile remains the same.
            # Simple queries ("what is the time?") will correctly be profiled as "fast".
            explicit_profile = params.get("cognitive_profile")
            if explicit_profile in ("fast", "deep"):
                profile = explicit_profile
                is_complex = (
                    needs_ml_fallback
                    or confidence < 0.5
                    or criticality > 0.6
                    or drift_score > 0.6
                    or len(description.split()) > 15
                    or any(
                        word in description_lower
                        for word in [
                            "complex",
                            "analysis",
                            "decompose",
                            "plan",
                            "strategy",
                            "reasoning",
                            "root cause",
                            "diagnose",
                            "mitigation",
                            "architecture",
                            "design a plan",
                        ]
                    )
                    or task_data.get("force_decomposition")
                )
                logger.debug(
                    f"Using explicit cognitive_profile={explicit_profile} from params "
                    f"(heuristic would suggest: {'deep' if is_complex else 'fast'})"
                )
            else:
                is_complex = (
                    needs_ml_fallback
                    or confidence < 0.5
                    or criticality > 0.6
                    or drift_score > 0.6
                    or len(description.split()) > 15
                    or any(
                        word in description_lower
                        for word in [
                            "complex",
                            "analysis",
                            "decompose",
                            "plan",
                            "strategy",
                            "reasoning",
                            "root cause",
                            "diagnose",
                            "mitigation",
                            "architecture",
                            "design a plan",
                        ]
                    )
                    or task_data.get("force_decomposition")
                )
                profile = "deep" if is_complex else "fast"

            # Map the profile to the DecisionKind the CognitiveCore expects
            decision_kind = (
                DecisionKind.COGNITIVE if profile == "deep" else DecisionKind.FAST_PATH
            )

            # Check for cognitive service availability
            if not self._cog_available or not self._cog:
                degraded_blob = {
                    "query_type": "cognitive_query_unserved",
                    "degraded_mode": True,
                    "reason": "central cognitive service unavailable",
                    "description": description,
                    "intended_profile": profile,
                }
                logger.error(
                    f"🚫 {self.agent_id}: cognitive service unavailable. Can't run {profile} reasoning for query='{description[:80]}'"
                )
                return {
                    "agent_id": self.agent_id,
                    "task_processed": True,
                    "success": False,
                    "quality": 0.0,
                    "capability_score": self.capability_score,
                    "mem_util": self.mem_util,
                    "result": degraded_blob,
                    "mem_hits": 0,
                    "used_cognitive_service": False,
                    "cognitive_profile": profile,
                }

            # --- In-flight request deduplication (no change) ---
            task_id = task_data.get("task_id") or task_data.get("id")
            request_key = task_id if task_id else f"{description[:100]}:{profile}"

            async with self._cog_inflight_lock:
                if request_key in self._cog_inflight:
                    existing_task = self._cog_inflight[request_key]
                    if not existing_task.done():
                        logger.info(
                            f"🔄 Agent {self.agent_id} deduplicating cognitive request for {request_key[:50]}... "
                            f"(waiting for existing call to complete)"
                        )
                        try:
                            existing_response = await existing_task
                            normalized = _normalize_cog_v2_response(existing_response)
                            if normalized:
                                payload, metadata = normalized
                                result = {
                                    "query_type": (
                                        "complex_cognitive_query"
                                        if profile == "deep"
                                        else "fast_cognitive_query"
                                    ),
                                    "query": description,
                                    "thought_process": payload.get("thought", ""),
                                    "plan": payload.get("solution_steps", []),
                                    "formatted": _extract_formatted(payload),
                                    "description": description,
                                    "meta": metadata,
                                    "profile_used": profile,
                                }
                                logger.info(
                                    f"✅ Agent {self.agent_id} reused result from in-flight cognitive request (deduplicated)"
                                )
                                return {
                                    "agent_id": self.agent_id,
                                    "task_processed": True,
                                    "success": True,
                                    "quality": 0.9 if profile == "deep" else 0.8,
                                    "capability_score": self.capability_score,
                                    "mem_util": self.mem_util,
                                    "result": result,
                                    "mem_hits": 1,
                                    "used_cognitive_service": True,
                                    "cognitive_profile": profile,
                                }
                        except Exception as e:
                            logger.debug(
                                f"Error waiting for in-flight request: {e}, making new call"
                            )
                        finally:
                            self._cog_inflight.pop(request_key, None)

            # --- Cognitive Service Call (no change) ---
            try:
                logger.info(
                    f"🧠 Agent {self.agent_id} using cognitive service (decision_kind={decision_kind.value}, complex={profile == 'deep'})"
                )
                try:
                    dbg_payload = {
                        "agent_id": self.agent_id,
                        "problem_statement": str(description or ""),
                        "decision_kind": decision_kind.value,
                        "profile": profile,
                    }
                    logger.info(
                        "[CognitivePayload_Outgoing] %s",
                        json.dumps(dbg_payload, default=str),
                    )
                except Exception:
                    pass

                # This closure matches the ProblemSolvingSignature inputs
                async def _cog_call():
                    input_data = {
                        "problem_statement": str(description or ""),
                        "constraints": params.get("constraints") or {},
                        "available_tools": params.get("available_tools") or {},
                    }
                    meta = {
                        "task_id": task_id,
                        "requested_profile": profile,
                        "agent_capabilities": self._summarize_agent_capabilities(),
                    }
                    return await self._cog.execute_async(
                        agent_id=self.agent_id,
                        cog_type=CognitiveType.PROBLEM_SOLVING,  # This maps to ProblemSolvingSignature
                        decision_kind=decision_kind,
                        input_data=input_data,
                        meta=meta,
                    )

                cog_task = asyncio.create_task(_cog_call())
                async with self._cog_inflight_lock:
                    self._cog_inflight[request_key] = cog_task

                try:
                    cog_response = await cog_task
                finally:
                    async with self._cog_inflight_lock:
                        self._cog_inflight.pop(request_key, None)

                normalized = _normalize_cog_v2_response(cog_response)
                if normalized:
                    payload, metadata = normalized
                    result = {
                        "query_type": (
                            "complex_cognitive_query"
                            if profile == "deep"
                            else "fast_cognitive_query"
                        ),
                        "query": description,
                        "thought_process": payload.get("thought", ""),
                        "plan": payload.get("solution_steps", []),
                        "formatted": _extract_formatted(payload),
                        "description": description,
                        "meta": metadata,
                        "profile_used": profile,
                    }
                    logger.info(
                        f"✅ Agent {self.agent_id} cognitive service completed with profile={profile}"
                    )
                    return {
                        "agent_id": self.agent_id,
                        "task_processed": True,
                        "success": True,
                        "quality": 0.9 if profile == "deep" else 0.8,
                        "capability_score": self.capability_score,
                        "mem_util": self.mem_util,
                        "result": result,
                        "mem_hits": 1,
                        "used_cognitive_service": True,
                        "cognitive_profile": profile,
                    }

                logger.warning(
                    "⚠️ Agent %s cognitive service returned unusable response (profile=%s), falling back",
                    self.agent_id,
                    profile,
                )

            except Exception as e:
                import traceback

                logger.warning(
                    f"⚠️ Agent {self.agent_id} cognitive service call failed (profile={profile}): {e}"
                )
                logger.debug("Traceback:\n%s", traceback.format_exc())

            # --- Fallback Error (no change) ---
            err_blob = {
                "query_type": "cognitive_query_failed",
                "description": description,
                "intended_profile": profile,
                "error": "cognitive service failure or unusable response",
            }
            return {
                "agent_id": self.agent_id,
                "task_processed": True,
                "success": False,
                "quality": 0.0,
                "capability_score": self.capability_score,
                "mem_util": self.mem_util,
                "result": err_blob,
                "mem_hits": 0,
                "used_cognitive_service": True,
                "cognitive_profile": profile,
            }

        except Exception as e:
            # --- Outer Catch-All (no change) ---
            logger.error(
                f"❌ Agent {self.agent_id} failed to handle general query: {e}"
            )
            return {
                "agent_id": self.agent_id,
                "task_processed": True,
                "success": False,
                "quality": 0.0,
                "capability_score": self.capability_score,
                "mem_util": self.mem_util,
                "error": str(e),
                "result": {
                    "query_type": "general_query",
                    "error": f"Task execution failed: {str(e)}",
                    "formatted": "I encountered an error while processing your query.",
                    "description": description,
                },
                "mem_hits": 0,
                "used_cognitive_service": False,
                "cognitive_profile": None,
            }

    def _simulate_task_execution(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Simulate task execution for non-general_query tasks.
        This maintains backward compatibility for other task types.
        """
        import random

        # Simulate task execution with some randomness
        success = random.choice([True, False])
        quality = random.uniform(0.5, 1.0)

        # Simulate memory hits for energy tracking
        mem_hits = random.randint(0, 5)

        return {
            "agent_id": self.agent_id,
            "task_processed": True,
            "success": success,
            "quality": quality,
            "capability_score": self.capability_score,
            "mem_util": self.mem_util,
            "mem_hits": mem_hits,
        }

    # === Telemetry surfaces for Tier-0 / Meta-learning ===
    def get_private_memory_vector(self) -> List[float]:
        return self._privmem.get_vector().tolist()

    def get_private_memory_telemetry(self) -> Dict[str, Any]:
        return self._privmem.telemetry()

    def reset_private_memory(self) -> bool:
        self._privmem.reset()
        self._legacy_state.h = [0.0] * 128
        return True

    def _export_tier0_summary(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "embedding": self._privmem.get_vector_list(),
            "capability_score": self.capability_score,
            "mem_util": self.mem_util,
            "tasks_processed": self.tasks_processed,
            "success_rate": (self.successful_tasks / self.tasks_processed)
            if self.tasks_processed
            else 0.0,
            "skill_deltas": self.skill_deltas,
            "peer_interactions": self.peer_interactions,
        }

    async def archive(self) -> bool:
        """
        Asynchronously move Tier-0 summaries to Mlt and mark this actor as archived.
        """
        try:
            summary = self._export_tier0_summary()

            # Promote the summary to LTM using our async method
            summary_key = f"agent_summary:{self.agent_id}:{int(time.time())}"
            await self._promote_to_mlt(summary_key, summary, compression=False)

            if self.mw_manager and hasattr(self.mw_manager, "evict_agent"):
                self.mw_manager.evict_agent(self.agent_id)  # Assuming fire-and-forget

            if self.mw_manager and hasattr(self.mw_manager, "clear"):
                try:
                    self.mw_manager.clear()
                    logger.debug(f"[{self.agent_id}] Cleared L0 cache on archive")
                except Exception as e:
                    logger.debug(f"[{self.agent_id}] Failed to clear L0 cache: {e}")

            if self.mfb_client and hasattr(self.mfb_client, "log_incident"):
                self.mfb_client.log_incident(
                    {"archive": True, "summary": summary}, salience=0.3
                )

            self._archived = True
            self.lifecycle_state = "Archived"
            return True
        except Exception as e:
            logger.exception(f"Archive failed for {self.agent_id}: {e}")
            return False

    # ---------- Checkpointing ----------
    def _maybe_restore(self):
        try:
            if self._ckpt_cfg.get("enabled") and hasattr(self._privmem, "load"):
                blob = self._ckpt_store.load(self._ckpt_key)
                if blob:
                    self._privmem.load(blob)
                    vec = self._privmem.get_vector_list()
                    self._legacy_state.h = list(vec)
        except Exception as e:
            logger.warning(f"[{self.agent_id}] restore failed: {e}")

    def _post_task_housekeeping(self):
        try:
            if self._ckpt_cfg.get("enabled") and hasattr(self._privmem, "dump"):
                self._ckpt_store.save(self._ckpt_key, self._privmem.dump())
        except Exception as e:
            logger.warning(f"[{self.agent_id}] checkpoint failed: {e}")

    def update_skill_delta(self, skill_name: str, delta: float):
        """
        Update local skill delta (per-agent scratch memory).

        Args:
            skill_name: Name of the skill
            delta: Change in skill level
        """
        try:
            new_val = self.skills.bump(skill_name, delta, clamp_delta=False)
            logger.debug(
                "Agent %s skill delta updated: %s -> %.3f",
                self.agent_id,
                skill_name,
                new_val,
            )
        except Exception as exc:
            logger.warning(
                "Failed to update skill delta for %s on %s: %s",
                skill_name,
                self.agent_id,
                exc,
            )

    def record_peer_interaction(self, peer_id: str):
        """
        Record interaction with another agent.

        Args:
            peer_id: ID of the peer agent
        """
        self.peer_interactions[peer_id] = self.peer_interactions.get(peer_id, 0) + 1
        logger.debug(f"Agent {self.agent_id} recorded interaction with {peer_id}")

    async def get_heartbeat(self) -> Dict[str, Any]:
        """
        Gathers the agent's current state and performance into a heartbeat.
        This merges BaseAgent telemetry with legacy fields expected by Tier-0.
        """
        base_heartbeat = await super().get_heartbeat()

        success_rate = (
            (self.successful_tasks / self.tasks_processed)
            if self.tasks_processed > 0
            else 0.0
        )
        current_quality = self.quality_scores[-1] if self.quality_scores else 0.0

        legacy_memory_metrics = {
            "memory_writes": self.memory_writes,
            "memory_hits_on_writes": self.memory_hits_on_writes,
            "salient_events_logged": self.salient_events_logged,
            "total_compression_gain": self.total_compression_gain,
            "mw_puts": getattr(self, "_mw_puts", 0),
            "mlt_promotions": getattr(self, "_mlt_promotions", 0),
        }

        legacy_payload = {
            "timestamp": time.time(),
            "agent_id": self.agent_id,
            "state_embedding_h": self.state_embedding.tolist(),
            "role_probs": self.role_probs,
            "performance_metrics": {
                "success_rate": success_rate,
                "quality_score": current_quality,
                "capability_score_c": self.capability_score,
                "mem_util": self.mem_util,
                "tasks_processed": self.tasks_processed,
                "successful_tasks": self.successful_tasks,
            },
            "memory_metrics": legacy_memory_metrics,
            "local_state": {
                "skill_deltas": self.skill_deltas,
                "peer_interactions": self.peer_interactions,
                "recent_quality_scores": self.quality_scores[-5:]
                if self.quality_scores
                else [],
            },
            "lifecycle": {
                "state": self.lifecycle_state,
                "created_at": self.created_at,
                "last_heartbeat": self.last_heartbeat,
                "uptime": time.time() - self.created_at,
                "capability_c": self.capability_score,
                "mem_util": self.mem_util,
                "idle_ticks": self.idle_ticks,
                "archived": self._archived,
            },
            "energy_state": self.energy_state,
        }

        merged = {**base_heartbeat, **legacy_payload}

        perf = dict(base_heartbeat.get("performance_metrics", {}))
        perf.update(legacy_payload["performance_metrics"])
        merged["performance_metrics"] = perf

        mem_metrics = dict(base_heartbeat.get("memory_metrics", {}))
        mem_metrics.update(legacy_memory_metrics)
        merged["memory_metrics"] = mem_metrics

        if self.mw_manager:
            try:
                tele = self.mw_manager.get_telemetry()
                mem_metrics.update(
                    {
                        "mw_hit_ratio": tele.get("hit_ratio", 0),
                        "mw_l0_hits": tele.get("l0_hits", 0),
                        "mw_l1_hits": tele.get("l1_hits", 0),
                        "mw_l2_hits": tele.get("l2_hits", 0),
                        "mw_task_cache_hits": tele.get("task_cache_hits", 0),
                        "mw_task_cache_misses": tele.get("task_cache_misses", 0),
                        "mw_task_evictions": tele.get("task_evictions", 0),
                        "mw_negative_cache_hits": tele.get("negative_cache_hits", 0),
                    }
                )

                if self.tasks_processed % 10 == 0 and random.random() < 0.05:
                    try:
                        hot = await self.mw_manager.get_hot_items_async(top_n=5)
                        mem_metrics["mw_hot_items"] = hot
                    except Exception:
                        pass
            except Exception as exc:
                logger.debug("[%s] Failed to get Mw telemetry: %s", self.agent_id, exc)

        self.last_heartbeat = time.time()
        return merged

    def on_task_row_loaded(self, task_row: Dict[str, Any]) -> None:
        """Hook called when a task row is loaded from database."""
        self.cache_task_row(task_row)

    def on_task_status_changed(self, task_id: str, new_status: str) -> None:
        """Hook called when task status changes."""
        if new_status in ("completed", "failed", "cancelled"):
            self.invalidate_task_cache(task_id)
        # For other status changes, the caller should re-cache with updated row

    def get_summary_stats(self) -> Dict[str, Any]:
        """
        Get a summary of agent statistics for monitoring.

        Returns:
            Dictionary with key performance indicators
        """
        try:
            ad = self.advertise_capabilities()
        except Exception as exc:
            logger.debug("advertise_capabilities failed for %s: %s", self.agent_id, exc)
            ad = {
                "agent_id": self.agent_id,
                "capability": self.capability_score,
                "mem_util": self.mem_util,
                "quality_avg": self.state.rolling_quality_avg() or 0.0,
            }

        success_rate = (
            (self.successful_tasks / self.tasks_processed)
            if self.tasks_processed > 0
            else 0.0
        )

        return {
            "agent_id": ad.get("agent_id", self.agent_id),
            "capability_score": ad.get("capability", self.capability_score),
            "mem_util": ad.get("mem_util", self.mem_util),
            "tasks_processed": self.tasks_processed,
            "success_rate": success_rate,
            "avg_quality": ad.get(
                "quality_avg", self.state.rolling_quality_avg() or 0.0
            ),
            "memory_writes": self.memory_writes,
            "peer_interactions_count": len(self.peer_interactions),
        }

    # --- NEW: Knowledge Finding Method for Scenario 1 ---
    async def find_knowledge(self, fact_id: str) -> Optional[Dict[str, Any]]:
        """
        Attempts to find a piece of knowledge, implementing the Mw -> Mlt escalation.
        This is an async method that uses non-blocking calls with negative caching and single-flight guards.

        Args:
            fact_id: The ID of the fact to find

        Returns:
            Optional[Dict[str, Any]]: The found knowledge or None if not found
        """
        logger.info(f"[{self.agent_id}] 🔍 Searching for '{fact_id}'...")

        # Check if memory managers are available
        if not self.mw_manager or not self.mlt_manager:
            logger.error(f"[{self.agent_id}] ❌ Memory managers not available")
            return None

        # Check negative cache first (avoid stampede on cold misses)
        if await self.mw_manager.check_negative_cache("fact", "global", fact_id):
            logger.info(f"[{self.agent_id}] NEG-HIT for {fact_id}; skipping Mlt lookup")
            return None

        # Try to acquire single-flight sentinel atomically
        sentinel_key = f"_inflight:fact:global:{fact_id}"
        sentinel_acquired = await self.mw_manager.try_set_inflight(
            sentinel_key, ttl_s=5
        )
        if not sentinel_acquired:
            logger.info(
                f"[{self.agent_id}] Another worker is fetching {fact_id}, waiting briefly..."
            )
            # Wait briefly for the other worker to complete
            await asyncio.sleep(0.05)  # Brief backoff
            # Try to get the result that might have been cached
            cached_data = await self.mw_manager.get_item_typed_async(
                "fact", "global", fact_id
            )
            if cached_data:
                logger.info(
                    f"[{self.agent_id}] ✅ Found '{fact_id}' after waiting (cache hit)."
                )
                try:
                    return (
                        json.loads(cached_data)
                        if isinstance(cached_data, str)
                        else cached_data
                    )
                except json.JSONDecodeError:
                    logger.warning(
                        f"[{self.agent_id}] ⚠️ Failed to parse cached data as JSON"
                    )
                    return {"raw_data": cached_data}
            return None

        try:
            # 1. Query Working Memory (Mw) first using typed key format
            logger.info(f"[{self.agent_id}] 📋 Querying Working Memory (Mw)...")
            try:
                cached_data = await self.mw_manager.get_item_typed_async(
                    "fact", "global", fact_id
                )

                if cached_data:
                    logger.info(
                        f"[{self.agent_id}] ✅ Found '{fact_id}' in Mw (cache hit)."
                    )
                    try:
                        return (
                            json.loads(cached_data)
                            if isinstance(cached_data, str)
                            else cached_data
                        )
                    except json.JSONDecodeError:
                        logger.warning(
                            f"[{self.agent_id}] ⚠️ Failed to parse cached data as JSON"
                        )
                        return {"raw_data": cached_data}
            except Exception as e:
                logger.error(f"[{self.agent_id}] ❌ Error querying Mw: {e}")

            # 2. On a miss, escalate to Long-Term Memory (Mlt)
            logger.info(
                f"[{self.agent_id}] ⚠️ '{fact_id}' not in Mw (cache miss). Escalating to Mlt..."
            )

            # --- ASYNC FIX ---
            long_term_data = await self.mlt_manager.query_holon_by_id_async(fact_id)

            if long_term_data:
                logger.info(f"[{self.agent_id}] ✅ Found '{fact_id}' in Mlt.")

                # 3. Cache the retrieved data back into Mw
                logger.info(f"[{self.agent_id}] 💾 Caching '{fact_id}' back to Mw...")
                try:
                    self.mw_manager.set_global_item_typed(
                        "fact", "global", fact_id, long_term_data, ttl_s=900
                    )
                except Exception as e:
                    logger.error(f"[{self.agent_id}] ❌ Failed to cache to Mw: {e}")

                return long_term_data
            else:
                # On total miss: write negative cache
                logger.info(
                    f"[{self.agent_id}] ❌ '{fact_id}' not found in Mlt. Setting negative cache."
                )
                try:
                    self.mw_manager.set_negative_cache(
                        "fact", "global", fact_id, ttl_s=30
                    )
                except Exception as e:
                    logger.error(
                        f"[{self.agent_id}] ❌ Failed to set negative cache: {e}"
                    )

                return None
        except Exception as e:
            logger.error(f"[{self.agent_id}] ❌ Error querying Mlt: {e}")
            return None
        finally:
            # Always clear in-flight sentinel
            try:
                # --- ASYNC FIX ---
                await self.mw_manager.del_global_key(sentinel_key)
            except Exception:
                pass

        logger.warning(
            f"[{self.agent_id}] 🚨 Could not find '{fact_id}' in any memory tier."
        )
        return None

    async def execute_collaborative_task(
        self, task_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Simulates executing a collaborative task that may require finding knowledge.
        This method implements the core logic for Scenario 1.

        Args:
            task_info: Dictionary containing task information including required_fact

        Returns:
            Dict[str, Any]: Task execution result with success status and details
        """
        task_name = task_info.get("name", "Unknown Task")
        required_fact = task_info.get("required_fact")

        logger.info(
            f"[{self.agent_id}] 🚀 Starting collaborative task '{task_name}'..."
        )

        # Capture energy before task execution
        E_before = self._energy_slice()

        knowledge = None
        if required_fact:
            logger.info(f"[{self.agent_id}] 📚 Task requires fact: {required_fact}")
            knowledge = await self.find_knowledge(required_fact)  # No await needed

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

        # 4. Update internal performance metrics (Ma)
        self.update_performance(
            success=success, quality=quality, task_metadata=task_info
        )

        # Update memory utilization based on task complexity
        task_complexity = task_info.get("complexity", 0.5)
        self.mem_util = min(1.0, self.mem_util + task_complexity * 0.1)

        # Calculate energy after task execution
        E_after = self._energy_slice()
        delta_e = E_after - E_before

        result = {
            "agent_id": self.agent_id,
            "task_name": task_name,
            "task_processed": True,
            "success": success,
            "quality": quality,
            "capability_score": self.capability_score,
            "mem_util": self.mem_util,
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
        # Use new normalized helpers
        self._mw_put_json_local(artifact_key, artifact)  # L0 for immediate local use
        self._mw_put_json_global(
            "collab_task", "global", artifact_key, artifact, ttl_s=900
        )
        if success and quality >= 0.8:
            await self._promote_to_mlt(artifact_key, artifact, compression=True)

        return result

    def _get_system_load(self) -> float:
        """Get current system load from energy state."""
        try:
            energy_state = self.get_energy_state()
            # Normalize energy state to system load (0-1)
            total_energy = sum(energy_state.values())
            return min(total_energy / 10.0, 1.0)  # Normalize to 0-1 range
        except:
            return 0.5

    def _get_memory_usage(self) -> float:
        """Get current memory usage."""
        try:
            return self.mem_util
        except:
            return 0.5

    def _get_cpu_usage(self) -> float:
        """Get current CPU usage estimate."""
        try:
            # Estimate CPU usage based on agent activity
            tasks_processed = getattr(self, "tasks_processed", 0)
            return min(tasks_processed / 100.0, 1.0)
        except:
            return 0.5

    def _get_response_time(self) -> float:
        """Get current response time estimate."""
        try:
            # Estimate response time based on recent performance
            quality_scores = getattr(self, "quality_scores", [])
            if quality_scores:
                avg_quality = sum(quality_scores) / len(quality_scores)
                # Lower quality = higher response time
                return max(0.1, 2.0 - avg_quality)
            return 1.0
        except:
            return 1.0

    def _get_error_rate(self) -> float:
        """Get current error rate."""
        try:
            tasks_processed = getattr(self, "tasks_processed", 0)
            successful_tasks = getattr(self, "successful_tasks", 0)
            if tasks_processed > 0:
                return (tasks_processed - successful_tasks) / tasks_processed
            return 0.0
        except:
            return 0.0

    def _classify_error_type(self, error_reason: str) -> float:
        """Classify error type for feature extraction."""
        error_reason_lower = error_reason.lower()

        if "timeout" in error_reason_lower:
            return 0.8  # High severity for timeouts
        elif "connection" in error_reason_lower:
            return 0.7  # Medium-high for connection issues
        elif "permission" in error_reason_lower:
            return 0.6  # Medium for permission issues
        elif "validation" in error_reason_lower:
            return 0.4  # Lower for validation errors
        else:
            return 0.5  # Default severity

    def _fallback_salience_scorer(self, features_list: List[dict]) -> List[float]:
        """Fallback salience scorer when ML service is unavailable."""
        scores = []
        for features in features_list:
            # Simple heuristic-based scoring (original method)
            task_risk = features.get("task_risk", 0.5)
            failure_severity = features.get("failure_severity", 0.5)
            score = task_risk * failure_severity

            # Add some context from other features
            agent_capability = features.get("agent_capability", 0.5)
            system_load = features.get("system_load", 0.5)

            # Adjust score based on agent capability and system load
            score *= (
                1.0 + (1.0 - agent_capability) * 0.2
            )  # Higher score for lower capability
            score *= 1.0 + system_load * 0.1  # Higher score under high load

            scores.append(max(0.0, min(1.0, score)))

        return scores

    async def start_heartbeat_loop(self, interval_seconds: int = 10):
        """
        Starts a loop to periodically emit heartbeats.
        This runs as a background task within the actor.

        Args:
            interval_seconds: Interval between heartbeats
        """
        logger.info(
            f"❤️ Agent {self.agent_id} starting heartbeat loop every {interval_seconds}s"
        )

        while True:
            try:
                heartbeat = await self.get_heartbeat()
                # In a real system, you would publish this to Redis Pub/Sub
                # or send it to a central telemetry service
                logger.info(
                    f"HEARTBEAT from {self.agent_id}: capability={heartbeat['performance_metrics']['capability_score_c']:.3f}"
                )

                # Light-touch hot-item prewarming with rate limiting
                if self.mw_manager and random.random() < 0.1:
                    # Reset rate limit counter every minute
                    now = time.time()
                    if now - self._prewarm_reset_time > 60:
                        self._prewarm_count = 0
                        self._prewarm_reset_time = now

                    # Check rate limit
                    if self._prewarm_count < self._max_prewarm_per_minute:
                        try:
                            hot_items = await self.mw_manager.get_hot_items_async(
                                top_n=5
                            )
                            for item_id, _cnt in hot_items:
                                # Touch into L0 via get_item_async (promotes if present in L1/L2)
                                _ = await self.mw_manager.get_item_async(item_id)
                                self._prewarm_count += 1
                            if hot_items:
                                logger.debug(
                                    f"[{self.agent_id}] Pre-warmed {len(hot_items)} hot items"
                                )
                        except Exception as e:
                            logger.debug(
                                f"[{self.agent_id}] Hot-item prewarming failed: {e}"
                            )

                # Log cache telemetry every 10th heartbeat
                if self.mw_manager and self.tasks_processed % 10 == 0:
                    try:
                        telemetry = self.mw_manager.get_telemetry()
                        logger.info(f"[{self.agent_id}] Cache telemetry: {telemetry}")
                    except Exception as e:
                        logger.debug(f"[{self.agent_id}] Telemetry logging failed: {e}")

                await asyncio.sleep(interval_seconds)
            except Exception as e:
                logger.error(f"Error in heartbeat loop for {self.agent_id}: {e}")
                await asyncio.sleep(interval_seconds)

    async def _start_registry_reporting(self):
        """Start optional registry reporting with graceful fallback."""
        if not self._registry:
            return
        try:
            await self._registry.register()
            await self._registry.set_status("alive")
            logger.info(f"✅ Agent {self.agent_id} registered with runtime registry")
        except Exception as e:
            logger.debug(f"Registry register failed for {self.agent_id}: {e}")
            return

        async def _beat_loop():
            """Background task for sending registry heartbeats."""
            while True:
                try:
                    await self._registry.beat()
                except Exception:
                    # Non-fatal - registry may be temporarily unavailable
                    pass
                await asyncio.sleep(float(os.getenv("REGISTRY_BEAT_SEC", "5")))

        # Start the heartbeat loop as a background task
        asyncio.create_task(_beat_loop())
        logger.info(f"✅ Agent {self.agent_id} started registry heartbeat reporting")

    async def start(self):
        """Start the agent with all background services."""
        # Start the existing heartbeat loop
        await self.start_heartbeat_loop()

        # Start registry reporting if enabled
        await self._start_registry_reporting()

    def reset_metrics(self):
        """Reset all performance metrics (for testing/debugging)."""
        self.tasks_processed = 0
        self.successful_tasks = 0
        self.quality_scores.clear()
        self.task_history.clear()
        self.capability_score = 0.5
        self.mem_util = 0.0
        try:
            self.state.reset_rolling()
        except Exception:
            pass
        self.memory_writes = 0
        self.memory_hits_on_writes = 0
        self.salient_events_logged = 0
        self.total_compression_gain = 0.0
        self.skill_deltas.clear()
        self.peer_interactions.clear()

        # Rate limiting for prewarm
        self._prewarm_count = 0
        self._prewarm_reset_time = time.time()
        self._max_prewarm_per_minute = 10
        logger.info(f"🔄 Agent {self.agent_id} metrics reset")

    # =============================================================================
    # Cognitive Reasoning Methods
    # =============================================================================

    async def reason_about_failure(self, incident_id: str) -> Dict[str, Any]:
        """
        Analyze agent failures using cognitive reasoning.

        Args:
            incident_id: ID of the incident to analyze

        Returns:
            Dictionary containing analysis results
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
                knowledge_context=self._get_memory_context(),  # optional enrich
            )
            norm = self._normalize_cog_resp(resp)
            payload = norm["payload"]

            # Calculate energy cost for reasoning
            reg_delta = 0.01 * len(str(payload.get("thought", "")))

            # Update energy state
            current_energy = self.get_energy_state()
            current_energy["cognitive_cost"] = (
                current_energy.get("cognitive_cost", 0.0) + reg_delta
            )
            self.update_energy_state(current_energy)

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

    async def make_decision(
        self, decision_context: Dict[str, Any], historical_data: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Make decisions using cognitive reasoning.

        Args:
            decision_context: Context for the decision
            historical_data: Historical data to inform the decision

        Returns:
            Dictionary containing decision results
        """
        if not self._cog:
            return {"success": False, "reason": "Cognitive service not available."}

        try:
            # Call cognitive service via HTTP client
            resp = await self._cog.make_decision(
                agent_id=self.agent_id,
                decision_context=decision_context,
                historical_data=historical_data or {},
                knowledge_context=self._get_memory_context(),
            )
            norm = self._normalize_cog_resp(resp)
            payload = norm["payload"]

            return {
                "success": True,
                "agent_id": self.agent_id,
                "reasoning": payload.get("reasoning", ""),
                "decision": payload.get("decision", ""),
                "confidence": payload.get("confidence", 0.0),
                "meta": norm["meta"],
                "error": norm["error"],
                "alternative_options": payload.get("alternative_options", ""),
            }

        except Exception as e:
            logger.error(f"Error in decision making for agent {self.agent_id}: {e}")
            return {"success": False, "agent_id": self.agent_id, "error": str(e)}

    async def synthesize_memory(
        self, memory_fragments: List[Dict[str, Any]], synthesis_goal: str
    ) -> Dict[str, Any]:
        """
        Synthesize information from multiple memory sources.

        Args:
            memory_fragments: List of memory fragments to synthesize
            synthesis_goal: Goal of the synthesis

        Returns:
            Dictionary containing synthesis results
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

    async def assess_capabilities(
        self, target_capabilities: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Assess agent capabilities and suggest improvements.

        Args:
            target_capabilities: Target capabilities to assess against

        Returns:
            Dictionary containing assessment results
        """
        if not self._cog:
            return {"success": False, "reason": "Cognitive service not available."}

        try:
            # Call cognitive service via HTTP client
            resp = await self._cog.assess_capabilities(
                agent_id=self.agent_id,
                performance_data=self._get_performance_data(),
                current_capabilities=self._get_agent_capabilities(),
                target_capabilities=target_capabilities or {},
            )
            norm = self._normalize_cog_resp(resp)
            payload = norm["payload"]

            return {
                "success": True,
                "agent_id": self.agent_id,
                "capability_gaps": payload.get("capability_gaps", ""),
                "improvement_plan": payload.get("improvement_plan", ""),
                "priority_recommendations": payload.get("priority_recommendations", ""),
                "meta": norm["meta"],
                "error": norm["error"],
            }

        except Exception as e:
            logger.error(
                f"Error in capability assessment for agent {self.agent_id}: {e}"
            )
            return {"success": False, "agent_id": self.agent_id, "error": str(e)}

    # =============================================================================
    # Helper Methods for Cognitive Context
    # =============================================================================

    def _get_memory_context(self) -> Dict[str, Any]:
        """Get memory context for cognitive tasks."""
        return {
            "memory_utilization": self.mem_util,
            "memory_writes": self.memory_writes,
            "memory_hits": self.memory_hits_on_writes,
            "compression_gain": self.total_compression_gain,
            "skill_deltas": self.skill_deltas.copy(),
        }

    def _get_lifecycle_context(self) -> Dict[str, Any]:
        """Get lifecycle context for cognitive tasks."""
        return {
            "agent_id": self.agent_id,
            "created_at": self.created_at,
            "last_heartbeat": self.last_heartbeat,
            "capability_score": self.capability_score,
            "role_probabilities": self.role_probs.copy(),
            "tasks_processed": self.tasks_processed,
            "successful_tasks": self.successful_tasks,
        }

    def _get_agent_capabilities(self) -> Dict[str, Any]:
        """Get current agent capabilities."""
        return {
            "capability_score": self.capability_score,
            "role_probabilities": self.role_probs.copy(),
            "skill_deltas": self.skill_deltas.copy(),
            "performance_history": {
                "tasks_processed": self.tasks_processed,
                "successful_tasks": self.successful_tasks,
                "avg_quality": sum(self.quality_scores) / len(self.quality_scores)
                if self.quality_scores
                else 0.0,
            },
        }

    def _summarize_agent_capabilities(self) -> str:
        """
        Convert internal agent capabilities dict into a stable, human-readable string
        so CognitiveService can inject it directly into prompts.
        """
        caps = self._get_agent_capabilities()
        if not isinstance(caps, dict):
            return str(caps)

        lines: List[str] = ["Agent capabilities:"]
        for key, value in caps.items():
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    def _get_performance_data(self) -> Dict[str, Any]:
        """Get performance data for capability assessment."""
        return {
            "tasks_processed": self.tasks_processed,
            "successful_tasks": self.successful_tasks,
            "quality_scores": self.quality_scores.copy(),
            "capability_score": self.capability_score,
            "memory_utilization": self.mem_util,
            "peer_interactions": self.peer_interactions.copy(),
        }
