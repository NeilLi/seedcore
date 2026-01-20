# Copyright 2024 SeedCore Contributors
# ... (license) ...

"""
Organ Actor (v2 - Lightweight Registry for Multiple Agent Types)

This class acts as an 'Organ' within the Organism. It is a stateful
Ray actor spawned by the OrganismCore and is responsible for:

- Spawning and managing a pool of agent actors (BaseAgent by default).
- Injecting shared resources (Tools, Memory Managers, Checkpointing) into its agents.
- Responding to calls from the OrganismCore (e.g., get_agent_handles).

THIS ACTOR IS PASSIVE. It does not run its own loops for polling or routing.
That logic is centralized in the OrganismCore and StateService.

The Organ supports multiple agent types:
- BaseAgent (default): Generic executor with Behavior Plugin System
- UtilityAgent: System observer and tuner (specialized learning agent)
"""

from __future__ import annotations

import os
import uuid
import ray  # pyright: ignore[reportMissingImports]
import asyncio
import random
import time
import importlib
from functools import lru_cache
from typing import Dict, Any, Optional, List, TYPE_CHECKING, Tuple

from seedcore.agents.roles import RoleProfile
from seedcore.serve.ml_client import MLServiceClient

# --- Core SeedCore Imports ---
from ..logging_setup import ensure_serve_logger, setup_logging

# Runtime imports for things used in code
from ..agents.roles.specialization import (
    Specialization,
    SpecializationProtocol,
    get_specialization,
)  # ← needed at runtime

# Type alias for readability (after ray import)
AgentHandle = ray.actor.ActorHandle

if TYPE_CHECKING:
    from ..agents.roles.specialization import RoleRegistry
    from ..agents.roles.skill_vector import SkillStoreProtocol
    from ..serve.cognitive_client import CognitiveServiceClient

    # --- Add imports for stateful dependencies ---
    from ..memory.mw_manager import MwManager
    from ..memory.holon_fabric import HolonFabric

setup_logging(app_name="seedcore.organs.organ")
logger = ensure_serve_logger("seedcore.organs.organ", level="DEBUG")

# Target namespace for agent actors
AGENT_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))


# =====================================================================
#  AGENT FACTORY HELPERS (Common, Reusable)
# =====================================================================


@lru_cache(maxsize=256)
def _import_symbol(module_path: str, symbol_name: str) -> Any:
    """
    Cached import helper for agent classes.
    Reduces import overhead in hot paths.
    """
    mod = importlib.import_module(module_path)
    sym = getattr(mod, symbol_name, None)
    if sym is None:
        raise AttributeError(f"Symbol '{symbol_name}' not found in '{module_path}'")
    return sym


def _resolve_classpath(agent_class_name: str, class_map: Dict[str, str]) -> str:
    """
    Resolve agent class name to fully-qualified classpath.

    Accepts either:
      - Short name: "BaseAgent" or "UtilityAgent" -> uses class_map
      - Full path: "seedcore.agents.foo.BarAgent" -> uses directly

    Args:
        agent_class_name: Short name or fully-qualified path
        class_map: Mapping of short names to classpaths

    Returns:
        Fully-qualified classpath string
    """
    if "." in agent_class_name:
        # Already a full path
        return agent_class_name
    # Look up in class map, fallback to BaseAgent
    return class_map.get(agent_class_name, class_map["BaseAgent"])


def _load_agent_class(classpath: str) -> Any:
    """
    Load agent class from fully-qualified classpath.

    Args:
        classpath: Fully-qualified classpath (e.g., "seedcore.agents.base.BaseAgent")

    Returns:
        Agent class (may be regular class or Ray actor class)
    """
    module_path, class_name = classpath.rsplit(".", 1)
    return _import_symbol(module_path, class_name)


def _is_ray_actor_class(cls: Any) -> bool:
    """
    Check if a class is already a Ray actor.

    Ray actor classes have a .remote callable (stable indicator without ray internals).

    Args:
        cls: Class to check

    Returns:
        True if cls is a Ray actor class, False otherwise
    """
    return hasattr(cls, "remote") and callable(getattr(cls, "remote", None))


def _ensure_ray_actor_class(
    cls: Any, *, default_remote_kwargs: Optional[Dict[str, Any]] = None
) -> Any:
    """
    Ensure a class is wrapped as a Ray actor.

    If cls is already a Ray actor -> return as-is.
    If cls is a regular class -> wrap with ray.remote().

    Args:
        cls: Class to wrap (may be regular class or Ray actor)
        default_remote_kwargs: Optional kwargs for ray.remote() wrapper

    Returns:
        Ray actor class (wrapped if needed)

    Raises:
        RuntimeError: If Ray is not available but wrapping is needed
        TypeError: If cls is not a class
    """
    if _is_ray_actor_class(cls):
        return cls

    if ray is None:
        raise RuntimeError("Ray is not available but a non-actor class needs wrapping.")

    if not isinstance(cls, type):
        raise TypeError(f"Resolved object is not a class (type={type(cls).__name__})")

    default_remote_kwargs = default_remote_kwargs or {
        "max_restarts": 2,
        "max_task_retries": 0,
    }
    return ray.remote(**default_remote_kwargs)(cls)


class AgentIDFactory:
    """
    Factory for generating agent IDs based on organ_id and specialization.

    Provides consistent ID generation across the system. OrganismCore typically
    uses this factory to generate IDs before calling Organ.create_agent().

    IMPORTANT: agent_id is a permanent, immutable identity. It includes organ_id
    only as part of the creation context, but agent_id does NOT imply current organ
    residence after migration. Agents can be transferred between organs via
    register_agent() without changing their ID.
    """

    def new(self, organ_id: str, spec: SpecializationProtocol) -> str:
        """
        Generate a stable, unique agent ID.

        NOTE: agent_id is a permanent identity. It includes organ_id only
        as part of the creation context, but agent_id does NOT imply
        current organ residence after migration.

        Args:
            organ_id: ID of the organ this agent belongs to (at creation time)
            spec: Agent specialization (static or dynamic)

        Returns:
            Generated agent ID string (format: agent_{organ_id}_{spec_safe}_{unique12})
        """
        # Use short UUID hex (12 chars) for readability, similar to ULID length
        # Collision probability: 16^12 ≈ 2^48 space → extremely safe even at millions of agents
        # Can be swapped for actual ULID library if time-sorted IDs are needed
        unique_id = uuid.uuid4().hex[:12]

        # Normalize specialization value to be safe in Ray actor names
        # Replace potentially unsafe characters: / . - → _
        spec_value = spec.value if hasattr(spec, 'value') else str(spec)
        spec_safe = spec_value.replace("/", "_").replace(".", "_").replace("-", "_")

        return f"agent_{organ_id}_{spec_safe}_{unique_id}"


@ray.remote
class Organ:
    """
    A Ray actor that serves as a simple agent registry, factory, and health tracker.

    Architecture:
      - Acts as a "Parent Node" for a specific functional group (Organ).
      - Manages dependency injection (Configs -> Agents).
      - Lazily initializes local resources (ToolManager, DB connections) only when needed.
    """

    # Central Registry for Agent Class Resolution
    # Legacy classes (ConversationAgent, ObserverAgent, OrchestrationAgent, EnvironmentIntelligenceAgent)
    # have been removed - use BaseAgent + behaviors instead
    AGENT_CLASS_MAP = {
        "BaseAgent": "seedcore.agents.base.BaseAgent",
        "UtilityAgent": "seedcore.agents.utility_agent.UtilityAgent",
        "UtilityLearningAgent": "seedcore.agents.utility_agent.UtilityAgent",  # Alias for UtilityAgent
    }

    def __init__(
        self,
        organ_id: str,
        # --- Configs (Safe: Dicts/Strings) ---
        holon_fabric_config: Optional[Dict[str, Any]] = None,
        cognitive_client_cfg: Optional[Dict[str, Any]] = None,
        ml_client_cfg: Optional[Dict[str, Any]] = None,
        checkpoint_cfg: Optional[Dict[str, Any]] = None,
        mw_manager_organ_id: Optional[str] = None,
        # --- Pre-computed/Shared Data (Safe: Immutable/Handles) ---
        role_registry: Optional["RoleRegistry"] = None,
        tool_handler_shards: Optional[List[Any]] = None,
        # --- Legacy / Deprecated ---
        organ_registry: Optional[Any] = None,
        agent_id_factory: Optional[Any] = None,
    ):
        self.organ_id = organ_id

        # 1. Configuration Storage
        self._holon_fabric_config = holon_fabric_config
        self._cognitive_client_cfg = cognitive_client_cfg
        self._ml_client_cfg = ml_client_cfg
        self._checkpoint_cfg = checkpoint_cfg or {"enabled": False}
        self._mw_manager_organ_id = mw_manager_organ_id or organ_id

        # 2. Dependency Storage (Lazy Init)
        self.role_registry = role_registry
        self.tool_handler_shards = tool_handler_shards
        self.organ_registry = organ_registry

        # 3. Internal State
        self.agents: Dict[str, AgentHandle] = {}
        self.agent_info: Dict[str, Dict[str, Any]] = {}

        # 4. Lazy Resource Containers
        self._tool_handler: Optional[Any] = None
        self._holon_fabric: Optional["HolonFabric"] = None
        self._skill_store: Optional["SkillStoreProtocol"] = None
        self._mw_manager: Optional["MwManager"] = None
        self._cognitive_client: Optional["CognitiveServiceClient"] = None
        self._ml_client: Optional["MLServiceClient"] = None

        # 5. Concurrency Control (Prevent race conditions during lazy init)
        self._init_lock = asyncio.Lock()

        logger.info(f"✅ Organ actor {self.organ_id} created.")

    # ==========================================================
    # Lazy Initialization Helpers (Concurrency Safe)
    # ==========================================================

    async def _ensure_holon_fabric(self) -> "HolonFabric":
        """Lazily initialize HolonFabric/SkillStore with thread safety."""
        if self._holon_fabric:
            return self._holon_fabric

        async with self._init_lock:
            # Double-check inside lock
            if self._holon_fabric:
                return self._holon_fabric

            if not self._holon_fabric_config:
                raise RuntimeError(f"Organ {self.organ_id} missing HolonFabric config")

            # Import locally to avoid top-level circular deps
            from ..memory.holon_fabric import HolonFabric
            from ..memory.backends.pgvector_backend import PgVectorStore
            from ..memory.backends.neo4j_graph import Neo4jGraph
            from ..organs.organism_core import HolonFabricSkillStoreAdapter
            from ..database import PG_DSN, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

            logger.info(f"⚙️ [{self.organ_id}] Initializing HolonFabric connections...")

            # 1. Setup PG
            pg_cfg = self._holon_fabric_config.get("pg", {})
            pg_store = PgVectorStore(
                dsn=pg_cfg.get("dsn")
                or self._holon_fabric_config.get("pg_dsn", PG_DSN),
                pool_size=pg_cfg.get("pool_size")
                or self._holon_fabric_config.get("pg_pool_size", 2),
                pool_min_size=1,
            )
            # Verify PG connection
            await pg_store._get_pool()

            # 2. Setup Neo4j
            neo4j_cfg = self._holon_fabric_config.get("neo4j", {})
            neo4j_graph = Neo4jGraph(
                neo4j_cfg.get("uri")
                or self._holon_fabric_config.get("neo4j_uri", NEO4J_URI),
                auth=(
                    neo4j_cfg.get("user")
                    or self._holon_fabric_config.get("neo4j_user", NEO4J_USER),
                    neo4j_cfg.get("password")
                    or self._holon_fabric_config.get("neo4j_password", NEO4J_PASSWORD),
                ),
            )

            # 3. Construct Fabric & Adapter
            self._holon_fabric = HolonFabric(vec_store=pg_store, graph=neo4j_graph)
            self._skill_store = HolonFabricSkillStoreAdapter(self._holon_fabric)

            logger.info(f"✅ [{self.organ_id}] HolonFabric initialized.")
            return self._holon_fabric

    async def _ensure_tool_handler(self) -> Any:
        """Lazily initialize local ToolManager if shards aren't provided."""
        if self._tool_handler:
            return self._tool_handler

        # Optimization: No lock needed if using shards (read-only access)
        if self.tool_handler_shards:
            self._tool_handler = self.tool_handler_shards
            return self._tool_handler

        async with self._init_lock:
            if self._tool_handler:
                return self._tool_handler

            # Local ToolManager requires dependencies
            await self._ensure_holon_fabric()

            from ..tools.manager import ToolManager

            logger.info(f"⚙️ [{self.organ_id}] Initializing local ToolManager...")

            self._tool_handler = ToolManager(
                skill_store=self._skill_store,
                mw_manager=self._get_mw_manager(),
                holon_fabric=self._holon_fabric,
                cognitive_client=self._get_client_instance("cognitive"),
                ml_client=self._get_client_instance("ml"),
            )
            logger.info(f"✅ [{self.organ_id}] Local ToolManager initialized.")
            return self._tool_handler

    def _get_mw_manager(self) -> "MwManager":
        """Synchronous lazy loader for MwManager (low overhead)."""
        if not self._mw_manager and self._mw_manager_organ_id:
            from ..memory.mw_manager import MwManager

            self._mw_manager = MwManager(organ_id=self._mw_manager_organ_id)
        return self._mw_manager

    def _get_client_instance(self, client_type: str) -> Any:
        """
        Generic factory for Service Clients.
        Constructs clients from stored config without triggering side-effects.
        """
        # Return cached if exists
        if client_type == "cognitive" and self._cognitive_client:
            return self._cognitive_client
        if client_type == "ml" and self._ml_client:
            return self._ml_client

        # Map type to config/class
        if client_type == "cognitive":
            cfg = self._cognitive_client_cfg
            from ..serve.cognitive_client import CognitiveServiceClient as ClientCls

            target_attr = "_cognitive_client"
            svc_name = "cognitive_service"
        elif client_type == "ml":
            cfg = self._ml_client_cfg
            from ..serve.ml_client import MLServiceClient as ClientCls

            target_attr = "_ml_client"
            svc_name = "ml_service"
        else:
            return None

        if not cfg:
            return None

        # Construction logic (Safe Bypass)
        from ..serve.base_client import BaseServiceClient, CircuitBreaker, RetryConfig

        # 1. Build Sub-components
        cb = CircuitBreaker(
            failure_threshold=cfg.get("circuit_breaker", {}).get(
                "failure_threshold", 5
            ),
            recovery_timeout=cfg.get("circuit_breaker", {}).get(
                "recovery_timeout", 30.0
            ),
        )
        rc = RetryConfig(
            max_attempts=cfg.get("retry_config", {}).get("max_attempts", 1),
            base_delay=cfg.get("retry_config", {}).get("base_delay", 1.0),
            max_delay=cfg.get("retry_config", {}).get("max_delay", 5.0),
        )

        # 2. Instantiate (Bypass __init__ to avoid env var reads/side effects)
        client = object.__new__(ClientCls)
        BaseServiceClient.__init__(
            client,
            service_name=svc_name,
            base_url=cfg["base_url"],
            timeout=cfg.get("timeout", 30.0),
            circuit_breaker=cb,
            retry_config=rc,
        )

        # 3. Apply Extra Fields
        if client_type == "ml" and "warmup_timeout" in cfg:
            client.warmup_timeout = cfg["warmup_timeout"]

        # Cache it
        setattr(self, target_attr, client)
        return client

    # ==========================================================
    # Public Interface
    # ==========================================================

    # Expose properties for internal use (ToolManager needs these)
    @property
    def holon_fabric(self):
        return self._holon_fabric

    @property
    def skill_store(self):
        return self._skill_store

    async def health_check(self) -> bool:
        """Readiness probe: Forces full dependency materialization."""
        try:
            # Parallelize initialization
            await asyncio.gather(
                self._ensure_holon_fabric(),
                self._ensure_tool_handler(),
                return_exceptions=False,
            )

            # Validation
            is_healthy = (
                self._tool_handler is not None
                and self.role_registry is not None
                and self._skill_store is not None
            )
            return is_healthy
        except Exception:
            logger.exception(f"[{self.organ_id}] Health check failed")
            return False

    async def ping(self) -> bool:
        return True

    async def create_agent(
        self,
        agent_id: str,
        specialization: "SpecializationProtocol",
        organ_id: str,
        agent_class_name: str = "BaseAgent",
        session: Optional[Any] = None,
        behaviors: Optional[List[str]] = None,
        behavior_config: Optional[Dict[str, Dict[str, Any]]] = None,
        **agent_actor_options,
    ) -> None:
        """
        Factory method to spawn Agent Actors.
        Injects CONFIGURATION (dicts/strings), not LIVE OBJECTS, to ensure serialization safety.

        This method uses a common factory pattern with:
        - Cached imports for performance
        - Support for both short class names and fully-qualified paths
        - Centralized per-class init kwargs registry
        - Automatic Ray actor wrapping for non-actor classes
        """
        if agent_id in self.agents:
            logger.warning(f"[{self.organ_id}] Agent {agent_id} already exists.")
            return

        if self.organ_id != organ_id:
            raise ValueError(f"ID Mismatch: Organ {self.organ_id} != Req {organ_id}")

        logger.info(f"🚀 [{self.organ_id}] Spawning {agent_class_name} '{agent_id}'...")

        try:
            # 1. Resolve classpath -> import -> ensure ray actor
            classpath = _resolve_classpath(agent_class_name, self.AGENT_CLASS_MAP)
            raw_cls = _load_agent_class(classpath)
            AgentActorClass = _ensure_ray_actor_class(raw_cls)

            if _is_ray_actor_class(raw_cls):
                logger.debug(
                    f"[{self.organ_id}] Agent class '{agent_class_name}' is already a Ray actor, using as-is"
                )
            else:
                logger.debug(
                    f"[{self.organ_id}] Wrapped '{agent_class_name}' with @ray.remote"
                )

            # 2. Build config-only params (serializable)
            # Snapshotting RoleRegistry avoids passing the whole object (safest approach)
            role_snapshot = self._get_role_registry_snapshot()

            # Determine Tool Handler (Pass Handles if Sharded, else None)
            # If shards exist, we pass the list. If local, we pass None (Agent creates its own local fallback).
            th_param = self.tool_handler_shards if self.tool_handler_shards else None

            # Prefer passing specialization as string for serialization safety
            # BaseAgent should normalize this back to Specialization enum
            spec_value = (
                specialization.value
                if hasattr(specialization, "value")
                else str(specialization)
            )

            agent_params: Dict[str, Any] = {
                "agent_id": agent_id,
                "organ_id": self.organ_id,
                # Pass as string for serialization stability (BaseAgent will normalize)
                "specialization": spec_value,
                "tool_handler_shards": th_param,
                "role_registry_snapshot": role_snapshot,
                "holon_fabric_config": self._holon_fabric_config,
                "cognitive_client_cfg": self._cognitive_client_cfg,
                "ml_client_cfg": self._ml_client_cfg,
                "mcp_client_cfg": getattr(self, "_mcp_client_cfg", None),
            }

            # 3. Behavior Plugin System: Pass behaviors to agent
            # Behaviors can come from:
            # - organs.yaml agent definition (behaviors, behavior_config) - passed via create_agent()
            # - RoleProfile.default_behaviors (handled in BaseAgent.__init__)
            # - pkg_subtask_types.default_params.executor (via executor hints in task, handled during JIT spawning)
            if behaviors is not None:
                agent_params["behaviors"] = behaviors
            if behavior_config is not None:
                agent_params["behavior_config"] = behavior_config

            # 4. Spawn actor
            actor_opts = {
                "name": agent_id,
                "namespace": AGENT_NAMESPACE,  # Use the module-level constant
                "get_if_exists": True,
                **agent_actor_options,
            }

            handle = AgentActorClass.options(**actor_opts).remote(**agent_params)

            # 5. Register locally
            self.agents[agent_id] = handle
            self.agent_info[agent_id] = {
                "agent_id": agent_id,
                "specialization": spec_value,  # Store as string for consistency
                "specialization_name": specialization.name
                if hasattr(specialization, "name")
                else spec_value,
                "class": agent_class_name,
                "classpath": classpath,  # Store full classpath for debugging/respawn
                "created_at": time.time(),
                "status": "ready",
            }

            # 6. Optional tier-1 registration
            if self.organ_registry and session:
                await self.organ_registry.register_agent(
                    session,
                    agent_id=agent_id,
                    organ_id=self.organ_id,
                    specialization=spec_value,
                )

            logger.info(f"✅ [{self.organ_id}] Registered {agent_id}")

        except Exception as e:
            logger.error(f"❌ Failed to spawn agent {agent_id}: {e}", exc_info=True)
            self.agents.pop(agent_id, None)
            self.agent_info.pop(agent_id, None)
            raise

    def _get_role_registry_snapshot(self) -> Dict[str, Any]:
        """Extracts serializable dict from RoleRegistry."""
        if not self.role_registry:
            return {}
        snapshot = {}
        for spec, profile in self.role_registry._profiles.items():
            spec_key = spec.value if hasattr(spec, "value") else str(spec)
            # Dump frozen dataclass to dict
            if hasattr(profile, "model_dump"):
                snapshot[spec_key] = profile.model_dump()
            elif hasattr(profile, "__dict__"):
                # Manual extraction for safety
                snapshot[spec_key] = {
                    "default_skills": dict(getattr(profile, "default_skills", {})),
                    "allowed_tools": list(getattr(profile, "allowed_tools", [])),
                    "routing_tags": list(getattr(profile, "routing_tags", [])),
                    "safety_policies": dict(getattr(profile, "safety_policies", {})),
                }
        return snapshot

    async def remove_agent(self, agent_id: str) -> bool:
        """
        Removes an agent from the registry and terminates it.
        This is called by OrganismCore's `evolve` (scale_down).
        """
        logger.info(f"[{self.organ_id}] Removing agent {agent_id}...")
        self.agent_info.pop(agent_id, None)
        agent_handle = self.agents.pop(agent_id, None)

        if agent_handle:
            try:
                # Asynchronously terminate the actor
                ray.kill(agent_handle, no_restart=True)
                logger.info(f"[{self.organ_id}] Terminated agent {agent_id}.")
                return True
            except Exception as e:
                logger.warning(f"Failed to kill agent {agent_id}: {e}")
                # Still return True because it's gone from the registry
                return True
        return False  # Agent was not found in the registry

    async def respawn_agent(self, agent_id: str) -> None:
        """
        Recreates a dead agent with its previous info.
        This is called by OrganismCore's `_reconciliation_loop`.
        """
        info = self.agent_info.get(agent_id, {})
        if not info:
            raise ValueError(f"Cannot respawn {agent_id}: no info retained.")

        # Handle both string value (new format) and name (legacy format)
        spec_str = info.get("specialization") or info.get(
            "specialization_name", "user_liaison"
        )

        # Resolve specialization (supports both static and dynamic)
        try:
            spec = get_specialization(spec_str)
        except KeyError:
            logger.warning(
                f"[{self.organ_id}] Unknown specialization '{spec_str}' for respawn, defaulting to GENERALIST"
            )
            spec = Specialization.GENERALIST

        agent_class_name = info.get("class", "BaseAgent")  # Get the class

        # Re-run creation logic with preserved agent class
        await self.create_agent(
            agent_id=agent_id,
            specialization=spec,
            organ_id=self.organ_id,
            agent_class_name=agent_class_name,  # Pass the class
            name=agent_id,  # Re-use original name
            num_cpus=0.01,
            lifetime="detached",
        )

        # Update status to indicate this is a respawned agent
        if agent_id in self.agent_info:
            self.agent_info[agent_id]["status"] = "respawned"

    async def update_role_registry(self, profile: RoleProfile) -> None:
        """
        Receive a role definition update from OrganismCore and propagate to Agents.
        """
        # 1. Update the Organ's LOCAL copy
        self.role_registry.register(profile)
        logger.info(
            f"[{self.organ_id}] 📥 Synced role definition: {profile.name.value}"
        )

        # 2. Broadcast to relevant Agents
        # We only need to notify agents that actually HOLD this specialization.
        target_spec_val = profile.name.value.lower()

        futures = []
        for agent_id, handle in self.agents.items():
            info = self.agent_info.get(agent_id, {})

            # Check if this agent matches the updated specialization
            # (Use the normalized value we stored during register_agent)
            # Support both new format (specialization as value) and legacy (specialization_value)
            agent_spec = (
                info.get("specialization", "") or info.get("specialization_value", "")
            ).lower()

            if agent_spec == target_spec_val:
                # 3. Remote Call to Agent
                # Fire-and-forget logic usually, or gather if you want confirmation
                ref = handle.update_role_profile.remote(profile)
                futures.append(ref)

        # 4. Wait for propagation (Optional but recommended for consistency)
        if futures:
            await asyncio.gather(*futures)
            logger.info(
                f"[{self.organ_id}] ⚡ Hot-swapped profile on {len(futures)} agents."
            )

    # ==========================================================
    # Introspection (Called by OrganismCore & StateService)
    # ==========================================================

    async def get_agent_handle(self, agent_id: str) -> Optional[AgentHandle]:
        """Returns the handle for a specific agent."""
        return self.agents.get(agent_id)

    async def get_agent_handles(self) -> Dict[str, AgentHandle]:
        """
        Returns all agent handles managed by this organ.
        This is the main method used by OrganismCore to poll for the StateService.
        """
        return self.agents.copy()

    async def list_agents(self) -> List[str]:
        """Returns all agent IDs managed by this organ."""
        return list(self.agents.keys())

    async def get_agent_info(self, agent_id: str) -> Dict[str, Any]:
        """Returns the metadata for a specific agent."""
        return self.agent_info.get(agent_id, {"error": "not_found"})

    async def get_status(self) -> Dict[str, Any]:
        """
        Returns the health status of this organ and all its agents.
        (Called by OrganismCore's health loop)

        Actually pings agents to determine liveness, so OrganismCore's
        reconciliation loop can detect and respawn dead agents.
        """
        agent_statuses = {}

        for agent_id, handle in self.agents.items():
            alive = True
            try:
                # Try to ping the agent via get_heartbeat (most agents implement this)
                if hasattr(handle, "get_heartbeat"):
                    ref = handle.get_heartbeat.remote()
                    # Small timeout to avoid hanging
                    await asyncio.wait_for(
                        asyncio.to_thread(ray.get, ref),
                        timeout=2.0,
                    )
                else:
                    # Fallback: try a lightweight ping if available
                    # If Ray can't talk to the actor, an exception will be raised
                    # This is a best-effort check
                    try:
                        # Try accessing actor metadata as a lightweight check
                        _ = handle.__class__.__name__
                    except Exception:
                        alive = False
            except Exception:
                alive = False

            agent_statuses[agent_id] = {
                "status": "registered" if alive else "unreachable",
                "alive": alive,
            }

        return {
            "organ_id": self.organ_id,
            "status": "healthy",  # organ-level; could down-rank if many agents are dead
            "agent_count": len(self.agents),
            "agents": agent_statuses,
        }

    # ==========================================================
    # Lifecycle & Metadata (Runtime Updates)
    # ==========================================================

    async def heartbeat(self, agent_id: str, metrics: Dict[str, Any]) -> None:
        """
        Lightweight runtime update.
        Agents call this periodically to report status, load, and new skills.
        """
        # 1. Fast existence check
        if agent_id not in self.agent_info:
            # Agent might have crashed and organ restarted.
            # In a robust system, we might ask it to re-register.
            logger.warning(
                f"[{self.organ_id}] Received heartbeat from unknown agent {agent_id}"
            )
            return

        # 2. Get reference to mutable metadata dict
        info = self.agent_info[agent_id]

        # 3. Update Dynamic Metrics (Load, Status)
        if "load" in metrics:
            info["load"] = metrics["load"]
        if "status" in metrics:
            info["status"] = metrics["status"]

        # 4. Update Skills (Crucial for Router V2)
        # If the agent learned something new since startup, we capture it here.
        if "skills" in metrics and isinstance(metrics["skills"], dict):
            # We merge updates rather than strict overwrite if you want to support partial updates,
            # but usually replacing the skill dict is safer to remove stale skills.
            info["skills"] = metrics["skills"]

        # 5. Update Timestamp
        info["last_heartbeat"] = time.time()

        # (Optional) Log if debug mode is on
        # logger.debug(f"[{self.organ_id}] Heartbeat processed for {agent_id}")

    # ==========================================================
    # Telemetry & Stats (Per-Organ Agent Statistics)
    # ==========================================================

    async def collect_agent_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Collect summary statistics from all agents in this organ.

        Returns:
            Dictionary mapping agent_id -> stats dict (whatever agent.get_summary_stats() returns)
        """
        if not self.agents:
            return {}

        timeout = float(os.getenv("ORGAN_STATS_TIMEOUT", "2.5"))
        items = list(self.agents.items())
        stats: Dict[str, Dict[str, Any]] = {}

        async def _get_stats(agent_id: str, handle: AgentHandle):
            try:
                ref = handle.get_summary_stats.remote()
                res = await asyncio.wait_for(
                    asyncio.to_thread(ray.get, ref),
                    timeout=timeout,
                )
                stats[agent_id] = res
            except Exception as e:
                logger.debug(f"[{self.organ_id}] Stats error for {agent_id}: {e}")

        tasks = [_get_stats(agent_id, handle) for agent_id, handle in items]
        await asyncio.gather(*tasks, return_exceptions=True)

        logger.debug(f"[{self.organ_id}] ✅ Collected stats: {len(stats)}/{len(items)}")

        # Warn if we have agents but collected no stats
        if len(items) > 0 and len(stats) == 0:
            logger.warning(
                f"[{self.organ_id}] No stats collected from {len(items)} agents - "
                "agents may not support get_summary_stats() or may be unreachable"
            )

        return stats

    async def get_summary(self) -> Dict[str, Any]:
        """
        Compute a simple per-organ summary over agent stats.

        Returns:
            Dictionary with organ-level aggregated statistics
        """
        stats = await self.collect_agent_stats()
        if not stats:
            return {
                "organ_id": self.organ_id,
                "agent_count": len(self.agents),
                "status": "no_agents",
            }

        total_agents = len(stats)
        total_tasks = sum(s.get("tasks_processed", 0) for s in stats.values())
        avg_cap = (
            sum(s.get("capability_score", 0.0) for s in stats.values()) / total_agents
            if total_agents > 0
            else 0.0
        )
        avg_mem = (
            sum(s.get("mem_util", 0.0) for s in stats.values()) / total_agents
            if total_agents > 0
            else 0.0
        )

        # Calculate organ-level metrics
        total_memory_writes = sum(s.get("memory_writes", 0) for s in stats.values())
        total_peer_interactions = sum(
            s.get("peer_interactions_count", 0) for s in stats.values()
        )

        return {
            "organ_id": self.organ_id,
            "agent_count": total_agents,
            "total_tasks_processed": total_tasks,
            "average_capability_score": avg_cap,
            "average_memory_utilization": avg_mem,
            "total_memory_writes": total_memory_writes,
            "total_peer_interactions": total_peer_interactions,
            "status": "active",
        }

    async def get_agent_private_memory(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch private memory vector & telemetry for a single agent in this organ.

        Args:
            agent_id: Agent identifier

        Returns:
            Dictionary with 'h' (memory vector) and 'telemetry', or None if not found
        """
        handle = self.agents.get(agent_id)
        if not handle:
            logger.warning(
                f"[{self.organ_id}] Agent {agent_id} not found for private memory fetch"
            )
            return None
        try:
            h_ref = handle.get_private_memory_vector.remote()
            tel_ref = handle.get_private_memory_telemetry.remote()
            # Fetch both concurrently to reduce latency (single RPC instead of two sequential)
            # ray.get([ref1, ref2]) returns [res1, res2]
            h, tel = await asyncio.to_thread(lambda: ray.get([h_ref, tel_ref]))
            return {"h": h, "telemetry": tel}
        except Exception:
            # Legacy fallback
            try:
                state_ref = handle.get_state.remote()
                state = await asyncio.to_thread(ray.get, state_ref)
                return {"h": state.get("h")}
            except Exception as e:
                logger.error(
                    f"[{self.organ_id}] Failed to get private memory for {agent_id}: {e}"
                )
                return None

    async def fetch_agent_memory_with_cache(
        self, agent_id: str, item_id: str
    ) -> Optional[Any]:
        """
        Full cache → LTM fetch via the agent.

        Args:
            agent_id: Agent identifier
            item_id: Item identifier to fetch

        Returns:
            Fetched data or None if not found
        """
        handle = self.agents.get(agent_id)
        if not handle:
            logger.warning(
                f"[{self.organ_id}] Agent {agent_id} not found for memory fetch"
            )
            return None
        try:
            ref = handle.fetch_with_cache.remote(item_id)
            data = await asyncio.to_thread(ray.get, ref)
            return data
        except Exception as e:
            logger.error(
                f"[{self.organ_id}] Failed to fetch memory via agent {agent_id}: {e}"
            )
            return None

    async def reset_agent_metrics(self, agent_id: str) -> bool:
        """
        Reset metrics for a specific agent in this organ.

        Args:
            agent_id: Agent identifier

        Returns:
            True if successful, False otherwise
        """
        handle = self.agents.get(agent_id)
        if not handle:
            return False
        try:
            ref = handle.reset_metrics.remote()
            await asyncio.to_thread(ray.get, ref)
            logger.info(f"[{self.organ_id}] 🔄 Reset metrics for agent {agent_id}")
            return True
        except Exception as e:
            logger.error(
                f"[{self.organ_id}] Failed to reset metrics for agent {agent_id}: {e}"
            )
            return False

    def generate_agent_id(self, specialization: "SpecializationProtocol") -> str:
        """
        Generate a new agent ID using AgentIDFactory if available.

        NOTE: Currently unused - OrganismCore generates IDs before calling create_agent(),
        and respawn_agent() reuses the same agent_id. This method is kept for future
        use cases where Organ might need to generate IDs dynamically.

        Args:
            specialization: Agent specialization (static or dynamic)

        Returns:
            Generated agent ID string
        """
        if self.agent_id_factory:
            return self.agent_id_factory.new(self.organ_id, specialization)
        # Fallback: simple ID generation if factory not available
        unique_id = uuid.uuid4().hex[:12]
        spec_value = specialization.value if hasattr(specialization, 'value') else str(specialization)
        return f"agent_{self.organ_id}_{spec_value}_{unique_id}"

    # ==========================================================
    # Routing (Called by OrganismCore/Router)
    # ==========================================================

    async def pick_random_agent(self) -> Tuple[Optional[str], Optional[AgentHandle]]:
        """Returns a random agent_id and handle from this organ."""
        if not self.agents:
            return None, None
        try:
            # Efficiently pick random key
            agent_id = random.choice(list(self.agents.keys()))
            return agent_id, self.agents[agent_id]
        except Exception:
            return None, None

    async def pick_agent_by_skills(
        self, required_skills: Dict[str, float]
    ) -> Tuple[Optional[str], Optional[AgentHandle]]:
        """
        Finds the agent with the highest skill match score.
        Uses a simple weighted sum intersection strategy.
        """
        if not self.agents:
            return None, None

        best_agent_id = None
        best_score = -1.0

        # Iterate all known agents
        for agent_id, info in self.agent_info.items():
            # info['skills'] should be a dict like {'python': 0.9, 'writing': 0.5}
            # If agent hasn't reported skills yet, assume empty
            agent_skills = info.get("skills", {})

            current_score = 0.0

            # Calculate match score
            for req_skill, req_level in required_skills.items():
                # Get agent's level (default 0.0)
                agent_level = agent_skills.get(req_skill, 0.0)
                # Simple additive scoring: reward possession of skill
                current_score += agent_level

            # Update best
            if current_score > best_score:
                best_score = current_score
                best_agent_id = agent_id

        # If we found a winner with a score > 0
        if best_agent_id and best_score > 0:
            return best_agent_id, self.agents[best_agent_id]

        # Fallback: If no skills match (or no skills known), pick random
        return await self.pick_random_agent()

    async def pick_agent_by_specialization(
        self, spec_name: str, required_skills: Optional[Dict[str, float]] = None
    ) -> Tuple[Optional[str], Optional[AgentHandle]]:
        """
        Finds an agent matching the specialization.

        Args:
            spec_name: Enum value or name (e.g. "contextual_planner")
            required_skills: Optional dict to break ties if multiple agents match spec.
        """
        spec_norm = spec_name.lower()
        candidates = []

        # 1. Filter candidates by Specialization
        # Support both new format (specialization as value) and legacy formats
        for agent_id, info in self.agent_info.items():
            # New format: specialization is the value (string)
            stored_value = info.get("specialization", "").lower()
            # Legacy formats: specialization_name or specialization_value
            stored_name = info.get("specialization_name", "").lower()
            legacy_value = info.get("specialization_value", "").lower()

            if (
                stored_value == spec_norm
                or stored_name == spec_norm
                or legacy_value == spec_norm
            ):
                candidates.append(agent_id)

        if not candidates:
            # Fallback if no specific agent matches the spec
            return await self.pick_random_agent()

        # 2. If only one candidate, return it
        if len(candidates) == 1:
            aid = candidates[0]
            return aid, self.agents.get(aid)

        # 3. If multiple candidates AND skills provided, pick best skill match
        if required_skills and len(candidates) > 1:
            best_agent_id = candidates[0]  # Default to first
            best_score = -1.0

            for aid in candidates:
                info = self.agent_info.get(aid, {})
                agent_skills = info.get("skills", {})

                # Calculate simple score
                score = 0.0
                for skill, _ in required_skills.items():
                    score += agent_skills.get(skill, 0.0)

                if score > best_score:
                    best_score = score
                    best_agent_id = aid

            return best_agent_id, self.agents.get(best_agent_id)

        # 4. Otherwise pick random from valid candidates (Load Balancing)
        chosen_id = random.choice(candidates)
        return chosen_id, self.agents.get(chosen_id)

    # ==========================================================
    # Shutdown
    # ==========================================================

    async def shutdown(self) -> None:
        """
        Terminates all agents owned by this organ.
        Called by OrganismCore's shutdown.
        """
        logger.info(
            f"[{self.organ_id}] Shutting down, terminating {len(self.agents)} agents..."
        )
        agent_ids = list(self.agents.keys())
        tasks = []

        for agent_id in agent_ids:
            tasks.append(self.remove_agent(agent_id))

        await asyncio.gather(*tasks)
        logger.info(f"[{self.organ_id}] Shutdown complete.")
