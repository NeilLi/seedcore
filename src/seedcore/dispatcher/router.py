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
from seedcore.utils.ray_utils import ensure_ray_initialized

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
                # Ray Serve application name is "coordinator" per serve status
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
            service_name="coordinator",
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
            
            logger.info(f"Routing task via Coordinator HTTP: {task_data.get('task_id', 'unknown')}")
            
            # Call Coordinator's process-task endpoint
            result = await self.client.post("/process-task", json=task_data)
            
            logger.info(f"Received result from Coordinator: {result}")
            # If router escalated with a proto_plan, execute via RayAgent and return that final result
            try:
                org_router = OrganismRouter(config=self.config)
                org_res = await org_router.route_and_execute(task_data, correlation_id=correlation_id)
                await org_router.close()
                return org_res
            except Exception as handoff_err:
                logger.warning(f"Agent handoff failed, returning original router result: {handoff_err}")
                # Fall through to return original result
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
                # Ray Serve application name is "organism" per serve status
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
            service_name="organism",
            base_url=base_url,
            timeout=self.config.timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config
        )

        # Cognitive client for escalation planning
        try:
            from seedcore.utils.ray_utils import SERVE_GATEWAY
            cognitive_base = f"{SERVE_GATEWAY}/cognitive"
        except Exception:
            cognitive_base = "http://127.0.0.1:8000/cognitive"

        self.cognitive_client = BaseServiceClient(
            service_name="cognitive",
            base_url=cognitive_base,
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

            # The Organism service does not return a boolean success flag here.
            # Treat presence of an error as failure; otherwise proceed if we have an organ id.
            if isinstance(route_result, dict) and route_result.get("error"):
                return {
                    "success": False,
                    "error": f"Route resolution failed: {route_result.get('error')}",
                    "path": "organism_route_error"
                }
            
            # Get the target organ ID (logical_id in new API)
            organ_id = route_result.get("organ_id") or route_result.get("logical_id")
            if not organ_id:
                return {
                    "success": False,
                    "error": "No organ ID returned from route resolution",
                    "path": "organism_no_organ"
                }
            
            # Execute the task on the target organ via new endpoint
            execute_payload = {
                "organ_id": organ_id,
                "task": task_data
            }
            execute_result = await self.client.post("/execute-on-organ", json=execute_payload)
            
            logger.debug(f"Received result from Organism: {execute_result}")

            # If organism escalated, plan with cognitive service and return that result
            try:
                if execute_result.get("kind") == "escalated":
                    # Ensure current_capabilities is a STRING for the /plan endpoint
                    raw_caps = task_data.get("current_capabilities") or task_data.get("capabilities")
                    if isinstance(raw_caps, dict):
                        lines = ["Agent capabilities:"]
                        for k, v in raw_caps.items():
                            lines.append(f"- {k}: {v}")
                        caps_str = "\n".join(lines)
                    else:
                        caps_str = str(raw_caps or "")

                    cog_request = {
                        "agent_id": task_data.get("agent_id", "router"),
                        "task_description": task_data.get("description", ""),
                        "current_capabilities": caps_str,
                        "available_tools": task_data.get("available_tools") or task_data.get("tools", {}),
                        # Prefer deep profile when escalated unless caller specified
                        "profile": task_data.get("profile", "deep")
                    }
                    plan_result = await self.cognitive_client.post("/plan", json=cog_request)
                    return plan_result
            except Exception as _:
                # Fall through to return original execute_result if escalation planning fails
                pass
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
