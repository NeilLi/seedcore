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
import logging
from typing import Any, Dict, Optional

import ray
from ray import serve
from fastapi import FastAPI, APIRouter, HTTPException, Request

# Type hint for Ray Serve handles
try:
    from ray.serve.handle import DeploymentHandle
except ImportError:
    # Fallback for older versions or if not available
    DeploymentHandle = Any

# Add the project root to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

from seedcore.logging_setup import setup_logging
setup_logging(app_name="seedcore.ops")
logger = logging.getLogger("seedcore.ops")

# Import service implementations
from seedcore.services.eventizer_service import EventizerService as EventizerServiceImpl
from seedcore.services.fact_manager import FactManager as FactManagerImpl
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
        """Process text through eventizer pipeline."""
        try:
            if not self._initialized:
                await self.initialize()
            
            # Process through eventizer using dict interface
            response = await self.impl.process_dict(payload)
            
            # Response is already a dict
            return response
            
        except Exception as e:
            logger.error(f"Eventizer processing failed: {e}")
            raise HTTPException(status_code=500, detail=f"Eventizer processing failed: {str(e)}")

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


# Lightweight wrappers for StateService and EnergyService
# These do NOT use @serve.ingress to avoid FastAPI docs conflicts with OpsGateway

@serve.deployment(route_prefix=None)
class StateService:
    """Lightweight state service wrapper - no FastAPI ingress to avoid docs conflicts."""
    
    def __init__(self) -> None:
        self._initialized = True
        logger.info("StateService wrapper initialized (lightweight, no ingress)")

    async def __call__(self, request: Request) -> Dict[str, Any]:
        """Health check endpoint."""
        return {"status": "healthy", "service": "state"}

    async def get_state(self, key: str = "unified") -> Dict[str, Any]:
        """Get system state - placeholder implementation."""
        return {
            "key": key,
            "state": {},
            "timestamp": "placeholder",
            "message": "Lightweight wrapper - implement state collection here"
        }

    async def health(self) -> Dict[str, Any]:
        """Health check."""
        return {"status": "healthy", "service": "state", "initialized": self._initialized}


@serve.deployment(route_prefix=None)
class EnergyService:
    """Lightweight energy service wrapper - no FastAPI ingress to avoid docs conflicts."""
    
    def __init__(self) -> None:
        self._initialized = True
        logger.info("EnergyService wrapper initialized (lightweight, no ingress)")

    async def __call__(self, request: Request) -> Dict[str, Any]:
        """Health check endpoint."""
        return {"status": "healthy", "service": "energy"}

    async def compute_energy(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Compute energy - placeholder implementation."""
        return {
            "total_energy": 0.0,
            "breakdown": {},
            "timestamp": "placeholder",
            "message": "Lightweight wrapper - implement energy calculation here"
        }

    async def health(self) -> Dict[str, Any]:
        """Health check."""
        return {"status": "healthy", "service": "energy", "initialized": self._initialized}


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
            """Process text through eventizer pipeline."""
            try:
                result = await self.eventizer.process.remote(payload)
                return result
            except Exception as e:
                logger.error(f"Eventizer processing failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

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

        # State endpoints
        @router.get("/state")
        async def state_get(key: str = "unified"):
            """Get system state."""
            try:
                result = await self.state.get_state.remote(key)
                return result
            except Exception as e:
                logger.error(f"State retrieval failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.get("/state/agent/{agent_id}")
        async def state_get_agent(agent_id: str):
            """Get agent-specific state."""
            try:
                result = await self.state.get_agent_state.remote(agent_id)
                return result
            except Exception as e:
                logger.error(f"Agent state retrieval failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.get("/state/health")
        async def state_health():
            """State health check."""
            return await self.state.health.remote()

        # Energy endpoints
        @router.get("/energy/summary")
        async def energy_summary():
            """Get energy summary."""
            try:
                result = await self.energy.get_energy_summary.remote()
                return result
            except Exception as e:
                logger.error(f"Energy summary retrieval failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.get("/energy/metrics")
        async def energy_metrics(window: str = "1h"):
            """Get energy metrics."""
            try:
                result = await self.energy.get_energy_metrics.remote(window)
                return result
            except Exception as e:
                logger.error(f"Energy metrics retrieval failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @router.get("/energy/health")
        async def energy_health():
            """Energy health check."""
            return await self.energy.health.remote()

        # Global health endpoint
        @router.get("/health")
        async def ops_health():
            """Overall ops application health."""
            try:
                # Check all services
                eventizer_health = await self.eventizer.health.remote()
                facts_health = await self.facts.health.remote()
                state_health = await self.state.health.remote()
                energy_health = await self.energy.health.remote()
                
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
    state = StateService.bind()
    energy = EnergyService.bind()

    # Wire gateway with handles - OpsGateway is the ONLY public ingress
    gateway = OpsGateway.bind(
        eventizer_handle=eventizer,
        facts_handle=facts,
        state_handle=state,
        energy_handle=energy,
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
