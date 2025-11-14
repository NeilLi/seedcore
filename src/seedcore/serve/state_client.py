#!/usr/bin/env python3
"""
State Service Client for SeedCore (Proactive v2)

This client provides a clean, read-only interface to the deployed
proactive StateService.

Its primary function is to fetch the pre-computed system metrics
that the Coordinator and other services need for decision-making.
"""

import logging
from typing import Dict, Any
from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig

logger = logging.getLogger(__name__)


class StateServiceClient(BaseServiceClient):
    """
    Client for the proactive StateService.

    NOTE: This client *does not* manage individual agent state,
    store memory, or handle persistence. That logic is now
    part of the OrganismCore (agents) and their Tools. This
    client is for read-only observation.

    ARCHITECTURE: Distillation Engine
    --------------------------------
    The StateService's AgentAggregator acts as a "distillation engine":

    - Raw Crude Oil: The `_agent_snapshots` cache contains raw, multi-megabyte
      data for every agent (embeddings, role probabilities, skills, etc.)

    - Refined Jet Fuel: The `_system_metrics` cache contains small, pre-computed
      aggregates (system_specialization_vector, avg_capability, h_hgnn, etc.)

    The distillation happens in `AgentAggregator._compute_system_metrics()`,
    which consumes the massive `_agent_snapshots` dictionary and refines it
    into the small, valuable `_system_metrics` dictionary that the Coordinator
    and Energy Service actually need for real-time decision-making.

    The real consumer of `_agent_snapshots` is the aggregator itself, not
    external services. External services should use `get_system_metrics()`
    (the hot path) for production workloads.
    """

    def __init__(self, base_url: str = None, timeout: float = 8.0):
        # This is correct: all traffic goes to the /ops gateway
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY

                base_url = f"{SERVE_GATEWAY}/ops"
            except Exception:
                base_url = "http://127.0.0.1:8000/ops"

        # Circuit breaker and retry config are still good
        circuit_breaker = CircuitBreaker(
            failure_threshold=5, recovery_timeout=30.0, expected_exception=(Exception,)
        )

        retry_config = RetryConfig(max_attempts=2, base_delay=1.0, max_delay=5.0)

        super().__init__(
            service_name="state_service",
            base_url=base_url,
            timeout=timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config,
        )

    # --- Primary Method ---

    async def get_system_metrics(self) -> Dict[str, Any]:
        """
        Get the pre-computed, unified system metrics.

        **HOT PATH - Refined Jet Fuel for Production**

        This is the main data endpoint for the Coordinator and Energy Service.
        It returns the distilled, pre-computed aggregates that are optimized
        for real-time routing decisions (O(1) lookup from cache).

        The data returned here is the "refined jet fuel" - small, valuable
        metrics extracted from the raw agent snapshots by the AgentAggregator's
        distillation engine (`_compute_system_metrics()`).

        Returns:
            The full metrics dictionary, e.g.:
            {
                "success": True,
                "metrics": {
                    "memory": { ... },
                    "system": { ... }
                },
                "timestamp": 12345.678
            }
        """
        # This route must match the OpsGateway
        return await self.get("/state/system-metrics")

    async def get_all_agent_snapshots(self) -> Dict[str, Any]:
        """
        Get the full state snapshot for all agents.

        COLD PATH - Raw "Crude Oil" for Debugging/Analysis Only

        This endpoint exposes the raw `_agent_snapshots` cache. It may contain
        multi-megabyte payloads for every agent in the system and is NOT designed
        for real-time or production use.

        Architectural Notes:
        --------------------
        1. Not for Production Use:
           The Coordinator and Energy Service must NEVER call this endpoint
           in production. They require refined, aggregated metrics from
           get_system_metrics() (the "jet fuel"), not raw snapshots.

        2. Intended Consumer:
           The true consumer of `_agent_snapshots` is the AgentAggregator, which
           distills this raw data into `_system_metrics` via `_compute_system_metrics()`.

        3. Scaling Considerations:
           At scale (hundreds of thousands to millions of agents), this method should
           only be used for:
           - Offline analysis
           - Debugging
           - QA and development environments
           In the future, this will be replaced by structured data streams into a
           data lake or warehouse.

        4. Distillation Pipeline:
           The AgentAggregator continuously polls agents, accumulates
           `_agent_snapshots`, and transforms them into `_system_metrics` - a compact
           representation used for real-time routing and scheduling.

        For real-time decision making, always use get_system_metrics() instead.

        Returns:
            Dictionary containing:
            {
                "success": True,
                "count": 42,
                "snapshots": {
                    "agent_id_1": {
                        "h": [...],
                        "p": {"E": 0.5, "S": 0.3, "O": 0.2},
                        "c": 0.85,
                        "mem_util": 0.6,
                        "lifecycle": "Employed",
                        "learned_skills": {...}
                    },
                    ...
                },
                "timestamp": 12345.678
            }
        """

        # This route must match the OpsGateway
        return await self.get("/state/agent-snapshots")

    # --- Service Information ---

    async def health(self) -> Dict[str, Any]:
        """
        Check the health of the StateService.

        This polls the OpsGateway, which in turn polls the
        StateService's internal /health endpoint.
        """
        # This route must match the OpsGateway
        return await self.get("/state/health")

    async def is_healthy(self) -> bool:
        """
        Check if the state service is healthy.

        Returns:
            True if the service reports 'healthy', False otherwise.
        """
        try:
            health_data = await self.health()
            # The health check proxies the service's own health
            return health_data.get("status") == "healthy"
        except Exception:
            return False
