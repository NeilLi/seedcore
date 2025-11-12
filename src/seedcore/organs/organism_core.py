# Copyright 2024 SeedCore Contributors
# ... (license) ...

"""
OrganismCore - Manages the lifecycle of Organs and routes tasks to them.

This refactored manager implements a specialization-based routing strategy
consistent with the new BaseAgent and TaskPayload architecture.

It is no longer responsible for agent-level routing, only for routing
tasks to the correct Organ based on the task's 'required_specialization'.
"""

from __future__ import annotations

import yaml  # pyright: ignore[reportMissingModuleSource]
import asyncio
import ray  # pyright: ignore[reportMissingImports]
import os
import random
from pathlib import Path
from typing import Dict, List, Any, Optional

# --- Core SeedCore Imports ---
# Assumes 'Organ' is the class name for your Tier0MemoryManager actor
from .base import Organ  
from .tier0 import tier0_manager 
from ..models import TaskPayload
from seedcore.agents.roles.specialization import Specialization
from seedcore.logging_setup import setup_logging, ensure_serve_logger

setup_logging(app_name="seedcore.organism")
logger = ensure_serve_logger("seedcore.OrganismCore", level="DEBUG")

# Target namespace for agent actors
AGENT_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
ORGANS_CONFIG_PATH = os.getenv("ORGANS_CONFIG_PATH", "/app/config/organs.yaml")

def _env_bool(name: str, default: bool = False) -> bool:
    """Robust environment variable parsing for boolean values."""
    val = os.getenv(name)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "y", "on")


class OrganismCore:
    """
    Manages all Organs (Tier0MemoryManagers) and routes incoming work
    based on required agent specializations.
    """

    def __init__(self, config_path = Path(ORGANS_CONFIG_PATH)):
        self.organs: Dict[str, ray.actor.ActorHandle] = {}
        self._lock = asyncio.Lock()
        
        # --- REFACTORED: This map is the new routing table ---
        # It maps a Specialization to the organ_id that manages it.
        self.specialization_to_organ: Dict[Specialization, str] = {}
        
        # This is a simple cache, not a routing table
        self.agent_to_organ_map: Dict[str, str] = {}
        
        self.organ_configs: List[Dict[str, Any]] = []
        self._load_config(config_path)
        self._initialized = False

        # Background tasks
        self._health_check_task: Optional[asyncio.Task] = None
        self._health_check_interval = 30  # seconds
        self._recon_task: Optional[asyncio.Task] = None
        
        # DB session
        self._session_factory = None
        try:
            from seedcore.database import get_async_pg_session_factory
            self._session_factory = get_async_pg_session_factory()
        except Exception as exc:
            logger.warning(f"Failed to initialize database session factory: {exc}")

        # Agent graph repo (for logging)
        self._agent_graph_repo = None
        self._agent_graph_repo_checked = False
        
        # Reconciliation tuning
        self._reconcile_grace_s = int(os.getenv("RECONCILE_GRACE_S", "15"))
        self._maintenance_interval_s = int(os.getenv("MAINTENANCE_INTERVAL_S", "15"))


    # -------------------------------------------------------------------------
    # Config / Ray helpers (Largely unchanged)
    # -------------------------------------------------------------------------
    def _load_config(self, config_path: str):
        """Loads the organism configuration from a YAML file."""
        try:
            path = Path(config_path)
            with open(path, 'r') as f:
                config = yaml.safe_load(f)
                # REFACTORED: Assume new config structure
                self.organ_configs = config['seedcore']['organism']['organs']
                logger.info(f"Loaded organism configuration with {len(self.organ_configs)} organ definitions")
        except Exception as e:
            logger.error(f"Error loading organism config from {config_path}: {e}", exc_info=True)
            self.organ_configs = []

    async def _async_ray_get(self, remote_call, timeout: float = 30.0):
        """Async wrapper for ray.get calls."""
        return await asyncio.to_thread(ray.get, remote_call, timeout=timeout)

    async def _async_ray_actor(self, name: str, namespace: Optional[str] = None):
        """Async wrapper for ray.get_actor calls."""
        loop = asyncio.get_event_loop()
        namespace = namespace or AGENT_NAMESPACE
        try:
            return await loop.run_in_executor(
                None,
                lambda: ray.get_actor(name, namespace=namespace)
            )
        except Exception as e:
            logger.debug(f"ray.get_actor could not find '{name}' in namespace '{namespace}': {e}")
            raise

    async def _call_actor_method(
        self,
        actor_handle: Any,
        method_name: str,
        *args,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> Any:
        """Invoke a Ray actor method or coroutine-friendly mock."""
        method = getattr(actor_handle, method_name, None)
        if method is None:
            raise AttributeError(f"{actor_handle!r} has no attribute '{method_name}'")

        if hasattr(method, "remote"):
            remote_call = method.remote(*args, **kwargs)
            return await self._async_ray_get(remote_call, timeout=timeout or 30.0)
        
        result = method(*args, **kwargs)
        return await result if asyncio.iscoroutine(result) else result

    # -------------------------------------------------------------------------
    # REFACTORED: Initialization and Agent Spawning
    # -------------------------------------------------------------------------

    async def initialize_organism(self, *args, **kwargs):
        """Create all organs and populate them with agents based on the config."""
        if self._initialized:
            logger.warning("Organism already initialized. Skipping re-initialization.")
            return

        logger.info("🚀 Initializing the Cognitive Organism...")
        self.specialization_to_organ.clear()

        if not ray.is_initialized():
            raise RuntimeError("Ray is not initialized. Ensure connection before initialize_organism().")

        # ... (Bootstrap actors, init Tier0Manager, etc. - unchanged) ...
        # (Assuming initialize_global_tier0_manager() is called elsewhere)

        try:
            await self._check_ray_cluster_health()
            
            logger.info("🏗️ Creating Organs...")
            await self._create_organs_from_config()

            logger.info("🤖 Creating and distributing Agents...")
            await self._create_and_distribute_agents_from_config()

            if _env_bool("ORGANISM_HEALTHCHECKS", True):
                await self._start_background_health_checks()
            
            self._initialized = True
            logger.info("✅ Organism initialization complete.")
            
            if _env_bool("ORGANISM_RECONCILE", True):
                if self._recon_task is None or self._recon_task.done():
                    self._recon_task = asyncio.create_task(self._reconcile_loop())
                    logger.info("✅ Started registry reconciliation loop")

        except Exception as e:
            logger.error(f"❌ Organism initialization failed: {e}", exc_info=True)
            raise

    async def _create_organs_from_config(self):
        """Create organ actors from configuration."""
        logger.info(f"📋 Found {len(self.organ_configs)} organ configs.")
        for config in self.organ_configs:
            organ_id = config['id']
            organ_type = config.get('type', 'Tier0MemoryManager') # Default to Tier0
            
            if organ_id in self.organs:
                logger.info(f"✅ Organ {organ_id} already running.")
                continue

            try:
                logger.info(f"🔍 Attempting to get existing organ: {organ_id}")
                try:
                    # Try to get existing actor handle
                    existing_organ = await self._async_ray_actor(organ_id, namespace=AGENT_NAMESPACE)
                    logger.info(f"✅ Retrieved existing Organ: {organ_id} from namespace '{AGENT_NAMESPACE}'")
                    
                    if not await self._test_organ_health_async(existing_organ, organ_id):
                        logger.warning(f"⚠️ Organ {organ_id} is unresponsive, recreating...")
                        raise ValueError("Organ unresponsive")
                        
                    async with self._lock:
                        self.organs[organ_id] = existing_organ

                except Exception:
                    # Not found or unresponsive, create new one
                    logger.info(f"🚀 Creating new organ: {organ_id} (Type: {organ_type})")
                    # Assumes 'Organ' is the Tier0MemoryManager class
                    organ_handle = Organ.options(
                        name=organ_id,
                        lifetime="detached",
                        num_cpus=0.1, # Keep organs lightweight
                        namespace=AGENT_NAMESPACE
                    ).remote(
                        # Pass dependencies needed by Tier0Manager
                        organ_id=organ_id, 
                        # We must ensure the global manager's clients are ready
                        mw_manager=tier0_manager.mw_manager, 
                        ltm_manager=tier0_manager.ltm_manager,
                        role_registry=tier0_manager._role_registry,
                        skill_store=tier0_manager._skill_store
                    )
                    
                    if not await self._test_organ_health_async(organ_handle, organ_id):
                        raise Exception(f"New organ {organ_id} failed health check")
                    async with self._lock:
                        self.organs[organ_id] = organ_handle

            except Exception as e:
                logger.error(f"❌ Failed to create/get organ {organ_id}: {e}")
                raise
        logger.info(f"🏗️ Organ creation complete. Total organs: {len(self.organs)}")

    async def _create_and_distribute_agents_from_config(self):
        """
        Create agents with specific specializations and register them
        with their designated organs.
        """
        agent_count = 0
        for config in self.organ_configs:
            organ_id = config['id']
            agent_definitions = config.get('agents', [])
            
            organ_handle = self.organs.get(organ_id)
            if not organ_handle:
                logger.warning(f"Organ '{organ_id}' not found. Skipping agent creation.")
                continue

            logger.info(f"🤖 Distributing agents for organ {organ_id}...")
            
            create_tasks = []
            for agent_def in agent_definitions:
                try:
                    spec_str = agent_def['specialization']
                    spec_enum = Specialization[spec_str.upper()]
                    count = int(agent_def.get('count', 1))

                    for i in range(count):
                        agent_id = f"{organ_id}_{spec_str.lower()}_{i}"
                        
                        # Call the Organ's (Tier0Manager's) create_agent method
                        # This method is now "role-aware"
                        create_tasks.append(self._call_actor_method(
                            organ_handle,
                            "create_agent",
                            agent_id=agent_id,
                            specialization=spec_enum,
                            organ_id=organ_id,
                            name=agent_id, # Ray actor name
                            lifetime="detached",
                            num_cpus=0.1
                        ))
                        
                        # --- Update routing maps ---
                        self.agent_to_organ_map[agent_id] = organ_id
                        if spec_enum not in self.specialization_to_organ:
                            self.specialization_to_organ[spec_enum] = organ_id
                        
                        agent_count += 1
                        logger.debug(f"Spawned agent {agent_id} (Spec: {spec_str}) in {organ_id}")

                except KeyError:
                    logger.error(f"Invalid specialization '{spec_str}' in config for organ {organ_id}.")
                except Exception as e:
                    logger.error(f"Failed to create agent for {organ_id}: {e}", exc_info=True)

            if create_tasks:
                await asyncio.gather(*create_tasks, return_exceptions=False)

        logger.info(f"✅ Created and distributed {agent_count} agents across {len(self.organs)} organs.")
        logger.info(f"🗺️ Specialization routing map built: { {k.name: v for k,v in self.specialization_to_organ.items()} }")

    # -------------------------------------------------------------------------
    # REFACTORED: INCOMING TASK HANDLER
    # -------------------------------------------------------------------------
    async def handle_incoming_task(
        self, 
        task: Dict[str, Any], 
        app_state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Unified handler for incoming tasks addressed to the Organism (local).
        
        Routing logic:
        1. Parse task into a unified TaskPayload object.
        2. Check for "Builtin Handlers" (from app_state).
        3. Check for "Local API Handlers" (e.g., get_organism_status).
        4. (DEFAULT) Route "Work Tasks" to the correct Organ based on
           the task's 'required_specialization' field.
        """
        
        # --- 1. Parse and Validate Task ---
        task_obj: TaskPayload

        if isinstance(task, TaskPayload):
            task_obj = task
        else:
            try:
                source_payload = task if isinstance(task, dict) else task.model_dump()  # type: ignore[call-arg]
                task_obj = TaskPayload.from_db(source_payload)
            except Exception as exc:
                logger.error(f"[OrganismManager] ❌ Failed to parse task payload: {exc}. Payload: {task}")
                return {"success": False, "error": f"Invalid task payload: {exc}"}

        task_id = task_obj.task_id
        task_type = (task_obj.type or "").strip().lower()
        params = task_obj.params
        
        logger.info(f"[OrganismCore] 🎯 Received task {task_id} (Type: {task_type})")
        if not task_type:
            return {"success": False, "error": "task.type is required"}

        # --- 2. Route "Builtin Handlers" (app_state) ---
        if app_state is not None:
            handlers = app_state.get("builtin_task_handlers", {}) or {}
            handler = handlers.get(task_type)
            if callable(handler):
                logger.info(f"[OrganismCore]  Routing '{task_type}' to builtin handler.")
                try:
                    out = handler() if not params else handler(**params)
                    if asyncio.iscoroutine(out):
                        out = await out
                    return {"success": True, "path": "builtin", "result": out}
                except Exception as e:
                    logger.exception(f"[OrganismCore] ❌ Builtin task '{task_type}' failed: {e}")
                    return {"success": False, "path": "builtin", "error": str(e)}

        # --- 3. Route "Local API Handlers" (Management tasks) ---
        # These are tasks for the OrganismCore itself.
        if task_type == "get_organism_status":
            return await self._api_get_organism_status()
            
        elif task_type == "get_organism_summary":
            return await self._api_get_organism_summary()

        elif task_type == "initialize_organism":
            return await self._api_initialize_organism()
            
        elif task_type == "shutdown_organism":
            return await self._api_shutdown_organism()
            
        elif task_type == "debug_namespace":
            return await self._api_debug_namespace()
        
        elif task_type == "execute_on_organ":
            # This is a "manual override" route for direct delegation.
            return await self._api_execute_on_organ(params, task_obj)
            
        elif task_type == "execute_on_random_organ":
            # This is also a "manual override" route.
            return await self._api_execute_on_random_organ(params, task_obj)

        # --- 4. DEFAULT: Route "Work Tasks" via Specialization ---
        # Any task_type not caught above is treated as a work task.
        # This replaces all the hardcoded 'elif task_type in ("graph_embed", ...)'
        else:
            logger.debug(f"[OrganismCore]  Routing '{task_type}' as general work task.")
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}

                # a) Get the required specialization from the task payload
                spec_str = task_obj.required_specialization
                if not spec_str:
                    logger.warning(f"Task {task_id} (type {task_type}) is a work task but has no 'required_specialization'")
                    return {"success": False, "error": f"Task {task_id} (type {task_type}) requires 'required_specialization' for routing."}

                # b) Find the Organ that hosts this specialization
                try:
                    spec_enum = Specialization(spec_str)
                except ValueError:
                    try:
                        spec_enum = Specialization[spec_str.upper()]
                    except KeyError:
                        return {"success": False, "error": f"Unknown specialization: {spec_str}"}

                organ_id = self.specialization_to_organ.get(spec_enum)
                if not organ_id:
                    logger.error(f"No organ found for specialization '{spec_str}'")
                    return {"success": False, "error": f"No organ registered to handle specialization: {spec_str}"}

                # c) Delegate the *entire* task object to that Organ
                # The Organ's internal router will handle agent selection.
                logger.info(f"🔀 Routing task {task_id} (spec: {spec_str}) to Organ {organ_id}")
                task_to_delegate = task_obj.model_dump()
                
                result = await self.execute_task_on_organ(organ_id, task_to_delegate)
                return {"success": True, "path": "specialization_router", "result": result}
            
            except Exception as e:
                logger.exception(f"Failed to route work task {task_id}: {e}")
                return {"success": False, "path": "specialization_router", "error": str(e)}

    # -------------------------------------------------------------------------
    # Local API Handler Implementations
    # -------------------------------------------------------------------------

    async def _api_get_organism_status(self) -> Dict[str, Any]:
        try:
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}
            status = await self.get_organism_status()
            return {"success": True, "path": "api_handler", "result": status}
        except Exception as e:
            return {"success": False, "path": "api_handler", "error": str(e)}

    async def _api_execute_on_organ(self, params: Dict[str, Any], task_obj: TaskPayload) -> Dict[str, Any]:
        try:
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}
            organ_id = params.get("organ_id")
            if not organ_id:
                return {"success": False, "error": "organ_id is required"}
            
            # Default 'task_data' to the full task payload
            task_data = params.get("task_data", task_obj.model_dump()) 
            
            result = await self.execute_task_on_organ(organ_id, task_data)
            return {"success": True, "path": "api_handler", "result": result}
        except Exception as e:
            return {"success": False, "path": "api_handler", "error": str(e)}

    async def _api_execute_on_random_organ(self, params: Dict[str, Any], task_obj: TaskPayload) -> Dict[str, Any]:
        try:
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}
            task_data = params.get("task_data", task_obj.model_dump())
            result = await self.execute_task_on_random_organ(task_data)
            return {"success": True, "path": "api_handler", "result": result}
        except Exception as e:
            return {"success": False, "path": "api_handler", "error": str(e)}

    async def _api_get_organism_summary(self) -> Dict[str, Any]:
        try:
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}
            summary = {
                "initialized": self.is_initialized(),
                "organ_count": self.get_organ_count(),
                "total_agent_count": self.get_total_agent_count(),
                "specialization_map": {k.value: v for k, v in self.specialization_to_organ.items()},
                "organs": {}
            }
            for organ_id in self.organs.keys():
                organ_handle = self.get_organ_handle(organ_id)
                if organ_handle:
                    try:
                        status = await self._call_actor_method(organ_handle, "get_status")
                        summary["organs"][organ_id] = status
                    except Exception as e:
                        summary["organs"][organ_id] = {"error": str(e)}
            return {"success": True, "path": "api_handler", "result": summary}
        except Exception as e:
            return {"success": False, "path": "api_handler", "error": str(e)}

    async def _api_initialize_organism(self) -> Dict[str, Any]:
        try:
            if self._initialized:
                return {"success": True, "path": "api_handler", "result": "Organism already initialized"}
            await self.initialize_organism()
            return {"success": True, "path": "api_handler", "result": "Organism initialized successfully"}
        except Exception as e:
            return {"success": False, "path": "api_handler", "error": str(e)}

    async def _api_shutdown_organism(self) -> Dict[str, Any]:
        try:
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}
            await self.shutdown_organism()
            return {"success": True, "path": "api_handler", "result": "Organism shutdown successfully"}
        except Exception as e:
            return {"success": False, "path": "api_handler", "error": str(e)}

    async def _api_debug_namespace(self) -> Dict[str, Any]:
        try:
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}
            debug_info = {
                "expected_namespace": AGENT_NAMESPACE,
                "ray_initialized": ray.is_initialized(),
                "organs": {},
            }
            for organ_id, organ_handle in self.organs.items():
                try:
                    status = await self._call_actor_method(organ_handle, "get_status", timeout=5.0)
                    debug_info["organs"][organ_id] = {"status": "responsive", "status_data": status}
                except Exception as e:
                    debug_info["organs"][organ_id] = {"status": "error", "error": str(e)}
            return {"success": True, "path": "api_handler", "result": debug_info}
        except Exception as e:
            return {"success": False, "path": "api_handler", "error": str(e)}

    # -------------------------------------------------------------------------
    # Status / Delegation (Task Execution)
    # -------------------------------------------------------------------------
    async def get_organism_status(self) -> List[Dict[str, Any]]:
        """Collect and return status from all organs."""
        if not self._initialized:
            return [{"error": "Organism not initialized"}]
        refs = [organ.get_status.remote() for organ in self.organs.values()]
        results = await asyncio.gather(*refs, return_exceptions=True)
        return [{"error": str(r)} if isinstance(r, Exception) else r for r in results]

    def get_organ_handle(self, organ_id: str) -> Optional[ray.actor.ActorHandle]:
        return self.organs.get(organ_id)

    def get_total_agent_count(self) -> int:
        return len(self.agent_to_organ_map)

    def get_organ_count(self) -> int:
        return len(self.organs)

    def is_initialized(self) -> bool:
        return self._initialized

    async def execute_task_on_organ(self, organ_id: str, task_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a task on a specific organ.
        The organ (Tier0Manager) will perform its own internal routing.
        """
        if not self._initialized:
            raise RuntimeError("Organism not initialized")
        organ_handle = self.organs.get(organ_id)
        if not organ_handle:
            raise ValueError(f"Organ {organ_id} not found")

        task_id = task_dict.get('task_id', 'unknown')
        timeout_s = float(task_dict.get("organ_timeout_s", 30.0))

        try:
            # We call 'execute_task' on the Organ, which is the
            # Tier0Manager. It will then find the best agent.
            result_ref = organ_handle.execute_task_on_best_agent.remote(task_dict)
            result = await self._async_ray_get(result_ref, timeout=timeout_s)
            
            await self._update_task_status(task_id, "FINISHED", result=result)
            return {"success": True, "result": result, "organ_id": organ_id}
        except Exception as e:
            error_msg = f"Error executing task {task_id} on organ {organ_id}: {e}"
            logger.error(error_msg, exc_info=True)
            await self._update_task_status(task_id, "FAILED", error=error_msg)
            return {"success": False, "error": error_msg, "organ_id": organ_id}

    async def execute_task_on_random_organ(self, task_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a task on a randomly selected organ."""
        if not self.organs:
            raise RuntimeError("No organs available")
        
        organ_id = random.choice(list(self.organs.keys()))
        logger.info(f"Routing task {task_dict.get('task_id')} to random organ: {organ_id}")
        return await self.execute_task_on_organ(organ_id, task_dict)

    # -------------------------------------------------------------------------
    # Background Loops & Maintenance (Unchanged)
    # -------------------------------------------------------------------------
    
    async def _start_background_health_checks(self):
        # ... (implementation unchanged) ...
        pass
    
    async def _test_organ_health_async(self, organ_handle, organ_id: str) -> bool:
        # ... (implementation unchanged) ...
        try:
            status = await self._async_ray_get(organ_handle.get_status.remote(), timeout=10.0)
            return bool(status and status.get('organ_id') == organ_id)
        except Exception:
            return False

    async def shutdown_organism(self):
        logger.info("🛑 Shutting down organism...")
        if self._health_check_task:
            self._health_check_task.cancel()
        if self._recon_task:
            self._recon_task.cancel()
        # Logic to kill/shutdown self.organs can be added here
        self._initialized = False
        self.specialization_to_organ.clear()
        logger.info("✅ Organism shutdown complete")

    async def _reconcile_loop(self):
        # ... (implementation unchanged) ...
        pass
        
    async def _update_task_status(self, task_id: str, status: str, error: str = None, result: Any = None):
        # ... (implementation unchanged) ...
        pass
        
    def _get_agent_graph_repository(self):
        # ... (implementation unchanged) ...
        return None

    # ... (Other private methods like _cleanup_dead_actors, etc.) ...

# Global instance
organism_core: Optional[OrganismCore] = None

# You would typically call this in your main application startup
# async def startup_event():
#     global Organism_core
#     Organism_core = OrganismCore()
#     await Organism_core.initialize_organism()