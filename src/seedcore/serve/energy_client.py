#!/usr/bin/env python3
"""
Energy Service Client for SeedCore (Proactive v2)

This client provides a clean interface to the OpsGateway → EnergyService
pipeline. It calls the unified /ops/energy/* endpoints exposed by the OpsGateway,
which forwards requests internally via RPC to the EnergyService deployment.
"""

import logging
from typing import Dict, Any, Optional

from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig

from seedcore.models.energy import (
    EnergyRequest,
    OptimizationRequest,
    FlywheelResultRequest,
)

logger = logging.getLogger(__name__)


class EnergyServiceClient(BaseServiceClient):
    """
    Client for the proactive EnergyService as routed through OpsGateway.

    All public-facing endpoints go through:
        http://<gateway>/ops/energy/<endpoint>

    The OpsGateway internally forwards to EnergyService RPC methods.
    """

    def __init__(self, base_url: str = None, timeout: float = 8.0):
        # Default to Ray Serve gateway
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY
                base_url = SERVE_GATEWAY  # e.g., "http://127.0.0.1:8000"
            except Exception:
                base_url = "http://127.0.0.1:8000"

        circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
            expected_exception=(Exception,),
        )

        retry_config = RetryConfig(
            max_attempts=2,
            base_delay=1.0,
            max_delay=5.0,
        )

        super().__init__(
            service_name="energy_service",
            base_url=base_url,
            timeout=timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config,
        )

    # ----------------------------------------------------------------------
    # FAST-PATH METRICS / HEALTH
    # ----------------------------------------------------------------------

    async def get_metrics(self) -> Dict[str, Any]:
        """Fetch the latest cached energy metrics (fast path)."""
        return await self.get("/ops/energy/metrics")

    async def health(self) -> Dict[str, Any]:
        """Ping EnergyService health via OpsGateway."""
        return await self.get("/ops/energy/health")

    async def is_healthy(self) -> bool:
        try:
            return (await self.health()).get("status") == "healthy"
        except Exception:
            return False

    # ----------------------------------------------------------------------
    # ENERGY COMPUTATION AND GRADIENTS
    # ----------------------------------------------------------------------

    async def compute_energy_from_state(self) -> Dict[str, Any]:
        """
        (On-Demand)
        Trigger EnergyService to fetch the latest StateService metrics
        and compute energy immediately.
        """
        return await self.get("/ops/energy/compute-from-state")

    async def compute_energy(
        self,
        unified_state: Dict[str, Any],
        weights: Optional[Dict[str, Any]] = None,
        include_gradients: bool = False,
    ) -> Dict[str, Any]:
        """Passive energy computation."""
        body = EnergyRequest(
            unified_state=unified_state,
            weights=weights,
            include_gradients=include_gradients,
        )
        return await self.post("/ops/energy/compute", json=body.model_dump())

    async def get_gradient(
        self,
        unified_state: Dict[str, Any],
        weights: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Compute energy with gradients."""
        return await self.compute_energy(
            unified_state,
            weights=weights,
            include_gradients=True,
        )

    # ----------------------------------------------------------------------
    # OPTIMIZATION (Agent Selection)
    # ----------------------------------------------------------------------

    async def optimize_agents(
        self,
        unified_state: Dict[str, Any],
        task: Dict[str, Any],
        max_agents: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Optimize agent selection for a task."""
        body = OptimizationRequest(
            unified_state=unified_state,
            task=task,
            max_agents=max_agents,
        )
        return await self.post("/ops/energy/optimize", json=body.model_dump())

    # ----------------------------------------------------------------------
    # FLYWHEEL — Feedback Loop
    # ----------------------------------------------------------------------

    async def post_flywheel_result(
        self,
        delta_e: float,
        cost: float,
        breakdown: Optional[Dict[str, float]] = None,
        scope: Optional[str] = "cluster",
        scope_id: Optional[str] = "-",
        p_fast: Optional[float] = 0.9,
        drift: Optional[float] = 0.0,
        beta_mem: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Submit feedback (ΔE, cost, weight change) to the EnergyService flywheel.
        """
        body = FlywheelResultRequest(
            delta_e=delta_e,
            cost=cost,
            breakdown=breakdown,
            scope=scope,
            scope_id=scope_id,
            p_fast=p_fast,
            drift=drift,
            beta_mem=beta_mem,
        )
        return await self.post("/ops/flywheel/result", json=body.model_dump())
