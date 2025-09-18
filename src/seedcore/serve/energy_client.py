#!/usr/bin/env python3
"""
Energy Service Client for SeedCore

This client provides a clean interface to the deployed energy service
for energy management, control loops, and system optimization.
"""

import logging
from typing import Dict, Any, Optional, List
from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig

logger = logging.getLogger(__name__)

class EnergyServiceClient(BaseServiceClient):
    """
    Client for the deployed energy service that handles:
    - Energy state management
    - Control loop operations
    - System optimization
    - Energy monitoring
    """
    
    def __init__(self, 
                 base_url: str = None, 
                 timeout: float = 8.0):
        # Use centralized gateway discovery
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY
                base_url = f"{SERVE_GATEWAY}/energy"
            except Exception:
                base_url = "http://127.0.0.1:8000/energy"
        
        # Configure circuit breaker for energy service
        circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
            expected_exception=(Exception,)  # Catch all exceptions
        )
        
        # Configure retry for energy service
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
    
    # Energy State Management
    async def get_energy_state(self, agent_id: str = None) -> Dict[str, Any]:
        """
        Get energy state for an agent or system.
        
        Args:
            agent_id: Optional agent identifier
            
        Returns:
            Energy state data
        """
        if agent_id:
            return await self.get(f"/state/{agent_id}")
        else:
            return await self.get("/state")
    
    async def update_energy_state(self, agent_id: str, energy_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update energy state for an agent.
        
        Args:
            agent_id: Agent identifier
            energy_data: Energy state data
            
        Returns:
            Update result
        """
        return await self.post(f"/state/{agent_id}", json=energy_data)
    
    async def get_energy_history(self, agent_id: str, time_range: str = "1h") -> Dict[str, Any]:
        """
        Get energy history for an agent.
        
        Args:
            agent_id: Agent identifier
            time_range: Time range for history (1h, 24h, 7d)
            
        Returns:
            Energy history data
        """
        params = {"time_range": time_range}
        return await self.get(f"/history/{agent_id}", params=params)
    
    # Control Loop Operations
    async def start_control_loop(self, loop_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Start a control loop.
        
        Args:
            loop_config: Control loop configuration
            
        Returns:
            Control loop start result
        """
        return await self.post("/control-loops/start", json=loop_config)
    
    async def stop_control_loop(self, loop_id: str) -> Dict[str, Any]:
        """
        Stop a control loop.
        
        Args:
            loop_id: Control loop identifier
            
        Returns:
            Control loop stop result
        """
        return await self.post(f"/control-loops/{loop_id}/stop")
    
    async def get_control_loop_status(self, loop_id: str = None) -> Dict[str, Any]:
        """
        Get control loop status.
        
        Args:
            loop_id: Optional control loop identifier
            
        Returns:
            Control loop status
        """
        if loop_id:
            return await self.get(f"/control-loops/{loop_id}")
        else:
            return await self.get("/control-loops")
    
    async def update_control_loop_config(self, loop_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update control loop configuration.
        
        Args:
            loop_id: Control loop identifier
            config: New configuration
            
        Returns:
            Update result
        """
        return await self.put(f"/control-loops/{loop_id}/config", json=config)
    
    # System Optimization
    async def optimize_energy_allocation(self, constraints: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Optimize energy allocation across the system.
        
        Args:
            constraints: Optional optimization constraints
            
        Returns:
            Optimization result
        """
        request_data = constraints or {}
        return await self.post("/optimize", json=request_data)
    
    async def get_optimization_recommendations(self, agent_id: str = None) -> Dict[str, Any]:
        """
        Get optimization recommendations.
        
        Args:
            agent_id: Optional agent identifier
            
        Returns:
            Optimization recommendations
        """
        if agent_id:
            return await self.get(f"/recommendations/{agent_id}")
        else:
            return await self.get("/recommendations")
    
    async def apply_optimization(self, optimization_id: str) -> Dict[str, Any]:
        """
        Apply an optimization.
        
        Args:
            optimization_id: Optimization identifier
            
        Returns:
            Application result
        """
        return await self.post(f"/optimizations/{optimization_id}/apply")
    
    # Energy Monitoring
    async def get_energy_metrics(self, time_range: str = "1h") -> Dict[str, Any]:
        """
        Get energy metrics.
        
        Args:
            time_range: Time range for metrics
            
        Returns:
            Energy metrics
        """
        params = {"time_range": time_range}
        return await self.get("/metrics", params=params)
    
    async def get_energy_alerts(self) -> Dict[str, Any]:
        """Get active energy alerts."""
        return await self.get("/alerts")
    
    async def acknowledge_alert(self, alert_id: str) -> Dict[str, Any]:
        """
        Acknowledge an energy alert.
        
        Args:
            alert_id: Alert identifier
            
        Returns:
            Acknowledgment result
        """
        return await self.post(f"/alerts/{alert_id}/acknowledge")
    
    async def get_energy_thresholds(self) -> Dict[str, Any]:
        """Get energy thresholds configuration."""
        return await self.get("/thresholds")
    
    async def update_energy_thresholds(self, thresholds: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update energy thresholds.
        
        Args:
            thresholds: New threshold values
            
        Returns:
            Update result
        """
        return await self.put("/thresholds", json=thresholds)
    
    # Energy Policies
    async def get_energy_policies(self) -> Dict[str, Any]:
        """Get active energy policies."""
        return await self.get("/policies")
    
    async def create_energy_policy(self, policy: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new energy policy.
        
        Args:
            policy: Policy configuration
            
        Returns:
            Creation result
        """
        return await self.post("/policies", json=policy)
    
    async def update_energy_policy(self, policy_id: str, policy: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an energy policy.
        
        Args:
            policy_id: Policy identifier
            policy: Updated policy configuration
            
        Returns:
            Update result
        """
        return await self.put(f"/policies/{policy_id}", json=policy)
    
    async def delete_energy_policy(self, policy_id: str) -> Dict[str, Any]:
        """
        Delete an energy policy.
        
        Args:
            policy_id: Policy identifier
            
        Returns:
            Deletion result
        """
        return await self.delete(f"/policies/{policy_id}")
    
    # Service Information
    async def get_service_info(self) -> Dict[str, Any]:
        """Get energy service information."""
        return await self.get("/info")
    
    async def is_healthy(self) -> bool:
        """Check if the energy service is healthy."""
        try:
            health = await self.health_check()
            return health.get("status") == "healthy"
        except Exception:
            return False
