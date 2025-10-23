#!/usr/bin/env python3
"""
Task Router Interface for SeedCore Dispatcher

This module provides a pluggable router interface that decouples the dispatcher
from direct Serve deployment handles, enabling better separation of concerns
and improved testability.
"""

import os
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass

from seedcore.models import TaskPayload
from seedcore.serve.base_client import BaseServiceClient, CircuitBreaker, RetryConfig

logger = logging.getLogger(__name__)

@dataclass
class RouterConfig:
    """Configuration for router implementations."""
    timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0
    circuit_breaker_failures: int = 5
    circuit_breaker_timeout: float = 30.0

class Router(ABC):
    """Abstract base class for task routing implementations."""
    
    @abstractmethod
    async def route_and_execute(self, 
                              payload: Union[TaskPayload, Dict[str, Any]], 
                              correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Route and execute a task.
        
        Args:
            payload: Task payload to route and execute
            correlation_id: Optional correlation ID for tracking
            
        Returns:
            Task execution result with unified schema
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """Check router health."""
        pass
    
    @abstractmethod
    async def close(self):
        """Close router resources."""
        pass

class CoordinatorHttpRouter(Router):
    """HTTP-based router that calls Coordinator service via HTTP."""
    
    def __init__(self, 
                 base_url: Optional[str] = None,
                 config: Optional[RouterConfig] = None):
        self.config = config or RouterConfig()
        
        # Use centralized gateway discovery
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY
                base_url = f"{SERVE_GATEWAY}/pipeline"
            except Exception:
                base_url = "http://127.0.0.1:8000/pipeline"
        
        # Configure circuit breaker for coordinator service
        circuit_breaker = CircuitBreaker(
            failure_threshold=self.config.circuit_breaker_failures,
            recovery_timeout=self.config.circuit_breaker_timeout,
            expected_exception=(Exception,)  # Catch all exceptions
        )
        
        # Configure retry for coordinator service
        retry_config = RetryConfig(
            max_attempts=self.config.max_retries,
            base_delay=self.config.retry_delay,
            max_delay=self.config.retry_delay * 4
        )
        
        self.client = BaseServiceClient(
            service_name="coordinator_router",
            base_url=base_url,
            timeout=self.config.timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config
        )
        
        logger.info(f"CoordinatorHttpRouter initialized with base_url: {base_url}")
    
    async def route_and_execute(self, 
                              payload: Union[TaskPayload, Dict[str, Any]], 
                              correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """Route task through Coordinator HTTP API."""
        try:
            # Convert TaskPayload to dict if needed
            if isinstance(payload, TaskPayload):
                task_data = payload.model_dump()
            else:
                task_data = payload
            
            # Add correlation ID if provided
            if correlation_id:
                task_data["correlation_id"] = correlation_id
            
            logger.debug(f"Routing task via Coordinator HTTP: {task_data.get('task_id', 'unknown')}")
            
            # Call Coordinator's process-task endpoint
            result = await self.client.post("/process-task", json=task_data)
            
            logger.debug(f"Received result from Coordinator: {result}")
            return result
            
        except Exception as e:
            logger.error(f"CoordinatorHttpRouter failed to route task: {e}")
            # Return error in expected format
            return {
                "success": False,
                "error": str(e),
                "path": "coordinator_http_error"
            }
    
    async def health_check(self) -> Dict[str, Any]:
        """Check Coordinator service health."""
        try:
            return await self.client.health_check()
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "router_type": "coordinator_http"
            }
    
    async def close(self):
        """Close HTTP client."""
        await self.client.close()

class OrganismRouter(Router):
    """Fast-path router that calls Organism service directly for routing."""
    
    def __init__(self, 
                 base_url: Optional[str] = None,
                 config: Optional[RouterConfig] = None):
        self.config = config or RouterConfig()
        
        # Use centralized gateway discovery
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY
                base_url = f"{SERVE_GATEWAY}/organism"
            except Exception:
                base_url = "http://127.0.0.1:8000/organism"
        
        # Configure circuit breaker for organism service
        circuit_breaker = CircuitBreaker(
            failure_threshold=self.config.circuit_breaker_failures,
            recovery_timeout=self.config.circuit_breaker_timeout,
            expected_exception=(Exception,)
        )
        
        # Configure retry for organism service
        retry_config = RetryConfig(
            max_attempts=self.config.max_retries,
            base_delay=self.config.retry_delay,
            max_delay=self.config.retry_delay * 4
        )
        
        self.client = BaseServiceClient(
            service_name="organism_router",
            base_url=base_url,
            timeout=self.config.timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config
        )
        
        logger.info(f"OrganismRouter initialized with base_url: {base_url}")
    
    async def route_and_execute(self, 
                              payload: Union[TaskPayload, Dict[str, Any]], 
                              correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """Route task through Organism service for fast-path execution."""
        try:
            # Convert TaskPayload to dict if needed
            if isinstance(payload, TaskPayload):
                task_data = payload.model_dump()
            else:
                task_data = payload
            
            # Add correlation ID if provided
            if correlation_id:
                task_data["correlation_id"] = correlation_id
            
            logger.debug(f"Routing task via Organism: {task_data.get('task_id', 'unknown')}")
            
            # First resolve the route
            route_result = await self.client.post("/resolve-route", json={"task": task_data})
            
            if not route_result.get("success", False):
                return {
                    "success": False,
                    "error": f"Route resolution failed: {route_result.get('error', 'Unknown error')}",
                    "path": "organism_route_error"
                }
            
            # Get the target organ ID
            organ_id = route_result.get("organ_id")
            if not organ_id:
                return {
                    "success": False,
                    "error": "No organ ID returned from route resolution",
                    "path": "organism_no_organ"
                }
            
            # Execute the task on the target organ
            execute_result = await self.client.post(f"/organs/{organ_id}/execute", json=task_data)
            
            logger.debug(f"Received result from Organism: {execute_result}")
            return execute_result
            
        except Exception as e:
            logger.error(f"OrganismRouter failed to route task: {e}")
            # Return error in expected format
            return {
                "success": False,
                "error": str(e),
                "path": "organism_error"
            }
    
    async def health_check(self) -> Dict[str, Any]:
        """Check Organism service health."""
        try:
            return await self.client.health_check()
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "router_type": "organism"
            }
    
    async def close(self):
        """Close HTTP client."""
        await self.client.close()

class RouterFactory:
    """Factory for creating router instances based on configuration."""
    
    @staticmethod
    def create_router(router_type: Optional[str] = None, 
                     config: Optional[RouterConfig] = None) -> Router:
        """
        Create a router instance based on configuration.
        
        Args:
            router_type: Type of router ('coordinator_http', 'organism', 'auto')
            config: Router configuration
            
        Returns:
            Configured router instance
        """
        if router_type is None:
            router_type = os.getenv("DISPATCHER_ROUTER_TYPE", "coordinator_http")
        
        if config is None:
            config = RouterConfig(
                timeout=float(os.getenv("DISPATCHER_ROUTER_TIMEOUT", "30.0")),
                max_retries=int(os.getenv("DISPATCHER_ROUTER_MAX_RETRIES", "3")),
                retry_delay=float(os.getenv("DISPATCHER_ROUTER_RETRY_DELAY", "1.0")),
                circuit_breaker_failures=int(os.getenv("DISPATCHER_ROUTER_CB_FAILURES", "5")),
                circuit_breaker_timeout=float(os.getenv("DISPATCHER_ROUTER_CB_TIMEOUT", "30.0"))
            )
        
        logger.info(f"Creating router of type: {router_type}")
        
        if router_type == "coordinator_http":
            return CoordinatorHttpRouter(config=config)
        elif router_type == "organism":
            return OrganismRouter(config=config)
        elif router_type == "auto":
            # Auto-select based on environment or service availability
            try:
                # Try organism first for fast path
                return OrganismRouter(config=config)
            except Exception:
                # Fallback to coordinator
                logger.warning("Organism router failed, falling back to Coordinator")
                return CoordinatorHttpRouter(config=config)
        else:
            raise ValueError(f"Unknown router type: {router_type}")
    
    @staticmethod
    async def create_router_with_health_check(router_type: Optional[str] = None,
                                            config: Optional[RouterConfig] = None) -> Router:
        """
        Create a router and verify it's healthy.
        
        Args:
            router_type: Type of router
            config: Router configuration
            
        Returns:
            Healthy router instance
            
        Raises:
            Exception: If router health check fails
        """
        router = RouterFactory.create_router(router_type, config)
        
        # Perform health check
        health = await router.health_check()
        if health.get("status") != "healthy":
            await router.close()
            raise Exception(f"Router health check failed: {health}")
        
        logger.info(f"Router {router_type} is healthy and ready")
        return router
