#!/usr/bin/env python3
"""
OrganismCore Client for SeedCore (V2 Agent-Centric)

This client provides a clean interface to the deployed OrganismCore.
Its primary role is to submit tasks for execution via the
canonical routing APIs: route_only() and route_and_execute().
"""

import logging
from typing import Dict, Any

from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig

logger = logging.getLogger(__name__)


def get_organism_service_handle():
    """
    Get a Ray Serve deployment handle to OrganismService.
    
    This is a convenience function for services that need direct Ray handle access
    (e.g., StateService's AgentAggregator which needs to call .remote() methods).
    
    Returns:
        Ray Serve deployment handle to OrganismService
    """
    try:
        from ray import serve  # pyright: ignore[reportMissingImports]
        return serve.get_deployment_handle("OrganismService", app_name="organism")
    except Exception as e:
        logger.error(f"Failed to get OrganismService handle: {e}")
        raise

class OrganismServiceClient(BaseServiceClient):
    """
    Client for the deployed OrganismCore (v2) router.
    
    This client provides access to the canonical routing APIs:
    - route_only(): Pure routing decisions (returns RouterDecision)
    - route_and_execute(): Routing + execution in one call
    
    It also provides monitoring and lifecycle management:
    - Health checks and status monitoring
    - Organism initialization and shutdown
    
    NOTE: This client does NOT manage policy, routing rules, or
    individual organ configurations. That logic is now handled
    by the Coordinator and the State/Energy services.
    """
    
    def __init__(self, 
                 base_url: str = None, 
                 timeout: float = 10.0):
        
        # This base URL is correct for a dedicated Organism app
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY
                base_url = f"{SERVE_GATEWAY}/organism"
            except Exception:
                base_url = "http://127.0.0.1:8000/organism"
        
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
            service_name="organism_service",
            base_url=base_url,
            timeout=timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config
        )
    
    # --- Primary Task Execution ---
    
    async def route_only(
        self,
        task: Dict[str, Any],
        current_epoch: str = None
    ) -> Dict[str, Any]:
        """
        Pure routing. Returns RouterDecision.
        
        This is the canonical API for Dispatcher, Coordinator,
        and external IoT/human/robot services.
        
        Used when callers need routing decisions but not immediate execution.
        
        Args:
            task: Task payload (TaskPayload-compatible dict)
            current_epoch: Optional epoch for instance validation
            
        Returns:
            RouterDecisionResponse with agent_id, organ_id, reason, is_high_stakes
        """
        request_data = {
            "task": task,
            "current_epoch": current_epoch
        }
        return await self.post("/route-only", json=request_data)
    
    async def route_and_execute(
        self,
        task: Dict[str, Any],
        current_epoch: str = None
    ) -> Dict[str, Any]:
        """
        Routing + execution convenience method.
        
        Calls:
            1. route_only()
            2. organism.execute_on_agent()
        
        Used by simple endpoints, cognitive client, demo workflows,
        and basic actuator interactions (IoT, robots, external systems).
        
        Args:
            task: Task payload (TaskPayload-compatible dict)
            current_epoch: Optional epoch for instance validation
            
        Returns:
            OrganismResponse with execution result and routing metadata
        """
        request_data = {
            "task": task,
            "current_epoch": current_epoch
        }
        return await self.post("/route-and-execute", json=request_data)
    
    # --- High-Level Organism Monitoring ---
    
    async def get_organism_status(self) -> Dict[str, Any]:
        """Get detailed status of all organ-registries in the organism."""
        return await self.get("/organism-status")
    
    async def get_organism_summary(self) -> Dict[str, Any]:
        """Get a summary of the organism's current state."""
        return await self.get("/organism-summary")

    async def get_organism_metrics(self) -> Dict[str, Any]:
        """Get organism performance metrics."""
        return await self.get("/metrics")
    
    async def get_organism_logs(self, log_level: str = "INFO", limit: int = 100) -> Dict[str, Any]:
        """Get organism logs."""
        params = {"level": log_level, "limit": limit}
        return await self.get("/logs", params=params)

    # --- Service Information & Lifecycle ---

    async def get_service_info(self) -> Dict[str, Any]:
        """Get organism service information."""
        return await self.get("/info")

    async def health(self) -> Dict[str, Any]:
        """Get organism health status."""
        return await self.get("/health")
    
    async def is_healthy(self) -> bool:
        """Check if the organism service is healthy."""
        try:
            # Note: We call our own .health() method, not .health_check()
            health_data = await self.health() 
            return health_data.get("status") == "healthy"
        except Exception:
            return False
            
    # --- Lifecycle (Optional - may be admin-only) ---
    
    async def initialize_organism(self, config: Dict[str, Any] = None) -> Dict[str, Any]:
        """Initialize the organism."""
        return await self.post("/initialize", json=config or {})
    
    async def shutdown_organism(self) -> Dict[str, Any]:
        """Shutdown the organism."""
        return await self.post("/shutdown")
