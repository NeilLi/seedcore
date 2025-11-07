"""
Cognitive Service: Integration layer for cognitive operations.

Multi-provider enhancements:
- Deep profile set via LLM_PROVIDER_DEEP (defaults to OpenAI if not set).
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
    
    This shim implements the DSPy LM interface to make custom engines compatible
    with DSPy's ChainOfThought and other modules.
    """
    def __init__(self, engine: 'LLMEngine'):
        self.engine = engine
        # Common attributes DSPy LMs have (required for DSPy compatibility)
        self.model = getattr(engine, 'model', 'unknown')
        self.max_tokens = getattr(engine, 'max_tokens', 1024)
        self.temperature = getattr(engine, 'temperature', 0.7)  # DSPy expects this attribute
        
        # Store default kwargs for DSPy compatibility
        # DSPy accesses lm.kwargs["temperature"] so this must be populated
        self.kwargs = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

    def basic_request(self, prompt: str, **kwargs):
        """DSPy-compatible basic_request method."""
        engine_base_url = getattr(self.engine, 'base_url', 'unknown')
        engine_model = getattr(self.engine, 'model', 'unknown')
        logger.debug(f"_DSPyEngineShim.basic_request called with prompt length={len(prompt)}, kwargs={list(kwargs.keys())}, model={engine_model}, base_url={engine_base_url}")
        # Merge defaults with overrides from DSPy
        gen_kwargs = {**self.kwargs, **kwargs}
        text = self.engine.generate(prompt, **gen_kwargs)
        logger.debug(f"_DSPyEngineShim.basic_request returning text length={len(text)}")
        return {"text": text}

    def __call__(self, prompt: str, **kwargs):
        """Call interface for DSPy LM compatibility."""
        return self.basic_request(prompt, **kwargs)
    
    def __getattr__(self, name):
        """Forward any missing attributes to the underlying engine."""
        return getattr(self.engine, name)

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
    def __init__(self, model: str, max_tokens: int = 1024, temperature: float = 0.7, base_url: str = None):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
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
        # Use a lambda to properly pass kwargs to generate_async, not anyio.run
        return anyio.run(lambda: self.generate_async(prompt, **kwargs))

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
    def __init__(self, model: str, max_tokens: int = 1024, temperature: float = 0.7,
                 base_url: Optional[str] = None, api_key: Optional[str] = None,
                 use_sdk: Optional[bool] = None, timeout: int = 60):
        # Harden: refuse to run if base_url is missing
        base_url = base_url or os.getenv("NIM_LLM_BASE_URL")
        if not base_url:
            raise RuntimeError(
                "NimEngine misconfigured: NIM_LLM_BASE_URL is not set. "
                "Refusing to fall back to api.openai.com."
            )
        
        # Harden: refuse to run if api_key is missing (but allow "none" as valid placeholder)
        # Some NIM deployments accept "none" as a placeholder API key
        api_key = api_key or os.getenv("NIM_LLM_API_KEY")
        if api_key == "":
            raise RuntimeError(
                "NimEngine misconfigured: NIM_LLM_API_KEY is not set."
            )
        # If api_key is "none", that's acceptable - some NIM deployments accept it as a placeholder

        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout

        from openai import OpenAI
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
        )
        logger.info(f"NimEngine configured with model={self.model}, base_url={self.base_url}, timeout={self.timeout}")

    def configure_for_dspy(self):
        pass

    async def generate_async(self, prompt: str, **kwargs) -> str:
        logger.debug(f"NimEngine.generate_async model={self.model}, base_url={self.base_url}, prompt_len={len(prompt)}")
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
        )
        return completion.choices[0].message.content

    def generate(self, prompt: str, **kwargs) -> str:
        logger.debug(f"NimEngine.generate model={self.model}, base_url={self.base_url}, prompt_len={len(prompt)}")
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
        )
        return completion.choices[0].message.content

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
    # For NIM/MLService, honor SEEDCORE_NIM_TIMEOUT_S if provided
    if provider in ("nim", "mlservice"):
        nim_timeout = os.getenv("SEEDCORE_NIM_TIMEOUT_S")
        if nim_timeout:
            return int(nim_timeout)
        # Sensible defaults for NIM/MLService
        return 12 if profile is LLMProfile.FAST else 30
    # Other providers
    if profile is LLMProfile.FAST:
        return int(os.getenv("FAST_TIMEOUT_SECONDS", "5"))
    return int(os.getenv("DEEP_TIMEOUT_SECONDS", "20"))

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
            os.getenv("NIM_LLM_MODEL" if pf=="deep" else "NIM_LLM_MODEL"),
            "meta/llama-3.1-8b-base" if pf=="deep" else "meta/llama-3.1-8b-base"
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
        return MLServiceEngine(model=model, max_tokens=max_tokens, temperature=0.7, base_url=base_url)
    if provider == "nim":
        return NimEngine(
            model=model,
            max_tokens=max_tokens,
            temperature=0.7,  # Default temperature for NimEngine
            base_url=os.getenv("NIM_LLM_BASE_URL"),
            api_key=os.getenv("NIM_LLM_API_KEY", "none"),
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

    Profiles (internal LLM selection, not routing):
      - DEEP provider set via LLM_PROVIDER_DEEP (defaults to OpenAI if not set).
      - FAST provider chosen from LLM_PROVIDER_FAST > LLM_PROVIDERS > LLM_PROVIDER > OpenAI.
      - Per-profile provider/model overrides supported via env.
    
    Note: Routing decisions use "planner" (not "deep"). DEEP profile is internal metadata
    that may be used within the planner path. Telemetry tracks "planner" only.
    """
    
    def __init__(self, ocps_client=None, profiles: Optional[Dict[LLMProfile, dict]] = None):
        self.ocps_client = ocps_client
        self.schema_version = "v2.0"
        self._executor = ThreadPoolExecutor(max_workers=4)

        # Resolve providers for both profiles
        deep_provider = _default_provider_deep()
        logger.info(f"Resolved DEEP profile provider: {deep_provider} (from LLM_PROVIDER_DEEP={os.getenv('LLM_PROVIDER_DEEP', 'not set')})")
        
        # Resolve FAST provider with detailed logging
        explicit_fast = os.getenv("LLM_PROVIDER_FAST")
        if explicit_fast:
            logger.info(f"FAST profile provider explicitly set via LLM_PROVIDER_FAST={explicit_fast}")
        fast_provider = (_first_non_empty(explicit_fast, None) or _default_provider_fast()).lower()
        logger.info(f"Resolved FAST profile provider: {fast_provider} (from LLM_PROVIDER_FAST={explicit_fast or 'not set'}, LLM_PROVIDERS={os.getenv('LLM_PROVIDERS', 'not set')})")

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

        # CRITICAL: Enable token logging BEFORE creating any cores
        # This ensures OpenAI client patching happens before DSPy creates clients
        if deep_provider == "openai" or fast_provider == "openai":
            try:
                from ..utils.token_logger import enable_token_logging
                enable_token_logging()
                logger.debug("Token logging enabled early in CognitiveService.__init__")
            except Exception as e:
                logger.debug(f"Could not enable token logging early: {e}")

        # Initialize cores & circuit breakers
        self.cores: Dict[LLMProfile, CognitiveCore] = {}
        self.core_configs: Dict[LLMProfile, dict] = {}  # Store configs with LM instances
        self.circuit_breakers: Dict[LLMProfile, CircuitBreaker] = {}
        self._initialize_cores()
        
        # Disable legacy single-core fallback to avoid OpenAI calls
        self.cognitive_core = None
    
    def _initialize_cores(self):
        for profile, config in self.profiles.items():
            try:
                provider = config["provider"].lower()
                model = config["model"]
                engine = _make_engine(provider, profile, model)
                core = self._create_core_with_engine(provider, engine, config)
                self.cores[profile] = core
                self.core_configs[profile] = config  # Store config with _dspy_lm
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
        
        Note: We store the LM instance in the core config to avoid global DSPy settings conflicts.
        Each core will configure DSPy with its own LM before processing.
        """
        import dspy

        provider = provider.lower()
        model = config["model"]
        max_tokens = config.get("max_tokens", 1024)

        # Enable token usage logging BEFORE creating OpenAI instances
        if provider in ("openai", "azure"):
            try:
                from ..utils.token_logger import enable_token_logging
                enable_token_logging()
            except Exception as e:
                logger.debug(f"Could not enable token logging: {e}")

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

        # Store LM in config for per-request configuration
        # Don't configure DSPy globally here - do it per-request to avoid conflicts
        config["_dspy_lm"] = lm

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
            depth = LLMProfile.FAST  # Update depth for correct config lookup
            if core is None:
                return create_error_result(
                    f"No cognitive core available for profile {depth.value}",
                    "SERVICE_UNAVAILABLE"
                ).model_dump()
        
        timeout_seconds = self.profiles.get(depth, {}).get("timeout_seconds", 10)
        
        # CRITICAL: Configure DSPy with the correct LM for this profile before processing
        import dspy
        config = self.core_configs.get(depth)
        logger.info(f"Using timeout={timeout_seconds}s for {depth.value} profile planning (provider={config.get('provider') if config else 'unknown'})")
        if config and "_dspy_lm" in config:
            dspy.settings.configure(lm=config["_dspy_lm"])
            logger.debug(f"Configured DSPy with {depth.value} profile LM (provider={config.get('provider')})")

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
                meta["provider_used"] = config.get("provider", "unknown") if config else "unknown"
                meta["timeout_seconds"] = timeout_seconds
                meta["circuit_breaker_state"] = circuit_breaker.state.state if circuit_breaker else "N/A"
            return result
        except Exception as e:
            logger.error(f"Error in {depth.value} planning: {e}")
            error_msg = f"Planning error: {str(e)}"
            if circuit_breaker and circuit_breaker.state.state == "OPEN":
                error_msg += " (Circuit breaker OPEN)"
            return create_error_result(error_msg, "PROCESSING_ERROR").model_dump()

    def plan_with_deep(self, context: 'CognitiveContext') -> Dict[str, Any]:
        fast_result = self.plan(context, depth=LLMProfile.FAST)
        if isinstance(fast_result, dict) and "result" in fast_result:
            meta = fast_result["result"].get("meta", {})
            if meta.get("escalate_hint", False):
                # Escalation to planner path: use DEEP profile internally (LLMProfile.DEEP)
                # Note: routing decision is "planner", profile="deep" is metadata
                logger.info(f"Escalation suggested, using DEEP profile (planner path) for task {context.task_type.value}")
                deep_result = self.plan(context, depth=LLMProfile.DEEP)
                if isinstance(deep_result, dict) and "result" in deep_result:
                    deep_result["result"]["meta"] = deep_result["result"].get("meta", {})
                    deep_result["result"]["meta"]["escalated_from_fast"] = True
                    deep_result["result"]["meta"]["fast_escalate_hint"] = True
                return deep_result
        return fast_result

    def health_check(self) -> Dict[str, Any]:
        try:
            if not self.cores:
                return {
                    "status": "unhealthy",
                    "reason": "No cognitive cores initialized",
                    "timestamp": time.time()
                }
            return {
                "status": "healthy",
                "cognitive_core_available": True,
                "schema_version": self.schema_version,
                "cores": {profile.value: "available" for profile in self.cores.keys()},
                "timestamp": time.time()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "reason": f"Health check failed: {str(e)}",
                "timestamp": time.time()
            }

    def process_cognitive_task(self, context: 'CognitiveContext') -> Dict[str, Any]:
        # Thin wrapper that delegates to multi-profile forward_cognitive_task
        return self.forward_cognitive_task(context, use_deep=False)

    def forward_cognitive_task(self, context: 'CognitiveContext', use_deep: bool = False) -> Dict[str, Any]:
        """
        Forward cognitive task to appropriate core.
        
        Args:
            context: Cognitive context for the task
            use_deep: If True, use DEEP profile (OpenAI), otherwise use FAST profile (default: False)
        """
        # Check for provider/model overrides in input_data
        input_data = context.input_data or {}
        provider_override = input_data.get("llm_provider_override")
        model_override = input_data.get("llm_model_override")
        providers_hint = input_data.get("providers")  # Multi-provider pool hint
        meta_extra = input_data.get("meta", {})
        
        # Determine which provider/model to use
        target_provider = None
        target_model = None
        
        if provider_override:
            target_provider = provider_override.lower().strip()
            logger.debug(f"Provider override requested: {target_provider}")
        
        if model_override:
            target_model = model_override.strip()
            logger.debug(f"Model override requested: {target_model}")
        
        # If overrides are provided, try to use/create a core with those settings
        if target_provider or target_model:
            # Resolve full provider/model
            if not target_provider:
                # Use default provider for the profile
                profile = LLMProfile.DEEP if use_deep else LLMProfile.FAST
                target_provider = self.profiles.get(profile, {}).get("provider", "openai")
            if not target_model:
                # Use default model for the provider/profile
                profile = LLMProfile.DEEP if use_deep else LLMProfile.FAST
                target_model = _model_for(target_provider, profile)
            
            # Check if we have a matching core (exact match on provider/model)
            # For now, create a temporary core with the override settings
            # TODO: Consider caching temporary cores by provider+model key
            try:
                logger.info(f"Creating temporary core with provider={target_provider}, model={target_model} (override requested)")
                temp_engine = _make_engine(target_provider, LLMProfile.DEEP if use_deep else LLMProfile.FAST, target_model)
                temp_config = {
                    "provider": target_provider,
                    "model": target_model,
                    "max_tokens": 2048 if use_deep else 1024,
                }
                temp_core = self._create_core_with_engine(target_provider, temp_engine, temp_config)
                
                # CRITICAL: Configure DSPy with the override LM before processing
                import dspy
                if temp_config and "_dspy_lm" in temp_config:
                    dspy.settings.configure(lm=temp_config["_dspy_lm"])
                    logger.debug(f"Configured DSPy with override LM (provider={target_provider})")
                
                result = temp_core.forward(context)
                if isinstance(result, dict):
                    result.setdefault("result", {}).setdefault("meta", {})
                    result["result"]["meta"]["profile_used"] = ("deep" if use_deep else "fast")
                    result["result"]["meta"]["provider_override"] = target_provider
                    result["result"]["meta"]["model_override"] = target_model
                    if meta_extra:
                        result["result"]["meta"].update(meta_extra)
                return result
            except Exception as e:
                logger.warning(f"Failed to create temporary core with overrides (provider={target_provider}, model={target_model}): {e}. Falling back to default core.")
                # Fall through to default core selection
        
        # Use new multi-profile system if available (no overrides or override creation failed)
        if self.cores:
            profile = LLMProfile.DEEP if use_deep else LLMProfile.FAST
            core = self.cores.get(profile)
            if core:
                try:
                    # CRITICAL: Configure DSPy with the correct LM for this profile before processing
                    # This avoids global state conflicts when multiple profiles are used
                    import dspy
                    config = self.core_configs.get(profile)
                    if config and "_dspy_lm" in config:
                        dspy.settings.configure(lm=config["_dspy_lm"])
                        logger.debug(f"Configured DSPy with {profile.value} profile LM (provider={config.get('provider')})")
                    
                    result = core.forward(context)
                    if isinstance(result, dict):
                        result.setdefault("result", {}).setdefault("meta", {})
                        result["result"]["meta"]["profile_used"] = profile.value
                        result["result"]["meta"]["provider_used"] = config.get("provider", "unknown") if config else "unknown"
                        if meta_extra:
                            result["result"]["meta"].update(meta_extra)
                    return result
                except Exception as e:
                    logger.error(f"Error forwarding cognitive task with {profile.value} profile: {e}")
                    # No legacy fallback allowed in this deployment
                    pass
        
        # No legacy fallback allowed in this deployment
        logger.error(f"No compatible cognitive core for request (use_deep={use_deep}, cores={list(self.cores.keys())})")
        return {
            "success": False,
            "result": {},
            "payload": {},
            "task_type": context.task_type.value,
            "metadata": {},
            "error": "No compatible cognitive core for this request (legacy core disabled)",
        }

    def build_fragments_for_synthesis(self, context: 'CognitiveContext', facts: List['Fact'], summary: str) -> List[Dict[str, Any]]:
        # Use multi-profile system if available
        if not self.cores:
            logger.warning("No cores available for build_fragments_for_synthesis")
            return []
        # Default to FAST profile
        core = self.cores.get(LLMProfile.FAST)
        if core is None:
            logger.warning("FAST core not available for build_fragments_for_synthesis")
            return []
        try:
            return core.build_fragments_for_synthesis(context, facts, summary)
        except Exception as e:
            logger.error(f"Error building synthesis fragments: {e}")
            return []

    def get_cognitive_core(self) -> Optional['CognitiveCore']:
        # Return FAST profile core for backward compatibility
        return self.cores.get(LLMProfile.FAST)

    def reset_cognitive_core(self):
        # Reset multi-profile cores
        for profile, core in self.cores.items():
            if core:
                from ..cognitive.cognitive_core import reset_cognitive_core
                reset_cognitive_core()
        self.cores.clear()
        self.core_configs.clear()
        self.circuit_breakers.clear()
        logger.info("All cognitive cores reset")
    
    def shutdown(self):
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=True)
            logger.info("Thread pool executor shutdown")

    def initialize_cognitive_core(self, llm_provider: str = "openai", model: str = "gpt-4o", context_broker: Optional['ContextBroker'] = None) -> 'CognitiveCore':
        """
        Legacy method - no longer creates legacy core.
        Multi-profile cores are initialized in __init__.
        """
        logger.warning("initialize_cognitive_core() called but is deprecated in multi-profile system")
        # Return FAST profile core for backward compatibility
        return self.cores.get(LLMProfile.FAST)

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
