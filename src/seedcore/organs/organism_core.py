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
#      • Connection to HolonFabric for long-term memory (replaces LongTermMemoryManager)
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
from copy import deepcopy
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, Set

import ray  # type: ignore

# ---------------------------------------------------------------------
#  SeedCore Imports
# ---------------------------------------------------------------------
from seedcore.agents.roles import RoleProfile
from seedcore.agents.roles.specialization import (
    Specialization,
    SpecializationProtocol,
    SpecializationManager,
    get_specialization,
    RoleRegistry,
)
from seedcore.agents.roles.skill_vector import SkillStoreProtocol
from seedcore.agents.roles.generic_defaults import DEFAULT_ROLE_REGISTRY
from seedcore.organs.tunnel_manager import TunnelManager
from seedcore.serve.ml_client import MLServiceClient
from seedcore.tools.manager import ToolManager
from seedcore.serve.cognitive_client import CognitiveServiceClient
from seedcore.serve.energy_client import EnergyServiceClient
from seedcore.models import TaskPayload
from seedcore.models.holon import Holon, HolonType, HolonScope
from seedcore.models.result_schema import make_envelope, normalize_envelope
from seedcore.models.cognitive import DecisionKind

from seedcore.organs.organ import Organ  # ← NEW ORGAN CLASS
from seedcore.organs.tunnel_policy import TunnelActivationPolicy
from seedcore.organs.registry import OrganRegistry
from seedcore.graph.agent_repository import AgentGraphRepository

# Long-term memory backend (HolonFabric replaces LongTermMemoryManager)
from seedcore.memory.holon_fabric import HolonFabric
from seedcore.memory.backends.pgvector_backend import PgVectorStore
from seedcore.memory.backends.neo4j_graph import Neo4jGraph

# --- Import stateful dependencies ---
from seedcore.memory.mw_manager import MwManager
from seedcore.tools.manager_actor import ToolManagerShard
from seedcore.database import (
    REDIS_URL,
    PG_DSN,
    NEO4J_URI,
    NEO4J_BOLT_URL,
    NEO4J_USER,
    NEO4J_PASSWORD,
)

from seedcore.logging_setup import setup_logging, ensure_serve_logger

# ---------------------------------------------------------------------
#  Settings & Environment
# ---------------------------------------------------------------------

CONFIG_PATH = os.getenv("CONFIG_PATH", "/app/config/organs.yaml")
RAY_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))

setup_logging(app_name="seedcore.organs.OrganismCore")
logger = ensure_serve_logger("seedcore.organs.OrganismCore", level="DEBUG")


# =====================================================================
#  TUYA INTEGRATION HELPERS
# =====================================================================


async def register_tuya_tools(tool_manager: Any) -> bool:
    """
    Register Tuya tools if Tuya is enabled.

    This function:
    - Checks TuyaConfig.enabled before registering
    - Registers tuya.get_status and tuya.send_command tools
    - Adds "device.vendor.tuya" capability flag
    - Handles both single ToolManager and ToolManagerShard instances

    Note: Tuya tools are designed for device control actions (domain="device").
    They should only be used by OrchestrationAgent for device orchestration tasks.

    Args:
        tool_manager: ToolManager instance or ToolManagerShard handle

    Returns:
        True if tools were registered, False if Tuya is disabled
    """
    try:
        from seedcore.config.tuya_config import TuyaConfig

        tuya_config = TuyaConfig()
        if not tuya_config.enabled:
            logger.debug("Tuya integration disabled (TUYA_ENABLED=false)")
            return False

        # Register tools
        # Handle both ToolManager instance and ToolManagerShard handle
        if hasattr(tool_manager, "register_internal"):
            # Direct ToolManager instance
            from seedcore.tools.tuya.tuya_tools import (
                TuyaGetStatusTool,
                TuyaSendCommandTool,
            )

            await tool_manager.register_internal(TuyaGetStatusTool())
            await tool_manager.register_internal(TuyaSendCommandTool())

            # Register capability flag for feature detection
            if hasattr(tool_manager, "add_capability"):
                await tool_manager.add_capability("device.vendor.tuya")

            logger.info(
                "✅ Tuya tools registered: tuya.get_status, tuya.send_command (capability: device.vendor.tuya)"
            )
            return True
        elif hasattr(tool_manager, "register_tuya_tools"):
            # ToolManagerShard handle (Ray actor) - use internal method
            result = await tool_manager.register_tuya_tools.remote()
            if result:
                logger.info(
                    "✅ Tuya tools registered in shard: tuya.get_status, tuya.send_command (capability: device.vendor.tuya)"
                )
            return bool(result)
        else:
            logger.warning("⚠️ Unknown tool_manager type, cannot register Tuya tools")
            return False

    except Exception as e:
        logger.warning(f"⚠️ Failed to register Tuya tools: {e}", exc_info=True)
        return False


async def register_reachy_tools(tool_manager: Any) -> bool:
    """
    Register Reachy tools.

    This function:
    - Registers reachy.motion and reachy.get_state tools
    - Handles both single ToolManager and ToolManagerShard instances
    - Connects to HAL FastAPI service (default: http://localhost:8001)

    Note: Reachy tools are designed for robot actuation (domain="physical").
    They should only be used by agents with appropriate RBAC permissions.
    The HAL service handles both physical hardware and simulation based on
    HAL_DRIVER_MODE configuration.

    Args:
        tool_manager: ToolManager instance or ToolManagerShard handle

    Returns:
        True if tools were registered, False otherwise
    """
    try:
        from seedcore.tools.reachy_tools import register_reachy_tools as _register_reachy_hal_tools
        
        # Get HAL base URL from environment or use default
        hal_base_url = os.getenv("HAL_BASE_URL", "http://localhost:8001")
        
        result = await _register_reachy_hal_tools(tool_manager, hal_base_url=hal_base_url)
        return result

    except Exception as e:
        logger.warning(f"⚠️ Failed to register Reachy tools: {e}", exc_info=True)
        return False


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "y", "on")


# =====================================================================
#  SkillStore Adapter — Bridge HolonFabric to SkillStoreProtocol
# =====================================================================


class HolonFabricSkillStoreAdapter(SkillStoreProtocol):
    def __init__(self, holon_fabric: HolonFabric):
        self.holon_fabric = holon_fabric

    async def load(self, agent_id: str) -> Optional[Dict[str, float]]:
        # Get Holon by id, read deltas from holon.content (or similar)
        holon = await self.holon_fabric.get_holon(agent_id)  # or whatever API you have
        if not holon:
            return None
        payload = holon.content or {}
        return {k: float(v) for k, v in payload.get("deltas", payload).items()}

    async def save(
        self,
        agent_id: str,
        deltas: Dict[str, float],
        metadata: Dict[str, Any],
    ) -> bool:
        # Embed these deltas into HolonFabric in some chosen form.
        holon = Holon(
            id=agent_id,
            type=HolonType.FACT,
            scope=HolonScope.GLOBAL,
            content={"deltas": deltas, **(metadata or {})},
            summary=f"Skill deltas for agent {agent_id}",
            embedding=None,  # or derived embedding if you wish
            links=[],
        )
        await self.holon_fabric.insert_holon(holon)
        return True


# =====================================================================
#  OrganismCore — Tier-1 Registry + Execution Layer (v2 Architecture)
#  OrganismCore = registry + execution; RoutingDirectory = Tier-0 router
#  Organ = agent registry; Agent = executor; Core = registry + execution
# =====================================================================


class OrganismCore:
    """
    Tier-1 OrganismCore: Registry and Execution Layer
    """

    def __init__(
        self,
        config_path: Path | str = CONFIG_PATH,
        config: Dict[str, Any] | None = None,
        **kwargs,
    ):
        # Initialize logger (CRITICAL: must be set before any logging calls)
        self.logger = logger

        self._initialized = False
        self._lock = asyncio.Lock()
        self._config_lock = asyncio.Lock()  # Lock for config updates

        self.organ_configs: List[Dict[str, Any]] = []
        self.organs: Dict[str, ray.actor.ActorHandle] = {}

        # 1. Normalize and Resolve Path immediately
        # Convert to Path object and resolve to absolute path to fix CWD issues in Ray
        self.config_path = Path(config_path).resolve()

        # 2. Early Validation
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found at: {self.config_path}"
            )

        # Specialization → organ mapping (for registry API only, NOT for routing decisions)
        # This is maintained for get_specialization_map() registry API
        # Supports both static Specialization enum and DynamicSpecialization
        self.specialization_to_organ: Dict[SpecializationProtocol, str] = {}

        # String-based specialization → organ mapping (for router lookup)
        # Maps specialization name (string) to organ_id
        self.organ_specs: Dict[str, str] = {}

        # Agent → organ (informational only, for registry)
        self.agent_to_organ_map: Dict[str, str] = {}

        # Load Config (YAML)
        # We assume _load_config populates self.organ_configs AND returns/sets root settings
        # Let's say _load_config returns a dict of global settings
        global_settings = self._load_config(self.config_path) or {}
        self.global_settings = global_settings  # Store for runtime updates
        self.router_cfgs = global_settings.get("router_config", {})
        self.topology_cfg: Dict[str, Any] = {}  # Topology configuration

        # Set self.config: use passed config if provided, otherwise use global_settings
        # This ensures self.config always exists for backward compatibility
        self.config = config if config is not None else global_settings

        # 4. Tunnel Subsystem
        # State: Who is assigned to whom?
        self.tunnel_manager = TunnelManager(redis_url=REDIS_URL)

        # Policy: Should we assign?
        # Extract thresholds from the global config, not the list of organs
        self.tunnel_policy = TunnelActivationPolicy(
            continuation_threshold=global_settings.get("tunnel_threshold", 0.7),
            interactive_intents=global_settings.get("tunnel_intents", None),
        )

        # Global infrastructure
        self.role_registry: RoleRegistry = DEFAULT_ROLE_REGISTRY
        self.skill_store: Optional[HolonFabricSkillStoreAdapter] = None
        self.tool_manager: Optional[ToolManager] = None
        self.num_tool_shards: int = 0
        self.agent_threshold_for_shards: int = 1000
        self.tool_shards: List[Any] = []  # or List["ToolManagerShard"]
        self.tool_handler: Any = None  # Can be ToolManager or List[ToolManagerShard]
        self.cognitive_client: Optional[CognitiveServiceClient] = None
        self.ml_client: Optional[MLServiceClient] = None
        self.energy_client: Optional[EnergyServiceClient] = None
        self.holon_fabric: Optional[HolonFabric] = None

        # --- Organ Registry (Tier-1) ---
        self.organ_registry: Optional[OrganRegistry] = None

        # --- Stateful dependencies for PersistentAgent ---
        self.mw_manager: Optional[MwManager] = None
        self.checkpoint_cfg: Dict[str, Any] = {
            "enabled": True,
            "path": os.getenv("CHECKPOINT_PATH", "/app/checkpoints"),
        }

        # Evolution guardrails
        self._evolve_max_cost = float(os.getenv("EVOLVE_MAX_COST", "1e6"))
        self._evolve_min_roi = float(os.getenv("EVOLVE_MIN_ROI", "0.2"))

        # Background tasks
        self._health_check_task: Optional[asyncio.Task] = None
        self._recon_task: Optional[asyncio.Task] = None
        self._config_watcher_task: Optional[asyncio.Task] = None
        self._health_interval = int(os.getenv("HEALTHCHECK_INTERVAL_S", "20"))
        self._recon_interval = int(os.getenv("RECONCILE_INTERVAL_S", "20"))
        self._shutdown_event = asyncio.Event()
        self._reconcile_queue: List[tuple] = []
        # Cache for fallback generalist agents (per organ)
        self._generalist_fallback_agents: Dict[str, str] = {}
        # Track agent creation times to avoid false positives during initialization
        self._agent_creation_times: Dict[
            str, float
        ] = {}  # agent_id -> creation timestamp
        self._agent_health_grace_period = float(
            os.getenv("AGENT_HEALTH_GRACE_PERIOD_S", "30.0")
        )  # Grace period before health checks

        # State service (lazy connection)
        self._state_service: Optional[Any] = None

    # ------------------------------------------------------------------
    #  CONFIG LOADING
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    #  CONFIG LOADING
    # ------------------------------------------------------------------
    def _load_config(self, path: Path | str) -> Dict[str, Any]:
        """
        Load Organism configuration from a YAML file.

        Populates:
          - self.organ_configs (List of organs)
          - self.routing_rules (Routing logic)

        Returns:
          - global_settings (Dict): Shared settings (tunnel thresholds, intents, etc.)
            used to initialize subsystems like TunnelPolicy.
        """
        path = Path(path)

        if not path.exists():
            logger.error(f"[OrganismCore] ❌ Config file not found at {path}")
            self.organ_configs = []
            return {}

        try:
            with open(path, "r") as f:
                cfg = yaml.safe_load(f) or {}

            # --- 1. Navigate to V2 Root ---
            # Structure: seedcore -> organism
            organism_cfg = cfg.get("seedcore", {}).get("organism", {})

            if not organism_cfg or "organs" not in organism_cfg:
                raise KeyError(
                    "YAML structure invalid. Expected path: seedcore -> organism -> organs"
                )

            # --- 2. Extract State Data (Side Effects) ---
            self.organ_configs = organism_cfg["organs"]
            self.routing_rules = organism_cfg.get("routing_rules", {})

            logger.info(
                f"✅ [OrganismCore] Loaded {len(self.organ_configs)} organs from {path.name}"
            )

            if not self.routing_rules:
                logger.warning(
                    "⚠️ [OrganismCore] Routing rules empty. Using specialization defaults."
                )

            # --- 3. Extract & Return Global Settings ---
            # We look for a explicit 'settings' block, or fallback to the organism root
            # This captures 'tunnel_threshold', 'tunnel_intents', etc.
            global_settings = organism_cfg.get("settings", {})

            # If settings were flat inside 'organism' instead of a sub-block,
            # we can merge them safely:
            if not global_settings:
                global_settings = {
                    k: v
                    for k, v in organism_cfg.items()
                    if k not in ["organs", "routing_rules"]
                }

            return global_settings

        except Exception as e:
            logger.critical(f"❌ [OrganismCore] CRITICAL FAILURE loading config: {e}")
            self.organ_configs = []
            self.routing_rules = {}
            return {}

    # ------------------------------------------------------------------
    #  INIT SEQUENCE
    # ------------------------------------------------------------------
    async def initialize_organism(self):
        """
        Bootstraps the Cognitive Organism in 4 Parallel Phases.

        Phase 1: Storage & Infrastructure (DBs, Janitor, Base Clients)
        Phase 2: Adapters & Logic (SkillStore, ToolManager, Registries)
        Phase 3: Actor Spawning (Organs, Agents)
        Phase 4: Background Loops (Health, Reconciliation)

        Architecture Philosophy:
        - **Static Initialization (YAML)**: `organs.yaml` and `specializations.yaml` provide
          the initial baseline configuration. This is ONLY used for first-time static setup.
        - **Dynamic Evolution (PKG)**: After initialization, `CapabilityMonitor` in `CoordinatorService`
          continuously watches `pkg_subtask_types` for changes and notifies `OrganismService` via RPC.
          The system becomes dynamically driven by database capabilities, not just YAML configs.
        - **Runtime Monitoring**: `CapabilityMonitor` automatically registers dynamic specializations
          and notifies `OrganismService` to update role profiles and manage agents accordingly.
        """
        if self._initialized:
            logger.warning("[OrganismCore] Already initialized.")
            return

        if not ray.is_initialized():
            # Auto-fix or strict fail based on policy
            raise RuntimeError("Ray must be initialized before OrganismCore startup.")

        logger.info("🚀 Starting OrganismCore initialization (Parallel Mode)...")
        start_time = asyncio.get_running_loop().time()

        # ==============================================================
        # PHASE 1: INFRASTRUCTURE & STORAGE (Parallel)
        # ==============================================================
        # These components have no internal dependencies on each other.
        # We assume Cognitive/Energy clients are stateless HTTP wrappers.
        logger.info("--- Phase 1: Infrastructure & Connectivity ---")

        # We use a list to capture results if needed, though mostly we set self.vars
        try:
            results = await asyncio.gather(
                self._ensure_janitor_actor(),
                self._init_holon_fabric(),  # Heavy: Connects to PG/Neo4j
                self._init_service_clients(),  # Light: Cognitive, Energy, MwManager
            )
        except Exception as e:
            logger.critical(f"❌ Phase 1 Boot Failed: {e}")
            raise

        # Extract HolonFabric from the gather result (it returns the instance)
        # Note: _ensure_janitor returns None, _init_services returns None
        self.holon_fabric = results[1]

        # ==============================================================
        # PHASE 2: ADAPTERS & LOGIC (Sequential dependency on Phase 1)
        # ==============================================================
        logger.info("--- Phase 2: Logic Adapters & Registries ---")

        # 2a. SkillStore (Immediate dependency on HolonFabric)
        self.skill_store = HolonFabricSkillStoreAdapter(self.holon_fabric)

        # 2b. Parallelize Registries and Tool Managers
        # ToolManager needs SkillStore (ready) and MwManager (ready from Phase 1)
        await asyncio.gather(
            self._init_organ_registry(),
            self._init_tool_manager(),
        )

        # ==============================================================
        # PHASE 3: ACTOR SPAWNING (The Heavy Lifting)
        # ==============================================================
        logger.info("--- Phase 3: Spawning Organism Actors ---")

        # 3a. Register all role profiles BEFORE creating agents (Option A: Strict Ordering)
        # This ensures all specializations are registered before any agent tries to access them
        await self._register_all_role_profiles_from_config()

        # 3b. Organs must be created before agents (agents depend on organs)
        await self._create_organs_from_config()

        # 3c. Propagate role registry to all organs (ensures consistency)
        await self._sync_role_registry_to_organs()

        # 3d. Now create agents (they can be created in parallel batches)
        await self._create_agents_from_config()

        # ==============================================================
        # PHASE 4: BACKGROUND LOOPS
        # ==============================================================
        logger.info("--- Phase 4: Lifecycle Hooks ---")

        if _env_bool("ORGANISM_HEALTHCHECKS", True):
            self._health_check_task = asyncio.create_task(self._health_loop())

        if _env_bool("ORGANISM_RECONCILE", True):
            self._recon_task = asyncio.create_task(self._reconciliation_loop())

        duration = asyncio.get_running_loop().time() - start_time
        self._initialized = True
        logger.info(f"🌱 OrganismCore initialized in {duration:.2f}s!")

    # ------------------------------------------------------------------
    #  HELPER: Actor Deployment Configuration
    # ------------------------------------------------------------------
    def _get_organ_actor_options(self, organ_id: str) -> Dict[str, Any]:
        """
        Builds dynamic Ray Actor options for Organ actors based on environment variables.
        Allows tuning CPU/Memory/Retries without code changes.

        Args:
            organ_id: The organ identifier (used as actor name)

        Returns:
            Dict of Ray actor options ready for ** unpacking
        """
        # 1. Load Tunables from Env (with sensible defaults)
        # Use a tiny default (0.01) for lightweight actors, or 0.1+ for heavy ones
        cpu_request = float(os.getenv("SEEDCORE_ORGAN_CPU", "0.01"))

        # -1 means infinite restarts (standard for long-running services)
        max_restarts = int(os.getenv("SEEDCORE_ORGAN_MAX_RESTARTS", "-1"))

        # "detached" keeps the actor alive if the driver script exits
        # "non_detached" is better for unit tests to clean up automatically
        lifetime = os.getenv("SEEDCORE_ACTOR_LIFETIME", "detached")

        # Task retries: -1 means infinite (usually bad), 0 means no retries, 3 is reasonable
        max_task_retries = int(os.getenv("SEEDCORE_ORGAN_MAX_TASK_RETRIES", "-1"))

        return {
            "name": organ_id,
            "namespace": RAY_NAMESPACE,
            "lifetime": lifetime,
            "max_restarts": max_restarts,
            "max_task_retries": max_task_retries,
            "num_cpus": cpu_request,
            # "resources": {"custom_resource": 1}  # easy to add later
        }

    def _get_agent_actor_options(self, agent_id: str) -> Dict[str, Any]:
        """
        Builds dynamic Ray Actor options for Agent actors based on environment variables.
        These options are passed as kwargs to create_agent.remote().

        Args:
            agent_id: The agent identifier (used as actor name)

        Returns:
            Dict of agent actor options ready for ** unpacking
        """
        # Agent-specific tunables
        cpu_request = float(os.getenv("SEEDCORE_AGENT_CPU", "0.02"))
        lifetime = os.getenv("SEEDCORE_ACTOR_LIFETIME", "detached")

        return {
            "name": agent_id,
            "num_cpus": cpu_request,
            "lifetime": lifetime,
        }

    def _get_tool_shard_actor_options(self) -> Dict[str, Any]:
        """
        Builds dynamic Ray Actor options for ToolManagerShard actors.
        Note: ToolManagerShard has @ray.remote(num_cpus=0.2) in class definition,
        but we can override with .options() if needed.

        Returns:
            Dict of tool shard actor options (currently empty, can be extended)
        """
        # Tool shards are heavier, so they might need more CPU
        cpu_request = float(os.getenv("SEEDCORE_TOOL_SHARD_CPU", "0.1"))
        max_restarts = int(os.getenv("SEEDCORE_TOOL_SHARD_MAX_RESTARTS", "-1"))
        lifetime = os.getenv("SEEDCORE_ACTOR_LIFETIME", "detached")

        return {
            "max_restarts": max_restarts,
            "lifetime": lifetime,
            "num_cpus": cpu_request,
        }

    def _get_janitor_actor_options(self) -> Dict[str, Any]:
        """
        Builds dynamic Ray Actor options for Janitor actor.

        Returns:
            Dict of janitor actor options
        """
        cpu_request = float(os.getenv("SEEDCORE_JANITOR_CPU", "0"))
        lifetime = os.getenv("SEEDCORE_ACTOR_LIFETIME", "detached")

        return {
            "name": "seedcore_janitor",
            "namespace": RAY_NAMESPACE,
            "lifetime": lifetime,
            "num_cpus": cpu_request,
        }

    # ------------------------------------------------------------------
    #  HELPER: Holon Fabric Config (for passing to remote actors)
    # ------------------------------------------------------------------
    def _get_holon_fabric_config(self) -> Dict[str, Any]:
        """
        Build config dict for HolonFabric initialization in remote actors.
        This avoids serialization issues by passing config instead of live connections.

        Returns a structured config dict with explicit pg/neo4j sections to avoid
        positional ambiguity and enable future schema evolution.
        """
        default_pool_size = int(os.getenv("PG_POOL_SIZE", "2"))
        pool_size = self.config.get("pg_pool_size", default_pool_size)

        return {
            "pg": {
                "dsn": PG_DSN,
                "pool_size": pool_size,
            },
            "neo4j": {
                "uri": NEO4J_URI or NEO4J_BOLT_URL,
                "user": NEO4J_USER,
                "password": NEO4J_PASSWORD,
            },
        }

    # ------------------------------------------------------------------
    #  HELPER: Cognitive Client Config (for passing to remote actors)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    #  HELPER: Shared Configuration Builder
    # ------------------------------------------------------------------
    def _build_service_config(
        self,
        config_key: str,
        client_attr: str,
        env_base_url: str,
        fallback_url_fn: Callable[[], str],
        env_timeout: str,
        default_timeout: float,
        env_retries: Optional[str] = None,
        default_retries: int = 1,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generic builder for service client configurations.
        Priority: Live Client Object > Config Dict > Environment Variables > Defaults
        """
        # 1. Try to extract from live client (Best-effort optimization)
        client = getattr(self, client_attr, None)
        if client:
            config = {
                "base_url": client.base_url,
                "timeout": client.timeout,
                "circuit_breaker": {
                    "failure_threshold": client.circuit_breaker.failure_threshold,
                    "recovery_timeout": client.circuit_breaker.recovery_timeout,
                },
                "retry_config": {
                    "max_attempts": client.retry_config.max_attempts,
                    "base_delay": client.retry_config.base_delay,
                    "max_delay": client.retry_config.max_delay,
                },
            }
            # Add any extra fields if they exist on the client
            if extra_fields:
                for field in extra_fields:
                    val = getattr(client, field, extra_fields[field])
                    config[field] = val
            return config

        # 2. Fallback to Config / Env / Defaults
        cfg = self.config.get(config_key, {})

        # Resolve Base URL
        base_url = cfg.get("base_url")
        if not base_url:
            base_url = os.getenv(env_base_url)
        if not base_url:
            base_url = fallback_url_fn()

        # Resolve Timeout
        timeout = cfg.get("timeout")
        if timeout is None:
            timeout = float(os.getenv(env_timeout, str(default_timeout)))

        # Resolve Retries (for retry_config)
        retries = cfg.get("retries")
        if retries is None:
            if env_retries:
                retries = int(os.getenv(env_retries, str(default_retries)))
            else:
                retries = default_retries

        # Construct Final Config
        result = {
            "base_url": base_url.rstrip("/") if base_url else "",
            "timeout": timeout,
            "circuit_breaker": cfg.get(
                "circuit_breaker",
                {
                    "failure_threshold": 5,
                    "recovery_timeout": 30.0,
                },
            ),
            "retry_config": cfg.get(
                "retry_config",
                {
                    "max_attempts": max(1, retries),
                    "base_delay": 1.0,
                    "max_delay": 5.0,
                },
            ),
        }

        # Merge extra fields (like warmup_timeout)
        if extra_fields:
            for k, v in extra_fields.items():
                result[k] = cfg.get(k, v)

        return result

    # ------------------------------------------------------------------
    #  Refactored Client Config Getters
    # ------------------------------------------------------------------
    def _get_cognitive_client_config(self) -> Dict[str, Any]:
        def _get_cog_url():
            try:
                from seedcore.utils.ray_utils import COG

                return COG
            except ImportError:
                return "http://127.0.0.1:8000/cognitive"

        return self._build_service_config(
            config_key="cognitive_client",
            client_attr="cognitive_client",
            env_base_url="COG_BASE_URL",
            fallback_url_fn=_get_cog_url,
            env_timeout="COG_CLIENT_TIMEOUT",
            default_timeout=75.0,
            env_retries="COG_CLIENT_RETRIES",
            default_retries=1,
        )

    def _get_ml_client_config(self) -> Dict[str, Any]:
        def _get_ml_url():
            try:
                from seedcore.utils.ray_utils import ML

                return ML
            except ImportError:
                return os.getenv("ML_BASE_URL", "http://127.0.0.1:8000/ml")

        return self._build_service_config(
            config_key="ml_client",
            client_attr="ml_client",
            env_base_url="ML_BASE_URL",  # Note: logic handles redundant env check safely
            fallback_url_fn=_get_ml_url,
            env_timeout="ML_CLIENT_TIMEOUT",
            default_timeout=10.0,
            default_retries=2,  # ML client defaults to 2 retries
            extra_fields={
                "warmup_timeout": float(os.getenv("ML_WARMUP_TIMEOUT", "30.0"))
            },
        )

    def _get_mcp_client_config(self) -> Optional[Dict[str, Any]]:
        def _get_mcp_url():
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY

                return f"{SERVE_GATEWAY}/mcp"
            except ImportError:
                return "http://127.0.0.1:8000/mcp"

        return self._build_service_config(
            config_key="mcp_client",
            client_attr="mcp_client",
            env_base_url="MCP_BASE_URL",
            fallback_url_fn=_get_mcp_url,
            env_timeout="MCP_CLIENT_TIMEOUT",
            default_timeout=30.0,
            default_retries=1,
        )

    def _get_mw_manager_config(self) -> Dict[str, Any]:
        """Simple config for MwManager."""
        return {"organ_id": "tool_manager_shard"}

    # ------------------------------------------------------------------
    #  HELPER: Holon Fabric (Storage Layer)
    # ------------------------------------------------------------------
    async def _init_holon_fabric(self) -> HolonFabric:
        """Initialize PG + Neo4j and return the Fabric instance."""
        logger.info("🔌 Connecting HolonFabric Storage...")

        # Pool size calculation:
        # - OrganismService can have up to 5 replicas (see rayservice.yaml)
        # - Each replica creates its own pool
        # - PostgreSQL default max_connections is usually 100
        # - Other services (Reaper, dispatchers, etc.) also need connections
        # - Default: 2 connections per replica (5 replicas × 2 = 10 connections)
        # - Configurable via PG_POOL_SIZE env var or config.pg_pool_size
        default_pool_size = int(os.getenv("PG_POOL_SIZE", "2"))
        pool_size = self.config.get("pg_pool_size", default_pool_size)

        pg_store = PgVectorStore(
            dsn=PG_DSN,
            pool_size=pool_size,
            pool_min_size=1,  # Minimum 1 connection per replica
        )
        neo4j_graph = Neo4jGraph(
            NEO4J_URI or NEO4J_BOLT_URL,
            auth=(NEO4J_USER, NEO4J_PASSWORD),
        )

        # Connect both DBs in parallel
        await asyncio.gather(
            pg_store._get_pool(),
            # Assuming neo4j_graph has an async verify or connect method
            # If not, it's usually lazy, which is fine.
            self._verify_neo4j(neo4j_graph),
        )

        return HolonFabric(
            vec_store=pg_store,
            graph=neo4j_graph,
            embedder=None,
        )

    # ------------------------------------------------------------------
    #  HELPER: Service Clients
    # ------------------------------------------------------------------
    async def _init_service_clients(self):
        """
        Initialize external API clients and Middleware manager.

        ⚠️ CRITICAL RAY SAFETY RULE:
        These clients MUST NOT be passed to Ray actors via .remote() calls.
        Actors must reconstruct clients from *_config helper methods.

        These clients are ONLY for use within OrganismCore (driver process).
        """
        self.cognitive_client = CognitiveServiceClient()
        self.energy_client = EnergyServiceClient()
        self.ml_client = MLServiceClient()
        try:
            self.mw_manager = MwManager(organ_id="organism_core_mw")
        except Exception as e:
            logger.warning(f"⚠️ MwManager init failed (Non-Critical): {e}")
            self.mw_manager = None

    # ------------------------------------------------------------------
    #  HELPER: Tuya Integration Check
    # ------------------------------------------------------------------
    def is_tuya_enabled(self) -> bool:
        """
        Check if Tuya integration is enabled.

        Returns:
            True if Tuya is enabled and configured, False otherwise
        """
        try:
            from seedcore.config.tuya_config import TuyaConfig

            tuya_config = TuyaConfig()
            return tuya_config.enabled
        except Exception:
            return False

    # ------------------------------------------------------------------
    #  HELPER: Tool Manager (Sharding Logic)
    # ------------------------------------------------------------------
    async def _init_tool_manager(self):
        """Calculates sharding requirements and spawns Tool Managers."""
        # This count might be async if checking a DB
        num_agents = await self._count_agents_from_config()
        threshold = self.config.get("agent_threshold_for_shards", 100)

        if num_agents < threshold:
            self.tool_manager = ToolManager(skill_store=self.skill_store)
            self.tool_handler = self.tool_manager
            logger.info("🔧 ToolManager initialized (Single Mode)")

            # Register Tuya tools if enabled
            await register_tuya_tools(self.tool_manager)
            
            # Register Reachy simulation tools
            await register_reachy_tools(self.tool_manager)
        else:
            # Dynamic Sharding Calculation
            # Default: 1 shard per 1000 agents, min 4, max 16
            shard_count = min(16, max(4, num_agents // 1000 * 4))

            logger.info(f"🔧 Spawning {shard_count} ToolManager shards...")

            # Create remote actors
            # Note: We don't await the remote() call itself (it returns ActorHandle instantly)
            # but if the Actors perform heavy init in __init__, we might want to wait for them to be ready.
            # Build configs for ToolManagerShard (avoids serialization issues)
            # CRITICAL: Pass configs, NOT live instances (locks, pools, sessions are non-serializable)
            holon_fabric_config = self._get_holon_fabric_config()
            cognitive_client_cfg = self._get_cognitive_client_config()
            ml_client_cfg = self._get_ml_client_config()
            mw_manager_cfg = self._get_mw_manager_config()
            mcp_client_cfg = self._get_mcp_client_config()

            # Get configuration-driven actor options for tool shards
            tool_shard_opts = self._get_tool_shard_actor_options()

            self.tool_shards = [
                ToolManagerShard.options(**tool_shard_opts).remote(
                    holon_fabric_config=holon_fabric_config,
                    mw_manager_cfg=mw_manager_cfg,
                    cognitive_client_cfg=cognitive_client_cfg,
                    ml_client_cfg=ml_client_cfg,
                    mcp_client_cfg=mcp_client_cfg,
                )
                for _ in range(shard_count)
            ]
            self.tool_handler = self.tool_shards

            # Register Tuya tools in all shards if enabled
            # Use gather to register in parallel for better performance
            registration_tasks = [
                register_tuya_tools(shard) for shard in self.tool_shards
            ]
            
            # Register Reachy tools in all shards
            reachy_tasks = [
                register_reachy_tools(shard) for shard in self.tool_shards
            ]
            registration_tasks.extend(reachy_tasks)
            await asyncio.gather(*registration_tasks, return_exceptions=True)

    # ------------------------------------------------------------------
    #  HELPER: Registries
    # ------------------------------------------------------------------
    async def _init_organ_registry(self):
        try:
            agent_repo = AgentGraphRepository()
            # Get session factory for database persistence
            try:
                from seedcore.database import get_async_pg_session_factory

                session_factory = get_async_pg_session_factory()
            except Exception as e:
                logger.warning(
                    f"⚠️ Could not get session factory for OrganRegistry: {e}"
                )
                session_factory = None
            self.organ_registry = OrganRegistry(
                agent_repo, session_factory=session_factory
            )
        except Exception as e:
            logger.warning(f"⚠️ OrganRegistry init failed: {e}")
            self.organ_registry = None

    def _create_serializable_organ_registry(self) -> Optional[OrganRegistry]:
        """
        Create a lightweight OrganRegistry copy without session_factory for Ray serialization.

        The session_factory contains thread locks that cannot be pickled by Ray.
        This lightweight copy can be passed to Organ actors. The Organ will work
        in-memory only or pass sessions explicitly when needed.

        Returns:
            Lightweight OrganRegistry instance without session_factory, or None if
            self.organ_registry is None
        """
        if not self.organ_registry:
            return None

        from seedcore.graph.agent_repository import AgentGraphRepository

        # Create a new registry instance without session_factory to avoid serialization issues
        lightweight_registry = OrganRegistry(
            repo=AgentGraphRepository(),
            session_factory=None,  # Don't pass session_factory to avoid serialization issues
        )
        return lightweight_registry

    async def _verify_neo4j(self, graph_client):
        """Optional hook to verify Neo4j connectivity asynchronously."""
        # Implementation depends on your Neo4jGraph class
        pass

    async def _register_all_role_profiles_from_config(self) -> None:
        """
        Extract all specializations from config and ensure they're registered in RoleRegistry.
        This implements Option A: Strict Ordering - all roles must be registered before agents are created.

        Supports both static Specialization enum and dynamic specializations.

        Integration with specializations.yaml:
        - Loads specializations.yaml first (if exists) to register dynamic specializations with their role profiles
        - Then processes organs.yaml to ensure all referenced specializations are registered
        - Role profiles from specializations.yaml provide default_behaviors and behavior_config
        - organs.yaml can override these defaults per-agent
        """
        logger.info("--- Registering all role profiles from config ---")

        spec_manager = SpecializationManager.get_instance()

        # Step 1: Load specializations.yaml first (if exists) to register dynamic specializations
        # This ensures role profiles with default_behaviors and behavior_config are available
        specializations_config_path = os.getenv(
            "SPECIALIZATIONS_CONFIG_PATH",
            str(Path(self.config_path).parent / "specializations.yaml"),
        )
        specializations_path = Path(specializations_config_path)

        if specializations_path.exists():
            try:
                loaded_count = spec_manager.load_from_config(specializations_path)
                logger.info(
                    f"✅ Loaded {loaded_count} dynamic specializations from {specializations_path.name}"
                )

                # Register role profiles from specializations.yaml into RoleRegistry
                # This ensures default_behaviors and behavior_config are available
                # Get all dynamic specializations and their role profiles
                dynamic_specs = spec_manager.list_dynamic()
                registered_dynamic_count = 0
                for dynamic_spec in dynamic_specs:
                    profile = spec_manager.get_role_profile(dynamic_spec)
                    if not profile:
                        continue

                    # Check if already registered (might have been registered from DEFAULT_ROLE_REGISTRY)
                    existing = self.role_registry.get_safe(profile.name)
                    if existing:
                        # Merge behaviors if existing profile doesn't have them
                        if not existing.default_behaviors and profile.default_behaviors:
                            # Update existing profile with behaviors from specializations.yaml
                            existing.default_behaviors = list(profile.default_behaviors)
                            existing.behavior_config = dict(profile.behavior_config)
                            logger.debug(
                                f"  📝 Updated behaviors for {dynamic_spec.value} from specializations.yaml"
                            )
                    else:
                        # Register new profile
                        self.role_registry.register(profile)
                        registered_dynamic_count += 1
                        logger.debug(
                            f"  ✅ Registered role profile for {dynamic_spec.value} from specializations.yaml "
                            f"(behaviors={profile.default_behaviors})"
                        )

                if registered_dynamic_count > 0:
                    logger.info(
                        f"✅ Registered {registered_dynamic_count} role profiles from specializations.yaml"
                    )
            except Exception as e:
                logger.warning(
                    f"⚠️ Failed to load specializations.yaml from {specializations_path}: {e}. "
                    "Continuing without dynamic specializations.",
                    exc_info=True,
                )
        else:
            logger.debug(
                f"ℹ️ Specializations config not found at {specializations_path}. "
                "Skipping dynamic specialization loading."
            )

        # Step 2: Collect all unique specializations from organs.yaml config
        specialization_strings: Set[str] = set()

        for cfg in self.organ_configs:
            agent_defs = cfg.get("agents", [])
            for block in agent_defs:
                spec_str = block.get("specialization")
                if spec_str:
                    specialization_strings.add(str(spec_str).strip())

        # Step 3: Resolve specializations (static or dynamic)
        specializations_needed: Set[SpecializationProtocol] = set()

        for spec_str in specialization_strings:
            try:
                # Use get_specialization() which handles both static and dynamic
                spec = get_specialization(spec_str)
                specializations_needed.add(spec)
            except KeyError:
                # Specialization not found - try to register as dynamic
                try:
                    logger.info(
                        f"⚠️ Specialization '{spec_str}' not found, attempting to register as dynamic"
                    )
                    # Register as dynamic specialization (will be created if needed)
                    spec = spec_manager.register_dynamic(
                        value=spec_str,
                        name=spec_str.replace("_", " ").title(),
                        metadata={"source": "organ_config"},
                    )
                    specializations_needed.add(spec)
                    logger.info(f"  ✅ Registered dynamic specialization '{spec_str}'")
                except Exception as e:
                    logger.warning(
                        f"⚠️ Failed to register specialization '{spec_str}': {e}. Skipping."
                    )

        # Step 4: Register missing specializations with default profiles
        # Priority: 1) SpecializationManager (from specializations.yaml), 2) DEFAULT_ROLE_REGISTRY, 3) Minimal default
        registered_count = 0
        for spec in specializations_needed:
            # Check if already registered
            if self.role_registry.get_safe(spec) is None:
                # Try to get from SpecializationManager first (may have been loaded from specializations.yaml)
                spec_manager_profile = None
                if spec_manager.is_registered(
                    spec.value if hasattr(spec, "value") else str(spec)
                ):
                    # Check if SpecializationManager has a role profile for this specialization
                    # (This would have been set during load_from_config)
                    # Note: SpecializationManager doesn't directly expose role profiles,
                    # but they're registered in RoleRegistry when load_from_config is called
                    # So we check DEFAULT_ROLE_REGISTRY next
                    # Verification that specialization exists in SpecializationManager is sufficient
                    pass

                # Try to get from DEFAULT_ROLE_REGISTRY (may have better defaults including behaviors)
                default_profile = DEFAULT_ROLE_REGISTRY.get_safe(spec)
                if default_profile:
                    # Use the default profile from DEFAULT_ROLE_REGISTRY
                    # This includes default_behaviors and behavior_config if defined
                    self.role_registry.register(default_profile)
                    logger.info(
                        f"  ✅ Registered profile for {spec.value} from DEFAULT_ROLE_REGISTRY "
                        f"(behaviors={default_profile.default_behaviors})"
                    )
                else:
                    # Create a minimal default RoleProfile for this specialization
                    profile = RoleProfile(
                        name=spec,
                        default_skills={},  # Empty defaults - can be customized later
                        allowed_tools=set(),  # Empty defaults - can be customized later
                        routing_tags=set(),
                        safety_policies={},
                        default_behaviors=[],  # Empty behaviors - can be customized via organs.yaml
                        behavior_config={},  # Empty config - can be customized via organs.yaml
                    )
                    self.role_registry.register(profile)
                    logger.info(
                        f"  ✅ Registered minimal default profile for {spec.value}"
                    )
                registered_count += 1

        if registered_count > 0:
            logger.info(
                f"✅ Registered {registered_count} new role profiles. "
                f"Total specializations: {len(specializations_needed)}"
            )
        else:
            logger.info(
                f"✅ All {len(specializations_needed)} specializations already registered"
            )

    async def _sync_role_registry_to_organs(self) -> None:
        """
        Propagate all role profiles from the global registry to all organ actors.
        This ensures organs have the complete registry before agents are created.
        """
        if not self.organs:
            logger.info("No organs to sync role registry to")
            return

        logger.info(f"--- Syncing role registry to {len(self.organs)} organs ---")

        # Get all registered profiles
        all_profiles = list(self.role_registry._profiles.values())

        if not all_profiles:
            logger.warning("⚠️ No role profiles to sync")
            return

        # Propagate each profile to all organs
        futures = []
        for organ_id, organ_handle in self.organs.items():
            for profile in all_profiles:
                futures.append(organ_handle.update_role_registry.remote(profile))

        # Wait for all propagations to complete
        if futures:
            await asyncio.gather(*futures, return_exceptions=True)
            logger.info(
                f"✅ Synced {len(all_profiles)} role profiles to {len(self.organs)} organs"
            )

    async def register_or_update_role(self, profile: RoleProfile) -> None:
        """
        Update the global RoleRegistry and propagate to all Organs.
        """
        # 1. Update Core's local copy (The Source of Truth)
        self.role_registry.register(profile)
        logger.info(
            f"[OrganismCore] Updated global registry for role: {profile.name.value}"
        )

        # 2. Push update to all distributed Organ actors
        # Because they hold their own cached copy of the registry.
        futures = []
        for organ_id, organ_handle in self.organs.items():
            # Call the method on the Organ (see below)
            futures.append(organ_handle.update_role_registry.remote(profile))

        # 3. Wait for propagation (ensures consistency)
        if futures:
            await asyncio.gather(*futures)
            logger.info(
                f"[OrganismCore] ✅ Synced role update to {len(futures)} organs."
            )

    # ==================================================================
    #  ORGAN CREATION
    # ==================================================================
    async def _create_organs_from_config(self):
        """
        Instantiate all Organ actors defined in the YAML config.

        This method is idempotent: calling it multiple times will only create
        organs that don't already exist in self.organs. This enables dynamic
        organ creation by adding new entries to self.organ_configs and calling
        this method again.
        """
        logger.info(f"[OrganismCore] Spawning {len(self.organ_configs)} organs...")

        for cfg in self.organ_configs:
            organ_id = cfg["id"]

            # Idempotent check: skip if organ already exists
            if organ_id in self.organs:
                # Verify the organ is still reachable (lightweight check)
                try:
                    organ_handle = self.organs[organ_id]
                    ping_ref = organ_handle.ping.remote()
                    await asyncio.wait_for(
                        asyncio.to_thread(ray.get, ping_ref), timeout=2.0
                    )
                    logger.info(f"  ↪ Organ {organ_id} already exists and is alive.")
                except Exception:
                    # Organ exists but is unreachable - will be handled by reconciliation loop
                    logger.warning(
                        f"  ⚠️ Organ {organ_id} exists but is unreachable. "
                        "Reconciliation loop will handle recovery."
                    )
                continue

            logger.info(f"  ➕ Creating Organ actor: {organ_id}")

            try:
                # --- Get configuration-driven actor options ---
                actor_opts = self._get_organ_actor_options(organ_id)

                # --- Create lightweight OrganRegistry copy without session_factory for serialization ---
                lightweight_registry = self._create_serializable_organ_registry()

                # --- Pass all dependencies to the Organ actor ---
                organ = Organ.options(
                    **actor_opts
                ).remote(
                    organ_id=organ_id,
                    # Stateless dependencies
                    role_registry=self.role_registry,
                    cognitive_client_cfg=self._get_cognitive_client_config(),
                    ml_client_cfg=self._get_ml_client_config(),
                    # Config for creating connections (avoids serialization)
                    holon_fabric_config=self._get_holon_fabric_config(),
                    # Tool handler: pass shard handles if sharded, None if single mode (creates locally)
                    tool_handler_shards=self.tool_shards
                    if hasattr(self, "tool_shards") and self.tool_shards
                    else None,
                    # Stateful dependencies (pass config/ID instead of instances)
                    mw_manager_organ_id=organ_id,  # Pass organ_id, create MwManager locally in actor
                    checkpoint_cfg=self.checkpoint_cfg,
                    # OrganRegistry for Tier-1 registration (lightweight copy without session_factory)
                    organ_registry=lightweight_registry,
                )

                # Sanity check
                ok_ref = organ.health_check.remote()
                ok = await self._ray_await(ok_ref)
                if not ok:
                    raise RuntimeError(f"Organ {organ_id} failed health check.")

                self.organs[organ_id] = organ

                # Register organ in Tier-1 registry (with DB persistence)
                if self.organ_registry:
                    # Extract organ metadata from config
                    organ_kind = (
                        cfg.get("kind") or cfg.get("description", "").split(".")[0]
                        if cfg.get("description")
                        else None
                    )
                    organ_props = {
                        "description": cfg.get("description"),
                        "config": cfg,
                    }
                    await self.organ_registry.record_organ(
                        organ_id,
                        organ,
                        kind=organ_kind,
                        props=organ_props,
                    )

            except Exception as e:
                logger.error(
                    f"❌ Failed to create organ '{organ_id}': {e}", exc_info=True
                )
                raise

        logger.info(f"✅ Organ creation complete. Total organs: {len(self.organs)}")

    async def _create_organs_batch(
        self, organ_configs: List[Dict[str, Any]]
    ) -> Dict[str, ray.actor.ActorHandle]:
        """
        Create a batch of organs from a list of configs.
        Returns a dict mapping organ_id -> organ_handle for the newly created organs.
        """
        new_organs: Dict[str, ray.actor.ActorHandle] = {}

        for cfg in organ_configs:
            organ_id = cfg["id"]

            # Skip if already exists
            if organ_id in self.organs:
                logger.info(f"  ↪ Organ {organ_id} already exists, skipping.")
                continue

            logger.info(f"  ➕ Creating Organ actor: {organ_id}")

            try:
                # --- Get configuration-driven actor options ---
                actor_opts = self._get_organ_actor_options(organ_id)

                # --- Create lightweight OrganRegistry copy without session_factory for serialization ---
                lightweight_registry = self._create_serializable_organ_registry()

                # --- Pass all dependencies to the Organ actor ---
                organ = Organ.options(
                    **actor_opts
                ).remote(
                    organ_id=organ_id,
                    # Stateless dependencies
                    role_registry=self.role_registry,
                    cognitive_client_cfg=self._get_cognitive_client_config(),
                    ml_client_cfg=self._get_ml_client_config(),
                    # Config for creating connections (avoids serialization)
                    holon_fabric_config=self._get_holon_fabric_config(),
                    # Tool handler: pass shard handles if sharded, None if single mode (creates locally)
                    tool_handler_shards=self.tool_shards
                    if hasattr(self, "tool_shards") and self.tool_shards
                    else None,
                    # Stateful dependencies (pass config/ID instead of instances)
                    mw_manager_organ_id=organ_id,  # Pass organ_id, create MwManager locally in actor
                    checkpoint_cfg=self.checkpoint_cfg,
                    # OrganRegistry for Tier-1 registration (lightweight copy without session_factory)
                    organ_registry=lightweight_registry,
                )

                # Sanity check
                ok_ref = organ.health_check.remote()
                ok = await self._ray_await(ok_ref)
                if not ok:
                    raise RuntimeError(f"Organ {organ_id} failed health check.")

                new_organs[organ_id] = organ

                # Register organ in Tier-1 registry (with DB persistence)
                if self.organ_registry:
                    # Extract organ metadata from config
                    organ_kind = (
                        cfg.get("kind") or cfg.get("description", "").split(".")[0]
                        if cfg.get("description")
                        else None
                    )
                    organ_props = {
                        "description": cfg.get("description"),
                        "config": cfg,
                    }
                    await self.organ_registry.record_organ(
                        organ_id,
                        organ,
                        kind=organ_kind,
                        props=organ_props,
                    )

            except Exception as e:
                logger.error(
                    f"❌ Failed to create organ '{organ_id}': {e}", exc_info=True
                )
                raise

        return new_organs

    # ==================================================================
    #  AGENT CREATION & ROUTING MAP BUILD
    # ==================================================================
    async def _create_agents_from_config(
        self, target_organs: Optional[List[Dict[str, Any]]] = None
    ):
        """
        Create agents and build the Specialization -> Organ routing table.

        Optimized for:
        1. True Idempotency (Checks Ray for detached actors).
        2. Parallelism (Spawns agents concurrently).
        3. State Re-hydration (Restores local map if actors exist).

        Args:
            target_organs: Optional list of organ configs to process.
                          If None, uses self.organ_configs.
        """
        creation_tasks = []
        total_created = 0
        total_restored = 0

        # Use target_organs if provided, otherwise use self.organ_configs
        organs_to_process = (
            target_organs if target_organs is not None else self.organ_configs
        )

        for cfg in organs_to_process:
            organ_id = cfg["id"]
            organ_handle = self.organs.get(organ_id)

            if not organ_handle:
                logger.error(
                    f"❌ [OrganismCore] Organ {organ_id} missing. Skipping agent creation."
                )
                continue

            agent_defs = cfg.get("agents", [])

            for block in agent_defs:
                spec_str = block["specialization"]
                count = int(block.get("count", 1))
                agent_class_name = block.get("class", "BaseAgent")

                # 1. Resolve Specialization (supports both static and dynamic)
                try:
                    spec = get_specialization(spec_str)
                except KeyError:
                    logger.error(
                        f"❌ Invalid specialization '{spec_str}' in organ {organ_id}. "
                        "Ensure it's registered in SpecializationManager."
                    )
                    continue

                # 1a. Behavior Plugin System Migration: Prefer BaseAgent + behaviors
                # If behaviors are specified in config, use BaseAgent (even for USER_LIAISON)
                # Legacy: Auto-assign ConversationAgent only if no behaviors specified
                user_liaison_value = Specialization.USER_LIAISON.value
                agent_behaviors = block.get("behaviors", [])

                # If behaviors are explicitly configured, use BaseAgent (migrated approach)
                if agent_behaviors and agent_class_name == "BaseAgent":
                    # Only log at debug level, and only if behaviors are actually configured
                    # (avoid redundant logging since we'll log the actual behaviors list below)
                    pass  # Logging moved to behavior extraction section below
                # Legacy: Auto-assign ConversationAgent for USER_LIAISON if no behaviors specified
                elif (
                    spec.value == user_liaison_value
                    and agent_class_name == "BaseAgent"
                    and not agent_behaviors
                ):
                    # Check if RoleProfile has default behaviors
                    role_profile = self.role_registry.get(spec)
                    has_default_behaviors = (
                        role_profile
                        and hasattr(role_profile, "default_behaviors")
                        and role_profile.default_behaviors
                    )

                    if not has_default_behaviors:
                        # No behaviors configured - use legacy ConversationAgent for backward compatibility
                        agent_class_name = "ConversationAgent"
                        logger.info(
                            f"[OrganismCore] Auto-assigning ConversationAgent to USER_LIAISON in {organ_id} "
                            f"(no behaviors specified, using legacy class)"
                        )
                    else:
                        logger.debug(
                            f"[OrganismCore] Using BaseAgent with RoleProfile default behaviors for USER_LIAISON in {organ_id}"
                        )

                # Warn if legacy classes are used with behaviors (should use BaseAgent instead)
                if agent_behaviors and agent_class_name != "BaseAgent":
                    logger.warning(
                        f"[OrganismCore] Agent class '{agent_class_name}' specified with behaviors. "
                        f"Consider migrating to BaseAgent + behaviors. Behaviors will be ignored for legacy classes."
                    )

                # 2. Update Routing Map (Last Write Wins)
                spec_val = spec.value
                self.organ_specs[spec_val] = organ_id

                # 2.5. Extract behaviors from agent config (Behavior Plugin System)
                # Merge defaults from RoleProfile with explicit overrides from organs.yaml
                role_profile = self.role_registry.get_safe(spec)
                if role_profile:
                    # Start with RoleProfile defaults (from specializations.yaml or DEFAULT_ROLE_REGISTRY)
                    agent_behaviors = (
                        list(role_profile.default_behaviors)
                        if role_profile.default_behaviors
                        else []
                    )
                    agent_behavior_config = (
                        dict(role_profile.behavior_config)
                        if role_profile.behavior_config
                        else {}
                    )

                    # Override with explicit values from organs.yaml (if provided)
                    if "behaviors" in block:
                        agent_behaviors = block.get("behaviors", [])
                        logger.debug(
                            f"[OrganismCore] Configuring {spec.value} in {organ_id} with behaviors: {agent_behaviors}"
                        )
                    elif agent_behaviors:
                        # Using RoleProfile defaults (no override in organs.yaml)
                        logger.debug(
                            f"[OrganismCore] Using RoleProfile default behaviors for {spec.value} in {organ_id}: {agent_behaviors}"
                        )

                    if "behavior_config" in block:
                        # Merge behavior_config (organs.yaml overrides RoleProfile defaults)
                        override_config = block.get("behavior_config", {})
                        agent_behavior_config = role_profile.merge_behavior_config(
                            override_config
                        )
                        # Only log if there are actual config overrides (avoid noise when no configs)
                        if override_config:
                            config_keys = list(override_config.keys())
                            logger.debug(
                                f"[OrganismCore] Merged behavior_config for {spec.value} in {organ_id}: "
                                f"overriding configs for {len(config_keys)} behavior(s): {config_keys}"
                            )
                else:
                    # No RoleProfile found - use explicit values from organs.yaml only
                    agent_behaviors = block.get("behaviors", [])
                    agent_behavior_config = block.get("behavior_config", {})
                    if agent_behaviors or agent_behavior_config:
                        logger.debug(
                            f"[OrganismCore] Using explicit behaviors for {spec.value} in {organ_id} "
                            f"(no RoleProfile defaults found)"
                        )

                # 3. Schedule Agent Checks/Creation
                for i in range(count):
                    agent_id = f"{organ_id}_{spec_val}_{i}".lower()

                    # Add to batch
                    creation_tasks.append(
                        self._ensure_single_agent(
                            agent_id=agent_id,
                            organ_id=organ_id,
                            organ_handle=organ_handle,
                            spec=spec,
                            agent_class_name=agent_class_name,
                            behaviors=agent_behaviors,  # Pass behaviors from config
                            behavior_config=agent_behavior_config,  # Pass behavior config
                        )
                    )

        # 4. Execute all tasks in parallel
        # This drastically reduces startup time compared to sequential processing
        results = await asyncio.gather(*creation_tasks, return_exceptions=True)

        # 5. Tally results
        for res in results:
            if isinstance(res, Exception):
                logger.error(f"⚠️ Agent creation failure: {res}")
            elif res is True:
                total_created += 1
            elif res is False:
                total_restored += 1

        logger.info(
            f"🤖 Agent Reconciliation Complete: {total_created} new spawned, "
            f"{total_restored} existing re-linked."
        )

    async def _ensure_single_agent(
        self,
        agent_id: str,
        organ_id: str,
        organ_handle: Any,
        spec: SpecializationProtocol,
        agent_class_name: str,
        behaviors: Optional[List[str]] = None,
        behavior_config: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> bool:
        """
        Helper: Ensures a specific agent exists.
        Returns: True if created, False if already existed (restored).
        """
        # A. Check Local Map (Fastest)
        if agent_id in self.agent_to_organ_map:
            return False

        # B. Check Ray Cluster (True Source of Truth)
        # Because agents are 'detached', they survive service restarts.
        try:
            # If this succeeds, the agent exists in the cluster.
            # We just need to update our local map.
            ray.get_actor(agent_id, namespace=RAY_NAMESPACE)

            self.agent_to_organ_map[agent_id] = organ_id
            # Track re-hydration time for grace period (treat as "new" for health checks)
            self._agent_creation_times[agent_id] = asyncio.get_running_loop().time()
            logger.info(f"♻️ Agent {agent_id} found in Ray (re-hydrated).")
            return False

        except ValueError:
            # Actor not found in Ray -> Actually create it.
            pass

        # C. Create via Organ (Remote Call)
        logger.info(f"✨ Spawning agent '{agent_id}' ({agent_class_name})...")

        # Get configuration-driven agent actor options
        agent_opts = self._get_agent_actor_options(agent_id)

        # Get database session for agent registration persistence
        # Note: We pass None as session since Organ.create_agent() will handle DB persistence
        # via OrganRegistry if available. The session is managed within the Organ actor.
        await organ_handle.create_agent.remote(
            agent_id=agent_id,
            specialization=spec,
            organ_id=organ_id,
            agent_class_name=agent_class_name,
            behaviors=behaviors,  # Pass behaviors from config
            behavior_config=behavior_config,  # Pass behavior config
            **agent_opts,  # Unpack: name, num_cpus, lifetime
        )

        self.agent_to_organ_map[agent_id] = organ_id
        # Track agent creation time for grace period in health checks
        self._agent_creation_times[agent_id] = asyncio.get_running_loop().time()
        return True

    # ==================================================================
    #  AGENT NUM COUNT
    # ==================================================================
    async def _count_agents_from_config(self) -> int:
        total = 0
        for cfg in self.organ_configs:
            organ_id = cfg["id"]
            organ = self.organs.get(organ_id)
            if not organ:
                continue
            total += len(cfg.get("agents", []))
        return total

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

    def _is_high_stakes_from_payload(
        self, payload: TaskPayload | Dict[str, Any]
    ) -> bool:
        """
        Inspect payload.params.risk and return is_high_stakes flag.

        NOTE: This is a fallback method. The primary source of truth for is_high_stakes
        is the router's decision, which is embedded in payload.params._router.is_high_stakes.
        This method is used only for backward compatibility when router metadata is not present.

        Architecture:
        - Routing determines is_high_stakes during route_only()
        - Router embeds it in payload.params._router.is_high_stakes
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
        Orchestrates execution on a specific agent.

        Flow:
        1. Resolve Agent (Get existing OR JIT Spawn)
        2. Execute (Normal OR High-Stakes)
        3. Manage Session (Tunnel Lifecycle)
        """
        # --- 1. Validation & Setup ---
        # Extract task_id for canonical envelope
        if hasattr(payload, "task_id"):
            task_id = payload.task_id
        elif isinstance(payload, dict):
            task_id = payload.get("task_id") or payload.get("id") or "unknown"
        else:
            task_id = "unknown"

        organ = self.organs.get(organ_id)
        if not organ:
            return make_envelope(
                task_id=task_id,
                success=False,
                error=f"Organ '{organ_id}' not found",
                error_type="organ_not_found",
                retry=False,
                path="organism_core",
            )

        # Normalize Payload to Dict (Mutable)
        task_dict = (
            payload.model_dump() if hasattr(payload, "model_dump") else payload
        ) or {}
        params = task_dict.get("params", {})
        router_meta = params.get("_router", {}) if isinstance(params, dict) else {}
        if not isinstance(router_meta, dict):
            router_meta = {}

        # --- 1.2. RBAC soft-fallback: convert to cognitive guidance instead of respawn ---
        # If router explicitly fell back due to RBAC/tool restrictions, avoid respawning
        # agents and provide a user-facing guidance response via cognitive service.
        router_reason = str(router_meta.get("reason") or "")
        if router_reason.startswith("rbac_soft_fallback"):
            routing = params.get("routing", {}) if isinstance(params, dict) else {}
            tools_list = routing.get("tools") if isinstance(routing, dict) else None
            spec_hint = None
            if isinstance(routing, dict):
                spec_hint = (
                    routing.get("required_specialization")
                    or routing.get("specialization")
                )
            return await self._cognitive_fallback_for_rbac_denied(
                organ_id=organ_id,
                organ_handle=organ,
                agent_id=agent_id,
                task_id=task_id,
                spec_hint=str(spec_hint) if spec_hint else None,
                tools=tools_list,
                task_dict=task_dict,
            )

        try:
            # --- 1.5. Specialization sanity guard + GENERALIST cognitive fallback ---
            routing = params.get("routing", {}) if isinstance(params, dict) else {}
            required_spec = (
                routing.get("required_specialization") or routing.get("specialization")
            )
            is_hard_required = bool(routing.get("required_specialization"))
            if required_spec and is_hard_required:
                resolved = self._resolve_registered_specialization(
                    str(required_spec).strip().lower(), params
                )
                if not resolved:
                    fallback = await self._cognitive_fallback_for_unregistered_spec(
                        organ_id=organ_id,
                        organ_handle=organ,
                        agent_id=agent_id,
                        task_id=task_id,
                        required_spec=str(required_spec),
                        task_dict=task_dict,
                    )
                    return fallback

            # --- 2. Agent Resolution (JIT Handling) ---
            # We abstract the "Try Get -> Fail -> Spawn -> Retry" loop here
            requested_agent_id = agent_id
            requested_organ_id = organ_id
            resolved_agent_id = agent_id
            resolved_organ_id = organ_id
            agent_resolution = await self._ensure_agent_handle(
                organ, organ_id, agent_id, params
            )

            if not agent_resolution:
                return make_envelope(
                    task_id=task_id,
                    success=False,
                    error=f"Agent '{agent_id}' could not be provisioned.",
                    error_type="agent_provisioning_failed",
                    retry=True,  # Allow retry after respawn completes
                    path="organism_core",
                )
            resolved_agent_id, agent_handle, resolved_organ_id = agent_resolution
            resolved_organ = self.organs.get(resolved_organ_id, organ)
            used_fallback = (
                resolved_agent_id != requested_agent_id
                or resolved_organ_id != requested_organ_id
            )

            # --- 2.5. Agent Readiness Check (prevent execution on respawning agents) ---
            # Check if agent is ready by attempting a lightweight ping
            agent_ready = False
            max_readiness_checks = 3
            readiness_check_delay = 0.5

            for attempt in range(max_readiness_checks):
                try:
                    # Try a lightweight check - if agent has get_heartbeat, use it
                    if hasattr(agent_handle, "get_heartbeat"):
                        heartbeat_ref = agent_handle.get_heartbeat.remote()
                        # Use a short timeout to avoid hanging
                        # Use _ray_await helper which properly handles async ray.get
                        await asyncio.wait_for(
                            self._ray_await(heartbeat_ref, timeout=2.0),
                            timeout=2.5,  # Slightly longer than ray.get timeout
                        )
                        agent_ready = True
                        break
                    else:
                        # No heartbeat method - assume ready if handle exists
                        agent_ready = True
                        break
                except (asyncio.TimeoutError, Exception) as e:
                    if attempt < max_readiness_checks - 1:
                        self.logger.info(
                            f"[{resolved_agent_id}] Agent not ready (attempt {attempt + 1}/{max_readiness_checks}): {e}. "
                            f"Waiting {readiness_check_delay}s before retry..."
                        )
                        await asyncio.sleep(readiness_check_delay)
                        readiness_check_delay *= 2  # Exponential backoff
                    else:
                        self.logger.warning(
                            f"[{resolved_agent_id}] Agent handle exists but not responding after {max_readiness_checks} attempts. "
                            f"Agent may be respawning. Error: {e}"
                        )

            if not agent_ready:
                return make_envelope(
                    task_id=task_id,
                    success=False,
                    error=f"Agent '{resolved_agent_id}' is not ready (may be respawning). Please retry.",
                    error_type="agent_not_ready",
                    retry=True,  # Allow retry after agent becomes ready
                    meta={
                        "agent_status": "respawning_or_unavailable",
                        "requested_agent_id": requested_agent_id,
                        "resolved_agent_id": resolved_agent_id,
                        "requested_organ_id": requested_organ_id,
                        "resolved_organ_id": resolved_organ_id,
                    },
                    path="organism_core",
                )

            if agent_handle:
                self.logger.info(
                    f"[OrganismCore] Agent handle resolved and ready: {resolved_agent_id} in {resolved_organ_id}"
                )
                
                # **CRITICAL FIX: Always check for specialization mismatch before execution**
                # This catches agents that were spawned with wrong specialization and fixes them immediately
                # We ALWAYS check agent ID pattern, even if routing params don't specify specialization
                routing = params.get("routing", {}) if isinstance(params, dict) else {}
                required_spec = routing.get("required_specialization") or routing.get("specialization")
                is_hard_required = bool(routing.get("required_specialization"))
                router_reason = str(router_meta.get("reason") or "")
                
                # **ENHANCEMENT: Always derive required specialization from agent ID as fallback**
                # Agent IDs often contain specialization name (e.g., "physical_actuation_organ_reachy_actuator_0")
                # This ensures we catch mismatches even when routing params don't specify specialization
                if not required_spec:
                    agent_id_lower = resolved_agent_id.lower()
                    # Try to extract specialization from agent ID
                    from seedcore.agents.roles.specialization import SpecializationManager
                    spec_manager = SpecializationManager.get_instance()
                    all_specs = spec_manager.list_all()  # Returns list of SpecializationProtocol objects
                    
                    # Extract specialization values (strings) for matching
                    for spec_protocol in all_specs:
                        spec_value = str(spec_protocol.value).lower() if hasattr(spec_protocol, 'value') else str(spec_protocol).lower()
                        if spec_value in agent_id_lower and len(spec_value) > 3:  # Avoid matching short words
                            required_spec = spec_value
                            self.logger.debug(
                                f"Derived required specialization '{required_spec}' from agent ID '{agent_id}'"
                            )
                            break
                
                # **ALWAYS check agent specialization - derive from agent ID if routing params don't specify**
                # This ensures we catch mismatches even when routing params don't specify specialization
                agent_id_lower_check = resolved_agent_id.lower()
                
                # Try to derive specialization from agent ID pattern if routing params don't have it
                if not required_spec:
                    from seedcore.agents.roles.specialization import SpecializationManager
                    spec_manager_check = SpecializationManager.get_instance()
                    all_specs_check = spec_manager_check.list_all()
                    for spec_protocol in all_specs_check:
                        spec_value = str(spec_protocol.value).lower() if hasattr(spec_protocol, 'value') else str(spec_protocol).lower()
                        if spec_value in agent_id_lower_check and len(spec_value) > 3:
                            required_spec = spec_value
                            self.logger.debug(
                                f"Using derived specialization '{required_spec}' from agent ID '{agent_id}' for mismatch check"
                            )
                            break
                
                # **CRITICAL: Always check agent specialization if we can derive it from agent ID**
                # This catches agents with wrong specialization even when routing params don't specify it
                # Skip specialization respawn if router explicitly fell back due to RBAC
                if required_spec and not used_fallback and not router_reason.startswith("rbac_soft_fallback"):
                    # Check agent's actual specialization
                    try:
                        agent_info_ref = resolved_organ.get_agent_info.remote(
                            resolved_agent_id
                        )
                        agent_info = await self._ray_await(agent_info_ref)
                        current_spec = (
                            agent_info.get("specialization", "")
                            or agent_info.get("specialization_name", "")
                            or ""
                        ).lower()
                        required_spec_lower = str(required_spec).strip().lower()
                        # Attempt to resolve unknown/aliased specializations to a registered spec
                        resolved_spec = self._resolve_registered_specialization(
                            required_spec_lower, params
                        )
                        if resolved_spec and resolved_spec != required_spec_lower:
                            self.logger.info(
                                f"[OrganismCore] Resolved specialization alias '{required_spec_lower}' -> '{resolved_spec}'"
                            )
                            required_spec_lower = resolved_spec
                        elif not resolved_spec and not is_hard_required:
                            # Soft hint is unregistered; proceed without respawn
                            self.logger.info(
                                f"[OrganismCore] Soft specialization hint '{required_spec_lower}' not registered. "
                                "Skipping respawn and executing with current agent."
                            )
                            required_spec_lower = current_spec or required_spec_lower
                        
                        if current_spec and current_spec != required_spec_lower:
                            self.logger.warning(
                                f"🔧 Agent {resolved_agent_id} has specialization mismatch: "
                                f"current='{current_spec}' != required='{required_spec_lower}'. "
                                f"Respawning with correct specialization..."
                            )
                            
                            # Respawn agent with correct specialization
                            try:
                                from seedcore.agents.roles.specialization import get_specialization
                                spec = get_specialization(required_spec_lower)
                                
                                # Get agent class from info
                                agent_class = agent_info.get("class", "BaseAgent")
                                
                                # **CRITICAL: Force kill Ray actor before respawning**
                                # get_if_exists=True will reuse existing actor, so we must kill it first
                                # Note: ray is imported at module level, so we can use it directly
                                try:
                                    from seedcore.organs.organ import AGENT_NAMESPACE
                                    
                                    # Try to get actor by name and kill it
                                    try:
                                        old_actor = ray.get_actor(resolved_agent_id, namespace=AGENT_NAMESPACE)
                                        ray.kill(old_actor, no_restart=True)
                                        self.logger.info(f"🔪 Force killed Ray actor '{resolved_agent_id}' in namespace '{AGENT_NAMESPACE}'")
                                        # Wait for Ray to clean up the actor
                                        await asyncio.sleep(1.0)
                                    except ValueError:
                                        # Actor doesn't exist, that's fine
                                        self.logger.debug(f"Ray actor '{resolved_agent_id}' doesn't exist, proceeding with respawn")
                                    except Exception as kill_err:
                                        self.logger.warning(f"Failed to kill Ray actor '{resolved_agent_id}': {kill_err}")
                                except Exception as e:
                                    self.logger.warning(f"Error during Ray actor cleanup: {e}")
                                
                                # Remove from organ registry (force kill by name to ensure clean removal)
                                remove_ref = resolved_organ.remove_agent.remote(
                                    resolved_agent_id, force_kill_by_name=True
                                )
                                await self._ray_await(remove_ref)
                                
                                # Additional cleanup: ensure Ray actor is gone
                                try:
                                    from seedcore.organs.organ import AGENT_NAMESPACE
                                    # Double-check and wait for actor to be fully removed
                                    for _ in range(5):  # Check up to 5 times
                                        try:
                                            test_actor = ray.get_actor(resolved_agent_id, namespace=AGENT_NAMESPACE)
                                            # Still exists, kill it again
                                            ray.kill(test_actor, no_restart=True)
                                            await asyncio.sleep(0.3)
                                        except ValueError:
                                            # Actor is gone, good
                                            break
                                except Exception as cleanup_err:
                                    self.logger.debug(f"Cleanup check error (non-fatal): {cleanup_err}")
                                
                                # Respawn with correct specialization
                                agent_opts = self._get_agent_actor_options(resolved_agent_id)
                                # CRITICAL: Use force_replace=True to ensure clean respawn
                                # Also remove get_if_exists to prevent Ray from reusing old actor
                                agent_opts_clean = {k: v for k, v in agent_opts.items() if k != "get_if_exists"}
                                create_ref = resolved_organ.create_agent.remote(
                                    agent_id=resolved_agent_id,
                                    specialization=spec,
                                    organ_id=resolved_organ_id,
                                    agent_class_name=agent_class,
                                    force_replace=True,  # Force replace existing agent
                                    **agent_opts_clean,
                                )
                                await self._ray_await(create_ref)
                                
                                # Update local mapping
                                self.agent_to_organ_map[resolved_agent_id] = resolved_organ_id
                                
                                # Get new handle
                                respawn_resolution = await self._ensure_agent_handle(
                                    resolved_organ,
                                    resolved_organ_id,
                                    resolved_agent_id,
                                    params,
                                )
                                agent_handle = (
                                    respawn_resolution[1] if respawn_resolution else None
                                )
                                
                                if not agent_handle:
                                    return make_envelope(
                                        task_id=task_id,
                                        success=False,
                                        error=f"Agent '{resolved_agent_id}' respawn failed after specialization fix.",
                                        error_type="agent_respawn_failed",
                                        retry=True,
                                        path="organism_core",
                                    )
                                
                                self.logger.info(
                                    f"✅ Successfully respawned agent {resolved_agent_id} with specialization '{required_spec_lower}'"
                                )
                            except Exception as e:
                                self.logger.error(
                                    f"❌ Failed to respawn agent {resolved_agent_id} with correct specialization: {e}",
                                    exc_info=True
                                )
                                return make_envelope(
                                    task_id=task_id,
                                    success=False,
                                    error=f"Agent specialization mismatch detected but respawn failed: {e}",
                                    error_type="agent_specialization_mismatch",
                                    retry=True,
                                    path="organism_core",
                                )
                    except Exception as e:
                        self.logger.debug(
                            f"Could not check agent specialization (non-fatal): {e}"
                        )

            # --- 3. Execution Logic ---
            # Priority: Trust the Router's decision envelope first
            router_meta = params.get("_router", {}) if isinstance(params, dict) else {}
            if not isinstance(router_meta, dict):
                router_meta = {}
            is_high_stakes = router_meta.get("is_high_stakes", False)

            # Legacy fallback: check risk envelope if router meta missing
            if not is_high_stakes:
                is_high_stakes = params.get("risk", {}).get("is_high_stakes", False)

            # Execution Timeout config
            timeout = 300.0 if is_high_stakes else 60.0

            # Select Method & Dispatch
            if is_high_stakes and hasattr(agent_handle, "execute_high_stakes_task"):
                ref = agent_handle.execute_high_stakes_task.remote(task_dict)
            else:
                if is_high_stakes:
                    self.logger.warning(
                        f"[{resolved_agent_id}] High-stakes requested but handler missing. Downgrading."
                    )
                ref = agent_handle.execute_task.remote(task_dict)

            # Await Result (Native Async)
            # We use asyncio.wait_for to enforce timeouts at the Router level
            try:
                result = await asyncio.wait_for(ref, timeout=timeout)
            except asyncio.CancelledError:
                # If cancelled, check if agent is still alive
                self.logger.warning(
                    f"[{resolved_agent_id}] Task execution was cancelled. Agent may be respawning."
                )
                raise  # Re-raise to propagate cancellation

            # --- 4. Tunnel Lifecycle (Side Effect) ---
            # Manage sticky sessions based on the result
            await self._manage_tunnel_lifecycle(task_dict, result, resolved_agent_id)

            # --- 4.5. RBAC -> Cognitive Fallback for Unregistered Specialization ---
            fallback = await self._maybe_cognitive_fallback_on_rbac(
                organ_id=organ_id,
                organ_handle=organ,
                agent_id=agent_id,
                task_id=task_id,
                task_dict=task_dict,
                result=result,
            )
            if fallback:
                return fallback

            # --- 5. Return Standardized Response ---
            # Normalize agent result to canonical envelope if needed
            if isinstance(result, dict) and "success" in result:
                # Agent already returned canonical format, normalize it
                normalized = normalize_envelope(
                    result, task_id=task_id, path="organism_core"
                )
                # Merge organism-specific metadata
                normalized["meta"] = {
                    **normalized.get("meta", {}),
                    "organ_id": resolved_organ_id,
                    "agent_id": resolved_agent_id,
                    "requested_agent_id": requested_agent_id,
                    "requested_organ_id": requested_organ_id,
                }
                return self._post_process_agent_result(
                    normalized, resolved_organ_id, resolved_agent_id
                )
            else:
                # Agent returned legacy format, wrap in canonical envelope
                wrapped = make_envelope(
                    task_id=task_id,
                    success=True,
                    payload=result,
                    meta={
                        "organ_id": resolved_organ_id,
                        "agent_id": resolved_agent_id,
                        "requested_agent_id": requested_agent_id,
                        "requested_organ_id": requested_organ_id,
                    },
                    path="organism_core",
                )
                return self._post_process_agent_result(
                    wrapped, resolved_organ_id, resolved_agent_id
                )

        except asyncio.CancelledError:
            # Task was cancelled - likely due to agent respawning or upstream cancellation
            self.logger.warning(
                f"[Execute] Task execution cancelled for {requested_agent_id}. "
                f"Agent may be respawning or request was cancelled upstream."
            )
            return make_envelope(
                task_id=task_id,
                success=False,
                error=f"Task execution was cancelled. Agent '{requested_agent_id}' may be respawning.",
                error_type="cancelled",
                retry=True,  # Allow retry after agent becomes ready
                meta={
                    "agent_status": "cancelled_or_respawning",
                    "requested_agent_id": requested_agent_id,
                    "resolved_agent_id": resolved_agent_id,
                    "requested_organ_id": requested_organ_id,
                    "resolved_organ_id": resolved_organ_id,
                },
                path="organism_core",
            )
        except asyncio.TimeoutError:
            self.logger.error(f"[Execute] Timeout on {requested_agent_id} after {timeout}s")
            return make_envelope(
                task_id=task_id,
                success=False,
                error="Execution Timed Out",
                error_type="timeout",
                retry=True,
                path="organism_core",
            )

        except Exception as e:
            self.logger.error(
                f"[Execute] Critical failure on {requested_agent_id}: {e}", exc_info=True
            )
            return make_envelope(
                task_id=task_id,
                success=False,
                error=f"Execution Exception: {str(e)}",
                error_type="execution_error",
                retry=True,
                path="organism_core",
            )

    async def _ensure_generalist_fallback_agent(
        self, organ_id: str, organ_handle: Any
    ) -> Optional[str]:
        """
        Ensure a GENERALIST fallback agent exists for the organ.
        Returns agent_id if created or found, otherwise None.
        """
        try:
            existing = self._generalist_fallback_agents.get(organ_id)
            if existing:
                try:
                    handle_ref = organ_handle.get_agent_handle.remote(existing)
                    handle = await self._ray_await(handle_ref, timeout=2.0)
                    if handle:
                        return existing
                except Exception:
                    pass

            fallback_id = f"{organ_id}_generalist_fallback"
            # Avoid duplicate creation if already exists in Ray
            try:
                ray.get_actor(fallback_id, namespace=RAY_NAMESPACE)
                self._generalist_fallback_agents[organ_id] = fallback_id
                return fallback_id
            except ValueError:
                pass

            spec = Specialization.GENERALIST
            agent_opts = self._get_agent_actor_options(fallback_id)
            await organ_handle.create_agent.remote(
                agent_id=fallback_id,
                specialization=spec,
                organ_id=organ_id,
                agent_class_name="BaseAgent",
                **agent_opts,
            )
            self.agent_to_organ_map[fallback_id] = organ_id
            self._agent_creation_times[fallback_id] = asyncio.get_running_loop().time()
            self._generalist_fallback_agents[organ_id] = fallback_id
            return fallback_id
        except Exception as e:
            self.logger.warning(
                f"[{organ_id}] Failed to ensure GENERALIST fallback agent: {e}"
            )
            return None

    async def _find_existing_fallback_handle(self) -> Optional[tuple[str, Any, str]]:
        """
        Try to reuse an existing GENERALIST or USER_LIAISON agent handle.
        Preference order:
        1) utility_organ (generalist)
        2) user_experience_organ (user_liaison)
        3) any organ with a GENERALIST or USER_LIAISON
        """
        preferred_organs = []
        if "utility_organ" in self.organs:
            preferred_organs.append("utility_organ")
        if "user_experience_organ" in self.organs:
            preferred_organs.append("user_experience_organ")

        # Build ordered organ list
        seen = set(preferred_organs)
        ordered_organs = list(preferred_organs) + [
            oid for oid in self.organs.keys() if oid not in seen
        ]

        # Try GENERALIST first, then USER_LIAISON
        candidates = [
            Specialization.GENERALIST.value,
            Specialization.USER_LIAISON.value,
        ]

        for organ_id in ordered_organs:
            organ_handle = self.organs.get(organ_id)
            if not organ_handle:
                continue
            for spec_val in candidates:
                try:
                    ref = organ_handle.pick_agent_by_specialization.remote(
                        spec_val, {}
                    )
                    res = await self._ray_await(ref, timeout=2.0)
                    if isinstance(res, tuple) and len(res) == 2:
                        agent_id, handle = res
                        if handle:
                            self.logger.info(
                                f"[OrganismCore] Reusing existing fallback agent for '{spec_val}' in '{organ_id}'"
                            )
                            return agent_id, handle, organ_id
                except Exception:
                    continue

        return None

    async def _cognitive_fallback_for_unregistered_spec(
        self,
        *,
        organ_id: str,
        organ_handle: Any,
        agent_id: str,
        task_id: str,
        required_spec: str,
        task_dict: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Use a GENERALIST fallback agent to call cognitive service and craft
        a user-facing guidance message when specialization is unregistered.
        """
        fallback_agent_id = await self._ensure_generalist_fallback_agent(
            organ_id, organ_handle
        )
        if not self.cognitive_client:
            return make_envelope(
                task_id=task_id,
                success=False,
                error=(
                    f"Specialization '{required_spec}' is not registered and cognitive "
                    "fallback is unavailable."
                ),
                error_type="specialization_unregistered",
                retry=False,
                meta={
                    "organ_id": organ_id,
                    "agent_id": agent_id,
                    "required_specialization": required_spec,
                },
                path="organism_core",
            )

        try:
            cog_task = dict(task_dict or {})
            cog_params = cog_task.get("params", {}) or {}
            cog_params.setdefault("cognitive", {})
            cog_params["cognitive"].update(
                {
                    "decision_kind": DecisionKind.COGNITIVE.value,
                    "note": "fallback_for_unregistered_specialization",
                }
            )
            cog_task["params"] = cog_params
            cog_task.setdefault(
                "description",
                f"Provide guidance: specialization '{required_spec}' is not registered. "
                "Suggest next steps or alternatives.",
            )

            response = await self.cognitive_client.execute_async(
                agent_id=fallback_agent_id or agent_id,
                cog_type="problem_solving",
                decision_kind=DecisionKind.COGNITIVE,
                task=cog_task,
            )

            return make_envelope(
                task_id=task_id,
                success=False,
                payload={
                    "owner_message": response,
                    "reason": "specialization_unregistered",
                    "required_specialization": required_spec,
                },
                error=(
                    f"Specialization '{required_spec}' is not registered. "
                    "Provided guidance via cognitive fallback."
                ),
                error_type="specialization_unregistered",
                retry=False,
                meta={
                    "organ_id": organ_id,
                    "agent_id": agent_id,
                    "fallback_agent_id": fallback_agent_id,
                    "required_specialization": required_spec,
                },
                path="organism_core",
            )
        except Exception as e:
            self.logger.warning(
                f"[{organ_id}] Cognitive fallback failed for '{required_spec}': {e}",
                exc_info=True,
            )
            return make_envelope(
                task_id=task_id,
                success=False,
                error=(
                    f"Specialization '{required_spec}' is not registered and cognitive "
                    f"fallback failed: {e}"
                ),
                error_type="specialization_unregistered",
                retry=False,
                meta={
                    "organ_id": organ_id,
                    "agent_id": agent_id,
                    "required_specialization": required_spec,
                },
                path="organism_core",
            )

    async def _cognitive_fallback_for_rbac_denied(
        self,
        *,
        organ_id: str,
        organ_handle: Any,
        agent_id: str,
        task_id: str,
        spec_hint: Optional[str],
        tools: Optional[List[str]],
        task_dict: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Provide user-facing guidance when RBAC/tool access blocks execution.
        This avoids respawning agents and returns a cognitive suggestion message.
        """
        tools = tools or []
        if not self.cognitive_client:
            return make_envelope(
                task_id=task_id,
                success=False,
                error=(
                    "Tool access denied for this specialization and cognitive fallback is unavailable. "
                    "Please update allowed_tools or route to a qualified agent."
                ),
                error_type="rbac_denied",
                retry=False,
                meta={
                    "organ_id": organ_id,
                    "agent_id": agent_id,
                    "specialization": spec_hint,
                    "tools": tools,
                },
                path="organism_core",
            )

        try:
            fallback_agent_id = None
            existing_fallback = await self._find_existing_fallback_handle()
            if existing_fallback:
                fallback_agent_id = existing_fallback[0]
            if not fallback_agent_id:
                fallback_agent_id = await self._ensure_generalist_fallback_agent(
                    organ_id, organ_handle
                )

            cog_task = dict(task_dict or {})
            cog_params = cog_task.get("params", {}) or {}
            cog_params.setdefault("cognitive", {})
            cog_params["cognitive"].update(
                {
                    "decision_kind": DecisionKind.COGNITIVE.value,
                    "note": "fallback_for_rbac_denied",
                }
            )
            cog_task["params"] = cog_params
            cog_task.setdefault(
                "description",
                "Provide guidance: requested tools are not permitted for the current specialization. "
                "Suggest next steps or alternatives (e.g., update allowed_tools or route to a qualified agent).",
            )

            response = await self.cognitive_client.execute_async(
                agent_id=fallback_agent_id or agent_id,
                cog_type="problem_solving",
                decision_kind=DecisionKind.COGNITIVE,
                task=cog_task,
            )

            return make_envelope(
                task_id=task_id,
                success=False,
                payload={
                    "owner_message": response,
                    "reason": "rbac_denied",
                    "specialization": spec_hint,
                    "tools": tools,
                },
                error=(
                    "Tool access denied for this specialization. "
                    "Provided guidance via cognitive fallback."
                ),
                error_type="rbac_denied",
                retry=False,
                meta={
                    "organ_id": organ_id,
                    "agent_id": agent_id,
                    "fallback_agent_id": fallback_agent_id,
                    "specialization": spec_hint,
                    "tools": tools,
                },
                path="organism_core",
            )
        except Exception as e:
            self.logger.warning(
                f"[{organ_id}] Cognitive fallback failed for RBAC denial: {e}",
                exc_info=True,
            )
            return make_envelope(
                task_id=task_id,
                success=False,
                error=(
                    "Tool access denied for this specialization and cognitive fallback failed. "
                    f"Reason: {e}"
                ),
                error_type="rbac_denied",
                retry=False,
                meta={
                    "organ_id": organ_id,
                    "agent_id": agent_id,
                    "specialization": spec_hint,
                    "tools": tools,
                },
                path="organism_core",
            )

    async def _maybe_cognitive_fallback_on_rbac(
        self,
        *,
        organ_id: str,
        organ_handle: Any,
        agent_id: str,
        task_id: str,
        task_dict: Dict[str, Any],
        result: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        If RBAC denied AND the specialization is unregistered, call cognitive fallback
        to provide advice/next steps. Returns an envelope or None.
        """
        try:
            if not isinstance(result, dict):
                return None

            payload = result.get("payload") or {}
            errors = payload.get("errors") or []
            if not isinstance(errors, list) or not errors:
                return None

            def _is_rbac_error(err: Dict[str, Any]) -> bool:
                if not isinstance(err, dict):
                    return False
                msg = str(err.get("error") or "").lower()
                return "rbac_denied" in msg or "permission" in msg

            if not any(_is_rbac_error(e) for e in errors):
                return None

            params = task_dict.get("params", {}) if isinstance(task_dict, dict) else {}
            if not isinstance(params, dict):
                params = {}

            # Avoid infinite fallback loops
            cognitive_note = (
                params.get("cognitive", {}).get("note")
                if isinstance(params.get("cognitive"), dict)
                else None
            )
            if cognitive_note == "fallback_for_unregistered_specialization":
                return None

            routing = params.get("routing", {}) if isinstance(params, dict) else {}
            if not isinstance(routing, dict):
                routing = {}

            required_spec = (
                routing.get("required_specialization") or routing.get("specialization")
            )
            if not required_spec:
                return None

            resolved = self._resolve_registered_specialization(
                str(required_spec).strip().lower(), params
            )
            if resolved:
                return None

            return await self._cognitive_fallback_for_unregistered_spec(
                organ_id=organ_id,
                organ_handle=organ_handle,
                agent_id=agent_id,
                task_id=task_id,
                required_spec=str(required_spec),
                task_dict=task_dict,
            )
        except Exception as e:
            self.logger.debug(
                f"[{organ_id}] RBAC cognitive fallback check failed (non-fatal): {e}"
            )
            return None

    def _post_process_agent_result(
        self, envelope: Dict[str, Any], organ_id: str, agent_id: str
    ) -> Dict[str, Any]:
        """
        Gracefully handle RBAC/tool-denial outcomes to avoid noisy retries.
        This keeps routing explicit but prevents repeated failures when tools/skills
        are missing for the current specialization.
        """
        try:
            if not isinstance(envelope, dict):
                return envelope

            payload = envelope.get("payload") or {}
            errors = payload.get("errors") or []
            if not isinstance(errors, list):
                return envelope

            # Detect RBAC/tool denial patterns
            def _is_rbac_error(err: Dict[str, Any]) -> bool:
                if not isinstance(err, dict):
                    return False
                msg = str(err.get("error") or "").lower()
                return "rbac_denied" in msg or "permission" in msg

            has_rbac = any(_is_rbac_error(e) for e in errors)
            if not has_rbac:
                return envelope

            # Graceful, non-retryable completion
            envelope["success"] = False
            envelope["retry"] = False
            envelope["error_type"] = "rbac_denied"
            envelope["error"] = (
                "Tool access denied for this specialization. "
                "Please update allowed_tools or route to a qualified agent."
            )
            meta = envelope.get("meta", {}) or {}
            meta.setdefault("organ_id", organ_id)
            meta.setdefault("agent_id", agent_id)
            meta["policy_hint"] = "update_role_profile_allowed_tools_or_reroute"
            envelope["meta"] = meta
            return envelope
        except Exception:
            return envelope

    # =========================================================
    # 🔧 HELPER: JIT PROVISIONING
    # =========================================================
    async def _ensure_agent_handle(
        self, organ: Any, organ_id: str, agent_id: str, params: dict
    ) -> Optional[tuple[str, Any, str]]:
        """
        Tries to fetch an agent handle. If missing, attempts JIT spawn.

        Behavior Plugin System: Extracts agent_class, behaviors, and behavior_config
        from params.executor if present (from pkg_subtask_types.default_params.executor).
        """
        # 1. Optimistic Fetch (Fast Path)
        handle = await organ.get_agent_handle.remote(agent_id)
        if handle:
            return agent_id, handle, organ_id

        # 1.5. Check if an agent with the required specialization already exists
        # This prevents spawning duplicate agents when a new unique ID is generated
        # but an agent with the same specialization already exists
        routing = params.get("routing", {})
        executor = params.get("executor", {})
        required_spec = (
            routing.get("required_specialization")
            or routing.get("specialization")
            or (executor.get("specialization") if isinstance(executor, dict) else None)
        )
        
        if required_spec:
            # If specialization is unregistered, reuse an existing fallback agent
            resolved_spec = self._resolve_registered_specialization(
                str(required_spec).strip().lower(), params
            )
            if not resolved_spec:
                fallback_handle = await self._find_existing_fallback_handle()
                if fallback_handle:
                    fallback_agent_id, fallback_handle_obj, fallback_organ_id = fallback_handle
                    self.logger.info(
                        f"[{organ_id}] Specialization '{required_spec}' unregistered. "
                        "Reusing existing fallback agent handle (no JIT spawn)."
                    )
                    return fallback_agent_id, fallback_handle_obj, fallback_organ_id

            # Check if any agent with this specialization already exists
            try:
                existing_agent_ref = organ.pick_agent_by_specialization.remote(
                    required_spec, {}
                )
                existing_agent_result = await self._ray_await(existing_agent_ref, timeout=2.0)
                if existing_agent_result and isinstance(existing_agent_result, tuple):
                    existing_agent_id, existing_handle = existing_agent_result
                    if existing_agent_id and existing_handle:
                        self.logger.info(
                            f"[{organ_id}] Found existing agent {existing_agent_id} with specialization '{required_spec}'. "
                            f"Reusing instead of spawning new agent {agent_id}."
                        )
                        return existing_agent_id, existing_handle, organ_id
            except Exception as e:
                self.logger.debug(
                    f"[{organ_id}] Could not check for existing agents with specialization '{required_spec}': {e}. "
                    f"Proceeding with JIT spawn."
                )

        # 2. Not Found - Start JIT Sequence
        self.logger.info(
            f"[{organ_id}] Agent {agent_id} missing. Initiating JIT spawn with specialization '{required_spec or 'GENERALIST'}'."
        )

        # Determine Specialization for the new agent
        # Priority: routing.required_specialization > routing.specialization > executor.specialization > GENERALIST
        # **CRITICAL: executor.specialization must be checked as fallback to ensure agents use correct specialization**
        routing = params.get("routing", {})
        executor = params.get("executor", {})
        
        spec_str = (
            routing.get("required_specialization")
            or routing.get("specialization")
            or (executor.get("specialization") if isinstance(executor, dict) else None)
            or "GENERALIST"
        )

        # Extract executor config from executor hints (Behavior Plugin System + agent class)
        jit_behaviors = (
            executor.get("behaviors") if isinstance(executor, dict) else None
        )
        jit_behavior_config = (
            executor.get("behavior_config") if isinstance(executor, dict) else None
        )
        jit_agent_class = (
            executor.get("agent_class") if isinstance(executor, dict) else None
        )

        # Spawn via Organ Actor
        spawn_success = await self._jit_spawn_agent(
            organ,
            organ_id,
            agent_id,
            spec_str,
            agent_class_name=jit_agent_class,
            behaviors=jit_behaviors,
            behavior_config=jit_behavior_config,
        )

        if spawn_success:
            # 3. Retry Fetch
            new_handle = await organ.get_agent_handle.remote(agent_id)
            if new_handle:
                return agent_id, new_handle, organ_id

        return None

    async def _jit_spawn_agent(
        self,
        organ: Any,
        organ_id: str,
        agent_id: str,
        spec_str: str,
        agent_class_name: Optional[str] = None,
        behaviors: Optional[List[str]] = None,
        behavior_config: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> bool:
        """
        JIT (Just-In-Time) spawn an agent when it's missing during execution.

        This is called when an agent is requested but doesn't exist yet.
        It creates the agent on-demand with the specified specialization.

        Behavior Plugin System: Accepts behaviors and agent_class from executor hints in task params.

        Args:
            organ: Ray actor handle for the Organ
            organ_id: ID of the organ
            agent_id: ID of the agent to spawn
            spec_str: Specialization string (e.g., "user_liaison", "GENERALIST")
            agent_class_name: Optional agent class name from executor hints (defaults to "BaseAgent")
            behaviors: Optional list of behavior names from executor hints
            behavior_config: Optional behavior config dict from executor hints

        Returns:
            True if spawn succeeded, False otherwise
        """
        try:
            # Resolve specialization (supports both static and dynamic)
            try:
                spec = get_specialization(spec_str)
            except KeyError:
                # Fallback to GENERALIST if unknown specialization
                self.logger.warning(
                    f"[{organ_id}] Unknown specialization '{spec_str}', "
                    "defaulting to GENERALIST for JIT spawn"
                )
                spec = Specialization.GENERALIST

            # Get agent class name from executor hints (graceful fallback to BaseAgent)
            # This allows pkg_subtask_types to specify custom agent classes via executor.agent_class
            agent_class_name = agent_class_name or "BaseAgent"

            # Get configuration-driven agent actor options
            agent_opts = self._get_agent_actor_options(agent_id)

            # Spawn agent via Organ actor (with behaviors from executor hints)
            await organ.create_agent.remote(
                agent_id=agent_id,
                specialization=spec,
                organ_id=organ_id,
                agent_class_name=agent_class_name,
                behaviors=behaviors,  # Pass behaviors from executor hints
                behavior_config=behavior_config,  # Pass behavior config from executor hints
                **agent_opts,
            )

            # Update local mapping
            self.agent_to_organ_map[agent_id] = organ_id
            # Track JIT spawn time for grace period
            self._agent_creation_times[agent_id] = asyncio.get_running_loop().time()

            self.logger.info(
                f"[{organ_id}] ✅ JIT spawned agent {agent_id} with specialization {spec.value} "
                f"(class: {agent_class_name})"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"[{organ_id}] ❌ Failed to JIT spawn agent {agent_id}: {e}",
                exc_info=True,
            )
            return False

    # =========================================================
    # 🔧 HELPER: TUNNEL MANAGEMENT
    # =========================================================
    async def _manage_tunnel_lifecycle(
        self, task_in: dict, result_out: Any, agent_id: str
    ):
        """
        Analyzes execution result to Create, Refresh, or Destroy sticky tunnels.
        """
        conversation_id = task_in.get("conversation_id")
        if not conversation_id or not isinstance(result_out, dict):
            return

        try:
            # 1. Check Policy
            should_stick = self.tunnel_policy.should_activate(result_out)

            if should_stick:
                # 2. Bind/Refresh Tunnel
                await self.tunnel_manager.assign(conversation_id, agent_id)

                # Tag result for UI visibility
                meta = result_out.setdefault("metadata", {})
                meta["tunnel_active"] = True
                meta["assigned_agent"] = agent_id
            else:
                # 3. Check for Termination
                status = result_out.get("status")
                if status in self.tunnel_policy.terminal_statuses:
                    await self.tunnel_manager.release(conversation_id)

        except Exception as e:
            # Non-blocking warning
            self.logger.warning(f"[Tunnel] Lifecycle error for {conversation_id}: {e}")

    # =====================================================================
    #  TUNNEL MANAGEMENT
    # =====================================================================

    async def ensure_tunnel(
        self, conversation_id: str, agent_id: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Ensure a persistent tunnel exists for a conversation with an agent.

        If a tunnel already exists for this conversation and agent, updates the
        last_active timestamp and returns the existing tunnel. Otherwise, creates
        a new tunnel entry in the registry.

        Args:
            conversation_id: Unique identifier for the conversation
            agent_id: ID of the agent handling the conversation
            context: Context dictionary containing conversation context (text/message)

        Returns:
            Dict containing tunnel metadata including conversation_id, agent_id,
            created_at, last_active, and context_snapshot
        """
        if conversation_id in self.tunnel_registry:
            existing = self.tunnel_registry[conversation_id]
            if existing["agent_id"] == agent_id:
                existing["last_active"] = time.time()
                return existing

        tunnel = {
            "conversation_id": conversation_id,
            "agent_id": agent_id,
            "created_at": time.time(),
            "last_active": time.time(),
            "context_snapshot": context.get("text") or context.get("message"),
        }
        self.tunnel_registry[conversation_id] = tunnel
        logger.info(
            f"[Organism] 🚇 Tunnel Established: {conversation_id} -> {agent_id}"
        )
        return tunnel

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
                logger.info(
                    f"[get_all_agents] Failed to get agents from organ {organ_id}: {e}"
                )
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
                logger.info(
                    f"[get_all_agent_skills] Failed to get skills for {agent_id}: {e}"
                )
                skills[agent_id] = None
        return skills

    def get_specialization_map(self) -> Dict[str, str]:
        """
        Get specialization -> organ_id mapping.

        Returns:
            Dict mapping specialization value -> organ_id
        """
        return {
            spec.value if hasattr(spec, "value") else str(spec): organ_id
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

    # =====================================================================
    #  CAPABILITY CHANGE MANAGEMENT (PKG Integration)
    # =====================================================================

    async def handle_capability_changes(
        self,
        changes: List[Dict[str, Any]],
        active_snapshot_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Handle capability change notifications from CapabilityMonitor.

        **PRIORITY: Dynamic updates from pkg_subtask_types override static YAML configs.**

        This processes changes to pkg_subtask_types and updates role profiles
        for affected agents. Implements selective broadcasting and snapshot validation.

        When a capability is updated, this method:
        1. Rebuilds the role profile from the capability data (pkg_subtask_types)
        2. Registers it with SpecializationManager (overriding any static YAML profile)
        3. Broadcasts the update to relevant organs/agents

        Args:
            changes: List of change dictionaries with:
                - capability_name: str
                - change_type: str ("added", "updated", "removed")
                - specialization: Optional[str]
                - snapshot_id: int (for version consistency validation)
                - new_capability: Optional[Dict] - Full capability data from pkg_subtask_types
            active_snapshot_id: Optional active snapshot ID for validation.
                              If None, will be fetched from PKG.

        Returns:
            Dict with success status and processing details
        """
        try:
            from seedcore.agents.roles.specialization import SpecializationManager
            from seedcore.ops.pkg.client import PKGClient
            from seedcore.database import get_async_pg_session_factory

            # Validate snapshot consistency if not provided
            if active_snapshot_id is None:
                session_factory = get_async_pg_session_factory()
                pkg_client = PKGClient(session_factory)
                active_snapshot = await pkg_client.get_active_snapshot()

                if not active_snapshot:
                    self.logger.warning(
                        "No active PKG snapshot found, rejecting capability changes"
                    )
                    return {
                        "success": False,
                        "error": "No active PKG snapshot found",
                        "rejected_changes": len(changes),
                    }

                active_snapshot_id = active_snapshot.id

            processed = {
                "added": 0,
                "updated": 0,
                "removed": 0,
                "rejected": 0,
                "errors": [],
            }

            spec_manager = SpecializationManager.get_instance()
            
            # Track which specializations were registered so we can sync them all at once at the end
            registered_specializations = []
            
            self.logger.info(
                f"📋 Processing {len(changes)} capability changes: "
                f"{sum(1 for c in changes if c.get('change_type') == 'added')} added, "
                f"{sum(1 for c in changes if c.get('change_type') == 'updated')} updated, "
                f"{sum(1 for c in changes if c.get('change_type') == 'removed')} removed"
            )

            for idx, change in enumerate(changes):
                try:
                    change_type = change.get("change_type")
                    spec_str = change.get("specialization")
                    snapshot_id = change.get("snapshot_id")
                    capability_name = change.get("capability_name", "unknown")
                    new_capability = change.get("new_capability")  # Full capability data
                    
                    self.logger.debug(
                        f"Processing capability change {idx+1}/{len(changes)}: {change_type} '{capability_name}' "
                        f"(specialization: '{spec_str}', snapshot_id: {snapshot_id})"
                    )

                    # Version consistency check (Snapshot Locking)
                    if snapshot_id is not None and snapshot_id != active_snapshot_id:
                        self.logger.warning(
                            f"⚠️ Rejecting capability change for '{capability_name}': "
                            f"snapshot_id mismatch (change: {snapshot_id}, active: {active_snapshot_id}). "
                            "This prevents logic drift from mixing DNA from different versions."
                        )
                        processed["rejected"] += 1
                        continue

                    # If specialization not provided, try to derive from capability name
                    if not spec_str:
                        # Derive specialization from capability name (e.g., "monitor_zone_safety" -> "monitor_zone_safety")
                        spec_str = capability_name.lower()
                        self.logger.debug(
                            f"No specialization provided for '{capability_name}', "
                            f"deriving from capability name: '{spec_str}'"
                        )

                    spec_str = str(spec_str).strip().lower()
                    if not spec_str:
                        self.logger.warning(
                            f"Could not determine specialization for capability '{capability_name}', skipping"
                        )
                        processed["rejected"] += 1
                        continue
                    if change_type == "added":
                        # New capability - register/update role profile from capability data
                        # This ensures dynamic pkg_subtask_types data overrides static YAML
                        role_profile = self._build_role_profile_from_capability(
                            spec_str, capability_name, new_capability
                        )

                        # **CRITICAL: Register the specialization FIRST before registering role profile**
                        # This ensures get_specialization() can find it when agents are spawned
                        # We MUST register even if role_profile is None, because agents need the specialization
                        specialization_registered = False
                        if spec_str and not spec_manager.is_registered(spec_str):
                            try:
                                # Extract metadata from capability if available
                                metadata = {
                                    "source": "pkg_subtask_types",
                                    "capability_name": capability_name,
                                    "snapshot_id": snapshot_id,
                                }
                                
                                # Register the specialization dynamically (this adds it to _dynamic_specs)
                                # Pass role_profile if available, otherwise None (will create minimal profile)
                                spec_manager.register_dynamic(
                                    value=spec_str,
                                    name=capability_name.replace("_", " ").title(),
                                    metadata=metadata,
                                    role_profile=role_profile,  # Pass role_profile if available
                                )
                                specialization_registered = True
                                self.logger.info(
                                    f"✅ Registered dynamic specialization '{spec_str}' from capability '{capability_name}'"
                                )
                            except Exception as e:
                                self.logger.error(
                                    f"❌ Failed to register dynamic specialization '{spec_str}': {e}",
                                    exc_info=True
                                )
                                processed["errors"].append(
                                    f"Failed to register specialization '{spec_str}' for capability '{capability_name}': {e}"
                                )
                                # Don't continue - specialization registration is critical for agent spawning
                                continue
                        elif spec_str and spec_manager.is_registered(spec_str):
                            # Already registered (maybe by CapabilityMonitor), but we still need to sync
                            specialization_registered = True
                            self.logger.info(
                                f"✅ Specialization '{spec_str}' already registered (from capability '{capability_name}'), "
                                f"ensuring role profile is synced"
                            )
                        
                        if role_profile:
                            # Register/update role profile in SpecializationManager (overrides static YAML config)
                            # This is safe to call even if specialization was already registered above
                            spec_manager.register_role_profile(role_profile)
                            
                            # **CRITICAL: Also register in RoleRegistry so it can be synced to organs**
                            # RoleRegistry is what _sync_role_registry_to_organs uses
                            self.role_registry.register(role_profile)
                            
                            self.logger.info(
                                f"✅ Registered role profile for '{spec_str}' from pkg_subtask_types "
                                f"(overrides static YAML config if present)"
                            )
                        
                        # **CRITICAL: Always sync if specialization is registered (even if no role_profile)**
                        # This ensures organs can find the specialization for agent spawning
                        if specialization_registered or spec_manager.is_registered(spec_str):
                            if not role_profile:
                                # Even if no role_profile, ensure specialization is synced to organs
                                # Get the registered specialization to create a minimal profile for RoleRegistry
                                try:
                                    registered_spec = spec_manager.get(spec_str)
                                    # Create minimal role profile for RoleRegistry sync
                                    from seedcore.agents.roles.specialization import RoleProfile
                                    minimal_profile = RoleProfile(
                                        name=registered_spec,
                                        default_skills={},
                                        allowed_tools=set(),
                                        routing_tags=set(),
                                    )
                                    self.role_registry.register(minimal_profile)
                                    self.logger.debug(
                                        f"✅ Created minimal role profile for '{spec_str}' "
                                        f"(no role profile data in capability)"
                                    )
                                except Exception as e:
                                    self.logger.warning(
                                        f"⚠️ Failed to create minimal profile for '{spec_str}': {e}"
                                    )
                            
                            # NOTE: We skip per-capability sync here to avoid blocking the loop.
                            # All specializations will be synced once at the end after processing all changes.
                            # This ensures faster batch processing and avoids potential blocking issues.

                        # **CRITICAL: Update organ_specs mapping for router lookup**
                        # This ensures the router can find which organ handles this specialization
                        # Inference is based on pkg_subtask_types name patterns, not hardcoded mappings
                        if spec_str:
                            organ_id = self._determine_organ_for_specialization(
                                spec_str, capability_name, new_capability
                            )
                            if organ_id:
                                self.organ_specs[spec_str] = organ_id
                                self.logger.info(
                                    f"📌 Mapped specialization '{spec_str}' -> organ '{organ_id}' "
                                    f"for router lookup (inferred from capability name: '{capability_name}')"
                                )
                            else:
                                self.logger.warning(
                                    f"⚠️ Could not determine organ for specialization '{spec_str}' "
                                    f"(capability: '{capability_name}'). Router will use fallback routing."
                                )

                        processed["added"] += 1
                        registered_specializations.append(spec_str)
                        self.logger.info(
                            f"➕ Capability '{capability_name}' added "
                            f"with specialization '{spec_str}'. Agents will spawn on-demand. "
                            f"(Processed {processed['added']}/{len([c for c in changes if c.get('change_type') == 'added'])} added capabilities)"
                        )

                    elif change_type == "updated":
                        # Updated capability - rebuild role profile from capability data and override static config
                        # **PRIORITY: pkg_subtask_types data takes precedence over static YAML**
                        role_profile = self._build_role_profile_from_capability(
                            spec_str, capability_name, new_capability
                        )

                        if not role_profile:
                            self.logger.debug(
                                f"Could not build role profile for '{spec_str}' from capability data, "
                                "trying to get existing profile"
                            )
                            # Fallback: try to get existing profile
                            role_profile = spec_manager.get_role_profile(spec_str)

                        if role_profile:
                            # **CRITICAL: Check if permissions (allowed_tools) changed**
                            # If tools changed, we need to evict live agents to force reload
                            old_profile = spec_manager.get_role_profile(spec_str)
                            tools_changed = False
                            if old_profile:
                                old_tools = old_profile.allowed_tools if hasattr(old_profile, 'allowed_tools') else set()
                                new_tools = role_profile.allowed_tools if hasattr(role_profile, 'allowed_tools') else set()
                                tools_changed = old_tools != new_tools
                                
                                if tools_changed:
                                    self.logger.info(
                                        f"🔧 Permissions changed for '{spec_str}': "
                                        f"old_tools={sorted(old_tools)}, new_tools={sorted(new_tools)}. "
                                        f"Evicting live agents to force reload."
                                    )
                                    # Evict agents with this specialization to force respawn with new permissions
                                    await self.evict_agents_by_specialization(spec_str)
                            
                            # **CRITICAL: Register the rebuilt profile to override static YAML config**
                            # This ensures pkg_subtask_types is the source of truth
                            spec_manager.register_role_profile(role_profile)
                            self.logger.info(
                                f"🔄 Updated role profile for '{spec_str}' from pkg_subtask_types "
                                f"(overrides static YAML config)"
                            )

                            # Selective Broadcasting: Only notify organs with agents matching this specialization
                            target_organs = await self.find_organs_with_specialization(
                                spec_str
                            )

                            # **CRITICAL FIX: Check for agents with mismatched specializations**
                            # Agents may have been spawned before the specialization was registered,
                            # causing them to default to GENERALIST. We need to respawn them.
                            await self._fix_mismatched_agent_specializations(spec_str, capability_name)

                            if not target_organs:
                                self.logger.debug(
                                    f"No organs found with specialization '{spec_str}', "
                                    "role profile updated but no agents to notify"
                                )
                            else:
                                self.logger.info(
                                    f"📢 Broadcasting updated role profile for '{spec_str}' "
                                    f"to {len(target_organs)} organ(s): {', '.join(target_organs)}"
                                )

                                # Broadcast only to relevant organs
                                for organ_id in target_organs:
                                    organ_handle = self.organs.get(organ_id)
                                    if not organ_handle:
                                        self.logger.warning(
                                            f"Organ {organ_id} not found, skipping update"
                                        )
                                        continue

                                    try:
                                        await organ_handle.update_role_registry.remote(
                                            role_profile
                                        )
                                        self.logger.debug(
                                            f"✅ Updated role profile for '{spec_str}' in organ {organ_id}"
                                        )
                                    except Exception as e:
                                        self.logger.warning(
                                            f"Failed to update role registry in organ {organ_id}: {e}"
                                        )
                            processed["updated"] += 1
                        else:
                            self.logger.debug(
                                f"Role profile not found for '{spec_str}', skipping update. "
                                "Capability may not have executor/routing hints."
                            )

                    elif change_type == "removed":
                        # Removed capability - log suggestion
                        self.logger.info(
                            f"➖ Capability '{capability_name}' removed "
                            f"with specialization '{spec_str}'. "
                            "Consider scaling down agents if no longer needed."
                        )
                        processed["removed"] += 1

                except Exception as e:
                    error_msg = f"Error processing change {idx+1}/{len(changes)} for '{capability_name}': {e}"
                    self.logger.error(
                        f"{error_msg} (continuing with remaining {len(changes) - idx - 1} changes)",
                        exc_info=True
                    )
                    processed["errors"].append(error_msg)
                    # Continue processing remaining changes - don't let one failure stop the batch
                    continue
            
            # Log summary of processing
            self.logger.info(
                f"📊 Capability processing summary: "
                f"{processed['added']} added, {processed['updated']} updated, "
                f"{processed['removed']} removed, {processed['rejected']} rejected, "
                f"{len(processed['errors'])} errors, "
                f"{len(registered_specializations)} specializations registered"
            )
            
            # **CRITICAL: Final sync of all role profiles to all organs after processing all changes**
            # This ensures all newly registered specializations are available to organs
            # even if individual syncs failed or were skipped
            if registered_specializations:
                try:
                    self.logger.info(
                        f"🔄 Performing final sync of {len(registered_specializations)} "
                        f"specialization(s) to all organs: {', '.join(registered_specializations)}"
                    )
                    await self._sync_role_registry_to_organs()
                    self.logger.info("✅ Final role registry sync completed")
                except Exception as e:
                    self.logger.warning(
                        f"⚠️ Final role registry sync failed: {e}",
                        exc_info=True
                    )

            return {
                "success": True,
                "processed": processed,
                "total_changes": len(changes),
                "active_snapshot_id": active_snapshot_id,
                "registered_specializations": registered_specializations,
            }

        except Exception as e:
            self.logger.error(
                f"Failed to process capability changes: {e}", exc_info=True
            )
            return {"success": False, "error": str(e)}

    async def _fix_mismatched_agent_specializations(
        self, spec_str: str, capability_name: str
    ) -> None:
        """
        Fix agents that have mismatched specializations.
        
        This detects agents whose names suggest they should have a specific specialization
        (e.g., agent_id contains the specialization name) but currently have a different
        specialization (typically GENERALIST due to being spawned before the specialization
        was registered).
        
        Args:
            spec_str: Expected specialization (normalized, lowercase)
            capability_name: Capability name for logging
        """
        try:
            from seedcore.agents.roles.specialization import get_specialization, Specialization
            
            # Verify the specialization is now registered
            try:
                spec = get_specialization(spec_str)
            except KeyError:
                self.logger.debug(
                    f"Specialization '{spec_str}' not yet registered, skipping mismatch check"
                )
                return
            
            # Check all organs for agents with mismatched specializations
            # Look for agents whose IDs contain the specialization name but have wrong spec
            spec_normalized = spec_str.lower()
            mismatched_agents = []
            
            for organ_id, organ_handle in self.organs.items():
                try:
                    # List all agents in the organ
                    agent_ids_ref = organ_handle.list_agents.remote()
                    agent_ids = await self._ray_await(agent_ids_ref)
                    
                    for agent_id in agent_ids:
                        # Check if agent ID suggests it should have this specialization
                        # Pattern: agent IDs often contain specialization name (e.g., "physical_actuation_organ_reachy_actuator_0")
                        agent_id_lower = agent_id.lower()
                        if spec_normalized in agent_id_lower or capability_name.lower() in agent_id_lower:
                            # Get agent info to check current specialization
                            agent_info_ref = organ_handle.get_agent_info.remote(agent_id)
                            agent_info = await self._ray_await(agent_info_ref)
                            
                            current_spec = (
                                agent_info.get("specialization", "")
                                or agent_info.get("specialization_name", "")
                                or ""
                            ).lower()
                            
                            # If agent has wrong specialization, mark for respawn
                            if current_spec and current_spec != spec_normalized:
                                mismatched_agents.append((organ_id, organ_handle, agent_id, current_spec))
                                self.logger.warning(
                                    f"🔧 Detected agent {agent_id} with mismatched specialization: "
                                    f"current='{current_spec}' != expected='{spec_normalized}'. "
                                    f"Will respawn with correct specialization."
                                )
                except Exception as e:
                    self.logger.debug(
                        f"Error checking organ {organ_id} for mismatched agents: {e}"
                    )
            
            # Respawn agents with correct specialization
            for organ_id, organ_handle, agent_id, old_spec in mismatched_agents:
                try:
                    self.logger.info(
                        f"🔄 Respawning agent {agent_id} from '{old_spec}' to '{spec_normalized}' "
                        f"in organ {organ_id}"
                    )
                    
                    # Get agent info BEFORE removing (so we can preserve agent class, etc.)
                    agent_info_ref = organ_handle.get_agent_info.remote(agent_id)
                    agent_info = await self._ray_await(agent_info_ref)
                    agent_class = agent_info.get("class", "BaseAgent")
                    
                    # Remove the old agent
                    remove_ref = organ_handle.remove_agent.remote(agent_id)
                    await self._ray_await(remove_ref)
                    
                    # Get agent actor options
                    agent_opts = self._get_agent_actor_options(agent_id)
                    
                    # Create agent with correct specialization
                    create_ref = organ_handle.create_agent.remote(
                        agent_id=agent_id,
                        specialization=spec,
                        organ_id=organ_id,
                        agent_class_name=agent_class,
                        **agent_opts,
                    )
                    await self._ray_await(create_ref)
                    
                    # Update local mapping
                    self.agent_to_organ_map[agent_id] = organ_id
                    
                    self.logger.info(
                        f"✅ Successfully respawned agent {agent_id} with specialization '{spec_normalized}'"
                    )
                except Exception as e:
                    self.logger.error(
                        f"❌ Failed to respawn agent {agent_id} with correct specialization: {e}",
                        exc_info=True
                    )
                    
        except Exception as e:
            self.logger.warning(
                f"Error fixing mismatched agent specializations: {e}",
                exc_info=True
            )

    def _build_role_profile_from_capability(
        self,
        spec_str: str,
        capability_name: str,
        capability_data: Optional[Dict[str, Any]],
    ) -> Optional["RoleProfile"]:
        """
        Build RoleProfile from pkg_subtask_types capability data.

        **PRIORITY: This method ensures dynamic pkg_subtask_types data overrides static YAML configs.**

        Extracts role profile information from capability's default_params.executor and
        default_params.routing fields, ensuring the database is the source of truth.

        Args:
            spec_str: Specialization string (normalized, lowercase)
            capability_name: Capability name from pkg_subtask_types
            capability_data: Full capability dictionary from pkg_subtask_types

        Returns:
            RoleProfile if capability data contains executor/routing hints, None otherwise
        """
        if not capability_data:
            return None

        try:
            from seedcore.agents.roles.specialization import (
                RoleProfile,
                DynamicSpecialization,
            )

            default_params = capability_data.get("default_params", {})
            if not isinstance(default_params, dict):
                return None

            executor = default_params.get("executor", {})
            routing = default_params.get("routing", {})

            # Handle legacy format: if executor/routing don't exist, try to derive from flat structure
            if not isinstance(executor, dict) and not isinstance(routing, dict):
                # Legacy format: check if we have agent_behavior or other hints
                agent_behavior = default_params.get("agent_behavior", [])
                if agent_behavior:
                    # Create minimal executor structure from agent_behavior
                    executor = {
                        "behaviors": agent_behavior
                        if isinstance(agent_behavior, list)
                        else [agent_behavior],
                    }
                    routing = {}
                else:
                    # No executor/routing structure and no agent_behavior - can't build role profile
                    return None

            # Ensure executor and routing are dicts
            if not isinstance(executor, dict):
                executor = {}
            if not isinstance(routing, dict):
                routing = {}

            # Extract skills from routing hints
            skills = {}
            if isinstance(routing, dict):
                skills = routing.get("skills", {}) or {}

            # Extract tools (from top-level allowed_tools, executor.tools, and routing.tools)
            # **CRITICAL: Check top-level allowed_tools first (database source of truth)**
            tools = set()
            
            # Priority 1: Top-level allowed_tools (direct from pkg_subtask_types)
            if isinstance(default_params, dict):
                top_level_tools = default_params.get("allowed_tools", [])
                if isinstance(top_level_tools, list):
                    tools.update(top_level_tools)
                elif isinstance(top_level_tools, str):
                    # Handle single string tool name
                    tools.add(top_level_tools)
            
            # Priority 2: executor.tools (legacy/alternative format)
            if isinstance(executor, dict):
                executor_tools = executor.get("tools", [])
                if isinstance(executor_tools, list):
                    tools.update(executor_tools)
                elif isinstance(executor_tools, str):
                    tools.add(executor_tools)
            
            # Priority 3: routing.tools (routing hints)
            if isinstance(routing, dict):
                routing_tools = routing.get("tools", [])
                if isinstance(routing_tools, list):
                    tools.update(routing_tools)
                elif isinstance(routing_tools, str):
                    tools.add(routing_tools)

            # Extract routing tags
            tags = set()
            if isinstance(routing, dict):
                routing_tags = routing.get("routing_tags", [])
                if isinstance(routing_tags, list):
                    tags.update(routing_tags)

            # Extract behaviors and behavior_config (Behavior Plugin System)
            behaviors = []
            behavior_config = {}
            if isinstance(executor, dict):
                behaviors = executor.get("behaviors", [])
                behavior_config = executor.get("behavior_config", {})
                if not isinstance(behaviors, list):
                    behaviors = []
                if not isinstance(behavior_config, dict):
                    behavior_config = {}

            # Handle legacy format: check for agent_behavior in default_params
            if not behaviors and isinstance(default_params, dict):
                agent_behavior = default_params.get("agent_behavior", [])
                if agent_behavior:
                    if isinstance(agent_behavior, list):
                        behaviors = agent_behavior
                    else:
                        behaviors = [agent_behavior]

            # Extract zone_affinity and environment_constraints (if present)
            zone_affinity = []
            environment_constraints = {}
            if isinstance(routing, dict):
                zone_affinity = routing.get("zone_affinity", [])
                environment_constraints = routing.get("environment_constraints", {})
                if not isinstance(zone_affinity, list):
                    zone_affinity = []
                if not isinstance(environment_constraints, dict):
                    environment_constraints = {}

            # Get or create specialization
            from seedcore.agents.roles.specialization import get_specialization

            try:
                spec = get_specialization(spec_str)
            except KeyError:
                # Create dynamic specialization if not found
                spec = DynamicSpecialization(
                    spec_str,
                    capability_name.replace("_", " ").title(),
                    metadata={
                        "source": "pkg_subtask_types",
                        "capability": capability_name,
                    },
                )

            # Create role profile from capability data
            # This ensures pkg_subtask_types is the source of truth
            role_profile = RoleProfile(
                name=spec,
                default_skills=skills,
                allowed_tools=tools,
                routing_tags=tags,
                default_behaviors=list(behaviors),
                behavior_config=dict(behavior_config),
                zone_affinity=list(zone_affinity),
                environment_constraints=dict(environment_constraints),
            )

            return role_profile

        except Exception as e:
            self.logger.warning(
                f"Failed to build role profile from capability '{capability_name}': {e}"
            )
            self.logger.debug("Build error details:", exc_info=True)
            return None

    def _determine_organ_for_specialization(
        self, spec_str: str, capability_name: Optional[str] = None, capability_data: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Determine which organ a specialization should belong to using federated mapping with explicit fallback.
        
        This follows a strict hierarchy of truth:
        1. Level Zero: Explicit Database Override (preferred_organ from pkg_subtask_types.default_params.routing)
        2. Level One: Capability-to-Organ Mapping (semantic keyword matching)
        3. Level Two: Structural Inference (pattern matching)
        4. Fallback: utility_organ (the generalist)
        
        Args:
            spec_str: Specialization string (normalized, lowercase)
            capability_name: Capability name from pkg_subtask_types (primary source for inference)
            capability_data: Optional full capability data dict for additional context
            
        Returns:
            organ_id if a match is found, None otherwise (will fallback to utility_organ in router)
        """
        if not self.organs:
            return None
        
        # Check if already mapped
        if spec_str in self.organ_specs:
            organ_id = self.organ_specs[spec_str]
            if organ_id in self.organs:
                return organ_id
        
        # =====================================================================
        # Level Zero: Explicit Database Override (Highest Priority)
        # Check if pkg_subtask_types.default_params.routing.preferred_organ is set
        # =====================================================================
        if capability_data:
            # Handle both direct dict and nested structures
            # capability_data can be: {"default_params": {...}} or just {...}
            default_params = None
            if isinstance(capability_data, dict):
                # Check if it's already the default_params structure
                if "default_params" in capability_data:
                    default_params = capability_data.get("default_params", {})
                elif "routing" in capability_data or "executor" in capability_data:
                    # It might be the default_params dict itself
                    default_params = capability_data
                else:
                    # Try to get default_params if it exists
                    default_params = capability_data.get("default_params", {})
            
            if isinstance(default_params, dict):
                routing = default_params.get("routing", {})
                if isinstance(routing, dict):
                    preferred_organ = routing.get("preferred_organ")
                    if preferred_organ and isinstance(preferred_organ, str):
                        preferred_organ = preferred_organ.strip()
                        if preferred_organ in self.organs:
                            self.logger.debug(
                                f"📌 Mapped specialization '{spec_str}' to organ '{preferred_organ}' "
                                f"(explicit preferred_organ from pkg_subtask_types.default_params.routing for capability '{capability_name}')"
                            )
                            return preferred_organ
                        else:
                            self.logger.warning(
                                f"⚠️ Capability '{capability_name}' specifies preferred_organ '{preferred_organ}' "
                                f"but this organ does not exist (available organs: {list(self.organs.keys())}). "
                                f"Falling back to inference."
                            )

                    elif preferred_organ:
                        self.logger.debug(
                            f"⚠️ Capability '{capability_name}' has preferred_organ but it's not a string: {type(preferred_organ)}"
                        )
        
        # Primary inference source: capability_name from pkg_subtask_types
        inference_source = capability_name or spec_str
        inference_source_lower = inference_source.lower()
        
        # Extract organ base names from existing organs (e.g., "physical_actuation" from "physical_actuation_organ")
        organ_bases = {}
        for organ_id in self.organs.keys():
            # Remove "_organ" suffix to get base name
            base = organ_id.replace("_organ", "")
            organ_bases[base] = organ_id
        
        # Pattern 1: Semantic keyword matching - map capability keywords to organ types
        # This handles semantic relationships like "actuator" -> "actuation", "monitor" -> "intelligence", etc.
        semantic_keywords = {
            "actuator": ["actuation"],
            "actuate": ["actuation"],
            "monitor": ["intelligence", "monitoring"],
            "control": ["orchestration", "execution"],
            "adjust": ["intelligence", "orchestration"],
            "optimize": ["intelligence"],
            "route": ["orchestration", "execution"],
            "generate": ["foundry", "intelligence"],
            "notify": ["experience", "orchestration"],
            "activate": ["execution", "orchestration"],
        }
        
        inference_parts = inference_source_lower.split("_")
        for inf_part in inference_parts:
            if len(inf_part) > 3 and inf_part in semantic_keywords:
                # Check if any organ matches the semantic keywords
                for keyword in semantic_keywords[inf_part]:
                    for organ_id in self.organs.keys():
                        organ_base = organ_id.replace("_organ", "").lower()
                        if keyword in organ_base:
                            self.logger.debug(
                                f"📌 Mapped specialization '{spec_str}' to organ '{organ_id}' "
                                f"(inferred from capability name: '{capability_name}' keyword '{inf_part}' -> organ keyword '{keyword}')"
                            )
                            return organ_id
        
        # Pattern 1b: Direct part matching - check if capability name parts match organ parts exactly
        # Try to match capability name parts against organ base names
        for organ_id in self.organs.keys():
            organ_base = organ_id.replace("_organ", "").lower()
            organ_parts = organ_base.split("_")
            
            # Check if any significant part of capability matches organ parts
            for inf_part in inference_parts:
                if len(inf_part) > 3:  # Only consider substantial parts
                    for org_part in organ_parts:
                        if len(org_part) > 3 and (inf_part == org_part or inf_part in org_part or org_part in inf_part):
                            self.logger.debug(
                                f"📌 Mapped specialization '{spec_str}' to organ '{organ_id}' "
                                f"(inferred from capability name: '{capability_name}' part '{inf_part}' matches organ part '{org_part}')"
                            )
                            return organ_id
        
        # Pattern 2: Check if capability name contains organ name keywords (inferred from naming convention)
        
        # Check if any organ base name appears in the capability name
        for base, organ_id in organ_bases.items():
            base_lower = base.lower()
            # Check if organ base name is contained in capability name
            # e.g., "physical_actuation" in "reachy_actuator" -> no match
            # but "brain_foundry" in "brain_foundry_scanner" -> match
            if base_lower in inference_source_lower or inference_source_lower in base_lower:
                # Avoid false positives: ensure it's a meaningful match
                # Check if the match is at word boundaries or is a significant substring
                if len(base_lower) > 5:  # Only consider substantial matches
                    self.logger.debug(
                        f"📌 Mapped specialization '{spec_str}' to organ '{organ_id}' "
                        f"(inferred from capability name: '{capability_name}' contains organ base '{base}')"
                    )
                    return organ_id
        
        # Pattern 3: Check routing tags or hints from capability data if available
        if capability_data:
            default_params = capability_data.get("default_params", {})
            if isinstance(default_params, dict):
                routing = default_params.get("routing", {})
                if isinstance(routing, dict):
                    routing_tags = routing.get("routing_tags", [])
                    if isinstance(routing_tags, list):
                        # Check if routing tags contain organ hints
                        for tag in routing_tags:
                            tag_lower = str(tag).lower()
                            for base, organ_id in organ_bases.items():
                                if base.lower() in tag_lower:
                                    self.logger.debug(
                                        f"📌 Mapped specialization '{spec_str}' to organ '{organ_id}' "
                                        f"(inferred from routing tag: '{tag}')"
                                    )
                                    return organ_id
        
        # Pattern 5: Partial word matching - check if significant parts of capability name match organ parts
        # This is a fallback for cases where exact or semantic matching didn't work
        inference_parts = inference_source_lower.split("_")
        for organ_id in self.organs.keys():
            organ_base = organ_id.replace("_organ", "")
            organ_parts = organ_base.split("_")
            # Check if any significant part (length > 3) of capability matches organ parts
            for inf_part in inference_parts:
                if len(inf_part) > 3:
                    for org_part in organ_parts:
                        if len(org_part) > 3 and (inf_part in org_part or org_part in inf_part):
                            self.logger.debug(
                                f"📌 Mapped specialization '{spec_str}' to organ '{organ_id}' "
                                f"(inferred from partial match: '{inf_part}' <-> '{org_part}')"
                            )
                            return organ_id
        
        # =====================================================================
        # Final Fallback: utility_organ (The Generalist)
        # If no explicit preference and no inference worked, use utility_organ
        # =====================================================================
        if "utility_organ" in self.organs:
            self.logger.debug(
                f"📌 Mapped specialization '{spec_str}' to organ 'utility_organ' "
                f"(fallback: no explicit preference or inference match for capability '{capability_name}')"
            )
            return "utility_organ"
        
        self.logger.warning(
            f"⚠️ Could not determine organ for specialization '{spec_str}' "
            f"(capability: '{capability_name}') and utility_organ is not available. Router will use fallback routing."
        )
        return None

    def _resolve_registered_specialization(
        self, spec_str: str, params: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Resolve a specialization string to a registered specialization.

        This handles aliasing and normalization for inputs like:
        - "Some.Spec" -> "some_spec"
        - "Design" -> best matching dynamic specialization (via routing_tags)
        - Capability-backed specs (params.capability / params.executor.specialization)
        """
        if not spec_str:
            return None

        from seedcore.agents.roles.specialization import SpecializationManager

        spec_manager = SpecializationManager.get_instance()
        normalized = str(spec_str).strip().lower()

        # 1) Direct or normalized variants
        variants = [
            normalized,
            normalized.replace(".", "_"),
            normalized.replace("-", "_"),
            normalized.replace("/", "_"),
        ]
        for v in variants:
            if spec_manager.is_registered(v):
                return v

        # 2) Capability-based fallback (if present)
        params = params or {}
        capability = params.get("capability")
        if capability and spec_manager.is_registered(str(capability).strip().lower()):
            return str(capability).strip().lower()

        executor_spec = (
            params.get("executor", {}).get("specialization")
            if isinstance(params.get("executor"), dict)
            else None
        )
        if executor_spec and spec_manager.is_registered(
            str(executor_spec).strip().lower()
        ):
            return str(executor_spec).strip().lower()

        # 3) Routing-tags based fallback (if unambiguous)
        profiles = getattr(self.role_registry, "_profiles", {})
        if isinstance(profiles, dict) and profiles:
            token = normalized.replace(".", " ").replace("_", " ").replace("-", " ")
            tokens = [t for t in token.split() if len(t) > 2]
            routing_tags = []
            routing = params.get("routing") if isinstance(params, dict) else None
            if isinstance(routing, dict):
                rt = routing.get("routing_tags")
                if isinstance(rt, (list, tuple, set)):
                    routing_tags = [str(t).lower() for t in rt]
            matches: list[str] = []
            for spec_obj, profile in profiles.items():
                tags = getattr(profile, "routing_tags", set()) or set()
                tags = {str(t).lower() for t in tags}
                if (
                    normalized in tags
                    or any(t in tags for t in tokens)
                    or any(t in tags for t in routing_tags)
                ):
                    spec_val = (
                        spec_obj.value
                        if hasattr(spec_obj, "value")
                        else str(spec_obj)
                    )
                    matches.append(str(spec_val).lower())
            if len(matches) == 1:
                return matches[0]

        return None

    async def find_organs_with_specialization(self, spec_str: str) -> List[str]:
        """
        Find organs that have agents with the given specialization.

        This implements selective broadcasting - only organs with relevant agents
        receive role profile updates, reducing network traffic.

        Args:
            spec_str: Specialization string (normalized, lowercase)

        Returns:
            List of organ IDs that have agents with this specialization
        """
        target_organs = []

        if not self.organs:
            return []

        # Method 1: Use organ_specs mapping (specialization -> organ_id)
        # This is populated during agent creation and provides fast lookup
        organ_id = self.organ_specs.get(spec_str)
        if organ_id and organ_id in self.organs:
            target_organs.append(organ_id)

        # Method 2: Check specialization_to_organ mapping (reverse lookup)
        # This maps Specialization enum/DynamicSpecialization -> organ_id
        for spec_protocol, organ_id in self.specialization_to_organ.items():
            spec_value = (
                spec_protocol.value
                if hasattr(spec_protocol, "value")
                else str(spec_protocol)
            ).lower()
            if (
                spec_value == spec_str
                and organ_id not in target_organs
                and organ_id in self.organs
            ):
                target_organs.append(organ_id)

        # Method 3: Query organs directly to find agents with this specialization
        # This is the most accurate as it checks actual agent state
        # Query all organs in parallel for efficiency
        async def check_organ(organ_id: str, organ_handle: Any) -> Optional[str]:
            """Check if organ has agents with the specialization."""
            try:
                # List all agents in the organ
                agent_ids_ref = organ_handle.list_agents.remote()
                agent_ids = await self._ray_await(agent_ids_ref)

                if not agent_ids:
                    return None

                # Check each agent's specialization
                for agent_id in agent_ids:
                    agent_info_ref = organ_handle.get_agent_info.remote(agent_id)
                    agent_info = await self._ray_await(agent_info_ref)

                    # Check specialization in agent info
                    agent_spec = (
                        agent_info.get("specialization", "")
                        or agent_info.get("specialization_name", "")
                        or agent_info.get("specialization_value", "")
                    ).lower()

                    if agent_spec == spec_str:
                        return organ_id

                return None
            except Exception as e:
                self.logger.debug(
                    f"Error checking organ {organ_id} for specialization {spec_str}: {e}"
                )
                return None

        # Query all organs in parallel
        check_tasks = [
            check_organ(organ_id, organ_handle)
            for organ_id, organ_handle in self.organs.items()
            if organ_id not in target_organs  # Skip already found organs
        ]

        if check_tasks:
            results = await asyncio.gather(*check_tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, str) and result not in target_organs:
                    target_organs.append(result)
                elif isinstance(result, Exception):
                    self.logger.debug(f"Error in organ check: {result}")

        # Remove duplicates while preserving order
        seen = set()
        unique_organs = []
        for organ_id in target_organs:
            if organ_id not in seen:
                seen.add(organ_id)
                unique_organs.append(organ_id)

        return unique_organs

    async def evict_agents_by_specialization(
        self, 
        spec_str: str,
        wait_for_tasks: bool = False,
        timeout_seconds: float = 30.0
    ) -> Dict[str, Any]:
        """
        Evict (kill) all agents with a given specialization to force respawn with updated permissions.
        
        This is called when capabilities are updated (e.g., allowed_tools changed) to ensure
        agents reload with the new permissions. Agents are killed and will be JIT-spawned
        on the next task request with the updated role profile.
        
        Args:
            spec_str: Specialization string (normalized, lowercase)
            wait_for_tasks: If True, wait for current tasks to finish before killing (default: False)
            timeout_seconds: Maximum time to wait for tasks if wait_for_tasks=True
            
        Returns:
            Dict with eviction results: {
                "evicted": [agent_ids],
                "failed": [agent_ids],
                "total": int
            }
        """
        spec_normalized = str(spec_str).strip().lower()
        self.logger.info(
            f"🔪 Evicting agents with specialization '{spec_normalized}' "
            f"(wait_for_tasks={wait_for_tasks}, timeout={timeout_seconds}s)"
        )
        
        evicted = []
        failed = []
        
        # Find all organs with agents matching this specialization
        target_organs = await self.find_organs_with_specialization(spec_normalized)
        
        if not target_organs:
            self.logger.debug(f"No organs found with specialization '{spec_normalized}', nothing to evict")
            return {"evicted": [], "failed": [], "total": 0}
        
        # Collect all agent IDs with this specialization
        agent_ids_to_evict = []
        for organ_id in target_organs:
            organ_handle = self.organs.get(organ_id)
            if not organ_handle:
                continue
                
            try:
                # List all agents in the organ
                agent_ids_ref = organ_handle.list_agents.remote()
                agent_ids = await self._ray_await(agent_ids_ref)
                
                # Check each agent's specialization
                for agent_id in agent_ids:
                    try:
                        agent_info_ref = organ_handle.get_agent_info.remote(agent_id)
                        agent_info = await self._ray_await(agent_info_ref)
                        
                        agent_spec = (
                            agent_info.get("specialization", "")
                            or agent_info.get("specialization_name", "")
                            or agent_info.get("specialization_value", "")
                        ).lower()
                        
                        if agent_spec == spec_normalized:
                            agent_ids_to_evict.append((agent_id, organ_id))
                    except Exception as e:
                        self.logger.debug(f"Error checking agent {agent_id}: {e}")
                        continue
            except Exception as e:
                self.logger.warning(f"Error listing agents in organ {organ_id}: {e}")
                continue
        
        if not agent_ids_to_evict:
            self.logger.debug(f"No agents found with specialization '{spec_normalized}' to evict")
            return {"evicted": [], "failed": [], "total": 0}
        
        self.logger.info(
            f"Found {len(agent_ids_to_evict)} agent(s) with specialization '{spec_normalized}' to evict: "
            f"{[aid for aid, _ in agent_ids_to_evict]}"
        )
        
        # Evict each agent
        for agent_id, organ_id in agent_ids_to_evict:
            try:
                organ_handle = self.organs.get(organ_id)
                if not organ_handle:
                    failed.append(agent_id)
                    continue
                
                # If wait_for_tasks is True, try to gracefully shutdown
                if wait_for_tasks:
                    try:
                        # Try to get agent handle and check if it has a shutdown method
                        agent_handle_ref = organ_handle.get_agent_handle.remote(agent_id)
                        agent_handle = await asyncio.wait_for(
                            self._ray_await(agent_handle_ref),
                            timeout=5.0
                        )
                        
                        if agent_handle and hasattr(agent_handle, "shutdown"):
                            self.logger.debug(f"Gracefully shutting down agent {agent_id}...")
                            shutdown_ref = agent_handle.shutdown.remote()
                            await asyncio.wait_for(
                                self._ray_await(shutdown_ref),
                                timeout=timeout_seconds
                            )
                    except (asyncio.TimeoutError, Exception) as e:
                        self.logger.debug(f"Graceful shutdown failed for {agent_id}: {e}, forcing kill")
                
                # Remove agent from organ (this kills the Ray actor)
                remove_ref = organ_handle.remove_agent.remote(agent_id, force_kill_by_name=True)
                removed = await self._ray_await(remove_ref)
                
                if removed:
                    evicted.append(agent_id)
                    self.logger.info(f"✅ Evicted agent {agent_id} from {organ_id}")
                else:
                    failed.append(agent_id)
                    self.logger.warning(f"⚠️ Failed to evict agent {agent_id} from {organ_id}")
                    
            except Exception as e:
                self.logger.error(
                    f"❌ Error evicting agent {agent_id}: {e}",
                    exc_info=True
                )
                failed.append(agent_id)
        
        result = {
            "evicted": evicted,
            "failed": failed,
            "total": len(agent_ids_to_evict)
        }
        
        self.logger.info(
            f"🔪 Eviction complete for '{spec_normalized}': "
            f"{len(evicted)} evicted, {len(failed)} failed, {len(agent_ids_to_evict)} total"
        )
        
        return result

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
                logger.warning(
                    f"[get_all_agent_handles] Failed to get agent handles from organ {organ_id}: {e}"
                )
                continue

        logger.info(
            f"[get_all_agent_handles] Returning {len(all_agent_handles)} agent handles from {len(self.organs)} organs"
        )
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
            return {
                "success": False,
                "error": "Missing 'op' or 'target_specialization'",
            }

        if op not in ["scale_up", "scale_down"]:
            return {
                "success": False,
                "error": f"Unknown operation: {op}. Must be 'scale_up' or 'scale_down'",
            }

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
            logger.error(
                f"[evolve] Evolution operation {op} failed: {e}", exc_info=True
            )
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

    def _get_organ_for_specialization(
        self, spec_name: str
    ) -> Optional[ray.actor.ActorHandle]:
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
            spec = get_specialization(spec_name)
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
            spec = get_specialization(spec_name)
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
                # Get configuration-driven agent actor options
                agent_opts = self._get_agent_actor_options(agent_id)

                # Create agent via organ (default to BaseAgent for evolution)
                ref = organ.create_agent.remote(
                    agent_id=agent_id,
                    specialization=spec,
                    organ_id=organ_id,
                    agent_class_name="BaseAgent",  # Default for evolution-created agents
                    **agent_opts,  # Unpack: name, num_cpus, lifetime
                )

                await self._ray_await(ref)
                self.agent_to_organ_map[agent_id] = organ_id
                # Track evolution-created agent time for grace period
                self._agent_creation_times[agent_id] = asyncio.get_running_loop().time()
                new_agent_ids.append(agent_id)
                logger.info(f"[evolve] Created agent {agent_id}")

            except Exception as e:
                logger.error(
                    f"[evolve] Failed to create agent {agent_id}: {e}", exc_info=True
                )
                # Continue with other agents even if one fails

        if not new_agent_ids:
            return {"success": False, "error": "Failed to create any agents"}

        logger.info(
            f"[evolve] Successfully scaled up {spec_name}: created {len(new_agent_ids)} agents"
        )
        return {
            "success": True,
            "result": {"created_agents": new_agent_ids, "count": len(new_agent_ids)},
        }

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
                    logger.info(
                        f"[evolve] Failed to get info for agent {agent_id}: {e}"
                    )
                    continue

            if len(agent_ids_by_spec) < count:
                logger.warning(
                    f"[evolve] Only {len(agent_ids_by_spec)} agents with specialization {spec_name} available, requested {count}"
                )
                count = len(agent_ids_by_spec)

            if count == 0:
                return {
                    "success": False,
                    "error": f"No agents with specialization {spec_name} available to remove",
                }

            # Select agents to remove (simple: take first N)
            agents_to_remove = agent_ids_by_spec[:count]

        except Exception as e:
            logger.error(
                f"[evolve] Failed to get agents from organ: {e}", exc_info=True
            )
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
                logger.error(
                    f"[evolve] Failed to remove agent {agent_id}: {e}", exc_info=True
                )
                # Continue with other agents even if one fails

        if not removed_agent_ids:
            return {"success": False, "error": "Failed to remove any agents"}

        logger.info(
            f"[evolve] Successfully scaled down {spec_name}: removed {len(removed_agent_ids)} agents"
        )
        return {
            "success": True,
            "result": {
                "removed_agents": removed_agent_ids,
                "count": len(removed_agent_ids),
            },
        }

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
                return {
                    "success": False,
                    "error": f"Not enough agents ({len(agent_ids)}) to split into {k} organs",
                }

            # Note: Organ split requires creating new organs, which needs organ config
            # This is a simplified implementation - full version would create organs properly
            logger.warning(
                "Organ split requires organ creation logic - not fully implemented"
            )
            return {
                "success": False,
                "error": "Organ split requires organ creation logic - not fully implemented",
            }
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
                    register_ref = dst_organ_handle.register_agent.remote(
                        agent_id, agent_handle
                    )
                    await self._ray_await(register_ref)
                    remove_ref = src_organ_handle.remove_agent.remote(agent_id)
                    await self._ray_await(remove_ref)
                    self.agent_to_organ_map[agent_id] = organ_id
                    # Track migration time for grace period (migrated agents need time to stabilize)
                    self._agent_creation_times[agent_id] = (
                        asyncio.get_running_loop().time()
                    )
                    total_agents_moved += 1

                # Remove source organ from registry
                del self.organs[src_organ_id]

            return {
                "success": True,
                "result": {
                    "destination_organ": organ_id,
                    "merged_organs": src_organ_ids,
                    "agents_moved": total_agents_moved,
                },
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
            logger.warning(
                "Organ clone requires organ creation logic - not fully implemented"
            )
            return {
                "success": False,
                "error": "Organ clone requires organ creation logic - not fully implemented",
            }
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
                    register_ref = dst_organ_handle.register_agent.remote(
                        agent_id, agent_handle
                    )
                    await self._ray_await(register_ref)
                    self.agent_to_organ_map[agent_id] = migrate_to
                    # Track migration time for grace period (migrated agents need time to stabilize)
                    self._agent_creation_times[agent_id] = (
                        asyncio.get_running_loop().time()
                    )
                    agents_migrated += 1

            # Remove organ from registry
            del self.organs[organ_id]

            return {
                "success": True,
                "result": {
                    "retired_organ": organ_id,
                    "agents_migrated": agents_migrated,
                    "migrate_to": migrate_to,
                },
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

                        # Filter out agents that are still in grace period (recently created)
                        current_time = asyncio.get_running_loop().time()
                        unhealthy_agents = []
                        for agent_id, st in status.get("agents", {}).items():
                            if not st.get("alive", False):
                                # Check if agent is still in grace period
                                creation_time = self._agent_creation_times.get(agent_id)
                                if creation_time:
                                    age = current_time - creation_time
                                    if age < self._agent_health_grace_period:
                                        # Agent is still initializing - skip health check
                                        logger.debug(
                                            f"[HealthLoop] Agent {agent_id} still initializing "
                                            f"(age={age:.1f}s < grace_period={self._agent_health_grace_period}s), "
                                            "skipping health check"
                                        )
                                        continue
                                # Agent is unhealthy and past grace period
                                unhealthy_agents.append(agent_id)

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

    async def _run_janitor(
        self,
        heartbeat_timeout_minutes: int = 5,
        cleanup_timeout_hours: int = 1,
    ) -> None:
        """
        Janitor/pruning logic: Marks stale agents/organs as offline and optionally deletes old ones.
        
        This solves the "State vs. Registry" discrepancy by:
        1. Marking agents as 'offline' if no heartbeat for timeout period
        2. Optionally deleting dynamic agents that have been offline for cleanup_timeout_hours
        3. Marking organs as 'inactive' if no heartbeat
        
        Args:
            heartbeat_timeout_minutes: Minutes without heartbeat before marking offline.
            cleanup_timeout_hours: Hours offline before deletion (0 = never delete).
        """
        try:
            from seedcore.database import get_async_pg_session_factory
            from seedcore.graph.agent_repository import AgentGraphRepository
            
            session_factory = get_async_pg_session_factory()
            if not session_factory:
                logger.debug("[Janitor] No session factory available, skipping pruning")
                return
            
            repo = AgentGraphRepository()
            
            # Get list of static agents to keep (from organs.yaml)
            keep_static_agents = []
            for cfg in self.organ_configs:
                for agent_def in cfg.get("agents", []):
                    spec_str = agent_def.get("specialization", "")
                    count = int(agent_def.get("count", 1))
                    for i in range(count):
                        agent_id = f"{cfg['id']}_{spec_str.lower()}_{i}"
                        keep_static_agents.append(agent_id)
            
            async with session_factory() as session:
                async with session.begin():
                    # Prune stale agents
                    agent_stats = await repo.prune_stale_agents(
                        session,
                        heartbeat_timeout_minutes=heartbeat_timeout_minutes,
                        cleanup_timeout_hours=cleanup_timeout_hours,
                        keep_static_agents=keep_static_agents,
                    )
                    
                    # Prune stale organs
                    organs_marked = await repo.prune_stale_organs(
                        session,
                        heartbeat_timeout_minutes=heartbeat_timeout_minutes,
                    )
                    
                    if agent_stats["marked_offline"] > 0 or agent_stats["deleted"] > 0 or organs_marked > 0:
                        logger.info(
                            f"🧹 [Janitor] Pruned: {agent_stats['marked_offline']} agents marked offline, "
                            f"{agent_stats['deleted']} agents deleted, {organs_marked} organs marked inactive"
                        )
        except Exception as e:
            logger.warning(f"[Janitor] Pruning failed (non-fatal): {e}", exc_info=True)

    async def _reconciliation_loop(self):
        """
        Rebuilds crashed organs or agents and updates internal routing maps.
        Also runs janitor/pruning logic to clean up stale agents and organs.
        """
        logger.info("[OrganismCore] Reconciliation loop started")
        
        # Janitor configuration
        janitor_interval_s = float(os.getenv("ORGANISM_JANITOR_INTERVAL_S", "300.0"))  # Default 5 minutes
        heartbeat_timeout_minutes = int(os.getenv("ORGANISM_HEARTBEAT_TIMEOUT_MINUTES", "5"))
        cleanup_timeout_hours = int(os.getenv("ORGANISM_CLEANUP_TIMEOUT_HOURS", "1"))
        last_janitor_run = 0.0

        while not self._shutdown_event.is_set():
            try:
                # Run janitor/pruning periodically
                current_time = asyncio.get_running_loop().time()
                if current_time - last_janitor_run >= janitor_interval_s:
                    await self._run_janitor(
                        heartbeat_timeout_minutes=heartbeat_timeout_minutes,
                        cleanup_timeout_hours=cleanup_timeout_hours,
                    )
                    last_janitor_run = current_time

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
                                # Update creation time for respawned agent (grace period reset)
                                self._agent_creation_times[agent_id] = (
                                    asyncio.get_running_loop().time()
                                )
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
    #  CONFIG WATCHER
    # =====================================================================

    async def start_config_watcher(self, interval: int = 2):
        """
        Background loop that watches for file changes and triggers updates.
        """
        logger.info(f"👀 Watching config file at: {self.config_path}")
        last_mtime = self.config_path.stat().st_mtime

        while not self._shutdown_event.is_set():
            await asyncio.sleep(interval)

            try:
                current_mtime = self.config_path.stat().st_mtime
                if current_mtime != last_mtime:
                    logger.info("Detected config file change. Reloading...")
                    last_mtime = current_mtime

                    # 1. Use your internal loader to get the Dict
                    # We need to reload the full config structure
                    with open(self.config_path, "r") as f:
                        new_config_dict = yaml.safe_load(f) or {}

                    # 2. Call the transactional applicator we just designed
                    # This makes the "Upstream Caller" the watcher loop
                    result = await self.apply_organism_config(new_config_dict)

                    if result["status"] == "success":
                        logger.info("Hot-reload successful.")

            except asyncio.CancelledError:
                logger.info("[ConfigWatcher] Cancelled")
                break
            except Exception as e:
                logger.error(f"Hot-reload check failed: {e}")

        logger.info("[OrganismCore] Config watcher exited")

    # =====================================================================
    #  CONFIG APPLICATION (RUNTIME UPDATES)
    # =====================================================================

    async def apply_organism_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply runtime configuration with Side-Effect Rollback and State Isolation.
        """
        async with self._config_lock:
            logger.info("⚙️ Runtime Config Update Requested...")

            # --- 1. Validation & Snapshot ---
            root = config.get("seedcore", {}).get("organism", {})
            if not root:
                return {"status": "ignored", "reason": "empty_config"}

            new_settings = root.get("settings", {})
            new_topology = root.get("topology", {})
            new_organs_list = root.get("organs", [])

            # Snapshot current state for comparison (and potential rollback)
            current_organs_map = {o["id"]: o for o in self.organ_configs}
            new_organs_map = {o["id"]: o for o in new_organs_list}

            # --- 2. Calculate Diff ---
            to_add = [
                o for oid, o in new_organs_map.items() if oid not in current_organs_map
            ]
            to_update = [
                o for oid, o in new_organs_map.items() if oid in current_organs_map
            ]
            # Calculate removed if you need to clean up old actors
            to_remove_ids = set(current_organs_map.keys()) - set(new_organs_map.keys())

            # Track side effects for rollback
            newly_spawned_handles = []

            try:
                # --- 3. Execution Phase (Isolated) ---

                # A. Parallel Updates (Non-blocking)
                # Fire update RPCs first. If these fail, we haven't spawned new stuff yet.
                update_futures = []
                for cfg in to_update:
                    organ_id = cfg["id"]
                    handle = self.organs.get(organ_id)
                    if handle and hasattr(handle, "update_config"):
                        update_futures.append(handle.update_config.remote(cfg))

                if update_futures:
                    # wait for updates to ensure they are valid before expanding
                    # return_exceptions=False ensures we fail fast if an update crashes
                    await asyncio.gather(*update_futures)

                # B. Additive Creation
                # CRITICAL CHANGE: Do not mutate self.organ_configs yet.
                # Pass the specific list to the creator method.
                # (You likely need to refactor _create_organs to accept an optional list)
                if to_add:
                    # Assuming _create_organs_batch returns a dict of {id: handle}
                    # and takes a list of configs as input.
                    new_handles_dict = await self._create_organs_batch(to_add)

                    # Register temporarily to track for rollback
                    newly_spawned_handles = list(new_handles_dict.values())

                    # Update our local handle registry temporarily
                    self.organs.update(new_handles_dict)

                # C. Agent Reconciliation
                # This likely depends on the organs existing.
                await self._create_agents_from_config(target_organs=to_add + to_update)

                # --- 4. Commit Phase (Point of No Return) ---
                # Only NOW do we mutate the source of truth

                # Update Config List
                self.organ_configs = new_organs_list

                # Update Global Settings
                self.global_settings = deepcopy(new_settings)

                # Smart Topology Rebuild: Only if changed
                if new_topology != self.topology_cfg:
                    self.topology_cfg = deepcopy(new_topology)
                    await self._rebuild_topology_from_config()

                # Handle Removals (Cleanup)
                for rid in to_remove_ids:
                    handle = self.organs.pop(rid, None)
                    if handle:
                        ray.kill(handle)  # Terminate the actor

                logger.info(
                    f"✅ Config Applied: {len(to_add)} added, {len(to_update)} updated."
                )
                return {
                    "status": "success",
                    "added": [o["id"] for o in to_add],
                    "updated": [o["id"] for o in to_update],
                }

            except Exception as e:
                # --- 5. True Rollback (Compensating Transactions) ---
                logger.error(
                    f"❌ Config Update Failed: {e}. Executing Rollback...",
                    exc_info=True,
                )

                # 1. Kill any actors we just spawned (Undo Side Effects)
                for handle in newly_spawned_handles:
                    try:
                        ray.kill(handle)
                    except Exception:
                        pass  # Best effort cleanup

                # 2. Revert local handle registry (if we touched self.organs)
                for cfg in to_add:
                    self.organs.pop(cfg["id"], None)

                # 3. Note: We never touched self.organ_configs, so no variable rollback needed!
                raise e

    async def _rebuild_topology_from_config(self):
        """
        Rebuild topology based on topology_cfg.
        This is a placeholder - implement topology rebuilding logic as needed.
        """
        logger.info(
            f"[OrganismCore] Topology rebuild requested (config: {self.topology_cfg})"
        )
        # TODO: Implement topology rebuilding logic
        # This might involve updating routing rules, network topology, etc.
        pass

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
            # Get configuration-driven actor options
            actor_opts = self._get_organ_actor_options(organ_id)

            # --- Create lightweight OrganRegistry copy without session_factory for serialization ---
            lightweight_registry = self._create_serializable_organ_registry()

            new_organ = Organ.options(
                **actor_opts
            ).remote(
                organ_id=organ_id,
                # Stateless dependencies
                role_registry=self.role_registry,
                cognitive_client_cfg=self._get_cognitive_client_config(),
                ml_client_cfg=self._get_ml_client_config(),
                # Config for creating connections (avoids serialization)
                holon_fabric_config=self._get_holon_fabric_config(),
                # Tool handler: pass shard handles if sharded, None if single mode (creates locally)
                tool_handler_shards=self.tool_shards
                if hasattr(self, "tool_shards") and self.tool_shards
                else None,
                # Stateful dependencies (pass config/ID instead of instances)
                mw_manager_organ_id=organ_id,  # Pass organ_id, create MwManager locally in actor
                checkpoint_cfg=self.checkpoint_cfg,
                # OrganRegistry for Tier-1 registration (lightweight copy without session_factory)
                organ_registry=lightweight_registry,
            )
        except Exception as e:
            logger.error(f"[OrganismCore] Failed to recreate organ: {e}")
            return

        self.organs[organ_id] = new_organ

        # Register organ in Tier-1 registry (with DB persistence)
        if self.organ_registry:
            # Get organ config for metadata
            cfg = next((c for c in self.organ_configs if c["id"] == organ_id), {})
            organ_kind = (
                cfg.get("kind") or cfg.get("description", "").split(".")[0]
                if cfg.get("description")
                else None
            )
            organ_props = {
                "description": cfg.get("description"),
                "config": cfg,
            }
            await self.organ_registry.record_organ(
                organ_id,
                new_organ,
                kind=organ_kind,
                props=organ_props,
            )

        logger.info(f"[OrganismCore] Organ `{organ_id}` recreated")

        # Respawn agents
        for agent_def in cfg.get("agents", []):
            try:
                spec = get_specialization(agent_def["specialization"])
            except KeyError:
                logger.error(
                    f"Invalid specialization '{agent_def['specialization']}' in config for organ {organ_id}"
                )
                continue
            count = agent_def.get("count", 1)
            for _ in range(count):
                agent_id = str(uuid.uuid4())
                try:
                    # Get agent class from config if available, default to BaseAgent
                    agent_class_name = agent_def.get("class", "BaseAgent")

                    # Get configuration-driven agent actor options
                    agent_opts = self._get_agent_actor_options(agent_id)

                    ref = new_organ.create_agent.remote(
                        agent_id=agent_id,
                        specialization=spec,
                        organ_id=organ_id,
                        agent_class_name=agent_class_name,
                        **agent_opts,  # Unpack: name, num_cpus, lifetime
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
                logger.info(
                    "[OrganismCore] Ray not initialized, skipping janitor check"
                )
                return

            namespace = RAY_NAMESPACE

            try:
                # Fast path: already exists
                jan = await asyncio.to_thread(
                    ray.get_actor, "seedcore_janitor", namespace=namespace
                )
                logger.info(
                    f"[OrganismCore] Janitor actor already running in {namespace}"
                )
                return
            except Exception:
                logger.info(
                    f"[OrganismCore] Launching janitor in namespace {namespace}"
                )

            # Create or reuse
            from seedcore.maintenance.janitor import Janitor

            try:
                # Get configuration-driven janitor actor options
                janitor_opts = self._get_janitor_actor_options()
                # Override namespace if different from RAY_NAMESPACE
                if namespace != RAY_NAMESPACE:
                    janitor_opts["namespace"] = namespace

                Janitor.options(**janitor_opts).remote(namespace)

                # Verify it is reachable
                jan = await asyncio.to_thread(
                    ray.get_actor, "seedcore_janitor", namespace=namespace
                )
                try:
                    pong_ref = jan.ping.remote()
                    pong = await self._ray_await(pong_ref)
                    logger.info(
                        f"✅ Janitor actor launched in {namespace} (ping={pong})"
                    )
                except Exception:
                    logger.info(
                        f"✅ Janitor actor launched in {namespace} (ping skipped)"
                    )
            except Exception as e:
                logger.warning(f"⚠️ Failed to launch janitor actor: {e}")
        except Exception as e:
            logger.info(f"[OrganismCore] Ensure janitor skipped: {e}")

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

        if self._config_watcher_task:
            self._config_watcher_task.cancel()
            try:
                await self._config_watcher_task
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

        # Close HolonFabric connections
        if self.holon_fabric:
            try:
                logger.info("[OrganismCore] Closing HolonFabric connections")
                if hasattr(self.holon_fabric, "vec") and self.holon_fabric.vec:
                    await self.holon_fabric.vec.close()
                if hasattr(self.holon_fabric, "graph") and self.holon_fabric.graph:
                    await self.holon_fabric.graph.close()
            except Exception as e:
                logger.error(f"[OrganismCore] Failed to close HolonFabric: {e}")

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
