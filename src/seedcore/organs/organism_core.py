# =====================================================================
#  ORGANISM CORE — COMPLETE REWRITE (2025)
#  Version: SeedCore Cognitive Architecture v2
#  Author: ChatGPT (with Ning)
#
#  Overview:
#    Tier-1 OrganismCore: Registry + Execution Layer
#
#    This module implements the Tier-1 registry and execution layer for the
#    distributed cognitive organism. It is responsible for:
#
#      • Maintaining organ and agent registries
#      • Direct agent-level execution (given organ_id + agent_id)
#      • Health monitoring and reconciliation
#      • Agent workforce evolution (scale up/down)
#      • Connection to the distributed LongTermMemoryManager Ray actor
#
#    Architecture:
#      • RoutingDirectory (Tier-0) = routing decisions and policy brain
#      • OrganismCore (Tier-1) = registry + execution (no routing decisions)
#      • Organ = agent registry + local supervision
#      • Agent = actual executor
#
#    Routing flow:
#      RoutingDirectory.route_and_execute() → makes routing decisions
#      → calls OrganismCore.execute_on_agent(organ_id, agent_id, payload)
#      → performs single-hop RPC to agent actor
#
#    This replaces the old Tier0 design and the older organ.execute_task
#    execution model. All execution is now single-hop:
#
#        RoutingDirectory → OrganismCore → agent_actor.execute_task(...)
#
#    This improves latency, fault isolation, and makes routing explicit.
#
# =====================================================================

from __future__ import annotations

import asyncio
import os
import time
import uuid
import yaml  # pyright: ignore[reportMissingModuleSource]
from pathlib import Path
from typing import Dict, Any, Optional, List

import ray  # type: ignore

# ---------------------------------------------------------------------
#  SeedCore Imports
# ---------------------------------------------------------------------
from seedcore.agents.roles.specialization import Specialization, RoleRegistry
from seedcore.agents.roles.skill_vector import SkillStoreProtocol
from seedcore.agents.roles.generic_defaults import DEFAULT_ROLE_REGISTRY
from seedcore.tools.manager import ToolManager
from seedcore.serve.cognitive_client import CognitiveServiceClient
from seedcore.serve.energy_client import EnergyServiceClient
from seedcore.models import TaskPayload

from seedcore.logging_setup import setup_logging, ensure_serve_logger
from seedcore.organs.organ import Organ, AgentIDFactory  # ← NEW ORGAN CLASS
from seedcore.organs.router import RoutingDirectory

# Long-term memory backend (Ray actor)
from seedcore.memory.long_term_memory import LongTermMemoryManager
# --- Import stateful dependencies ---
from seedcore.memory.mw_manager import MwManager

setup_logging(app_name="seedcore.OrganismCore")
logger = ensure_serve_logger("seedcore.OrganismCore", level="DEBUG")

# ---------------------------------------------------------------------
#  Settings & Environment
# ---------------------------------------------------------------------

AGENT_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
ORGANS_CONFIG_PATH = os.getenv("ORGANS_CONFIG_PATH", "/app/config/organs.yaml")


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "y", "on")


# =====================================================================
#  SkillStore Adapter — Bridge LTM to SkillStoreProtocol
# =====================================================================


class LTMSkillStoreAdapter(SkillStoreProtocol):
    """
    Wraps a Ray LongTermMemoryManager actor to satisfy SkillStoreProtocol.
    This is the unified storage backend for agent skill vectors.
    """

    def __init__(self, ltm_handle):
        self.ltm = ltm_handle

    async def get_skill_vector(self, agent_id: str) -> Optional[List[float]]:
        try:
            result = await self.ltm.query_holon_by_id_async.remote(agent_id)
            result = await asyncio.to_thread(ray.get, result)
            if result and "embedding" in result:
                return result["embedding"]
            return None
        except Exception as e:
            logger.error(f"[SkillStore] Error loading skill vector for {agent_id}: {e}")
            return None

    async def save_skill_vector(
        self, agent_id: str, vector: List[float], meta: Dict[str, Any] = None
    ) -> bool:
        """
        Persist an agent's skill vector into LTM as a holon.
        """
        try:
            holon = {
                "vector": {"id": agent_id, "embedding": vector, "meta": meta or {}}
            }
            ref = self.ltm.insert_holon_async.remote(holon)
            return bool(await asyncio.to_thread(ray.get, ref))
        except Exception as e:
            logger.error(f"[SkillStore] Error saving skill vector for {agent_id}: {e}")
            return False


# =====================================================================
#  OrganismCore — Tier-1 Registry + Execution Layer (v2 Architecture)
#  OrganismCore = registry + execution; RoutingDirectory = Tier-0 router
#  Organ = agent registry; Agent = executor; Core = registry + execution
# =====================================================================


class OrganismCore:
    """
    Tier-1 OrganismCore: Registry and Execution Layer
    
    Responsibilities:
      1. Registry:
         - Maintain organs
         - Maintain agent registry
         - Maintain agent handles
      
      2. Execution:
         - Given (organ_id, agent_id, task_dict) → perform single-hop RPC
         - Pure execution, NO routing logic
      
      3. Health / Evolution:
         - Health checks
         - Agent/organ reconciliation
         - Evolution operations (scale up/down)
      
      4. Registry API for Router:
         - get_all_agents()
         - get_all_agent_skills()
         - get_specialization_map()
         - get_organ_health()
    
    Architecture:
      - Router pulls data; OrganismCore never pushes routing logic
      - Router makes routing decisions and calls execute_on_agent()
      - OrganismCore is a pure registry + execution layer
    """

    def __init__(
        self,
        config_path: Path | str = ORGANS_CONFIG_PATH,
        role_registry: Optional[RoleRegistry] = None,
    ):
        self._initialized = False
        self._lock = asyncio.Lock()

        self.organ_configs: List[Dict[str, Any]] = []
        self.organs: Dict[str, ray.actor.ActorHandle] = {}

        # Specialization → organ mapping (for registry API only, NOT for routing decisions)
        # This is maintained for get_specialization_map() registry API
        self.specialization_to_organ: Dict[Specialization, str] = {}

        # Agent → organ (informational only, for registry)
        self.agent_to_organ_map: Dict[str, str] = {}

        # Load config (YAML)
        self._load_config(config_path)

        # Global infrastructure
        self.role_registry: RoleRegistry = role_registry or DEFAULT_ROLE_REGISTRY
        self.skill_store: Optional[LTMSkillStoreAdapter] = None
        self.tool_manager: Optional[ToolManager] = None
        self.cognitive_client: Optional[CognitiveServiceClient] = None
        self.energy_client: Optional[EnergyServiceClient] = None
        self.ltm_handle: Optional[Any] = None
        
        # --- Stateful dependencies for RayAgent ---
        self.mw_manager: Optional[MwManager] = None
        self.checkpoint_cfg: Dict[str, Any] = {
            "enabled": True,
            "path": os.getenv("CHECKPOINT_PATH", "/app/checkpoints")
        }
        
        # Evolution guardrails
        self._evolve_max_cost = float(os.getenv("EVOLVE_MAX_COST", "1e6"))
        self._evolve_min_roi = float(os.getenv("EVOLVE_MIN_ROI", "0.2"))

        # Background tasks
        self._health_check_task: Optional[asyncio.Task] = None
        self._recon_task: Optional[asyncio.Task] = None
        self._health_interval = int(os.getenv("HEALTHCHECK_INTERVAL_S", "20"))
        self._recon_interval = int(os.getenv("RECONCILE_INTERVAL_S", "20"))
        self._shutdown_event = asyncio.Event()
        self._reconcile_queue: List[tuple] = []
        
        # State service (lazy connection)
        self._state_service: Optional[Any] = None

    # ------------------------------------------------------------------
    #  CONFIG LOADING
    # ------------------------------------------------------------------
    def _load_config(self, path: Path | str):
        try:
            path = Path(path)
            with open(path, "r") as f:
                cfg = yaml.safe_load(f)
                self.organ_configs = cfg["seedcore"]["organism"]["organs"]
                logger.info(
                    f"[OrganismCore] Loaded {len(self.organ_configs)} organ configs."
                )
        except Exception as e:
            logger.error(f"[OrganismCore] Failed to load config {path}: {e}")
            self.organ_configs = []

    # ------------------------------------------------------------------
    #  INIT SEQUENCE
    # ------------------------------------------------------------------
    async def initialize_organism(self):
        """
        Bootstraps:
          0. Ensure Janitor actor (system maintenance service)
          1. LongTermMemoryManager Ray actor
          2. SkillStore adapter
          3. RoleRegistry
          4. ToolManager
          5. CognitiveServiceClient
          6. Organ actors
          7. Agent actors
          8. Background health + reconciliation loops
        """

        if self._initialized:
            logger.warning("[OrganismCore] Already initialized.")
            return

        if not ray.is_initialized():
            raise RuntimeError("Ray must be initialized before OrganismCore startup.")

        logger.info("🚀 Starting OrganismCore initialization...")

        # --------------------------------------------------------------
        # 0. Ensure Janitor actor (system maintenance service)
        # --------------------------------------------------------------
        await self._ensure_janitor_actor()

        # --------------------------------------------------------------
        # 1. Start distributed LongTermMemoryManager
        # --------------------------------------------------------------
        try:
            logger.info("🔌 Launching LongTermMemoryManager (Ray actor)...")

            self.ltm_handle = LongTermMemoryManager.options(
                name="ltm_manager",
                lifetime="detached",
                namespace=AGENT_NAMESPACE,
                max_restarts=-1,
                max_task_retries=-1,
            ).remote()

            # Async initialization inside actor
            await self._ray_await(self.ltm_handle.initialize.remote())

            logger.info("✅ LTM Manager ready.")

        except Exception as e:
            logger.error(
                f"[OrganismCore] Failed to start LTM Manager: {e}", exc_info=True
            )
            raise

        # --------------------------------------------------------------
        # 2. Create SkillStore adapter
        # --------------------------------------------------------------
        self.skill_store = LTMSkillStoreAdapter(self.ltm_handle)

        # --------------------------------------------------------------
        # 3. RoleRegistry (already set in __init__ via DEFAULT_ROLE_REGISTRY or provided)
        # --------------------------------------------------------------
        logger.info(
            f"[OrganismCore] Using RoleRegistry with {len(list(self.role_registry.all_profiles()))} profiles."
        )

        # --------------------------------------------------------------
        # 4. ToolManager (with skill store for micro-flywheel)
        # --------------------------------------------------------------
        self.tool_manager = ToolManager(skill_store=self.skill_store)

        # --------------------------------------------------------------
        # 5. Cognitive service client
        # --------------------------------------------------------------
        self.cognitive_client = CognitiveServiceClient()
        
        # --------------------------------------------------------------
        # 5.5. Energy service client (for evolution flywheel)
        # --------------------------------------------------------------
        self.energy_client = EnergyServiceClient()

        # --------------------------------------------------------------
        # 5.6. Initialize stateful MwManager
        # --------------------------------------------------------------
        logger.info("🔌 Initializing stateful MwManager...")
        try:
            self.mw_manager = MwManager(organ_id="organism_core_mw")
            logger.info("✅ MwManager initialized.")
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize MwManager: {e}")
            self.mw_manager = None

        # --------------------------------------------------------------
        # 6. Spawn Organs
        # --------------------------------------------------------------
        await self._create_organs_from_config()

        # --------------------------------------------------------------
        # 7. Spawn Agents
        # --------------------------------------------------------------
        await self._create_agents_from_config()

        # --------------------------------------------------------------
        # 7.5. Initialize Router with dependencies
        # --------------------------------------------------------------
        agent_id_factory = AgentIDFactory()
        
        self.router = RoutingDirectory(
            agent_id_factory=agent_id_factory,
            organism=self,
            cognitive_client=self.cognitive_client,
            role_registry=self.role_registry,
            skill_store=self.skill_store,
        )
        logger.info("✅ Router initialized with OrganismCore dependencies")

        # --------------------------------------------------------------
        # 8. Background tasks
        # --------------------------------------------------------------
        if _env_bool("ORGANISM_HEALTHCHECKS", True):
            self._health_check_task = asyncio.create_task(self._health_loop())

        if _env_bool("ORGANISM_RECONCILE", True):
            self._recon_task = asyncio.create_task(self._reconciliation_loop())

        self._initialized = True
        logger.info("🌱 OrganismCore initialization complete!")

    # ==================================================================
    #  ORGAN CREATION
    # ==================================================================
    async def _create_organs_from_config(self):
        """
        Instantiate all Organ actors defined in the YAML config.
        """
        logger.info(f"[OrganismCore] Spawning {len(self.organ_configs)} organs...")

        for cfg in self.organ_configs:
            organ_id = cfg["id"]

            if organ_id in self.organs:
                logger.info(f"  ↪ Organ {organ_id} already exists.")
                continue

            logger.info(f"  ➕ Creating Organ actor: {organ_id}")

            try:
                # --- Pass all dependencies to the Organ actor ---
                organ = Organ.options(
                    name=organ_id,
                    namespace=AGENT_NAMESPACE,
                    lifetime="detached",
                    max_restarts=-1,
                    max_task_retries=-1,
                    num_cpus=0.1,
                ).remote(
                    organ_id=organ_id,
                    # Stateless dependencies
                    role_registry=self.role_registry,
                    skill_store=self.skill_store,
                    tool_manager=self.tool_manager,
                    cognitive_client=self.cognitive_client,
                    # Stateful dependencies
                    mw_manager=self.mw_manager,
                    ltm_manager=self.ltm_handle,
                    checkpoint_cfg=self.checkpoint_cfg,
                )

                # Sanity check
                ok_ref = organ.health_check.remote()
                ok = await self._ray_await(ok_ref)
                if not ok:
                    raise RuntimeError(f"Organ {organ_id} failed health check.")

                self.organs[organ_id] = organ

            except Exception as e:
                logger.error(
                    f"❌ Failed to create organ '{organ_id}': {e}", exc_info=True
                )
                raise

        logger.info(f"✅ Organ creation complete. Total organs: {len(self.organs)}")

    # ==================================================================
    #  AGENT CREATION
    # ==================================================================
    async def _create_agents_from_config(self):
        """
        Create and distribute all agents specified per organ in config.
        """
        total = 0

        for cfg in self.organ_configs:
            organ_id = cfg["id"]
            organ = self.organs.get(organ_id)

            if not organ:
                logger.error(f"[OrganismCore] Organ {organ_id} missing!")
                continue

            agent_defs = cfg.get("agents", [])
            logger.info(
                f"[OrganismCore] Creating {len(agent_defs)} agent groups for organ {organ_id}..."
            )

            for block in agent_defs:
                spec_str = block["specialization"]
                count = int(block.get("count", 1))
                
                # --- Read agent class from config (default to BaseAgent) ---
                agent_class_name = block.get("class", "BaseAgent")

                try:
                    spec = Specialization[spec_str.upper()]
                except KeyError:
                    logger.error(
                        f"Invalid specialization '{spec_str}' in config for organ {organ_id}"
                    )
                    continue

                # Map specialization → organ
                if spec not in self.specialization_to_organ:
                    self.specialization_to_organ[spec] = organ_id

                # Spawn agents
                for i in range(count):
                    agent_id = f"{organ_id}_{spec.value}_{i}"

                    # --- Tell the Organ which class to create ---
                    ref = organ.create_agent.remote(
                        agent_id=agent_id,
                        specialization=spec,
                        organ_id=organ_id,
                        agent_class_name=agent_class_name,
                        name=agent_id,
                        num_cpus=0.1,
                        lifetime="detached",
                    )

                    await self._ray_await(ref)
                    self.agent_to_organ_map[agent_id] = organ_id
                    total += 1

        logger.info(f"🤖 Spawned {total} agents across {len(self.organs)} organs.")
        logger.info(
            f"🗺 Built specialization routing map: { {k.name: v for k, v in self.specialization_to_organ.items()} }"
        )

    # =====================================================================
    #  ASYNC RAY HELPER
    # =====================================================================
    
    async def _ray_await(self, obj_ref, *, timeout: Optional[float] = None):
        """
        Helper to await Ray object references without blocking the event loop.
        
        Args:
            obj_ref: Ray object reference
            timeout: Optional timeout in seconds
            
        Returns:
            The result from ray.get()
        """
        return await asyncio.to_thread(ray.get, obj_ref, timeout=timeout)

    # =====================================================================
    #  TASK EXECUTION (PURE EXECUTION, NO ROUTING DECISIONS)
    # =====================================================================

    def _is_high_stakes_from_payload(self, payload: TaskPayload | Dict[str, Any]) -> bool:
        """
        Inspect payload.params.risk and return is_high_stakes flag.
        
        NOTE: This is a fallback method. The primary source of truth for is_high_stakes
        is the router's decision, which is embedded in payload.params._router_metadata.is_high_stakes.
        This method is used only for backward compatibility when router metadata is not present.
        
        Architecture:
        - Routing determines is_high_stakes during route_only()
        - Router embeds it in payload.params._router_metadata.is_high_stakes
        - Execution reads from router metadata (single source of truth)
        - This ensures routing and execution are always consistent
        """
        if isinstance(payload, TaskPayload):
            task_dict = payload.model_dump()
        else:
            task_dict = payload or {}
        params = task_dict.get("params", {}) or {}
        risk = params.get("risk", {}) or {}
        return bool(risk.get("is_high_stakes", False))

    async def execute_on_agent(
        self,
        organ_id: str,
        agent_id: str,
        payload: TaskPayload | Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute task on a specific agent within an organ.

        - For normal tasks: call agent.execute_task(...)
        - For high-stakes tasks: delegate to organ.execute_high_stakes(...),
          which calls agent.execute_high_stakes_task(...).

        No routing decisions here – only execution semantics.
        
        Args:
            organ_id: Organ ID containing the agent
            agent_id: Agent ID to execute the task on
            payload: TaskPayload or dict to execute
        
        Returns:
            Dict with organ_id, agent_id, and result/error
        """
        organ = self.organs.get(organ_id)
        if not organ:
            return {"error": f"Organ '{organ_id}' not found"}

        try:
            # Normalize payload to dict for both paths
            task_dict = (
                payload.model_dump() if isinstance(payload, TaskPayload) else payload
            ) or {}

            # Get agent handle from organ registry
            agent_handle_ref = organ.get_agent_handle.remote(agent_id)
            agent_handle = await self._ray_await(agent_handle_ref)

            if not agent_handle:
                return {"error": f"Agent '{agent_id}' not found in organ '{organ_id}'"}

            # Detect high-stakes from router's decision (single source of truth)
            # Router determines is_high_stakes during routing and embeds it in payload
            # This ensures execution honors routing's decision consistently
            router_metadata = task_dict.get("params", {}).get("_router_metadata", {})
            is_high_stakes = router_metadata.get("is_high_stakes", False)
            
            # Fallback: if router didn't set it, check payload risk (backward compatibility)
            if not is_high_stakes:
                is_high_stakes = self._is_high_stakes_from_payload(task_dict)

            if is_high_stakes:
                # 🔐 HIGH-STAKES EXECUTION PATH
                # Call agent's execute_high_stakes_task() directly
                if hasattr(agent_handle, "execute_high_stakes_task"):
                    ref = agent_handle.execute_high_stakes_task.remote(task_dict)
                else:
                    # Fallback: use normal execution if agent doesn't support high-stakes
                    logger.warning(
                        f"[execute_on_agent] Agent {agent_id} doesn't support execute_high_stakes_task, "
                        "falling back to execute_task"
                    )
                    ref = agent_handle.execute_task.remote(task_dict)
                result = await self._ray_await(ref, timeout=300.0)  # 5 min timeout for high-stakes
            else:
                # 🟢 NORMAL EXECUTION PATH
                # Execute task directly on agent actor
                ref = agent_handle.execute_task.remote(task_dict)
                result = await self._ray_await(ref)

            return {
                "organ_id": organ_id,
                "agent_id": agent_id,
                "result": result,
            }

        except Exception as e:
            logger.error(f"[execute_on_agent] Error: {e}", exc_info=True)
            return {
                "organ_id": organ_id,
                "agent_id": agent_id,
                "error": f"Execution failure: {e}",
            }

    # =====================================================================
    #  REGISTRY API FOR ROUTER (Router pulls data; OrganismCore never pushes routing logic)
    # =====================================================================

    async def get_all_agents(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all agents with their metadata.
        
        Returns:
            Dict mapping agent_id -> agent metadata dict
        """
        all_agents = {}
        for organ_id, organ in self.organs.items():
            try:
                ref = organ.get_agent_handles.remote()
                agent_handles = await self._ray_await(ref)
                for agent_id in agent_handles.keys():
                    agent_info = await self.get_agent_info(agent_id)
                    if "error" not in agent_info:
                        all_agents[agent_id] = {
                            **agent_info,
                            "organ_id": organ_id,
                        }
            except Exception as e:
                logger.debug(f"[get_all_agents] Failed to get agents from organ {organ_id}: {e}")
                continue
        return all_agents

    async def get_all_agent_skills(self) -> Dict[str, Optional[List[float]]]:
        """
        Get skill vectors for all agents.
        
        Returns:
            Dict mapping agent_id -> skill vector (or None if not available)
        """
        if not self.skill_store:
            return {}
        
        all_agents = await self.get_all_agents()
        skills = {}
        for agent_id in all_agents.keys():
            try:
                skill_vector = await self.skill_store.get_skill_vector(agent_id)
                skills[agent_id] = skill_vector
            except Exception as e:
                logger.debug(f"[get_all_agent_skills] Failed to get skills for {agent_id}: {e}")
                skills[agent_id] = None
        return skills

    def get_specialization_map(self) -> Dict[str, str]:
        """
        Get specialization -> organ_id mapping.
        
        Returns:
            Dict mapping specialization name -> organ_id
        """
        return {
            spec.name: organ_id 
            for spec, organ_id in self.specialization_to_organ.items()
        }
    
    def map_specializations(self) -> Dict[str, str]:
        """
        [DEPRECATED] Alias for get_specialization_map().
        
        Use get_specialization_map() instead for consistency.
        
        Returns:
            Dict mapping specialization name -> organ_id
        """
        return self.get_specialization_map()

    async def get_organ_health(self) -> Dict[str, Dict[str, Any]]:
        """
        Get health status for all organs.
        
        Returns:
            Dict mapping organ_id -> health status dict
        """
        health = {}
        for organ_id, organ in self.organs.items():
            try:
                ref = organ.get_status.remote()
                status = await self._ray_await(ref)
                health[organ_id] = status
            except Exception as e:
                health[organ_id] = {"error": str(e), "status": "unhealthy"}
        return health

    # =====================================================================
    #  INTROSPECTION API — OBSERVE CLOSELY
    # =====================================================================

    def list_organs(self) -> List[str]:
        return list(self.organs.keys())

    async def list_agents(self, organ_id: Optional[str] = None) -> List[str]:
        """
        List all agent IDs from a specific organ or all organs.
        
        In v2 architecture:
        - Organ = agent registry (lightweight container)
        - This queries the registry for agent IDs (not handles)
        
        This method efficiently reuses get_all_agent_handles() when listing from all organs,
        avoiding code duplication.
        
        Args:
            organ_id: Optional organ ID to list agents from. If None, lists from all organs.
            
        Returns:
            List[str]: List of agent IDs
        """
        if organ_id:
            # Query specific organ
            organ = self.organs.get(organ_id)
            if not organ:
                return []
            ref = organ.list_agents.remote()
            return await self._ray_await(ref)
        else:
            # Reuse get_all_agent_handles() to avoid duplication
            # Just extract the keys (agent IDs) from the handles dictionary
            handles = await self.get_all_agent_handles()
            return list(handles.keys())


    async def get_agent_info(self, agent_id: str) -> Dict[str, Any]:
        """
        Returns metadata about an agent, if alive.
        """
        organ_id = self.agent_to_organ_map.get(agent_id)
        if not organ_id:
            return {"error": f"Agent '{agent_id}' unknown"}

        organ = self.organs.get(organ_id)
        if not organ:
            return {"error": f"Organ '{organ_id}' unavailable"}

        try:
            ref = organ.get_agent_info.remote(agent_id)
            return await self._ray_await(ref)
        except Exception as e:
            return {"error": str(e)}

    async def get_all_agent_handles(self) -> Dict[str, Any]:
        """
        Get all agent handles from all organs.
        
        In v2 architecture:
        - Organ = agent registry (lightweight container)
        - Agent = true execution endpoint (Ray actor handle)
        
        This method queries each organ registry to get its registered agent handles,
        then aggregates them into a single dictionary.
        
        Returns:
            Dict[str, Any]: Dictionary mapping agent_id -> agent_handle (Ray actor handle).
                           These are the actual BaseAgent Ray actor handles that can
                           be used to call .remote() methods like get_heartbeat().
        
        Example:
            {
                "organ1_research_0": <RayActorHandle>,
                "organ1_research_1": <RayActorHandle>,
                "organ2_critic_0": <RayActorHandle>,
                ...
            }
        """
        all_agent_handles: Dict[str, Any] = {}
        
        for organ_id, organ in self.organs.items():
            try:
                # Query the organ registry for its agent handles
                # Organ.get_agent_handles() returns Dict[agent_id, agent_handle]
                ref = organ.get_agent_handles.remote()
                organ_agent_handles = await self._ray_await(ref)
                
                # Merge agent handles into the global dictionary
                # Note: organ_agent_handles is already Dict[agent_id, agent_handle]
                all_agent_handles.update(organ_agent_handles)
            except Exception as e:
                logger.warning(f"[get_all_agent_handles] Failed to get agent handles from organ {organ_id}: {e}")
                continue
        
        logger.debug(f"[get_all_agent_handles] Returning {len(all_agent_handles)} agent handles from {len(self.organs)} organs")
        return all_agent_handles

    async def get_organ_status(self, organ_id: str) -> Dict[str, Any]:
        organ = self.organs.get(organ_id)
        if not organ:
            return {"error": f"Organ '{organ_id}' does not exist"}
        try:
            ref = organ.get_status.remote()
            return await self._ray_await(ref)
        except Exception as e:
            return {"error": str(e)}

    async def get_system_status(self) -> Dict[str, Any]:
        """
        Returns a complete map of organ and agent health.
        """
        out = {"organs": {}, "specialization_map": self.get_specialization_map()}
        for oid, organ in self.organs.items():
            try:
                ref = organ.get_status.remote()
                out["organs"][oid] = await self._ray_await(ref)
            except Exception as e:
                out["organs"][oid] = {"error": str(e)}
        return out

    # =====================================================================
    #  EVOLUTION API — AGENT WORKFORCE SCALING (v2)
    # =====================================================================

    async def evolve(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute AGENT WORKFORCE evolution operations (v2).
        
        This is the agent-centric evolution system. Instead of splitting/merging
        organs (organ-centric), we scale up/down the agent workforce for a
        given specialization.
        
        Proposal format:
            {
                "op": "scale_up" | "scale_down",
                "target_specialization": "DeviceOrchestrator" | "Critic" | etc.,
                "count": int  # Number of agents to add/remove
            }
        
        Returns:
            Dict with evolution result including energy measurements and flywheel feedback.
        """
        if not self._initialized:
            return {"success": False, "error": "OrganismCore not initialized"}

        op = proposal.get("op")
        spec_name = proposal.get("target_specialization")
        count = proposal.get("count", 1)

        if not op or not spec_name:
            return {"success": False, "error": "Missing 'op' or 'target_specialization'"}

        if op not in ["scale_up", "scale_down"]:
            return {"success": False, "error": f"Unknown operation: {op}. Must be 'scale_up' or 'scale_down'"}

        if count <= 0:
            return {"success": False, "error": "count must be positive"}

        # --- 1. GET ENERGY BEFORE (Proactive Way) ---
        E_before = 0.0
        try:
            if self.energy_client:
                E_before_metrics = await self.energy_client.get_metrics()
                E_before = E_before_metrics.get("total", 0.0)
        except Exception as e:
            logger.warning(f"[evolve] Failed to get energy before: {e}")

        # --- 2. CHECK GUARDRAILS ---
        estimated_cost = self._estimate_agent_spinup_cost(op, count, spec_name)
        if estimated_cost > self._evolve_max_cost:
            return {
                "success": False,
                "error": f"Estimated cost {estimated_cost} exceeds max {self._evolve_max_cost}",
            }

        try:
            # --- 3. EXECUTE v2 OPERATION ---
            if op == "scale_up":
                result = await self._execute_scale_up(spec_name, count)
            elif op == "scale_down":
                result = await self._execute_scale_down(spec_name, count)
            else:
                return {"success": False, "error": f"Unknown op: {op}"}

            if not result.get("success", False):
                return result

            # --- 4. GET ENERGY AFTER ---
            # Wait a moment for system to stabilize
            await asyncio.sleep(2.0)
            E_after = 0.0
            try:
                if self.energy_client:
                    E_after_metrics = await self.energy_client.get_metrics()
                    E_after = E_after_metrics.get("total", 0.0)
            except Exception as e:
                logger.warning(f"[evolve] Failed to get energy after: {e}")

            delta_E = E_after - E_before

            # --- 5. CHECK ROI GUARDRAIL ---
            roi = None
            if delta_E is not None and estimated_cost > 0:
                roi = delta_E / estimated_cost
                if roi < self._evolve_min_roi:
                    logger.warning(
                        f"[evolve] Evolution ROI {roi} below minimum {self._evolve_min_roi}"
                    )
                    # Continue execution but log the warning

            # --- 6. LOG TO FLYWHEEL ---
            # This is the feedback loop!
            try:
                if self.energy_client:
                    await self.energy_client.post_flywheel_result(
                        delta_e=delta_E,
                        cost=estimated_cost,
                        breakdown={"total": delta_E},
                    )
            except Exception as e:
                logger.warning(f"[evolve] Failed to post flywheel result: {e}")

            return {
                "success": True,
                "op": op,
                "specialization": spec_name,
                "delta_E_realized": delta_E,
                "cost": estimated_cost,
                "roi": roi,
                "result": result.get("result", {}),
            }

        except Exception as e:
            logger.error(f"[evolve] Evolution operation {op} failed: {e}", exc_info=True)
            # Log failure to flywheel
            try:
                if self.energy_client:
                    await self.energy_client.post_flywheel_result(
                        delta_e=0.0,  # No change
                        cost=estimated_cost,
                        breakdown={"error": 1.0},
                    )
            except Exception:
                pass
            return {"success": False, "error": str(e)}

    def _estimate_agent_spinup_cost(self, op: str, count: int, spec_name: str) -> float:
        """
        Estimate the cost of scaling agents.
        
        This is a simple cost model. In production, you might want to:
        - Factor in agent specialization complexity
        - Consider current system load
        - Use historical data
        """
        base_cost_per_agent = 100.0  # Base cost for spinning up/down an agent
        
        # Scale up is more expensive (creating resources)
        # Scale down is cheaper (releasing resources)
        multiplier = 1.0 if op == "scale_up" else 0.5
        
        return base_cost_per_agent * count * multiplier

    def _get_organ_for_specialization(self, spec_name: str) -> Optional[ray.actor.ActorHandle]:
        """
        Get the organ handle for a given specialization name.
        
        ⚠️ NOTE: This method is used ONLY for evolution operations (scaling agents),
        NOT for routing decisions. Evolution needs to know which organ contains
        agents of a given specialization to scale them up/down.
        
        Args:
            spec_name: Specialization name (e.g., "DeviceOrchestrator")
            
        Returns:
            Ray actor handle for the organ, or None if not found
        """
        try:
            spec = Specialization[spec_name.upper()]
        except KeyError:
            logger.error(f"[evolve] Invalid specialization: {spec_name}")
            return None

        # ⚠️ NOTE: Using specialization_to_organ for evolution (lifecycle), NOT routing
        organ_id = self.specialization_to_organ.get(spec)
        if not organ_id:
            logger.error(f"[evolve] No organ found for specialization {spec_name}")
            return None

        organ = self.organs.get(organ_id)
        if not organ:
            logger.error(f"[evolve] Organ {organ_id} not found in active organs")
            return None

        return organ

    async def _execute_scale_up(self, spec_name: str, count: int) -> Dict[str, Any]:
        """
        (v2) Creates new agent actors and registers them with their organ.
        
        Args:
            spec_name: Specialization name (e.g., "DeviceOrchestrator")
            count: Number of agents to create
            
        Returns:
            Dict with success status and created agent IDs
        """
        logger.info(f"[evolve] Scaling up {spec_name} by {count} agents...")

        # 1. Get the 'Organ' (registry) for this specialization
        organ = self._get_organ_for_specialization(spec_name)
        if not organ:
            return {"success": False, "error": f"No organ found for {spec_name}"}

        try:
            spec = Specialization[spec_name.upper()]
        except KeyError:
            return {"success": False, "error": f"Invalid specialization: {spec_name}"}

        # Get organ_id for agent naming
        # ⚠️ NOTE: Using specialization_to_organ for evolution (lifecycle), NOT routing
        organ_id = self.specialization_to_organ.get(spec)
        if not organ_id:
            return {"success": False, "error": f"No organ_id found for {spec_name}"}

        # 2. Loop and create new agent actors
        new_agent_ids = []
        for i in range(count):
            # Generate unique agent ID
            agent_id = f"{organ_id}_{spec.value}_{int(time.time())}_{i}"

            try:
                # Create agent via organ (default to BaseAgent for evolution)
                ref = organ.create_agent.remote(
                    agent_id=agent_id,
                    specialization=spec,
                    organ_id=organ_id,
                    agent_class_name="BaseAgent",  # Default for evolution-created agents
                    name=agent_id,
                    num_cpus=0.1,
                    lifetime="detached",
                )

                await self._ray_await(ref)
                self.agent_to_organ_map[agent_id] = organ_id
                new_agent_ids.append(agent_id)
                logger.info(f"[evolve] Created agent {agent_id}")

            except Exception as e:
                logger.error(f"[evolve] Failed to create agent {agent_id}: {e}", exc_info=True)
                # Continue with other agents even if one fails

        if not new_agent_ids:
            return {"success": False, "error": "Failed to create any agents"}

        logger.info(f"[evolve] Successfully scaled up {spec_name}: created {len(new_agent_ids)} agents")
        return {"success": True, "result": {"created_agents": new_agent_ids, "count": len(new_agent_ids)}}

    async def _execute_scale_down(self, spec_name: str, count: int) -> Dict[str, Any]:
        """
        (v2) Removes agent actors from their organ and cleans up.
        
        Args:
            spec_name: Specialization name (e.g., "DeviceOrchestrator")
            count: Number of agents to remove
            
        Returns:
            Dict with success status and removed agent IDs
        """
        logger.info(f"[evolve] Scaling down {spec_name} by {count} agents...")

        # 1. Get the 'Organ' (registry) for this specialization
        organ = self._get_organ_for_specialization(spec_name)
        if not organ:
            return {"success": False, "error": f"No organ found for {spec_name}"}

        # 2. Get list of agents filtered by specialization
        try:
            # Get all agents from the organ
            agents_ref = organ.get_agent_handles.remote()
            all_agents = await self._ray_await(agents_ref)
            
            # Filter agents by specialization
            # Get agent info for each agent to check specialization
            agent_ids_by_spec = []
            for agent_id in all_agents.keys():
                try:
                    info_ref = organ.get_agent_info.remote(agent_id)
                    info = await self._ray_await(info_ref)
                    if info.get("specialization") == spec_name:
                        agent_ids_by_spec.append(agent_id)
                except Exception as e:
                    logger.debug(f"[evolve] Failed to get info for agent {agent_id}: {e}")
                    continue
            
            if len(agent_ids_by_spec) < count:
                logger.warning(
                    f"[evolve] Only {len(agent_ids_by_spec)} agents with specialization {spec_name} available, requested {count}"
                )
                count = len(agent_ids_by_spec)

            if count == 0:
                return {"success": False, "error": f"No agents with specialization {spec_name} available to remove"}

            # Select agents to remove (simple: take first N)
            agents_to_remove = agent_ids_by_spec[:count]

        except Exception as e:
            logger.error(f"[evolve] Failed to get agents from organ: {e}", exc_info=True)
            return {"success": False, "error": f"Failed to get agents: {e}"}

        # 3. Remove agents
        removed_agent_ids = []
        for agent_id in agents_to_remove:
            try:
                # Remove from organ registry
                ref = organ.remove_agent.remote(agent_id)
                removed = await self._ray_await(ref)
                
                if removed:
                    # Remove from global map
                    self.agent_to_organ_map.pop(agent_id, None)
                    removed_agent_ids.append(agent_id)
                    logger.info(f"[evolve] Removed agent {agent_id}")
                else:
                    logger.warning(f"[evolve] Agent {agent_id} not found in organ")

            except Exception as e:
                logger.error(f"[evolve] Failed to remove agent {agent_id}: {e}", exc_info=True)
                # Continue with other agents even if one fails

        if not removed_agent_ids:
            return {"success": False, "error": "Failed to remove any agents"}

        logger.info(f"[evolve] Successfully scaled down {spec_name}: removed {len(removed_agent_ids)} agents")
        return {"success": True, "result": {"removed_agents": removed_agent_ids, "count": len(removed_agent_ids)}}

    # =====================================================================
    #  STATE AGGREGATION (Ported from OrganismManager)
    # =====================================================================
    
    async def _get_state_service(self) -> Optional[Any]:
        """
        Get or connect to the state service (actor).
        
        NOTE: This method performs a blocking Ray call (ray.get_actor) but wraps it
        in asyncio.to_thread to avoid blocking the event loop. The first call may
        have some latency as it searches multiple namespaces.
        """
        if self._state_service is None:
            try:
                for namespace in ["seedcore-dev", "serve", AGENT_NAMESPACE, "default"]:
                    try:
                        # Use asyncio.to_thread to avoid blocking the event loop
                        self._state_service = await asyncio.to_thread(
                            ray.get_actor, "StateService", namespace=namespace
                        )
                        logger.info(f"✅ Connected to state service in namespace: {namespace}")
                        break
                    except Exception as e:
                        logger.debug(f"StateService not in {namespace}: {e}")
                        continue
                if self._state_service is None:
                    logger.warning("Failed to connect to state service in any namespace")
            except Exception as e:
                logger.warning(f"Failed to connect to state service: {e}")
                self._state_service = None
        return self._state_service
    
    async def get_unified_state(self, agent_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Get unified state for specified agents or all agents via StateService.
        Returns a UnifiedState object if types are available, else a minimal dict.
        """
        if not self._initialized:
            logger.warning("OrganismCore not initialized, returning empty state")
            return {"agents": {}, "organs": {}, "system": {}, "memory": {}}
        
        state_service = await self._get_state_service()
        if state_service is None:
            logger.error("State service not available, returning empty state")
            return {"agents": {}, "organs": {}, "system": {}, "memory": {}}
        
        try:
            response_ref = state_service.get_unified_state.remote(
                agent_ids=agent_ids,
                include_organs=True,
                include_system=True,
                include_memory=True
            )
            response = await self._ray_await(response_ref)
            
            if not response.get("success"):
                logger.error(f"State service failed: {response.get('error')}")
                return {"agents": {}, "organs": {}, "system": {}, "memory": {}}
            
            return response.get("unified_state", {})
        except Exception as e:
            logger.error(f"Failed to get unified state from StateService: {e}")
            return {"agents": {}, "organs": {}, "system": {}, "memory": {}}
    
    # =====================================================================
    #  ORGAN-LEVEL EVOLUTION OPERATIONS (Ported from OrganismManager)
    # =====================================================================
    
    async def evolve_organ(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        """
        [EXPERIMENTAL] Execute organ-level evolution operations (split, merge, clone, retire).
        
        ⚠️ WARNING: This API is experimental and partially implemented. Only "merge" and
        "retire" operations are fully functional. "split" and "clone" are not implemented
        and will return errors.
        
        This is different from agent scaling - these operations mutate organs themselves.
        
        Proposal format:
            {
                "op": "split" | "merge" | "clone" | "retire",
                "organ_id": str,
                "params": dict  # Operation-specific parameters
            }
        """
        logger.warning("[evolve_organ] Experimental API - use with caution")
        
        if not self._initialized:
            return {"success": False, "error": "OrganismCore not initialized"}
        
        op = proposal.get("op")
        organ_id = proposal.get("organ_id")
        params = proposal.get("params", {})
        
        if not op or not organ_id:
            return {"success": False, "error": "Missing required fields: op, organ_id"}
        
        # Reject unimplemented operations early
        if op in ["split", "clone"]:
            return {
                "success": False,
                "error": f"Operation '{op}' is not fully implemented. Only 'merge' and 'retire' are supported.",
            }
        
        if organ_id not in self.organs:
            return {"success": False, "error": f"Organ {organ_id} not found"}
        
        try:
            if op == "split":
                return await self._op_split(organ_id, params)
            elif op == "merge":
                return await self._op_merge(organ_id, params)
            elif op == "clone":
                return await self._op_clone(organ_id, params)
            elif op == "retire":
                return await self._op_retire(organ_id, params)
            else:
                return {"success": False, "error": f"Unknown operation: {op}"}
        except Exception as e:
            logger.error(f"Organ evolution operation {op} failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def _op_split(self, organ_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Split an organ into k-1 new organs and repartition agents."""
        k = params.get("k", 2)
        if k < 2:
            return {"success": False, "error": "k must be >= 2 for split operation"}
        
        try:
            organ_handle = self.organs[organ_id]
            # organ_status = await asyncio.to_thread(ray.get, organ_handle.get_status.remote())
            # organ_type = organ_status.get("organ_type", "Unknown")  # Reserved for future use
            
            # Get current agents
            agent_handles_ref = organ_handle.get_agent_handles.remote()
            agent_handles = await self._ray_await(agent_handles_ref)
            agent_ids = list(agent_handles.keys())
            
            if len(agent_ids) < k:
                return {"success": False, "error": f"Not enough agents ({len(agent_ids)}) to split into {k} organs"}
            
            # Note: Organ split requires creating new organs, which needs organ config
            # This is a simplified implementation - full version would create organs properly
            logger.warning("Organ split requires organ creation logic - not fully implemented")
            return {"success": False, "error": "Organ split requires organ creation logic - not fully implemented"}
        except Exception as e:
            logger.error(f"Split operation failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def _op_merge(self, organ_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Merge source organs into the target organ."""
        src_organ_ids = params.get("src_organs", [])
        if not src_organ_ids:
            return {"success": False, "error": "No source organs specified"}
        
        try:
            dst_organ_handle = self.organs[organ_id]
            total_agents_moved = 0
            
            for src_organ_id in src_organ_ids:
                if src_organ_id not in self.organs:
                    logger.warning(f"Source organ {src_organ_id} not found, skipping")
                    continue
                
                src_organ_handle = self.organs[src_organ_id]
                agent_handles_ref = src_organ_handle.get_agent_handles.remote()
                agent_handles = await self._ray_await(agent_handles_ref)
                
                # Move agents to destination
                for agent_id, agent_handle in agent_handles.items():
                    register_ref = dst_organ_handle.register_agent.remote(agent_id, agent_handle)
                    await self._ray_await(register_ref)
                    remove_ref = src_organ_handle.remove_agent.remote(agent_id)
                    await self._ray_await(remove_ref)
                    self.agent_to_organ_map[agent_id] = organ_id
                    total_agents_moved += 1
                
                # Remove source organ from registry
                del self.organs[src_organ_id]
            
            return {
                "success": True,
                "result": {
                    "destination_organ": organ_id,
                    "merged_organs": src_organ_ids,
                    "agents_moved": total_agents_moved
                }
            }
        except Exception as e:
            logger.error(f"Merge operation failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def _op_clone(self, organ_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Clone an organ, optionally moving some agents to the new organ."""
        # move_fraction = params.get("move_fraction", 0.0)  # Reserved for future use
        
        try:
            # Verify organ exists
            if organ_id not in self.organs:
                return {"success": False, "error": f"Organ {organ_id} not found"}
            
            # Note: Organ clone requires creating new organs, which needs organ config
            # This would require:
            # 1. Getting organ config/type
            # 2. Creating new organ with same config
            # 3. Optionally moving agents
            logger.warning("Organ clone requires organ creation logic - not fully implemented")
            return {"success": False, "error": "Organ clone requires organ creation logic - not fully implemented"}
        except Exception as e:
            logger.error(f"Clone operation failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def _op_retire(self, organ_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Retire an organ, optionally migrating agents to another organ."""
        migrate_to = params.get("migrate_to")
        
        try:
            organ_handle = self.organs[organ_id]
            agent_handles_ref = organ_handle.get_agent_handles.remote()
            agent_handles = await self._ray_await(agent_handles_ref)
            agents_migrated = 0
            
            # Migrate agents if specified
            if migrate_to and migrate_to in self.organs:
                dst_organ_handle = self.organs[migrate_to]
                for agent_id, agent_handle in agent_handles.items():
                    register_ref = dst_organ_handle.register_agent.remote(agent_id, agent_handle)
                    await self._ray_await(register_ref)
                    self.agent_to_organ_map[agent_id] = migrate_to
                    agents_migrated += 1
            
            # Remove organ from registry
            del self.organs[organ_id]
            
            return {
                "success": True,
                "result": {
                    "retired_organ": organ_id,
                    "agents_migrated": agents_migrated,
                    "migrate_to": migrate_to
                }
            }
        except Exception as e:
            logger.error(f"Retire operation failed: {e}")
            return {"success": False, "error": str(e)}

    # =====================================================================
    #  HEALTH LOOP & RECONCILIATION LOOP
    # =====================================================================

    async def _health_loop(self):
        """
        Periodically queries each organ to confirm liveness,
        detects crashed agents, and schedules reconciliation tasks.
        """
        logger.info("[OrganismCore] Health loop started")

        while not self._shutdown_event.is_set():
            try:
                for organ_id, organ in self.organs.items():
                    try:
                        # Lightweight ping with timeout
                        alive_ref = organ.ping.remote()
                        try:
                            alive = await self._ray_await(alive_ref, timeout=5.0)
                        except Exception as e:
                            logger.warning(
                                f"[HealthLoop] Organ {organ_id} ping timeout/failure: {e}"
                            )
                            self._schedule_reconciliation(organ_id)
                            continue

                        if not alive:
                            logger.warning(
                                f"[HealthLoop] Organ not responding: {organ_id}"
                            )
                            self._schedule_reconciliation(organ_id)
                            continue

                        # Deep health including agent heartbeats with timeout
                        status_ref = organ.get_status.remote()
                        try:
                            status = await self._ray_await(status_ref, timeout=10.0)
                        except Exception as e:
                            logger.warning(
                                f"[HealthLoop] Organ {organ_id} status check timeout/failure: {e}"
                            )
                            continue

                        unhealthy_agents = [
                            a
                            for a, st in status.get("agents", {}).items()
                            if not st.get("alive", False)
                        ]
                        if unhealthy_agents:
                            logger.warning(
                                f"[HealthLoop] Unhealthy agents in {organ_id}: {unhealthy_agents}"
                            )
                            self._schedule_reconciliation(organ_id, unhealthy_agents)

                    except Exception as e:
                        logger.error(
                            f"[HealthLoop] Failure checking organ {organ_id}: {e}"
                        )

                await asyncio.sleep(self._health_interval)

            except asyncio.CancelledError:
                logger.info("[HealthLoop] Cancelled")
                break
            except Exception as e:
                logger.error(f"[HealthLoop] Unexpected error: {e}", exc_info=True)
                await asyncio.sleep(3)

        logger.info("[OrganismCore] Health loop exited")

    def _schedule_reconciliation(
        self, organ_id: str, dead_agents: Optional[List[str]] = None
    ):
        """
        Enqueue a reconciliation request.
        """
        self._reconcile_queue.append((organ_id, dead_agents))

    async def _reconciliation_loop(self):
        """
        Rebuilds crashed organs or agents and updates internal routing maps.
        """
        logger.info("[OrganismCore] Reconciliation loop started")

        while not self._shutdown_event.is_set():
            try:
                if self._reconcile_queue:
                    organ_id, dead_agents = self._reconcile_queue.pop(0)
                    logger.info(
                        f"[Reconcile] Organ={organ_id}, dead_agents={dead_agents}"
                    )

                    organ = self.organs.get(organ_id)
                    if not organ:
                        logger.warning(
                            f"[Reconcile] Organ '{organ_id}' missing — recreating actor"
                        )
                        await self._recreate_organ(organ_id)
                        continue

                    if dead_agents:
                        for agent_id in dead_agents:
                            logger.warning(
                                f"[Reconcile] Respawning agent {agent_id} inside {organ_id}"
                            )
                            try:
                                ref = organ.respawn_agent.remote(agent_id)
                                await self._ray_await(ref)
                            except Exception as e:
                                logger.error(
                                    f"[Reconcile] Failed to respawn agent {agent_id}: {e}",
                                    exc_info=True,
                                )

                await asyncio.sleep(self._recon_interval)

            except asyncio.CancelledError:
                logger.info("[ReconcileLoop] Cancelled")
                break
            except Exception as e:
                logger.error(f"[ReconcileLoop] Unexpected error: {e}", exc_info=True)
                await asyncio.sleep(3)

        logger.info("[OrganismCore] Reconciliation loop exited")

    # =====================================================================
    #  ORGAN & AGENT RESPAWN HELPERS
    # =====================================================================

    async def _recreate_organ(self, organ_id: str):
        """
        Fully rebuild an organ and its agents.
        """
        logger.info(f"[OrganismCore] Recreating organ={organ_id}")

        # Look up config
        cfg = None
        for oc in self.organ_configs:
            if oc["id"] == organ_id:
                cfg = oc
                break

        if not cfg:
            logger.error(
                f"[OrganismCore] Cannot recreate organ `{organ_id}` — config not found"
            )
            return

        # Remove stale entry
        if organ_id in self.organs:
            try:
                del self.organs[organ_id]
            except Exception:
                pass

        # Create new organ actor (use same name as initial creation for consistency)
        try:
            new_organ = Organ.options(
                name=organ_id,  # Same as initial creation, not "organ-{organ_id}"
                namespace=AGENT_NAMESPACE
            ).remote(
                organ_id=organ_id,
                # Stateless dependencies
                role_registry=self.role_registry,
                skill_store=self.skill_store,
                tool_manager=self.tool_manager,
                cognitive_client=self.cognitive_client,
                # Stateful dependencies
                mw_manager=self.mw_manager,
                ltm_manager=self.ltm_handle,
                checkpoint_cfg=self.checkpoint_cfg,
            )
        except Exception as e:
            logger.error(f"[OrganismCore] Failed to recreate organ: {e}")
            return

        self.organs[organ_id] = new_organ
        logger.info(f"[OrganismCore] Organ `{organ_id}` recreated")

        # Respawn agents
        for agent_def in cfg.get("agents", []):
            try:
                spec = Specialization[agent_def["specialization"].upper()]
            except KeyError:
                logger.error(f"Invalid specialization '{agent_def['specialization']}' in config for organ {organ_id}")
                continue
            count = agent_def.get("count", 1)
            for _ in range(count):
                agent_id = str(uuid.uuid4())
                try:
                    # Get agent class from config if available, default to BaseAgent
                    agent_class_name = agent_def.get("class", "BaseAgent")
                    ref = new_organ.create_agent.remote(
                        agent_id=agent_id,
                        specialization=spec,
                        organ_id=organ_id,
                        agent_class_name=agent_class_name,
                        name=agent_id,
                        num_cpus=0.1,
                        lifetime="detached"
                    )
                    await self._ray_await(ref)
                    self.agent_to_organ_map[agent_id] = organ_id
                except Exception as e:
                    logger.error(
                        f"[OrganismCore] Failed to respawn agent {agent_id}: {e}"
                    )

        logger.info(f"[OrganismCore] Organ `{organ_id}` fully rebuilt")

    # =====================================================================
    #  SYSTEM INITIALIZATION HELPERS
    # =====================================================================

    async def _ensure_janitor_actor(self):
        """
        Ensure the detached Janitor actor exists in the expected namespace.
        
        The Janitor is a system-wide maintenance service responsible for cleaning
        up dead actors and maintaining cluster health. This method ensures it's
        running before the organism starts processing tasks.
        
        This is idempotent - if the janitor already exists, it will be reused.
        """
        try:
            if not ray.is_initialized():
                logger.debug("[OrganismCore] Ray not initialized, skipping janitor check")
                return
            
            namespace = AGENT_NAMESPACE
            
            try:
                # Fast path: already exists
                jan = await asyncio.to_thread(
                    ray.get_actor, "seedcore_janitor", namespace=namespace
                )
                logger.debug(f"[OrganismCore] Janitor actor already running in {namespace}")
                return
            except Exception:
                logger.info(f"[OrganismCore] Launching janitor in namespace {namespace}")

            # Create or reuse
            from seedcore.maintenance.janitor import Janitor
            try:
                Janitor.options(
                    name="seedcore_janitor",
                    namespace=namespace,
                    lifetime="detached",
                    num_cpus=0,
                ).remote(namespace)
                
                # Verify it is reachable
                jan = await asyncio.to_thread(
                    ray.get_actor, "seedcore_janitor", namespace=namespace
                )
                try:
                    pong_ref = jan.ping.remote()
                    pong = await self._ray_await(pong_ref)
                    logger.info(f"✅ Janitor actor launched in {namespace} (ping={pong})")
                except Exception:
                    logger.info(f"✅ Janitor actor launched in {namespace} (ping skipped)")
            except Exception as e:
                logger.warning(f"⚠️ Failed to launch janitor actor: {e}")
        except Exception as e:
            logger.debug(f"[OrganismCore] Ensure janitor skipped: {e}")

    # =====================================================================
    #  SHUTDOWN LOGIC
    # =====================================================================

    async def shutdown(self):
        """
        Graceful shutdown:
          - Stop background tasks
          - Instruct organs to stop
          - Close LTM actor
        """
        if self._shutdown_event.is_set():
            return

        logger.info("[OrganismCore] Shutting down...")
        self._shutdown_event.set()

        # Wait for health & reconcile tasks to stop
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except Exception:
                pass

        if self._recon_task:
            self._recon_task.cancel()
            try:
                await self._recon_task
            except Exception:
                pass

        # Stop organs
        for organ_id, organ in self.organs.items():
            try:
                logger.info(f"[OrganismCore] Stopping organ {organ_id}")
                ref = organ.shutdown.remote()
                await self._ray_await(ref)
            except Exception as e:
                logger.error(
                    f"[OrganismCore] Error shutting down organ {organ_id}: {e}"
                )

        # Close LTM
        if self.ltm_handle:
            try:
                logger.info("[OrganismCore] Closing LTM actor")
                await self._ray_await(self.ltm_handle.close.remote())
            except Exception as e:
                logger.error(f"[OrganismCore] Failed to close LTM: {e}")

        logger.info("[OrganismCore] Shutdown complete")


# =====================================================================
#  GLOBAL SINGLETON & HELPERS
# =====================================================================

_GLOBAL_ORGANISM_INSTANCE: Optional[OrganismCore] = None


def get_organism() -> OrganismCore:
    if _GLOBAL_ORGANISM_INSTANCE is None:
        raise RuntimeError("OrganismCore has not been created yet")
    return _GLOBAL_ORGANISM_INSTANCE


def set_organism(org: OrganismCore):
    global _GLOBAL_ORGANISM_INSTANCE
    _GLOBAL_ORGANISM_INSTANCE = org


# =====================================================================
#  END OF FILE
# =====================================================================
