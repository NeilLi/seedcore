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
from seedcore.agents.roles.specialization import Specialization, RoleRegistry
from seedcore.agents.roles.skill_vector import SkillStoreProtocol
from seedcore.agents.roles.generic_defaults import DEFAULT_ROLE_REGISTRY
from seedcore.organs.tunnel_manager import TunnelManager
from seedcore.serve.ml_client import MLServiceClient
from seedcore.tools.manager import ToolManager
from seedcore.serve.cognitive_client import CognitiveServiceClient
from seedcore.serve.energy_client import EnergyServiceClient
from seedcore.models import TaskPayload
from seedcore.models.holon import Holon, HolonType, HolonScope

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
            raise FileNotFoundError(f"Configuration file not found at: {self.config_path}")

        # Specialization → organ mapping (for registry API only, NOT for routing decisions)
        # This is maintained for get_specialization_map() registry API
        self.specialization_to_organ: Dict[Specialization, str] = {}

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
                }
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
            "circuit_breaker": cfg.get("circuit_breaker", {
                "failure_threshold": 5,
                "recovery_timeout": 30.0,
            }),
            "retry_config": cfg.get("retry_config", {
                "max_attempts": max(1, retries),
                "base_delay": 1.0,
                "max_delay": 5.0,
            }),
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
            default_retries=1
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
            }
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
            default_retries=1
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

    # ------------------------------------------------------------------
    #  HELPER: Registries
    # ------------------------------------------------------------------
    async def _init_organ_registry(self):
        try:
            agent_repo = AgentGraphRepository()
            self.organ_registry = OrganRegistry(agent_repo)
        except Exception as e:
            logger.warning(f"⚠️ OrganRegistry init failed: {e}")
            self.organ_registry = None

    async def _verify_neo4j(self, graph_client):
        """Optional hook to verify Neo4j connectivity asynchronously."""
        # Implementation depends on your Neo4jGraph class
        pass

    async def _register_all_role_profiles_from_config(self) -> None:
        """
        Extract all specializations from config and ensure they're registered in RoleRegistry.
        This implements Option A: Strict Ordering - all roles must be registered before agents are created.
        """
        logger.info("--- Registering all role profiles from config ---")
        
        # Collect all unique specializations from config
        specializations_needed: Set[Specialization] = set()
        
        for cfg in self.organ_configs:
            agent_defs = cfg.get("agents", [])
            for block in agent_defs:
                spec_str = block.get("specialization")
                if spec_str:
                    try:
                        spec = Specialization[spec_str.upper()]
                        specializations_needed.add(spec)
                    except KeyError:
                        logger.warning(
                            f"⚠️ Unknown specialization '{spec_str}' in config, skipping"
                        )
        
        # Register missing specializations with default profiles
        registered_count = 0
        for spec in specializations_needed:
            # Check if already registered
            if self.role_registry.get_safe(spec) is None:
                # Try to get from DEFAULT_ROLE_REGISTRY first (may have better defaults)
                default_profile = DEFAULT_ROLE_REGISTRY.get_safe(spec)
                if default_profile:
                    # Use the default profile from DEFAULT_ROLE_REGISTRY
                    self.role_registry.register(default_profile)
                    logger.info(f"  ✅ Registered profile for {spec.value} from DEFAULT_ROLE_REGISTRY")
                else:
                    # Create a minimal default RoleProfile for this specialization
                    profile = RoleProfile(
                        name=spec,
                        default_skills={},  # Empty defaults - can be customized later
                        allowed_tools=set(),  # Empty defaults - can be customized later
                        routing_tags=set(),
                        safety_policies={},
                    )
                    self.role_registry.register(profile)
                    logger.info(f"  ✅ Registered minimal default profile for {spec.value}")
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
                
                # --- Pass all dependencies to the Organ actor ---
                organ = Organ.options(**actor_opts).remote(
                    organ_id=organ_id,
                    # Stateless dependencies
                    role_registry=self.role_registry,
                    cognitive_client_cfg=self._get_cognitive_client_config(),
                    ml_client_cfg=self._get_ml_client_config(),
                    # Config for creating connections (avoids serialization)
                    holon_fabric_config=self._get_holon_fabric_config(),
                    # Tool handler: pass shard handles if sharded, None if single mode (creates locally)
                    tool_handler_shards=self.tool_shards if hasattr(self, 'tool_shards') and self.tool_shards else None,
                    # Stateful dependencies (pass config/ID instead of instances)
                    mw_manager_organ_id=organ_id,  # Pass organ_id, create MwManager locally in actor
                    checkpoint_cfg=self.checkpoint_cfg,
                    # OrganRegistry for Tier-1 registration (currently kept for backward compatibility)
                    organ_registry=self.organ_registry,
                )

                # Sanity check
                ok_ref = organ.health_check.remote()
                ok = await self._ray_await(ok_ref)
                if not ok:
                    raise RuntimeError(f"Organ {organ_id} failed health check.")

                self.organs[organ_id] = organ

                # Register organ in Tier-1 registry
                if self.organ_registry:
                    self.organ_registry.record_organ(organ_id, organ)

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
                
                # --- Pass all dependencies to the Organ actor ---
                organ = Organ.options(**actor_opts).remote(
                    organ_id=organ_id,
                    # Stateless dependencies
                    role_registry=self.role_registry,
                    cognitive_client_cfg=self._get_cognitive_client_config(),
                    ml_client_cfg=self._get_ml_client_config(),
                    # Config for creating connections (avoids serialization)
                    holon_fabric_config=self._get_holon_fabric_config(),
                    # Tool handler: pass shard handles if sharded, None if single mode (creates locally)
                    tool_handler_shards=self.tool_shards if hasattr(self, 'tool_shards') and self.tool_shards else None,
                    # Stateful dependencies (pass config/ID instead of instances)
                    mw_manager_organ_id=organ_id,  # Pass organ_id, create MwManager locally in actor
                    checkpoint_cfg=self.checkpoint_cfg,
                    # OrganRegistry for Tier-1 registration (currently kept for backward compatibility)
                    organ_registry=self.organ_registry,
                )

                # Sanity check
                ok_ref = organ.health_check.remote()
                ok = await self._ray_await(ok_ref)
                if not ok:
                    raise RuntimeError(f"Organ {organ_id} failed health check.")

                new_organs[organ_id] = organ

                # Register organ in Tier-1 registry
                if self.organ_registry:
                    self.organ_registry.record_organ(organ_id, organ)

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
        organs_to_process = target_organs if target_organs is not None else self.organ_configs

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

                # 1. Resolve Specialization
                try:
                    spec = Specialization[spec_str.upper()]
                except KeyError:
                    logger.error(
                        f"❌ Invalid specialization '{spec_str}' in organ {organ_id}"
                    )
                    continue

                # 1a. Architectural Rule: USER_LIAISON → ConversationAgent (implicit)
                # ConversationAgent is a runtime capability, not a specialization.
                # Only USER_LIAISON agents should be ConversationAgents by default.
                # This ensures proper ownership of params.chat and episodic conversation memory.
                #
                # Production semantics: Only USER_LIAISON owns params.chat and agent-tunnel
                # interactions. YAML can override for debugging/experimentation, but this is
                # discouraged in production.
                if agent_class_name == "ConversationAgent" and spec != Specialization.USER_LIAISON:
                    logger.warning(
                        f"[OrganismCore] ConversationAgent used for non-USER_LIAISON specialization "
                        f"({spec.value}) in {organ_id}. This is supported for development but "
                        "discouraged in production. Only USER_LIAISON should own params.chat."
                    )
                
                if spec == Specialization.USER_LIAISON and agent_class_name == "BaseAgent":
                    agent_class_name = "ConversationAgent"
                    logger.info(
                        f"[OrganismCore] Auto-assigning ConversationAgent to USER_LIAISON in {organ_id}"
                    )

                # 2. Update Routing Map (Last Write Wins)
                spec_val = spec.value
                self.organ_specs[spec_val] = organ_id

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
        spec: Specialization,
        agent_class_name: str,
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
            logger.info(f"♻️ Agent {agent_id} found in Ray (re-hydrated).")
            return False

        except ValueError:
            # Actor not found in Ray -> Actually create it.
            pass

        # C. Create via Organ (Remote Call)
        logger.info(f"✨ Spawning agent '{agent_id}' ({agent_class_name})...")

        # Get configuration-driven agent actor options
        agent_opts = self._get_agent_actor_options(agent_id)

        await organ_handle.create_agent.remote(
            agent_id=agent_id,
            specialization=spec,
            organ_id=organ_id,
            agent_class_name=agent_class_name,
            **agent_opts,  # Unpack: name, num_cpus, lifetime
        )

        self.agent_to_organ_map[agent_id] = organ_id
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
        Orchestrates execution on a specific agent.

        Flow:
        1. Resolve Agent (Get existing OR JIT Spawn)
        2. Execute (Normal OR High-Stakes)
        3. Manage Session (Tunnel Lifecycle)
        """
        # --- 1. Validation & Setup ---
        organ = self.organs.get(organ_id)
        if not organ:
            return {"success": False, "error": f"Organ '{organ_id}' not found"}

        # Normalize Payload to Dict (Mutable)
        task_dict = (
            payload.model_dump() if hasattr(payload, "model_dump") else payload
        ) or {}
        params = task_dict.get("params", {})

        try:
            # --- 2. Agent Resolution (JIT Handling) ---
            # We abstract the "Try Get -> Fail -> Spawn -> Retry" loop here
            agent_handle = await self._ensure_agent_handle(
                organ, organ_id, agent_id, params
            )

            if not agent_handle:
                return {
                    "success": False,
                    "error": f"Agent '{agent_id}' could not be provisioned.",
                    "retry": True,  # Allow retry after respawn completes
                }

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
                        await asyncio.wait_for(
                            asyncio.to_thread(ray.get, heartbeat_ref),
                            timeout=2.0,
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
                            f"[{agent_id}] Agent not ready (attempt {attempt + 1}/{max_readiness_checks}): {e}. "
                            f"Waiting {readiness_check_delay}s before retry..."
                        )
                        await asyncio.sleep(readiness_check_delay)
                        readiness_check_delay *= 2  # Exponential backoff
                    else:
                        self.logger.warning(
                            f"[{agent_id}] Agent handle exists but not responding after {max_readiness_checks} attempts. "
                            f"Agent may be respawning. Error: {e}"
                        )
            
            if not agent_ready:
                return {
                    "success": False,
                    "error": f"Agent '{agent_id}' is not ready (may be respawning). Please retry.",
                    "retry": True,  # Allow retry after agent becomes ready
                    "agent_status": "respawning_or_unavailable",
                }

            if agent_handle:
                self.logger.info(
                    f"[OrganismCore] Agent handle resolved and ready: {agent_id} in {organ_id}"
                )

            # --- 3. Execution Logic ---
            # Priority: Trust the Router's decision envelope first
            router_meta = params.get("_router", {})
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
                        f"[{agent_id}] High-stakes requested but handler missing. Downgrading."
                    )
                ref = agent_handle.execute_task.remote(task_dict)

            # Await Result (Native Async)
            # We use asyncio.wait_for to enforce timeouts at the Router level
            try:
                result = await asyncio.wait_for(ref, timeout=timeout)
            except asyncio.CancelledError:
                # If cancelled, check if agent is still alive
                self.logger.warning(
                    f"[{agent_id}] Task execution was cancelled. Agent may be respawning."
                )
                raise  # Re-raise to propagate cancellation

            # --- 4. Tunnel Lifecycle (Side Effect) ---
            # Manage sticky sessions based on the result
            await self._manage_tunnel_lifecycle(task_dict, result, agent_id)

            # --- 5. Return Standardized Response ---
            return {
                "success": True,
                "organ_id": organ_id,
                "agent_id": agent_id,
                "result": result,
            }

        except asyncio.CancelledError:
            # Task was cancelled - likely due to agent respawning or upstream cancellation
            self.logger.warning(
                f"[Execute] Task execution cancelled for {agent_id}. "
                f"Agent may be respawning or request was cancelled upstream."
            )
            return {
                "success": False,
                "error": f"Task execution was cancelled. Agent '{agent_id}' may be respawning.",
                "retry": True,  # Allow retry after agent becomes ready
                "agent_status": "cancelled_or_respawning",
            }
        except asyncio.TimeoutError:
            self.logger.error(f"[Execute] Timeout on {agent_id} after {timeout}s")
            return {"success": False, "error": "Execution Timed Out"}

        except Exception as e:
            self.logger.error(
                f"[Execute] Critical failure on {agent_id}: {e}", exc_info=True
            )
            return {"success": False, "error": f"Execution Exception: {str(e)}"}

    # =========================================================
    # 🔧 HELPER: JIT PROVISIONING
    # =========================================================
    async def _ensure_agent_handle(
        self, organ: Any, organ_id: str, agent_id: str, params: dict
    ) -> Optional[Any]:
        """
        Tries to fetch an agent handle. If missing, attempts JIT spawn.
        """
        # 1. Optimistic Fetch (Fast Path)
        handle = await organ.get_agent_handle.remote(agent_id)
        if handle:
            return handle

        # 2. Not Found - Start JIT Sequence
        self.logger.info(
            f"[{organ_id}] Agent {agent_id} missing. Initiating JIT spawn."
        )

        # Determine Specialization for the new agent
        routing = params.get("routing", {})
        spec_str = (
            routing.get("required_specialization")
            or routing.get("specialization")
            or "GENERALIST"
        )

        # Spawn via Organ Actor
        spawn_success = await self._jit_spawn_agent(organ, organ_id, agent_id, spec_str)

        if spawn_success:
            # 3. Retry Fetch
            return await organ.get_agent_handle.remote(agent_id)

        return None

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
                    f"❌ Config Update Failed: {e}. Executing Rollback...", exc_info=True
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
            
            new_organ = Organ.options(**actor_opts).remote(
                organ_id=organ_id,
                # Stateless dependencies
                role_registry=self.role_registry,
                cognitive_client_cfg=self._get_cognitive_client_config(),
                ml_client_cfg=self._get_ml_client_config(),
                # Config for creating connections (avoids serialization)
                holon_fabric_config=self._get_holon_fabric_config(),
                # Tool handler: pass shard handles if sharded, None if single mode (creates locally)
                tool_handler_shards=self.tool_shards if hasattr(self, 'tool_shards') and self.tool_shards else None,
                # Stateful dependencies (pass config/ID instead of instances)
                mw_manager_organ_id=organ_id,  # Pass organ_id, create MwManager locally in actor
                checkpoint_cfg=self.checkpoint_cfg,
                # OrganRegistry for Tier-1 registration (currently kept for backward compatibility)
                organ_registry=self.organ_registry,
            )
        except Exception as e:
            logger.error(f"[OrganismCore] Failed to recreate organ: {e}")
            return

        self.organs[organ_id] = new_organ

        # Register organ in Tier-1 registry
        if self.organ_registry:
            self.organ_registry.record_organ(organ_id, new_organ)

        logger.info(f"[OrganismCore] Organ `{organ_id}` recreated")

        # Respawn agents
        for agent_def in cfg.get("agents", []):
            try:
                spec = Specialization[agent_def["specialization"].upper()]
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
