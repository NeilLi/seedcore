"""
Cognitive Service: Integration layer for cognitive operations.

Multi-provider enhancements:
- Deep profile set via LLM_PROVIDER_DEEP (defaults to OpenAI if not set).
- Fast profile can be selected from a multi-provider pool (LLM_PROVIDERS=openai,anthropic,nim,...).
- Per-profile provider & model overrides via env.
- Backward compatible with SeedCore core & telemetry.
"""

# Ensure DSP logging is patched before any DSP/DSPy import via transitive imports
try:
    from seedcore.cognitive import dsp_patch  # type: ignore
except Exception:
    pass

import json
import logging
import os
import random
import time
import threading
import httpx
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol

from seedcore.logging_setup import ensure_serve_logger
from ..coordinator.utils import normalize_task_payloads

logger = ensure_serve_logger("seedcore.CognitiveService", level="DEBUG")


class LLMProfile(Enum):
    """LLM profile types for different cognitive processing depths."""

    FAST = "fast"
    DEEP = "deep"


class LLMEngine(Protocol):
    """Protocol for LLM engine abstraction."""

    def configure_for_dspy(self) -> Any:
        ...


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


class MLServiceError(RuntimeError):
    """Raised when MLService returns an invalid response or fails."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class MLServiceEngine:
    """Synchronous MLService engine backed by httpx with retries and structured errors."""

    def __init__(self, model: str, max_tokens: int = 1024, temperature: float = 0.7, base_url: str = None):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
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

        self.timeout = float(os.getenv("MLS_TIMEOUT", "10.0"))
        connect_timeout = float(os.getenv("MLS_CONNECT_TIMEOUT", "2.0"))
        write_timeout = float(os.getenv("MLS_WRITE_TIMEOUT", "5.0"))
        pool_timeout = float(os.getenv("MLS_POOL_TIMEOUT", "2.0"))
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=connect_timeout, read=self.timeout, write=write_timeout, pool=pool_timeout),
            limits=httpx.Limits(
                max_keepalive_connections=int(os.getenv("MLS_MAX_KEEPALIVE_CONNECTIONS", "20")),
                max_connections=int(os.getenv("MLS_MAX_CONNECTIONS", "100")),
            ),
            http2=os.getenv("MLS_HTTP2", "1") not in {"0", "false", "False"},
        )
        self._closed = False
        self._client_lock = threading.Lock()

    def configure_for_dspy(self):
        pass

    def _post_chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        attempts = max(1, int(os.getenv("MLS_RETRY_ATTEMPTS", "3")))
        base_delay = float(os.getenv("MLS_RETRY_BASE_DELAY", "0.25"))

        for attempt in range(1, attempts + 1):
            try:
                response = self._client.post("/chat", json=payload)
                response.raise_for_status()
                return response.json()
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as exc:
                if attempt < attempts:
                    delay = base_delay * (2 ** (attempt - 1))
                    delay += random.random() * 0.2
                    time.sleep(delay)
                    continue
                logger.error("Transient MLService error after retries: %s", exc, exc_info=True)
                raise MLServiceError(f"MLService transient error: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else None
                body = None
                try:
                    body = exc.response.text
                except Exception:
                    pass
                logger.error("MLService HTTP %s: %s", status, body)
                raise MLServiceError(f"MLService HTTP {status}", status=status) from exc
            except Exception as exc:
                logger.error("Unexpected MLService error: %s", exc, exc_info=True)
                raise MLServiceError(f"Unexpected MLService error: {exc}") from exc

        # Should not reach here
        raise MLServiceError("MLService request failed after retries")

    def generate(self, prompt: str, **kwargs) -> str:
        if self._closed:
            raise MLServiceError("MLServiceEngine is closed")

        messages = [{"role": "user", "content": prompt}]
        generation_params = {
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            **{k: v for k, v in kwargs.items() if k != "max_tokens"}
        }
        generation_params.setdefault("temperature", self.temperature)
        payload = {
            "model": self.model,
            "messages": messages,
            **generation_params,
        }

        data = self._post_chat(payload)
        if not isinstance(data, dict):
            raise MLServiceError("Invalid MLService response: expected object")

        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict) and "content" in message:
                    return message["content"]

        if "content" in data:
            return data["content"]

        raise MLServiceError("Invalid MLService response: missing 'content'")

    def close(self) -> None:
        if self._closed:
            return
        with self._client_lock:
            if self._closed:
                return
            try:
                self._client.close()
            finally:
                self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

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
    CognitiveCore,
    ContextBroker,
    Fact,
    RetrievalSufficiency,
    LLMEngine,
    LLMProfile,
    initialize_cognitive_core,
    get_cognitive_core,
)

from ..models.cognitive import (
    CognitiveType, CognitiveContext, DecisionKind,
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
            return normalize_task_payloads(result)
        except Exception as e:
            logger.error(f"Error in {depth.value} planning: {e}")
            error_msg = f"Planning error: {str(e)}"
            if circuit_breaker and circuit_breaker.state.state == "OPEN":
                error_msg += " (Circuit breaker OPEN)"
            return normalize_task_payloads(create_error_result(error_msg, "PROCESSING_ERROR").model_dump())

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
        """
        DEPRECATED: Legacy wrapper retained for backwards compatibility.

        Callers should set 'meta.decision_kind' on the context input_data and call
        'forward_cognitive_task' directly.
        """
        logger.warning(
            "process_cognitive_task() is deprecated. "
            "Inject 'meta.decision_kind' and call forward_cognitive_task() directly."
        )

        # Inject the default FAST path decision kind if missing
        input_data = context.input_data or {}
        meta = input_data.get("meta")
        if meta is None:
            meta = {}
            input_data["meta"] = meta
        if "decision_kind" not in meta:
            meta["decision_kind"] = DecisionKind.FAST_PATH.value
        context.input_data = input_data

        return self.forward_cognitive_task(context)

    def forward_cognitive_task(
        self,
        context: 'CognitiveContext',
        use_deep: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Forward cognitive task to the appropriate core based on decision_kind.
        
        Args:
            context: Cognitive context for the task
            use_deep: Deprecated legacy flag. Prefer `meta.decision_kind` on context input_data.
        """
        input_data_raw = context.input_data or {}
        input_data = normalize_task_payloads(dict(input_data_raw))
        meta_extra = input_data.get("meta")
        if meta_extra is None:
            meta_extra = {}
            input_data["meta"] = meta_extra
        context.input_data = input_data

        # Support legacy callers passing use_deep flag by projecting into decision_kind
        if use_deep is not None and "decision_kind" not in meta_extra:
            inferred_kind = DecisionKind.COGNITIVE if use_deep else DecisionKind.FAST_PATH
            meta_extra["decision_kind"] = inferred_kind.value
            logger.debug(
                "Injected decision_kind='%s' based on deprecated use_deep=%s flag",
                inferred_kind.value,
                use_deep,
            )

        decision_kind_raw = meta_extra.get("decision_kind")
        decision_kind_value = (
            str(decision_kind_raw).strip().lower()
            if decision_kind_raw is not None
            else DecisionKind.FAST_PATH.value
        )

        legacy_aliases = {
            "ray_agent_fast": DecisionKind.FAST_PATH,
        }

        try:
            decision_kind_enum = DecisionKind(decision_kind_value)
        except ValueError:
            decision_kind_enum = legacy_aliases.get(decision_kind_value)

        if decision_kind_enum is None:
            logger.warning(
                "Unknown decision_kind '%s'. Defaulting to FAST profile.",
                decision_kind_raw,
            )
            decision_kind_enum = DecisionKind.FAST_PATH

        # Step 1: select LLM profile based on decision_kind
        if decision_kind_enum is DecisionKind.FAST_PATH:
            profile_key = LLMProfile.FAST
        elif decision_kind_enum in (DecisionKind.COGNITIVE, DecisionKind.ESCALATED):
            profile_key = LLMProfile.DEEP
        else:
            profile_key = LLMProfile.FAST

        logger.debug(
            "Routing task from decision_kind '%s' to LLMProfile '%s'",
            decision_kind_enum.value,
            profile_key.value,
        )

        # Step 2: provider/model overrides
        provider_override = input_data.get("llm_provider_override")
        model_override = input_data.get("llm_model_override")

        if provider_override or model_override:
            target_provider = (provider_override or "").lower().strip()
            target_model = (model_override or "").strip()

            if not target_provider:
                target_provider = self.profiles.get(profile_key, {}).get("provider", "openai")
            if not target_model:
                target_model = _model_for(target_provider, profile_key)

            try:
                logger.info(
                    "Creating temporary core with provider=%s, model=%s (override requested)",
                    target_provider,
                    target_model,
                )
                temp_engine = _make_engine(target_provider, profile_key, target_model)
                temp_config = {
                    "provider": target_provider,
                    "model": target_model,
                    "max_tokens": self.profiles.get(profile_key, {}).get("max_tokens", 2048),
                }
                temp_core = self._create_core_with_engine(target_provider, temp_engine, temp_config)
                
                import dspy
                if temp_config and "_dspy_lm" in temp_config:
                    dspy.settings.configure(lm=temp_config["_dspy_lm"])
                    logger.debug(
                        "Configured DSPy with override LM (provider=%s, profile=%s)",
                        target_provider,
                        profile_key.value,
                    )
                
                result = temp_core.forward(context)
                if isinstance(result, dict):
                    result.setdefault("result", {}).setdefault("meta", {})
                    result["result"]["meta"]["profile_used"] = profile_key.value
                    result["result"]["meta"]["provider_override"] = target_provider
                    result["result"]["meta"]["model_override"] = target_model
                    if meta_extra:
                        result["result"]["meta"].update(meta_extra)
                return normalize_task_payloads(result)
            except Exception as e:
                logger.warning(
                    "Failed to create temporary core with overrides (provider=%s, model=%s): %s. "
                    "Falling back to default core.",
                    target_provider,
                    target_model,
                    e,
                )

        # Step 3: Use default profile core (no overrides)
        if self.cores:
            core = self.cores.get(profile_key)
            if core:
                try:
                    import dspy
                    config = self.core_configs.get(profile_key)
                    if config and "_dspy_lm" in config:
                        dspy.settings.configure(lm=config["_dspy_lm"])
                        logger.debug(
                            "Configured DSPy with %s profile LM (provider=%s)",
                            profile_key.value,
                            config.get("provider"),
                        )

                    result = core.forward(context)
                    if isinstance(result, dict):
                        result.setdefault("result", {}).setdefault("meta", {})
                        result["result"]["meta"]["profile_used"] = profile_key.value
                        result["result"]["meta"]["provider_used"] = config.get("provider", "unknown") if config else "unknown"
                        if meta_extra:
                            result["result"]["meta"].update(meta_extra)
                    return normalize_task_payloads(result)
                except Exception as e:
                    logger.error(
                        "Error forwarding cognitive task with %s profile: %s",
                        profile_key.value,
                        e,
                    )
                    pass

        # Step 4: Fallback error
        logger.error(
            "No compatible cognitive core for request (decision_kind=%s, profile=%s, cores=%s)",
            decision_kind_enum.value,
            profile_key.value,
            list(self.cores.keys()),
        )
        return normalize_task_payloads(
            {
                "success": False,
                "result": {},
                "payload": {},
                "cog_type": context.cog_type.value,
                "metadata": {},
                "error": "No compatible cognitive core for this request (legacy core disabled)",
            }
        )

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
    "CognitiveType", 
    "CognitiveContext",
    "LLMProfile",
    "LLMEngine",
    "OpenAIEngine",
    "MLServiceEngine",
    "NimEngine"
]
