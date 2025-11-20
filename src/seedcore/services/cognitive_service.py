#!/usr/bin/env python3
"""
===============================================================================
Cognitive Service + Ray Serve Deployment (Unified Module)
===============================================================================

This module implements SeedCore's central Cognitive Service (Tier-1 Manager)
in the Tiered Brain architecture, combining:

    • Strategic orchestration logic (profile allocation, resource management)
    • Ray Serve deployment
    • FastAPI routing
    • Server-side hydration (Data Pull pattern)

It is designed to be consumed as a single `cognitive_service.py` module.

-------------------------------------------------------------------------------
Architecture: Tiered Brain (Tier-1 Manager)
-------------------------------------------------------------------------------

The CognitiveOrchestrator acts as the STRATEGY Layer:

    Responsibilities:
    1. Resource Management: Allocates Fast vs Deep profiles based on DecisionKind
    2. Context Isolation: Ensures thread-safe execution via dspy.context
    3. Data Access: Initializes repositories for Server-Side Hydration
    4. Governance: Applies circuit breakers and timeouts

    The CognitiveCore (Worker) follows data-driven orders:
    - skip_retrieval=True: Skip RAG (Fast/Chat mode)
    - hgnn_embedding present: Use HGNN context
    - Otherwise: Run RAG pipeline

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
   • The `/execute` FastAPI endpoint uses `TaskPayload` (Pydantic) as the
     public API contract for system-wide consistency.
   • Requests are converted into an internal `CognitiveContext` object
     consumed by orchestration logic.
   • `CognitiveOrchestrator` resolves profiles based on `DecisionKind`:
       - FAST_PATH → LLMProfile.FAST
       - COGNITIVE/ESCALATED → LLMProfile.DEEP
   • Supports runtime overrides:
        - `llm_provider_override`
        - `llm_model_override`

3. LLM Invocation & Orchestration
   -------------------------------
   • The `CognitiveOrchestrator` maintains multiple `CognitiveCore` instances,
     one per `LLMProfile` (FAST, DEEP).
   • Each Core is initialized with `graph_repo` and `session_maker` for
     server-side hydration (Lazy Coordinator pattern).
   • `CognitiveService` (Serve layer) uses `asyncio.to_thread` to call the
     synchronous `forward_cognitive_task()` method without blocking the event loop.
   • Thread-safe execution: Uses `dspy.context(lm=execution_lm)` to isolate
     LM settings per request, preventing global state conflicts.
   • A `CircuitBreaker` protects the system from repeatedly calling a failing
     LLM provider.

4. Server-Side Hydration (Data Pull Pattern)
   ------------------------------------------
   • When Coordinator sends minimal payload (only `task_id`), the Core can
     hydrate context from the database using `TaskMetadataRepository`.
   • Hydration occurs automatically in `_run_rag_pipeline` if context is "thin".
   • Supports Lazy Coordinator architecture where Coordinator doesn't need to
     fetch full task data before routing.

5. Chat Optimization
   ------------------
   • Chat tasks use `dspy.Predict` instead of `ChainOfThought` for low latency.
   • Fast path with `skip_retrieval=True` for conversational interactions.
   • Optimized for high-velocity agent-tunneled conversations.

-------------------------------------------------------------------------------
Exports
-------------------------------------------------------------------------------
- CognitiveService      : Ray Serve deployment class (`@serve.deployment`)
- cognitive_app         : Bound FastAPI application instance
- CognitiveOrchestrator : Main orchestrator for cognitive execution (Tier-1)
- LLMEngine, OpenAIEngine, MLServiceEngine, NimEngine
- CognitiveContext, CognitiveType, LLMProfile

-------------------------------------------------------------------------------
Notes
-------------------------------------------------------------------------------
- `dsp_patch` is imported at module load time to ensure DSPy hooks are applied
  before any LLM engine initialization.
- The Orchestrator manages Core lifecycle; no global singletons.
- Database session factory is injected into Cores for hydration support.
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
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Protocol

# 2) Third-party light deps (safe at import time)
import httpx  # type: ignore[reportMissingImports]
from fastapi import FastAPI, HTTPException  # type: ignore[reportMissingImports]
from pydantic import BaseModel  # type: ignore[reportMissingImports]
from ray import serve  # type: ignore[reportMissingImports]

# 3) SeedCore internals (no heavy side effects)
from seedcore.logging_setup import ensure_serve_logger, setup_logging
from ..coordinator.utils import normalize_task_payloads
from ..cognitive.cognitive_core import CognitiveCore, Fact
from ..models.cognitive import CognitiveContext, CognitiveType, DecisionKind, LLMProfile
from ..models.task_payload import TaskPayload
try:
    from seedcore.utils.ray_utils import ML
except Exception:
    ML = None  # Fallback handled in _make_engine
from ..models.result_schema import create_error_result

# Optional: Graph Repo for Server-Side Hydration
try:
    from ..graph.task_metadata_repository import TaskMetadataRepository
except ImportError:
    TaskMetadataRepository = None

# Database (Required for Server-Side Hydration)
try:
    from ..database import get_async_pg_session_factory
    get_async_session_maker = get_async_pg_session_factory  # Alias for clarity
except ImportError:
    get_async_session_maker = None

if TYPE_CHECKING:
    from ..cognitive.cognitive_core import ContextBroker

# Configure logging for driver process (script that invokes serve.run)
setup_logging(app_name="seedcore.cognitive_service.driver")
logger = ensure_serve_logger("seedcore.cognitive_service", level="DEBUG")

# -----------------------------------------------------------------------------
# 5) Provider-agnostic interfaces / helpers
# -----------------------------------------------------------------------------



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
    The STRATEGY Layer (Tier-1 Manager).
    
    Responsibilities:
    1. Resource Management: Allocates Fast vs Deep profiles.
    2. Context Isolation: Ensures thread-safe execution via dspy.context.
    3. Data Access: Initializes repositories for Server-Side Hydration.
    4. Governance: Applies circuit breakers and timeouts.
    """

    def __init__(self, ocps_client=None, profiles: Optional[Dict[LLMProfile, dict]] = None):
        self.ocps_client = ocps_client
        self.schema_version = "v2.1"
        
        # Configurable Thread Pool
        max_workers = int(os.getenv("COGNITIVE_MAX_WORKERS", "8"))
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

        # --- 1. Data Layer (Server-Side Hydration) ---
        self.graph_repo = None
        self.session_maker = None
        
        if TaskMetadataRepository and get_async_session_maker:
            try:
                self.graph_repo = TaskMetadataRepository()
                self.session_maker = get_async_session_maker()
                logger.info("✅ CognitiveOrchestrator connected to Graph Repository & DB")
            except Exception as e:
                logger.warning(f"⚠️ Failed to connect to Graph Repository: {e}")

        # --- 2. Profile Resolution ---
        deep_provider = self._resolve_provider_env("DEEP")
        fast_provider = self._resolve_provider_env("FAST")
        
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

        # --- 3. Core Initialization ---
        self.cores: Dict[LLMProfile, CognitiveCore] = {}
        self.core_configs: Dict[LLMProfile, dict] = {}
        self.circuit_breakers: Dict[LLMProfile, CircuitBreaker] = {}
        self._initialize_cores()

    def _initialize_cores(self):
        """Initialize the persistent CognitiveCores for each profile."""
        for profile, config in self.profiles.items():
            try:
                provider = config["provider"].lower()
                model = config["model"]
                
                # 1. Create the DSPy LM (The "Brain")
                lm = self._create_dspy_lm(provider, model, config)
                config["_dspy_lm"] = lm
                
                # 2. Create the Execution Core (The "Worker")
                # CRITICAL: Pass self.graph_repo and session_maker for server-side hydration
                core = CognitiveCore(
                    llm_provider=provider,
                    model=model,
                    context_broker=None,
                    ocps_client=self.ocps_client,
                    graph_repo=self.graph_repo,
                    session_maker=self.session_maker
                )
                
                self.cores[profile] = core
                self.core_configs[profile] = config
                self.circuit_breakers[profile] = CircuitBreaker(
                    failure_threshold=3, recovery_timeout=60.0
                )
                logger.info(f"✅ Initialized {profile.value} core | {provider}/{model}")
                
            except Exception as e:
                logger.error(f"❌ Failed to initialize {profile.value} core: {e}")

    def _create_dspy_lm(self, provider: str, model: str, config: dict) -> Any:
        """Factory to create DSPy LM objects. Used by init and overrides."""
        import dspy  # type: ignore[reportMissingImports]
        max_tokens = config.get("max_tokens", 1024)
        provider = provider.lower()

        if provider == "openai":
            return dspy.OpenAI(model=model, max_tokens=max_tokens)
        elif provider == "anthropic":
            try:
                return dspy.Anthropic(model=model, max_tokens=max_tokens)
            except Exception:
                return dspy.LM(provider="anthropic", model=model, max_tokens=max_tokens)
        elif provider == "google":
            try:
                return dspy.Google(model=model, max_tokens=max_tokens)
            except Exception:
                return dspy.LM(provider="google", model=model, max_tokens=max_tokens)
        elif provider == "azure":
            return dspy.OpenAI(model=model, max_tokens=max_tokens)
        
        # Fallback to Generic Engine Shim
        engine = _make_engine(provider, LLMProfile.FAST, model)  # Profile doesn't matter for make_engine here
        return _DSPyEngineShim(engine)

    # ------------------ Orchestration methods ------------------

    def _resolve_profile(self, kind: DecisionKind, use_deep_hint: Optional[bool]) -> LLMProfile:
        """Determines the correct LLM profile based on decision kind and hints."""
        # 1. Explicit Hint Override (Legacy support)
        if use_deep_hint is True:
            return LLMProfile.DEEP
            
        # 2. Decision Kind Mapping
        if kind in (DecisionKind.COGNITIVE, DecisionKind.ESCALATED):
            return LLMProfile.DEEP
        
        # 3. Default
        return LLMProfile.FAST

    def _resolve_lm_engine(self, profile: LLMProfile, input_data: Dict[str, Any]) -> Any:
        """Resolves the LM Engine, handling per-request overrides."""
        params_cog = input_data.get("params", {}).get("cognitive", {})
        prov_override = params_cog.get("llm_provider_override") or input_data.get("llm_provider_override")
        mod_override = params_cog.get("llm_model_override") or input_data.get("llm_model_override")

        if prov_override or mod_override:
            config = self.core_configs.get(profile, {})
            target_prov = (prov_override or config.get("provider", "openai")).lower().strip()
            target_mod = (mod_override or config.get("model", "gpt-4o")).strip()
            
            logger.info(f"🔧 Override active: {target_prov}/{target_mod}")
            
            # Use the factory to create a lightweight LM object (not a whole core)
            temp_config = config.copy()
            temp_config["max_tokens"] = config.get("max_tokens", 1024)
            return self._create_dspy_lm(target_prov, target_mod, temp_config)

        # Default: Return cached LM from init
        config = self.core_configs.get(profile)
        if config and "_dspy_lm" in config:
            return config["_dspy_lm"]
            
        raise RuntimeError(f"No LM configuration found for profile {profile}")

    def _inject_telemetry(self, result: Dict, profile: LLMProfile, kind: DecisionKind, lm: Any):
        """Injects operational metadata into the result."""
        result.setdefault("result", {}).setdefault("meta", {})
        
        provider = getattr(lm, "provider", "unknown")
        model = getattr(lm, "model", "unknown")
        
        # Handle Shim/Engine wrapper
        if hasattr(lm, "engine"):
             model = getattr(lm.engine, "model", model)
             
        result["result"]["meta"].update({
            "profile_used": profile.value,
            "decision_kind": kind.value,
            "provider_used": provider,
            "model_used": model,
            "timestamp": time.time()
        })

    def _resolve_provider_env(self, profile_name: str) -> str:
        """Helper to get default providers from env."""
        # e.g. LLM_PROVIDER_FAST
        explicit = os.getenv(f"LLM_PROVIDER_{profile_name}")
        if explicit: 
            return explicit.lower()
        # Fallback to general LLM_PROVIDERS list or openai
        return "openai"

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
        return {
            "status": "healthy",
            "cores": {p.value: "active" for p in self.cores},
            "graph_repo": bool(self.graph_repo)
        }

    def shutdown(self):
        self._executor.shutdown(wait=True)

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
        """
        Executes a cognitive task with thread-safety and profile management.
        """
        try:
            # 1. Strategy: Resolve Profile
            decision_kind = context.decision_kind
            profile_key = self._resolve_profile(decision_kind, use_deep)
            
            # 2. Resource: Select Core
            core = self.cores.get(profile_key)
            if not core:
                return create_error_result(
                    f"No core available for profile {profile_key}", 
                    "SERVICE_UNAVAILABLE"
                ).model_dump()

            # 3. Resource: Resolve Engine (Handle Overrides)
            execution_lm = self._resolve_lm_engine(profile_key, context.input_data)

            # 4. Execution: Thread-Safe Context
            # This ensures that parallel requests do not clobber global settings
            import dspy  # type: ignore[reportMissingImports]
            
            if hasattr(dspy, 'context'):
                with dspy.context(lm=execution_lm):
                    logger.debug(f"⚡ Executing {context.cog_type.value} on {profile_key.value}")
                    raw_result = core.forward(context)
            else:
                # Fallback for older DSPy (Risky)
                logger.warning("dspy.context missing; using global settings.")
                dspy.settings.configure(lm=execution_lm)
                raw_result = core.forward(context)

            # 5. Metadata Injection
            result = normalize_task_payloads(raw_result)
            self._inject_telemetry(result, profile_key, decision_kind, execution_lm)

            return result

        except Exception as e:
            logger.exception(f"Orchestration Failed: {e}")
            return create_error_result(str(e), "COGNITIVE_EXECUTION_ERROR").model_dump()

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
# Note: Using TaskPayload directly for system-wide consistency
# Cognitive metadata is expected in params.cognitive namespace

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
    async def execute_cognitive_task(self, request: TaskPayload):
        """
        Executes a cognitive task using the standard TaskPayload.
        Expects input params to contain a 'cognitive' dictionary with metadata.
        """
        start_time = time.time()
        
        # 1. Validate Cognitive Metadata
        # TaskPayload guarantees .params is a dict, so we can access safely
        params = request.params
        cognitive_section = params.get("cognitive", {})
        
        if not cognitive_section:
            # Fail fast if the client didn't use the new execute_async standard
            raise HTTPException(
                status_code=400, 
                detail="Missing 'params.cognitive' metadata. Use CognitiveServiceClient."
            )
        
        # 2. Extract Required Fields
        agent_id = cognitive_section.get("agent_id")
        cog_type_str = cognitive_section.get("cog_type")
        
        if not agent_id or not cog_type_str:
            raise HTTPException(
                status_code=400, 
                detail="params.cognitive must contain 'agent_id' and 'cog_type'"
            )
        
        try:
            cog_type = CognitiveType(cog_type_str)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid cog_type: {cog_type_str}")
        
        # 3. Construct Cognitive Context
        # We use request.model_dump() to ensure we pass the full, validated structure
        # including any routing hints or drift scores that might be relevant to the planner.
        
        # Note: request.model_dump() triggers .to_db_params(), which packs routing info 
        # into params['routing']. This is exactly what we want.
        input_data = request.model_dump()
        
        # Extract overrides explicitly from the cognitive section (for backward compatibility)
        # The CognitiveContext will extract these from params.cognitive via its decision_kind property
        if "llm_provider_override" in cognitive_section:
            input_data["llm_provider_override"] = cognitive_section["llm_provider_override"]
        if "llm_model_override" in cognitive_section:
            input_data["llm_model_override"] = cognitive_section["llm_model_override"]
        
        try:
            # Create CognitiveContext using standard dataclass initialization
            # The decision_kind will be automatically extracted via the property
            context = CognitiveContext(
                agent_id=agent_id,
                cog_type=cog_type,
                input_data=input_data,  # Contains full TaskPayload structure with params.cognitive
            )

            # Use context.decision_kind property instead of manually extracting
            self.logger.info(
                f"/execute: Task {request.task_id} | Agent {agent_id} | "
                f"Type {cog_type.value} | Kind {context.decision_kind.value}"
            )

            # 4. Forward to Orchestrator (Off-thread)
            result_dict = await asyncio.to_thread(
                self.cognitive_service.forward_cognitive_task,
                context,
            )

            processing_time = (time.time() - start_time) * 1000
            
            # Log success/fail
            if not result_dict.get("success", False):
                self.logger.warning(
                    f"Task {request.task_id} failed in {processing_time:.2f}ms: {result_dict.get('error')}"
                )
            else:
                self.logger.info(
                    f"Task {request.task_id} completed in {processing_time:.2f}ms"
                )

            return CognitiveResponse(
                success=result_dict.get("success", False),
                result=result_dict.get("result", {}),
                error=result_dict.get("error"),
                metadata=result_dict.get("metadata", {}),
            )

        except HTTPException:
            # Re-raise HTTP exceptions as-is
            raise
        except Exception as e:
            # ... error handling remains the same ...
            processing_time = (time.time() - start_time) * 1000
            tb_str = traceback.format_exc()
            self.logger.error(f"FATAL: {e}\n{tb_str}")
            return CognitiveResponse(
                success=False, 
                result={}, 
                error=str(e), 
                metadata={"traceback": tb_str}
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
