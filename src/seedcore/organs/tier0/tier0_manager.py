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
Tier 0 Memory Manager
Manages Ray agents and collects heartbeats for the meta-controller.
"""

from seedcore.logging_setup import setup_logging
setup_logging(app_name="seedcore.Tier0MemoryManager")


import os
import ray
import time
import uuid
import asyncio
import concurrent.futures
from ...utils.ray_utils import ensure_ray_initialized
from typing import Dict, List, Any, Optional, Union
from collections import defaultdict
import logging
import json

from ...agents.ray_agent import RayAgent
from ...models import TaskPayload
from ...agents.roles import RoleRegistry, DEFAULT_ROLE_REGISTRY, SkillStoreProtocol, NullSkillStore
from ...ops.energy.optimizer import select_best_agent, score_agent
from .specs import GraphClient, AgentSpec
from ...registry import list_active_instances
# Avoid importing EnergyLedger at module import time to prevent circular imports.
# We'll import it inside functions that need it.

# --- Import New Memory Managers ---
# These are the clients that will be passed to the agents
from ...memory.mw_manager import MwManager
from ...memory.long_term_memory import LongTermMemoryManager

logger = logging.getLogger("seedcore.Tier0MemoryManager")

# Target namespace for agent actors (prefer SEEDCORE_NS, fallback to RAY_NAMESPACE)
AGENT_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))

# Non-blocking ray.get helper (module scope)
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=int(os.getenv("TIER0_TP_MAX", "8"))
)

async def _aget(obj_ref, timeout: float = 2.0):
    """Non-blocking ray.get with timeout using thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_EXECUTOR, lambda: ray.get(obj_ref, timeout=timeout))

class Tier0MemoryManager:
    """
    Manages Tier 0 per-agent memory (Ma) using Ray actors.
    
    Responsibilities:
    - Create and manage Ray agent actors
    - Inject memory manager clients (MwManager, LongTermMemoryManager) into agents
    - Collect heartbeats and stats from all agents
    - Provide an async API for task execution
    """
    
    def __init__(
        self,
        mw_manager: MwManager,
        ltm_manager: LongTermMemoryManager,
        *,
        role_registry: Optional[RoleRegistry] = None,
        skill_store: Optional[SkillStoreProtocol] = None,
    ):
        """
        Initialize with memory manager clients.
        
        Args:
            mw_manager: The MwManager (Tier 1) client instance.
            ltm_manager: The LongTermMemoryManager (Tier 2) client instance.
        """
        self.agents: Dict[str, Any] = {}  # agent_id -> Ray actor handle
        self.heartbeats: Dict[str, Dict[str, Any]] = {}  # agent_id -> latest heartbeat
        self.agent_stats: Dict[str, Dict[str, Any]] = {}  # agent_id -> summary stats
        self.last_collection = time.time()
        self.collection_interval = 5.0  # seconds
        
        # --- Store the memory manager clients ---
        self.mw_manager = mw_manager
        self.ltm_manager = ltm_manager
        self.role_registry = role_registry or DEFAULT_ROLE_REGISTRY
        self.skill_store = skill_store or NullSkillStore()
        
        # Track transient ping failures to avoid pruning on single hiccup
        self._ping_failures: Dict[str, int] = {}
        # Graph client for desired-state reconciliation
        self._graph: Optional[GraphClient] = None
        
        logger.info("✅ Tier0MemoryManager initialized with memory clients")
        
        # Best-effort auto-discovery on init so that detached Ray actors get picked up
        try:
            self._refresh_agents_from_cluster()
        except Exception as e:
            logger.debug(f"Auto-discovery on init skipped: {e}")

        # Optional environment-driven attachment of known actor names
        try:
            import os
            attach_env = os.getenv("TIER0_ATTACH_ACTORS", "").strip()
            if attach_env:
                self._ensure_ray()
                # Support comma/semicolon/space-separated lists
                raw_parts = [p for sep in [",", ";", " "] for p in attach_env.split(sep)]
                candidate_names = [p.strip() for p in raw_parts if p and p.strip()]
                attached = 0
                for actor_name in candidate_names:
                    try:
                        # Try explicit namespace first (prefer SEEDCORE_NS), then fallback
                        try:
                            ns = AGENT_NAMESPACE
                            handle = ray.get_actor(actor_name, namespace=ns)
                        except Exception:
                            # Fallback to explicit namespace (prefer SEEDCORE_NS)
                            ns = AGENT_NAMESPACE
                            handle = ray.get_actor(actor_name, namespace=ns)
                        # Sanity check
                        resolved_id = ray.get(handle.get_id.remote())
                        self.attach_existing_actor(resolved_id, handle)
                        attached += 1
                    except Exception as e:
                        logger.debug(f"Env attach failed for {actor_name}: {e}")
                if attached:
                    logger.info(f"🔗 Attached {attached} actor(s) from TIER0_ATTACH_ACTORS")
        except Exception as e:
            logger.debug(f"Env-driven attachment skipped: {e}")
    
    def _prepare_task_payload(self, task: Union[TaskPayload, Dict[str, Any]]) -> Dict[str, Any]:
        """Normalize task payloads and preserve additional fields for agent execution."""
        extra_fields: Dict[str, Any] = {}

        if isinstance(task, TaskPayload):
            payload = task
            task_dict = payload.model_dump()
        elif isinstance(task, dict):
            raw_task = dict(task)
            try:
                payload = TaskPayload.from_db(raw_task)
            except Exception as exc:
                logger.debug(
                    "Tier0MemoryManager: TaskPayload.from_db fallback due to %s; constructing payload directly",
                    exc,
                )
                fallback_id = raw_task.get("task_id") or raw_task.get("id") or uuid.uuid4().hex
                payload = TaskPayload(
                    task_id=str(fallback_id),
                    type=raw_task.get("type") or "unknown_task",
                    params=raw_task.get("params") or {},
                    description=raw_task.get("description") or "",
                    domain=raw_task.get("domain"),
                    drift_score=float(raw_task.get("drift_score") or 0.0),
                )
            task_dict = payload.model_dump()
            extra_fields = {k: v for k, v in raw_task.items() if k not in task_dict}
        else:
            raise TypeError(f"Unsupported task payload type: {type(task)}")

        task_id = payload.task_id or uuid.uuid4().hex
        if not payload.task_id or payload.task_id in ("", "None"):
            payload = payload.copy(update={"task_id": task_id})
            task_dict = payload.model_dump()

        for key, value in extra_fields.items():
            if key not in task_dict:
                task_dict[key] = value

        task_dict.setdefault("id", task_id)
        task_dict.setdefault("task_id", task_id)
        return task_dict
    
    def create_agent(
        self,
        agent_id: str,
        role_probs: Optional[Dict[str, float]] = None,
        *,
        name: Optional[str] = None,
        lifetime: Optional[str] = None,
        num_cpus: Optional[float] = None,
        num_gpus: Optional[float] = None,
        resources: Optional[Dict[str, float]] = None,
        namespace: Optional[str] = None,
        organ_id: Optional[str] = None,
    ) -> str:
        """
        Create a new Ray agent actor (idempotent - reuses existing named actors).
        
        Args:
            agent_id: Unique identifier for the agent
            role_probs: Initial role probabilities
            organ_id: ID of the organ this agent belongs to
            
        Returns:
            The agent ID if successful
        """
        if agent_id in self.agents:
            logger.warning(f"Agent {agent_id} already exists in registry")
            return agent_id

        try:
            # Ensure Ray first
            self._ensure_ray()

            # Build Ray options once
            options_kwargs: Dict[str, Any] = {}
            effective_name = name or agent_id  # stable name by default
            options_kwargs["name"] = effective_name
            options_kwargs["lifetime"] = lifetime or "detached"
            if num_cpus is not None:
                options_kwargs["num_cpus"] = num_cpus
            if num_gpus is not None:
                options_kwargs["num_gpus"] = num_gpus
            if resources:
                options_kwargs["resources"] = resources

            # Namespace from arg → env → default
            ns = (
                namespace
                or os.getenv("SEEDCORE_NS")
                or os.getenv("RAY_NAMESPACE")
                or AGENT_NAMESPACE
            )
            options_kwargs["namespace"] = ns

            # --- Reuse existing named actor if present ---
            try:
                handle = ray.get_actor(effective_name, namespace=ns)
                resolved_id = ray.get(handle.get_id.remote())
                self.attach_existing_actor(resolved_id, handle)
                logger.info(f"🔗 Reused existing actor '{effective_name}' in ns='{ns}'")
                return resolved_id
            except Exception:
                # Not found; proceed to create fresh
                pass

            # --- Create fresh actor ---
            #
            # ENHANCEMENT: Pass the memory manager clients to the
            # RayAgent's constructor. This assumes RayAgent.__init__
            # now accepts mw_manager and ltm_manager.
            #
            agent_handle = RayAgent.options(**options_kwargs).remote(
                agent_id=agent_id,
                initial_role_probs=role_probs,
                organ_id=organ_id,
                role_registry=self.role_registry,
                skill_store=self.skill_store,
                mw_manager=self.mw_manager,
                ltm_manager=self.ltm_manager,
            )
            self.agents[agent_id] = agent_handle
            self.heartbeats[agent_id] = {}
            self.agent_stats[agent_id] = {}

            logger.info(f"✅ Created Ray agent: {agent_id} (name='{effective_name}', ns='{ns}')")
            return agent_id

        except Exception as e:
            logger.error(f"Failed to create/attach agent {agent_id}: {e}")
            try:
                _is_init = getattr(ray, "is_initialized", None)
                init_state = _is_init() if callable(_is_init) else True
            except Exception:
                init_state = True
            logger.error(f"Ray initialized: {init_state}")
            if init_state:
                try:
                    runtime_context = ray.get_runtime_context()
                    logger.error(f"Ray namespace: {getattr(runtime_context, 'namespace', 'unknown')}")
                    logger.error(f"Ray address: {getattr(runtime_context, 'gcs_address', 'unknown')}")
                except Exception as ctx_e:
                    logger.error(f"Failed to get Ray context: {ctx_e}")
            raise
    
    def create_agents_batch(self, agent_configs: List[Dict[str, Any]]) -> List[str]:
        """
        Create multiple agents in batch.
        
        Args:
            agent_configs: List of agent configurations
                [{"agent_id": "agent_1", "role_probs": {...}}, ...]
                
        Returns:
            List of created agent IDs
        """
        created_ids = []
        for config in agent_configs:
            agent_id = config["agent_id"]
            role_probs = config.get("role_probs")
            # Optional Ray options passthrough
            name = config.get("name")
            lifetime = config.get("lifetime")
            num_cpus = config.get("num_cpus")
            num_gpus = config.get("num_gpus")
            resources = config.get("resources")
            namespace = config.get("namespace")
            try:
                self.create_agent(
                    agent_id,
                    role_probs,
                    name=name,
                    lifetime=lifetime,
                    num_cpus=num_cpus,
                    num_gpus=num_gpus,
                    resources=resources,
                    namespace=namespace,
                )
                created_ids.append(agent_id)
            except Exception as e:
                logger.error(f"Failed to create agent {agent_id}: {e}")
        
        logger.info(f"✅ Created {len(created_ids)} agents in batch")
        return created_ids
    
    def get_agent(self, agent_id: str) -> Optional[Any]:
        """
        Get a Ray agent actor handle.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            Ray actor handle or None if not found
        """
        return self.agents.get(agent_id)
    
    def list_agents(self) -> List[str]:
        """Get list of all agent IDs.
        
        If no local registrations exist, attempt to discover agents from:
        1. Runtime registry (PostgreSQL) - preferred
        2. Ray cluster scan - fallback
        """
        # Prefer returning only alive agents and refresh if registry is empty
        try:
            if not self.agents:
                # Fall back to Ray cluster scan (registry discovery is async)
                self._refresh_agents_from_cluster()
        except Exception as e:
            logger.debug(f"Agent discovery failed during list: {e}")
        alive = self.prune_and_list()
        return [a["id"] for a in alive]

    # Health-aware listing and pruning
    def _alive(self, handle: Any) -> bool:
        """Faster liveness check using ray.wait for early returns."""
        try:
            ready, _ = ray.wait([handle.ping.remote()], timeout=2.0)
            return bool(ready)
        except Exception:
            return False

    def prune_and_list(self) -> List[Dict[str, Any]]:
        """Remove dead handles and return a simple list of alive agent ids."""
        if not self.agents:
            try:
                self._refresh_agents_from_cluster()
            except Exception as e:
                logger.debug(f"Agent discovery failed during prune: {e}")
        live: Dict[str, Any] = {}
        for agent_id, handle in list(self.agents.items()):
            if self._alive(handle):
                live[agent_id] = handle
                self._ping_failures[agent_id] = 0
            else:
                fails = self._ping_failures.get(agent_id, 0) + 1
                self._ping_failures[agent_id] = fails
                if fails >= 3:
                    logger.warning(f"Archiving agent after {fails} consecutive ping failures: {agent_id}")
                    try:
                        handle = self.agents.get(agent_id)
                        if handle and hasattr(handle, "archive"):
                            ray.get(handle.archive.remote())
                    except Exception:
                        logger.exception("archive() failed; detaching actor reference.")
                    finally:
                        self.agents.pop(agent_id, None)
                        self.heartbeats.pop(agent_id, None)
                        self.agent_stats.pop(agent_id, None)
        return [{"id": aid} for aid in live.keys()]

    # ---------------------------------------------------------------------
    # Cluster discovery and attachment helpers
    # ---------------------------------------------------------------------
    def attach_existing_actor(self, agent_id: str, handle: Any) -> None:
        """Attach a known Ray actor handle into the manager registry."""
        if agent_id not in self.agents:
            self.agents[agent_id] = handle
            self.heartbeats.setdefault(agent_id, {})
            self.agent_stats.setdefault(agent_id, {})

    def _ensure_ray(self, ray_address: Optional[str] = None, ray_namespace: Optional[str] = None):
        """
        Ensure Ray is initialized, with exponential backoff.
        Prefers explicit args; falls back to env, then cluster defaults.
        """
        import ray

        try:
            _is_init = getattr(ray, "is_initialized", None)
            if callable(_is_init) and _is_init():
                # Additional sanity check: verify Ray is actually functional
                try:
                    ray.cluster_resources()
                    return
                except Exception:
                    # Ray is initialized but not functional - reset it
                    logger.warning("Ray is initialized but not functional, resetting...")
                    ray.shutdown()
        except Exception:
            # If the mock ray lacks is_initialized, continue with init attempts
            pass

        # Namespace: SEEDCORE_NS → RAY_NAMESPACE → default
        ray_namespace = (
            ray_namespace
            or os.getenv("SEEDCORE_NS")
            or os.getenv("RAY_NAMESPACE")
            or "seedcore-dev"
        )

        # Address: prefer explicit; otherwise build from env or sane cluster defaults
        if ray_address is None:
            addr_env = os.getenv("RAY_ADDRESS")
            if addr_env:
                ray_address = addr_env.strip()
            else:
                ray_host = os.getenv("RAY_HOST", "seedcore-svc-head-svc")
                ray_port = os.getenv("RAY_PORT", "10001")
                ray_address = f"ray://{ray_host}:{ray_port}"

        delay = 0.5
        max_attempts = 6
        for attempt in range(1, max_attempts + 1):
            logger.info(f"Connecting to Ray at {ray_address} (ns={ray_namespace}), attempt {attempt}/{max_attempts}")
            if ensure_ray_initialized(ray_address=ray_address, ray_namespace=ray_namespace):
                logger.info("✅ Ray connection established")
                return
            time.sleep(delay)
            delay *= 2

        raise RuntimeError(f"Failed to initialize Ray (address={ray_address}, ns={ray_namespace})")

    def _refresh_agents_from_cluster(self) -> None:
        """Discover and attach existing RayAgent actors from the Ray cluster.
        
        This picks up detached, named Ray actors of class RayAgent that may
        have been started by other components (e.g., organisms) and registers
        them into this manager so API endpoints can see them.
        """
        self._ensure_ray()

        discovered: Dict[str, Any] = {}

        # Prefer public Ray state API when available
        try:
            # Ray 2.x public state API
            from ray.util.state import list_actors  # type: ignore
            actor_infos = list_actors()
            for info in actor_infos:
                try:
                    # Support both object-style and dict-style info
                    state_val = getattr(info, "state", None) if not isinstance(info, dict) else info.get("state")
                    state_str = str(state_val).upper() if state_val is not None else ""
                    if state_str and "ALIVE" not in state_str:
                        continue

                    name = (
                        getattr(info, "name", None)
                        if not isinstance(info, dict)
                        else info.get("name") or info.get("actor_name")
                    )
                    class_name = (
                        getattr(info, "class_name", None)
                        if not isinstance(info, dict)
                        else info.get("class_name") or (info.get("classDescriptor") or {}).get("class_name")
                    )
                    namespace = (
                        getattr(info, "namespace", None)
                        if not isinstance(info, dict)
                        else info.get("namespace")
                    )
                    if name and class_name and str(class_name).endswith("RayAgent"):
                        try:
                            handle = None
                            # Try resolve with namespace first if present
                            if namespace:
                                try:
                                    handle = ray.get_actor(name=name, namespace=namespace)
                                except Exception:
                                    handle = None
                            # Fallback to explicit namespace (prefer SEEDCORE_NS)
                            if handle is None:
                                ns = AGENT_NAMESPACE
                                handle = ray.get_actor(name, namespace=ns)
                            discovered[name] = handle
                        except Exception:
                            # Could be in a different namespace; skip if not retrievable
                            continue
                except Exception:
                    continue
        except Exception:
            # Fallback to private API (older Ray)
            try:
                from ray._private.state import actors  # type: ignore
                actor_infos = actors()
                for _, info in actor_infos.items():
                    try:
                        # info is a dict-like
                        name = info.get("Name") or info.get("name")
                        class_name = info.get("ClassName") or info.get("class_name")
                        state = info.get("State") or info.get("state")
                        namespace = info.get("Namespace") or info.get("namespace")
                        if state != "ALIVE":
                            continue
                        if name and class_name and class_name.endswith("RayAgent"):
                            try:
                                handle = None
                                if namespace:
                                    try:
                                        handle = ray.get_actor(name=name, namespace=namespace)
                                    except Exception:
                                        handle = None
                                if handle is None:
                                    # Use explicit namespace (prefer SEEDCORE_NS)
                                    ns = AGENT_NAMESPACE
                                    handle = ray.get_actor(name, namespace=ns)
                                discovered[name] = handle
                            except Exception:
                                continue
                    except Exception:
                        continue
            except Exception as e:
                logger.debug(f"Ray private state API not available: {e}")

        # Merge discovered into registry without overriding existing entries
        newly_attached = 0
        for agent_id, handle in discovered.items():
            if agent_id not in self.agents:
                self.agents[agent_id] = handle
                # Initialize caches for newly attached
                self.heartbeats.setdefault(agent_id, {})
                self.agent_stats.setdefault(agent_id, {})
                newly_attached += 1

        if newly_attached:
            logger.info(f"🔎 Attached {newly_attached} existing RayAgent(s) from cluster: {list(discovered.keys())}")

    async def discover_from_registry(self):
        """
        Discover and attach agents from the runtime registry.
        
        Queries the active_instance view to find registered agents and attaches
        their Ray actor handles. Falls back gracefully if registry is unavailable.
        """
        try:
            rows = await list_active_instances()  # one per logical_id
            attached = 0
            for r in rows:
                name = r.get("actor_name")
                lid = r.get("logical_id")
                if not name or not lid:
                    continue
                try:
                    handle = ray.get_actor(name, namespace=AGENT_NAMESPACE)
                    # Attach with logical_id so API can address by data-layer identity
                    self.attach_existing_actor(lid, handle)
                    attached += 1
                except Exception:
                    continue
            if attached:
                logger.info(f"🔗 Attached {attached} agent(s) from registry view")
        except Exception as e:
            logger.debug(f"Registry discovery skipped: {e}")

    async def discover_and_refresh_agents(self):
        """
        Discover agents from registry and refresh from Ray cluster.
        
        This method can be called from async contexts to perform both
        registry-based and Ray cluster-based discovery.
        """
        # Try registry discovery first
        await self.discover_from_registry()
        
        # If still no agents, try Ray cluster scan as fallback
        if not self.agents:
            try:
                self._refresh_agents_from_cluster()
            except Exception as e:
                logger.debug(f"Ray cluster discovery failed: {e}")
    
    async def execute_task_on_agent(self, agent_id: str, task_data: Union[TaskPayload, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Asynchronously execute a task on a specific agent.
        
        Args:
            agent_id: Agent to execute the task on
            task_data: Task information and payload
            
        Returns:
            Task execution result or None if agent not found
        """
        agent = self.get_agent(agent_id)
        if not agent:
            logger.warning(f"Agent {agent_id} not found")
            return None
        
        try:
            prepared_task = self._prepare_task_payload(task_data)
            # ENHANCEMENT: Use async _aget instead of blocking ray.get
            result = await _aget(agent.execute_task.remote(prepared_task), timeout=120.0)
            logger.info(f"✅ Task executed on agent {agent_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to execute task on agent {agent_id}: {e}")
            return None
    
    async def execute_task_on_random_agent(self, task_data: Union[TaskPayload, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Asynchronously execute a task on a randomly selected agent.
        
        Args:
            task_data: Task information and payload
            
        Returns:
            Task execution result or None if no agents available
        """
        if not self.agents:
            logger.warning("No agents available for task execution")
            return None
        
        import random
        agent_id = random.choice(list(self.agents.keys()))
        # ENHANCEMENT: Await the async method
        return await self.execute_task_on_agent(agent_id, task_data)
    
    async def execute_task_on_best_agent(self, task_data: Union[TaskPayload, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Asynchronously executes a task on the most suitable agent based on energy optimization.
        
        Args:
            task_data: Task information and payload
            
        Returns:
            Task execution result or None if no agents available
        """
        if not self.agents:
            logger.warning("No agents available for task execution")
            return None
        
        # Get all agent actor handles
        agent_handles = list(self.agents.values())
        
        try:
            prepared_task = self._prepare_task_payload(task_data)
            # Use the new energy-aware selection
            best_agent, predicted_delta_e = select_best_agent(agent_handles, prepared_task)
            
            if not best_agent:
                logger.error("Could not select a best agent.")
                return None
            
            # ENHANCEMENT: Use async _aget for execution and ID get
            result_task = _aget(best_agent.execute_task.remote(prepared_task), timeout=120.0)
            id_task = _aget(best_agent.get_id.remote())
            
            result, agent_id = await asyncio.gather(result_task, id_task)
            
            logger.info(f"✅ Energy-aware selection: Chose agent {agent_id} with predicted ΔE of {predicted_delta_e:.4f}")
            return result
            
        except Exception as e:
            logger.warning(f"Energy optimizer failed ({e}), falling back to random selection.")
            # ENHANCEMENT: Await the async method
            return await self.execute_task_on_random_agent(task_data)

    # === COA §6: Local GNN-like selection within an organ (fast path Level 4) ===
    async def execute_task_on_best_of(self, candidate_agent_ids: List[str], task_data: Union[TaskPayload, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Asynchronously execute a task on the best agent selected from a provided candidate set.
        Supports OrganismManager's Level-4 local selection (COA §6.2).
        """
        handles = [self.agents[a] for a in candidate_agent_ids if a in self.agents]
        if not handles:
            logger.warning("No candidate agents available for constrained best-of selection")
            return None
        prepared_task = self._prepare_task_payload(task_data)
        try:
            best_agent, predicted_delta_e = select_best_agent(handles, prepared_task)
            
            # ENHANCEMENT: Use async _aget for execution and ID get
            result_task = _aget(best_agent.execute_task.remote(prepared_task), timeout=120.0)
            id_task = _aget(best_agent.get_id.remote())
            
            result, agent_id = await asyncio.gather(result_task, id_task)
            logger.info(f"✅ Best-of selection: {agent_id} ΔE≈{predicted_delta_e:.4f}")
            return result
        except Exception as e:
            logger.warning(f"Best-of optimizer failed ({e}); falling back to random within candidate set.")
            import random
            handle = random.choice(handles)
            # ENHANCEMENT: Use async _aget
            return await _aget(handle.execute_task.remote(prepared_task), timeout=120.0)

    async def execute_task_on_organ_best(self, organ_id: str, task_data: Union[TaskPayload, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Convenience: select best agent among those belonging to an organ.
        Assumes standard agent naming: f"{organ_id}_agent_{'{'}i{'}'}".
        """
        prefix = f"{organ_id}_agent_"
        candidate_ids = [aid for aid in self.agents.keys() if aid.startswith(prefix)]
        return await self.execute_task_on_best_of(candidate_ids, task_data)
    
    async def collect_heartbeats(self) -> Dict[str, Dict[str, Any]]:
        """
        Collect heartbeats from all agents (non-blocking with timeouts).
        
        Returns:
            Dictionary of agent_id -> heartbeat data
        """
        if not self.agents:
            try:
                self._refresh_agents_from_cluster()
            except Exception as e:
                logger.debug(f"Discovery failed during heartbeat collection: {e}")
            if not self.agents:
                return {}

        timeout = float(os.getenv("TIER0_HEARTBEAT_TIMEOUT", "2.0"))
        items = list(self.agents.items())
        tasks = [ _aget(handle.get_heartbeat.remote(), timeout=timeout) for _, handle in items ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        successes = 0
        for (agent_id, _), res in zip(items, results):
            if isinstance(res, Exception):
                logger.debug(f"Heartbeat error for {agent_id}: {res}")
                continue
            self.heartbeats[agent_id] = res
            successes += 1

        self.last_collection = time.time()
        logger.debug(f"✅ Collected heartbeats: {successes}/{len(items)}")
        return {aid: self.heartbeats[aid] for aid in self.heartbeats}
    
    async def collect_agent_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Collect summary statistics from all agents (non-blocking with timeouts).
        
        Returns:
            Dictionary of agent_id -> summary stats
        """
        if not self.agents:
            return {}

        timeout = float(os.getenv("TIER0_STATS_TIMEOUT", "2.5"))
        items = list(self.agents.items())
        tasks = [ _aget(handle.get_summary_stats.remote(), timeout=timeout) for _, handle in items ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        successes = 0
        for (agent_id, _), res in zip(items, results):
            if isinstance(res, Exception):
                logger.debug(f"Stats error for {agent_id}: {res}")
                continue
            self.agent_stats[agent_id] = res
            successes += 1

        logger.debug(f"✅ Collected stats: {successes}/{len(items)}")
        return {aid: self.agent_stats[aid] for aid in self.agent_stats}
    
    def get_system_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the entire Tier 0 memory system.
        
        Returns:
            System-wide statistics and metrics
        """
        if not self.agent_stats:
            return {"total_agents": 0, "status": "no_agents"}
        
        total_agents = len(self.agent_stats)
        total_tasks = sum(stats.get("tasks_processed", 0) for stats in self.agent_stats.values())
        avg_capability = sum(stats.get("capability_score", 0) for stats in self.agent_stats.values()) / total_agents
        avg_mem_util = sum(stats.get("mem_util", 0) for stats in self.agent_stats.values()) / total_agents
        
        # Calculate system-wide metrics
        total_memory_writes = sum(stats.get("memory_writes", 0) for stats in self.agent_stats.values())
        total_peer_interactions = sum(stats.get("peer_interactions_count", 0) for stats in self.agent_stats.values())
        
        return {
            "total_agents": total_agents,
            "total_tasks_processed": total_tasks,
            "average_capability_score": avg_capability,
            "average_memory_utilization": avg_mem_util,
            "total_memory_writes": total_memory_writes,
            "total_peer_interactions": total_peer_interactions,
            "last_heartbeat_collection": self.last_collection,
            "collection_interval": self.collection_interval,
            "status": "active"
        }

    def get_agent_private_memory(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Returns the agent's private memory vector and telemetry if available.
        Falls back to legacy state.h when telemetry endpoints are unavailable.
        """
        agent = self.get_agent(agent_id)
        if not agent:
            logger.warning(f"Agent {agent_id} not found for private memory fetch")
            return None
        try:
            h = ray.get(agent.get_private_memory_vector.remote())
            tel = ray.get(agent.get_private_memory_telemetry.remote())
            return {"h": h, "telemetry": tel}
        except Exception:
            # Legacy fallback
            try:
                state = ray.get(agent.get_state.remote())
                return {"h": state.get("h")}
            except Exception:
                return None
    
    async def fetch_agent_memory_with_cache(self, agent_id: str, item_id: str) -> Optional[Any]:
        """
        Fetches an item from an agent's perspective, using the
        full cache -> LTM workflow.
        
        Args:
            agent_id: Agent identifier
            item_id: Item identifier to fetch
            
        Returns:
            Fetched data or None if not found
        """
        agent = self.get_agent(agent_id)
        if not agent:
            logger.warning(f"Agent {agent_id} not found for memory fetch")
            return None
        try:
            # ENHANCEMENT: Call the new, unified fetch method on the agent
            # This replaces get_private_memory_vector
            data = await _aget(agent.fetch_with_cache.remote(item_id))
            return data
        except Exception as e:
            logger.error(f"Failed to fetch memory via agent {agent_id}: {e}")
            return None
    
    async def start_heartbeat_monitoring(self, interval_seconds: int = 10):
        """
        Start continuous heartbeat monitoring.
        
        Args:
            interval_seconds: Interval between heartbeat collections
        """
        logger.info(f"❤️ Starting heartbeat monitoring every {interval_seconds}s")
        
        while True:
            try:
                await self.collect_heartbeats()
                await self.collect_agent_stats()
                
                # Log system summary periodically
                summary = self.get_system_summary()
                logger.info(f"📊 Tier 0 Summary: {summary['total_agents']} agents, "
                          f"avg_cap={summary['average_capability_score']:.3f}, "
                          f"total_tasks={summary['total_tasks_processed']}")
                
                await asyncio.sleep(interval_seconds)
                
            except Exception as e:
                logger.error(f"Error in heartbeat monitoring: {e}")
                await asyncio.sleep(interval_seconds)
    
    def get_agent_heartbeat(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the latest heartbeat for a specific agent.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            Heartbeat data or None if not found
        """
        return self.heartbeats.get(agent_id)
    
    def get_all_heartbeats(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all cached heartbeats.
        
        Returns:
            Dictionary of all agent heartbeats
        """
        return self.heartbeats.copy()
    
    def reset_agent_metrics(self, agent_id: str) -> bool:
        """
        Reset metrics for a specific agent.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            True if successful, False otherwise
        """
        agent = self.get_agent(agent_id)
        if not agent:
            return False
        
        try:
            ray.get(agent.reset_metrics.remote())
            logger.info(f"🔄 Reset metrics for agent {agent_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to reset metrics for agent {agent_id}: {e}")
            return False
    
    def shutdown_agents(self):
        """Shutdown all agent actors."""
        if not self.agents:
            return
        
        logger.info(f"🔄 Shutting down {len(self.agents)} agents")
        
        # Clear our caches
        self.heartbeats.clear()
        self.agent_stats.clear()
        
        # The agents will be garbage collected by Ray
        self.agents.clear()
        
        logger.info("✅ All agents shut down")

    # ---------------------------------------------------------------------
    # Graph-aware reconciliation methods
    # ---------------------------------------------------------------------
    
    def attach_graph(self, graph: GraphClient):
        """Attach a graph client for desired-state reconciliation."""
        self._graph = graph
        logger.info("🔗 Graph client attached for reconciliation")

    def reconcile_from_graph(self) -> None:
        """Ensure Ray agents match desired state in the graph."""
        if not self._graph:
            logger.debug("No graph attached; skip reconcile")
            return

        desired: List[AgentSpec] = self._graph.list_agent_specs()
        desired_ids = {s.agent_id for s in desired}
        current_ids = set(self.agents.keys())

        # Create missing agents
        for spec in desired:
            if spec.agent_id not in current_ids:
                logger.info(f"Creating missing agent from graph: {spec.agent_id}")
                self.create_agent(
                    agent_id=spec.agent_id,
                    role_probs=None,
                    name=spec.name,
                    lifetime=spec.lifetime,
                    num_cpus=spec.resources.get("num_cpus"),
                    num_gpus=spec.resources.get("num_gpus"),
                    resources={k: v for k, v in spec.resources.items()
                               if k not in ("num_cpus", "num_gpus")},
                    namespace=spec.namespace,
                    organ_id=spec.organ_id,
                )

        # Optionally retire extra agents (keep conservative by default)
        extras = current_ids - desired_ids
        if extras:
            logger.info(f"Graph reconcile: {len(extras)} unmanaged agent(s) present: {sorted(extras)}")
            # Provide a flag to auto-archive extras if you want strict reconciliation
            if os.getenv("TIER0_STRICT_RECONCILE", "false").lower() == "true":
                for aid in extras:
                    logger.info(f"Archiving unmanaged agent {aid}")
                    try:
                        h = self.agents.get(aid)
                        if h and hasattr(h, "archive"):
                            ray.get(h.archive.remote())
                    except Exception:
                        logger.exception("archive() failed during reconcile")
                    finally:
                        self.agents.pop(aid, None)
                        self.heartbeats.pop(aid, None)
                        self.agent_stats.pop(aid, None)

    def start_graph_reconciler(self, interval: int = 15):
        """Start periodic graph reconciliation."""
        async def _loop():
            while True:
                try:
                    self._ensure_ray()
                    self.reconcile_from_graph()
                except Exception as e:
                    logger.warning(f"Graph reconcile error: {e}")
                await asyncio.sleep(interval)
        asyncio.create_task(_loop())
        logger.info(f"🔄 Started graph reconciler with {interval}s interval")

    # ---------------------------------------------------------------------
    # Graph-aware task routing methods
    # ---------------------------------------------------------------------
    
    def _graph_filter_candidates(self, task_data: Dict[str, Any]) -> List[str]:
        """Return agent_ids that satisfy required skills/models/policies based on the graph."""
        if not self._graph:
            return list(self.agents.keys())

        required_skills = set(task_data.get("required_skills", []))
        required_models = set(task_data.get("required_models", []))
        organ_hint = task_data.get("organ_id")

        # pull desired specs once
        specs = {s.agent_id: s for s in self._graph.list_agent_specs()}

        candidates = []
        for aid, spec in specs.items():
            if aid not in self.agents:
                continue  # Skip specs for agents not currently running
                
            if organ_hint and spec.organ_id != organ_hint:
                continue
            if required_skills and not required_skills.issubset(set(spec.skills)):
                continue
            if required_models and not required_models.issubset(set(spec.models)):
                continue
            
            # Policy gate
            if not self._policy_allows(spec, task_data):
                continue
                
            candidates.append(aid)
        return candidates

    def _policy_allows(self, agent_spec: AgentSpec, task_data: Dict[str, Any]) -> bool:
        """Simple policy gate before executing tasks."""
        policies = agent_spec.metadata.get("policies", "").split(",")
        # Example rule: block external network if policy forbids
        if "no_external_egress" in policies and task_data.get("requires_external_network"):
            return False
        return True

    async def execute_task_on_graph_best(self, task_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Execute task on best agent from graph-filtered candidates."""
        ids = self._graph_filter_candidates(task_data)
        if not ids:
            logger.warning("No graph-qualified agents; falling back to global best")
            return await self.execute_task_on_best_agent(task_data)
        return await self.execute_task_on_best_of(ids, task_data)

# --- Global Instance Management (ENHANCED) ---

# The global instance is now set by an explicit initializer
# to ensure dependencies are injected correctly.

_tier0_manager_instance: Optional[Tier0MemoryManager] = None


async def initialize_global_tier0_manager(
    mw_manager: MwManager,
    ltm_manager: LongTermMemoryManager
) -> Tier0MemoryManager:
    """
    Creates and registers the global Tier0MemoryManager instance
    with its required memory dependencies.
    
    This should be called once at application startup.
    
    Args:
        mw_manager: The MwManager (Tier 1) client instance.
        ltm_manager: The LongTermMemoryManager (Tier 2) client instance.
        
    Returns:
        The initialized Tier0MemoryManager instance.
    """
    global _tier0_manager_instance
    if _tier0_manager_instance is None:
        logger.info("Initializing global Tier0MemoryManager...")
        _tier0_manager_instance = Tier0MemoryManager(
            mw_manager=mw_manager,
            ltm_manager=ltm_manager
        )
        # Perform initial discovery
        await _tier0_manager_instance.discover_and_refresh_agents()
    return _tier0_manager_instance


def get_tier0_manager() -> Tier0MemoryManager:
    """
    Get the global Tier0MemoryManager instance.
    
    Raises:
        RuntimeError: If initialize_global_tier0_manager() has not been called.
    """
    if _tier0_manager_instance is None:
        raise RuntimeError(
            "Tier0MemoryManager is not initialized. "
            "Call 'initialize_global_tier0_manager()' at application startup."
        )
    return _tier0_manager_instance


# For backward compatibility, a proxy object
class Tier0ManagerProxy:
    def __getattr__(self, name):
        # This will raise the RuntimeError if not initialized, which is correct.
        return getattr(get_tier0_manager(), name)


tier0_manager = Tier0ManagerProxy() 