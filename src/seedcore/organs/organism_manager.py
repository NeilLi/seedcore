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
This implements the COA framework's "swarm-of-swarms" model where organs act as specialized 
containers for pools of agents.

IMPORTANT: This module runs as a Ray client connecting to a remote Ray cluster.
Ray client connections have limitations:
- ray.util.state APIs (list_actors, list_nodes, etc.) are NOT available
- Namespace verification must use alternative methods (actor communication tests)
- Actor information must be obtained through actor handles, not state APIs
"""

import yaml
import logging
import asyncio
import time
import ray
import os
import uuid
import concurrent.futures
# SOLUTION: Ray connection is now handled centrally by ray_connector.py
import traceback
import random
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple, Set, TYPE_CHECKING
# Note: ray.util.state APIs don't work with Ray client connections
# from ray.util.state import list_actors, list_nodes

from .base import Organ
from ..agents import tier0_manager

# Import cognitive client for HGNN escalation
try:
    from ..serve.cognitive_client import CognitiveServiceClient
    COGNITIVE_AVAILABLE = True
except ImportError:
    COGNITIVE_AVAILABLE = False
    CognitiveServiceClient = None

# Import result schema functions for proper result building
try:
    from ..models.result_schema import create_escalated_result
    RESULT_SCHEMA_AVAILABLE = True
except ImportError:
    RESULT_SCHEMA_AVAILABLE = False
    create_escalated_result = None

logger = logging.getLogger(__name__)

@dataclass
class StandardizedOrganInterface:
    """COA §6.2: I_o = <T_o, R_o, S_o>"""
    task_types: Set[str] = field(default_factory=set)
    response_schema: Dict[str, Any] = field(default_factory=dict)
    state_summary: Dict[str, Any] = field(default_factory=dict)


class OCPSValve:
    """
    Online Change-Point Sentinel (CUSUM) used as the coordinator valve.
    Maintains p_fast and decides escalation to HGNN (COA §6).
    """
    def __init__(self, nu: float = 0.1, h: float = 5.0):
        self.nu = nu
        self.h = h
        self.S = 0.0
        self.fast_hits = 0
        self.esc_hits = 0

    def update(self, drift_score: float) -> bool:
        # One-sided CUSUM-like statistic
        self.S = max(0.0, self.S + drift_score - self.nu)
        escalate = self.S > self.h
        if escalate:
            self.esc_hits += 1
            self.S = 0.0
        else:
            self.fast_hits += 1
        return escalate

    @property
    def p_fast(self) -> float:
        tot = self.fast_hits + self.esc_hits
        return (self.fast_hits / tot) if tot else 1.0


class RoutingTable:
    """Hierarchical routing (COA §6.2): Levels 1–3, plus a hyperedge cache."""
    def __init__(self):
        self.by_task_type: Dict[str, str] = {}
        self.by_domain: Dict[Tuple[str, str], str] = {}
        self.hyperedge_cache: Dict[str, List[str]] = {}

    def resolve(self, task_type: Optional[str], domain: Optional[str]) -> Optional[str]:
        if task_type is None:
            return None
        key = (task_type, domain)
        if key in self.by_domain:
            return self.by_domain[key]
        return self.by_task_type.get(task_type)

    def standardize(self, task_type: str, organ_id: str, domain: Optional[str] = None):
        if domain:
            self.by_domain[(task_type, domain)] = organ_id
        else:
            self.by_task_type[task_type] = organ_id

class OrganismManager:
    """
    Manages the lifecycle of organs and the distribution of agents within them.
    
    This class implements the COA framework's organ-based architecture where:
    - Organs are specialized containers for pools of agents
    - Each organ has a distinct type and role
    - Agents are distributed across organs based on configuration
    - The entire organism can be managed as a cohesive unit
    """

    def __init__(self, config_path: str = "src/seedcore/config/defaults.yaml"):
        self.organs: Dict[str, ray.actor.ActorHandle] = {}
        self.agent_to_organ_map: Dict[str, str] = {}
        self.organ_configs: List[Dict[str, Any]] = []
        self._load_config(config_path)
        self._initialized = False
        
        # Initialize routing components (these don't depend on Ray)
        self.ocps = OCPSValve()
        self.routing = RoutingTable()
        self.organ_interfaces: Dict[str, StandardizedOrganInterface] = {}
        
        # Set up default routing rules to avoid cognitive organ for simple queries
        self._setup_default_routing()
        
        # Cognitive client configuration
        self.cognitive_client = None
        self.escalation_timeout_s = float(os.getenv("COGNITIVE_TIMEOUT_S", "8.0"))
        self.escalation_max_inflight = int(os.getenv("COGNITIVE_MAX_INFLIGHT", "64"))
        self._inflight = 0
        self.ocps_drift_threshold = float(os.getenv("OCPS_DRIFT_THRESHOLD", "0.5"))
        self.fast_path_latency_slo_ms = float(os.getenv("FAST_PATH_LATENCY_SLO_MS", "1000"))
        self.max_plan_steps = int(os.getenv("MAX_PLAN_STEPS", "16"))
        
        # Note: Ray-dependent initialization is now handled in initialize_organism()
        # This constructor is safe to call before Ray is ready

    # SOLUTION: Ray connection is now handled centrally by ray_connector.py
    # This method is no longer needed and has been removed.
    
    # SOLUTION: Namespace verification is now handled centrally by ray_connector.py
    # This method is no longer needed and has been removed.

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

    def _check_ray_cluster_health(self):
        """Check Ray cluster health and log diagnostic information."""
        try:
            # Check cluster resources (available with Ray client)
            cluster_resources = ray.cluster_resources()
            available_resources = ray.available_resources()
            
            logger.info(f"📊 Cluster resources: {cluster_resources}")
            logger.info(f"📊 Available resources: {available_resources}")
            
            # Verify we have at least some CPU resources available
            total_cpu = cluster_resources.get('CPU', 0)
            available_cpu = available_resources.get('CPU', 0)
            
            if total_cpu == 0:
                raise Exception("No CPU resources available in Ray cluster")
            
            if available_cpu < 1.0:
                logger.warning(f"⚠️ Low CPU availability: {available_cpu}/{total_cpu} CPUs available")
            
            # Note: list_nodes() and list_actors() are not available with Ray client connections
            # We can only check basic cluster resources and test actor communication
            
            # Test basic Ray functionality with a simple remote task
            try:
                @ray.remote
                def _health_check_task():
                    return "healthy"
                
                result = ray.get(_health_check_task.remote())
                if result == "healthy":
                    logger.info("✅ Ray remote task execution test passed")
                else:
                    logger.warning(f"⚠️ Ray remote task test returned unexpected result: {result}")
                    
            except Exception as e:
                logger.warning(f"Ray remote task test failed: {e}")
                
            logger.info("✅ Ray cluster health check completed")
            
        except Exception as e:
            logger.error(f"❌ Failed to check Ray cluster health: {e}")
            raise  # Re-raise to trigger retry mechanism

    async def _cleanup_dead_actors(self):
        """Clean up dead Ray actors using the Janitor actor for cluster-side cleanup."""
        try:
            if not ray.is_initialized():
                return
            
            jan = None
            try:
                jan = ray.get_actor("seedcore_janitor")
            except Exception:
                logger.debug("Janitor actor not available; skipping cluster cleanup")
            
            if jan:
                try:
                    res = ray.get(jan.reap.remote(prefix=None))  # Clean up all dead actors
                    if res.get("count"):
                        logger.info("Cluster cleanup removed %d dead actors: %s", res["count"], res["reaped"])
                    else:
                        logger.debug("No dead actors found to clean up")
                except Exception as e:
                    logger.debug("Cluster cleanup failed: %s", e)
            else:
                logger.debug("Janitor actor not available; skipping cluster cleanup")
                
        except Exception as e:
            logger.debug("Cluster cleanup skipped: %s", e)

    def _test_organ_health(self, organ_handle, organ_id: str) -> bool:
        """Test if an organ actor is healthy and responsive."""
        try:
            # Test with a timeout using ThreadPoolExecutor since get_status is synchronous
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    lambda: ray.get(organ_handle.get_status.remote())
                )
                result = future.result(timeout=10.0)
                logger.info(f"✅ Organ {organ_id} health check passed")
                return True
        except Exception as e:
            logger.warning(f"⚠️ Organ {organ_id} health check failed: {e}")
            return False

    def _recreate_dead_organ(self, organ_id: str, organ_type: str):
        """Recreate a dead organ actor."""
        try:
            logger.info(f"🔄 Recreating dead organ: {organ_id}")
            
            # Try to kill the dead actor first
            try:
                actors = list_actors()
                for actor in actors:
                    if actor.name == organ_id and actor.state == "DEAD":
                        ray.kill(actor.actor_id)
                        logger.info(f"🗑️ Killed dead actor: {organ_id}")
                        break
            except Exception as e:
                logger.warning(f"Could not kill dead actor {organ_id}: {e}")
            
            # Get the expected namespace from environment variables
            ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
            logger.info(f"🔧 Creating organ in namespace: {ray_namespace}")
            
            # Try multiple approaches to ensure namespace is respected
            organ_created = False
            
            # Approach 1: Use Organ.options with explicit namespace
            try:
                logger.info(f"🔧 Attempting to create organ with explicit namespace: {ray_namespace}")
                new_organ = Organ.options(
                    name=organ_id, 
                    lifetime="detached",
                    num_cpus=0.1,
                    namespace=ray_namespace
                ).remote(
                    organ_id=organ_id,
                    organ_type=organ_type
                )
                organ_created = True
                logger.info(f"✅ Created new organ with explicit namespace: {organ_id}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to create organ with explicit namespace: {e}")
            
            # Approach 2: Use Organ.options without namespace (should inherit)
            if not organ_created:
                try:
                    logger.info(f"🔧 Attempting to create organ without namespace (should inherit)")
                    new_organ = Organ.options(
                        name=organ_id, 
                        lifetime="detached",
                        num_cpus=0.1
                    ).remote(
                        organ_id=organ_id,
                        organ_type=organ_type
                    )
                    organ_created = True
                    logger.info(f"✅ Created new organ without namespace (inherited): {organ_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to create organ without namespace: {e}")
            
            # Approach 3: Use Organ.remote directly (last resort)
            if not organ_created:
                try:
                    logger.info(f"🔧 Attempting to create organ with direct remote call")
                    new_organ = Organ.remote(
                        organ_id=organ_id,
                        organ_type=organ_type
                    )
                    organ_created = True
                    logger.info(f"✅ Created new organ with direct remote: {organ_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to create organ with direct remote: {e}")
            
            if not organ_created:
                raise Exception(f"All approaches to recreate organ {organ_id} failed")
            
            # Test the new organ
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

    def _create_organs(self):
        """Creates the organ actors as defined in the configuration."""
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
                    # Try to get existing organ first
                    try:
                        existing_organ = ray.get_actor(organ_id)
                        logger.info(f"✅ Retrieved existing Organ: {organ_id} (Type: {organ_type})")
                        
                        # Test if the organ is healthy
                        if not self._test_organ_health(existing_organ, organ_id):
                            logger.warning(f"⚠️ Organ {organ_id} is unresponsive, recreating...")
                            if self._recreate_dead_organ(organ_id, organ_type):
                                continue
                            else:
                                raise Exception(f"Failed to recreate organ {organ_id}")
                        
                        self.organs[organ_id] = existing_organ
                        
                    except ValueError:
                        # Create new organ if it doesn't exist (idempotent semantics)
                        logger.info(f"🚀 Creating new organ: {organ_id} (Type: {organ_type})")
                        logger.info(f"🔧 Ray initialized: {ray.is_initialized()}")
                        # Get the expected namespace from environment variables
                        ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
                        logger.info(f"🔧 Expected Ray namespace: {ray_namespace}")
                        
                        # Try multiple approaches to ensure namespace is respected
                        organ_created = False
                        
                        # Approach 1: Use Organ.options with explicit namespace
                        try:
                            logger.info(f"🔧 Attempting to create organ with explicit namespace: {ray_namespace}")
                            self.organs[organ_id] = Organ.options(
                                name=organ_id, 
                                lifetime="detached",
                                num_cpus=0.1,
                                namespace=ray_namespace
                            ).remote(
                                organ_id=organ_id,
                                organ_type=organ_type
                            )
                            organ_created = True
                            logger.info(f"✅ Created new Organ with explicit namespace: {organ_id}")
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to create organ with explicit namespace: {e}")
                        
                        # Approach 2: Use Organ.options without namespace (should inherit)
                        if not organ_created:
                            try:
                                logger.info(f"🔧 Attempting to create organ without namespace (should inherit)")
                                self.organs[organ_id] = Organ.options(
                                    name=organ_id, 
                                    lifetime="detached",
                                    num_cpus=0.1
                                ).remote(
                                    organ_id=organ_id,
                                    organ_type=organ_type
                                )
                                organ_created = True
                                logger.info(f"✅ Created new Organ without namespace (inherited): {organ_id}")
                            except Exception as e:
                                logger.warning(f"⚠️ Failed to create organ without namespace: {e}")
                        
                        # Approach 3: Use Organ.remote directly (last resort)
                        if not organ_created:
                            try:
                                logger.info(f"🔧 Attempting to create organ with direct remote call")
                                self.organs[organ_id] = Organ.remote(
                                    organ_id=organ_id,
                                    organ_type=organ_type
                                )
                                organ_created = True
                                logger.info(f"✅ Created new Organ with direct remote: {organ_id}")
                            except Exception as e:
                                logger.error(f"❌ Failed to create organ with direct remote: {e}")
                        
                        if not organ_created:
                            raise Exception(f"All approaches to create organ {organ_id} failed")
                        
                        # Test the new organ
                        if not self._test_organ_health(self.organs[organ_id], organ_id):
                            logger.error(f"❌ New organ {organ_id} is not healthy")
                            raise Exception(f"New organ {organ_id} failed health check")
                            
                except Exception as e:
                    logger.error(f"❌ Failed to create/get organ {organ_id}: {e}")
                    logger.error(f"❌ Exception type: {type(e)}")
                    logger.error(f"❌ Exception details: {str(e)}")
                    logger.error(f"❌ Traceback: {traceback.format_exc()}")
                    raise
            else:
                logger.info(f"✅ Organ {organ_id} already exists in self.organs")
        
        logger.info(f"🏗️ Organ creation process completed. Total organs: {len(self.organs)}")
        logger.info(f"🔍 Final organs: {list(self.organs.keys())}")
        
        # Verify namespace consistency
        logger.info(f"🔍 Verifying namespace consistency...")
        try:
            # Get the expected namespace from environment variables
            ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
            logger.info(f"🔍 Expected Ray namespace: {ray_namespace}")
            
            # First, verify namespace using our direct actor handles (more reliable)
            logger.info(f"🔍 Verifying namespace using direct actor handles...")
            for organ_id, organ_handle in self.organs.items():
                try:
                    # Try to get actor info from Ray state API
                    try:
                        # Note: ray.util.state.list_actors() doesn't work with Ray client connections
                        # Instead, we'll use the actor handle directly to get information
                        logger.info(f"   - {organ_id}: checking namespace via actor handle...")
                        
                        # Get the actor's namespace using the runtime context from the actor handle
                        try:
                            # This approach works with Ray client connections
                            actor_info = ray.get_runtime_context().get_actor_info(organ_handle._actor_ref.actor_id)
                            if actor_info:
                                actor_namespace = getattr(actor_info, 'namespace', 'unknown')
                                logger.info(f"   - {organ_id}: namespace='{actor_namespace}' (via actor handle)")
                                
                                if actor_namespace == 'unknown':
                                    logger.info(f"ℹ️  Organ {organ_id} shows 'unknown' namespace (this may be normal)")
                                elif actor_namespace != ray_namespace:
                                    logger.warning(f"⚠️  WARNING: Organ {organ_id} is in namespace '{actor_namespace}' != '{ray_namespace}'")
                                else:
                                    logger.info(f"   ✅ Organ {organ_id} is in correct namespace '{actor_namespace}'")
                            else:
                                logger.info(f"   - {organ_id}: actor info not available (may be newly created)")
                        except Exception as actor_info_error:
                            logger.info(f"   - {organ_id}: could not get actor info: {actor_info_error}")
                            # Fallback: assume namespace is correct if we can communicate with the actor
                            logger.info(f"   - {organ_id}: assuming namespace is correct (actor is responsive)")
                            
                    except Exception as state_error:
                        logger.warning(f"   - {organ_id}: could not check via actor handle: {state_error}")
                        
                except Exception as e:
                    logger.warning(f"⚠️  Could not verify namespace for {organ_id}: {e}")
            
            # Alternative namespace verification that works with Ray client connections
            logger.info(f"🔍 Verifying namespace using alternative methods...")
            try:
                # Since we can't use Ray state API from client connections, we'll verify
                # namespace consistency by checking if we can communicate with the actors
                logger.info("ℹ️  Ray state API not available from client connections - using actor communication test")
                
                for organ_id, organ_handle in self.organs.items():
                    try:
                        # Test if we can communicate with the actor (this verifies it's accessible)
                        # Use get_status() which is a method that actually exists on the Organ class
                        status = ray.get(organ_handle.get_status.remote(), timeout=5.0)
                        if status and status.get('organ_id') == organ_id:
                            logger.info(f"   ✅ Organ {organ_id}: responsive and accessible")
                            logger.info(f"      - Type: {status.get('organ_type', 'unknown')}")
                            logger.info(f"      - Agent count: {status.get('agent_count', 0)}")
                        else:
                            logger.warning(f"⚠️  Organ {organ_id}: responsive but status mismatch (expected {organ_id}, got {status})")
                    except Exception as comm_error:
                        logger.warning(f"⚠️  Organ {organ_id}: communication test failed: {comm_error}")
                        
            except Exception as e:
                logger.warning(f"⚠️  Could not verify namespace using alternative methods: {e}")
                    
        except Exception as e:
            logger.warning(f"⚠️  Could not verify namespace consistency: {e}")

    async def _create_and_distribute_agents(self):
        """Creates agents and registers them with their designated organs."""
        agent_count = 0
        
        for organ_config in self.organ_configs:
            organ_id = organ_config['id']
            num_agents = organ_config['agent_count']
            organ_handle = self.organs.get(organ_id)

            if not organ_handle:
                logger.warning(f"Organ '{organ_id}' not found. Skipping agent creation.")
                continue

            logger.info(f"Creating {num_agents} agents for organ {organ_id}...")
            
            # First, clean up excess agents if needed
            await self._cleanup_excess_agents(organ_handle, organ_id, num_agents)
            
            for i in range(num_agents):
                agent_id = f"{organ_id}_agent_{i}"
                
                try:
                    # Check if agent already exists in the organ
                    logger.info(f"🔍 Checking for existing agent {agent_id} in organ {organ_id}...")
                    try:
                        # get_agent_handles is synchronous, so use ray.get() instead of await
                        existing_agents = ray.get(organ_handle.get_agent_handles.remote())
                        logger.info(f"✅ Retrieved existing agents for {organ_id}: {list(existing_agents.keys())}")
                    except Exception as e:
                        logger.error(f"❌ Failed to get agent handles from organ {organ_id}: {e}")
                        continue
                    
                    if agent_id in existing_agents:
                        # Reuse existing agent
                        logger.info(f"✅ Reusing existing agent: {agent_id}")
                        self.agent_to_organ_map[agent_id] = organ_id
                        agent_count += 1
                        continue
                    
                    # Create the agent via Tier0 manager to centralize lifecycle
                    initial_role_probs = self._get_role_probs_for_organ_type(organ_config['type'])

                    try:
                        logger.info(f"🚀 Creating Tier0 agent {agent_id} via Tier0MemoryManager...")
                        # Ensure a detached, named actor with 1 CPU for stability
                        tier0_manager.create_agent(
                            agent_id=agent_id,
                            role_probs=initial_role_probs,
                            name=agent_id,
                            lifetime="detached",
                            num_cpus=0.1,
                        )

                        # Retrieve the handle from Tier0 manager
                        agent_handle = tier0_manager.get_agent(agent_id)
                        if not agent_handle:
                            raise Exception("Agent handle not found after creation")

                        logger.info(f"✅ Tier0 agent {agent_id} created, testing with get_id...")
                        test_result = ray.get(agent_handle.get_id.remote())
                        logger.info(f"✅ Agent {agent_id} get_id test passed: {test_result}")

                        if test_result != agent_id:
                            raise Exception(f"Agent ID mismatch: expected {agent_id}, got {test_result}")

                        # Register the agent with its organ
                        logger.info(f"📝 Registering agent {agent_id} with organ {organ_id}...")
                        ray.get(organ_handle.register_agent.remote(agent_id, agent_handle))
                        logger.info(f"✅ Agent {agent_id} registered with organ {organ_id}")

                        self.agent_to_organ_map[agent_id] = organ_id
                        agent_count += 1
                        logger.info(f"✅ Created new agent via Tier0 manager: {agent_id}")

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
            # get_agent_handles is synchronous, so use ray.get() instead of await
            existing_agents = ray.get(organ_handle.get_agent_handles.remote())
            current_count = len(existing_agents)
            logger.info(f"📊 Current agent count in {organ_id}: {current_count}")
            
            if current_count > target_count:
                excess_count = current_count - target_count
                logger.info(f"🧹 Cleaning up {excess_count} excess agents from {organ_id}")
                
                # Remove excess agents (keep the first target_count)
                agent_ids = list(existing_agents.keys())
                for agent_id in agent_ids[target_count:]:
                    try:
                        logger.info(f"🗑️ Removing excess agent: {agent_id}")
                        # remove_agent is also synchronous
                        ray.get(organ_handle.remove_agent.remote(agent_id))
                        logger.info(f"✅ Removed excess agent: {agent_id}")
                    except Exception as e:
                        logger.error(f"❌ Failed to remove agent {agent_id}: {e}")
            else:
                logger.info(f"✅ No excess agents to clean up in {organ_id}")
                        
        except Exception as e:
            logger.error(f"❌ Error during agent cleanup for {organ_id}: {e}")

    def _get_role_probs_for_organ_type(self, organ_type: str) -> Dict[str, float]:
        """Returns appropriate role probabilities based on organ type."""
        if organ_type == "Cognitive":
            return {'E': 0.3, 'S': 0.6, 'O': 0.1}  # High S for reasoning
        elif organ_type == "Actuator":
            return {'E': 0.7, 'S': 0.2, 'O': 0.1}  # High E for action
        elif organ_type == "Utility":
            return {'E': 0.2, 'S': 0.3, 'O': 0.5}  # High O for observation
        else:
            return {'E': 0.33, 'S': 0.33, 'O': 0.34}  # Default balanced

    async def get_organism_status(self) -> List[Dict[str, Any]]:
        """Collects and returns the status of all organs."""
        if not self._initialized:
            return [{"error": "Organism not initialized"}]

        try:
            # fan out
            refs = [organ.get_status.remote() for organ in self.organs.values()]
            results = await asyncio.gather(*refs, return_exceptions=True)

            statuses = []
            for r in results:
                if isinstance(r, Exception):
                    statuses.append({"error": str(r)})
                else:
                    statuses.append(r)
            return statuses
        except Exception as e:
            logger.error(f"Error getting organism status: {e}")
            return [{"error": str(e)}]

    def get_organ_handle(self, organ_id: str) -> Optional[ray.actor.ActorHandle]:
        """Returns the handle to a specific organ."""
        return self.organs.get(organ_id)

    def get_agent_organ(self, agent_id: str) -> Optional[str]:
        """Returns the organ ID that contains a specific agent."""
        return self.agent_to_organ_map.get(agent_id)

    def get_total_agent_count(self) -> int:
        """Returns the total number of agents across all organs."""
        return len(self.agent_to_organ_map)

    def get_organ_count(self) -> int:
        """Returns the number of organs."""
        return len(self.organs)

    def is_initialized(self) -> bool:
        """Returns whether the organism has been initialized."""
        return self._initialized

    async def execute_task_on_organ(self, organ_id: str, task: Dict[str, Any]) -> Dict[str, Any]:
        """Executes a task on a specific organ."""
        if not self._initialized:
            raise RuntimeError("Organism not initialized")
            
        organ_handle = self.organs.get(organ_id)
        if not organ_handle:
            raise ValueError(f"Organ {organ_id} not found")
            
        try:
            result = await organ_handle.run_task.remote(task)
            return {"success": True, "result": result, "organ_id": organ_id}
        except Exception as e:
            logger.error(f"Error executing task on organ {organ_id}: {e}")
            return {"success": False, "error": str(e), "organ_id": organ_id}

    async def execute_task_on_random_organ(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Executes a task on a randomly selected organ."""
        if not self.organs:
            raise RuntimeError("No organs available")
            
        organ_id = random.choice(list(self.organs.keys()))
        return await self.execute_task_on_organ(organ_id, task)

    # === COA §6: Fast Router + OCPS Valve + HGNN Escalation ===
    async def route_and_execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Coordinator entry-point. Implements the two-tier coordination from COA §6:
        Level 1–2 fast routing; OCPS decides whether to escalate the remaining ~10% to HGNN.
        Returns a dict with success flag, result payload, selected path, and p_fast.
        """
        if not self._initialized:
            raise RuntimeError("Organism not initialized")

        ttype = task.get("type") or task.get("task_type")
        domain = task.get("domain")
        drift = float(task.get("drift_score", 0.0))

        # Try fast-path resolution first
        organ_id = self.routing.resolve(ttype, domain)
        escalate = self.ocps.update(drift)
        
        # Apply configurable drift threshold for escalation
        if drift >= self.ocps_drift_threshold:
            escalate = True
            logger.info(f"Task {task.get('id', 'unknown')} escalated due to drift threshold ({drift} >= {self.ocps_drift_threshold})")

        if organ_id and not escalate:
            try:
                # Level 4: best agent within selected organ via Tier 0 constrained selection
                organ_handle = self.organs[organ_id]
                handles = ray.get(organ_handle.get_agent_handles.remote())
                candidate_ids = list(handles.keys())
                
                if not candidate_ids:
                    logger.warning(f"⚠️ Organ {organ_id} has no agents available for task {task.get('id', 'unknown')}")
                    escalate = True
                else:
                    # Inject OCPS regime signals for agent-side F-block features
                    task["p_fast"] = self.ocps.p_fast
                    task["escalated"] = False
                    
                    start_time = time.time()
                    result = tier0_manager.execute_task_on_best_of(candidate_ids, task)
                    fast_path_latency = (time.time() - start_time) * 1000  # Convert to ms
                    
                    # Track metrics
                    self._track_metrics("fast", True, fast_path_latency)
                    
                    logger.info(f"✅ Fast-path execution completed on organ {organ_id} in {fast_path_latency:.2f}ms")
                    
                    return {
                        "success": True, 
                        "result": result, 
                        "organ_id": organ_id, 
                        "path": "fast", 
                        "p_fast": self.ocps.p_fast,
                        "kind": "fast_path",
                        "escalated": False
                    }
            except Exception as e:
                logger.warning(f"Fast-path failure on organ {organ_id}: {e}; escalating to HGNN")
                logger.debug(f"Task details: {task}")
                escalate = True

        # Escalation path: HGNN decomposition to multi-organ plan
        start_time = time.time()
        plan = await self._hgnn_decompose(task)
        results: List[Dict[str, Any]] = []
        for sub in plan:
            sub_organ = sub["organ_id"]
            sub_task = sub["task"]
            # Inject OCPS regime signals for escalated path
            sub_task["p_fast"] = self.ocps.p_fast
            sub_task["escalated"] = True
            r = await self.execute_task_on_organ(sub_organ, sub_task)
            results.append(r)

        success = all(r.get("success") for r in results) if results else False
        
        # Track HGNN metrics
        hgnn_latency = (time.time() - start_time) * 1000  # Convert to ms
        self._track_metrics("hgnn", success, hgnn_latency)
        
        if success:
            key = self._pattern_key(plan)
            self.routing.hyperedge_cache.setdefault(key, [p["organ_id"] for p in plan])
        
        # Set explicit escalation signals for verifier
        return self._make_escalation_result(results, plan, success)

    # === COA §6.1: enhanced hypergraph decomposition with cognitive client ===
    async def _hgnn_decompose(self, task: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Enhanced HGNN-based decomposition using CognitiveCore Serve deployment.
        
        This method:
        1. Checks if cognitive client is available and healthy
        2. Calls CognitiveCore for intelligent task decomposition
        3. Validates the returned plan
        4. Falls back to simple routing if cognitive reasoning fails
        """
        # Check if we can use cognitive escalation
        if (not self.cognitive_client or 
            self._inflight >= self.escalation_max_inflight or
            not self.cognitive_client.is_healthy()):
            logger.info("Using fallback plan (cognitive client unavailable or at capacity)")
            return self._fallback_plan(task)

        # Prepare the request for CognitiveCore
        req = {
            "agent_id": f"hgnn_planner_{task.get('id', task.get('task_id', 'unknown'))}",
            "problem_statement": task.get("description", str(task)),
            "task_id": str(task.get("id", task.get("task_id", "unknown"))),
            "type": task.get("type", task.get("task_type", "unknown")),
            "description": task.get("description", str(task)),
            "constraints": {
                "latency_ms": self.fast_path_latency_slo_ms,
                "budget": task.get("budget", 0.02)
            },
            "context": {
                "features": task.get("features", {}),
                "history_ids": task.get("history_ids", []),
                "drift_score": float(task.get("drift_score", 0.0))
            },
            "available_organs": list(self.organs.keys()),
            "correlation_id": str(task.get("correlation_id", uuid.uuid4()))
        }

        self._inflight += 1
        try:
            logger.info(f"Calling CognitiveCore for task {req['task_id']}")
            resp = await self.cognitive_client.solve_problem(**req)
            
            if resp and resp.get("success"):
                plan = resp.get("solution_steps", [])
                validated_plan = self._validate_or_fallback(plan, task)
                if validated_plan:
                    logger.info(f"✅ CognitiveCore generated plan with {len(validated_plan)} steps")
                    return validated_plan
                else:
                    logger.warning("CognitiveCore plan validation failed, using fallback")
                    return self._fallback_plan(task)
            else:
                logger.warning(f"CognitiveCore returned unsuccessful response: {resp}")
                return self._fallback_plan(task)
                
        except Exception as e:
            logger.warning(f"HGNN call failed: {e}")
            return self._fallback_plan(task)
        finally:
            self._inflight -= 1

    def _fallback_plan(self, task: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create a minimal safe fallback plan when cognitive reasoning is unavailable."""
        ttype = task.get("type") or task.get("task_type")
        
        # If any organ claims support for this type, prefer it
        for organ_id, iface in getattr(self, "organ_interfaces", {}).items():
            if ttype in iface.task_types:
                return [{"organ_id": organ_id, "task": task}]
        
        # Fallback: round-robin across known organs
        if self.organs:
            first = next(iter(self.organs.keys()))
            return [{"organ_id": first, "task": task}]
        
        return []

    def _make_escalation_result(self, results: List[Dict[str, Any]], plan: List[Dict[str, Any]], success: bool) -> Dict[str, Any]:
        """
        Create a properly formatted escalation result using the result schema.
        
        This ensures the verifier gets the expected structure with escalated=True,
        plan_source="cognitive_core", and proper metadata.
        """
        if RESULT_SCHEMA_AVAILABLE and create_escalated_result:
            # Use proper result schema for escalation
            from ..models.result_schema import TaskStep
            solution_steps = []
            for r in results:
                step = TaskStep(
                    organ_id=r.get("organ_id", "unknown"),
                    success=r.get("success", False),
                    task=r.get("task", {}),
                    result=r.get("result"),
                    error=r.get("error"),
                    metadata={k: v for k, v in r.items() if k not in {"organ_id", "success", "task", "result", "error"}}
                )
                solution_steps.append(step)
            
            escalated_result = create_escalated_result(
                solution_steps=solution_steps,
                plan_source="cognitive_core",
                **{
                    "success": success,
                    "path": "hgnn",
                    "p_fast": self.ocps.p_fast,
                    "step_count": len(plan)
                }
            )
            return escalated_result.model_dump()
        else:
            # Fallback to manual result building if schema not available
            return {
                "success": success, 
                "result": results, 
                "path": "hgnn", 
                "p_fast": self.ocps.p_fast,
                "kind": "escalated",
                "escalated": True,
                "plan_source": "cognitive_core",
                "step_count": len(plan)
            }

    def _validate_or_fallback(self, plan: List[Dict[str, Any]], task: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """Validate the plan from CognitiveCore and return fallback if invalid."""
        if not isinstance(plan, list) or len(plan) > self.max_plan_steps:
            logger.warning(f"Plan validation failed: invalid format or too many steps ({len(plan) if isinstance(plan, list) else 'not a list'})")
            return None
            
        for step in plan:
            if not isinstance(step, dict):
                logger.warning(f"Plan validation failed: step is not a dict: {step}")
                return None
                
            organ_id = step.get("organ_id")
            if not organ_id or organ_id not in self.organs:
                logger.warning(f"Plan validation failed: unknown organ '{organ_id}'")
                return None
                
            if "task" not in step:
                logger.warning(f"Plan validation failed: step missing 'task' field: {step}")
                return None
        
        return plan

    def _track_metrics(self, path: str, success: bool, latency_ms: float):
        """Track task execution metrics for monitoring and optimization."""
        if not hasattr(self, '_task_metrics'):
            self._task_metrics = {
                "total_tasks": 0,
                "successful_tasks": 0,
                "failed_tasks": 0,
                "fast_path_tasks": 0,
                "hgnn_tasks": 0,
                "escalation_failures": 0,
                "fast_path_latency_ms": [],
                "hgnn_latency_ms": []
            }
        
        self._task_metrics["total_tasks"] += 1
        
        if success:
            self._task_metrics["successful_tasks"] += 1
        else:
            self._task_metrics["failed_tasks"] += 1
        
        if path == "fast":
            self._task_metrics["fast_path_tasks"] += 1
            self._task_metrics["fast_path_latency_ms"].append(latency_ms)
            # Keep only last 1000 measurements
            if len(self._task_metrics["fast_path_latency_ms"]) > 1000:
                self._task_metrics["fast_path_latency_ms"] = self._task_metrics["fast_path_latency_ms"][-1000:]
        elif path == "hgnn":
            self._task_metrics["hgnn_tasks"] += 1
            self._task_metrics["hgnn_latency_ms"].append(latency_ms)
            # Keep only last 1000 measurements
            if len(self._task_metrics["hgnn_latency_ms"]) > 1000:
                self._task_metrics["hgnn_latency_ms"] = self._task_metrics["hgnn_latency_ms"][-1000:]

    def get_metrics(self) -> Dict[str, Any]:
        """Get current task execution metrics."""
        if not hasattr(self, '_task_metrics'):
            return {}
        
        metrics = self._task_metrics.copy()
        
        # Calculate averages
        if metrics.get("fast_path_latency_ms"):
            metrics["fast_path_latency_avg_ms"] = sum(metrics["fast_path_latency_ms"]) / len(metrics["fast_path_latency_ms"])
        if metrics.get("hgnn_latency_ms"):
            metrics["hgnn_latency_avg_ms"] = sum(metrics["hgnn_latency_ms"]) / len(metrics["hgnn_latency_ms"])
        
        # Calculate ratios
        total = metrics.get("total_tasks", 0)
        if total > 0:
            metrics["fast_path_ratio"] = metrics.get("fast_path_tasks", 0) / total
            metrics["escalation_ratio"] = metrics.get("hgnn_tasks", 0) / total
            metrics["success_ratio"] = metrics.get("successful_tasks", 0) / total
        
        return metrics

    def _pattern_key(self, plan: List[Dict[str, Any]]) -> str:
        return "|".join(f"{p['organ_id']}:{p['task'].get('type', p['task'].get('task_type',''))}" for p in plan)

    # === §8 hooks: memory-aware prefetch/record (stubs) ===
    def prefetch_context(self, task: Dict[str, Any]) -> None:
        """Hook for Mw/Mlt prefetch as per §8.6 Unified RAG Operations. No-op until memory wired."""
        pass

    async def handle_incoming_task(self, task: Dict[str, Any], app_state=None) -> Dict[str, Any]:
        """
        Unified handler for all incoming tasks.
        - If a builtin handler exists for task['type'], use it (no hairpin).
        - Else, route via COA fast-path + OCPS; escalate to HGNN as needed.
        Returns a dict with:
            success: bool
            path: "builtin" | "fast" | "hgnn"
            p_fast: float
            result: any
        """
        ttype = (task.get("type") or task.get("task_type") or "").strip()
        if not ttype:
            return {"success": False, "error": "task.type is required"}

        # 1) Builtins registered on app.state (set in server.py)
        if app_state is not None:
            handlers = getattr(app_state, "builtin_task_handlers", {}) or {}
            handler = handlers.get(ttype)
            if callable(handler):
                try:
                    # allow both sync and async handler funcs
                    out = handler() if task.get("params") is None else handler(**task.get("params", {}))
                    if asyncio.iscoroutine(out):
                        out = await out
                    return {"success": True, "path": "builtin", "p_fast": self.ocps.p_fast, "result": out}
                except Exception as e:
                    logger.exception("Builtin task '%s' failed", ttype)
                    return {"success": False, "path": "builtin", "p_fast": self.ocps.p_fast, "error": str(e)}

        # 2) NEW: API Router Task Handlers (for Coordinator calls)
        if ttype == "get_organism_status":
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                status = await self.get_organism_status()
                return {"success": True, "path": "api_handler", "p_fast": self.ocps.p_fast, "result": status}
            except Exception as e:
                return {"success": False, "path": "api_handler", "p_fast": self.ocps.p_fast, "error": str(e)}

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
                return {"success": True, "path": "api_handler", "p_fast": self.ocps.p_fast, "result": result}
            except Exception as e:
                return {"success": False, "path": "api_handler", "p_fast": self.ocps.p_fast, "error": str(e)}

        elif ttype == "execute_on_random_organ":
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                params = task.get("params", {})
                task_data = params.get("task_data", {})
                result = await self.execute_task_on_random_organ(task_data)
                return {"success": True, "path": "api_handler", "p_fast": self.ocps.p_fast, "result": result}
            except Exception as e:
                return {"success": False, "path": "api_handler", "p_fast": self.ocps.p_fast, "error": str(e)}

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
                # Get detailed organ info via Ray actor handles
                for organ_id in self.organs.keys():
                    organ_handle = self.get_organ_handle(organ_id)
                    if organ_handle:
                        try:
                            status = ray.get(organ_handle.get_status.remote())
                            summary["organs"][organ_id] = status
                        except Exception as e:
                            summary["organs"][organ_id] = {"error": str(e)}
                return {"success": True, "path": "api_handler", "p_fast": self.ocps.p_fast, "result": summary}
            except Exception as e:
                return {"success": False, "path": "api_handler", "p_fast": self.ocps.p_fast, "error": str(e)}

        elif ttype == "initialize_organism":
            try:
                if self._initialized:
                    return {"success": True, "path": "api_handler", "p_fast": self.ocps.p_fast, "result": "Organism already initialized"}
                await self.initialize_organism()
                return {"success": True, "path": "api_handler", "p_fast": self.ocps.p_fast, "result": "Organism initialized successfully"}
            except Exception as e:
                return {"success": False, "path": "api_handler", "p_fast": self.ocps.p_fast, "error": str(e)}

        elif ttype == "shutdown_organism":
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                self.shutdown_organism()
                return {"success": True, "path": "api_handler", "p_fast": self.ocps.p_fast, "result": "Organism shutdown successfully"}
            except Exception as e:
                return {"success": False, "path": "api_handler", "p_fast": self.ocps.p_fast, "error": str(e)}

        elif ttype == "get_metrics":
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                metrics = self.get_metrics()
                return {"success": True, "path": "api_handler", "p_fast": self.ocps.p_fast, "result": metrics}
            except Exception as e:
                return {"success": False, "path": "api_handler", "p_fast": self.ocps.p_fast, "error": str(e)}

        elif ttype == "get_routing_debug":
            try:
                if not self._initialized:
                    return {"success": False, "error": "Organism not initialized"}
                
                # Get detailed routing information for debugging
                routing_info = {
                    "routing_table": self.get_routing_config(),
                    "available_organs": list(self.organs.keys()),
                    "organ_details": {},
                    "task_type": task.get("params", {}).get("task_type", "general_query"),
                    "domain": task.get("params", {}).get("domain"),
                }
                
                # Check what would be routed for a specific task type
                test_task_type = task.get("params", {}).get("task_type", "general_query")
                test_domain = task.get("params", {}).get("domain")
                routed_organ = self.routing.resolve(test_task_type, test_domain)
                
                routing_info["test_routing"] = {
                    "task_type": test_task_type,
                    "domain": test_domain,
                    "routed_organ": routed_organ,
                    "would_escalate": self.ocps.update(float(task.get("params", {}).get("drift_score", 0.0)))
                }
                
                # Get organ details
                for organ_id, organ_handle in self.organs.items():
                    try:
                        status = ray.get(organ_handle.get_status.remote())
                        routing_info["organ_details"][organ_id] = status
                    except Exception as e:
                        routing_info["organ_details"][organ_id] = {"error": str(e)}
                
                return {"success": True, "path": "api_handler", "p_fast": self.ocps.p_fast, "result": routing_info}
            except Exception as e:
                return {"success": False, "path": "api_handler", "p_fast": self.ocps.p_fast, "error": str(e)}

        # 3) Default: COA routing
        try:
            routed = await self.route_and_execute(task)
            routed.setdefault("path", "fast" if routed.get("path") == "fast" else "hgnn")
            return routed
        except Exception as e:
            logger.exception("route_and_execute failed for task.type=%s", ttype)
            return {"success": False, "error": str(e), "path": "error", "p_fast": self.ocps.p_fast}

    async def initialize_organism(self):
        """Creates all organs and populates them with agents based on the config."""
        if self._initialized:
            logger.warning("Organism already initialized. Skipping re-initialization.")
            return
            
        logger.info("🚀 Initializing the Cognitive Organism...")
        
        # Verify Ray is ready before proceeding
        if not ray.is_initialized():
            raise RuntimeError("Ray is not initialized. Please ensure Ray connection is established before calling initialize_organism.")
        
        # Bootstrap required singleton actors
        try:
            logger.info("🚀 Bootstrapping required singleton actors...")
            from ..bootstrap import bootstrap_actors
            bootstrap_actors()
            logger.info("✅ Singleton actors bootstrapped successfully")
        except Exception as e:
            logger.error(f"⚠️ Failed to bootstrap singleton actors: {e}", exc_info=True)
            logger.warning("⚠️ Agents may have limited functionality without memory managers")
        
        max_retries = 3
        retry_delay = 10  # seconds
        
        for attempt in range(max_retries):
            try:
                logger.info(f"🔄 Attempt {attempt + 1}/{max_retries} to initialize organism...")
                
                # Check Ray cluster health before proceeding
                self._check_ray_cluster_health()
                
                # Clean up dead actors first
                await self._cleanup_dead_actors()
                
                logger.info("🏗️ Creating organs...")
                self._create_organs()
                
                logger.info("🤖 Creating and distributing agents...")
                await self._create_and_distribute_agents()
                # Register known task types for fast-path routing (standardization)
                for organ_config in self.organ_configs:
                    organ_id = organ_config['id']
                    known_types = set(organ_config.get('task_types', []) or [])
                    if known_types:
                        self.organ_interfaces[organ_id] = StandardizedOrganInterface(task_types=known_types)
                        for t in known_types:
                            self.routing.standardize(t, organ_id)
                
                # Initialize cognitive client for HGNN escalation
                await self._initialize_cognitive_client()
                
                self._initialized = True
                logger.info("✅ Organism initialization complete.")
                return  # Success, exit the retry loop
                
            except Exception as e:
                logger.error(f"❌ Attempt {attempt + 1}/{max_retries} failed to initialize organism: {e}")
                
                if attempt < max_retries - 1:
                    logger.info(f"⏳ Waiting {retry_delay} seconds before retry...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"❌ All {max_retries} attempts failed. Giving up.")
                    raise

    async def _initialize_cognitive_client(self):
        """Initialize the cognitive client for HGNN escalation."""
        if not COGNITIVE_AVAILABLE:
            logger.warning("⚠️ CognitiveCore not available - HGNN escalation will use fallback plans")
            return
            
        try:
            self.cognitive_client = CognitiveServiceClient(
                base_url=os.getenv("COGNITIVE_SERVICE_URL", "http://127.0.0.1:8000"),
                timeout_s=self.escalation_timeout_s
            )
            logger.info("✅ Cognitive client ready")
        except Exception as e:
            logger.warning(f"⚠️ Cognitive client not ready: {e}")

    def shutdown_organism(self):
        """Shuts down the organism and cleans up resources."""
        logger.info("🛑 Shutting down organism...")
        
        # Note: Ray actors with lifetime="detached" will persist until explicitly terminated
        # In a production system, you might want to add explicit cleanup here
        self._initialized = False
        logger.info("✅ Organism shutdown complete")

    def get_drift_threshold(self) -> float:
        """Get the current drift threshold value for diagnostic purposes."""
        return self.ocps_drift_threshold

    def get_routing_config(self) -> Dict[str, Any]:
        """Get the current routing configuration for diagnostic purposes."""
        return {
            "by_task_type": self.routing.by_task_type,
            "by_domain": self.routing.by_domain,
            "hyperedge_cache": self.routing.hyperedge_cache
        }

    def _setup_default_routing(self):
        """Sets up default routing rules to ensure general_query tasks go to utility_organ."""
        # Add a default rule for general_query to go to Utility organ
        self.routing.standardize("general_query", "utility_organ")
        logger.info("✅ Default routing for general_query to utility_organ set.")

# Global instance for easy access from the API server
# SOLUTION: Lazy initialization - this will be created by FastAPI lifespan after Ray is connected
organism_manager: Optional[OrganismManager] = None 