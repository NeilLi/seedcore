#!/usr/bin/env python3
"""
Energy Service Client for SeedCore (Proactive v2)

This client provides a clean interface to the deployed proactive energy service.
It fetches pre-computed metrics and can trigger on-demand
computations or optimizations.
"""

import logging
from typing import Dict, Any, Optional
from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig
from pydantic import BaseModel  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)

# --- Pydantic models for POST bodies ---
# (These should match the models in energy_service.py)

class EnergyRequestBody(BaseModel):
    unified_state: Dict[str, Any]
    weights: Optional[Dict[str, Any]] = None
    include_gradients: bool = False

class OptimizationRequestBody(BaseModel):
    unified_state: Dict[str, Any]
    task: Dict[str, Any]
    weights: Optional[Dict[str, float]] = None
    max_agents: Optional[int] = None

class FlywheelResultRequestBody(BaseModel):
    delta_e: float
    breakdown: Optional[Dict[str, float]] = None
    cost: Optional[float] = 0.0
    scope: Optional[str] = "cluster"
    scope_id: Optional[str] = "-"
    p_fast: Optional[float] = 0.9
    drift: Optional[float] = 0.0
    beta_mem: Optional[float] = None

class GradientRequestBody(BaseModel):
    unified_state: Dict[str, Any]
    weights: Optional[Dict[str, Any]] = None

# ----------------------------------------

class EnergyServiceClient(BaseServiceClient):
    """
    Client for the proactive EnergyService.

    NOTE: This client does not manage control loops, policies, or
    individual agent energy states. That logic now belongs to the
    Coordinator, which uses this client to get its data.
    """
    
    def __init__(self, 
                 base_url: str = None, 
                 timeout: float = 8.0):
        
        # We set the base_url to the *gateway*, not the /ops path
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY
                base_url = SERVE_GATEWAY  # e.g., "http://127.0.0.1:8000"
            except Exception:
                base_url = "http://127.0.0.1:8000"
        
        circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
            expected_exception=(Exception,)
        )
        
        retry_config = RetryConfig(
            max_attempts=2,
            base_delay=1.0,
            max_delay=5.0
        )
        
        super().__init__(
            service_name="energy_service",
            base_url=base_url,
            timeout=timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config
        )
    
    # --- Primary Methods (Proactive) ---
    
    async def get_metrics(self) -> Dict[str, Any]:
        """
        Get the current, pre-computed energy breakdown.
        
        This is the main, fast-path endpoint that reads from the
        EnergyService's internal ledger cache.
        
        Returns:
            A dictionary of energy terms, e.g.:
            {
                "pair": ...,
                "hyper": ...,
                "entropy": ...,
                "reg": ...,
                "mem": ...,
                "drift_term": ...,
                "anomaly_term": ...,
                "scaling_score": ...,
                "total": ...
            }
        """
        # Path includes the /ops prefix from the gateway
        return await self.get("/ops/energy/metrics")
    
    async def get_meta(self) -> Dict[str, Any]:
        """
        Get energy metadata (e.g., Lipschitz constant L_tot).
        
        This endpoint provides metadata about the energy system state.
        
        Returns:
            A dictionary with metadata fields like L_tot, etc.
        """
        # Use the seedcore-api endpoint for energy meta
        # This might be proxied through the gateway or accessed directly
        return await self.get("/ops/energy/meta")
    
    async def health(self) -> Dict[str, Any]:
        """
        Check the health of the EnergyService.
        
        This polls the OpsGateway, which in turn polls the
        EnergyService's internal /health endpoint.
        """
        return await self.get("/ops/energy/health")

    async def is_healthy(self) -> bool:
        """Check if the energy service is healthy."""
        try:
            health_data = await self.health()
            return health_data.get("status") == "healthy"
        except Exception:
            return False

    # --- On-Demand / Passive Methods ---

    async def compute_energy_from_state(self) -> Dict[str, Any]:
        """
        (On-Demand) Triggers the EnergyService to
        fetch the *latest* state and compute energy *now*.
        
        This is slower than get_metrics() as it's not cached.
        
        Returns:
            An EnergyResponse dictionary.
        """
        return await self.get("/ops/energy/compute-from-state")

    async def compute_energy(
        self, 
        unified_state: Dict[str, Any], 
        weights: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        (Passive) Compute energy by providing the unified state.
        
        Args:
            unified_state: A full unified state dictionary.
            weights: Optional custom energy weights.
            
        Returns:
            An EnergyResponse dictionary.
        """
        request_data = EnergyRequestBody(
            unified_state=unified_state,
            weights=weights,
            include_gradients=False
        )
        return await self.post("/ops/energy/compute", json=request_data.model_dump())
        
    async def get_gradient(
        self, 
        unified_state: Dict[str, Any], 
        weights: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        (Passive) Compute energy and its gradients by providing the state.
        
        Args:
            unified_state: A full unified state dictionary.
            weights: Optional custom energy weights.
            
        Returns:
            An EnergyResponse dictionary with a 'gradients' field.
        """
        request_data = EnergyRequestBody(
            unified_state=unified_state,
            weights=weights,
            include_gradients=True
        )
        # Note: Assuming OpsGateway proxies a POST /energy/gradient
        # If not, this can be combined with compute_energy
        return await self.post("/ops/energy/compute", json=request_data.model_dump())

    async def optimize_agents(
        self, 
        unified_state: Dict[str, Any], 
        task: Dict[str, Any],
        max_agents: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        (Passive) Get agent recommendations for a task,
        given the current system state.
        
        Args:
            unified_state: A full unified state dictionary.
            task: A dictionary describing the task.
            max_agents: Optional limit on agents to return.
            
        Returns:
            An OptimizationResponse dictionary.
        """
        request_data = OptimizationRequestBody(
            unified_state=unified_state,
            task=task,
            max_agents=max_agents
        )
        return await self.post("/ops/energy/optimize", json=request_data.model_dump())

    # --- Flywheel Method ---
    
    async def post_flywheel_result(
        self, 
        delta_e: float, 
        cost: float,
        breakdown: Optional[Dict[str, float]] = None,
        scope: Optional[str] = "cluster",
        scope_id: Optional[str] = "-",
        p_fast: Optional[float] = 0.9,
        drift: Optional[float] = 0.0,
        beta_mem: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Posts the result of an action (ΔE) back to the
        EnergyService to update its ledger and adapt weights.
        
        Args:
            delta_e: The change in energy from the action.
            cost: The computed cost (e.g., tokens, time) of the action.
            breakdown: Optional per-term energy breakdown.
            scope: Optional scope identifier (default: "cluster").
            scope_id: Optional scope ID (default: "-").
            p_fast: Optional fast probability (default: 0.9).
            drift: Optional drift value (default: 0.0).
            beta_mem: Optional memory beta parameter.
            
        Returns:
            A FlywheelResultResponse dictionary.
        """
        request_data = FlywheelResultRequestBody(
            delta_e=delta_e,
            cost=cost,
            breakdown=breakdown,
            scope=scope,
            scope_id=scope_id,
            p_fast=p_fast,
            drift=drift,
            beta_mem=beta_mem
        )
        # Assumes /ops/flywheel/result is proxied by OpsGateway
        return await self.post("/ops/flywheel/result", json=request_data.model_dump())