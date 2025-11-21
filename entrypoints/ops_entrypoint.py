#!/usr/bin/env python3
"""
Ops Service Entrypoint for SeedCore - Merged Application

This entrypoint creates a unified Ray Serve application that hosts:
- EventizerService: Text processing and classification
- FactManager: Policy-driven fact management with PKG integration
- StateService: Centralized state aggregation
- EnergyService: Energy calculations and optimization

All services are exposed under a single /ops route prefix with a lightweight
OpsGateway that fans in/out to each service via Ray Serve handles.
"""

import os
import sys
import json
from typing import Any, Dict

from fastapi import APIRouter, FastAPI, HTTPException, Request  # type: ignore[reportMissingImports]
from ray import serve  # type: ignore[reportMissingImports]
from starlette.requests import Request as StarletteRequest  # type: ignore[reportMissingImports]

# Type hint for Ray Serve handles
try:
    from ray.serve.handle import DeploymentHandle  # type: ignore[reportMissingImports]
except ImportError:
    # Fallback for older versions or if not available
    DeploymentHandle = Any

# Add the project root to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

from seedcore.logging_setup import ensure_serve_logger, setup_logging
from seedcore.services.eventizer_service import EventizerService as EventizerServiceImpl
from seedcore.services.state_service import state_app
from seedcore.services.energy_service import energy_app

setup_logging(app_name="seedcore.ops_service.driver")
logger = ensure_serve_logger("seedcore.ops_service", level="DEBUG")
# Note: StateService and EnergyService from seedcore.services have @serve.ingress(FastAPI())
# which would conflict with OpsGateway's docs. We create lightweight wrappers below instead.

# Models are handled internally by the service

# --- Configuration ---
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "serve")

# ---------- Serve Deployments (wrappers) ----------

@serve.deployment(route_prefix=None)  # No direct public route; called via handle
class EventizerService:
    """Ray Serve wrapper for EventizerService."""
    
    def __init__(self) -> None:
        self.impl = EventizerServiceImpl()
        self._initialized = False

    async def __call__(self, request: Request) -> Dict[str, Any]:
        """Health check endpoint."""
        return {"status": "healthy", "service": "eventizer"}

    async def initialize(self) -> None:
        """Initialize the underlying service."""
        if not self._initialized:
            await self.impl.initialize()
            self._initialized = True
            logger.info("EventizerService initialized")

    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process text through eventizer pipeline.
        
        Uses the dict interface which handles EventizerRequest construction
        and returns a dict representation of EventizerResponse.
        """
        try:
            if not self._initialized:
                await self.initialize()
            
            # Process through eventizer using dict interface
            # This handles EventizerRequest construction and returns dict response
            response = await self.impl.process_dict(payload)
            
            # Check if process_dict returned an error response
            if isinstance(response, dict) and response.get("success") is False:
                error_msg = response.get("error", "Unknown error")
                logger.error(f"Eventizer processing failed: {error_msg}")
                # Return error response in EventizerResponse format
                return {
                    "original_text": payload.get("text", ""),
                    "processed_text": payload.get("text", ""),
                    "event_tags": {
                        "event_types": [],
                        "keywords": [],
                        "entities": [],
                        "patterns": [],
                        "priority": 0,
                        "urgency": "normal"
                    },
                    "attributes": {},
                    "confidence": {
                        "overall_confidence": 0.0,
                        "confidence_level": "low",
                        "needs_ml_fallback": True,
                        "fallback_reasons": ["exception"],
                        "processing_notes": [error_msg]
                    },
                    "processing_time_ms": 0.0,
                    "patterns_applied": 0,
                    "pii_redacted": False,
                    "errors": [error_msg],
                    "success": False
                }
            
            # Response is already a dict (EventizerResponse.model_dump())
            return response
            
        except Exception as e:
            logger.exception(f"Eventizer processing failed: {e}")
            # Return error response matching EventizerResponse structure
            return {
                "original_text": payload.get("text", ""),
                "processed_text": payload.get("text", ""),
                "event_tags": {
                    "event_types": [],
                    "keywords": [],
                    "entities": [],
                    "patterns": [],
                    "priority": 0,
                    "urgency": "normal"
                },
                "attributes": {},
                "confidence": {
                    "overall_confidence": 0.0,
                    "confidence_level": "low",
                    "needs_ml_fallback": True,
                    "fallback_reasons": ["exception"],
                    "processing_notes": [str(e)]
                },
                "processing_time_ms": 0.0,
                "patterns_applied": 0,
                "pii_redacted": False,
                "errors": [str(e)],
                "success": False
            }

    async def health(self) -> Dict[str, Any]:
        """Health check."""
        return {
            "status": "healthy",
            "service": "eventizer",
            "initialized": self._initialized
        }


@serve.deployment(route_prefix=None)
class FactManager:
    """Ray Serve wrapper for FactManager."""
    
    def __init__(self) -> None:
        self.impl = None
        self._initialized = False

    async def __call__(self, request: Request) -> Dict[str, Any]:
        """Health check endpoint."""
        return {"status": "healthy", "service": "fact_manager"}

    async def initialize(self) -> None:
        """Initialize the underlying service."""
        if not self._initialized:
            # Note: FactManager requires a database session
            # This will be initialized when first used
            self._initialized = True
            logger.info("FactManager wrapper initialized")

    async def create_fact(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a basic fact."""
        try:
            if not self._initialized:
                await self.initialize()
            
            # For now, return a placeholder response
            # In a real implementation, this would use the FactManager
            return {
                "status": "created",
                "fact_id": "placeholder-id",
                "message": "Fact creation not yet implemented in wrapper"
            }
            
        except Exception as e:
            logger.error(f"Fact creation failed: {e}")
            raise HTTPException(status_code=500, detail=f"Fact creation failed: {str(e)}")

    async def query_facts(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Query facts."""
        try:
            if not self._initialized:
                await self.initialize()
            
            # For now, return a placeholder response
            return {
                "status": "success",
                "facts": [],
                "count": 0,
                "message": "Fact querying not yet implemented in wrapper"
            }
            
        except Exception as e:
            logger.error(f"Fact query failed: {e}")
            raise HTTPException(status_code=500, detail=f"Fact query failed: {str(e)}")

    async def health(self) -> Dict[str, Any]:
        """Health check."""
        return {
            "status": "healthy",
            "service": "fact_manager",
            "initialized": self._initialized
        }

# ---------- HTTP Gateway (single public ingress) ----------

@serve.deployment
@serve.ingress(FastAPI())
class OpsGateway:
    """Unified gateway for all ops services - SINGLE FastAPI ingress for the ops application."""
    
    def __init__(self, 
                 eventizer_handle: DeploymentHandle,
                 facts_handle: DeploymentHandle,
                 state_handle: DeploymentHandle,
                 energy_handle: DeploymentHandle) -> None:
        
        # FastAPI app with explicit docs configuration
        # This is the ONLY ingress with docs in the ops application
        self.app = FastAPI(
            title="SeedCore Ops App",
            description="Unified application for EventizerService, FactManager, StateService, and EnergyService",
            version="1.0.0",
            docs_url="/docs",      # Explicit docs path
            redoc_url="/redoc",    # Explicit redoc path
            openapi_url="/openapi.json"  # Explicit OpenAPI schema path
        )
        
        self.eventizer = eventizer_handle
        self.facts = facts_handle
        self.state = state_handle
        self.energy = energy_handle

        # Create router for all ops endpoints
        router = APIRouter(prefix="")

        # Eventizer endpoints
        @router.post("/eventizer/process")
        async def process_eventizer(payload: Dict[str, Any]):
            """
            Process text through eventizer pipeline.
            
            Returns EventizerResponse as dict. Errors are returned as part of
            the response structure (with success=False) rather than HTTP errors,
            matching the eventizer_client.py interface.
            """
            try:
                result = await self.eventizer.process.remote(payload)
                # Service wrapper returns dict response (may contain error info)
                return result
            except Exception as e:
                # Only raise HTTPException for transport/deployment errors
                logger.error(f"Eventizer service call failed: {e}")
                raise HTTPException(status_code=500, detail=f"Service unavailable: {str(e)}")

        @router.get("/eventizer/health")
        async def eventizer_health():
            """Eventizer health check."""
            return await self.eventizer.health.remote()

        # Facts endpoints
        @router.post("/facts/create")
        async def facts_create(payload: Dict[str, Any]):
            """Create a fact."""
            try:
                result = await self.facts.create_fact.remote(payload)
                return result
            except Exception as e:
                logger.error(f"Fact creation failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.post("/facts/query")
        async def facts_query(payload: Dict[str, Any]):
            """Query facts."""
            try:
                result = await self.facts.query_facts.remote(payload)
                return result
            except Exception as e:
                logger.error(f"Fact query failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.get("/facts/health")
        async def facts_health():
            """Facts health check."""
            return await self.facts.health.remote()

        # State endpoints (matching state_client.py interface)
        # 
        # ARCHITECTURE: Distillation Engine
        # --------------------------------
        # The StateService's AgentAggregator acts as a "distillation engine":
        # - Raw Crude Oil: `_agent_snapshots` cache (multi-megabyte raw data)
        # - Refined Jet Fuel: `_system_metrics` cache (small, pre-computed aggregates)
        # 
        # The distillation happens in `AgentAggregator._compute_system_metrics()`,
        # which consumes `_agent_snapshots` and refines it into `_system_metrics`.
        # The real consumer of `_agent_snapshots` is the aggregator itself.
        
        @router.get("/state/system-metrics")
        async def state_system_metrics():
            """
            Get pre-computed system metrics from StateService.

            HOT PATH - Refined Jet Fuel for Production

            Returns the distilled, pre-computed aggregates optimized for real-time
            routing decisions. This is what the Coordinator and Energy Service use
            in production (O(1) lookup from cache).
            """
            try:
                # Call FastAPI endpoint via handle - use Request object pattern
                request_obj = StarletteRequest(
                    scope={
                        "type": "http",
                        "method": "GET",
                        "path": "/system-metrics",
                        "headers": [],
                        "query_string": b"",
                        "path_params": {},
                        "client": ("127.0.0.1", 0),
                        "server": ("127.0.0.1", 8000),
                    }
                )
                result = await self.state.__call__.remote(request_obj)
                return result
            except Exception as e:
                logger.error(f"State system metrics retrieval failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.get("/state/agent-snapshots")
        async def state_agent_snapshots():
            """
            Get full state snapshot for all agents from StateService.

            COLD PATH - Raw Crude Oil for Debugging/Analysis

            Returns the raw `_agent_snapshots` cache containing multi-megabyte
            data for every agent. This is the "crude oil" that gets distilled
            into `_system_metrics` by the AgentAggregator.

            IMPORTANT:
            - NOT for production use by Coordinator/Energy Service
            - Real consumer is the AgentAggregator itself (via `_compute_system_metrics()`)
            - At scale (millions of agents), this would be replaced by a data stream
              to a data lake/warehouse for offline analysis
            - Intended for debugging, development, and offline analysis only
            """
            try:
                # Call FastAPI endpoint via handle - use Request object pattern
                request_obj = StarletteRequest(
                    scope={
                        "type": "http",
                        "method": "GET",
                        "path": "/agent-snapshots",
                        "headers": [],
                        "query_string": b"",
                        "path_params": {},
                        "client": ("127.0.0.1", 0),
                        "server": ("127.0.0.1", 8000),
                    }
                )
                result = await self.state.__call__.remote(request_obj)
                return result
            except Exception as e:
                logger.error(f"State agent snapshots retrieval failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.get("/state/health")
        async def state_health():
            """State health check."""
            try:
                # Call FastAPI endpoint via handle - use Request object pattern
                request_obj = StarletteRequest(
                    scope={
                        "type": "http",
                        "method": "GET",
                        "path": "/health",
                        "headers": [],
                        "query_string": b"",
                        "path_params": {},
                        "client": ("127.0.0.1", 0),
                        "server": ("127.0.0.1", 8000),
                    }
                )
                result = await self.state.__call__.remote(request_obj)
                return result
            except Exception as e:
                logger.error(f"State health check failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        # Energy endpoints (matching energy_client.py interface)
        @router.get("/energy/metrics")
        async def energy_metrics():
            """Get current energy metrics from EnergyService ledger cache."""
            try:
                request_obj = StarletteRequest(
                    scope={
                        "type": "http",
                        "method": "GET",
                        "path": "/metrics",
                        "headers": [],
                        "query_string": b"",
                        "path_params": {},
                        "client": ("127.0.0.1", 0),
                        "server": ("127.0.0.1", 8000),
                    }
                )
                result = await self.energy.__call__.remote(request_obj)
                return result
            except Exception as e:
                logger.error(f"Energy metrics retrieval failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.get("/energy/compute-from-state")
        async def energy_compute_from_state():
            """On-demand energy computation from latest state."""
            try:
                request_obj = StarletteRequest(
                    scope={
                        "type": "http",
                        "method": "GET",
                        "path": "/compute-energy-from-state",
                        "headers": [],
                        "query_string": b"",
                        "path_params": {},
                        "client": ("127.0.0.1", 0),
                        "server": ("127.0.0.1", 8000),
                    }
                )
                result = await self.energy.__call__.remote(request_obj)
                return result
            except Exception as e:
                logger.error(f"Energy compute from state failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.post("/energy/compute")
        async def energy_compute(payload: Dict[str, Any]):
            """Compute energy from provided unified state."""
            try:
                body_bytes = json.dumps(payload).encode()
                request_obj = StarletteRequest(
                    scope={
                        "type": "http",
                        "method": "POST",
                        "path": "/compute-energy",
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body_bytes)).encode())],
                        "query_string": b"",
                        "path_params": {},
                        "client": ("127.0.0.1", 0),
                        "server": ("127.0.0.1", 8000),
                    }
                )
                # Attach JSON body
                request_obj._body = body_bytes
                result = await self.energy.__call__.remote(request_obj)
                return result
            except Exception as e:
                logger.error(f"Energy computation failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.post("/energy/optimize")
        async def energy_optimize(payload: Dict[str, Any]):
            """Optimize agent selection for a task."""
            try:
                body_bytes = json.dumps(payload).encode()
                request_obj = StarletteRequest(
                    scope={
                        "type": "http",
                        "method": "POST",
                        "path": "/optimize-agents",
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body_bytes)).encode())],
                        "query_string": b"",
                        "path_params": {},
                        "client": ("127.0.0.1", 0),
                        "server": ("127.0.0.1", 8000),
                    }
                )
                # Attach JSON body
                request_obj._body = body_bytes
                result = await self.energy.__call__.remote(request_obj)
                return result
            except Exception as e:
                logger.error(f"Energy optimization failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.post("/flywheel/result")
        async def flywheel_result(payload: Dict[str, Any]):
            """Post flywheel result to update ledger and adapt weights."""
            try:
                body_bytes = json.dumps(payload).encode()
                request_obj = StarletteRequest(
                    scope={
                        "type": "http",
                        "method": "POST",
                        "path": "/flywheel/result",
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body_bytes)).encode())],
                        "query_string": b"",
                        "path_params": {},
                        "client": ("127.0.0.1", 0),
                        "server": ("127.0.0.1", 8000),
                    }
                )
                # Attach JSON body
                request_obj._body = body_bytes
                result = await self.energy.__call__.remote(request_obj)
                return result
            except Exception as e:
                logger.error(f"Flywheel result posting failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.get("/energy/health")
        async def energy_health():
            """Energy health check."""
            try:
                request_obj = StarletteRequest(
                    scope={
                        "type": "http",
                        "method": "GET",
                        "path": "/health",
                        "headers": [],
                        "query_string": b"",
                        "path_params": {},
                        "client": ("127.0.0.1", 0),
                        "server": ("127.0.0.1", 8000),
                    }
                )
                result = await self.energy.__call__.remote(request_obj)
                return result
            except Exception as e:
                logger.error(f"Energy health check failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        # Global health endpoint
        @router.get("/health")
        async def ops_health():
            """Overall ops application health."""
            try:
                # Check all services
                eventizer_health = await self.eventizer.health.remote()
                facts_health = await self.facts.health.remote()
                # State and Energy services use FastAPI, call via Request pattern
                state_request = StarletteRequest(
                    scope={
                        "type": "http",
                        "method": "GET",
                        "path": "/health",
                        "headers": [],
                        "query_string": b"",
                        "path_params": {},
                        "client": ("127.0.0.1", 0),
                        "server": ("127.0.0.1", 8000),
                    }
                )
                energy_request = StarletteRequest(
                    scope={
                        "type": "http",
                        "method": "GET",
                        "path": "/health",
                        "headers": [],
                        "query_string": b"",
                        "path_params": {},
                        "client": ("127.0.0.1", 0),
                        "server": ("127.0.0.1", 8000),
                    }
                )
                state_health = await self.state.__call__.remote(state_request)
                energy_health = await self.energy.__call__.remote(energy_request)
                
                return {
                    "status": "healthy",
                    "application": "ops",
                    "services": {
                        "eventizer": eventizer_health,
                        "facts": facts_health,
                        "state": state_health,
                        "energy": energy_health
                    }
                }
            except Exception as e:
                logger.error(f"Health check failed: {e}")
                return {
                    "status": "unhealthy",
                    "application": "ops",
                    "error": str(e)
                }

        # Include all routes
        self.app.include_router(router)

    # FastAPI needs to reference the ASGI app via @serve.ingress
    # The app is already configured in __init__


# ---------- Application Builder ----------

def build_ops_app(args: dict = None) -> serve.Deployment:
    """
    Ray Serve application builder for the unified ops service.
    
    Args:
        args: Optional configuration dictionary (required by Ray Serve API)
    
    Returns:
        The bound OpsGateway deployment with all service handles wired.
    """
    
    logger.info("Building ops application with unified services")
    
    # Bind individual service deployments
    # All services are lightweight wrappers with NO FastAPI ingress
    # Only OpsGateway has @serve.ingress(FastAPI()) to avoid docs conflicts
    eventizer = EventizerService.bind()
    facts = FactManager.bind()

    # Wire gateway with handles - OpsGateway is the ONLY public ingress
    gateway = OpsGateway.bind(
        eventizer_handle=eventizer,
        facts_handle=facts,
        state_handle=state_app,
        energy_handle=energy_app,
    )
    
    logger.info("Ops application built successfully with single ingress (OpsGateway)")
    return gateway


def main():
    """Standalone runner for testing."""
    logger.info("🚀 Starting Ops Application (standalone mode)...")
    
    try:
        # This would normally be handled by Ray Serve
        logger.info("Ops application configured for Ray Serve deployment")
        logger.info("Use 'ray serve start' or RayService YAML to deploy")
        
    except Exception as e:
        logger.error(f"Failed to start ops application: {e}")
        raise


if __name__ == "__main__":
    main()
