#!/usr/bin/env python3
"""
Fact Service Client for SeedCore (Proactive v2)

This client provides a clean, read-only interface to the OpsGateway → FactManagerService
pipeline. It interacts exclusively with the refined, production-grade endpoints:
    /ops/fact/create
    /ops/fact/query
    /ops/fact/health
"""

import logging
from typing import Dict, Any

from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig

logger = logging.getLogger(__name__)


class FactManagerServiceClient(BaseServiceClient):
    """
    Client for the proactive FactManagerService via OpsGateway.

    NOTE:
    -----
    - **Gateway Pattern**: This client does NOT connect to Ray Actors directly. 
      It targets the centralized `OpsGateway` (HTTP), allowing the backend to 
      scale or restart actors without breaking client connections.
    - **Hybrid Payload**: The backend accepts both Pydantic models (via HTTP docs)
      and Dicts. This client sends JSON Dicts, which the service normalizes.
    """

    def __init__(self, base_url: str = None, timeout: float = 8.0):
        # All traffic must go to OpsGateway, not directly to underlying services.
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY
                base_url = SERVE_GATEWAY  # e.g. "http://127.0.0.1:8000"
            except Exception:
                base_url = "http://127.0.0.1:8000"

        # Circuit Breaker: Fail fast if the Knowledge Graph is down
        circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
            expected_exception=(Exception,),
        )

        # Retry: Facts are critical; retry briefly on transient network glitches
        retry_config = RetryConfig(
            max_attempts=2,
            base_delay=1.0,
            max_delay=5.0,
        )

        super().__init__(
            service_name="FactManagerService",
            base_url=base_url,
            timeout=timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config,
        )

    # ----------------------------------------------------------------------
    # WRITE PATH (Transactional)
    # ----------------------------------------------------------------------

    async def create_fact(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Persist a new fact into the Knowledge Graph.
        
        This endpoint handles the 'Dual Interface' logic on the backend, 
        converting this Dict into a Pydantic `FactCreate` model internally.

        Args:
            payload (Dict): Must contain 'content'. Optional 'source', 'metadata'.
        
        Returns:
            Dict: Confirmation with the new 'fact_id'.
        """
        return await self.post("/ops/fact/create", json=payload)

    # ----------------------------------------------------------------------
    # READ PATH (Analytical)
    # ----------------------------------------------------------------------

    async def query_fact(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Query facts using semantic search or filters.

        PROTOCOL NOTE: 
        We use POST here (instead of GET) because query payloads often contain 
        complex structures (filters, vector embeddings) that hit URL length limits 
        or are insecure in query parameters.

        Args:
            payload (Dict): Filters, query_text, or limits.

        Returns:
            Dict: List of matching facts and metadata.
        """
        # CRITICAL FIX: Changed from self.get to self.post to match OpsGateway definition
        return await self.post("/ops/fact/query", json=payload)

    async def health(self) -> Dict[str, Any]:
        """
        Health check for FactManagerService via OpsGateway.
        
        Verifies that:
        1. The HTTP Gateway is up.
        2. The underlying FactManager Actor is initialized and ready.
        """
        return await self.get("/ops/fact/health")

    async def is_healthy(self) -> bool:
        """Convenience method: return True if service reports healthy."""
        try:
            return (await self.health()).get("status") == "healthy"
        except Exception:
            return False