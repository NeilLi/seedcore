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
import uuid
import httpx
import json
import contextlib
from pathlib import Path
from typing import Dict, List, Any, Optional

from .base import Organ
from ..agents import tier0_manager

logger = logging.getLogger(__name__)

from seedcore.logging_setup import ensure_serve_logger

logger = ensure_serve_logger("seedcore.OrganismManager", level="DEBUG")

# Target namespace for agent actors (prefer SEEDCORE_NS, fallback to RAY_NAMESPACE)
AGENT_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))

def _env_bool(name: str, default: bool = False) -> bool:
    """Robust environment variable parsing for boolean values."""
    val = os.getenv(name)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "y", "on")


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
        
        # Evolution configuration - use centralized SERVE gateway
        try:
            from seedcore.utils.ray_utils import SERVE_GATEWAY
            default_energy = f"{SERVE_GATEWAY}/energy"
        except Exception:
            default_energy = "http://127.0.0.1:8000/energy"
        self._energy_url = os.getenv("SEEDCORE_ENERGY_URL", default_energy)
        self._evolve_min_roi = float(os.getenv("EVOLVE_MIN_ROI", "0.2"))
        self._evolve_max_cost = float(os.getenv("EVOLVE_MAX_COST", "1e6"))
        
        # Memory thresholds (bandit hook)
        self._memory_thresholds = {}
        
        # Agent graph repository (lazy initialization)
        self._agent_graph_repo = None
        self._agent_graph_repo_checked = False
        
        # Runtime registry configuration
        self.rolling = _env_bool("SEEDCORE_ROLLING_INIT", False)
        self._recon_task: Optional[asyncio.Task] = None

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

                        # Persist organ to registry (best-effort)
                        repo = self._get_agent_graph_repository()
                        if repo:
                            try:
                                await repo.ensure_organ(
                                    organ_id=organ_id, 
                                    kind=organ_type, 
                                    props=json.dumps({"ray_namespace": organ_namespace})
                                )
                                logger.info(f"✅ Persisted existing organ '{organ_id}' to registry")
                            except Exception as e:
                                logger.error(f"❌ Persist existing organ '{organ_id}' failed: {e}")

                        # Start runtime heartbeats (idempotent)
                        try:
                            start_info = await self._async_ray_get(existing_organ.start.remote())
                            logger.info(f"✅ Organ '{organ_id}' started: {start_info}")
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to start organ '{organ_id}': {e}")

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
                        
                        # Persist new organ to registry (best-effort)
                        repo = self._get_agent_graph_repository()
                        if repo:
                            try:
                                await repo.ensure_organ(
                                    organ_id=organ_id, 
                                    kind=organ_type, 
                                    props=json.dumps({"ray_namespace": ray_namespace})
                                )
                                logger.info(f"✅ Persisted new organ '{organ_id}' to registry")
                            except Exception as e:
                                logger.error(f"❌ Persist new organ '{organ_id}' failed: {e}")

                        # Start runtime heartbeats (idempotent)
                        try:
                            start_info = await self._async_ray_get(self.organs[organ_id].start.remote())
                            logger.info(f"✅ Organ '{organ_id}' started: {start_info}")
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to start organ '{organ_id}': {e}")

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
                        
                        # Persist existing agent and ensure link to organ (best-effort)
                        repo = self._get_agent_graph_repository()
                        if repo:
                            try:
                                await repo.ensure_agent(
                                    agent_id=agent_id, 
                                    display_name=agent_id, 
                                    props=json.dumps({"ray_namespace": AGENT_NAMESPACE})
                                )
                                await repo.link_agent_to_organ(agent_id=agent_id, organ_id=organ_id)
                                logger.info(f"✅ Ensured existing agent '{agent_id}' linked to organ '{organ_id}' in DB")
                            except Exception as e:
                                logger.error(f"❌ Persist/link existing agent '{agent_id}'→'{organ_id}' failed: {e}")
                        
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
                            organ_id=organ_id,
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

                        # Persist agent and link to organ (best-effort)
                        repo = self._get_agent_graph_repository()
                        if repo:
                            try:
                                await repo.ensure_agent(
                                    agent_id=agent_id, 
                                    display_name=agent_id, 
                                    props=json.dumps({"ray_namespace": AGENT_NAMESPACE})
                                )
                                await repo.link_agent_to_organ(agent_id=agent_id, organ_id=organ_id)
                                logger.info(f"✅ Linked agent '{agent_id}' to organ '{organ_id}' in DB")
                            except Exception as e:
                                logger.error(f"❌ Persist/link agent '{agent_id}'→'{organ_id}' failed: {e}")

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
        elif organ_type == "Graph":
            return {'E': 0.4, 'S': 0.4, 'O': 0.2}  # graph processing
        elif organ_type == "Fact":
            return {'E': 0.3, 'S': 0.5, 'O': 0.2}  # fact management
        elif organ_type == "Resource":
            return {'E': 0.5, 'S': 0.3, 'O': 0.2}  # resource management
        elif organ_type == "AgentLayer":
            return {'E': 0.4, 'S': 0.4, 'O': 0.2}  # agent layer management
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
        
        # Graph-based routing (skill/service-aware)
        required_skill = (task.get("params") or {}).get("required_skill")
        required_service = (task.get("params") or {}).get("required_service")
        repo = self._get_agent_graph_repository()

        if repo and (required_skill or required_service):
            try:
                if required_skill:
                    organ_id = await repo.find_organ_by_skill(required_skill)
                else:
                    organ_id = await repo.find_organ_by_service(required_service)
                if organ_id and organ_id in self.organs:
                    logger.info(f"🧠 Routing task to organ '{organ_id}' based on graph ({required_skill or required_service})")
                    return await self.execute_task_on_organ(organ_id, task)
                else:
                    logger.warning(f"⚠️ Graph suggested organ '{organ_id}' not active; falling back")
            except Exception as e:
                logger.error(f"❌ Graph-based routing failed: {e}; falling back")
        
        # Enhanced routing based on task type (Migration 007+)
        ttype = task.get("type", "").lower()
        
        # Route graph tasks to graph dispatcher if available
        if ttype in ("graph_embed", "graph_rag_query", "graph_embed_v2", "graph_rag_query_v2", 
                     "graph_sync_nodes", "graph_fact_embed", "graph_fact_query"):
            if "graph_dispatcher" in self.organs:
                return await self.execute_task_on_organ("graph_dispatcher", task)
        
        # Route fact operations to utility organ if available
        if ttype in ("fact_search", "fact_store"):
            if "utility_organ_1" in self.organs:
                return await self.execute_task_on_organ("utility_organ_1", task)
        
        # Route resource management to utility organ if available
        if ttype in ("artifact_manage", "capability_manage", "memory_cell_manage"):
            if "utility_organ_1" in self.organs:
                return await self.execute_task_on_organ("utility_organ_1", task)
        
        # Route agent layer management to utility organ if available
        if ttype in ("model_manage", "policy_manage", "service_manage", "skill_manage"):
            if "utility_organ_1" in self.organs:
                return await self.execute_task_on_organ("utility_organ_1", task)
        
        # Fallback to random selection
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

        # Enhanced parameter validation for new node types (Migration 007+)
        params = task.get("params", {})
        if ttype in ("graph_embed", "graph_rag_query", "graph_embed_v2", "graph_rag_query_v2", "graph_sync_nodes"):
            # Validate graph task parameters
            required_params = ["start_node_ids", "k"]
            for param in required_params:
                if param not in params:
                    logger.warning(f"[OrganismManager] ⚠️ Graph task {task_id} missing parameter: {param}")
            
            # Log new node type parameters if present
            new_node_params = ["start_fact_ids", "start_artifact_ids", "start_capability_ids", 
                             "start_memory_cell_ids", "start_model_ids", "start_policy_ids", 
                             "start_service_ids", "start_skill_ids"]
            for param in new_node_params:
                if param in params and params[param]:
                    logger.info(f"[OrganismManager] 📋 Graph task {task_id} includes {param}: {len(params[param])} items")
        
        elif ttype in ("graph_fact_embed", "graph_fact_query"):
            # Validate fact task parameters
            if "start_fact_ids" not in params:
                logger.warning(f"[OrganismManager] ⚠️ Fact task {task_id} missing start_fact_ids parameter")
        
        elif ttype in ("fact_search", "fact_store"):
            # Validate fact operation parameters
            if ttype == "fact_search" and "query" not in params:
                logger.warning(f"[OrganismManager] ⚠️ Fact search task {task_id} missing query parameter")
            elif ttype == "fact_store" and "text" not in params:
                logger.warning(f"[OrganismManager] ⚠️ Fact store task {task_id} missing text parameter")
        
        elif ttype in ("artifact_manage", "capability_manage", "memory_cell_manage"):
            # Validate resource management parameters
            if "action" not in params:
                logger.warning(f"[OrganismManager] ⚠️ Resource management task {task_id} missing action parameter")
        
        elif ttype in ("model_manage", "policy_manage", "service_manage", "skill_manage"):
            # Validate agent layer management parameters
            if "action" not in params:
                logger.warning(f"[OrganismManager] ⚠️ Agent layer management task {task_id} missing action parameter")

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

        # Graph task handlers (Migration 007+)
        elif ttype in ("graph_embed", "graph_rag_query", "graph_embed_v2", "graph_rag_query_v2", "graph_sync_nodes"):
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                # Route graph tasks to graph dispatcher
                params = task.get("params", {})
                organ_id = params.get("organ_id", "graph_dispatcher")
                task_data = params.get("task_data", task)
                result = await self.execute_task_on_organ(organ_id, task_data)
                return {"success": True, "path": "graph_handler", "result": result}
            except Exception as e:
                return {"success": False, "path": "graph_handler", "error": str(e)}

        # Facts system handlers (Migration 009)
        elif ttype in ("graph_fact_embed", "graph_fact_query"):
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                # Route fact tasks to graph dispatcher
                params = task.get("params", {})
                organ_id = params.get("organ_id", "graph_dispatcher")
                task_data = params.get("task_data", task)
                result = await self.execute_task_on_organ(organ_id, task_data)
                return {"success": True, "path": "fact_handler", "result": result}
            except Exception as e:
                return {"success": False, "path": "fact_handler", "error": str(e)}

        elif ttype in ("fact_search", "fact_store"):
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                # Route fact operations to utility organ
                params = task.get("params", {})
                organ_id = params.get("organ_id", "utility_organ_1")
                task_data = params.get("task_data", task)
                result = await self.execute_task_on_organ(organ_id, task_data)
                return {"success": True, "path": "fact_handler", "result": result}
            except Exception as e:
                return {"success": False, "path": "fact_handler", "error": str(e)}

        # Resource management handlers (Migration 007)
        elif ttype in ("artifact_manage", "capability_manage", "memory_cell_manage"):
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                # Route resource management to utility organ
                params = task.get("params", {})
                organ_id = params.get("organ_id", "utility_organ_1")
                task_data = params.get("task_data", task)
                result = await self.execute_task_on_organ(organ_id, task_data)
                return {"success": True, "path": "resource_handler", "result": result}
            except Exception as e:
                return {"success": False, "path": "resource_handler", "error": str(e)}

        # Agent layer management handlers (Migration 008)
        elif ttype in ("model_manage", "policy_manage", "service_manage", "skill_manage"):
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                # Route agent layer management to utility organ
                params = task.get("params", {})
                organ_id = params.get("organ_id", "utility_organ_1")
                task_data = params.get("task_data", task)
                result = await self.execute_task_on_organ(organ_id, task_data)
                return {"success": True, "path": "agent_layer_handler", "result": result}
            except Exception as e:
                return {"success": False, "path": "agent_layer_handler", "error": str(e)}

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

                # 0) Rotate epoch unless rolling mode (env-controlled)
                try:
                    repo = self._get_agent_graph_repository()
                    if repo and not self.rolling:
                        import uuid as _uuid
                        new_epoch = str(_uuid.uuid4())
                        await repo.set_current_cluster_epoch(new_epoch)
                        logger.info(f"[organism] hard init: rotated epoch={new_epoch}")
                    else:
                        logger.info("[organism] rolling init: keeping current epoch")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to manage cluster epoch: {e}")

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
                # Start reconciliation loop (best-effort)
                try:
                    if self._recon_task is None or self._recon_task.done():
                        self._recon_task = asyncio.create_task(self._reconcile_loop())
                        logger.info("✅ Started registry reconciliation loop")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to start reconcile loop: {e}")
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
        
        # Cancel reconciliation task
        if self._recon_task:
            self._recon_task.cancel()
            with contextlib.suppress(Exception):
                await self._recon_task
        
        # Note: detached Ray actors persist until explicitly terminated (out of scope here)
        self._initialized = False
        logger.info("✅ Organism shutdown complete")

    async def _reconcile_loop(self):
        """Background loop to expire stale/old-epoch instances in registry."""
        while True:
            try:
                await asyncio.sleep(15)
                repo = self._get_agent_graph_repository()
                if repo:
                    stale = await repo.expire_stale_instances(timeout_seconds=15)
                    old = await repo.expire_old_epoch_instances()
                    if stale or old:
                        logger.info(f"[reconcile] stale={stale}, old_epoch={old}")
                else:
                    logger.warning("[reconcile] AgentGraphRepository not available, skipping reconciliation")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[reconcile] error: {e}")

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

    def _get_agent_graph_repository(self):
        """Get or create the agent graph repository (lazy initialization)."""
        if self._agent_graph_repo is not None or self._agent_graph_repo_checked:
            return self._agent_graph_repo

        self._agent_graph_repo_checked = True
        try:
            from seedcore.graph.agent_graph_repository import AgentGraphRepository
            self._agent_graph_repo = AgentGraphRepository()
            logger.debug("✅ AgentGraphRepository initialized")
        except Exception as exc:
            logger.warning(f"AgentGraphRepository initialization failed: {exc}")
            self._agent_graph_repo = None
        return self._agent_graph_repo

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

    # -------------------------------------------------------------------------
    # Evolution Operations
    # -------------------------------------------------------------------------
    async def evolve(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute organism evolution operations with guardrails.
        
        Args:
            proposal: Evolution proposal containing:
                - op: Operation type ('split', 'merge', 'clone', 'retire')
                - organ_id: Target organ ID
                - params: Operation-specific parameters
                
        Returns:
            Dict with evolution result including energy measurements
        """
        if not self._initialized:
            return {"success": False, "error": "Organism not initialized"}
            
        op = proposal.get("op")
        organ_id = proposal.get("organ_id")
        params = proposal.get("params", {})
        
        if not op or not organ_id:
            return {"success": False, "error": "Missing required fields: op, organ_id"}
            
        if organ_id not in self.organs:
            return {"success": False, "error": f"Organ {organ_id} not found"}
            
        # Get energy before operation (best-effort)
        E_before = await self._try_energy_total()
        
        # Estimate cost and check guardrails
        estimated_cost = self._estimate_evolution_cost(op, params)
        if estimated_cost > self._evolve_max_cost:
            return {"success": False, "error": f"Estimated cost {estimated_cost} exceeds max {self._evolve_max_cost}"}
            
        # Execute operation
        try:
            result = await self._execute_evolution_op(op, organ_id, params)
            if not result.get("success", False):
                return result
                
            # Get energy after operation (best-effort)
            E_after = await self._try_energy_total()
            delta_E = E_after - E_before if E_after is not None and E_before is not None else None
            
            # Check ROI guardrail
            if delta_E is not None and estimated_cost > 0:
                roi = delta_E / estimated_cost
                if roi < self._evolve_min_roi:
                    logger.warning(f"Evolution ROI {roi} below minimum {self._evolve_min_roi}")
                    # Continue execution but log the warning
                    
            # Log evolution event to energy system
            await self._log_evolution_event(
                op=op,
                organ_id=organ_id,
                delta_E_est=delta_E,
                E_before=E_before,
                delta_E_realized=delta_E,
                cost=estimated_cost,
                success=True
            )
            
            return {
                "success": True,
                "op": op,
                "organ_id": organ_id,
                "delta_E_est": delta_E,
                "E_before": E_before,
                "delta_E_realized": delta_E,
                "cost": estimated_cost,
                "result": result.get("result", {})
            }
            
        except Exception as e:
            logger.error(f"Evolution operation {op} failed: {e}")
            await self._log_evolution_event(
                op=op,
                organ_id=organ_id,
                delta_E_est=None,
                E_before=E_before,
                delta_E_realized=None,
                cost=estimated_cost,
                success=False,
                error=str(e)
            )
            return {"success": False, "error": str(e)}

    async def _execute_evolution_op(self, op: str, organ_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a specific evolution operation."""
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

    async def _op_split(self, organ_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Split an organ into k-1 new organs and repartition agents."""
        k = params.get("k", 2)
        if k < 2:
            return {"success": False, "error": "k must be >= 2 for split operation"}
            
        try:
            organ_handle = self.organs[organ_id]
            organ_type = await self._async_ray_get(organ_handle.get_status.remote())
            organ_type = organ_type.get("organ_type", "Unknown")
            
            # Get current agents
            agent_handles = await self._async_ray_get(organ_handle.get_agent_handles.remote())
            agent_ids = list(agent_handles.keys())
            
            if len(agent_ids) < k:
                return {"success": False, "error": f"Not enough agents ({len(agent_ids)}) to split into {k} organs"}
                
            # Create k-1 new organs
            new_organ_ids = []
            for i in range(k - 1):
                new_organ_id = await self._unique_organ_id(f"{organ_id}_split_{i}")
                new_organ = await self._create_organ(new_organ_id, organ_type)
                if new_organ:
                    new_organ_ids.append(new_organ_id)
                    self.organs[new_organ_id] = new_organ
                    
            if not new_organ_ids:
                return {"success": False, "error": "Failed to create new organs"}
                
            # Repartition agents
            agents_per_organ = len(agent_ids) // k
            for i, new_organ_id in enumerate(new_organ_ids):
                start_idx = i * agents_per_organ
                end_idx = start_idx + agents_per_organ
                if i == len(new_organ_ids) - 1:  # Last organ gets remaining agents
                    end_idx = len(agent_ids)
                    
                # Move agents to new organ
                new_organ_handle = self.organs[new_organ_id]
                for agent_id in agent_ids[start_idx:end_idx]:
                    agent_handle = agent_handles[agent_id]
                    await self._async_ray_get(new_organ_handle.register_agent.remote(agent_id, agent_handle))
                    await self._async_ray_get(organ_handle.remove_agent.remote(agent_id))
                    self.agent_to_organ_map[agent_id] = new_organ_id
                    
            return {
                "success": True,
                "result": {
                    "original_organ": organ_id,
                    "new_organs": new_organ_ids,
                    "agents_moved": len(agent_ids) - agents_per_organ
                }
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
                
                # Get agents from source organ
                agent_handles = await self._async_ray_get(src_organ_handle.get_agent_handles.remote())
                
                # Move agents to destination
                for agent_id, agent_handle in agent_handles.items():
                    await self._async_ray_get(dst_organ_handle.register_agent.remote(agent_id, agent_handle))
                    self.agent_to_organ_map[agent_id] = organ_id
                    total_agents_moved += 1
                    
                # Retire source organ
                await self._retire_organ_actor(src_organ_id)
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
        move_fraction = params.get("move_fraction", 0.0)
        
        try:
            src_organ_handle = self.organs[organ_id]
            organ_status = await self._async_ray_get(src_organ_handle.get_status.remote())
            organ_type = organ_status.get("organ_type", "Unknown")
            
            # Create new organ
            new_organ_id = await self._unique_organ_id(f"{organ_id}_clone")
            new_organ = await self._create_organ(new_organ_id, organ_type)
            if not new_organ:
                return {"success": False, "error": "Failed to create cloned organ"}
                
            self.organs[new_organ_id] = new_organ
            
            # Optionally move agents
            agents_moved = 0
            if move_fraction > 0:
                agent_handles = await self._async_ray_get(src_organ_handle.get_agent_handles.remote())
                agent_ids = list(agent_handles.keys())
                num_to_move = int(len(agent_ids) * move_fraction)
                
                for agent_id in agent_ids[:num_to_move]:
                    agent_handle = agent_handles[agent_id]
                    await self._async_ray_get(new_organ.register_agent.remote(agent_id, agent_handle))
                    await self._async_ray_get(src_organ_handle.remove_agent.remote(agent_id))
                    self.agent_to_organ_map[agent_id] = new_organ_id
                    agents_moved += 1
                    
            return {
                "success": True,
                "result": {
                    "original_organ": organ_id,
                    "cloned_organ": new_organ_id,
                    "agents_moved": agents_moved
                }
            }
            
        except Exception as e:
            logger.error(f"Clone operation failed: {e}")
            return {"success": False, "error": str(e)}

    async def _op_retire(self, organ_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Retire an organ, optionally migrating agents to another organ."""
        migrate_to = params.get("migrate_to")
        
        try:
            organ_handle = self.organs[organ_id]
            
            # Get agents from organ
            agent_handles = await self._async_ray_get(organ_handle.get_agent_handles.remote())
            agents_migrated = 0
            
            # Migrate agents if specified
            if migrate_to and migrate_to in self.organs:
                dst_organ_handle = self.organs[migrate_to]
                for agent_id, agent_handle in agent_handles.items():
                    await self._async_ray_get(dst_organ_handle.register_agent.remote(agent_id, agent_handle))
                    self.agent_to_organ_map[agent_id] = migrate_to
                    agents_migrated += 1
                    
            # Retire the organ
            await self._retire_organ_actor(organ_id)
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

    # -------------------------------------------------------------------------
    # Evolution Helper Methods
    # -------------------------------------------------------------------------
    async def _infer_organ_type(self, organ_id: str) -> str:
        """Infer organ type from configuration or existing organ."""
        # First check if organ exists and get its type
        if organ_id in self.organs:
            try:
                status = await self._async_ray_get(self.organs[organ_id].get_status.remote())
                return status.get("organ_type", "Unknown")
            except Exception:
                pass
                
        # Check configuration for organ type
        for config in self.organ_configs:
            if config.get("id") == organ_id:
                return config.get("type", "Unknown")
                
        return "Unknown"

    async def _create_organ(self, organ_id: str, organ_type: str) -> Optional[ray.actor.ActorHandle]:
        """Create a new organ actor."""
        try:
            ray_namespace = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
            organ = Organ.options(
                name=organ_id,
                lifetime="detached",
                num_cpus=0.1,
                namespace=ray_namespace
            ).remote(
                organ_id=organ_id,
                organ_type=organ_type
            )
            logger.info(f"✅ Created new organ: {organ_id} (Type: {organ_type})")
            return organ
        except Exception as e:
            logger.error(f"❌ Failed to create organ {organ_id}: {e}")
            return None

    async def _retire_organ_actor(self, organ_id: str):
        """Retire an organ actor."""
        try:
            if organ_id in self.organs:
                organ_handle = self.organs[organ_id]
                # Try to shutdown gracefully if the organ supports it
                try:
                    # Prefer close() to mark dead in runtime registry
                    await self._async_ray_get(organ_handle.close.remote(), timeout=5.0)
                except Exception:
                    # Fallback to optional shutdown()
                    try:
                        await self._async_ray_get(organ_handle.shutdown.remote(), timeout=5.0)
                    except Exception:
                        pass  # Organ may not have shutdown method
                    
                # Kill the actor
                ray.kill(organ_handle)
                logger.info(f"✅ Retired organ actor: {organ_id}")
        except Exception as e:
            logger.error(f"❌ Failed to retire organ {organ_id}: {e}")

    async def _unique_organ_id(self, base_id: str) -> str:
        """Generate a unique organ ID."""
        counter = 1
        candidate_id = base_id
        while candidate_id in self.organs:
            candidate_id = f"{base_id}_{counter}"
            counter += 1
        return candidate_id

    def _estimate_evolution_cost(self, op: str, params: Dict[str, Any]) -> float:
        """Estimate the cost of an evolution operation."""
        # Simple cost estimation based on operation type
        base_costs = {
            "split": 1000.0,
            "merge": 500.0,
            "clone": 1500.0,
            "retire": 200.0
        }
        return base_costs.get(op, 1000.0)

    # -------------------------------------------------------------------------
    # Energy Integration
    # -------------------------------------------------------------------------
    async def _try_energy_total(self) -> Optional[float]:
        """Try to get current energy total from energy service (best-effort)."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Primary: /metrics returns a breakdown with 'total'
                response = await client.get(f"{self._energy_url}/metrics")
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, dict):
                        total = data.get("total")
                        if isinstance(total, (int, float)):
                            return float(total)
                # Fallback: GET /gradient returns {breakdown: {...}}
                response = await client.get(f"{self._energy_url}/gradient")
                if response.status_code == 200:
                    data = response.json()
                    bd = data.get("breakdown") if isinstance(data, dict) else None
                    if isinstance(bd, dict):
                        total = bd.get("total")
                        if isinstance(total, (int, float)):
                            return float(total)
        except Exception as e:
            logger.debug(f"Failed to get energy total: {e}")
        return None

    async def _log_evolution_event(self, op: str, organ_id: str, delta_E_est: Optional[float], 
                                 E_before: Optional[float], delta_E_realized: Optional[float], 
                                 cost: float, success: bool, error: Optional[str] = None):
        """Log evolution event to energy system (best-effort)."""
        try:
            # Map to FlywheelResultRequest schema
            delta_e = (
                float(delta_E_realized) if delta_E_realized is not None
                else (float(delta_E_est) if delta_E_est is not None else 0.0)
            )
            payload = {
                "delta_e": delta_e,
                "cost": float(cost),
                "scope": "evolution",
                "scope_id": str(organ_id),
            }
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(f"{self._energy_url}/flywheel/result", json=payload)
        except Exception as e:
            logger.debug(f"Failed to log evolution event: {e}")

    # -------------------------------------------------------------------------
    # Memory Interface (Bandit Hook)
    # -------------------------------------------------------------------------
    async def set_memory_thresholds(self, thresholds: Dict[str, float]) -> Dict[str, Any]:
        """Set memory thresholds and return current dE/dmem (best-effort)."""
        self._memory_thresholds.update(thresholds)
        
        # Try to get current dE/dmem from energy gradient
        dE_dmem = None
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._energy_url}/gradient")
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, dict):
                        grads = data.get("gradients")
                        if isinstance(grads, dict) and "mem" in grads:
                            val = grads.get("mem")
                            if isinstance(val, (int, float)):
                                dE_dmem = float(val)
                        if dE_dmem is None:
                            bd = data.get("breakdown")
                            if isinstance(bd, dict) and "mem" in bd:
                                val2 = bd.get("mem")
                                if isinstance(val2, (int, float)):
                                    dE_dmem = float(val2)
        except Exception as e:
            logger.debug(f"Failed to get memory gradient: {e}")
            
        return {
            "thresholds": self._memory_thresholds,
            "dE_dmem": dE_dmem,
            "status": "success"
        }


# Global instance (created by FastAPI lifespan after Ray connects)
organism_manager: Optional[OrganismManager] = None
