# Copyright 2024 SeedCore Contributors
# ... (license) ...

"""
Organ Actor (replaces legacy Tier0MemoryManager)

This class acts as an 'Organ' within the Organism. It is a stateful
Ray actor spawned by the OrganismManager and is responsible for:

- Spawning and managing a pool of specialized WorkerAgents (BaseAgents).
- Injecting shared resources (Tools, Registries, SkillStore) into its agents.
- Collecting advertisements (heartbeats) from its agents.
- Performing Level 2 (intra-organ) routing to select the best agent for a task.
"""

from __future__ import annotations

import os
import ray  # pyright: ignore[reportMissingImports]
import asyncio
import uuid
import random
import signal
import contextlib
from typing import Dict, Any, Optional, TYPE_CHECKING

# --- Core SeedCore Imports ---
from ..utils.ray_utils import get_ray_node_ip
from ..models import TaskPayload
from ..agents.roles import (
    Specialization,
    RoleRegistry,
    SkillStoreProtocol,
    Router,  # The Level 2 (intra-organ) router
    AgentAdvertisement
)
from ..logging_setup import setup_logging, ensure_serve_logger
setup_logging(app_name="seedcore.Organ")

if TYPE_CHECKING:
    from ..agents.worker_agent import WorkerAgent # The new BaseAgent actor
    from ..tools.manager import ToolManager
    # Note: MwManager and LongTermMemoryManager are removed
    from ..graph.agent_repository import AgentGraphRepository

logger = ensure_serve_logger("seedcore.Organ", level="DEBUG")

# Target namespace for agent actors
AGENT_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))

# Configurable heartbeat parameters
HB_BASE = float(os.getenv("RUNTIME_HB_BASE_S", "3.0"))     # 3s
HB_JITTER = float(os.getenv("RUNTIME_HB_JITTER_S", "2.0")) # +[0..2]s
HB_BACKOFF_MAX = float(os.getenv("RUNTIME_HB_BACKOFF_S", "10.0"))

# Non-blocking ray.get helper
async def _aget(obj_ref, timeout: float = 2.0):
    loop = asyncio.get_running_loop()
    # Use a threadpool to call blocking ray.get
    return await loop.run_in_executor(None, lambda: ray.get(obj_ref, timeout=timeout))

async def _call_actor_method(
    actor_handle: Any,
    method_name: str,
    *args,
    timeout: Optional[float] = None,
    **kwargs,
) -> Any:
    """Helper to invoke a Ray actor method."""
    method = getattr(actor_handle, method_name, None)
    if method is None:
        raise AttributeError(f"{actor_handle!r} has no attribute '{method_name}'")
    
    remote_call = method.remote(*args, **kwargs)
    return await _aget(remote_call, timeout=timeout or 30.0)


@ray.remote
class Organ:
    """
    Stateful Ray-based Organ actor (the new Tier0MemoryManager).
    
    This organ acts as a specialized container for a pool of agents,
    implementing the "swarm-of-swarms" model.
    """
    
    def __init__(
        self,
        organ_id: str,
        organ_type: str, # For logging/grouping, e.g., "GuestRelations"
        serve_route: Optional[str] = None, # For runtime registry
        *,
        # --- Injected Dependencies from OrganismManager ---
        # Note: No direct memory managers are injected here.
        role_registry: "RoleRegistry",
        skill_store: "SkillStoreProtocol",
        tool_manager: "ToolManager",
        cognitive_base_url: Optional[str] = None
    ):
        self.organ_id = organ_id
        self.organ_type = organ_type
        self.serve_route = serve_route
        self.agents: Dict[str, "WorkerAgent"] = {} # agent_id -> Ray actor handle

        # --- Store Injected Shared Resources ---
        self.role_registry = role_registry
        self.skill_store = skill_store
        self.tool_manager = tool_manager
        self.cognitive_base_url = cognitive_base_url

        # --- Internal Level 2 Router ---
        self.router = Router(registry=self.role_registry)
        
        # Internal state
        self._ping_failures: Dict[str, int] = {}
        self.instance_id = uuid.uuid4().hex
        self._started = False
        self._closing = asyncio.Event()

        # Background tasks
        self._hb_task: Optional[asyncio.Task] = None # For this organ's heartbeat
        self._ad_task: Optional[asyncio.Task] = None # For collecting agent ads

        # Database dependencies (lazy)
        self._repo: Optional["AgentGraphRepository"] = None
        self._session_factory = None
        try:
            from seedcore.database import get_async_pg_session_factory
            self._session_factory = get_async_pg_session_factory()
        except Exception as exc:
            logger.warning(f"[{self.organ_id}] DB session factory unavailable: {exc}")

        logger.info(f"✅ Organ actor {self.organ_id} (Type: {self.organ_type}) initialized.")


    # ------------------------------------------------------------------
    # Agent Lifecycle (Called by OrganismManager)
    # ------------------------------------------------------------------

    def create_agent(
        self,
        agent_id: str,
        specialization: Specialization,
        organ_id: str, # Passed for verification
        *,
        name: Optional[str] = None,
        lifetime: Optional[str] = None,
        num_cpus: Optional[float] = None,
        num_gpus: Optional[float] = None,
        resources: Optional[Dict[str, float]] = None,
    ) -> str:
        """
        Create a new WorkerAgent actor (idempotent).
        This is called by the OrganismManager.
        """
        # Ensure we import the agent class *inside* the Ray actor
        from ..agents.worker_agent import WorkerAgent

        if agent_id in self.agents:
            logger.warning(f"[{self.organ_id}] Agent {agent_id} already exists.")
            return agent_id
            
        if self.organ_id != organ_id:
             logger.error(f"Organ ID mismatch! Expected {self.organ_id}, got {organ_id}")
             raise ValueError("Organ ID mismatch")

        try:
            options_kwargs: Dict[str, Any] = {}
            effective_name = name or agent_id
            options_kwargs["name"] = effective_name
            options_kwargs["lifetime"] = lifetime or "detached"
            if num_cpus is not None:
                options_kwargs["num_cpus"] = num_cpus
            if num_gpus is not None:
                options_kwargs["num_gpus"] = num_gpus
            if resources:
                options_kwargs["resources"] = resources
            options_kwargs["namespace"] = AGENT_NAMESPACE
            options_kwargs["get_if_exists"] = True # Re-attach if already exists

            logger.info(f"🚀 [{self.organ_id}] Creating/getting agent '{effective_name}'...")
            
            # Create fresh actor, injecting all dependencies
            handle = WorkerAgent.options(**options_kwargs).remote(
                agent_id=agent_id,
                specialization=specialization,
                # Pass all the shared resources
                role_registry=self.role_registry,
                skill_store=self.skill_store,
                tool_manager=self.tool_manager,
                cognitive_base_url=self.cognitive_base_url,
                organ_id=self.organ_id
            )

            self.agents[agent_id] = handle
            
            # Immediately fetch and register its advertisement
            try:
                ad_dict = ray.get(handle.advertise_capabilities.remote())
                ad_obj = AgentAdvertisement(**ad_dict)
                self.router.register(ad_obj)
            except Exception as e:
                logger.warning(f"Failed to get initial advertisement for {agent_id}: {e}")

            logger.info(f"✅ [{self.organ_id}] Created agent: {agent_id} (Spec: {specialization.value})")
            return agent_id

        except Exception as e:
            logger.error(f"Failed to create agent {agent_id} in {self.organ_id}: {e}", exc_info=True)
            raise

    def remove_agent(self, agent_id: str) -> bool:
        """Removes an agent from this organ and its router."""
        logger.info(f"[{self.organ_id}] Removing agent {agent_id}...")
        self.router.remove(agent_id)
        if agent_id in self.agents:
            # We don't kill the agent, just de-register it.
            # The OrganismManager is responsible for killing the actor.
            del self.agents[agent_id]
            return True
        return False

    def get_agent_handles(self) -> Dict[str, 'WorkerAgent']:
        """Returns all agent handles in this organ."""
        return self.agents.copy()

    # ------------------------------------------------------------------
    # Task Execution (Called by OrganismManager)
    # ------------------------------------------------------------------

    async def execute_task_on_best_agent(
        self, 
        task: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Asynchronously executes a task on the most suitable agent *within this organ*.
        This is the main Level 2 (intra-organ) routing logic.
        """
        task_obj: TaskPayload
        try:
            task_obj = TaskPayload.from_db(task)
        except Exception as e:
            logger.error(f"[{self.organ_id}] Failed to parse TaskPayload: {e}")
            return {"success": False, "error": f"Invalid task payload: {e}"}

        logger.info(f"[{self.organ_id}] Routing task {task_obj.task_id} (Spec: {task_obj.required_specialization})...")

        if not self.agents:
            logger.error(f"[{self.organ_id}] No agents available for task {task_obj.task_id}")
            return {"success": False, "error": "No agents available in organ"}
        
        try:
            # 1. Use the internal router to select the best agent
            best_ad = self.router.select_best(
                required_role=Specialization(task_obj.required_specialization) if task_obj.required_specialization else None,
                required_tags=task_obj.params.get("routing", {}).get("required_tags"), # Legacy
                desired_skills=task_obj.desired_skills
            )
            
            if not best_ad:
                logger.warning(f"[{self.organ_id}] No suitable agent found for task {task_obj.task_id}. Trying random.")
                agent_handle = random.choice(list(self.agents.values()))
                agent_id = await _call_actor_method(agent_handle, "get_id")
            else:
                agent_id = best_ad.agent_id
                agent_handle = self.agents.get(agent_id)
                if not agent_handle:
                     logger.error(f"Router selected agent {agent_id} but it's not in the handle list.")
                     return {"success": False, "error": f"Agent {agent_id} not found after routing"}

            logger.info(f"[{self.organ_id}] Task {task_obj.task_id} routed to agent {agent_id}")

            # 2. Dispatch the task to the selected agent
            # We pass the full task dictionary
            result = await _call_actor_method(
                agent_handle, 
                "execute_task", 
                task, # Pass the original dict, BaseAgent will re-parse it
                timeout=120.0
            )
            
            logger.info(f"✅ [{self.organ_id}] Task {task_obj.task_id} executed by {agent_id}")
            return result
            
        except Exception as e:
            logger.error(f"[{self.organ_id}] Task execution failed for {task_obj.task_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Status & Heartbeat
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Returns the current status of the organ."""
        return {
            "organ_id": self.organ_id,
            "organ_type": self.organ_type,
            "instance_id": str(self.instance_id),
            "agent_count": len(self.agents),
            "agent_ids": list(self.agents.keys()),
            "specializations": list(self.router.get_specializations()),
            "status": "healthy"
        }

    def ping(self) -> str:
        """Health check method to verify the organ is responsive."""
        return "pong"

    async def start(self) -> Dict[str, Any]:
        """Register in runtime registry and start background loops."""
        if self._started:
            return {"status": "alive", "instance_id": self.instance_id, "logical_id": self.organ_id}
        
        logger.info(f"[{self.organ_id}] Starting...")
        
        # Start this Organ's own heartbeat loop
        self._hb_task = asyncio.create_task(self._heartbeat_loop())
        
        # Start the advertisement collection loop for child agents
        self._ad_task = asyncio.create_task(self._collect_advertisements_loop())
        
        # Try to handle SIGTERM to mark dead early
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(self.close()))
        except Exception:
            pass  # Not available in all contexts
        
        self._started = True
        logger.info(f"✅ [{self.organ_id}] Started background loops.")
        return {"status": "alive", "instance_id": self.instance_id, "logical_id": self.organ_id}

    async def _heartbeat_loop(self):
        """
        Robust, production-grade heartbeat loop for Organ actors.

        Features:
        - Retries DB/repo initialization until ready.
        - Registers instance exactly once.
        - Clean cancellation semantics.
        - Exponential backoff with circuit breaker.
        - Reliable Ray node IP resolution.
        - Deterministic heartbeat intervals.
        """

        # --- Phase 1: Ensure DB & Repo Availability ---
        repo = None
        failures = 0
        MAX_INIT_FAILURES = 100  # ~5 minutes total before long sleep
        INIT_RETRY_DELAY = 3.0

        # Resolve real node IP (Ray-safe, with robust fallbacks)
        node_ip = get_ray_node_ip()
        logger.debug(f"[{self.organ_id}] Resolved node IP: {node_ip}")

        while not self._closing.is_set():
            try:
                repo = await self._repo_lazy()
                if repo and self._session_factory:
                    break

                failures += 1
                logger.warning(
                    f"[{self.organ_id}] Waiting for DB/Repo availability "
                    f"(failure {failures}/{MAX_INIT_FAILURES})"
                )

                if failures >= MAX_INIT_FAILURES:
                    logger.error(
                        f"[{self.organ_id}] Too many DB init failures. "
                        "Entering degraded idle mode for 5 minutes."
                    )
                    await asyncio.sleep(300)
                    failures = 0  # reset counter
                    continue

                await asyncio.sleep(INIT_RETRY_DELAY)

            except asyncio.CancelledError:
                # Actor is shutting down
                return
            except Exception as e:
                failures += 1
                logger.error(
                    f"[{self.organ_id}] DB initialization error: {e}, retrying...",
                    exc_info=True
                )
                await asyncio.sleep(INIT_RETRY_DELAY)

        if self._closing.is_set():
            return

        logger.info(f"[{self.organ_id}] DB/Repo ready. Starting heartbeat loop.")

        # --- Phase 2: Register the Organ once ---
        registered = False
        REG_FAILURE_LIMIT = 20  # before entering degraded sleep
        failures = 0

        while not self._closing.is_set() and not registered:
            try:
                if not self._session_factory:
                    raise RuntimeError("Session factory not available")
                async with self._session_factory() as session:
                    async with session.begin():
                        # Fetch cluster epoch
                        cluster_epoch = await repo.get_current_cluster_epoch(session)

                        # Register this Organ instance
                        await repo.register_instance(
                            session=session,
                            instance_id=self.instance_id,
                            logical_id=self.organ_id,
                            cluster_epoch=cluster_epoch,
                            actor_name=self.organ_id,
                            serve_route=self.serve_route,
                            node_id=os.getenv("RAY_NODE_ID", ""),
                            ip_address=node_ip,
                            pid=os.getpid(),
                        )

                logger.info(f"[{self.organ_id}] Registered instance in registry.")
                registered = True

            except asyncio.CancelledError:
                return
            except Exception as e:
                failures += 1
                logger.warning(
                    f"[{self.organ_id}] Registration failed ({failures}/{REG_FAILURE_LIMIT}): {e}"
                )
                if failures >= REG_FAILURE_LIMIT:
                    logger.error(
                        f"[{self.organ_id}] Too many registration failures. "
                        "Sleeping for 5 minutes before retry."
                    )
                    await asyncio.sleep(300)
                    failures = 0
                    continue

                await asyncio.sleep(3)

        if self._closing.is_set():
            return

        logger.info(f"[{self.organ_id}] Registration complete. Entering heartbeat mode.")

        # --- Phase 3: Steady-State Heartbeat Loop ---
        backoff = 0.5
        failures = 0
        MAX_HB_FAILURES = 50  # ~5 mins at 5s interval

        while not self._closing.is_set():
            try:
                if not self._session_factory:
                    raise RuntimeError("Session factory not available")
                async with self._session_factory() as session:
                    async with session.begin():
                        # Status "alive"
                        await repo.set_instance_status(session, self.instance_id, "alive")

                        # Heartbeat
                        await repo.beat(session, self.instance_id)

                # Reset backoff on success
                backoff = 0.5
                failures = 0

            except asyncio.CancelledError:
                return
            except Exception as e:
                failures += 1
                logger.warning(
                    f"❌ [{self.organ_id}] Heartbeat failure "
                    f"({failures}/{MAX_HB_FAILURES}): {e}, backoff={backoff}s"
                )

                if failures >= MAX_HB_FAILURES:
                    logger.error(
                        f"[{self.organ_id}] Too many heartbeat failures. "
                        "Entering degraded idle mode for 5 minutes."
                    )
                    await asyncio.sleep(300)
                    failures = 0
                    backoff = 0.5
                    continue

                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, HB_BACKOFF_MAX)
                continue

            # --- Normal heartbeat delay ---
            delay = HB_BASE + random.random() * HB_JITTER
            try:
                await asyncio.wait_for(self._closing.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass  # normal loop

    async def _collect_advertisements_loop(self, interval: int = 10):
        """Periodically collects advertisements from all child agents."""
        while not self._closing.is_set():
            await asyncio.sleep(interval)
            if not self._closing.is_set():
                try:
                    await self.collect_advertisements()
                except Exception as e:
                    logger.warning(f"[{self.organ_id}] Ad collection loop error: {e}")

    async def collect_advertisements(self) -> Dict[str, Any]:
        """
        Collects advertisements from all agents and registers them with the internal router.
        """
        if not self.agents:
            return {"status": "no_agents", "collected": 0}

        agent_items = list(self.agents.items())
        tasks = [
            _call_actor_method(handle, "advertise_capabilities", timeout=2.0)
            for _, handle in agent_items
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        successes = 0
        failed_agents = []
        async with self.router.get_lock(): # Lock the router for batch update
            for (agent_id, handle), res in zip(agent_items, results):
                if isinstance(res, Exception):
                    logger.debug(f"[{self.organ_id}] Failed ad from {agent_id}: {res}")
                    self._ping_failures[agent_id] = self._ping_failures.get(agent_id, 0) + 1
                    if self._ping_failures[agent_id] >= 3:
                        failed_agents.append(agent_id)
                    continue
                
                self._ping_failures[agent_id] = 0
                try:
                    ad_obj = AgentAdvertisement(**res)
                    self.router.register(ad_obj)
                    successes += 1
                except Exception as e:
                    logger.warning(f"Failed to parse ad from {agent_id}: {e}")
        
        # Prune failed agents
        for agent_id in failed_agents:
            logger.warning(f"[{self.organ_id}] Removing agent {agent_id} after 3 ping failures.")
            self.router.remove(agent_id)
            self.agents.pop(agent_id, None)

        logger.info(f"[{self.organ_id}] Collected {successes}/{len(agent_items)} agent advertisements.")
        return {"collected": successes, "failed": len(agent_items) - successes}

    async def close(self) -> Dict[str, Any]:
        """Stop heartbeats and mark dead in runtime registry."""
        if self._closing.is_set():
            return {"status": "dead", "instance_id": self.instance_id}
        
        logger.info(f"🛑 [{self.organ_id}] Closing...")
        self._closing.set()
        
        # Cancel and await background tasks
        if self._hb_task:
            self._hb_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._hb_task
        if self._ad_task:
            self._ad_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ad_task
        
        # Mark dead in registry
        repo = await self._repo_lazy()
        with contextlib.suppress(Exception):
            if repo and self._session_factory:
                async with self._session_factory() as session:
                    async with session.begin():
                        await repo.set_instance_status(session, self.instance_id, "dead")
        
        logger.info(f"✅ [{self.organ_id}] Marked dead.")
        return {"status": "dead", "instance_id": self.instance_id}

    async def _repo_lazy(self):
        if self._repo is None:
            try:
                from seedcore.graph.agent_repository import AgentGraphRepository
                self._repo = AgentGraphRepository()
            except Exception:
                logger.debug("AgentGraphRepository not available.")
        return self._repo