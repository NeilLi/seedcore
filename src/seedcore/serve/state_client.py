#!/usr/bin/env python3
"""
State Service Client for SeedCore (Proactive v2)

This client provides a clean, read-only interface to the OpsGateway → StateService
pipeline. It interacts exclusively with the refined, production-grade endpoints:
    /ops/state/system-metrics
    /ops/state/agent-snapshots
    /ops/state/config/w_mode
    /ops/state/health

The StateService itself aggregates raw agent snapshots (crude oil)
into distilled system metrics (jet fuel) that are suitable for real-time
agent routing and energy computation.
"""

import logging
from typing import Dict, Any

from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig
from .ops_rpc import call_ops_rpc, get_ops_gateway_handle

logger = logging.getLogger(__name__)


class StateServiceClient(BaseServiceClient):
    """
    Client for the proactive StateService via OpsGateway.

    NOTE:
    -----
    - This client never reads/writes individual agent state.
    - It ONLY consumes the distilled system metrics and exposes cold-path
      agent snapshots for debugging and offline analysis (optional).
    """

    def __init__(self, base_url: str = None, timeout: float = 8.0):
        # All traffic must go to OpsGateway, not directly to underlying services.
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY
                base_url = SERVE_GATEWAY  # e.g. "http://127.0.0.1:8000"
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
            service_name="StateService",
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
    # HOT PATH (Production)
    # ----------------------------------------------------------------------


    async def get_system_metrics(self) -> Dict[str, Any]:
        """
        Fetch refined, pre-computed system metrics (HOT PATH).
        
        Note: We do NOT pass 'response' here. The client just fetches data.
        The server endpoint sets the headers, and httpx handles receiving them.
        """
        try:
            return await self._call_ops_rpc("rpc_state_system_metrics")
        except Exception as exc:
            logger.debug("StateServiceClient RPC get_system_metrics fallback: %s", exc)
            return await self.get("/ops/state/system-metrics")

    async def get_unified_state(self) -> Dict[str, Any]:
        """Fetch the full unified state snapshot for planner/debug workloads."""
        try:
            return await self._call_ops_rpc("rpc_state_unified_state")
        except Exception as exc:
            logger.debug("StateServiceClient RPC get_unified_state fallback: %s", exc)
            return await self.get("/ops/state/unified-state")

    # ----------------------------------------------------------------------
    # COLD PATH (Debugging / Offline Analysis)
    # ----------------------------------------------------------------------

    async def get_all_agent_snapshots(self) -> Dict[str, Any]:
        """
        Fetch raw agent snapshots (COLD PATH).

        Heavy, multi-megabyte data. Only use for debugging or offline analysis.

        Returns:
            Raw snapshot dictionary.
        """
        try:
            return await self._call_ops_rpc("rpc_state_agent_snapshots")
        except Exception as exc:
            logger.debug(
                "StateServiceClient RPC get_all_agent_snapshots fallback: %s", exc
            )
            return await self.get("/ops/state/agent-snapshots")

    # ----------------------------------------------------------------------
    # CONFIGURATION / CONTROL
    # ----------------------------------------------------------------------

    async def update_w_mode(self, new_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update the global system weight configuration (w_mode).

        Args:
            new_config: { "w_mode": "...", ... }

        Returns:
            A dictionary indicating success or updated mode.
        """
        try:
            return await self._call_ops_rpc("rpc_state_update_w_mode", new_config)
        except Exception as exc:
            logger.debug("StateServiceClient RPC update_w_mode fallback: %s", exc)
            return await self.post("/ops/state/config/w_mode", json=new_config)

    async def get_status(self) -> Dict[str, Any]:
        """Get readiness/details for the state runtime."""
        try:
            return await self._call_ops_rpc("rpc_state_status")
        except Exception as exc:
            logger.debug("StateServiceClient RPC get_status fallback: %s", exc)
            return await self.get("/ops/state/status")

    # ----------------------------------------------------------------------
    # HEALTH
    # ----------------------------------------------------------------------

    async def health(self) -> Dict[str, Any]:
        """
        Health check for StateService via OpsGateway.
        """
        try:
            return await self._call_ops_rpc("rpc_state_health")
        except Exception as exc:
            logger.debug("StateServiceClient RPC health fallback: %s", exc)
            return await self.get("/ops/state/health")

    async def is_healthy(self) -> bool:
        """Convenience method: return True if service reports healthy."""
        try:
            return (await self.health()).get("status") == "healthy"
        except Exception:
            return False
