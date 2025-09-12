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
OrganismManager - Manages the lifecycle of organs and the distribution of agents within them.
Implements the local, intra-organism control (no global Coordinator logic).

IMPORTANT (Ray client):
- ray.util.state APIs (list_actors, list_nodes, etc.) are NOT available
- Verify namespaces via actor communication tests
- Use actor handles for information; avoid state APIs
"""

from seedcore.logging_setup import setup_logging
setup_logging(app_name="seedcore.organism")

import yaml
import logging
import asyncio
import time
import ray
import os
import concurrent.futures
import numpy as np
import traceback
import random
from pathlib import Path
from typing import Dict, List, Any, Optional

from .base import Organ
from ..agents import tier0_manager

logger = logging.getLogger(__name__)

from seedcore.logging_setup import ensure_serve_logger

logger = ensure_serve_logger("seedcore.OrganismManager", level="DEBUG")

# Target namespace for agent actors (prefer SEEDCORE_NS, fallback to RAY_NAMESPACE)
AGENT_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))


class OrganismManager:
    """
    Local manager of organs and agents:
      - Creates organs & distributes agents
      - Executes tasks on specific/random organs
      - Performs health checks & basic summaries
      - Exposes state aggregation via a standalone StateService actor
    """

    def __init__(self, config_path: str = "src/seedcore/config/defaults.yaml"):
        self.organs: Dict[str, ray.actor.ActorHandle] = {}
        self.agent_to_organ_map: Dict[str, str] = {}
        self.organ_configs: List[Dict[str, Any]] = []
        self._load_config(config_path)
        self._initialized = False

        # Background health check task
        self._health_check_task: Optional[asyncio.Task] = None
        self._health_check_interval = 30  # seconds

        # State service connection (replaces local state aggregator)
        self._state_service = None

    # -------------------------------------------------------------------------
    # Config / Ray helpers
    # -------------------------------------------------------------------------
    def _load_config(self, config_path: str):
        """Loads the organism configuration from a YAML file."""
        try:
            path = Path(config_path)
            with open(path, 'r') as f:
                config = yaml.safe_load(f)
                self.organ_configs = config['seedcore']['organism']['organ_types']
                logger.info(f"Loaded organism configuration with {len(self.organ_configs)} organ types")
        except FileNotFoundError:
            logger.error(f"Configuration file not found at {config_path}")
            self.organ_configs = []
        except KeyError as e:
            logger.error(f"Missing required configuration key: {e}")
            self.organ_configs = []
        except Exception as e:
            logger.error(f"Error loading organism configuration: {e}")
            self.organ_configs = []

    async def _async_ray_get(self, remote_call, timeout: float = 30.0):
        """Async wrapper for ray.get calls to prevent blocking the event loop."""
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: ray.get(remote_call, timeout=timeout)
            )
            return result
        except Exception as e:
            logger.error(f"Async ray.get failed: {e}")
            raise

    async def _async_ray_actor(self, name: str, namespace: Optional[str] = None):
        """Async wrapper for ray.get_actor calls."""
        try:
            loop = asyncio.get_event_loop()
            if namespace is None:
                namespace = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
                logger.debug(f"🔍 Using default namespace '{namespace}' for actor '{name}'")
            actor = await loop.run_in_executor(
                None,
                lambda: ray.get_actor(name, namespace=namespace)
            )
            return actor
        except Exception as e:
            logger.error(f"Async ray.get_actor failed for '{name}' in namespace '{namespace}': {e}")
            raise

    async def get_agent_handle(self, agent_name: str) -> Optional[ray.actor.ActorHandle]:
        """Find a RayAgent actor handle by explicitly looking in the correct namespace."""
        try:
            namespace = AGENT_NAMESPACE
            logger.info(f"Searching for actor '{agent_name}' in namespace '{namespace}'...")
            handle = await self._async_ray_actor(agent_name, namespace=namespace)
            return handle
        except ValueError:
            logger.warning(f"Actor '{agent_name}' not found in namespace '{AGENT_NAMESPACE}'.")
            return None
        except Exception as e:
            logger.warning(f"Failed to get actor '{agent_name}' in namespace '{AGENT_NAMESPACE}': {e}")
            return None

    # -------------------------------------------------------------------------
    # Health / background checks
    # -------------------------------------------------------------------------
    async def _check_ray_cluster_health(self):
        """Check Ray cluster health and log diagnostic information."""
        try:
            cluster_resources = ray.cluster_resources()
            available_resources = ray.available_resources()

            logger.info(f"📊 Cluster resources: {cluster_resources}")
            logger.info(f"📊 Available resources: {available_resources}")

            total_cpu = cluster_resources.get('CPU', 0)
            available_cpu = available_resources.get('CPU', 0)

            if total_cpu == 0:
                raise Exception("No CPU resources available in Ray cluster")

            if available_cpu < 1.0:
                logger.warning(f"⚠️ Low CPU availability: {available_cpu}/{total_cpu} CPUs available")

            try:
                @ray.remote
                def _health_check_task():
                    return "healthy"
                result = await self._async_ray_get(_health_check_task.remote())
                if result == "healthy":
                    logger.info("✅ Ray remote task execution test passed")
                else:
                    logger.warning(f"⚠️ Ray remote task test returned unexpected result: {result}")
            except Exception as e:
                logger.warning(f"Ray remote task test failed: {e}")

            logger.info("✅ Ray cluster health check completed")

        except Exception as e:
            logger.error(f"❌ Failed to check Ray cluster health: {e}")
            raise

    async def _start_background_health_checks(self):
        """Start background health check task to monitor organs and agents."""
        if self._health_check_task and not self._health_check_task.done():
            logger.info("Background health checks already running")
            return
        try:
            self._health_check_task = asyncio.create_task(self._background_health_check_loop())
            logger.info("✅ Background health checks started")
        except Exception as e:
            logger.error(f"❌ Failed to start background health checks: {e}")

    async def _stop_background_health_checks(self):
        """Stop background health check task."""
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            logger.info("✅ Background health checks stopped")

    async def _background_health_check_loop(self):
        """Background loop for health checks."""
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                await self._perform_background_health_checks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Background health check error: {e}")
                await asyncio.sleep(5)

    async def _perform_background_health_checks(self):
        """Perform health checks on organs and agents in the background."""
        try:
            logger.debug("🔄 Performing background health checks...")
            tasks = [asyncio.create_task(self._check_organ_health_async(h, oid))
                     for oid, h in self.organs.items()]
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for i, result in enumerate(results):
                    organ_id = list(self.organs.keys())[i]
                    if isinstance(result, Exception):
                        logger.warning(f"⚠️ Organ {organ_id} health check failed: {result}")
                    else:
                        logger.debug(f"✅ Organ {organ_id} health check passed")
            logger.debug("✅ Background health checks completed")
        except Exception as e:
            logger.error(f"❌ Background health checks failed: {e}")

    async def _check_organ_health_async(self, organ_handle, organ_id: str) -> bool:
        """Async version of organ health check."""
        try:
            status = await self._async_ray_get(organ_handle.get_status.remote(), timeout=10.0)
            if status and status.get('organ_id') == organ_id:
                return True
            else:
                logger.warning(f"⚠️ Organ {organ_id} status mismatch")
                return False
        except Exception as e:
            logger.warning(f"⚠️ Organ {organ_id} health check failed: {e}")
            return False

    def _test_organ_health(self, organ_handle, organ_id: str) -> bool:
        """Sync test if an organ actor is healthy and responsive."""
        try:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(lambda: ray.get(organ_handle.get_status.remote()))
                _ = future.result(timeout=10.0)
                logger.info(f"✅ Organ {organ_id} health check passed")
                return True
        except Exception as e:
            logger.warning(f"⚠️ Organ {organ_id} health check failed: {e}")
            return False

    async def _test_organ_health_async(self, organ_handle, organ_id: str) -> bool:
        """Async test if an organ actor is healthy and responsive."""
        try:
            status = await self._async_ray_get(organ_handle.get_status.remote(), timeout=10.0)
            if status and status.get('organ_id') == organ_id:
                logger.info(f"✅ Organ {organ_id} health check passed")
                return True
            logger.warning(f"⚠️ Organ {organ_id} status mismatch")
            return False
        except Exception as e:
            logger.warning(f"⚠️ Organ {organ_id} health check failed: {e}")
            return False

    async def _cleanup_dead_actors(self):
        """Use Janitor actor to reap dead actors, if present."""
        try:
            if not ray.is_initialized():
                return
            jan = None
            try:
                namespace = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
                jan = await self._async_ray_actor("seedcore_janitor", namespace=namespace)
            except Exception:
                logger.debug("Janitor actor not available; skipping cluster cleanup")
                jan = None

            if jan:
                try:
                    res = await self._async_ray_get(jan.reap.remote(prefix=None))
                    if res.get("count"):
                        logger.info("Cluster cleanup removed %d dead actors: %s", res["count"], res["reaped"])
                    else:
                        logger.debug("No dead actors found to clean up")
                except Exception as e:
                    logger.debug("Cluster cleanup failed: %s", e)
        except Exception as e:
            logger.debug("Cluster cleanup skipped: %s", e)

    # -------------------------------------------------------------------------
    # Organ / Agent lifecycle
    # -------------------------------------------------------------------------
    async def _recreate_dead_organ(self, organ_id: str, organ_type: str):
        """Recreate a dead organ actor."""
        try:
            logger.info(f"🔄 Recreating dead organ: {organ_id}")
            try:
                organ_namespace = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
                dead_actor = await self._async_ray_actor(organ_id, namespace=organ_namespace)
                ray.kill(dead_actor)
                logger.info(f"🗑️ Killed dead actor: {organ_id} from namespace '{organ_namespace}'")
            except Exception:
                logger.debug(f"Actor {organ_id} not found or already dead")

            ray_namespace = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
            try:
                new_organ = Organ.options(
                    name=organ_id,
                    lifetime="detached",
                    num_cpus=0.1,
                    namespace=ray_namespace
                ).remote(
                    organ_id=organ_id,
                    organ_type=organ_type
                )
                logger.info(f"✅ Created new organ with explicit namespace: {organ_id}")
            except Exception as e:
                logger.error(f"❌ Failed to create organ {organ_id} with namespace {ray_namespace}: {e}")
                raise

            if self._test_organ_health(new_organ, organ_id):
                self.organs[organ_id] = new_organ
                logger.info(f"✅ Successfully recreated organ: {organ_id}")
                return True
            else:
                logger.error(f"❌ Failed to create healthy organ: {organ_id}")
                return False

        except Exception as e:
            logger.error(f"❌ Failed to recreate organ {organ_id}: {e}")
            return False

    async def _create_organs(self):
        """Create organ actors from configuration."""
        logger.info(f"🏗️ Starting organ creation process...")
        logger.info(f"📋 Organ configs loaded: {len(self.organ_configs)}")
        logger.info(f"🔍 Current organs: {list(self.organs.keys())}")

        for config in self.organ_configs:
            organ_id = config['id']
            organ_type = config['type']
            logger.info(f"🔍 Processing organ config: {organ_id} (Type: {organ_type})")

            if organ_id not in self.organs:
                try:
                    logger.info(f"🔍 Attempting to get existing organ: {organ_id}")
                    try:
                        organ_namespace = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
                        existing_organ = await self._async_ray_actor(organ_id, namespace=organ_namespace)
                        logger.info(f"✅ Retrieved existing Organ: {organ_id} (Type: {organ_type}) from namespace '{organ_namespace}'")

                        if not await self._test_organ_health_async(existing_organ, organ_id):
                            logger.warning(f"⚠️ Organ {organ_id} is unresponsive, recreating...")
                            if await self._recreate_dead_organ(organ_id, organ_type):
                                continue
                            else:
                                raise Exception(f"Failed to recreate organ {organ_id}")

                        self.organs[organ_id] = existing_organ

                    except ValueError:
                        logger.info(f"🚀 Creating new organ: {organ_id} (Type: {organ_type})")
                        ray_namespace = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
                        try:
                            self.organs[organ_id] = Organ.options(
                                name=organ_id,
                                lifetime="detached",
                                num_cpus=0.1,
                                namespace=ray_namespace
                            ).remote(
                                organ_id=organ_id,
                                organ_type=organ_type
                            )
                            logger.info(f"✅ Created new Organ with explicit namespace: {organ_id}")
                        except Exception as e:
                            logger.error(f"❌ Failed to create organ {organ_id} with namespace {ray_namespace}: {e}")
                            raise

                        if not await self._test_organ_health_async(self.organs[organ_id], organ_id):
                            logger.error(f"❌ New organ {organ_id} is not healthy")
                            raise Exception(f"New organ {organ_id} failed health check")

                except Exception as e:
                    logger.error(f"❌ Failed to create/get organ {organ_id}: {e}")
                    logger.error(f"❌ Traceback: {traceback.format_exc()}")
                    raise
            else:
                logger.info(f"✅ Organ {organ_id} already exists in self.organs")

        logger.info(f"🏗️ Organ creation process completed. Total organs: {len(self.organs)}")
        logger.info(f"🔍 Final organs: {list(self.organs.keys())}")

        # Verify namespace via communication tests
        logger.info(f"🔍 Verifying namespace accessibility via actor communication...")
        try:
            for organ_id, organ_handle in self.organs.items():
                try:
                    status = ray.get(organ_handle.get_status.remote(), timeout=5.0)
                    if status and status.get('organ_id') == organ_id:
                        logger.info(f"   ✅ Organ {organ_id}: responsive and accessible")
                    else:
                        logger.warning(f"⚠️ Organ {organ_id}: responsive but status mismatch")
                except Exception as comm_error:
                    logger.warning(f"⚠️ Organ {organ_id}: communication test failed: {comm_error}")
        except Exception as e:
            logger.warning(f"⚠️ Could not verify namespace accessibility: {e}")

    async def _create_and_distribute_agents(self):
        """Create agents and register them with their designated organs."""
        agent_count = 0
        for organ_config in self.organ_configs:
            organ_id = organ_config['id']
            num_agents = organ_config['agent_count']
            organ_handle = self.organs.get(organ_id)

            if not organ_handle:
                logger.warning(f"Organ '{organ_id}' not found. Skipping agent creation.")
                continue

            logger.info(f"Creating {num_agents} agents for organ {organ_id}...")

            # Clean up excess agents if needed
            await self._cleanup_excess_agents(organ_handle, organ_id, num_agents)

            for i in range(num_agents):
                agent_id = f"{organ_id}_agent_{i}"
                try:
                    # Check for existing
                    try:
                        existing_agents = await self._async_ray_get(organ_handle.get_agent_handles.remote())
                        logger.info(f"✅ Existing agents in {organ_id}: {list(existing_agents.keys())}")
                    except Exception as e:
                        logger.error(f"❌ Failed to get agent handles from organ {organ_id}: {e}")
                        continue

                    if agent_id in existing_agents:
                        logger.info(f"✅ Reusing existing agent: {agent_id}")
                        self.agent_to_organ_map[agent_id] = organ_id
                        agent_count += 1
                        continue

                    # Create via Tier0 manager
                    initial_role_probs = self._get_role_probs_for_organ_type(organ_config['type'])
                    try:
                        logger.info(f"🚀 Creating Tier0 agent {agent_id} via Tier0MemoryManager...")
                        tier0_manager.create_agent(
                            agent_id=agent_id,
                            role_probs=initial_role_probs,
                            name=agent_id,
                            lifetime="detached",
                            num_cpus=0.1,
                        )

                        agent_handle = tier0_manager.get_agent(agent_id)
                        if not agent_handle:
                            raise Exception("Agent handle not found after creation")

                        logger.info(f"✅ Tier0 agent {agent_id} created, testing with get_id...")
                        test_result = await self._async_ray_get(agent_handle.get_id.remote())
                        logger.info(f"✅ Agent {agent_id} get_id test passed: {test_result}")
                        if test_result != agent_id:
                            raise Exception(f"Agent ID mismatch: expected {agent_id}, got {test_result}")

                        # Register with organ
                        logger.info(f"📝 Registering agent {agent_id} with organ {organ_id}...")
                        await self._async_ray_get(organ_handle.register_agent.remote(agent_id, agent_handle))
                        logger.info(f"✅ Agent {agent_id} registered with organ {organ_id}")

                        self.agent_to_organ_map[agent_id] = organ_id
                        agent_count += 1

                    except asyncio.TimeoutError:
                        logger.error(f"❌ Timeout creating agent {agent_id}")
                        continue
                    except Exception as e:
                        logger.error(f"❌ Failed to create agent {agent_id}: {e}")
                        continue

                except Exception as e:
                    logger.error(f"❌ Failed to create agent {agent_id}: {e}")
                    continue

        logger.info(f"✅ Created and distributed {agent_count} agents across {len(self.organs)} organs.")

    async def _cleanup_excess_agents(self, organ_handle, organ_id: str, target_count: int):
        """Remove excess agents from an organ to match the target count."""
        try:
            logger.info(f"🧹 Checking for excess agents in {organ_id} (target: {target_count})...")
            existing_agents = await self._async_ray_get(organ_handle.get_agent_handles.remote())
            current_count = len(existing_agents)
            logger.info(f"📊 Current agent count in {organ_id}: {current_count}")

            if current_count > target_count:
                excess_count = current_count - target_count
                logger.info(f"🧹 Cleaning up {excess_count} excess agents from {organ_id}")
                agent_ids = list(existing_agents.keys())
                for agent_id in agent_ids[target_count:]:
                    try:
                        logger.info(f"🗑️ Removing excess agent: {agent_id}")
                        await self._async_ray_get(organ_handle.remove_agent.remote(agent_id))
                        logger.info(f"✅ Removed excess agent: {agent_id}")
                    except Exception as e:
                        logger.error(f"❌ Failed to remove agent {agent_id}: {e}")
            else:
                logger.info(f"✅ No excess agents to clean up in {organ_id}")

        except Exception as e:
            logger.error(f"❌ Error during agent cleanup for {organ_id}: {e}")

    def _get_role_probs_for_organ_type(self, organ_type: str) -> Dict[str, float]:
        """Role priors per organ type."""
        if organ_type == "Cognitive":
            return {'E': 0.3, 'S': 0.6, 'O': 0.1}  # reasoning
        elif organ_type == "Actuator":
            return {'E': 0.7, 'S': 0.2, 'O': 0.1}  # action
        elif organ_type == "Utility":
            return {'E': 0.2, 'S': 0.3, 'O': 0.5}  # observation
        else:
            return {'E': 0.33, 'S': 0.33, 'O': 0.34}  # balanced

    # -------------------------------------------------------------------------
    # Status / execution
    # -------------------------------------------------------------------------
    async def get_organism_status(self) -> List[Dict[str, Any]]:
        """Collect and return status from all organs."""
        if not self._initialized:
            return [{"error": "Organism not initialized"}]
        try:
            refs = [organ.get_status.remote() for organ in self.organs.values()]
            results = await asyncio.gather(*refs, return_exceptions=True)
            statuses = []
            for r in results:
                statuses.append({"error": str(r)} if isinstance(r, Exception) else r)
            return statuses
        except Exception as e:
            logger.error(f"Error getting organism status: {e}")
            return [{"error": str(e)}]

    def get_organ_handle(self, organ_id: str) -> Optional[ray.actor.ActorHandle]:
        return self.organs.get(organ_id)

    def get_agent_organ(self, agent_id: str) -> Optional[str]:
        return self.agent_to_organ_map.get(agent_id)

    def get_total_agent_count(self) -> int:
        return len(self.agent_to_organ_map)

    def get_organ_count(self) -> int:
        return len(self.organs)

    def is_initialized(self) -> bool:
        return self._initialized

    async def execute_task_on_organ(self, organ_id: str, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a task on a specific organ with timeout & status handling."""
        if not self._initialized:
            raise RuntimeError("Organism not initialized")
        organ_handle = self.organs.get(organ_id)
        if not organ_handle:
            raise ValueError(f"Organ {organ_id} not found")

        task_id = task.get('id', 'unknown')
        timeout_s = float(task.get("organ_timeout_s", 30.0))

        try:
            result = await self._execute_task_with_timeout(organ_handle, task, timeout_s)
            if result["success"]:
                await self._update_task_status(task_id, "FINISHED", result=result["result"])
            else:
                await self._update_task_status(task_id, "FAILED", error=result["error"])
            return {"success": result["success"], "result": result.get("result"), "organ_id": organ_id, "error": result.get("error")}
        except Exception as e:
            error_msg = f"Error executing task on organ {organ_id}: {e}"
            logger.error(error_msg)
            await self._update_task_status(task_id, "FAILED", error=error_msg)
            return {"success": False, "error": error_msg, "organ_id": organ_id}

    async def execute_task_on_random_organ(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a task on a randomly selected organ."""
        if not self.organs:
            raise RuntimeError("No organs available")
        organ_id = random.choice(list(self.organs.keys()))
        return await self.execute_task_on_organ(organ_id, task)

    # -------------------------------------------------------------------------
    # Incoming task handler (local-only)
    # -------------------------------------------------------------------------
    async def handle_incoming_task(self, task: Dict[str, Any], app_state=None) -> Dict[str, Any]:
        """
        Unified handler for incoming tasks addressed to the Organism (local).
        - Prefer builtin handlers (registered on app_state).
        - Expose local API operations for direct control.
        """
        task_id = task.get('id') or task.get('task_id', 'unknown')
        logger.info(f"[OrganismManager] 🎯 Received task {task_id}")
        domain_value = task.get('domain') if task.get('domain') is not None else "None"
        logger.info(f"[OrganismManager] 📋 Task details: type={task.get('type')}, domain={domain_value}")

        print(f"[OrganismManager] Received task {task_id} with payload={task}")

        ttype = (task.get("type") or task.get("task_type") or "").strip().lower()
        task["type"] = ttype  # normalize
        logger.info(f"[OrganismManager] 🔍 Normalized task type: '{ttype}'")

        if not ttype:
            logger.error(f"[OrganismManager] ❌ Task {task_id} missing required type field")
            return {"success": False, "error": "task.type is required"}

        # 1) Builtins (app_state.builtin_task_handlers)
        logger.info(f"[OrganismManager] 🔍 Checking builtin handlers for '{ttype}'")
        if app_state is not None:
            handlers = getattr(app_state, "builtin_task_handlers", {}) or {}
            logger.info(f"[OrganismManager] 📦 Available builtin handlers: {list(handlers.keys())}")
            handler = handlers.get(ttype)
            if callable(handler):
                try:
                    out = handler() if task.get("params") is None else handler(**task.get("params", {}))
                    if asyncio.iscoroutine(out):
                        out = await out
                    logger.info(f"[OrganismManager] ✅ Builtin handler for '{ttype}' completed")
                    return {"success": True, "path": "builtin", "result": out}
                except Exception as e:
                    logger.exception(f"[OrganismManager] ❌ Builtin task '{ttype}' failed: {e}")
                    return {"success": False, "path": "builtin", "error": str(e)}
        else:
            logger.info(f"[OrganismManager] ⚠️ No app_state provided, skipping builtin handlers")

        # 2) Local API handlers (for direct organism control)
        if ttype == "get_organism_status":
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                status = await self.get_organism_status()
                return {"success": True, "path": "api_handler", "result": status}
            except Exception as e:
                return {"success": False, "path": "api_handler", "error": str(e)}

        elif ttype == "execute_on_organ":
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                params = task.get("params", {})
                organ_id = params.get("organ_id")
                task_data = params.get("task_data", {})
                if not organ_id:
                    return {"success": False, "error": "organ_id is required"}
                result = await self.execute_task_on_organ(organ_id, task_data)
                return {"success": True, "path": "api_handler", "result": result}
            except Exception as e:
                return {"success": False, "path": "api_handler", "error": str(e)}

        elif ttype == "execute_on_random_organ":
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                params = task.get("params", {})
                task_data = params.get("task_data", {})
                result = await self.execute_task_on_random_organ(task_data)
                return {"success": True, "path": "api_handler", "result": result}
            except Exception as e:
                return {"success": False, "path": "api_handler", "error": str(e)}

        elif ttype == "get_organism_summary":
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                summary = {
                    "initialized": self.is_initialized(),
                    "organ_count": self.get_organ_count(),
                    "total_agent_count": self.get_total_agent_count(),
                    "organs": {}
                }
                for organ_id in self.organs.keys():
                    organ_handle = self.get_organ_handle(organ_id)
                    if organ_handle:
                        try:
                            status = await self._async_ray_get(organ_handle.get_status.remote())
                            summary["organs"][organ_id] = status
                        except Exception as e:
                            summary["organs"][organ_id] = {"error": str(e)}
                return {"success": True, "path": "api_handler", "result": summary}
            except Exception as e:
                return {"success": False, "path": "api_handler", "error": str(e)}

        elif ttype == "initialize_organism":
            try:
                if self._initialized:
                    return {"success": True, "path": "api_handler", "result": "Organism already initialized"}
                await self.initialize_organism()
                return {"success": True, "path": "api_handler", "result": "Organism initialized successfully"}
            except Exception as e:
                return {"success": False, "path": "api_handler", "error": str(e)}

        elif ttype == "shutdown_organism":
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                await self.shutdown_organism()
                return {"success": True, "path": "api_handler", "result": "Organism shutdown successfully"}
            except Exception as e:
                return {"success": False, "path": "api_handler", "error": str(e)}

        elif ttype == "recover_stale_tasks":
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                await self._recover_stale_tasks()
                return {"success": True, "path": "api_handler", "result": "Stale task recovery completed"}
            except Exception as e:
                return {"success": False, "path": "api_handler", "error": str(e)}

        elif ttype == "debug_namespace":
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                debug_info = {
                    "current_ray_namespace": os.getenv("RAY_NAMESPACE"),
                    "seedcore_namespace": os.getenv("SEEDCORE_NS"),
                    "expected_namespace": os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev")),
                    "ray_initialized": ray.is_initialized(),
                    "organs": {},
                    "organ_namespaces": {}
                }
                for organ_id, organ_handle in self.organs.items():
                    try:
                        expected_namespace = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
                        debug_info["organ_namespaces"][organ_id] = expected_namespace
                        status = await self._async_ray_get(organ_handle.get_status.remote(), timeout=5.0)
                        debug_info["organs"][organ_id] = {"status": "responsive", "status_data": status}
                    except Exception as e:
                        debug_info["organs"][organ_id] = {"status": "error", "error": str(e)}
                return {"success": True, "path": "api_handler", "result": debug_info}
            except Exception as e:
                return {"success": False, "path": "api_handler", "error": str(e)}

        # No local handler
        return {"success": False, "path": "none", "error": f"No local handler for task.type='{ttype}'"}

    # -------------------------------------------------------------------------
    # Initialize / shutdown
    # -------------------------------------------------------------------------
    async def initialize_organism(self, *args, **kwargs):
        """Create all organs and populate them with agents based on the config."""
        if args and isinstance(args[0], dict):
            config = args[0]
            logger.info(f"📋 Using provided configuration: {list(config.keys())}")
            if 'organ_types' in config:
                self.organ_configs = config['organ_types']
                logger.info(f"✅ Updated organ configs: {len(self.organ_configs)} organs")

        if self._initialized:
            logger.warning("Organism already initialized. Skipping re-initialization.")
            return

        logger.info("🚀 Initializing the Cognitive Organism...")

        if not ray.is_initialized():
            raise RuntimeError("Ray is not initialized. Ensure connection before initialize_organism().")

        # Bootstrap required singleton actors
        try:
            logger.info("🚀 Bootstrapping required singleton actors...")
            from ..bootstrap import bootstrap_actors, bootstrap_memory_actors
            bootstrap_actors()          # Core system actors in seedcore-dev namespace
            bootstrap_memory_actors()   # Memory actors in mem-dev namespace
            logger.info("✅ Singleton actors bootstrapped successfully")
        except Exception as e:
            logger.error(f"⚠️ Failed to bootstrap singletons: {e}", exc_info=True)
            logger.warning("⚠️ Agents may have limited functionality without memory managers")

        max_retries = 3
        retry_delay = 10  # seconds

        for attempt in range(max_retries):
            try:
                logger.info(f"🔄 Attempt {attempt + 1}/{max_retries} to initialize organism...")

                await self._check_ray_cluster_health()
                await self._cleanup_dead_actors()
                await self._recover_stale_tasks()

                logger.info("🏗️ Creating organs...")
                await self._create_organs()

                logger.info("🤖 Creating and distributing agents...")
                await self._create_and_distribute_agents()

                await self._start_background_health_checks()

                self._initialized = True
                logger.info("✅ Organism initialization complete.")
                return

            except Exception as e:
                logger.error(f"❌ Attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    logger.info(f"⏳ Waiting {retry_delay} seconds before retry...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.error("❌ All attempts failed. Giving up.")
                    raise

    async def shutdown_organism(self):
        """Shut down the organism and stop background tasks."""
        logger.info("🛑 Shutting down organism...")
        await self._stop_background_health_checks()
        # Note: detached Ray actors persist until explicitly terminated (out of scope here)
        self._initialized = False
        logger.info("✅ Organism shutdown complete")

    # -------------------------------------------------------------------------
    # Task execution helpers / status updates
    # -------------------------------------------------------------------------
    async def _execute_task_with_timeout(self, organ_handle, task: Dict[str, Any], timeout_s: float = 30.0) -> Dict[str, Any]:
        """Execute a task on an organ with timeout handling."""
        try:
            result_ref = organ_handle.run_task.remote(task)
            result = await self._async_ray_get(result_ref, timeout=timeout_s)
            return {"success": True, "result": result}
        except asyncio.TimeoutError:
            logger.error(f"⏰ Task {task.get('id', 'unknown')} timed out after {timeout_s}s")
            return {"success": False, "error": f"Task timed out after {timeout_s} seconds"}
        except Exception as e:
            logger.error(f"❌ Task {task.get('id', 'unknown')} failed: {e}")
            return {"success": False, "error": str(e)}

    async def _update_task_status(self, task_id: str, status: str, error: str = None, result: Any = None):
        """
        Update task status in DB (stub, enable when task system is ready).
        """
        try:
            logger.info(f"ℹ️ Task status update for {task_id} → {status} (stub)")
            # TODO: integrate with task management/DB when ready
        except Exception as e:
            logger.error(f"❌ Failed to update task {task_id} status: {e}")

    async def _recover_stale_tasks(self):
        """
        Recover stale tasks stuck in RUNNING (stub, enable with task system).
        """
        try:
            logger.info("🔄 Stale task recovery (stub) — feature not yet implemented")
        except Exception as e:
            logger.error(f"❌ Failed to recover stale tasks: {e}")

    # -------------------------------------------------------------------------
    # State aggregation via StateService actor
    # -------------------------------------------------------------------------
    def _get_state_service(self):
        """Get or connect to the state service (actor)."""
        if self._state_service is None:
            try:
                for namespace in ["seedcore-dev", "serve", AGENT_NAMESPACE, "default"]:
                    try:
                        self._state_service = ray.get_actor("StateService", namespace=namespace)
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

    async def get_unified_state(self, agent_ids: Optional[List[str]] = None):
        """
        Get unified state for specified agents or all agents via StateService.
        Returns a ..energy.state.UnifiedState object if types are available, else a minimal dict.
        """
        # If not initialized, return an empty shell of UnifiedState
        if not self._initialized:
            logger.warning("Organism not initialized, returning empty state")
            try:
                from ..models.state import UnifiedState, SystemState, MemoryVector
                return UnifiedState(
                    agents={}, organs={}, system=SystemState(),
                    memory=MemoryVector(ma={}, mw={}, mlt={}, mfb={})
                )
            except Exception:
                return {"agents": {}, "organs": {}, "system": {}, "memory": {}}

        state_service = self._get_state_service()
        if state_service is None:
            logger.error("State service not available, returning empty state")
            try:
                from ..models.state import UnifiedState, SystemState, MemoryVector
                return UnifiedState(
                    agents={}, organs={}, system=SystemState(),
                    memory=MemoryVector(ma={}, mw={}, mlt={}, mfb={})
                )
            except Exception:
                return {"agents": {}, "organs": {}, "system": {}, "memory": {}}

        try:
            # Invoke actor and await result properly
            response_ref = state_service.get_unified_state.remote(
                agent_ids=agent_ids,
                include_organs=True,
                include_system=True,
                include_memory=True
            )
            response = await self._async_ray_get(response_ref)

            if not response.get("success"):
                logger.error(f"State service failed: {response.get('error')}")
                try:
                    from ..models.state import UnifiedState, SystemState, MemoryVector
                    return UnifiedState(
                        agents={}, organs={}, system=SystemState(),
                        memory=MemoryVector(ma={}, mw={}, mlt={}, mfb={})
                    )
                except Exception:
                    return {"agents": {}, "organs": {}, "system": {}, "memory": {}}

            state_dict = response["unified_state"]

            # If energy.state classes are available, materialize the typed object
            try:
                from ..models.state import UnifiedState, SystemState, MemoryVector, AgentSnapshot, OrganState
                # Agents
                agents = {}
                for agent_id, agent_data in state_dict.get("agents", {}).items():
                    agents[agent_id] = AgentSnapshot(
                        h=np.array(agent_data["h"], dtype=np.float32),
                        p=agent_data["p"],
                        c=agent_data["c"],
                        mem_util=agent_data["mem_util"],
                        lifecycle=agent_data["lifecycle"]
                    )
                # Organs
                organs = {}
                for organ_id, organ_data in state_dict.get("organs", {}).items():
                    organs[organ_id] = OrganState(
                        h=np.array(organ_data["h"], dtype=np.float32),
                        P=np.array(organ_data["P"], dtype=np.float32),
                        v_pso=np.array(organ_data["v_pso"], dtype=np.float32) if organ_data.get("v_pso") else None
                    )
                # System
                sys_data = state_dict.get("system", {})
                system = SystemState(
                    h_hgnn=np.array(sys_data["h_hgnn"], dtype=np.float32) if sys_data.get("h_hgnn") else None,
                    E_patterns=np.array(sys_data["E_patterns"], dtype=np.float32) if sys_data.get("E_patterns") else None,
                    w_mode=np.array(sys_data["w_mode"], dtype=np.float32) if sys_data.get("w_mode") else None
                )
                # Memory
                mem_data = state_dict.get("memory", {})
                memory = MemoryVector(
                    ma=mem_data.get("ma", {}),
                    mw=mem_data.get("mw", {}),
                    mlt=mem_data.get("mlt", {}),
                    mfb=mem_data.get("mfb", {})
                )
                return UnifiedState(agents=agents, organs=organs, system=system, memory=memory)
            except Exception:
                # Fallback to dict if types are unavailable
                return state_dict

        except Exception as e:
            logger.error(f"Failed to get unified state from StateService: {e}")
            try:
                from ..models.state import UnifiedState, SystemState, MemoryVector
                return UnifiedState(
                    agents={}, organs={}, system=SystemState(),
                    memory=MemoryVector(ma={}, mw={}, mlt={}, mfb={})
                )
            except Exception:
                return {"agents": {}, "organs": {}, "system": {}, "memory": {}}

    async def get_agent_state_summary(self, agent_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Get a summary of agent states for monitoring and debugging.
        """
        if agent_ids is None:
            agent_ids = list(self.agent_to_organ_map.keys())

        summary = {
            "total_agents": len(agent_ids),
            "agent_details": {},
            "organ_distribution": {},
            "system_health": "unknown"
        }

        try:
            for agent_id in agent_ids:
                organ_id = self.agent_to_organ_map.get(agent_id)
                summary["agent_details"][agent_id] = {
                    "organ": organ_id,
                    "status": "active" if organ_id else "orphaned"
                }
                if organ_id:
                    summary["organ_distribution"][organ_id] = summary["organ_distribution"].get(organ_id, 0) + 1

            summary["system_health"] = "healthy" if (self._initialized and len(self.organs) > 0) else "unhealthy"
            logger.debug(f"Agent state summary: {len(agent_ids)} agents across {len(summary['organ_distribution'])} organs")

        except Exception as e:
            logger.error(f"Failed to get agent state summary: {e}")
            summary["error"] = str(e)

        return summary


# Global instance (created by FastAPI lifespan after Ray connects)
organism_manager: Optional[OrganismManager] = None
