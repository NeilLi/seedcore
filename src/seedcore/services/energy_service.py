#!/usr/bin/env python3
"""
Energy Service - Standalone Ray Serve Application

This service provides energy calculations and optimization for the SeedCore system.
It consumes UnifiedState data from the state service and computes various energy
metrics, gradients, and optimization recommendations.

Key Features:
- Pure computational service (no state collection)
- Multiple energy calculation methods
- Gradient computation for control loops
- Energy optimization and agent selection
- RESTful API for energy queries
- Integration with energy ledger and persistence

This service implements the energy model described in the COA paper.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Tuple
import numpy as np
import ray
from ray import serve
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from ..energy.state import UnifiedState, AgentSnapshot, OrganState, SystemState, MemoryVector
from ..energy.calculator import (
    compute_energy,
    energy_and_grad,
    entropy_of_roles,
    cost_vq,
    role_entropy_grad
)
from ..energy.weights import EnergyWeights
from ..energy.ledger import EnergyLedger, EnergyTerms
from ..energy.optimizer import (
    calculate_agent_suitability_score,
    select_best_agent,
    rank_agents_by_suitability,
    get_ideal_role_for_task,
    estimate_task_complexity
)

logger = logging.getLogger(__name__)

# --- Request/Response Models ---
class EnergyRequest(BaseModel):
    unified_state: Dict[str, Any]
    weights: Optional[Dict[str, float]] = None
    include_gradients: bool = False
    include_breakdown: bool = True

class EnergyResponse(BaseModel):
    success: bool
    energy: Optional[Dict[str, float]] = None
    gradients: Optional[Dict[str, Any]] = None
    breakdown: Optional[Dict[str, float]] = None
    error: Optional[str] = None
    timestamp: float
    computation_time_ms: float

class OptimizationRequest(BaseModel):
    unified_state: Dict[str, Any]
    task: Dict[str, Any]
    weights: Optional[Dict[str, float]] = None
    max_agents: Optional[int] = None

class OptimizationResponse(BaseModel):
    success: bool
    selected_agents: Optional[List[str]] = None
    suitability_scores: Optional[Dict[str, float]] = None
    recommended_roles: Optional[Dict[str, str]] = None
    task_complexity: Optional[float] = None
    error: Optional[str] = None
    timestamp: float
    computation_time_ms: float

class HealthResponse(BaseModel):
    status: str
    service: str
    initialized: bool
    state_service_connected: bool
    error: Optional[str] = None

# --- FastAPI App ---
app = FastAPI(title="SeedCore Energy Service", version="1.0.0")

@serve.deployment(
    name="EnergyService",
    num_replicas=1,
    max_ongoing_requests=16,
    ray_actor_options={
        "num_cpus": 0.2,
        "num_gpus": 0,
        "memory": 1073741824,  # 1GB
        "resources": {"head_node": 0.001},
    },
)
class EnergyService:
    """
    Standalone energy calculation service.
    
    This service consumes UnifiedState data and computes energy metrics,
    gradients, and optimization recommendations. It is purely computational
    and does not collect state itself.
    """
    
    def __init__(self):
        self.state_service = None
        self._initialized = False
        self._init_lock = asyncio.Lock()
        
        # Default energy weights - will be updated based on actual state dimensions
        self.default_weights = EnergyWeights(
            W_pair=np.array([[1.0]]),  # Default 1x1 matrix
            W_hyper=np.array([1.0]),  # Default hyperedge weights
            alpha_entropy=0.1,  # Default entropy weight
            lambda_reg=0.01,  # Default regularization weight
            beta_mem=0.05  # Default memory weight
        )
        
        # ASGI app integration
        self._app = app
        
        logger.info("✅ EnergyService initialized - will connect to state service on first request")
    
    async def __call__(self, request):
        """Handle HTTP requests through FastAPI."""
        return await self._app(request.scope, request.receive, request.send)
    
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
        """Initialize the service by connecting to the state service."""
        if self._initialized:
            return
            
        async with self._init_lock:
            if self._initialized:
                return
                
            try:
                # Get the state service from Ray - try multiple namespaces
                state_handle = None
                for namespace in ["seedcore-dev", "serve", "default"]:
                    try:
                        state_handle = ray.get_actor("StateService", namespace=namespace)
                        logger.info(f"✅ EnergyService connected to state service in namespace: {namespace}")
                        break
                    except Exception as e:
                        logger.debug(f"Failed to connect to state service in namespace {namespace}: {e}")
                        continue
                
                if state_handle is None:
                    logger.warning("⚠️ State service not available - EnergyService will work with direct state input only")
                else:
                    self.state_service = state_handle
                
                self._initialized = True
                logger.info("✅ EnergyService initialized")
                
            except Exception as e:
                logger.error(f"❌ Failed to initialize EnergyService: {e}")
                # Don't raise - service can still work with direct state input
                self._initialized = True
    
    async def reconfigure(self, config: dict = None):
        """Ray Serve reconfigure hook."""
        logger.info("⏳ EnergyService reconfigure called")
        try:
            if not self._initialized:
                logger.info("🔄 EnergyService starting lazy initialization...")
                await self._lazy_init()
            logger.info("🔁 EnergyService reconfigure completed successfully")
        except Exception as e:
            logger.error(f"❌ EnergyService reconfigure failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    # --- Health and Status Endpoints ---
    
    @app.get("/health", response_model=HealthResponse)
    async def health(self):
        """Health check endpoint."""
        try:
            state_service_connected = False
            if self.state_service:
                try:
                    # Try to get state service health
                    health_response = await self.state_service.health.remote()
                    state_service_connected = health_response.get("status") == "healthy"
                except Exception:
                    state_service_connected = False
            
            return HealthResponse(
                status="healthy" if self._initialized and state_service_connected else "unhealthy",
                service="energy-service",
                initialized=self._initialized,
                state_service_connected=state_service_connected
            )
        except Exception as e:
            return HealthResponse(
                status="unhealthy",
                service="energy-service",
                initialized=self._initialized,
                state_service_connected=False,
                error=str(e)
            )
    
    @app.get("/status")
    async def status(self):
        """Get detailed service status."""
        try:
            return {
                "status": "healthy",
                "service": "energy-service",
                "initialized": self._initialized,
                "state_service_connected": self.state_service is not None,
                "default_weights": {
                    "alpha_entropy": self.default_weights.alpha_entropy,
                    "lambda_reg": self.default_weights.lambda_reg,
                    "beta_mem": self.default_weights.beta_mem
                }
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    # --- Core Energy Calculation Endpoints ---
    
    @app.post("/compute-energy", response_model=EnergyResponse)
    async def compute_energy_endpoint(self, request: EnergyRequest):
        """
        Compute energy metrics from unified state.
        
        This is the main endpoint for energy calculations, supporting
        various energy terms and gradient computation.
        """
        start_time = time.time()
        
        try:
            # Parse unified state
            unified_state = self._parse_unified_state(request.unified_state)
            
            # Extract matrices for energy calculation
            H = unified_state.H_matrix()
            P = unified_state.P_matrix()
            
            # Extract E_patterns and s_norm if available
            E_sel = None
            if unified_state.system.E_patterns is not None:
                E_sel = unified_state.system.E_patterns
            
            s_norm = 0.0
            if H.size > 0:
                s_norm = float(np.linalg.norm(H))
            
            # Create weights with appropriate dimensions
            if request.weights:
                weights = self._parse_weights(request.weights)
                # Ensure weights have correct dimensions
                if weights.W_pair.shape[0] != H.shape[0]:
                    weights = self._create_weights_for_state(H, E_sel)
            else:
                weights = self._create_weights_for_state(H, E_sel)
            
            # Get memory statistics
            memory_stats = {
                "r_effective": 1.0,  # Default values
                "p_compress": 0.0
            }
            
            # Compute energy
            if request.include_gradients:
                breakdown, gradients = energy_and_grad(
                    {
                        "h_agents": H,
                        "P_roles": P,
                        "hyper_sel": E_sel,
                        "s_norm": s_norm
                    },
                    weights,
                    memory_stats
                )
                
                # Convert gradients to serializable format
                gradients_serializable = {}
                for key, value in gradients.items():
                    if isinstance(value, np.ndarray):
                        gradients_serializable[key] = value.tolist()
                    else:
                        gradients_serializable[key] = value
            else:
                total_energy, breakdown = compute_energy(
                    H, P, weights, memory_stats, E_sel, s_norm
                )
                breakdown["total"] = total_energy
                gradients_serializable = None
            
            computation_time = (time.time() - start_time) * 1000
            
            logger.info(f"✅ Energy computed: total={breakdown.get('total', 0):.4f}, {computation_time:.2f}ms")
            
            return EnergyResponse(
                success=True,
                energy=breakdown if request.include_breakdown else {"total": breakdown.get("total", 0)},
                gradients=gradients_serializable,
                breakdown=breakdown if request.include_breakdown else None,
                timestamp=time.time(),
                computation_time_ms=computation_time
            )
            
        except Exception as e:
            logger.error(f"Failed to compute energy: {e}")
            return EnergyResponse(
                success=False,
                error=str(e),
                timestamp=time.time(),
                computation_time_ms=(time.time() - start_time) * 1000
            )
    
    @app.post("/optimize-agents", response_model=OptimizationResponse)
    async def optimize_agents_endpoint(self, request: OptimizationRequest):
        """
        Optimize agent selection for a given task.
        
        This endpoint provides agent selection and role recommendations
        based on energy optimization principles.
        """
        start_time = time.time()
        
        try:
            # Parse unified state
            unified_state = self._parse_unified_state(request.unified_state)
            
            # Create weights with appropriate dimensions (will be updated based on state)
            weights = self._create_weights_for_state(np.array([[0.0]]), None)  # Placeholder, will be updated
            
            # Estimate task complexity
            task_complexity = estimate_task_complexity(request.task)
            
            # Get agent snapshots
            agents = unified_state.agents
            
            if not agents:
                return OptimizationResponse(
                    success=False,
                    error="No agents available for optimization",
                    timestamp=time.time(),
                    computation_time_ms=(time.time() - start_time) * 1000
                )
            
            # Calculate suitability scores for all agents
            suitability_scores = {}
            for agent_id, agent_snapshot in agents.items():
                # Convert agent snapshot to format expected by optimizer
                agent_data = {
                    "h": agent_snapshot.h,
                    "p": agent_snapshot.p,
                    "c": agent_snapshot.c,
                    "mem_util": agent_snapshot.mem_util,
                    "lifecycle": agent_snapshot.lifecycle
                }
                
                score = calculate_agent_suitability_score(agent_data, request.task)
                suitability_scores[agent_id] = score
            
            # Rank agents by suitability
            ranked_agents = rank_agents_by_suitability(suitability_scores)
            
            # Select best agents (limit by max_agents if specified)
            max_agents = request.max_agents or len(ranked_agents)
            selected_agents = ranked_agents[:max_agents]
            
            # Get recommended roles for selected agents
            recommended_roles = {}
            for agent_id in selected_agents:
                agent_snapshot = agents[agent_id]
                agent_data = {
                    "h": agent_snapshot.h,
                    "p": agent_snapshot.p,
                    "c": agent_snapshot.c,
                    "mem_util": agent_snapshot.mem_util,
                    "lifecycle": agent_snapshot.lifecycle
                }
                
                role = get_ideal_role_for_task(agent_data, request.task)
                recommended_roles[agent_id] = role
            
            computation_time = (time.time() - start_time) * 1000
            
            logger.info(f"✅ Agent optimization completed: {len(selected_agents)} agents selected, {computation_time:.2f}ms")
            
            return OptimizationResponse(
                success=True,
                selected_agents=selected_agents,
                suitability_scores=suitability_scores,
                recommended_roles=recommended_roles,
                task_complexity=task_complexity,
                timestamp=time.time(),
                computation_time_ms=computation_time
            )
            
        except Exception as e:
            logger.error(f"Failed to optimize agents: {e}")
            return OptimizationResponse(
                success=False,
                error=str(e),
                timestamp=time.time(),
                computation_time_ms=(time.time() - start_time) * 1000
            )
    
    # --- Convenience Endpoints ---
    
    @app.get("/energy-from-state")
    async def get_energy_from_state(
        self,
        agent_ids: Optional[List[str]] = Query(None, description="List of agent IDs to include"),
        include_gradients: bool = Query(False, description="Include gradient calculations"),
        include_breakdown: bool = Query(True, description="Include energy term breakdown")
    ):
        """Get energy metrics from current state service data."""
        try:
            if not self.state_service:
                raise HTTPException(
                    status_code=503,
                    detail="State service not available"
                )
            
            # Get unified state from state service
            state_response = await self.state_service.get_unified_state.remote(
                agent_ids=agent_ids,
                include_organs=True,
                include_system=True,
                include_memory=True
            )
            
            if not state_response.get("success"):
                raise HTTPException(
                    status_code=503,
                    detail=f"Failed to get state: {state_response.get('error')}"
                )
            
            # Create energy request
            energy_request = EnergyRequest(
                unified_state=state_response["unified_state"],
                weights=None,  # Will use dynamic weights
                include_gradients=include_gradients,
                include_breakdown=include_breakdown
            )
            
            return await self.compute_energy_endpoint(energy_request)
            
        except Exception as e:
            logger.error(f"Failed to get energy from state: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    # --- Helper Methods ---
    
    def _parse_unified_state(self, state_dict: Dict[str, Any]) -> UnifiedState:
        """Parse unified state dictionary into UnifiedState object."""
        try:
            # Parse agents
            agents = {}
            for agent_id, agent_data in state_dict.get("agents", {}).items():
                agents[agent_id] = AgentSnapshot(
                    h=np.array(agent_data["h"], dtype=np.float32),
                    p=agent_data["p"],
                    c=agent_data["c"],
                    mem_util=agent_data["mem_util"],
                    lifecycle=agent_data["lifecycle"]
                )
            
            # Parse organs
            organs = {}
            for organ_id, organ_data in state_dict.get("organs", {}).items():
                organs[organ_id] = OrganState(
                    h=np.array(organ_data["h"], dtype=np.float32),
                    P=np.array(organ_data["P"], dtype=np.float32),
                    v_pso=np.array(organ_data["v_pso"], dtype=np.float32) if organ_data.get("v_pso") else None
                )
            
            # Parse system
            system_data = state_dict.get("system", {})
            system = SystemState(
                h_hgnn=np.array(system_data["h_hgnn"], dtype=np.float32) if system_data.get("h_hgnn") else None,
                E_patterns=np.array(system_data["E_patterns"], dtype=np.float32) if system_data.get("E_patterns") else None,
                w_mode=np.array(system_data["w_mode"], dtype=np.float32) if system_data.get("w_mode") else None
            )
            
            # Parse memory
            memory_data = state_dict.get("memory", {})
            memory = MemoryVector(
                ma=memory_data.get("ma", {}),
                mw=memory_data.get("mw", {}),
                mlt=memory_data.get("mlt", {}),
                mfb=memory_data.get("mfb", {})
            )
            
            return UnifiedState(
                agents=agents,
                organs=organs,
                system=system,
                memory=memory
            )
            
        except Exception as e:
            logger.error(f"Failed to parse unified state: {e}")
            raise ValueError(f"Invalid unified state format: {e}")
    
    def _parse_weights(self, weights_dict: Optional[Dict[str, Any]]) -> EnergyWeights:
        """Parse weights dictionary into EnergyWeights object."""
        if not weights_dict:
            return self.default_weights
        
        # Create a copy of default weights and update with provided values
        weights = EnergyWeights(
            W_pair=self.default_weights.W_pair.copy(),
            W_hyper=self.default_weights.W_hyper.copy(),
            alpha_entropy=self.default_weights.alpha_entropy,
            lambda_reg=self.default_weights.lambda_reg,
            beta_mem=self.default_weights.beta_mem
        )
        
        # Update with provided values
        if "alpha_entropy" in weights_dict:
            weights.alpha_entropy = float(weights_dict["alpha_entropy"])
        if "lambda_reg" in weights_dict:
            weights.lambda_reg = float(weights_dict["lambda_reg"])
        if "beta_mem" in weights_dict:
            weights.beta_mem = float(weights_dict["beta_mem"])
        if "W_pair" in weights_dict:
            weights.W_pair = np.array(weights_dict["W_pair"])
        if "W_hyper" in weights_dict:
            weights.W_hyper = np.array(weights_dict["W_hyper"])
        
        return weights
    
    def _create_weights_for_state(self, H: np.ndarray, E_sel: Optional[np.ndarray] = None) -> EnergyWeights:
        """Create weights with appropriate dimensions for the given state."""
        n_agents = H.shape[0] if H.size > 0 else 1
        n_hyper = E_sel.shape[0] if E_sel is not None and E_sel.size > 0 else 1
        
        return EnergyWeights(
            W_pair=np.eye(n_agents) * 0.1,  # Identity matrix scaled down
            W_hyper=np.ones(n_hyper) * 0.1,  # Uniform hyperedge weights
            alpha_entropy=self.default_weights.alpha_entropy,
            lambda_reg=self.default_weights.lambda_reg,
            beta_mem=self.default_weights.beta_mem
        )

# --- Main Entrypoint ---
energy_app = EnergyService.bind()

def build_energy_app(args: dict = None):
    """
    Builder function for the energy service application.
    
    This function returns a bound Serve application that can be deployed
    via Ray Serve YAML configuration.
    """
    return EnergyService.bind()

def main():
    """Main entrypoint for standalone deployment."""
    logger.info("🚀 Starting Energy Service...")
    try:
        serve.run(
            energy_app,
            name="energy-service",
            route_prefix="/energy"
        )
        logger.info("✅ Energy service is running.")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down gracefully...")
    finally:
        serve.shutdown()
        logger.info("✅ Serve shutdown complete.")

if __name__ == "__main__":
    main()