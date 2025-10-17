#!/usr/bin/env python3
"""
State Service Client for SeedCore

This client provides a clean interface to the deployed state service
for agent state management, memory operations, and state aggregation.
"""

import logging
from typing import Dict, Any, Optional, List
from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig

logger = logging.getLogger(__name__)

class StateServiceClient(BaseServiceClient):
    """
    Client for the deployed state service that handles:
    - Agent state management
    - Memory operations
    - State aggregation
    - State persistence
    """
    
    def __init__(self, 
                 base_url: str = None, 
                 timeout: float = 8.0):
        # Use centralized gateway discovery (state service now under /ops)
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY
                base_url = f"{SERVE_GATEWAY}/ops"
            except Exception:
                base_url = "http://127.0.0.1:8000/ops"
        
        # Configure circuit breaker for state service
        circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
            expected_exception=(Exception,)  # Catch all exceptions
        )
        
        # Configure retry for state service
        retry_config = RetryConfig(
            max_attempts=2,
            base_delay=1.0,
            max_delay=5.0
        )
        
        super().__init__(
            service_name="state_service",
            base_url=base_url,
            timeout=timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config
        )
    
    # Agent State Management
    async def get_agent_state(self, agent_id: str) -> Dict[str, Any]:
        """
        Get state for a specific agent.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            Agent state data
        """
        return await self.get(f"/agent/{agent_id}")
    
    async def update_agent_state(self, agent_id: str, state_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update state for a specific agent.
        
        Args:
            agent_id: Agent identifier
            state_data: State data to update
            
        Returns:
            Update result
        """
        return await self.post(f"/agent/{agent_id}", json=state_data)
    
    async def delete_agent_state(self, agent_id: str) -> Dict[str, Any]:
        """
        Delete state for a specific agent.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            Deletion result
        """
        return await self.delete(f"/agent/{agent_id}")
    
    async def list_agents(self) -> Dict[str, Any]:
        """List all agents with state."""
        return await self.get("/agents")
    
    # Memory Operations
    async def store_memory(self, agent_id: str, memory_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Store memory for an agent.
        
        Args:
            agent_id: Agent identifier
            memory_data: Memory data to store
            
        Returns:
            Storage result
        """
        request_data = {
            "agent_id": agent_id,
            "memory_data": memory_data
        }
        return await self.post("/memory", json=request_data)
    
    async def retrieve_memory(self, agent_id: str, query: str = None) -> Dict[str, Any]:
        """
        Retrieve memory for an agent.
        
        Args:
            agent_id: Agent identifier
            query: Optional query for memory retrieval
            
        Returns:
            Retrieved memory data
        """
        params = {}
        if query:
            params["query"] = query
        return await self.get(f"/memory/{agent_id}", params=params)
    
    async def search_memory(self, agent_id: str, search_query: str) -> Dict[str, Any]:
        """
        Search memory for an agent.
        
        Args:
            agent_id: Agent identifier
            search_query: Search query
            
        Returns:
            Search results
        """
        request_data = {
            "agent_id": agent_id,
            "query": search_query
        }
        return await self.post("/memory/search", json=request_data)
    
    async def delete_memory(self, agent_id: str, memory_id: str) -> Dict[str, Any]:
        """
        Delete specific memory for an agent.
        
        Args:
            agent_id: Agent identifier
            memory_id: Memory identifier
            
        Returns:
            Deletion result
        """
        return await self.delete(f"/memory/{agent_id}/{memory_id}")
    
    # State Aggregation
    async def get_aggregated_state(self, aggregation_type: str = "all") -> Dict[str, Any]:
        """
        Get aggregated state across all agents.
        
        Args:
            aggregation_type: Type of aggregation (all, recent, summary)
            
        Returns:
            Aggregated state data
        """
        return await self.get(f"/aggregated/{aggregation_type}")
    
    async def get_system_state(self) -> Dict[str, Any]:
        """Get overall system state."""
        return await self.get("/system")
    
    async def get_state_summary(self) -> Dict[str, Any]:
        """Get state summary."""
        return await self.get("/summary")
    
    # State Persistence
    async def backup_state(self, backup_name: str = None) -> Dict[str, Any]:
        """
        Create a state backup.
        
        Args:
            backup_name: Optional backup name
            
        Returns:
            Backup result
        """
        request_data = {}
        if backup_name:
            request_data["backup_name"] = backup_name
        return await self.post("/backup", json=request_data)
    
    async def restore_state(self, backup_name: str) -> Dict[str, Any]:
        """
        Restore state from backup.
        
        Args:
            backup_name: Backup name to restore
            
        Returns:
            Restore result
        """
        request_data = {"backup_name": backup_name}
        return await self.post("/restore", json=request_data)
    
    async def list_backups(self) -> Dict[str, Any]:
        """List available state backups."""
        return await self.get("/backups")
    
    # State Statistics
    async def get_state_stats(self) -> Dict[str, Any]:
        """Get state statistics."""
        return await self.get("/stats")
    
    async def get_memory_stats(self, agent_id: str = None) -> Dict[str, Any]:
        """
        Get memory statistics.
        
        Args:
            agent_id: Optional agent identifier for specific stats
            
        Returns:
            Memory statistics
        """
        if agent_id:
            return await self.get(f"/memory/stats/{agent_id}")
        else:
            return await self.get("/memory/stats")
    
    # Service Information
    async def get_service_info(self) -> Dict[str, Any]:
        """Get state service information."""
        return await self.get("/info")
    
    async def is_healthy(self) -> bool:
        """Check if the state service is healthy."""
        try:
            health = await self.health_check()
            return health.get("status") == "healthy"
        except Exception:
            return False
