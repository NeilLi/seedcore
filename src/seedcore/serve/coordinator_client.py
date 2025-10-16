#!/usr/bin/env python3
"""
Coordinator Service Client for SeedCore

This client provides a clean interface to the deployed coordinator service
for task processing, anomaly triage, and system orchestration.
"""

import logging
from typing import Dict, Any, Optional, List
from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig

logger = logging.getLogger(__name__)

class CoordinatorServiceClient(BaseServiceClient):
    """
    Client for the deployed coordinator service that handles:
    - Task processing and routing
    - Anomaly triage pipeline
    - System orchestration
    - Energy management
    - ML tuning coordination
    """
    
    def __init__(self, 
                 base_url: str = None, 
                 timeout: float = 10.0):
        # Use centralized gateway discovery
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY
                base_url = f"{SERVE_GATEWAY}/pipeline"
            except Exception:
                base_url = "http://127.0.0.1:8000/pipeline"
        
        # Configure circuit breaker for coordinator service
        circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
            expected_exception=(Exception,)  # Catch all exceptions
        )
        
        # Configure retry for coordinator service
        retry_config = RetryConfig(
            max_attempts=2,
            base_delay=1.0,
            max_delay=5.0
        )
        
        super().__init__(
            service_name="coordinator",
            base_url=base_url,
            timeout=timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config
        )
    
    # Task Processing Methods
    async def process_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a task through the coordinator.
        
        Args:
            task: Task dictionary with type, params, description, domain, drift_score
            
        Returns:
            Task processing result
        """
        return await self.post("/process-task", json=task)
    
    async def submit_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit a task for processing.
        
        Args:
            task: Task dictionary
            
        Returns:
            Task submission result
        """
        return await self.post("/submit-task", json=task)
    
    # Anomaly Triage Pipeline
    async def anomaly_triage(self, 
                           incident_data: Dict[str, Any], 
                           correlation_id: str = None) -> Dict[str, Any]:
        """
        Process anomaly triage pipeline.
        
        Args:
            incident_data: Incident data for triage
            correlation_id: Optional correlation ID
            
        Returns:
            Triage result with recommendations
        """
        request_data = {
            "incident_data": incident_data,
            "correlation_id": correlation_id
        }
        return await self.post("/anomaly-triage", json=request_data)
    
    # System Status and Health
    async def get_system_status(self) -> Dict[str, Any]:
        """Get overall system status."""
        return await self.get("/status")
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get detailed health status of all services."""
        return await self.get("/health")
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get system metrics and performance data."""
        return await self.get("/metrics")
    
    # Energy Management
    async def get_energy_state(self, agent_id: str) -> Dict[str, Any]:
        """
        Get energy state for an agent.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            Energy state information
        """
        return await self.get(f"/ops/energy/{agent_id}")
    
    async def update_energy_state(self, agent_id: str, energy_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update energy state for an agent.
        
        Args:
            agent_id: Agent identifier
            energy_data: Energy state data
            
        Returns:
            Update result
        """
        return await self.post(f"/ops/energy/{agent_id}", json=energy_data)
    
    # ML Tuning Coordination
    async def submit_ml_tuning_job(self, 
                                 agent_id: str, 
                                 tuning_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit an ML tuning job.
        
        Args:
            agent_id: Agent identifier
            tuning_config: Tuning configuration
            
        Returns:
            Job submission result
        """
        request_data = {
            "agent_id": agent_id,
            "tuning_config": tuning_config
        }
        return await self.post("/ml/tune/submit", json=request_data)
    
    async def get_ml_tuning_status(self, job_id: str) -> Dict[str, Any]:
        """
        Get status of an ML tuning job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Job status information
        """
        return await self.get(f"/ml/tune/status/{job_id}")
    
    async def ml_tuning_callback(self, job_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle ML tuning job callback.
        
        Args:
            job_id: Job identifier
            result: Tuning result
            
        Returns:
            Callback processing result
        """
        request_data = {
            "job_id": job_id,
            "result": result
        }
        return await self.post("/ml/tune/callback", json=request_data)
    
    # Circuit Breaker Management
    async def get_circuit_breaker_status(self) -> Dict[str, Any]:
        """Get status of all circuit breakers."""
        return await self.get("/circuit-breakers")
    
    async def reset_circuit_breaker(self, service_name: str) -> Dict[str, Any]:
        """
        Reset a circuit breaker.
        
        Args:
            service_name: Name of the service
            
        Returns:
            Reset result
        """
        return await self.post(f"/circuit-breakers/{service_name}/reset")
    
    # Service Information
    async def get_service_info(self) -> Dict[str, Any]:
        """Get coordinator service information."""
        return await self.get("/info")
    
    async def is_healthy(self) -> bool:
        """Check if the coordinator service is healthy."""
        try:
            health = await self.health_check()
            return health.get("status") == "healthy"
        except Exception:
            return False
