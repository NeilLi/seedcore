"""
Cognitive Service: Integration layer for cognitive operations.

Multi-provider enhancements:
- Deep profile defaults to OpenAI (LLM_PROVIDER=openai).
- Fast profile can be selected from a multi-provider pool (LLM_PROVIDERS=openai,anthropic,nim,...).
- Per-profile provider & model overrides via env.
- Backward compatible with SeedCore core & telemetry.
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

class _DSPyEngineShim:
    """
    Minimal DSPy LM shim that adapts any engine exposing .generate(prompt, **kwargs) -> str.
    Used for NimEngine and MLServiceEngine.
    """
    def __init__(self, engine: 'LLMEngine'):
        self.engine = engine

    def basic_request(self, prompt: str, **kwargs):
        text = self.engine.generate(prompt, **kwargs)
        return {"text": text}

    def __call__(self, prompt: str, **kwargs):
        return self.basic_request(prompt, **kwargs)

# ------------------ Provider engines ------------------

class OpenAIEngine:
    """OpenAI LLM engine implementation (DSPy config handled in core shim)."""
    def __init__(self, model: str, max_tokens: int = 1024):
        self.model = model
        self.max_tokens = max_tokens
    
    def configure_for_dspy(self):
        pass  # DSPy configured in _create_core_with_engine

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
        from seedcore.serve.ml_client import MLServiceClient
        self.client = MLServiceClient(base_url=self.base_url)
    
    def configure_for_dspy(self):
        pass
    
    async def generate_async(self, prompt: str, **kwargs) -> str:
        try:
            messages = [{"role": "user", "content": prompt}]
            generation_params = {
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                **{k: v for k, v in kwargs.items() if k != "max_tokens"}
            }
            response = await self.client.chat(
                model=self.model,
                messages=messages,
                **generation_params
            )
            if "choices" in response and len(response["choices"]) > 0:
                return response["choices"][0]["message"]["content"]
            logger.error(f"Unexpected response format from MLService: {response}")
            return "Error: Invalid response from MLService"
        except Exception as e:
            logger.error(f"Error generating text with MLService: {e}")
            return f"Error: {str(e)}"
    
    def generate(self, prompt: str, **kwargs) -> str:
        import anyio
        return anyio.run(self.generate_async, prompt, **kwargs)

from seedcore.ml.driver import get_driver as _get_nim_driver
# get_active_providers parses LLM_PROVIDERS (if you have the registry; otherwise falls back below)
try:
    from seedcore.utils.llm_registry import get_active_providers
except Exception:
    def get_active_providers() -> List[str]:
        v = os.getenv("LLM_PROVIDERS", "")
        return [p.strip().lower() for p in v.split(",") if p.strip()]

class NimEngine:
    """
    NIM (OpenAI-compatible) engine using SeedCore nim drivers (SDK or HTTP).
    Keeps the same .generate() contract as other engines.
    """
    def __init__(self, model: str, max_tokens: int = 1024,
                 base_url: Optional[str] = None, api_key: Optional[str] = None,
                 use_sdk: Optional[bool] = None, timeout: int = 60):
        self.model = model
        self.max_tokens = max_tokens
        base_url = (base_url or
                    os.getenv("NIM_LLM_BASE_URL") or
                    "http://127.0.0.1:8000/v1")
        api_key = api_key or os.getenv("NIM_LLM_API_KE", "none")
        self.driver = _get_nim_driver(
            use_sdk=use_sdk, base_url=base_url, api_key=api_key,
            model=model, timeout=timeout, auto_fallback=True,
        )

    def configure_for_dspy(self):
        pass

    async def generate_async(self, prompt: str, **kwargs) -> str:
        messages = [{"role": "user", "content": prompt}]
        params = {
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            **{k: v for k, v in kwargs.items() if k != "max_tokens"}
        }
        return self.driver.chat(messages, **params)

    def generate(self, prompt: str, **kwargs) -> str:
        import anyio
        return anyio.run(self.generate_async, prompt, **kwargs)

# =============================================================================
# Circuit breaker
# =============================================================================

@dataclass
class CircuitBreakerState:
    failure_count: int = 0
    last_failure_time: float = 0
    state: str = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    failure_threshold: int = 5
    recovery_timeout: float = 30.0

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.state = CircuitBreakerState(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout
        )
        self._lock = threading.Lock()
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        with self._lock:
            if self.state.state == "OPEN":
                if time.time() - self.state.last_failure_time > self.state.recovery_timeout:
                    self.state.state = "HALF_OPEN"
                else:
                    raise Exception("Circuit breaker is OPEN")
        try:
            result = func(*args, **kwargs)
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

# =============================================================================
# Core imports
# =============================================================================

from ..cognitive.cognitive_core import (
    CognitiveCore, ContextBroker, Fact, RetrievalSufficiency, 
    CognitiveTaskType, CognitiveContext, initialize_cognitive_core, get_cognitive_core
)

from ..models.result_schema import (
    create_cognitive_result, create_error_result, TaskResult
)

# =============================================================================
# Helpers: provider & model selection
# =============================================================================

def _first_non_empty(*vals: Optional[str]) -> Optional[str]:
    for v in vals:
        if v and str(v).strip():
            return str(v).strip()
    return None

def _normalize_list(val: Optional[str]) -> List[str]:
    return [x.strip().lower() for x in (val or "").split(",") if x.strip()]

def _default_provider_deep() -> str:
    """Resolve the default provider for the DEEP profile."""
    explicit = os.getenv("LLM_PROVIDER_DEEP")
    if explicit and explicit.strip():
        return explicit.strip().lower()
    return "openai"

def _default_provider_fast() -> str:
    # Fast uses explicit > first in LLM_PROVIDERS > global > openai
    explicit = os.getenv("LLM_PROVIDER_FAST")
    if explicit:
        return explicit.strip().lower()
    providers = get_active_providers() or _normalize_list(os.getenv("LLM_PROVIDERS"))
    if providers:
        return providers[0]
    return (_first_non_empty(os.getenv("LLM_PROVIDER"), "openai") or "openai").lower()

def _timeout(profile: LLMProfile, provider: str) -> int:
    # Allow global overrides; otherwise set sensible defaults by provider/profile
    if profile is LLMProfile.FAST:
        return int(os.getenv("FAST_TIMEOUT_SECONDS", "6" if provider in ("nim", "mlservice") else "5"))
    return int(os.getenv("DEEP_TIMEOUT_SECONDS", "25" if provider in ("nim", "mlservice") else "20"))

def _model_for(provider: str, profile: LLMProfile) -> str:
    pr = provider.lower()
    pf = profile.value  # "fast" | "deep"
    # Provider-specific env overrides then defaults
    if pr == "openai":
        return _first_non_empty(
            os.getenv("OPENAI_MODEL_DEEP" if pf=="deep" else "OPENAI_MODEL_FAST"),
            "gpt-4o" if pf=="deep" else "gpt-4o-mini"
        )
    if pr == "anthropic":
        return _first_non_empty(
            os.getenv("ANTHROPIC_MODEL_DEEP" if pf=="deep" else "ANTHROPIC_MODEL_FAST"),
            "claude-3-5-sonnet" if pf=="deep" else "claude-3-5-haiku"
        )
    if pr == "google":
        return _first_non_empty(
            os.getenv("GOOGLE_MODEL_DEEP" if pf=="deep" else "GOOGLE_MODEL_FAST"),
            "gemini-1.5-pro" if pf=="deep" else "gemini-1.5-flash"
        )
    if pr == "azure":
        # You may map deployment names separately; this keeps a sane default
        return _first_non_empty(
            os.getenv("AZURE_OPENAI_MODEL_DEEP" if pf=="deep" else "AZURE_OPENAI_MODEL_FAST"),
            "gpt-4o" if pf=="deep" else "gpt-4o-mini"
        )
    if pr == "nim":
        return _first_non_empty(
            os.getenv("SEEDCORE_NIM_MODEL_DEEP" if pf=="deep" else "SEEDCORE_NIM_MODEL_FAST"),
            "meta/llama-3.1-70b-instruct" if pf=="deep" else "meta/llama-3.1-8b-instruct"
        )
    if pr == "mlservice":
        return _first_non_empty(
            os.getenv("MLS_MODEL_DEEP" if pf=="deep" else "MLS_MODEL_FAST"),
            "llama3-70b-instruct" if pf=="deep" else "llama3-8b-instruct-q4"
        )
    # Unknown provider — fallback to openai defaults
    return "gpt-4o" if pf == "deep" else "gpt-4o-mini"

def _make_engine(provider: str, profile: LLMProfile, model: str):
    provider = provider.lower()
    max_tokens = 2048 if profile is LLMProfile.DEEP else 1024
    if provider == "openai":
        return OpenAIEngine(model=model, max_tokens=max_tokens)
    if provider == "mlservice":
        base_url = os.getenv("MLS_BASE_URL")
        if not base_url:
            try:
                from seedcore.utils.ray_utils import ML
                base_url = str(ML)
            except Exception:
                base_url = "http://127.0.0.1:8000/ml"
        return MLServiceEngine(model=model, max_tokens=max_tokens, base_url=base_url)
    if provider == "nim":
        return NimEngine(
            model=model,
            max_tokens=max_tokens,
            base_url=os.getenv("NIM_LLM_BASE_URL"),
            api_key=os.getenv("NIM_LLM_API_KE", "none"),
            use_sdk=None,
            timeout=_timeout(profile, provider),
        )
    if provider in ("anthropic", "google", "azure"):
        # These are handled via DSPy native integrations below in _create_core_with_engine
        return OpenAIEngine(model=model, max_tokens=max_tokens)  # placeholder for protocol
    raise ValueError(f"Unsupported provider: {provider}")

# =============================================================================
# Cognitive Service Integration Layer
# =============================================================================

class CognitiveService:
    """
    Service layer for cognitive operations with multi-provider, dual-profile (FAST/DEEP) support.

    Behavior:
      - DEEP provider defaults to OpenAI (LLM_PROVIDER=openai).
      - FAST provider chosen from LLM_PROVIDERS list, or falls back to LLM_PROVIDER/openai.
      - Per-profile provider/model overrides supported via env.
    """
    
    def __init__(self, ocps_client=None, profiles: Optional[Dict[LLMProfile, dict]] = None):
        self.ocps_client = ocps_client
        self.schema_version = "v2.0"
        self._executor = ThreadPoolExecutor(max_workers=4)

        # Resolve providers for both profiles
        deep_provider_resolved = _default_provider_deep()
        if deep_provider_resolved != "openai":
            logger.warning(
                "DEEP profile provider '%s' is not supported; forcing 'openai'",
                deep_provider_resolved,
            )
        deep_provider = "openai"
        fast_provider = (_first_non_empty(os.getenv("LLM_PROVIDER_FAST"), None) or _default_provider_fast()).lower()

        # Build default profile configs if not supplied
        self.profiles = profiles or {
            LLMProfile.FAST: {
                "provider": fast_provider,
                "model": _model_for(fast_provider, LLMProfile.FAST),
                "max_tokens": 1024,
                "timeout_seconds": _timeout(LLMProfile.FAST, fast_provider),
            },
            LLMProfile.DEEP: {
                "provider": deep_provider,
                "model": _model_for(deep_provider, LLMProfile.DEEP),
                "max_tokens": 2048,
                "timeout_seconds": _timeout(LLMProfile.DEEP, deep_provider),
            },
        }

        # Initialize cores & circuit breakers
        self.cores: Dict[LLMProfile, CognitiveCore] = {}
        self.circuit_breakers: Dict[LLMProfile, CircuitBreaker] = {}
        self._initialize_cores()
        
        # Legacy single core alias (FAST)
        self.cognitive_core = self.cores.get(LLMProfile.FAST)
    
    def _initialize_cores(self):
        for profile, config in self.profiles.items():
            try:
                provider = config["provider"].lower()
                model = config["model"]
                engine = _make_engine(provider, profile, model)
                core = self._create_core_with_engine(provider, engine, config)
                self.cores[profile] = core
                self.circuit_breakers[profile] = CircuitBreaker(
                    failure_threshold=3,
                    recovery_timeout=60.0
                )
                logger.info(f"Initialized {profile.value} core with provider={provider} model={model}")
            except Exception as e:
                logger.error(f"Failed to initialize {profile.value} core: {e}")
                continue

    def _create_core_with_engine(self, provider: str, engine: LLMEngine, config: dict) -> CognitiveCore:
        """
        Create an isolated CognitiveCore instance for a profile and configure DSPy LM accordingly.
        - openai / anthropic / google / azure use DSPy's native LMs.
        - nim / mlservice use the DSPy shim (_DSPyEngineShim).
        """
        import dspy

        provider = provider.lower()
        model = config["model"]
        max_tokens = config.get("max_tokens", 1024)

        if provider == "openai":
            lm = dspy.OpenAI(model=model, max_tokens=max_tokens)
        elif provider == "anthropic":
            # DSPy provides Anthropic integration as dspy.Claude (or generic)
            try:
                lm = dspy.Anthropic(model=model, max_tokens=max_tokens)  # if available in your DSPy version
            except Exception:
                lm = dspy.LM(provider="anthropic", model=model, max_tokens=max_tokens)
        elif provider == "google":
            try:
                lm = dspy.Google(model=model, max_tokens=max_tokens)  # Gemini wrapper if present
            except Exception:
                lm = dspy.LM(provider="google", model=model, max_tokens=max_tokens)
        elif provider == "azure":
            # Depending on DSPy version, you may supply endpoint/deployment via env
            lm = dspy.OpenAI(model=model, max_tokens=max_tokens)  # Azure OpenAI is OpenAI-compatible
        else:
            # nim / mlservice / others use shim to call your engine
            lm = _DSPyEngineShim(engine)  # type: ignore

        dspy.settings.configure(lm=lm)

        from ..cognitive.cognitive_core import CognitiveCore
        return CognitiveCore(
            llm_provider=provider, 
            model=model, 
            context_broker=None, 
            ocps_client=self.ocps_client
        )

    # ------------------ Orchestration methods ------------------

    def plan(self, context: 'CognitiveContext', depth: LLMProfile = LLMProfile.FAST) -> Dict[str, Any]:
        core = self.cores.get(depth)
        circuit_breaker = self.circuit_breakers.get(depth)
        if core is None:
            core = self.cores.get(LLMProfile.FAST)
            circuit_breaker = self.circuit_breakers.get(LLMProfile.FAST)
            if core is None:
                return create_error_result(
                    f"No cognitive core available for profile {depth.value}",
                    "SERVICE_UNAVAILABLE"
                ).model_dump()
        
        timeout_seconds = self.profiles.get(depth, {}).get("timeout_seconds", 10)

        def _execute_with_timeout():
            future = self._executor.submit(core.forward, context)
            try:
                return future.result(timeout=timeout_seconds)
            except FuturesTimeoutError:
                raise TimeoutError(f"LLM planning timed out after {timeout_seconds}s")
        
        try:
            result = circuit_breaker.call(_execute_with_timeout) if circuit_breaker else _execute_with_timeout()
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
            return create_error_result(error_msg, "PROCESSING_ERROR").model_dump()

    def plan_with_escalation(self, context: 'CognitiveContext') -> Dict[str, Any]:
        fast_result = self.plan(context, depth=LLMProfile.FAST)
        if isinstance(fast_result, dict) and "result" in fast_result:
            meta = fast_result["result"].get("meta", {})
            if meta.get("escalate_hint", False):
                logger.info(f"Escalation suggested, trying DEEP profile for task {context.task_type.value}")
                deep_result = self.plan(context, depth=LLMProfile.DEEP)
                if isinstance(deep_result, dict) and "result" in deep_result:
                    deep_result["result"]["meta"] = deep_result["result"].get("meta", {})
                    deep_result["result"]["meta"]["escalated_from_fast"] = True
                    deep_result["result"]["meta"]["fast_escalate_hint"] = True
                return deep_result
        return fast_result

    def health_check(self) -> Dict[str, Any]:
        try:
            if self.cognitive_core is None:
                return {
                    "status": "unhealthy",
                    "reason": "CognitiveCore not initialized",
                    "timestamp": time.time()
                }
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

    def process_cognitive_task(self, context: 'CognitiveContext') -> Dict[str, Any]:
        if self.cognitive_core is None:
            return create_error_result("CognitiveCore not initialized", "SERVICE_UNAVAILABLE").model_dump()
        try:
            return self.cognitive_core.forward(context)
        except Exception as e:
            logger.error(f"Error processing cognitive task: {e}")
            return create_error_result(f"Processing error: {str(e)}", "PROCESSING_ERROR").model_dump()

    def forward_cognitive_task(self, context: 'CognitiveContext') -> Dict[str, Any]:
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

    def build_fragments_for_synthesis(self, context: 'CognitiveContext', facts: List['Fact'], summary: str) -> List[Dict[str, Any]]:
        if self.cognitive_core is None:
            return []
        try:
            return self.cognitive_core.build_fragments_for_synthesis(context, facts, summary)
        except Exception as e:
            logger.error(f"Error building synthesis fragments: {e}")
            return []

    def get_cognitive_core(self) -> Optional['CognitiveCore']:
        return self.cognitive_core

    def reset_cognitive_core(self):
        if self.cognitive_core:
            from ..cognitive.cognitive_core import reset_cognitive_core
            reset_cognitive_core()
            self.cognitive_core = None
            logger.info("Cognitive core reset")
    
    def shutdown(self):
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=True)
            logger.info("Thread pool executor shutdown")

    def initialize_cognitive_core(self, llm_provider: str = "openai", model: str = "gpt-4o", context_broker: Optional['ContextBroker'] = None) -> 'CognitiveCore':
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
    return COGNITIVE_SERVICE_INSTANCE

def reset_cognitive_service():
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
    "MLServiceEngine",
    "NimEngine"
]
