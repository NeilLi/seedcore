#!/usr/bin/env python3
"""
State Service - Standalone Ray Serve Application

This service provides centralized state aggregation for the SeedCore system.
It collects state from distributed Ray actors and memory managers, producing
UnifiedState objects that can be consumed by other services.

Key Features:
- Efficient batch collection from Ray actors
- Smart caching to reduce overhead
- Error handling and graceful degradation
- Support for all memory tiers (ma, mw, mlt, mfb)
- Real-time E_patterns collection
- RESTful API for state queries

This service implements Paper §3.1 requirements for light aggregators from
live Ray actors and memory managers.
"""

import asyncio
import logging
import time
import os
import json
import urllib.request
from typing import Dict, List, Optional, Any
import numpy as np
import ray
from ray import serve
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from ..models.state import (
    UnifiedState, 
    AgentSnapshot, 
    OrganState, 
    SystemState, 
    MemoryVector
)
from ..state import (
    AgentStateAggregator,
    MemoryManagerAggregator,
    SystemStateAggregator
)

from seedcore.logging_setup import ensure_serve_logger
from seedcore.utils.ray_utils import COG

logger = ensure_serve_logger("seedcore.state", level="DEBUG")

# --- Request/Response Models ---
class StateRequest(BaseModel):
    agent_ids: Optional[List[str]] = None
    include_organs: bool = True
    include_system: bool = True
    include_memory: bool = True

class StateResponse(BaseModel):
    success: bool
    unified_state: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: float
    collection_time_ms: float

class HealthResponse(BaseModel):
    status: str
    service: str
    initialized: bool
    organism_connected: bool
    cognitive_connected: bool
    error: Optional[str] = None

# --- FastAPI App ---
app = FastAPI(title="SeedCore State Service", version="1.0.0")

@serve.deployment(
    name="StateService",
    num_replicas=1,
    max_ongoing_requests=32,
    ray_actor_options={
        "num_cpus": 0.5,
        "num_gpus": 0,
        "memory": 1073741824,  # 1GB
        "resources": {"head_node": 0.001},
    },
)
@serve.ingress(app)
class StateService:
    """
    Standalone state aggregation service.
    
    This service collects state from distributed Ray actors and memory managers,
    providing a unified view of the system state for energy calculations,
    monitoring, and other consumers.
    """
    
    def __init__(self):
        self.organism_manager = None
        self.cognitive_service = None
        self._initialized = False
        self._init_lock = asyncio.Lock()
        
        # Initialize specialized aggregators (will be set when organism is connected)
        self.agent_aggregator = None
        self.memory_aggregator = None
        self.system_aggregator = None
        # Base URLs (HTTP fallbacks)
        try:
            self._cog_base = os.getenv("COGNITIVE_BASE_URL", COG)
        except Exception:
            self._cog_base = os.getenv("COGNITIVE_BASE_URL", "http://127.0.0.1:8000/cognitive")
        
        # ASGI app integration
        self._app = app
        
        logger.info("✅ StateService initialized - will connect to organism manager on first request")
    
    
    async def _serve_asgi_lifespan(self, scope, receive, send):
        """ASGI lifespan handler for Ray Serve."""
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await self._lazy_init()
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    break
    
    async def _lazy_init(self):
        """Initialize the service by connecting to the organism manager."""
        if self._initialized:
            return
            
        async with self._init_lock:
            if self._initialized:
                return
                
            try:
                # Get the organism manager from Ray Serve - try different app names
                organism_handle = None
                for app_name in ["organism", "coordinator"]:
                    try:
                        organism_handle = serve.get_deployment_handle("OrganismManager", app_name=app_name)
                        logger.info(f"✅ StateService connected to organism manager with app_name: {app_name}")
                        break
                    except Exception as e:
                        logger.debug(f"Failed to connect to organism manager with app_name {app_name}: {e}")
                        continue
                
                if organism_handle is None:
                    logger.warning("⚠️ Organism manager not available - StateService will work in limited mode")
                    self._initialized = True
                    return
                
                self.organism_manager = organism_handle
                
                # Initialize specialized aggregators
                self.agent_aggregator = AgentStateAggregator(organism_handle, cache_ttl=5.0)
                self.memory_aggregator = MemoryManagerAggregator(organism_handle, cache_ttl=5.0)
                self.system_aggregator = SystemStateAggregator(organism_handle, cache_ttl=5.0)

                # Try to attach CognitiveService (Serve) as an optional provider for E_patterns
                try:
                    self.cognitive_service = serve.get_deployment_handle(
                        "CognitiveService", app_name="cognitive"
                    )
                    logger.info("✅ StateService connected to CognitiveService via Serve handle (app: cognitive)")
                except Exception as e:
                    self.cognitive_service = None
                    logger.warning(f"⚠️ CognitiveService handle not available: {e} (will use HTTP fallback {self._cog_base})")
                
                self._initialized = True
                logger.info("✅ StateService connected to organism manager")
                
            except Exception as e:
                logger.error(f"❌ Failed to initialize StateService: {e}")
                # Don't raise - service can still start and work in limited mode
                self._initialized = True
    
    async def reconfigure(self, config: dict = None):
        """Ray Serve reconfigure hook."""
        logger.info("⏳ StateService reconfigure called")
        try:
            if not self._initialized:
                logger.info("🔄 StateService starting lazy initialization...")
                await self._lazy_init()
            logger.info("🔁 StateService reconfigure completed successfully")
        except Exception as e:
            logger.error(f"❌ StateService reconfigure failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    # --- Health and Status Endpoints ---
    
    @app.get("/health", response_model=HealthResponse)
    async def health(self):
        """Health check endpoint."""
        try:
            # Trigger lazy initialization if not already done
            if not self._initialized:
                await self._lazy_init()
            
            organism_connected = False
            cognitive_connected = False
            if self.organism_manager:
                try:
                    # Try to get organism status to verify connection
                    await self.organism_manager.get_organism_status.remote()
                    organism_connected = True
                except Exception:
                    organism_connected = False

            # Probe cognitive availability (best-effort)
            cognitive_connected = await self._probe_cognitive()

            return HealthResponse(
                status="healthy" if self._initialized and (organism_connected or cognitive_connected) else "unhealthy",
                service="state-service",
                initialized=self._initialized,
                organism_connected=organism_connected,
                cognitive_connected=cognitive_connected
            )
        except Exception as e:
            return HealthResponse(
                status="unhealthy",
                service="state-service",
                initialized=self._initialized,
                organism_connected=False,
                cognitive_connected=False,
                error=str(e)
            )
    
    @app.get("/status")
    async def status(self):
        """Get detailed service status."""
        try:
            if not self._initialized:
                return {
                    "status": "uninitialized",
                    "error": "Service not initialized"
                }
            
            # Get organism status
            organism_status = await self.organism_manager.get_organism_status.remote()
            
            return {
                "status": "healthy",
                "service": "state-service",
                "organism_status": organism_status,
                "aggregators": {
                    "agent_aggregator": self.agent_aggregator is not None,
                    "memory_aggregator": self.memory_aggregator is not None,
                    "system_aggregator": self.system_aggregator is not None
                }
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    # --- Core State Collection Endpoints ---
    
    @app.post("/unified-state", response_model=StateResponse)
    async def get_unified_state(self, request: StateRequest):
        """
        Get unified state for specified agents or all agents.
        
        This is the main endpoint for state aggregation, implementing Paper §3.1
        requirements for light aggregators from live Ray actors and memory managers.
        """
        start_time = time.time()
        
        try:
            if not self._initialized:
                await self._lazy_init()
            
            if not self.organism_manager:
                raise HTTPException(
                    status_code=503,
                    detail="Organism manager not available"
                )
            
            # Get agent IDs if not specified
            agent_ids = request.agent_ids
            if agent_ids is None:
                agent_to_organ_map = await self.organism_manager.get_agent_to_organ_map.remote()
                agent_ids = list(agent_to_organ_map.keys())
            
            logger.info(f"Building unified state for {len(agent_ids)} agents")
            
            # Collect all state components in parallel for efficiency
            tasks = []
            
            if request.include_organs:
                tasks.append(self._get_organ_states())
            else:
                tasks.append(asyncio.create_task(asyncio.sleep(0, result={})))
            
            if request.include_system:
                tasks.append(self._get_system_state())
            else:
                tasks.append(asyncio.create_task(asyncio.sleep(0, result=SystemState())))
            
            if request.include_memory:
                tasks.append(self._get_memory_stats())
            else:
                tasks.append(asyncio.create_task(asyncio.sleep(0, result=MemoryVector(ma={}, mw={}, mlt={}, mfb={}))))
            
            # Always collect agent snapshots
            tasks.append(self._get_agent_snapshots(agent_ids))
            
            # Wait for all tasks to complete
            organ_states, system_state, memory_stats, agent_snapshots = await asyncio.gather(
                *tasks, return_exceptions=True
            )
            
            # Handle any exceptions
            if isinstance(agent_snapshots, Exception):
                logger.error(f"Failed to collect agent snapshots: {agent_snapshots}")
                agent_snapshots = {}
            
            if isinstance(organ_states, Exception):
                logger.error(f"Failed to collect organ states: {organ_states}")
                organ_states = {}
            
            if isinstance(system_state, Exception):
                logger.error(f"Failed to collect system state: {system_state}")
                system_state = SystemState()
            
            if isinstance(memory_stats, Exception):
                logger.error(f"Failed to collect memory stats: {memory_stats}")
                memory_stats = MemoryVector(ma={}, mw={}, mlt={}, mfb={})
            
            # Build unified state then use model's serializer to ensure coherence
            unified_state = UnifiedState(
                agents=agent_snapshots,
                organs=organ_states,
                system=system_state,
                memory=memory_stats
            )
            unified_state = unified_state.projected()
            unified_state_dict = unified_state.to_payload()
            
            collection_time = (time.time() - start_time) * 1000
            
            logger.info(f"✅ Unified state built: {len(agent_snapshots)} agents, {len(organ_states)} organs, {collection_time:.2f}ms")
            
            return StateResponse(
                success=True,
                unified_state=unified_state_dict,
                timestamp=time.time(),
                collection_time_ms=collection_time
            )
            
        except Exception as e:
            logger.error(f"Failed to build unified state: {e}")
            return StateResponse(
                success=False,
                error=str(e),
                timestamp=time.time(),
                collection_time_ms=(time.time() - start_time) * 1000
            )
    
    @app.get("/unified-state")
    async def get_unified_state_simple(
        self,
        agent_ids: Optional[List[str]] = Query(None, description="List of agent IDs to include"),
        include_organs: bool = Query(True, description="Include organ states"),
        include_system: bool = Query(True, description="Include system state"),
        include_memory: bool = Query(True, description="Include memory statistics")
    ):
        """Simplified GET endpoint for unified state."""
        request = StateRequest(
            agent_ids=agent_ids,
            include_organs=include_organs,
            include_system=include_system,
            include_memory=include_memory
        )
        return await self.get_unified_state(request)
    
    # --- Specialized State Collection Methods ---
    
    async def _probe_cognitive(self) -> bool:
        """Best-effort probe of CognitiveService (Serve handle → HTTP)."""
        # Try Serve handle call first (expects a 'status' or 'health' callable, if exposed)
        if self.cognitive_service is not None:
            try:
                if hasattr(self.cognitive_service, "health"):
                    resp = await self.cognitive_service.health.remote()
                    status = None
                    if isinstance(resp, dict):
                        status = resp.get("status")
                    elif hasattr(resp, "model_dump"):
                        status = resp.model_dump().get("status")
                    elif hasattr(resp, "dict"):
                        status = resp.dict().get("status")
                    else:
                        status = getattr(resp, "status", None)
                    if str(status).lower() == "healthy":
                        return True
            except Exception:
                pass
        # Fallback to HTTP
        try:
            with urllib.request.urlopen(f"{self._cog_base}/health", timeout=1.5) as r:
                data = json.loads(r.read().decode("utf-8"))
            return str(data.get("status", "")).lower() == "healthy"
        except Exception:
            return False

    async def _get_agent_snapshots(self, agent_ids: List[str]) -> Dict[str, AgentSnapshot]:
        """Collect agent state from Ray actors."""
        if not self.agent_aggregator:
            return {}
        return await self.agent_aggregator.collect_agent_snapshots(agent_ids)
    
    async def _get_organ_states(self) -> Dict[str, OrganState]:
        """Collect organ-level state information."""
        if not self.organism_manager:
            return {}
            
        organ_states = {}
        
        try:
            # Get organ handles from organism manager
            organ_handles = await self.organism_manager.get_organs.remote()
            
            for organ_id, organ_handle in organ_handles.items():
                try:
                    # Get organ status
                    status = await self._async_ray_get(organ_handle.get_status.remote())
                    
                    # Get agent handles for this organ
                    agent_handles = await self._async_ray_get(organ_handle.get_agent_handles.remote())
                    
                    if not agent_handles:
                        # Empty organ
                        organ_states[organ_id] = OrganState(
                            h=np.zeros(128, dtype=np.float32),
                            P=np.zeros((0, 3), dtype=np.float32)
                        )
                        continue
                    
                    # Collect agent states for this organ
                    agent_heartbeats = []
                    for agent_handle in agent_handles.values():
                        try:
                            hb = await self._async_ray_get(agent_handle.get_heartbeat.remote())
                            agent_heartbeats.append(hb)
                        except Exception as e:
                            logger.warning(f"Failed to get heartbeat from agent in organ {organ_id}: {e}")
                            continue
                    
                    if not agent_heartbeats:
                        organ_states[organ_id] = OrganState(
                            h=np.zeros(128, dtype=np.float32),
                            P=np.zeros((0, 3), dtype=np.float32)
                        )
                        continue
                    
                    # Compute organ-level state
                    h_vectors = []
                    p_vectors = []
                    
                    for hb in agent_heartbeats:
                        state_embedding = hb.get('state_embedding_h', hb.get('state_embedding', []))
                        if state_embedding:
                            h_vectors.append(np.array(state_embedding, dtype=np.float32))
                        
                        role_probs = hb.get('role_probs', {})
                        p_vector = [
                            float(role_probs.get('E', 0.0)),
                            float(role_probs.get('S', 0.0)),
                            float(role_probs.get('O', 0.0))
                        ]
                        p_vectors.append(p_vector)
                    
                    if h_vectors:
                        h_matrix = np.vstack(h_vectors)
                        h_organ = np.mean(h_matrix, axis=0)  # Average agent embedding
                    else:
                        h_organ = np.zeros(128, dtype=np.float32)
                    
                    if p_vectors:
                        P_matrix = np.array(p_vectors, dtype=np.float32)
                    else:
                        P_matrix = np.zeros((0, 3), dtype=np.float32)
                    
                    organ_states[organ_id] = OrganState(
                        h=h_organ,
                        P=P_matrix
                    )
                    
                except Exception as e:
                    logger.warning(f"Failed to collect state for organ {organ_id}: {e}")
                    continue
            
            logger.debug(f"Successfully collected {len(organ_states)} organ states")
            return organ_states
            
        except Exception as e:
            logger.error(f"Failed to collect organ states: {e}")
            return {}
    
    async def _get_system_state(self) -> SystemState:
        """Collect system-level state including E_patterns and h_hgnn.
        Uses aggregator first, then CognitiveService fallback, then defaults.
        """
        # 1) Try primary aggregator
        agg_state: Optional[SystemState] = None
        if self.system_aggregator:
            try:
                agg_state = await self.system_aggregator.collect_system_state()
            except Exception as e:
                logger.debug(f"system_aggregator failed, will try cognitive fallback: {e}")
                agg_state = None

        # 2) If E_patterns missing/empty, try CognitiveService probe (handle → HTTP)
        patterns: Optional[np.ndarray] = None
        if agg_state is None or getattr(agg_state, "E_patterns", None) is None \
           or (isinstance(getattr(agg_state, "E_patterns", None), np.ndarray) and getattr(agg_state, "E_patterns").size == 0):
            patterns = await self._fetch_cognitive_patterns()
        else:
            # Respect aggregator value
            try:
                ep = np.asarray(getattr(agg_state, "E_patterns"), dtype=np.float32)
                if ep.size == 0:
                    patterns = await self._fetch_cognitive_patterns()
                else:
                    patterns = ep
            except Exception:
                patterns = await self._fetch_cognitive_patterns()

        # 3) Always provide a non-empty vector as last resort
        if patterns is None or getattr(patterns, "size", 0) == 0:
            patterns = np.ones(4, dtype=np.float32)

        # Preserve h_hgnn/w_mode if available from aggregator
        h_hgnn = getattr(agg_state, "h_hgnn", None) if agg_state else None
        w_mode = getattr(agg_state, "w_mode", None) if agg_state else None
        return SystemState(h_hgnn=h_hgnn, E_patterns=patterns, w_mode=w_mode)

    async def _fetch_cognitive_patterns(self) -> Optional[np.ndarray]:
        """Try to retrieve E_patterns from CognitiveService with multiple strategies.
        Returns None if not available.
        """
        # A) Serve handle with methods that may return patterns/metrics
        if self.cognitive_service is not None:
            for method in ("get_patterns", "metrics", "status"):
                try:
                    if hasattr(self.cognitive_service, method):
                        resp = await getattr(self.cognitive_service, method).remote()
                        vec = self._extract_patterns_from_obj(resp)
                        if vec is not None and getattr(vec, "size", 0) > 0:
                            return vec
                except Exception:
                    pass
        # B) HTTP fallbacks: /patterns, /metrics, /status
        for path in ("/patterns", "/metrics", "/status"):
            try:
                with urllib.request.urlopen(f"{self._cog_base}{path}", timeout=1.5) as r:
                    data = json.loads(r.read().decode("utf-8"))
                vec = self._extract_patterns_from_obj(data)
                if vec is not None and getattr(vec, "size", 0) > 0:
                    return vec
            except Exception:
                continue
        return None

    def _extract_patterns_from_obj(self, obj: Any) -> Optional[np.ndarray]:
        """Heuristically pull a numeric vector out of common payloads."""
        try:
            if isinstance(obj, dict):
                for key in ("E_patterns", "patterns", "pattern_vec", "embedding"):
                    if key in obj:
                        arr = np.asarray(obj[key], dtype=np.float32)
                        return arr.reshape(-1) if arr.ndim > 1 else arr
        except Exception:
            pass
        return None
    
    async def _get_memory_stats(self) -> MemoryVector:
        """Collect memory manager statistics from all memory tiers."""
        if not self.memory_aggregator:
            return MemoryVector(ma={}, mw={}, mlt={}, mfb={})
        return await self.memory_aggregator.collect_memory_vector()
    
    async def _async_ray_get(self, refs) -> Any:
        """Safely resolve Ray references with proper error handling."""
        try:
            if isinstance(refs, list):
                return await asyncio.gather(*[self._async_ray_get(ref) for ref in refs])
            else:
                # Single reference
                if hasattr(refs, 'result'):
                    # DeploymentResponse
                    return await asyncio.get_event_loop().run_in_executor(
                        None, lambda: refs.result(timeout_s=15.0)
                    )
                else:
                    # ObjectRef
                    return await asyncio.get_event_loop().run_in_executor(
                        None, lambda: ray.get(refs, timeout=15.0)
                    )
        except Exception as e:
            logger.warning(f"Failed to resolve Ray reference: {e}")
            raise

# --- Main Entrypoint ---
state_app = StateService.bind()

def build_state_app(args: dict = None):
    """
    Builder function for the state service application.
    
    This function returns a bound Serve application that can be deployed
    via Ray Serve YAML configuration.
    """
    return StateService.bind()

def main():
    """Main entrypoint for standalone deployment."""
    logger.info("🚀 Starting State Service...")
    try:
        serve.run(
            state_app,
            name="state-service",
            route_prefix="/state"
        )
        logger.info("✅ State service is running.")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down gracefully...")
    finally:
        serve.shutdown()
        logger.info("✅ Serve shutdown complete.")

if __name__ == "__main__":
    main()
