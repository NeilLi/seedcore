import ray  # pyright: ignore[reportMissingImports]
from typing import Dict, Any, Optional
from .manager import ToolManager

@ray.remote(num_cpus=0.1)
class ToolManagerShard:
    def __init__(
        self,
        holon_fabric_config: Dict[str, Any],
        mw_manager_cfg: Optional[Dict[str, Any]] = None,
        cognitive_client_cfg: Optional[Dict[str, Any]] = None,
        ml_client_cfg: Optional[Dict[str, Any]] = None,
        mcp_client_cfg: Optional[Dict[str, Any]] = None,
    ):
        # Store configs for lazy initialization (avoids serialization issues)
        # CRITICAL: All clients/managers must be created INSIDE the actor, not passed in
        self._holon_fabric_config = holon_fabric_config
        self._mw_manager_cfg = mw_manager_cfg
        self._mw_manager = None
        self._cognitive_client_cfg = cognitive_client_cfg
        self._cognitive_client = None
        self._ml_client_cfg = ml_client_cfg
        self._ml_client = None
        self._mcp_client_cfg = mcp_client_cfg
        self._mcp_client = None
        self._manager: Optional[ToolManager] = None
    
    def _get_cognitive_client(self):
        """Lazily create CognitiveServiceClient from config to avoid serialization issues."""
        if self._cognitive_client is None and self._cognitive_client_cfg:
            from ..serve.cognitive_client import CognitiveServiceClient
            from ..serve.base_client import CircuitBreaker, RetryConfig
            
            cfg = self._cognitive_client_cfg
            circuit_breaker = CircuitBreaker(
                failure_threshold=cfg.get("circuit_breaker", {}).get("failure_threshold", 5),
                recovery_timeout=cfg.get("circuit_breaker", {}).get("recovery_timeout", 30.0),
            )
            retry_config = RetryConfig(
                max_attempts=cfg.get("retry_config", {}).get("max_attempts", 1),
                base_delay=cfg.get("retry_config", {}).get("base_delay", 1.0),
                max_delay=cfg.get("retry_config", {}).get("max_delay", 5.0),
            )
            
            # Create client with explicit config (bypassing __init__ env var logic)
            # We create an instance without calling __init__, then initialize BaseServiceClient directly
            self._cognitive_client = object.__new__(CognitiveServiceClient)
            from ..serve.base_client import BaseServiceClient
            BaseServiceClient.__init__(
                self._cognitive_client,
                service_name="cognitive_service",
                base_url=cfg["base_url"],
                timeout=cfg.get("timeout", 75.0),
                circuit_breaker=circuit_breaker,
                retry_config=retry_config,
            )
        
        return self._cognitive_client
    
    def _get_ml_client(self):
        """Lazily create MLServiceClient from config to avoid serialization issues."""
        if self._ml_client is None and self._ml_client_cfg:
            from ..serve.ml_client import MLServiceClient
            from ..serve.base_client import CircuitBreaker, RetryConfig
            
            cfg = self._ml_client_cfg
            circuit_breaker = CircuitBreaker(
                failure_threshold=cfg.get("circuit_breaker", {}).get("failure_threshold", 5),
                recovery_timeout=cfg.get("circuit_breaker", {}).get("recovery_timeout", 30.0),
            )
            retry_config = RetryConfig(
                max_attempts=cfg.get("retry_config", {}).get("max_attempts", 2),
                base_delay=cfg.get("retry_config", {}).get("base_delay", 1.0),
                max_delay=cfg.get("retry_config", {}).get("max_delay", 5.0),
            )
            
            # Create client with explicit config
            self._ml_client = object.__new__(MLServiceClient)
            from ..serve.base_client import BaseServiceClient
            BaseServiceClient.__init__(
                self._ml_client,
                service_name="ml_service",
                base_url=cfg["base_url"],
                timeout=cfg.get("timeout", 10.0),
                circuit_breaker=circuit_breaker,
                retry_config=retry_config,
            )
            # Set warmup_timeout if present
            if "warmup_timeout" in cfg:
                self._ml_client.warmup_timeout = cfg["warmup_timeout"]
        
        return self._ml_client
    
    def _get_mcp_client(self):
        """Lazily create MCPServiceClient from config to avoid serialization issues."""
        if self._mcp_client is None and self._mcp_client_cfg:
            from ..serve.mcp_client import MCPServiceClient
            from ..serve.base_client import CircuitBreaker, RetryConfig
            
            cfg = self._mcp_client_cfg
            circuit_breaker = CircuitBreaker(
                failure_threshold=cfg.get("circuit_breaker", {}).get("failure_threshold", 5),
                recovery_timeout=cfg.get("circuit_breaker", {}).get("recovery_timeout", 30.0),
            )
            retry_config = RetryConfig(
                max_attempts=cfg.get("retry_config", {}).get("max_attempts", 1),
                base_delay=cfg.get("retry_config", {}).get("base_delay", 1.0),
                max_delay=cfg.get("retry_config", {}).get("max_delay", 5.0),
            )
            
            # Create client with explicit config
            self._mcp_client = object.__new__(MCPServiceClient)
            from ..serve.base_client import BaseServiceClient
            BaseServiceClient.__init__(
                self._mcp_client,
                service_name="mcp_service",
                base_url=cfg["base_url"],
                timeout=cfg.get("timeout", 30.0),
                circuit_breaker=circuit_breaker,
                retry_config=retry_config,
            )
        
        return self._mcp_client
    
    def _get_mw_manager(self):
        """Lazily create MwManager from config to avoid serialization issues."""
        if self._mw_manager is None and self._mw_manager_cfg:
            from ..memory.mw_manager import MwManager
            organ_id = self._mw_manager_cfg.get("organ_id", "tool_manager_shard")
            self._mw_manager = MwManager(organ_id=organ_id)
        
        return self._mw_manager
    
    async def _ensure_manager(self):
        """Lazily initialize ToolManager with local connections."""
        if self._manager is None:
            # Import here to avoid circular imports
            from ..memory.holon_fabric import HolonFabric
            from ..memory.backends.pgvector_backend import PgVectorStore
            from ..memory.backends.neo4j_graph import Neo4jGraph
            from ..database import PG_DSN, NEO4J_URI, NEO4J_BOLT_URL, NEO4J_USER, NEO4J_PASSWORD
            from ..organs.organism_core import HolonFabricSkillStoreAdapter
            
            # Create HolonFabric with local connections
            # Support both structured (new) and flat (legacy) config formats
            pg_cfg = self._holon_fabric_config.get("pg", {})
            neo4j_cfg = self._holon_fabric_config.get("neo4j", {})
            
            pg_store = PgVectorStore(
                dsn=pg_cfg.get("dsn") or self._holon_fabric_config.get("pg_dsn", PG_DSN),
                pool_size=pg_cfg.get("pool_size") or self._holon_fabric_config.get("pg_pool_size", 2),
                pool_min_size=1,
            )
            neo4j_uri = neo4j_cfg.get("uri") or self._holon_fabric_config.get("neo4j_uri") or NEO4J_URI or NEO4J_BOLT_URL
            neo4j_graph = Neo4jGraph(
                neo4j_uri,
                auth=(
                    neo4j_cfg.get("user") or self._holon_fabric_config.get("neo4j_user", NEO4J_USER),
                    neo4j_cfg.get("password") or self._holon_fabric_config.get("neo4j_password", NEO4J_PASSWORD),
                ),
            )
            
            # Initialize connections
            # Neo4j driver is lazy, so we just verify pg_store connection
            await pg_store._get_pool()
            
            holon_fabric = HolonFabric(
                vec_store=pg_store,
                graph=neo4j_graph,
                embedder=None,
            )
            
            skill_store = HolonFabricSkillStoreAdapter(holon_fabric)
            
            self._manager = ToolManager(
                skill_store=skill_store,
                mw_manager=self._get_mw_manager(),
                holon_fabric=holon_fabric,
                cognitive_client=self._get_cognitive_client(),
                ml_client=self._get_ml_client(),
                mcp_client=self._get_mcp_client(),
            )
        
        return self._manager
    
    @property
    def manager(self) -> ToolManager:
        """Lazy accessor for manager (creates on first access)."""
        if self._manager is None:
            raise RuntimeError("ToolManager not initialized. Call _ensure_manager() first.")
        return self._manager

    async def execute_tool(self, agent_id, name, args):
        manager = await self._ensure_manager()
        return await manager.execute(name, args, agent_id)

    async def register_tool(self, name, tool):
        manager = await self._ensure_manager()
        await manager.register(name, tool)
    
    async def register_tuya_tools(self):
        """
        Register Tuya tools if Tuya is enabled. Called internally after manager creation.
        
        Note: Tuya tools are designed for device control actions (domain="device").
        They should only be used by OrchestrationAgent for device orchestration tasks.
        """
        try:
            from seedcore.config.tuya_config import TuyaConfig
            
            tuya_config = TuyaConfig()
            if not tuya_config.enabled:
                return False
            
            manager = await self._ensure_manager()
            
            # Import and create tools inside the actor (avoids serialization issues)
            from seedcore.tools.tuya.tuya_tools import TuyaGetStatusTool, TuyaSendCommandTool
            
            await manager.register_internal(TuyaGetStatusTool())
            await manager.register_internal(TuyaSendCommandTool())
            
            # Register capability flag for feature detection
            if hasattr(manager, "add_capability"):
                await manager.add_capability("device.vendor.tuya")
            
            return True
        except Exception as e:
            # Log but don't fail - Tuya is optional
            import logging
            logger = logging.getLogger("seedcore.tools.manager_actor")
            logger.warning(f"Failed to register Tuya tools in shard: {e}")
            return False

    async def list_tools(self):
        manager = await self._ensure_manager()
        return await manager.list_tools()

    async def stats(self):
        manager = await self._ensure_manager()
        return await manager.stats()
    
    async def add_capability(self, capability: str):
        """Add a capability flag to the manager."""
        manager = await self._ensure_manager()
        if hasattr(manager, "add_capability"):
            await manager.add_capability(capability)
    
    async def has_capability(self, capability: str) -> bool:
        """Check if a capability is available."""
        manager = await self._ensure_manager()
        if hasattr(manager, "has_capability"):
            return await manager.has_capability(capability)
        return False
    
    async def list_capabilities(self):
        """Get all registered capabilities."""
        manager = await self._ensure_manager()
        if hasattr(manager, "list_capabilities"):
            return await manager.list_capabilities()
        return set()

