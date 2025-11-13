# =====================================================================
#  ORGANISM CORE — COMPLETE REWRITE (2025)
#  Version: SeedCore Cognitive Architecture v2
#  Author: ChatGPT (with Ning)
#
#  Overview:
#    This module implements the LEVEL-1 ROUTER for the entire distributed
#    cognitive organism. It is the global control plane responsible for:
#
#      • specialization → organ selection
#      • organ → agent selection (via organ metadata tables)
#      • direct agent-level execution (no organ-level RPCs)
#      • global load distribution policies
#      • connection to the distributed LongTermMemoryManager Ray actor
#
#    In this v2 architecture:
#      • Organ = agent registry + health tracker
#      • Agent = true execution endpoint (task executor)
#      • OrganismCore = the global router and orchestrator
#
#    This replaces the old Tier0 design and the older organ.execute_task
#    execution model. All execution is now single-hop:
#
#        OrganismCore → agent_actor.execute_task(...)
#
#    This improves latency, fault isolation, and makes routing explicit.
#
# =====================================================================

from __future__ import annotations

import asyncio
import os
import uuid
import yaml  # pyright: ignore[reportMissingModuleSource]
import random
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
from seedcore.models import TaskPayload

from seedcore.logging_setup import setup_logging, ensure_serve_logger
from seedcore.organs.organ import Organ  # ← NEW ORGAN CLASS

# Long-term memory backend (Ray actor)
from seedcore.memory.long_term_memory import LongTermMemoryManager

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
#  OrganismCore — LEVEL-1 ROUTER (Direct Agent Execution, v2 Architecture)
#  Routes: specialization → organ → agent, then calls agent.execute_task()
#  Organ = agent registry; Agent = executor; Core = global orchestrator.
# =====================================================================


class OrganismCore:
    """
    Manages:
      - global RoleRegistry
      - global ToolManager
      - global CognitiveServiceClient
      - global SkillStore (via LTM)
      - Organ creation
      - Agent creation
      - Specialization → Organ routing
      - Task dispatch
      - Health checks + reconciliation
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

        # Specialization → organ routing table
        self.specialization_to_organ: Dict[Specialization, str] = {}

        # Agent → organ (informational only)
        self.agent_to_organ_map: Dict[str, str] = {}

        # Load config (YAML)
        self._load_config(config_path)

        # Global infrastructure
        self.role_registry: RoleRegistry = role_registry or DEFAULT_ROLE_REGISTRY
        self.skill_store: Optional[LTMSkillStoreAdapter] = None
        self.tool_manager: Optional[ToolManager] = None
        self.cognitive_client: Optional[CognitiveServiceClient] = None
        self.ltm_handle: Optional[Any] = None

        # Background tasks
        self._health_check_task: Optional[asyncio.Task] = None
        self._recon_task: Optional[asyncio.Task] = None
        self._health_interval = int(os.getenv("HEALTHCHECK_INTERVAL_S", "20"))
        self._recon_interval = int(os.getenv("RECONCILE_INTERVAL_S", "20"))
        self._shutdown_event = asyncio.Event()
        self._reconcile_queue: List[tuple] = []

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
            await asyncio.to_thread(ray.get, self.ltm_handle.initialize.remote())

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
        # 4. ToolManager
        # --------------------------------------------------------------
        self.tool_manager = ToolManager()

        # --------------------------------------------------------------
        # 5. Cognitive service client
        # --------------------------------------------------------------
        self.cognitive_client = CognitiveServiceClient()

        # --------------------------------------------------------------
        # 6. Spawn Organs
        # --------------------------------------------------------------
        await self._create_organs_from_config()

        # --------------------------------------------------------------
        # 7. Spawn Agents
        # --------------------------------------------------------------
        await self._create_agents_from_config()

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
                organ = Organ.options(
                    name=organ_id,
                    namespace=AGENT_NAMESPACE,
                    lifetime="detached",
                    max_restarts=-1,
                    max_task_retries=-1,
                    num_cpus=0.1,
                ).remote(
                    organ_id=organ_id,
                    role_registry=self.role_registry,
                    skill_store=self.skill_store,
                    tool_manager=self.tool_manager,
                    cognitive_client=self.cognitive_client,
                )

                # Sanity check
                ok_ref = organ.health_check.remote()
                ok = await asyncio.to_thread(ray.get, ok_ref)
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
                    agent_id = f"{organ_id}_{spec.name.lower()}_{i}"

                    ref = organ.create_agent.remote(
                        agent_id=agent_id,
                        specialization=spec,
                        organ_id=organ_id,
                        name=agent_id,
                        num_cpus=0.1,
                        lifetime="detached",
                    )

                    await asyncio.to_thread(ray.get, ref)
                    self.agent_to_organ_map[agent_id] = organ_id
                    total += 1

        logger.info(f"🤖 Spawned {total} agents across {len(self.organs)} organs.")
        logger.info(
            f"🗺 Built specialization routing map: { {k.name: v for k, v in self.specialization_to_organ.items()} }"
        )

    # =====================================================================
    #  TASK ROUTING (LEVEL-1 ROUTER, DIRECT-TO-AGENT EXECUTION)
    # =====================================================================

    async def route_task(
        self,
        specialization: Specialization,
        payload: TaskPayload,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        prefer_agent_id: Optional[str] = None,
        ask_any_agent: bool = False,
        ask_any_organ: bool = False,
    ) -> Dict[str, Any]:
        """
        LEVEL-1 ROUTER (DIRECT AGENT EXECUTION)
        --------------------------------------
        The OrganismCore is the central router for the entire distributed
        organism. It performs *selection only* — actual execution is done
        directly on the chosen agent actor.

        Routing pipeline:

            1) Select the target organ
                - by specialization → organ
                - OR choose any organ (ask_any_organ)

            2) Select the agent inside the organ
                - explicitly via prefer_agent_id
                - OR via specialization-based agent routing
                - OR choose any agent (ask_any_agent)

            3) Execute task *directly on the agent actor*
                - no organ-level task execution
                - single-hop RPC → lower latency, clearer architecture

        Returns:
            dict with:
                {
                    "organ_id": str,
                    "agent_id": str,
                    "result": Any or {"error": ...}
                }

        This is the recommended design for Ray-based agent systems because it
        decouples:
            - organ = agent registry, health supervisor
            - agent = execution endpoint
            - organism = global router
        """

        logger.debug(
            f"[OrganismCore.route_task] spec={specialization} "
            f"prefer_agent={prefer_agent_id} any_agent={ask_any_agent} any_organ={ask_any_organ}"
        )

        # ------------------------------------------------------------
        # 1. Select target organ (agent registry lookup)
        # ------------------------------------------------------------
        try:
            if ask_any_organ:
                organ_id, organ = random.choice(list(self.organs.items()))
            else:
                organ_id = self.specialization_to_organ.get(specialization)
                if not organ_id:
                    return {
                        "error": f"No organ registered for specialization {specialization.name}"
                    }
                organ = self.organs.get(organ_id)
                if not organ:
                    return {"error": f"Organ '{organ_id}' unavailable"}
        except Exception as e:
            logger.error(f"[route_task] Organ selection failed: {e}")
            return {"error": f"Organ selection failure: {e}"}

        # ------------------------------------------------------------
        # 2. Select agent and get its actor handle from organ
        # ------------------------------------------------------------
        try:
            if prefer_agent_id:
                agent_id = prefer_agent_id
                agent_handle_ref = organ.get_agent_handle.remote(agent_id)
                agent_handle = await asyncio.to_thread(ray.get, agent_handle_ref)
            elif ask_any_agent:
                pick_result_ref = organ.pick_random_agent.remote()
                agent_id, agent_handle = await asyncio.to_thread(
                    ray.get, pick_result_ref
                )
            else:
                pick_result_ref = organ.pick_agent_by_specialization.remote(
                    specialization.value
                )
                agent_id, agent_handle = await asyncio.to_thread(
                    ray.get, pick_result_ref
                )

            if not agent_id or not agent_handle:
                return {
                    "error": f"No agent available for specialization {specialization.name}"
                }

        except Exception as e:
            logger.error(f"[route_task] Agent selection failed: {e}", exc_info=True)
            return {"error": f"Agent selection failure: {e}"}

        # ------------------------------------------------------------
        # 3. Execute task directly on agent actor (single-hop RPC)
        #    No organ-level delegation - direct agent execution
        # ------------------------------------------------------------
        try:
            logger.debug(
                f"[route_task] Dispatching → organ={organ_id}, agent={agent_id}"
            )

            # Convert TaskPayload to dict for agent execution
            task_dict = (
                payload.model_dump() if isinstance(payload, TaskPayload) else payload
            )

            ref = agent_handle.execute_task.remote(task_dict, metadata or {})
            result = await asyncio.to_thread(ray.get, ref)

            return {
                "organ_id": organ_id,
                "agent_id": agent_id,
                "result": result,
            }

        except Exception as e:
            logger.error(f"[route_task] Execution error: {e}", exc_info=True)
            return {
                "organ_id": organ_id,
                "agent_id": agent_id,
                "error": f"Execution failure: {e}",
            }

    # =====================================================================
    #  ORGAN-LOCAL MANAGEMENT API
    # =====================================================================

    async def execute_task_on_organ(
        self,
        organ_id: str,
        payload: TaskPayload,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Execute task on a specific organ using direct agent routing.

        The organ acts as an agent registry - we query it for an agent handle,
        then execute the task directly on the selected agent actor.

        Returns:
            dict with organ_id, agent_id, and result/error.
        """
        organ = self.organs.get(organ_id)
        if not organ:
            return {"error": f"Organ '{organ_id}' not found"}

        try:
            # Pick a random agent from the organ
            pick_result_ref = organ.pick_random_agent.remote()
            agent_id, agent_handle = await asyncio.to_thread(ray.get, pick_result_ref)

            if not agent_id or not agent_handle:
                return {"error": f"No agents available in organ '{organ_id}'"}

            # Convert TaskPayload to dict for agent execution
            task_dict = (
                payload.model_dump() if isinstance(payload, TaskPayload) else payload
            )

            ref = agent_handle.execute_task.remote(task_dict, metadata or {})
            result = await asyncio.to_thread(ray.get, ref)

            return {
                "organ_id": organ_id,
                "agent_id": agent_id,
                "result": result,
            }
        except Exception as e:
            logger.error(f"[execute_task_on_organ] Error: {e}", exc_info=True)
            return {"error": str(e)}

    async def execute_task_on_random_organ(
        self, payload: TaskPayload, metadata: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        """
        Execute task on a random organ using direct agent routing.

        Selects a random organ, picks a random agent from it, then executes
        the task directly on the agent actor.

        Returns:
            dict with organ_id, agent_id, and result/error.
        """
        if not self.organs:
            return {"error": "No organs available"}

        organ_id, organ = random.choice(list(self.organs.items()))
        try:
            # Pick a random agent from the organ
            pick_result_ref = organ.pick_random_agent.remote()
            agent_id, agent_handle = await asyncio.to_thread(ray.get, pick_result_ref)

            if not agent_id or not agent_handle:
                return {"error": f"No agents available in organ '{organ_id}'"}

            # Convert TaskPayload to dict for agent execution
            task_dict = (
                payload.model_dump() if isinstance(payload, TaskPayload) else payload
            )

            ref = agent_handle.execute_task.remote(task_dict, metadata or {})
            result = await asyncio.to_thread(ray.get, ref)

            return {
                "organ_id": organ_id,
                "agent_id": agent_id,
                "result": result,
            }
        except Exception as e:
            logger.error(f"[execute_task_on_random_organ] Error: {e}", exc_info=True)
            return {"error": str(e)}

    # =====================================================================
    #  INTROSPECTION API — OBSERVE CLOSELY
    # =====================================================================

    def list_organs(self) -> List[str]:
        return list(self.organs.keys())

    def list_agents(self, organ_id: Optional[str] = None) -> List[str]:
        if organ_id:
            organ = self.organs.get(organ_id)
            if not organ:
                return []
            ref = organ.list_agents.remote()
            return ray.get(ref)
        else:
            all_agents = []
            for organ in self.organs.values():
                ref = organ.list_agents.remote()
                agents = ray.get(ref)
                all_agents.extend(agents)
            return all_agents

    def map_specializations(self) -> Dict[str, str]:
        """
        { "RESEARCH": "research_organ", ... }
        """
        return {
            spec.name: organ for spec, organ in self.specialization_to_organ.items()
        }

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
            return await asyncio.to_thread(ray.get, ref)
        except Exception as e:
            return {"error": str(e)}

    async def get_organ_status(self, organ_id: str) -> Dict[str, Any]:
        organ = self.organs.get(organ_id)
        if not organ:
            return {"error": f"Organ '{organ_id}' does not exist"}
        try:
            ref = organ.get_status.remote()
            return await asyncio.to_thread(ray.get, ref)
        except Exception as e:
            return {"error": str(e)}

    async def get_system_status(self) -> Dict[str, Any]:
        """
        Returns a complete map of organ and agent health.
        """
        out = {"organs": {}, "specialization_map": self.map_specializations()}
        for oid, organ in self.organs.items():
            try:
                ref = organ.get_status.remote()
                out["organs"][oid] = await asyncio.to_thread(ray.get, ref)
            except Exception as e:
                out["organs"][oid] = {"error": str(e)}
        return out

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
                        # Lightweight ping
                        alive_ref = organ.ping.remote()
                        alive = await asyncio.to_thread(ray.get, alive_ref)

                        if not alive:
                            logger.warning(
                                f"[HealthLoop] Organ not responding: {organ_id}"
                            )
                            self._schedule_reconciliation(organ_id)
                            continue

                        # Deep health including agent heartbeats
                        status_ref = organ.get_status.remote()
                        status = await asyncio.to_thread(ray.get, status_ref)

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
                                await asyncio.to_thread(ray.get, ref)
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
        for oc in self.config.organs:
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

        # Create new organ actor
        organ_name = f"organ-{organ_id}".lower()
        try:
            new_organ = Organ.options(
                name=organ_name, namespace=self.ray_namespace
            ).remote(
                organ_id=organ_id,
                role_registry=self.role_registry,
                skill_store=self.skill_store,
                tool_manager=self.tool_manager,
                cognitive_client=self.cognitive_client,
            )
        except Exception as e:
            logger.error(f"[OrganismCore] Failed to recreate organ: {e}")
            return

        self.organs[organ_id] = new_organ
        logger.info(f"[OrganismCore] Organ `{organ_id}` recreated")

        # Respawn agents
        for agent_def in cfg.get("agents", []):
            spec = Specialization.from_label(agent_def["specialization"])
            count = agent_def.get("count", 1)
            for _ in range(count):
                agent_id = str(uuid.uuid4())
                try:
                    ref = new_organ.create_agent.remote(agent_id, spec)
                    await asyncio.to_thread(ray.get, ref)
                    self.agent_to_organ_map[agent_id] = organ_id
                except Exception as e:
                    logger.error(
                        f"[OrganismCore] Failed to respawn agent {agent_id}: {e}"
                    )

        logger.info(f"[OrganismCore] Organ `{organ_id}` fully rebuilt")

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
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except Exception:
                pass

        if self._reconcile_task:
            self._reconcile_task.cancel()
            try:
                await self._reconcile_task
            except Exception:
                pass

        # Stop organs
        for organ_id, organ in self.organs.items():
            try:
                logger.info(f"[OrganismCore] Stopping organ {organ_id}")
                ref = organ.shutdown.remote()
                await asyncio.to_thread(ray.get, ref)
            except Exception as e:
                logger.error(
                    f"[OrganismCore] Error shutting down organ {organ_id}: {e}"
                )

        # Close LTM
        try:
            logger.info("[OrganismCore] Closing LTM actor")
            await self.ltm.close.remote()
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
