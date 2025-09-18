"""
Cognitive Service: Integration layer for cognitive operations.

This module provides service-layer integration for cognitive operations,
delegating to the core cognitive logic while providing telemetry and
service management capabilities.

Key Features:
- Service layer integration and telemetry
- Delegates to CognitiveCore for core logic
- Provides service management and monitoring
- Handles service-level concerns like health checks

Note: This is the service layer that integrates with telemetry and other services.
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List

from seedcore.logging_setup import setup_logging

setup_logging("seedcore.CognitiveService")
logger = logging.getLogger("seedcore.CognitiveService")

# Import core types and logic
from ..agents.cognitive_core import (
    CognitiveCore, ContextBroker, Fact, RetrievalSufficiency, 
    CognitiveTaskType, CognitiveContext, initialize_cognitive_core, get_cognitive_core
)

# Import the new centralized result schema
from ..models.result_schema import (
    create_cognitive_result, create_error_result, TaskResult
)


# =============================================================================
# Cognitive Service Integration Layer
# =============================================================================

class CognitiveService:
    """
    Service layer integration for cognitive operations.
    
    This class provides service-level integration for cognitive operations,
    delegating to the CognitiveCore for core logic while handling service-level
    concerns like telemetry, health checks, and service management.
    """
    
    def __init__(self, ocps_client=None):
        self.ocps_client = ocps_client
        self.cognitive_core = None
        self.schema_version = "v2.0"
        
        # Initialize the cognitive core
        try:
            self.cognitive_core = get_cognitive_core()
            if self.cognitive_core is None:
                self.cognitive_core = initialize_cognitive_core(ocps_client=self.ocps_client)
            else:
                # Set ocps_client on existing instance
                try:
                    self.cognitive_core.ocps_client = self.ocps_client
                except Exception:
                    pass
            logger.info("CognitiveService initialized with CognitiveCore")
        except Exception as e:
            logger.error(f"Failed to initialize CognitiveCore: {e}")
            self.cognitive_core = None

    def health_check(self) -> Dict[str, Any]:
        """Perform health check on the cognitive service."""
        try:
            if self.cognitive_core is None:
                return {
                    "status": "unhealthy",
                    "reason": "CognitiveCore not initialized",
                    "timestamp": time.time()
                }
            
            # Basic health check - could be extended with more checks
            return {
                "status": "healthy",
                "cognitive_core_available": True,
                "schema_version": self.schema_version,
                "timestamp": time.time()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "reason": f"Health check failed: {str(e)}",
                "timestamp": time.time()
            }

    def process_cognitive_task(self, context: CognitiveContext) -> Dict[str, Any]:
        """Process a cognitive task by delegating to the core."""
        if self.cognitive_core is None:
            return create_error_result("CognitiveCore not initialized", "SERVICE_UNAVAILABLE").to_dict()
        
        try:
            return self.cognitive_core.process(context)
        except Exception as e:
            logger.error(f"Error processing cognitive task: {e}")
            return create_error_result(f"Processing error: {str(e)}", "PROCESSING_ERROR").to_dict()

    def forward_cognitive_task(self, context: CognitiveContext) -> Dict[str, Any]:
        """Forward a cognitive task by delegating to the core."""
        if self.cognitive_core is None:
            return {
                "success": False,
                "result": {},
                "payload": {},
                "task_type": context.task_type.value,
                "metadata": {},
                "error": "CognitiveCore not initialized",
            }
        
        try:
            return self.cognitive_core.forward(context)
        except Exception as e:
            logger.error(f"Error forwarding cognitive task: {e}")
            return {
                "success": False,
                "result": {},
                "payload": {},
                "task_type": context.task_type.value,
                "metadata": {},
                "error": f"Processing error: {str(e)}",
            }

    def build_fragments_for_synthesis(self, context: CognitiveContext, facts: List[Fact], summary: str) -> List[Dict[str, Any]]:
        """Build memory-synthesis fragments by delegating to the core."""
        if self.cognitive_core is None:
            return []
        
        try:
            return self.cognitive_core.build_fragments_for_synthesis(context, facts, summary)
        except Exception as e:
            logger.error(f"Error building synthesis fragments: {e}")
            return []

    def get_cognitive_core(self) -> Optional[CognitiveCore]:
        """Get the underlying cognitive core instance."""
        return self.cognitive_core

    def reset_cognitive_core(self):
        """Reset the cognitive core instance."""
        if self.cognitive_core:
            from ..agents.cognitive_core import reset_cognitive_core
            reset_cognitive_core()
            self.cognitive_core = None
            logger.info("Cognitive core reset")

    def initialize_cognitive_core(self, llm_provider: str = "openai", model: str = "gpt-4o", context_broker: Optional[ContextBroker] = None) -> CognitiveCore:
        """Initialize or reinitialize the cognitive core."""
        try:
            self.cognitive_core = initialize_cognitive_core(llm_provider, model, context_broker)
            logger.info(f"Cognitive core reinitialized with {llm_provider} and {model}")
            return self.cognitive_core
        except Exception as e:
            logger.error(f"Failed to reinitialize cognitive core: {e}")
            raise


# =============================================================================
# Global Service Instance Management
# =============================================================================

COGNITIVE_SERVICE_INSTANCE: Optional[CognitiveService] = None


def initialize_cognitive_service(ocps_client=None) -> CognitiveService:
    """Initialize the global cognitive service instance."""
    global COGNITIVE_SERVICE_INSTANCE
    
    if COGNITIVE_SERVICE_INSTANCE is None:
        try:
            COGNITIVE_SERVICE_INSTANCE = CognitiveService(ocps_client=ocps_client)
            logger.info("Initialized global cognitive service")
        except Exception as e:
            logger.error(f"Failed to initialize cognitive service: {e}")
            raise
    
    return COGNITIVE_SERVICE_INSTANCE


def get_cognitive_service() -> Optional[CognitiveService]:
    """Get the global cognitive service instance."""
    return COGNITIVE_SERVICE_INSTANCE


def reset_cognitive_service():
    """Reset the global cognitive service instance (useful for testing)."""
    global COGNITIVE_SERVICE_INSTANCE
    if COGNITIVE_SERVICE_INSTANCE:
        COGNITIVE_SERVICE_INSTANCE.reset_cognitive_core()
    COGNITIVE_SERVICE_INSTANCE = None

# Re-export core types for decoupling
__all__ = [
    "CognitiveService", 
    "initialize_cognitive_service", 
    "get_cognitive_service", 
    "reset_cognitive_service",
    "CognitiveTaskType", 
    "CognitiveContext"
]