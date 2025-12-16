#!/usr/bin/env python3
"""
Coordinator Service Client for SeedCore

This client provides a clean interface to the deployed coordinator service
for task processing, anomaly triage, and system orchestration.

The Coordinator Service now uses a unified interface:
- All business operations go through `/route-and-execute`
- Type-based routing: Uses TaskPayload.type to route internally
  * type: "anomaly_triage" → Anomaly triage pipeline
  * type: "ml_tune_callback" → ML tuning callback handler
  * Other types → Standard routing & execution
"""

import logging
from typing import Dict, Any, Optional, List, Union
from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig

logger = logging.getLogger(__name__)

class CoordinatorServiceClient(BaseServiceClient):
    """
    Client for the deployed coordinator service that handles:
    - Task processing and routing (unified interface)
    - Anomaly triage pipeline (via type-based routing)
    - System orchestration
    - ML tuning coordination (via type-based routing)
    
    All business operations use the unified `/route-and-execute` endpoint
    with type-based internal routing.
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
    async def route_and_execute(self, task: Union[Dict[str, Any], Any]) -> Dict[str, Any]:
        """
        Universal Interface: Process a task through the coordinator.
        
        This is the unified entrypoint for all Coordinator operations.
        Uses TaskPayload.type to route internally:
        - type: "anomaly_triage" → Anomaly triage pipeline
        - type: "ml_tune_callback" → ML tuning callback handler
        - Other types → Standard routing & execution
        
        Args:
            task: TaskPayload object or dict with:
                - type: Task type (e.g., "anomaly_triage", "ml_tune_callback", "general_query")
                - params: Task parameters (including agent_id, series, context for anomaly_triage)
                - description: Task description
                - domain: Optional domain
                - correlation_id: Optional correlation ID
            
        Returns:
            Task processing result (varies by type)
        """
        # Handle TaskPayload objects
        if hasattr(task, 'model_dump'):
            task = task.model_dump()
        elif hasattr(task, 'dict'):
            task = task.dict()
        
        return await self.post("/route-and-execute", json=task)
    
    async def submit_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit a task for processing (alias for route_and_execute).
        
        DEPRECATED: Use route_and_execute() directly for clarity.
        This method is kept for backward compatibility.
        
        Args:
            task: Task dictionary
            
        Returns:
            Task processing result
        """
        logger.warning("submit_task() is deprecated. Use route_and_execute() instead.")
        return await self.route_and_execute(task)
    
    # Anomaly Triage Pipeline (via Unified Interface)
    async def anomaly_triage(self, 
                           agent_id: str,
                           series: List[float] = None,
                           context: Dict[str, Any] = None,
                           correlation_id: str = None) -> Dict[str, Any]:
        """
        Process anomaly triage pipeline via unified interface.
        
        This method constructs a TaskPayload with type="anomaly_triage"
        and routes it through the unified route_and_execute endpoint.
        
        Args:
            agent_id: Agent identifier
            series: Time series data for anomaly detection (optional)
            context: Additional context data (optional)
            correlation_id: Optional correlation ID
            
        Returns:
            AnomalyTriageResponse with anomalies, reason, decision_kind, etc.
        """
        task_payload = {
            "type": "anomaly_triage",
            "params": {
                "agent_id": agent_id,
                "series": series or [],
                "context": context or {},
            },
            "description": f"Anomaly triage for agent {agent_id}",
        }
        
        if correlation_id:
            task_payload["correlation_id"] = correlation_id
        
        return await self.route_and_execute(task_payload)
    
    # System Status and Health (Operational Endpoints)
    async def get_health_status(self) -> Dict[str, Any]:
        """
        Get detailed health status of coordinator service.
        
        Note: This is an operational endpoint (hidden from OpenAPI schema).
        Used by Kubernetes liveness probes.
        """
        return await self.get("/health")
    
    async def get_metrics(self) -> Dict[str, Any]:
        """
        Get system metrics and performance data.
        
        Note: This is an operational endpoint (hidden from OpenAPI schema).
        Used by Prometheus for monitoring.
        """
        return await self.get("/metrics")
    
    async def get_predicate_status(self) -> Dict[str, Any]:
        """
        Get predicate system status and GPU guard information.
        
        Note: This is an operational/admin endpoint (hidden from OpenAPI schema).
        """
        return await self.get("/predicates/status")
    
    async def get_predicate_config(self) -> Dict[str, Any]:
        """
        Get current predicate configuration.
        
        Note: This is an operational/admin endpoint (hidden from OpenAPI schema).
        """
        return await self.get("/predicates/config")
    
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
    
    # ML Tuning Coordination (via Unified Interface)
    async def ml_tuning_callback(self, 
                                job_id: str,
                                status: str = "completed",
                                E_after: Optional[float] = None,
                                gpu_seconds: Optional[float] = None,
                                error: Optional[str] = None) -> Dict[str, Any]:
        """
        Handle ML tuning job callback via unified interface.
        
        This method constructs a TaskPayload with type="ml_tune_callback"
        and routes it through the unified route_and_execute endpoint.
        
        Args:
            job_id: Job identifier
            status: Job status ("completed" or "failed")
            E_after: Energy after tuning (optional)
            gpu_seconds: GPU seconds used (optional)
            error: Error message if failed (optional)
            
        Returns:
            Callback processing result
        """
        task_payload = {
            "type": "ml_tune_callback",
            "params": {
                "job_id": job_id,
                "status": status,
            },
            "description": f"ML tuning callback for job {job_id}",
        }
        
        if E_after is not None:
            task_payload["params"]["E_after"] = E_after
        if gpu_seconds is not None:
            task_payload["params"]["gpu_seconds"] = gpu_seconds
        if error is not None:
            task_payload["params"]["error"] = error
        
        return await self.route_and_execute(task_payload)
    
    # Health Check
    async def health_check(self) -> Dict[str, Any]:
        """
        Health check endpoint (alias for get_health_status).
        
        Returns:
            Health status dictionary
        """
        return await self.get_health_status()
    
    async def is_healthy(self) -> bool:
        """
        Check if the coordinator service is healthy.
        
        Returns:
            True if service is healthy, False otherwise
        """
        try:
            health = await self.health_check()
            return health.get("status") == "healthy"
        except Exception:
            return False
