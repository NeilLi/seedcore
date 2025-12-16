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

    # ----------------------------------------------------------------------
    # HOT PATH (Production)
    # ----------------------------------------------------------------------


    async def get_system_metrics(self) -> Dict[str, Any]:
        """
        Fetch refined, pre-computed system metrics (HOT PATH).
        
        Note: We do NOT pass 'response' here. The client just fetches data.
        The server endpoint sets the headers, and httpx handles receiving them.
        """
        # The underlying self.get should handle the HTTP call
        return await self.get("/ops/state/system-metrics")

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
        return await self.post("/ops/state/config/w_mode", json=new_config)

    # ----------------------------------------------------------------------
    # HEALTH
    # ----------------------------------------------------------------------

    async def health(self) -> Dict[str, Any]:
        """
        Health check for StateService via OpsGateway.
        """
        return await self.get("/ops/state/health")

    async def is_healthy(self) -> bool:
        """Convenience method: return True if service reports healthy."""
        try:
            return (await self.health()).get("status") == "healthy"
        except Exception:
            return False
