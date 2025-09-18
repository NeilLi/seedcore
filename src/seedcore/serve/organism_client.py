#!/usr/bin/env python3
"""
Organism Service Client for SeedCore (Updated)

This client provides a clean interface to the deployed organism service
using the new base client architecture.
"""

import logging
from typing import Dict, Any, Optional, List
from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig

logger = logging.getLogger(__name__)

class OrganismServiceClient(BaseServiceClient):
    """
    Client for the deployed organism service that handles:
    - Task execution
    - Organ management
    - Decision making
    - Task planning
    - Organism status monitoring
    """
    
    def __init__(self, 
                 base_url: str = None, 
                 timeout: float = 10.0):
        # Use centralized gateway discovery
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY
                base_url = f"{SERVE_GATEWAY}/organism"
            except Exception:
                base_url = "http://127.0.0.1:8000/organism"
        
        # Configure circuit breaker for organism service
        circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
            expected_exception=(Exception,)  # Catch all exceptions
        )
        
        # Configure retry for organism service
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
    
    # Task Execution
    async def execute_on_organ(self, 
                             organ_name: str,
                             task: Dict[str, Any],
                             app_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute a task on a specific organ.
        
        Args:
            organ_name: Name of the organ
            task: Task to execute
            app_state: Optional application state
            
        Returns:
            Task execution result
        """
        request_data = {
            "organ_name": organ_name,
            "task": task,
            "app_state": app_state or {}
        }
        return await self.post("/execute-on-organ", json=request_data)
    
    async def handle_task(self, 
                         task: Dict[str, Any],
                         app_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Handle a task through the organism service.
        
        Args:
            task: Task to handle
            app_state: Optional application state
            
        Returns:
            Task handling result
        """
        request_data = {
            "task": task,
            "app_state": app_state or {}
        }
        return await self.post("/handle-task", json=request_data)
    
    # Decision Making
    async def make_decision(self, 
                          task: Dict[str, Any],
                          app_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Make a decision through the organism service.
        
        Args:
            task: Task for decision making
            app_state: Optional application state
            
        Returns:
            Decision result
        """
        request_data = {
            "task": task,
            "app_state": app_state or {}
        }
        return await self.post("/make-decision", json=request_data)
    
    # Task Planning
    async def plan_task(self, 
                       task: Dict[str, Any],
                       app_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Plan a task through the organism service.
        
        Args:
            task: Task to plan
            app_state: Optional application state
            
        Returns:
            Task planning result
        """
        request_data = {
            "task": task,
            "app_state": app_state or {}
        }
        return await self.post("/plan-task", json=request_data)
    
    # Organ Management
    async def get_organ_status(self, organ_name: str = None) -> Dict[str, Any]:
        """
        Get status of a specific organ or all organs.
        
        Args:
            organ_name: Optional organ name
            
        Returns:
            Organ status information
        """
        if organ_name:
            return await self.get(f"/organs/{organ_name}")
        else:
            return await self.get("/organs")
    
    async def get_organ_capabilities(self, organ_name: str) -> Dict[str, Any]:
        """
        Get capabilities of a specific organ.
        
        Args:
            organ_name: Name of the organ
            
        Returns:
            Organ capabilities
        """
        return await self.get(f"/organs/{organ_name}/capabilities")
    
    async def update_organ_config(self, organ_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update configuration of a specific organ.
        
        Args:
            organ_name: Name of the organ
            config: New configuration
            
        Returns:
            Update result
        """
        return await self.put(f"/organs/{organ_name}/config", json=config)
    
    # Organism Status
    async def get_organism_status(self) -> Dict[str, Any]:
        """Get detailed status of all organs in the organism."""
        return await self.get("/organism-status")
    
    async def get_organism_summary(self) -> Dict[str, Any]:
        """Get a summary of the organism's current state."""
        return await self.get("/organism-summary")
    
    async def get_organism_health(self) -> Dict[str, Any]:
        """Get organism health status."""
        return await self.get("/organism-health")
    
    # Organism Management
    async def initialize_organism(self, config: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Initialize the organism.
        
        Args:
            config: Optional initialization configuration
            
        Returns:
            Initialization result
        """
        request_data = config or {}
        return await self.post("/initialize", json=request_data)
    
    async def shutdown_organism(self) -> Dict[str, Any]:
        """Shutdown the organism."""
        return await self.post("/shutdown")
    
    async def restart_organism(self) -> Dict[str, Any]:
        """Restart the organism."""
        return await self.post("/restart")
    
    # Organism Monitoring
    async def get_organism_metrics(self) -> Dict[str, Any]:
        """Get organism performance metrics."""
        return await self.get("/metrics")
    
    async def get_organism_logs(self, log_level: str = "INFO", limit: int = 100) -> Dict[str, Any]:
        """
        Get organism logs.
        
        Args:
            log_level: Log level filter
            limit: Maximum number of log entries
            
        Returns:
            Log entries
        """
        params = {
            "level": log_level,
            "limit": limit
        }
        return await self.get("/logs", params=params)
    
    # Service Information
    async def get_service_info(self) -> Dict[str, Any]:
        """Get organism service information."""
        return await self.get("/info")
    
    async def is_healthy(self) -> bool:
        """Check if the organism service is healthy."""
        try:
            health = await self.health_check()
            return health.get("status") == "healthy"
        except Exception:
            return False
