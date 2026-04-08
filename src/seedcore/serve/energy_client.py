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
from .ops_rpc import call_ops_rpc, get_ops_gateway_handle

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
            service_name="EnergyService",
            base_url=base_url,
            timeout=timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config,
        )
        self._ops_handle = None

    async def _call_ops_rpc(self, method_name: str, *args: Any) -> Dict[str, Any]:
        if self._ops_handle is None:
            self._ops_handle = get_ops_gateway_handle()
        if self._ops_handle is None:
            raise RuntimeError("ops_gateway_rpc_unavailable")
        return await call_ops_rpc(
            self._ops_handle,
            method_name,
            *args,
            timeout_s=self.timeout,
        )

    # ----------------------------------------------------------------------
    # FAST-PATH METRICS / HEALTH
    # ----------------------------------------------------------------------

    async def get_metrics(self) -> Dict[str, Any]:
        """Fetch the latest cached energy metrics (fast path)."""
        try:
            return await self._call_ops_rpc("rpc_energy_metrics")
        except Exception as exc:
            logger.debug("EnergyServiceClient RPC get_metrics fallback: %s", exc)
            return await self.get("/ops/energy/metrics")

    async def get_current_energy(self) -> Dict[str, Any]:
        """Backward-compatible alias used by older cognitive helpers."""
        return await self.get_metrics()

    async def health(self) -> Dict[str, Any]:
        """Ping EnergyService health via OpsGateway."""
        try:
            return await self._call_ops_rpc("rpc_energy_health")
        except Exception as exc:
            logger.debug("EnergyServiceClient RPC health fallback: %s", exc)
            return await self.get("/ops/energy/health")

    async def get_status(self) -> Dict[str, Any]:
        """Fetch runtime readiness and mode details."""
        try:
            return await self._call_ops_rpc("rpc_energy_status")
        except Exception as exc:
            logger.debug("EnergyServiceClient RPC get_status fallback: %s", exc)
            return await self.get("/ops/energy/status")

    async def get_meta(self) -> Dict[str, Any]:
        """Fetch promotion/contractivity metadata."""
        try:
            return await self._call_ops_rpc("rpc_energy_meta")
        except Exception as exc:
            logger.debug("EnergyServiceClient RPC get_meta fallback: %s", exc)
            return await self.get("/ops/energy/meta")

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
        try:
            return await self._call_ops_rpc("rpc_energy_compute_from_state")
        except Exception as exc:
            logger.debug(
                "EnergyServiceClient RPC compute_energy_from_state fallback: %s", exc
            )
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
        payload = body.model_dump()
        try:
            return await self._call_ops_rpc("rpc_energy_compute", payload)
        except Exception as exc:
            logger.debug("EnergyServiceClient RPC compute_energy fallback: %s", exc)
            return await self.post("/ops/energy/compute", json=payload)

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
        payload = body.model_dump()
        try:
            return await self._call_ops_rpc("rpc_energy_optimize", payload)
        except Exception as exc:
            logger.debug("EnergyServiceClient RPC optimize_agents fallback: %s", exc)
            return await self.post("/ops/energy/optimize", json=payload)

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
        payload = body.model_dump()
        try:
            return await self._call_ops_rpc("rpc_energy_flywheel_result", payload)
        except Exception as exc:
            logger.debug(
                "EnergyServiceClient RPC post_flywheel_result fallback: %s", exc
            )
            return await self.post("/ops/flywheel/result", json=payload)

    async def log_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Log an operational energy event."""
        try:
            return await self._call_ops_rpc("rpc_energy_log", payload)
        except Exception as exc:
            logger.debug("EnergyServiceClient RPC log_event fallback: %s", exc)
            return await self.post("/ops/energy/log", json=payload)

    async def get_logs(self, limit: int = 100) -> Dict[str, Any]:
        """Fetch recent operational energy events."""
        try:
            return await self._call_ops_rpc("rpc_energy_logs", int(limit))
        except Exception as exc:
            logger.debug("EnergyServiceClient RPC get_logs fallback: %s", exc)
            return await self.get("/ops/energy/logs", params={"limit": limit})
