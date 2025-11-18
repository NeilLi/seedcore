#!/usr/bin/env python3
"""
===============================================================================
Cognitive Service + Ray Serve Deployment (Unified Module)
===============================================================================

This module implements SeedCore’s central Cognitive Service, combining:

    • Core cognitive orchestration logic
    • Ray Serve deployment
    • FastAPI routing

It is designed to be consumed as a single `cognitive_service.py` module.

-------------------------------------------------------------------------------
Key Functionalities
-------------------------------------------------------------------------------

1. LLM Engine Adaptors
   --------------------
   • Defines the `LLMEngine` protocol to abstract different LLM providers.
   • Provides concrete implementations:
        - `OpenAIEngine`
        - `MLServiceEngine` (httpx client with retries + error handling)
        - `NimEngine` (OpenAI-compatible SDK)
   • Includes `_DSPyEngineShim` to adapt any engine exposing `.generate()`
     into a DSPy-compatible backend.
   • A factory (`_make_engine`) selects the correct engine based on provider
     configuration.

2. Prompt Context Signature & API Layer
   -------------------------------------
   • The `/execute` FastAPI endpoint uses `CognitiveRequest` (Pydantic) as the
     public API contract.
   • Requests are converted into an internal `CognitiveContext` object
     consumed by orchestration logic.
   • `CognitiveOrchestrator` routes work based on `meta.decision_kind`
       (e.g., FAST_PATH, COGNITIVE).
   • Supports runtime overrides:
        - `llm_provider_override`
        - `llm_model_override`

3. LLM Invocation & Orchestration
   -------------------------------
   • The `CognitiveOrchestrator` maintains multiple `CognitiveCore` instances,
     one per `LLMProfile` (FAST, DEEP).
   • `CognitiveService` (Serve layer) uses `asyncio.to_thread` to call the
     synchronous `forward_cognitive_task()` method without blocking the event loop.
   • The orchestrator’s planning (`core.forward`) uses a `ThreadPoolExecutor`
     with per-profile timeouts to run blocking LLM calls.
   • A `CircuitBreaker` protects the system from repeatedly calling a failing
     LLM provider.

-------------------------------------------------------------------------------
Exports
-------------------------------------------------------------------------------
- CognitiveService      : Ray Serve deployment class (`@serve.deployment`)
- cognitive_app         : Bound FastAPI application instance
- CognitiveOrchestrator : Main orchestrator for cognitive execution
- LLMEngine, OpenAIEngine, MLServiceEngine, NimEngine
- CognitiveContext, CognitiveType, LLMProfile

-------------------------------------------------------------------------------
Notes
-------------------------------------------------------------------------------
- `dsp_patch` is imported at module load time to ensure DSPy hooks are applied
  before any LLM engine initialization.
-------------------------------------------------------------------------------
"""

from __future__ import annotations
# 0) Must be first: patch hooks
try:
    from seedcore.cognitive import dsp_patch  # type: ignore  # noqa: F401
except Exception:
    pass

# 1) Standard library
import asyncio
import os
import random
import time
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Protocol

# 2) Third-party light deps (safe at import time)
import httpx  # type: ignore[reportMissingImports]
from fastapi import FastAPI  # type: ignore[reportMissingImports]
from pydantic import BaseModel, Field  # type: ignore[reportMissingImports]
from ray import serve  # type: ignore[reportMissingImports]

# 3) SeedCore internals (no heavy side effects)
from seedcore.logging_setup import ensure_serve_logger, setup_logging
from ..coordinator.utils import normalize_task_payloads
from ..cognitive.cognitive_core import CognitiveCore, Fact
from ..models.cognitive import CognitiveContext, CognitiveType, DecisionKind
try:
    from seedcore.utils.ray_utils import ML
except Exception:
    ML = None  # Fallback handled in _make_engine
from ..models.result_schema import create_error_result

if TYPE_CHECKING:
    from ..cognitive.cognitive_core import ContextBroker

# Configure logging for driver process (script that invokes serve.run)
setup_logging(app_name="seedcore.cognitive_service.driver")
logger = ensure_serve_logger("seedcore.cognitive_service", level="DEBUG")

# -----------------------------------------------------------------------------
# 5) Provider-agnostic interfaces / helpers
# -----------------------------------------------------------------------------

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
        self.model = getattr(engine, 'model', 'unknown')
        self.max_tokens = getattr(engine, 'max_tokens', 1024)
        self.temperature = getattr(engine, 'temperature', 0.7)
        self.kwargs = {"temperature": self.temperature, "max_tokens": self.max_tokens}

    def basic_request(self, prompt: str, **kwargs):
        engine_base_url = getattr(self.engine, 'base_url', 'unknown')
        engine_model = getattr(self.engine, 'model', 'unknown')
        logger.debug(
            f"_DSPyEngineShim.basic_request prompt_len={len(prompt)} "
            f"kwargs={list(kwargs.keys())} model={engine_model} base_url={engine_base_url}"
        )
        gen_kwargs = {**self.kwargs, **kwargs}
        text = self.engine.generate(prompt, **gen_kwargs)
        logger.debug(f"_DSPyEngineShim.basic_request returning text length={len(text)}")
        return {"text": text}

    def __call__(self, prompt: str, **kwargs):
        return self.basic_request(prompt, **kwargs)

    def __getattr__(self, name):
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
        payload = {"model": self.model, "messages": messages, **generation_params}
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


try:
    from seedcore.utils.llm_registry import get_active_providers
except Exception:
    def get_active_providers() -> List[str]:
        v = os.getenv("LLM_PROVIDERS", "")
        return [p.strip().lower() for p in v.split(",") if p.strip()]


class NimEngine:
    """NIM (OpenAI-compatible) engine using SeedCore nim drivers (SDK or HTTP)."""
    def __init__(self, model: str, max_tokens: int = 1024, temperature: float = 0.7,
                 base_url: Optional[str] = None, api_key: Optional[str] = None,
                 use_sdk: Optional[bool] = None, timeout: int = 60):
        base_url = base_url or os.getenv("NIM_LLM_BASE_URL")
        if not base_url:
            raise RuntimeError(
                "NimEngine misconfigured: NIM_LLM_BASE_URL is not set."
            )
        api_key = api_key or os.getenv("NIM_LLM_API_KEY")
        if api_key == "":
            raise RuntimeError("NimEngine misconfigured: NIM_LLM_API_KEY is not set.")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        from openai import OpenAI  # type: ignore[reportMissingImports]
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=self.timeout)
        logger.info(f"NimEngine configured model={self.model} base_url={self.base_url} timeout={self.timeout}")

    def configure_for_dspy(self):
        pass

    async def generate_async(self, prompt: str, **kwargs) -> str:
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
        )
        return completion.choices[0].message.content

    def generate(self, prompt: str, **kwargs) -> str:
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
# Cognitive Service Integration Layer
# =============================================================================

def _first_non_empty(*vals: Optional[str]) -> Optional[str]:
    for v in vals:
        if v and str(v).strip():
            return str(v).strip()
    return None

def _normalize_list(val: Optional[str]) -> List[str]:
    return [x.strip().lower() for x in (val or "").split(",") if x.strip()]

def _default_provider_deep() -> str:
    explicit = os.getenv("LLM_PROVIDER_DEEP")
    if explicit and explicit.strip():
        return explicit.strip().lower()
    return "openai"

def _default_provider_fast() -> str:
    explicit = os.getenv("LLM_PROVIDER_FAST")
    if explicit:
        return explicit.strip().lower()
    providers = get_active_providers() or _normalize_list(os.getenv("LLM_PROVIDERS"))
    if providers:
        return providers[0]
    return (_first_non_empty(os.getenv("LLM_PROVIDER"), "openai") or "openai").lower()

def _timeout(profile: LLMProfile, provider: str) -> int:
    if provider in ("nim", "mlservice"):
        nim_timeout = os.getenv("SEEDCORE_NIM_TIMEOUT_S")
        if nim_timeout:
            return int(nim_timeout)
        return 12 if profile is LLMProfile.FAST else 30
    if profile is LLMProfile.FAST:
        return int(os.getenv("FAST_TIMEOUT_SECONDS", "5"))
    return int(os.getenv("DEEP_TIMEOUT_SECONDS", "20"))


# ----------------------------------------------------------------------
# CENTRAL PROVIDER REGISTRY
# ----------------------------------------------------------------------

PROVIDER_CONFIG = {
    "openai": {
        "env": {
            "deep": "OPENAI_MODEL_DEEP",
            "fast": "OPENAI_MODEL_FAST",
        },
        "defaults": {
            "deep": "gpt-4o",
            "fast": "gpt-4o-mini",
        },
        "engine": lambda model, profile: OpenAIEngine(
            model=model,
            max_tokens=2048 if profile is LLMProfile.DEEP else 1024
        ),
    },
    "anthropic": {
        "env": {
            "deep": "ANTHROPIC_MODEL_DEEP",
            "fast": "ANTHROPIC_MODEL_FAST",
        },
        "defaults": {
            "deep": "claude-3-5-sonnet",
            "fast": "claude-3-5-haiku",
        },
        "engine": lambda model, profile: OpenAIEngine(
            model=model,
            max_tokens=2048 if profile is LLMProfile.DEEP else 1024
        ),
    },
    "google": {
        "env": {
            "deep": "GOOGLE_MODEL_DEEP",
            "fast": "GOOGLE_MODEL_FAST",
        },
        "defaults": {
            "deep": "gemini-1.5-pro",
            "fast": "gemini-1.5-flash",
        },
        "engine": lambda model, profile: OpenAIEngine(
            model=model,
            max_tokens=2048 if profile is LLMProfile.DEEP else 1024
        ),
    },
    "azure": {
        "env": {
            "deep": "AZURE_OPENAI_MODEL_DEEP",
            "fast": "AZURE_OPENAI_MODEL_FAST",
        },
        "defaults": {
            "deep": "gpt-4o",
            "fast": "gpt-4o-mini",
        },
        "engine": lambda model, profile: OpenAIEngine(
            model=model,
            max_tokens=2048 if profile is LLMProfile.DEEP else 1024
        ),
    },
    "nim": {
        "env": {"deep": "NIM_LLM_MODEL", "fast": "NIM_LLM_MODEL"},
        "defaults": {
            "deep": "meta/llama-3.1-8b-base",
            "fast": "meta/llama-3.1-8b-base",
        },
        "engine": lambda model, profile: NimEngine(
            model=model,
            temperature=0.7,
            max_tokens=2048 if profile is LLMProfile.DEEP else 1024,
            base_url=os.getenv("NIM_LLM_BASE_URL"),
            api_key=os.getenv("NIM_LLM_API_KEY", "none"),
            use_sdk=None,
            timeout=_timeout(profile, "nim"),
        ),
    },
    "mlservice": {
        "env": {
            "deep": "MLS_MODEL_DEEP",
            "fast": "MLS_MODEL_FAST",
        },
        "defaults": {
            "deep": "llama3-70b-instruct",
            "fast": "llama3-8b-instruct-q4",
        },
        "engine": lambda model, profile: MLServiceEngine(
            model=model,
            max_tokens=2048 if profile is LLMProfile.DEEP else 1024,
            temperature=0.7,
            base_url=os.getenv("MLS_BASE_URL") or (str(ML).rstrip("/") if ML else "http://127.0.0.1:8000/ml"),
        ),
    },
}


def _model_for(provider: str, profile: LLMProfile) -> str:
    """Get model name for provider and profile using centralized registry."""
    pr = provider.lower()
    pf = "deep" if profile is LLMProfile.DEEP else "fast"

    config = PROVIDER_CONFIG.get(pr)
    if not config:
        # Universal fallback
        return "gpt-4o" if pf == "deep" else "gpt-4o-mini"

    # env override or default
    env_key = config["env"].get(pf)
    return _first_non_empty(
        os.getenv(env_key) if env_key else None,
        config["defaults"][pf],
    ) or ("gpt-4o" if pf == "deep" else "gpt-4o-mini")


def _make_engine(provider: str, profile: LLMProfile, model: str):
    """Create engine instance for provider and profile using centralized registry."""
    pr = provider.lower()
    config = PROVIDER_CONFIG.get(pr)
    if not config:
        raise ValueError(f"Unsupported provider: {provider}")

    return config["engine"](model, profile)


class CognitiveOrchestrator:
    """
    Service layer for cognitive operations with multi-provider, dual-profile (FAST/DEEP) support.
    """
    def __init__(self, ocps_client=None, profiles: Optional[Dict[LLMProfile, dict]] = None):
        self.ocps_client = ocps_client
        self.schema_version = "v2.0"
        self._executor = ThreadPoolExecutor(max_workers=4)

        deep_provider = _default_provider_deep()
        logger.info(f"Resolved DEEP profile provider: {deep_provider} (LLM_PROVIDER_DEEP={os.getenv('LLM_PROVIDER_DEEP', 'not set')})")
        explicit_fast = os.getenv("LLM_PROVIDER_FAST")
        if explicit_fast:
            logger.info(f"FAST profile provider explicitly set: {explicit_fast}")
        fast_provider = (_first_non_empty(explicit_fast, None) or _default_provider_fast()).lower()
        logger.info(f"Resolved FAST profile provider: {fast_provider}")

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

        if deep_provider == "openai" or fast_provider == "openai":
            try:
                from ..utils.token_logger import enable_token_logging
                enable_token_logging()
                logger.debug("Token logging enabled early in CognitiveService.__init__")
            except Exception as e:
                logger.debug(f"Could not enable token logging early: {e}")

        self.cores: Dict[LLMProfile, CognitiveCore] = {}
        self.core_configs: Dict[LLMProfile, dict] = {}
        self.circuit_breakers: Dict[LLMProfile, CircuitBreaker] = {}
        self._initialize_cores()

        # Legacy single-core disabled
        self.cognitive_core = None

    def _initialize_cores(self):
        for profile, config in self.profiles.items():
            try:
                provider = config["provider"].lower()
                model = config["model"]
                engine = _make_engine(provider, profile, model)
                core = self._create_core_with_engine(provider, engine, config)
                self.cores[profile] = core
                self.core_configs[profile] = config
                self.circuit_breakers[profile] = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
                logger.info(f"Initialized {profile.value} core with provider={provider} model={model}")
            except Exception as e:
                logger.error(f"Failed to initialize {profile.value} core: {e}")
                continue

    def _create_core_with_engine(self, provider: str, engine: LLMEngine, config: dict) -> CognitiveCore:
        import dspy  # type: ignore[reportMissingImports]
        provider = provider.lower()
        model = config["model"]
        max_tokens = config.get("max_tokens", 1024)

        if provider in ("openai", "azure"):
            try:
                from ..utils.token_logger import enable_token_logging
                enable_token_logging()
            except Exception as e:
                logger.debug(f"Could not enable token logging: {e}")

        if provider == "openai":
            lm = dspy.OpenAI(model=model, max_tokens=max_tokens)
        elif provider == "anthropic":
            try:
                lm = dspy.Anthropic(model=model, max_tokens=max_tokens)
            except Exception:
                lm = dspy.LM(provider="anthropic", model=model, max_tokens=max_tokens)
        elif provider == "google":
            try:
                lm = dspy.Google(model=model, max_tokens=max_tokens)
            except Exception:
                lm = dspy.LM(provider="google", model=model, max_tokens=max_tokens)
        elif provider == "azure":
            lm = dspy.OpenAI(model=model, max_tokens=max_tokens)
        else:
            lm = _DSPyEngineShim(engine)  # type: ignore

        config["_dspy_lm"] = lm
        return CognitiveCore(llm_provider=provider, model=model, context_broker=None, ocps_client=self.ocps_client)

    # ------------------ Orchestration methods ------------------

    def plan(self, context: 'CognitiveContext', depth: LLMProfile = LLMProfile.FAST) -> Dict[str, Any]:
        core = self.cores.get(depth) or self.cores.get(LLMProfile.FAST)
        circuit_breaker = self.circuit_breakers.get(depth) or self.circuit_breakers.get(LLMProfile.FAST)
        if core is None:
            return create_error_result(f"No cognitive core for profile {depth.value}", "SERVICE_UNAVAILABLE").model_dump()

        timeout_seconds = self.profiles.get(depth, {}).get("timeout_seconds", 10)

        import dspy  # type: ignore[reportMissingImports]
        config = self.core_configs.get(depth)
        logger.info(f"Using timeout={timeout_seconds}s for {depth.value} planning (provider={config.get('provider') if config else 'unknown'})")
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
                return {"status": "unhealthy", "reason": "No cognitive cores initialized", "timestamp": time.time()}
            return {
                "status": "healthy",
                "cognitive_core_available": True,
                "schema_version": self.schema_version,
                "cores": {profile.value: "available" for profile in self.cores.keys()},
                "timestamp": time.time(),
            }
        except Exception as e:
            return {"status": "unhealthy", "reason": f"Health check failed: {str(e)}", "timestamp": time.time()}

    def process_cognitive_task(self, context: 'CognitiveContext') -> Dict[str, Any]:
        logger.warning("process_cognitive_task() is deprecated; use forward_cognitive_task()")
        input_data = context.input_data or {}
        meta = input_data.get("meta") or {}
        input_data["meta"] = meta
        if "decision_kind" not in meta:
            meta["decision_kind"] = DecisionKind.FAST_PATH.value
        context.input_data = input_data
        return self.forward_cognitive_task(context)

    def forward_cognitive_task(self, context: 'CognitiveContext', use_deep: Optional[bool] = None) -> Dict[str, Any]:
        input_data_raw = context.input_data or {}
        input_data = normalize_task_payloads(dict(input_data_raw))
        meta_extra = input_data.get("meta") or {}
        input_data["meta"] = meta_extra
        context.input_data = input_data

        if use_deep is not None and "decision_kind" not in meta_extra:
            inferred_kind = DecisionKind.COGNITIVE if use_deep else DecisionKind.FAST_PATH
            meta_extra["decision_kind"] = inferred_kind.value
            logger.debug("Injected decision_kind='%s' from use_deep=%s", inferred_kind.value, use_deep)

        decision_kind_raw = meta_extra.get("decision_kind")
        decision_kind_value = (str(decision_kind_raw).strip().lower()
                               if decision_kind_raw is not None else DecisionKind.FAST_PATH.value)

        legacy_aliases = {"ray_agent_fast": DecisionKind.FAST_PATH}
        try:
            decision_kind_enum = DecisionKind(decision_kind_value)
        except ValueError:
            decision_kind_enum = legacy_aliases.get(decision_kind_value)
        if decision_kind_enum is None:
            logger.warning("Unknown decision_kind '%s'. Defaulting to FAST.", decision_kind_raw)
            decision_kind_enum = DecisionKind.FAST_PATH

        if decision_kind_enum is DecisionKind.FAST_PATH:
            profile_key = LLMProfile.FAST
        elif decision_kind_enum in (DecisionKind.COGNITIVE, DecisionKind.ESCALATED):
            profile_key = LLMProfile.DEEP
        else:
            profile_key = LLMProfile.FAST

        provider_override = input_data.get("llm_provider_override")
        model_override = input_data.get("llm_model_override")

        if provider_override or model_override:
            target_provider = (provider_override or "").lower().strip() or self.profiles.get(profile_key, {}).get("provider", "openai")
            target_model = (model_override or "").strip() or _model_for(target_provider, profile_key)
            try:
                logger.info("Creating temporary core override provider=%s model=%s", target_provider, target_model)
                temp_engine = _make_engine(target_provider, profile_key, target_model)
                temp_config = {"provider": target_provider, "model": target_model, "max_tokens": self.profiles.get(profile_key, {}).get("max_tokens", 2048)}
                temp_core = self._create_core_with_engine(target_provider, temp_engine, temp_config)
                import dspy  # type: ignore[reportMissingImports]
                if "_dspy_lm" in temp_config:
                    dspy.settings.configure(lm=temp_config["_dspy_lm"])
                    logger.debug("Configured DSPy with override LM (provider=%s, profile=%s)", target_provider, profile_key.value)
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
                logger.warning("Failed override provider=%s model=%s: %s. Falling back.", target_provider, target_model, e)

        if self.cores:
            core = self.cores.get(profile_key)
            if core:
                try:
                    import dspy  # type: ignore[reportMissingImports]
                    config = self.core_configs.get(profile_key)
                    if config and "_dspy_lm" in config:
                        dspy.settings.configure(lm=config["_dspy_lm"])
                        logger.debug("Configured DSPy with %s LM (provider=%s)", profile_key.value, config.get("provider"))
                    result = core.forward(context)
                    if isinstance(result, dict):
                        result.setdefault("result", {}).setdefault("meta", {})
                        result["result"]["meta"]["profile_used"] = profile_key.value
                        result["result"]["meta"]["provider_used"] = config.get("provider", "unknown") if config else "unknown"
                        if meta_extra:
                            result["result"]["meta"].update(meta_extra)
                    return normalize_task_payloads(result)
                except Exception as e:
                    logger.error("Error forwarding cognitive task with %s profile: %s", profile_key.value, e)

        logger.error("No compatible cognitive core (decision_kind=%s, profile=%s)", decision_kind_enum.value, profile_key.value)
        return normalize_task_payloads({"success": False, "result": {}, "payload": {}, "cog_type": context.cog_type.value, "metadata": {}, "error": "No compatible cognitive core for this request (legacy core disabled)"})

    def build_fragments_for_synthesis(self, context: 'CognitiveContext', facts: List['Fact'], summary: str) -> List[Dict[str, Any]]:
        if not self.cores:
            logger.warning("No cores available for build_fragments_for_synthesis")
            return []
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
        return self.cores.get(LLMProfile.FAST)

    def reset_cognitive_core(self):
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
        logger.warning("initialize_cognitive_core() deprecated in multi-profile system")
        return self.cores.get(LLMProfile.FAST)


# =============================================================================
# Global Service Instance Management
# =============================================================================

COGNITIVE_SERVICE_INSTANCE: Optional[CognitiveOrchestrator] = None

def initialize_cognitive_service(ocps_client=None) -> CognitiveOrchestrator:
    global COGNITIVE_SERVICE_INSTANCE
    if COGNITIVE_SERVICE_INSTANCE is None:
        try:
            COGNITIVE_SERVICE_INSTANCE = CognitiveOrchestrator(ocps_client=ocps_client)
            logger.info("Initialized global cognitive service")
        except Exception as e:
            logger.error(f"Failed to initialize cognitive service: {e}")
            raise
    return COGNITIVE_SERVICE_INSTANCE

def get_cognitive_service() -> Optional[CognitiveOrchestrator]:
    return COGNITIVE_SERVICE_INSTANCE

def reset_cognitive_service():
    global COGNITIVE_SERVICE_INSTANCE
    if COGNITIVE_SERVICE_INSTANCE:
        COGNITIVE_SERVICE_INSTANCE.reset_cognitive_core()
    COGNITIVE_SERVICE_INSTANCE = None


# =============================================================================
# Serve/FastAPI Deployment (formerly cognitive_services.py)
# =============================================================================

# --- Configuration for info endpoints ---
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore-dev")

# --- Request/Response Models ---
class CognitiveRequest(BaseModel):
    """Unified request model for the /execute endpoint using TaskPayload schema.
    
    All requests must use the unified TaskPayload format with cognitive metadata
    in params.cognitive namespace.
    """
    # TaskPayload format fields (required)
    type: str
    task_id: str
    params: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    domain: Optional[str] = None
    
    class Config:
        extra = "allow"  # Allow additional TaskPayload fields

class CognitiveResponse(BaseModel):
    """Unified response model for the /execute endpoint."""
    success: bool
    result: Dict[str, Any]
    error: Optional[str] = None
    metadata: Dict[str, Any]

# FastAPI app for ingress
app = FastAPI(title="SeedCore Cognitive Service", version="2.0.0")

@serve.deployment(name="CognitiveService")
@serve.ingress(app)
class CognitiveService:
    def __init__(self):
        setup_logging(app_name="seedcore.cognitive_service.replica")
        self.logger = ensure_serve_logger("seedcore.cognitive_service", level="DEBUG")

        self.logger.info("🚀 Initializing warm cognitive_service for new replica...")
        self.cognitive_service: CognitiveOrchestrator = initialize_cognitive_service()
        self.logger.info("✅ Cognitive_service is warm and ready.")

    @app.get("/health")
    async def health(self):
        health_status = self.cognitive_service.health_check()
        health_status.update({
            "service": "cognitive-warm-replica",
            "route_prefix": "/cognitive",
            "ray_namespace": RAY_NS,
            "ray_address": RAY_ADDR,
            "endpoints": {"health": "/health", "info": "/info", "execute": "/execute"},
        })
        return health_status

    @app.get("/")
    async def root(self):
        return {
            "status": "healthy",
            "service": "cognitive-warm-replica",
            "message": "SeedCore Cognitive Service is running.",
            "documentation": "See /docs for API details.",
            "endpoint": "/execute",
        }

    @app.get("/info")
    async def info(self):
        return {
            "service": "cognitive-warm-replica",
            "ray_namespace": RAY_NS,
            "ray_address": RAY_ADDR,
            "deployment": {
                "name": "CognitiveService",
                "replicas": int(os.getenv("COG_SVC_REPLICAS", "1")),
                "max_ongoing_requests": 32,
            },
        }

    @app.post("/execute", response_model=CognitiveResponse)
    async def execute_cognitive_task(self, request: CognitiveRequest):
        start_time = time.time()
        
        # Extract from unified TaskPayload format
        params = request.params or {}
        cognitive_section = params.get("cognitive", {})
        
        if not cognitive_section:
            raise ValueError(
                "params.cognitive is required. Expected structure: "
                "params.cognitive = {agent_id, cog_type, decision_kind, ...}"
            )
        
        # Extract required fields from params.cognitive
        agent_id = cognitive_section.get("agent_id")
        if not agent_id:
            raise ValueError("params.cognitive.agent_id is required")
        
        cog_type_str = cognitive_section.get("cog_type")
        if not cog_type_str:
            raise ValueError("params.cognitive.cog_type is required")
        
        try:
            cog_type = CognitiveType(cog_type_str)
        except ValueError:
            raise ValueError(f"Invalid cog_type '{cog_type_str}'. Must be a valid CognitiveType.")
        
        decision_kind_str = cognitive_section.get("decision_kind", DecisionKind.FAST_PATH.value)
        
        # Extract task_id
        task_id = request.task_id
        
        # Build input_data from TaskPayload structure for CognitiveContext
        # This preserves the full TaskPayload structure for cognitive_core to access
        input_data = {
            "task_id": task_id,
            "type": request.type,
            "description": request.description or "",
            "domain": request.domain,
            "params": params,  # Include full params for cognitive processing
        }
        
        # Extract overrides from params.cognitive
        llm_provider_override = cognitive_section.get("llm_provider_override")
        llm_model_override = cognitive_section.get("llm_model_override")
        
        if llm_provider_override:
            input_data["llm_provider_override"] = llm_provider_override
        if llm_model_override:
            input_data["llm_model_override"] = llm_model_override
        
        try:
            context = CognitiveContext(
                agent_id=agent_id,
                cog_type=cog_type,
                input_data=input_data,
            )

            decision_kind = decision_kind_str
            self.logger.info(
                f"/execute: Received task_id={task_id} for agent {agent_id}. "
                f"cog_type={cog_type.value}, decision_kind={decision_kind}"
            )

            result_dict = await asyncio.to_thread(
                self.cognitive_service.forward_cognitive_task,
                context,
            )

            processing_time = (time.time() - start_time) * 1000
            self.logger.info(
                f"/execute: Completed task_id={task_id} for agent {agent_id} "
                f"in {processing_time:.2f}ms. Success={result_dict.get('success')}"
            )

            if not result_dict.get("success", False):
                return CognitiveResponse(
                    success=False,
                    result=result_dict.get("result", {}),
                    error=result_dict.get("error", "Cognitive task failed"),
                    metadata=result_dict.get("metadata", {}),
                )

            return CognitiveResponse(
                success=True,
                result=result_dict.get("result", {}),
                error=None,
                metadata=result_dict.get("metadata", {}),
            )

        except Exception as e:
            processing_time = (time.time() - start_time) * 1000
            tb_str = traceback.format_exc()
            self.logger.error(
                f"FATAL /execute: Unhandled exception for task_id={task_id} "
                f"after {processing_time:.2f}ms. Error: {e}\n{tb_str}"
            )
            return CognitiveResponse(
                success=False,
                result={},
                error=f"Unhandled exception in API endpoint: {e}",
                metadata={"traceback": tb_str},
            )


# Expose a bound app for Ray Serve YAML importers
cognitive_app = CognitiveService.bind()

# Re-export core types for decoupling
__all__ = [
    "CognitiveOrchestrator",
    "initialize_cognitive_service",
    "get_cognitive_service",
    "reset_cognitive_service",
    "CognitiveType",
    "CognitiveContext",
    "LLMProfile",
    "LLMEngine",
    "OpenAIEngine",
    "MLServiceEngine",
    "NimEngine",
    "CognitiveService",
    "cognitive_app",
]
