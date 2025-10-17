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

# Ensure DSP logging is patched before any DSP/DSPy import via transitive imports
import sys as _sys
_sys.path.insert(0, '/app/docker')
try:
    import dsp_patch  # type: ignore
except Exception:
    pass

import json
import logging
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from enum import Enum
from typing import Dict, Any, Optional, List, Protocol, Callable
from dataclasses import dataclass

from seedcore.logging_setup import ensure_serve_logger

logger = ensure_serve_logger("seedcore.CognitiveService", level="DEBUG")

## Using ray_utils for MLService base URL discovery happens inline where needed

# =============================================================================
# LLM Profile Management
# =============================================================================

class LLMProfile(Enum):
    """LLM profile types for different cognitive processing depths."""
    FAST = "fast"
    DEEP = "deep"

class LLMEngine(Protocol):
    """Protocol for LLM engine abstraction."""
    def configure_for_dspy(self) -> Any: ...

class _DSPyMLServiceLM:
    """
    Minimal LM shim for DSPy that delegates to MLServiceEngine.
    Only implements the methods DSPy actually calls during signatures.
    """
    def __init__(self, engine: 'MLServiceEngine'):
        self.engine = engine

    # DSPy calls this to get text generations
    def basic_request(self, prompt: str, **kwargs):
        # Return a dict that mirrors OpenAI-ish "text" content
        text = self.engine.generate(prompt, **kwargs)
        return {"text": text}

    # Optional: some versions call .__call__ for convenience
    def __call__(self, prompt: str, **kwargs):
        return self.basic_request(prompt, **kwargs)

class OpenAIEngine:
    """OpenAI LLM engine implementation."""
    def __init__(self, model: str, max_tokens: int = 1024):
        self.model = model
        self.max_tokens = max_tokens
    
    def configure_for_dspy(self):
        # This method is not used since the core handles DSPy configuration
        # Keeping for protocol compliance but core handles actual DSPy setup
        pass

class MLServiceEngine:
    """MLService engine implementation for local LLM inference using MLServiceClient."""
    def __init__(self, model: str, max_tokens: int = 1024, base_url: str = None):
        self.model = model
        self.max_tokens = max_tokens
        # Resolve base URL (env > ray_utils > localhost)
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            env_url = os.getenv("MLS_BASE_URL")
            if env_url:
                self.base_url = env_url.rstrip("/")
            else:
                try:
                    from seedcore.utils.ray_utils import ML
                    self.base_url = str(ML).rstrip("/")
                except Exception:
                    self.base_url = "http://127.0.0.1:8000/ml"
        
        # Import and initialize MLServiceClient
        from seedcore.serve.ml_client import MLServiceClient
        self.client = MLServiceClient(base_url=self.base_url)
    
    def configure_for_dspy(self):
        # This method is not used since the core handles DSPy configuration
        # Keeping for protocol compliance but core handles actual DSPy setup
        pass
    
    async def generate_async(self, prompt: str, **kwargs) -> str:
        """Generate text using MLServiceClient."""
        try:
            # Convert prompt to chat format
            messages = [{"role": "user", "content": prompt}]
            
            # Merge max_tokens from kwargs or use instance default
            generation_params = {
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                **kwargs
            }
            
            # Call MLService via client
            response = await self.client.chat(
                model=self.model,
                messages=messages,
                **generation_params
            )
            
            # Extract response text from OpenAI-compatible format
            if "choices" in response and len(response["choices"]) > 0:
                return response["choices"][0]["message"]["content"]
            else:
                logger.error(f"Unexpected response format from MLService: {response}")
                return "Error: Invalid response from MLService"
                
        except Exception as e:
            logger.error(f"Error generating text with MLService: {e}")
            return f"Error: {str(e)}"
    
    def generate(self, prompt: str, **kwargs) -> str:
        """Synchronous wrapper for generate_async."""
        import anyio
        return anyio.run(self.generate_async, prompt, **kwargs)

@dataclass
class CircuitBreakerState:
    """Circuit breaker state tracking."""
    failure_count: int = 0
    last_failure_time: float = 0
    state: str = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    failure_threshold: int = 5
    recovery_timeout: float = 30.0

class CircuitBreaker:
    """Simple circuit breaker implementation."""
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.state = CircuitBreakerState(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout
        )
        self._lock = threading.Lock()
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection."""
        with self._lock:
            if self.state.state == "OPEN":
                if time.time() - self.state.last_failure_time > self.state.recovery_timeout:
                    self.state.state = "HALF_OPEN"
                else:
                    raise Exception("Circuit breaker is OPEN")
        
        try:
            result = func(*args, **kwargs)
            # Success - reset failure count
            with self._lock:
                self.state.failure_count = 0
                self.state.state = "CLOSED"
            return result
        except Exception as e:
            with self._lock:
                self.state.failure_count += 1
                self.state.last_failure_time = time.time()
                if self.state.failure_count >= self.state.failure_threshold:
                    self.state.state = "OPEN"
            raise e

# Import core types and logic
from ..cognitive.cognitive_core import (
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
    Service layer integration for cognitive operations with LLM profile management.
    
    This class provides service-level integration for cognitive operations,
    managing multiple CognitiveCore instances for different LLM profiles (FAST/DEEP)
    while handling service-level concerns like telemetry, health checks, and service management.
    """
    
    def __init__(self, ocps_client=None, profiles: Optional[Dict[LLMProfile, dict]] = None):
        self.ocps_client = ocps_client
        self.schema_version = "v2.0"
        
        # Thread pool for timeout enforcement
        self._executor = ThreadPoolExecutor(max_workers=4)
        
        # Get provider preference from environment
        default_provider = os.getenv("LLM_PROVIDER", "openai").lower()
        # Resolve MLService base URL once for profiles (env > ray_utils > localhost)
        env_url = os.getenv("MLS_BASE_URL")
        if env_url:
            mlservice_base_url = env_url.rstrip("/")
        else:
            try:
                from seedcore.utils.ray_utils import ML
                mlservice_base_url = str(ML).rstrip("/")
            except Exception:
                mlservice_base_url = "http://127.0.0.1:8000/ml"
        
        # Default LLM profiles; can be overridden via config
        self.profiles = profiles or self._get_default_profiles(default_provider, mlservice_base_url)
        
        # Initialize cores for each profile
        self.cores: Dict[LLMProfile, CognitiveCore] = {}
        self.circuit_breakers: Dict[LLMProfile, CircuitBreaker] = {}
        self._initialize_cores()
        
        # Legacy single core for backward compatibility
        self.cognitive_core = self.cores.get(LLMProfile.FAST)
    
    def _get_default_profiles(self, provider: str, mlservice_base_url: str) -> Dict[LLMProfile, dict]:
        """Get default profile configurations based on provider preference."""
        if provider == "mlservice":
            return {
                LLMProfile.FAST: {
                    "provider": "mlservice", 
                    "model": "llama3-8b-instruct-q4", 
                    "max_tokens": 1024,
                    "timeout_seconds": 5,
                    "base_url": mlservice_base_url
                },
                LLMProfile.DEEP: {
                    "provider": "mlservice", 
                    "model": "llama3-70b-instruct", 
                    "max_tokens": 2048,
                    "timeout_seconds": 20,
                    "base_url": mlservice_base_url
                },
            }
        else:  # Default to OpenAI
            return {
                LLMProfile.FAST: {
                    "provider": "openai", 
                    "model": "gpt-4o-mini", 
                    "max_tokens": 1024,
                    "timeout_seconds": 5
                },
                LLMProfile.DEEP: {
                    "provider": "openai", 
                    "model": "gpt-4o", 
                    "max_tokens": 2048,
                    "timeout_seconds": 20
                },
            }

    def _initialize_cores(self):
        """Initialize CognitiveCore instances for each LLM profile."""
        for profile, config in self.profiles.items():
            try:
                # Create engine based on provider
                if config["provider"] == "openai":
                    engine = OpenAIEngine(
                        model=config["model"], 
                        max_tokens=config.get("max_tokens", 1024)
                    )
                elif config["provider"] == "mlservice":
                    engine = MLServiceEngine(
                        model=config["model"], 
                        max_tokens=config.get("max_tokens", 1024),
                        base_url=config.get("base_url")
                    )
                else:
                    raise ValueError(f"Unsupported provider: {config['provider']}")
                
                # Initialize core with this engine
                core = self._create_core_with_engine(engine, config)
                self.cores[profile] = core
                
                # Initialize circuit breaker for this profile
                self.circuit_breakers[profile] = CircuitBreaker(
                    failure_threshold=3,  # Trip after 3 consecutive failures
                    recovery_timeout=60.0  # 1 minute recovery time
                )
                
                logger.info(f"Initialized {profile.value} core with {config['model']}")
                
            except Exception as e:
                logger.error(f"Failed to initialize {profile.value} core: {e}")
                # Continue with other profiles even if one fails
                continue

    def _create_core_with_engine(self, engine: LLMEngine, config: dict) -> CognitiveCore:
        """
        Create an isolated CognitiveCore instance for a profile.
        Also configures DSPy to use the right LM for this profile.
        """
        import dspy

        provider = config["provider"]
        model = config["model"]
        max_tokens = config.get("max_tokens", 1024)

        if provider == "openai":
            lm = dspy.OpenAI(model=model, max_tokens=max_tokens)
        elif provider == "mlservice":
            # Minimal DSPy adapter over your MLService engine
            lm = _DSPyMLServiceLM(engine)  # type: ignore
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        # Configure DSPy for this profile
        dspy.settings.configure(lm=lm)
        
        # Build a fresh core (no singleton) - import CognitiveCore directly
        from ..cognitive.cognitive_core import CognitiveCore
        return CognitiveCore(
            llm_provider=provider, 
            model=model, 
            context_broker=None, 
            ocps_client=self.ocps_client
        )

    def plan(self, context: CognitiveContext, depth: LLMProfile = LLMProfile.FAST) -> Dict[str, Any]:
        """
        Plan cognitive tasks using the specified LLM profile with timeout and circuit breaker protection.
        
        Args:
            context: Cognitive context for the task
            depth: LLM profile to use (FAST or DEEP)
            
        Returns:
            Planning result with solution_steps and metadata
        """
        core = self.cores.get(depth)
        circuit_breaker = self.circuit_breakers.get(depth)
        
        if core is None:
            # Fallback to FAST if requested profile isn't available
            core = self.cores.get(LLMProfile.FAST)
            circuit_breaker = self.circuit_breakers.get(LLMProfile.FAST)
            if core is None:
                return create_error_result(
                    f"No cognitive core available for profile {depth.value}", 
                    "SERVICE_UNAVAILABLE"
                ).to_dict()
        
        timeout_seconds = self.profiles.get(depth, {}).get("timeout_seconds", 10)
        
        def _execute_with_timeout():
            """Execute the planning with real timeout enforcement."""
            future = self._executor.submit(core.forward, context)
            try:
                return future.result(timeout=timeout_seconds)
            except FuturesTimeoutError:
                raise TimeoutError(f"LLM planning timed out after {timeout_seconds}s")
        
        try:
            # Use circuit breaker if available
            if circuit_breaker:
                result = circuit_breaker.call(_execute_with_timeout)
            else:
                result = _execute_with_timeout()
            
            # Add profile metadata to result - safe meta merge
            if isinstance(result, dict):
                result.setdefault("result", {}).setdefault("meta", {})
                meta = result["result"]["meta"]
                meta["profile_used"] = depth.value
                meta["timeout_seconds"] = timeout_seconds
                meta["circuit_breaker_state"] = circuit_breaker.state.state if circuit_breaker else "N/A"
            
            return result
            
        except Exception as e:
            logger.error(f"Error in {depth.value} planning: {e}")
            error_msg = f"Planning error: {str(e)}"
            if circuit_breaker and circuit_breaker.state.state == "OPEN":
                error_msg += " (Circuit breaker OPEN)"
            return create_error_result(error_msg, "PROCESSING_ERROR").to_dict()

    def plan_with_escalation(self, context: CognitiveContext) -> Dict[str, Any]:
        """
        Plan with automatic escalation: try FAST first, then DEEP if escalate_hint is True.
        
        Args:
            context: Cognitive context for the task
            
        Returns:
            Planning result from FAST or DEEP profile
        """
        # Try FAST first
        fast_result = self.plan(context, depth=LLMProfile.FAST)
        
        # Check if escalation is suggested
        if isinstance(fast_result, dict) and "result" in fast_result:
            meta = fast_result["result"].get("meta", {})
            if meta.get("escalate_hint", False):
                logger.info(f"Escalation suggested, trying DEEP profile for task {context.task_type.value}")
                deep_result = self.plan(context, depth=LLMProfile.DEEP)
                
                # Add escalation metadata
                if isinstance(deep_result, dict) and "result" in deep_result:
                    deep_result["result"]["meta"] = deep_result["result"].get("meta", {})
                    deep_result["result"]["meta"]["escalated_from_fast"] = True
                    deep_result["result"]["meta"]["fast_escalate_hint"] = True
                
                return deep_result
        
        # Return FAST result (no escalation needed)
        return fast_result

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
            return self.cognitive_core.forward(context)
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
            from ..cognitive.cognitive_core import reset_cognitive_core
            reset_cognitive_core()
            self.cognitive_core = None
            logger.info("Cognitive core reset")
    
    def shutdown(self):
        """Shutdown the service and cleanup resources."""
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=True)
            logger.info("Thread pool executor shutdown")

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
    "CognitiveContext",
    "LLMProfile",
    "LLMEngine",
    "OpenAIEngine",
    "MLServiceEngine"
]