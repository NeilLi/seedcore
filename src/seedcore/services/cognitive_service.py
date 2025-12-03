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

# 1) Standard library
import asyncio
import atexit
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Protocol

# 2) Third-party light deps (safe at import time)
import httpx  # type: ignore[reportMissingImports]
from fastapi import FastAPI, HTTPException  # type: ignore[reportMissingImports]
from pydantic import BaseModel  # type: ignore[reportMissingImports]
from ray import serve  # type: ignore[reportMissingImports]
import dspy  # pyright: ignore[reportMissingImports]
from openai import OpenAI  # pyright: ignore[reportMissingImports]

# 3) SeedCore internals (no heavy side effects)
from ..coordinator.utils import normalize_task_payloads
from ..cognitive.cognitive_core import CognitiveCore, Fact
from ..models.cognitive import (
    CognitiveContext, 
    CognitiveType, 
    DecisionKind, 
    LLMProfile
)
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

# Configure logging for driver process (script that invokes serve.run)
from seedcore.logging_setup import ensure_serve_logger, setup_logging

setup_logging(app_name="seedcore.cognitive_service.driver")
logger = ensure_serve_logger("seedcore.cognitive_service", level="DEBUG")

# -----------------------------------------------------------------------------
# 5) Provider-agnostic interfaces / helpers
# -----------------------------------------------------------------------------

# ------------------ Interfaces ------------------

class LLMEngine(Protocol):
    """Protocol ensures engines match the Shim's expectations."""
    model: str
    max_tokens: int
    
    def configure_for_dspy(self) -> Any: ...
    
    def generate(self, prompt: str, **kwargs) -> str: ...


class _DSPyEngineShim:
    """
    Adapts any engine exposing .generate(prompt, **kwargs) -> str to DSPy's API.
    """
    def __init__(self, engine: LLMEngine):
        self.engine = engine
        self.model = getattr(engine, 'model', 'unknown')
        # DSPy often looks for these attributes directly
        self.kwargs = {
            "temperature": getattr(engine, 'temperature', 0.7),
            "max_tokens": getattr(engine, 'max_tokens', 1024),
            "model": self.model
        }

    def __call__(self, prompt: str, **kwargs) -> List[str]:
        """
        DSPy calls the LM instance directly. 
        Returns a LIST of strings (completions).
        """
        return self.request(prompt, **kwargs)

    def request(self, prompt: str, **kwargs) -> List[str]:
        # Merge defaults with call-specific kwargs
        gen_kwargs = {**self.kwargs, **kwargs}
        
        # Remove DSPy specific args that might confuse the underlying engine
        gen_kwargs.pop("n", None) 
        
        logger.debug(f"Shim Request: model={self.model} prompt_len={len(prompt)}")
        
        # Call the underlying engine
        text = self.engine.generate(prompt, **gen_kwargs)
        
        # Return list for DSPy compatibility
        return [text]

    def configure_for_dspy(self):
        return self.engine.configure_for_dspy()

# ------------------ Engines ------------------

class OpenAIEngine:
    """
    Standard OpenAI wrapper. 
    If you use dspy.OpenAI directly, you don't need this. 
    But if you use the Shim, you MUST implement generate.
    """
    def __init__(self, model: str, max_tokens: int = 1024, api_key: str = None):
        self.model = model
        self.max_tokens = max_tokens
        self.client = OpenAI(api_key=api_key)

    def configure_for_dspy(self):
        pass

    def generate(self, prompt: str, **kwargs) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            temperature=kwargs.get("temperature", 0.7)
        )
        return response.choices[0].message.content


class MLServiceError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status

class MLServiceEngine:
    """Synchronous MLService engine."""
    def __init__(self, model: str, max_tokens: int = 1024, temperature: float = 0.7, base_url: str = None):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        
        # Base URL Logic
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            self.base_url = (os.getenv("MLS_BASE_URL") or "http://127.0.0.1:8000/ml").rstrip("/")

        # HTTP Client Setup
        self.timeout = float(os.getenv("MLS_TIMEOUT", "10.0"))
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            limits=httpx.Limits(
                max_keepalive_connections=int(os.getenv("MLS_MAX_KEEPALIVE", "20")),
                max_connections=int(os.getenv("MLS_MAX_CONNECTIONS", "100")),
            ),
            # ... (Limits config omitted for brevity, keep original)
        )
        self._closed = False

    def configure_for_dspy(self):
        pass

    def generate(self, prompt: str, **kwargs) -> str:
        if self._closed:
            raise MLServiceError("MLServiceEngine is closed")
            
        messages = [{"role": "user", "content": prompt}]
        
        # Safe kwargs merging
        req_params = {
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
            "model": self.model,
            "messages": messages
        }
        
        try:
            resp = self._client.post("/chat", json=req_params)
            resp.raise_for_status()
            data = resp.json()
            # Simplify response parsing
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"MLService Error: {e}")
            raise MLServiceError(str(e)) from e

    def close(self):
        if not self._closed:
            self._client.close()
            self._closed = True

class NimEngine:
    """
    NIM Engine wrapper. 
    Replaces 'NimDriverSDK' by handling OpenAI connections and artifact cleaning directly.
    """
    def __init__(self, model: str, base_url: str, api_key: str, max_tokens: int = 1024, temperature: float = 0.7, timeout: int = 60):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        
        # We can safely import this here or at the top level
        self.client = OpenAI(base_url=base_url.rstrip("/"), api_key=api_key, timeout=timeout)

    def configure_for_dspy(self):
        pass

    def _clean_text(self, text: str) -> str:
        """Strip formatting and control tokens (migrated from NimDriverSDK)."""
        return (
            text.replace("<|im_start|>", "")
            .replace("<|im_end|>", "")
            .replace("\\begin{code}", "")
            .replace("\\end{code}", "")
            .strip()
        )

    def generate(self, prompt: str, **kwargs) -> str:
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
        )
        
        raw_content = completion.choices[0].message.content
        return self._clean_text(raw_content)

# ----------------------------------------------------------------------
# CONFIGURATION & FACTORY
# ----------------------------------------------------------------------

def _default_max_tokens(profile: LLMProfile) -> int:
    return 2048 if profile == LLMProfile.DEEP else 1024

def _timeout(profile: LLMProfile, provider: str) -> int:
    # Simplified for example
    return 30 if profile == LLMProfile.DEEP else 10

# Revised PROVIDER_CONFIG
# We use 'factory' which is a Callable accepting (model, profile) and returning an Engine.
# This avoids the **kwargs injection confusion in _make_engine.

CACHEABLE_PROVIDERS = {"openai", "nim", "mlservice"}
NATIVE_DSPY_PROVIDERS = {"anthropic", "google", "azure"}

PROVIDER_CONFIG: Dict[str, Dict[str, Any]] = {
    "openai": {
        "env": {"deep": "OPENAI_MODEL_DEEP", "fast": "OPENAI_MODEL_FAST"},
        "defaults": {"deep": "gpt-4o", "fast": "gpt-4o-mini"},
        "factory": lambda model, profile: OpenAIEngine(
            model=model,
            max_tokens=_default_max_tokens(profile),
            api_key=os.getenv("OPENAI_API_KEY")
        ),
    },
    "nim": {
        "env": {"deep": "NIM_LLM_MODEL", "fast": "NIM_LLM_MODEL"},
        "defaults": {"deep": "meta/llama-3.1-8b-base", "fast": "meta/llama-3.1-8b-base"},
        "factory": lambda model, profile: NimEngine(
            model,
            os.getenv("NIM_LLM_BASE_URL"),
            os.getenv("NIM_LLM_API_KEY", "none"),
            max_tokens=_default_max_tokens(profile),
            temperature=0.7,
            timeout=_timeout(profile, "nim"),
        ),
    },
    "mlservice": {
        "env": {"deep": "MLS_MODEL_DEEP", "fast": "MLS_MODEL_FAST"},
        "defaults": {"deep": "llama3-70b", "fast": "llama3-8b"},
        "factory": lambda model, profile: MLServiceEngine(
            model=model,
            max_tokens=_default_max_tokens(profile),
            temperature=0.7
        ),
    },
    # For DSPy native providers, return None
    "anthropic": {
        "env": {"deep": "CLAUDE_DEEP", "fast": "CLAUDE_FAST"},
        "defaults": {"deep": "claude-3-opus", "fast": "claude-3-haiku"},
        "factory": lambda model, profile: None 
    },
    "google": {
        "env": {"deep": "GOOGLE_LLM_DEEP", "fast": "GOOGLE_LLM_FAST"},
        "defaults": {"deep": "gemini-1.5-pro", "fast": "gemini-1.5-flash"},
        "factory": lambda model, profile: None
    },
    "azure": {
        "env": {"deep": "AZURE_OPENAI_MODEL_DEEP", "fast": "AZURE_OPENAI_MODEL_FAST"},
        "defaults": {"deep": "gpt-4o", "fast": "gpt-4o-mini"},
        "factory": lambda model, profile: None
    },
}

def _normalize_list(val: Optional[str]) -> List[str]:
    """Split comma-separated provider lists into normalized tokens."""
    if not val:
        return []
    return [entry.strip().lower() for entry in val.split(",") if entry.strip()]


def _first_non_empty(*vals: Optional[str]) -> Optional[str]:
    """Return the first provided value that is not empty/whitespace."""
    for candidate in vals:
        if candidate and str(candidate).strip():
            return str(candidate).strip().lower()
    return None


def get_active_providers() -> List[str]:
    """Resolve the ordered list of active providers from env config."""
    return _normalize_list(os.getenv("LLM_PROVIDERS", ""))


def _default_provider_deep() -> str:
    """
    Resolve provider for DEEP profile honoring overrides/list defaults.
    Priority: LLM_PROVIDER_DEEP > LLM_PROVIDER > LLM_PROVIDERS[0] > openai
    """
    explicit = os.getenv("LLM_PROVIDER_DEEP")
    if explicit and explicit.strip():
        return explicit.strip().lower()

    general = os.getenv("LLM_PROVIDER")
    if general and general.strip():
        return general.strip().lower()

    providers = get_active_providers()
    if providers:
        return providers[0]

    return "openai"


def _default_provider_fast() -> str:
    """
    Resolve provider for FAST profile honoring overrides/list defaults.
    Priority: LLM_PROVIDER_FAST > LLM_PROVIDER > LLM_PROVIDERS[0] > openai
    """
    explicit = os.getenv("LLM_PROVIDER_FAST")
    if explicit and explicit.strip():
        return explicit.strip().lower()

    general = os.getenv("LLM_PROVIDER")
    if general and general.strip():
        return general.strip().lower()

    providers = get_active_providers()
    if providers:
        return providers[0]

    return "openai"

def _model_for(provider: str, profile: LLMProfile) -> str:
    config = PROVIDER_CONFIG.get(provider)
    if not config: return "gpt-4o"  # noqa: E701
    
    pf_key = profile.value
    env_var = config["env"].get(pf_key)
    default_model = config["defaults"].get(pf_key)
    
    return _first_non_empty(os.getenv(env_var) if env_var else None, default_model, "gpt-3.5-turbo")

class CognitiveOrchestrator:
    """
    The STRATEGY Layer (Tier-1 Manager).
    
    Responsibilities:
    1. Resource Management: Allocates Fast vs Deep profiles.
    2. Context Isolation: Ensures thread-safe execution via dspy.context.
    3. Data Access: Initializes repositories for Server-Side Hydration.
    4. Governance: Applies circuit breakers and timeouts.
    """

    def __init__(
        self,
        ocps_client=None,
        *,
        fast_pool_size: int = 8,
        deep_pool_size: int = 2,
    ):
        self.ocps_client = ocps_client
        self.schema_version = "v2.2"

        # Cache of DSPy LM instances (lazy-initialized)
        self.lms: Dict[LLMProfile, Any] = {}
        self.lm_lock = threading.Lock()

        # Track desired pool sizes for rebuild/reset flows
        self.pool_sizes: Dict[LLMProfile, int] = {
            LLMProfile.FAST: fast_pool_size,
            LLMProfile.DEEP: deep_pool_size,
        }
        self.circuit_breakers: Dict[str, Any] = {}
        
        # Configurable Thread Pool
        max_workers = int(os.getenv("COGNITIVE_MAX_WORKERS", "8"))
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        atexit.register(self.shutdown)

        # ----------------------------
        # Hydration Resources
        # ----------------------------
        if TaskMetadataRepository and get_async_session_maker:
            try:
                self.graph_repo = TaskMetadataRepository()
                self.session_maker = get_async_session_maker()
                logger.info("✅ Connected to Graph Repository + DB (hydration enabled)")
            except Exception as e:
                self.graph_repo = None
                self.session_maker = None
                logger.warning(f"⚠️ Hydration Layer Disabled: {e}")
        else:
            self.graph_repo = None
            self.session_maker = None
            logger.warning("⚠️ Hydration Layer Disabled: repository or session factory missing")

        # ----------------------------
        # Initialize Core Pools
        # ----------------------------
        self.core_pools: Dict[LLMProfile, List[CognitiveCore]] = {
            profile: self._make_cores(profile, size)
            for profile, size in self.pool_sizes.items()
        }
        
        # round-robin counters
        self.rr_counter = {p: 0 for p in self.core_pools.keys()}

        # congestion thresholds
        self.queue_threshold = {
            LLMProfile.FAST: 80,
            LLMProfile.DEEP: 20,
        }
        # self._initialize_cores()

        logger.info("🌐 Cognitive Orchestrator v2 ready")

        # ============================================================================
    # 🏗️ Core Construction
    # ============================================================================
    def _make_cores(self, profile: LLMProfile, count: int) -> List[CognitiveCore]:
        """Create a pool of CognitiveCore instances for a given profile."""
        pool = []
        for i in range(count):
            core = CognitiveCore(
                profile=profile,
                ocps_client=self.ocps_client,
                graph_repo=self.graph_repo,
                session_maker=self.session_maker,
            )
            pool.append(core)
            logger.info(f"🧠 Initialized {profile.value} worker #{i+1}")
        return pool

    # ============================================================================
    # 🔁 Load Balancing (Round Robin)
    # ============================================================================
    def _next_core(self, profile: LLMProfile) -> Optional[CognitiveCore]:
        pool = self.core_pools.get(profile) or []
        if not pool:
            return None

        idx = self.rr_counter[profile] % len(pool)
        self.rr_counter[profile] += 1
        return pool[idx]

    # ============================================================================
    # 📉 Congestion-Aware Downgrade
    # ============================================================================
    def _maybe_downgrade(self, profile: LLMProfile) -> LLMProfile:
        pool = self.core_pools.get(profile)
        if not pool:
            return profile

        qsize = sum(getattr(c, "pending_requests", 0) for c in pool if c)

        if qsize <= self.queue_threshold[profile]:
            return profile

        # downgrade rules
        if profile == LLMProfile.DEEP:
            logger.warning("⬇️ DEEP overloaded → downgrade to FAST")
            return LLMProfile.FAST

        return profile

    def _create_dspy_lm(self, provider: str, model: str, profile: LLMProfile) -> Any:
        """
        Universal Factory: Creates a DSPy-compatible LM object.
        Uses PROVIDER_CONFIG factories via _make_engine logic where possible.
        """
        provider = provider.lower()
        
        # 1. Try to use our central factory registry first
        # We manually retrieve the factory here to support 'model' overrides 
        # that _make_engine's default internal resolution might miss.
        # 1. Custom Engines (Nim, MLService, OpenAI-via-Shim)
        # We check PROVIDER_CONFIG directly so we can pass the SPECIFIC 'model' arg
        config = PROVIDER_CONFIG.get(provider)
        factory = config.get("factory") if config else None

        if factory:
            # We call the factory with the OVERRIDE model, not the default env var model
            engine = factory(model, profile)
            
            # If the factory returns an engine, wrap it in the Shim
            if engine:
                # Apply late-binding temperature if supported (optional)
                if hasattr(engine, 'temperature'):
                    engine.temperature = 0.7 
                return _DSPyEngineShim(engine)

        # 2. Native DSPy Providers (Anthropic, Google, Azure)
        # These return None from the factory (or have no factory)
        max_tokens = 2048 if profile == LLMProfile.DEEP else 1024
        
        if provider == "anthropic":
            return dspy.Anthropic(
                model=model, 
                max_tokens=max_tokens, 
                api_key=os.getenv("ANTHROPIC_API_KEY")
            )
        elif provider == "google":
            return dspy.Google(
                model=model, 
                max_tokens=max_tokens, 
                api_key=os.getenv("GOOGLE_API_KEY")
            )
        elif provider == "azure":
            return dspy.AzureOpenAI(model=model, max_tokens=max_tokens)

        # 3. Last Resort Fallback
        # If we get here, it's an unknown provider or a configuration error.
        logger.warning(f"Provider '{provider}' not recognized via factory. Defaulting to OpenAI/Shim.")
        
        # Force usage of the OpenAI factory with the requested model
        openai_factory = PROVIDER_CONFIG["openai"]["factory"]
        return _DSPyEngineShim(openai_factory(model, profile))


    def _resolve_lm_engine(self, profile: LLMProfile, params: dict) -> Any:
        """
        Determines the correct LM for the request.
        Priority:
        1. Request params Overrides (Creates fresh, temporary LM)
        2. Cached Default for Profile (Uses self.lms)
        """
        # --- Path A: Handle Overrides (Fresh Instance) ---
        ov_provider = params.get("llm_provider_override")
        ov_model = params.get("llm_model_override")

        if ov_provider or ov_model:
            # 1. Resolve Provider (Override -> Profile Default)
            target_prov = ov_provider
            if not target_prov:
                # Use global helpers to find default provider for this profile
                target_prov = _default_provider_deep() if profile == LLMProfile.DEEP else _default_provider_fast()
            
            # 2. Resolve Model (Override -> Profile Default)
            target_mod = ov_model
            if not target_mod:
                # Use global helper to find default model for this provider/profile
                target_mod = _model_for(target_prov, profile)

            logger.info(f"🔧 Request Override: {target_prov}/{target_mod}")
            return self._create_dspy_lm(target_prov, target_mod, profile)

        # --- Path B: Handle Defaults (Cached Instance) ---

        # Return cached instance if available
        with self.lm_lock:
            cached_lm = self.lms.get(profile)
        if cached_lm:
            return cached_lm

        # Calculate Defaults
        default_provider = _default_provider_deep() if profile == LLMProfile.DEEP else _default_provider_fast()
        default_model = _model_for(default_provider, profile)

        logger.info(f"⚙️  Initializing Default LM for {profile.name}: {default_provider}/{default_model}")
        
        # Create and Cache
        lm = self._create_dspy_lm(default_provider, default_model, profile)

        if default_provider in CACHEABLE_PROVIDERS:
            with self.lm_lock:
                self.lms[profile] = lm
        
        return lm

    def _inject_telemetry(self, result: Dict, profile: LLMProfile, kind: DecisionKind, lm: Any):
        """Injects operational metadata into the result."""
        result.setdefault("result", {}).setdefault("meta", {})
        
        provider = getattr(lm, "provider", "unknown")
        model = getattr(lm, "model", "unknown")
        
        # Map DSPy native providers explicitly (they don't expose .provider)
        anthropic_cls = getattr(dspy, "Anthropic", None)
        google_cls = getattr(dspy, "Google", None)
        if anthropic_cls and isinstance(lm, anthropic_cls):
            provider = "anthropic"
        elif google_cls and isinstance(lm, google_cls):
            provider = "google"
        
        # Handle Shim/Engine wrapper
        if hasattr(lm, "engine"):
             model = getattr(lm.engine, "model", model)
             provider = getattr(lm.engine, "provider", provider)
             
        result["result"]["meta"].update({
            "profile_used": profile.value,
            "decision_kind": kind.value,
            "provider_used": provider,
            "model_used": model,
            "timestamp": time.time()
        })

    def _determine_profile(self, decision: DecisionKind, params: dict) -> LLMProfile:
        """Maps DecisionKind to Profile."""
        # 1. Check explicit params override logic
        if params.get("force_deep_reasoning"):
            return LLMProfile.DEEP
        if params.get("force_fast"):
            return LLMProfile.FAST
            
        # 2. Map kinds
        if decision in (DecisionKind.COGNITIVE, DecisionKind.ESCALATED):
            return LLMProfile.DEEP
            
        return LLMProfile.FAST

    def shutdown(self):
        self._executor.shutdown(wait=True)

    def forward_cognitive_task(self, context: 'CognitiveContext') -> Dict[str, Any]:
        """
        Executes a cognitive task with thread-safety and profile management.
        """
        try:
            # 1. Strategy: Resolve Profile
            decision_kind = context.decision_kind
            params = context.input_data.get("params", {}).get("cognitive", {})
            profile = self._determine_profile(decision_kind, params)
            profile = self._maybe_downgrade(profile)
            
            # 3. Pick next worker
            core = self._next_core(profile)

            if not core:
                return create_error_result(
                    f"No core available for profile {profile}", 
                    "SERVICE_UNAVAILABLE"
                ).model_dump()

            # 3. Resource: Resolve Engine (Handle Overrides)
            execution_lm = self._resolve_lm_engine(profile, params)

            # 4. Execution: Thread-Safe Context
            # This ensures that parallel requests do not clobber global settings
            import dspy  # type: ignore[reportMissingImports]
            
            if hasattr(dspy, 'context'):
                with dspy.context(lm=execution_lm):
                    logger.debug(f"⚡ Executing {context.cog_type.value} on {profile.value}")
                    raw_result = core.forward(context)
            else:
                # Fallback for older DSPy (Risky)
                logger.warning("dspy.context missing; using global settings.")
                dspy.settings.configure(lm=execution_lm)
                raw_result = core.forward(context)

            # 5. Metadata Injection
            result = normalize_task_payloads(raw_result)
            self._inject_telemetry(result, profile, decision_kind, execution_lm)

            return result

        except Exception as e:
            logger.exception(f"Orchestration Failed: {e}")
            return create_error_result(str(e), "COGNITIVE_EXECUTION_ERROR").model_dump()

    def build_fragments_for_synthesis(self, context: 'CognitiveContext', facts: List['Fact'], summary: str) -> List[Dict[str, Any]]:
        fast_pool = self.core_pools.get(LLMProfile.FAST) or []
        if not fast_pool:
            logger.warning("No FAST cores available for build_fragments_for_synthesis")
            return []

        core = fast_pool[0]
        try:
            return core.build_fragments_for_synthesis(context, facts, summary)
        except Exception as e:
            logger.error(f"Error building synthesis fragments: {e}")
            return []

    def get_cognitive_core(self) -> Optional['CognitiveCore']:
        fast_pool = self.core_pools.get(LLMProfile.FAST) or []
        return fast_pool[0] if fast_pool else None

    def reset_cognitive_core(self):
        """
        Reset or rebuild CognitiveCore pools without tearing down the entire orchestrator.
        """
        new_pools: Dict[LLMProfile, List[CognitiveCore]] = {}

        for profile, pool in self.core_pools.items():
            refreshed_pool: List[CognitiveCore] = []
            for core in pool:
                if not core:
                    continue

                if hasattr(core, "reset"):
                    try:
                        core.reset()
                        refreshed_pool.append(core)
                        continue
                    except Exception as exc:
                        logger.warning(f"Failed to reset core ({profile.value}): {exc}")
                # Core cannot be reset; drop and replace below

            desired = self.pool_sizes.get(profile, len(pool) or 1)
            deficit = max(desired - len(refreshed_pool), 0)
            if deficit:
                refreshed_pool.extend(self._make_cores(profile, deficit))

            new_pools[profile] = refreshed_pool

        self.core_pools = new_pools
        self.rr_counter = {p: 0 for p in self.core_pools.keys()}
        with self.lm_lock:
            self.lms.clear()

        if hasattr(self, "circuit_breakers"):
            self.circuit_breakers.clear()

        logger.info("All cognitive cores reset")

    def initialize_cognitive_core(self) -> Optional['CognitiveCore']:
        logger.warning("initialize_cognitive_core() deprecated in multi-profile system")
        fast_pool = self.core_pools.get(LLMProfile.FAST) or []
        return fast_pool[0] if fast_pool else None
    
    def health_check(self) -> Dict[str, Any]:
        """Returns the health status of the orchestrator and its pools."""
        status = {
            "status": "healthy",
            "pools": {},
            "hydration": "enabled" if self.session_maker else "disabled"
        }
        
        # Check Thread Pool
        if self._executor._shutdown:
             status["status"] = "unhealthy"
             status["error"] = "Thread pool is shutdown"

        # Check Core Pools
        total_cores = 0
        for profile, pool in self.core_pools.items():
            active_count = len([c for c in pool if c])
            status["pools"][profile.value] = {
                "active": active_count,
                "target": self.pool_sizes.get(profile, 0)
            }
            total_cores += active_count

        if total_cores == 0:
            status["status"] = "degraded"
            status["warning"] = "No cognitive cores available"

        return status
    

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
        CognitiveCore v2 endpoint.
        Executes cognitive tasks using the final TaskPayload v2 contract.

        Required structure (enforced):
            params.cognitive = {
                agent_id: str,
                cog_type: str (CognitiveType),
                decision_kind: str (DecisionKind),
                ...
            }

        Notes:
        - ChatSignature requires params.chat.{message, history}
        - Conversation history MUST be a list of dicts (not JSON strings)
        - All cognitive metadata is taken ONLY from params.cognitive
        """

        start_time = time.time()

        # ----------------------------------------------------------------------
        # 1. Extract and validate cognitive metadata
        # ----------------------------------------------------------------------
        params = request.params or {}
        cognitive_section = params.get("cognitive")

        if not cognitive_section:
            raise HTTPException(
                status_code=400,
                detail="Missing required 'params.cognitive'. "
                    "Use CognitiveServiceClient / TaskPayload v2."
            )

        agent_id = cognitive_section.get("agent_id")
        cog_type_raw = cognitive_section.get("cog_type")
        decision_kind_raw = cognitive_section.get("decision_kind")

        if not agent_id or not cog_type_raw:
            raise HTTPException(
                status_code=400,
                detail="params.cognitive must contain both 'agent_id' and 'cog_type'."
            )

        # Parse correct enums
        try:
            cog_type = CognitiveType(cog_type_raw)
        except Exception:
            raise HTTPException(400, detail=f"Invalid cog_type={cog_type_raw}")

        try:
            decision_kind = DecisionKind(decision_kind_raw)
        except Exception:
            raise HTTPException(400, detail=f"Invalid decision_kind={decision_kind_raw}")

        # ----------------------------------------------------------------------
        # 2. Construct the input_data that gets fed into signatures
        # ----------------------------------------------------------------------
        # model_dump() will properly pack routing into params.routing
        input_data = request.model_dump()

        # ----------------------------------------------------------------------
        # 3. Build CognitiveContext (strict v2)
        # ----------------------------------------------------------------------
        context = CognitiveContext(
            agent_id=agent_id,
            cog_type=cog_type,
            input_data=input_data,
        )

        self.logger.info(
            f"[CognitiveCore] Task {request.task_id} | "
            f"Agent={agent_id} | CogType={cog_type.value} | Kind={decision_kind.value}"
        )

        # ----------------------------------------------------------------------
        # 4. Execute using CognitiveService orchestrator
        # ----------------------------------------------------------------------
        try:
            result_dict = await asyncio.to_thread(
                self.cognitive_service.forward_cognitive_task,
                context
            )
        except HTTPException:
            raise
        except Exception as e:
            tb_str = traceback.format_exc()
            self.logger.error(f"[CognitiveCore Fatal] {e}\n{tb_str}")
            return CognitiveResponse(
                success=False,
                result={},
                error=str(e),
                metadata={"traceback": tb_str},
            )

        # ----------------------------------------------------------------------
        # 5. Prepare Response (CognitiveResponse)
        # ----------------------------------------------------------------------
        processing_time = (time.time() - start_time) * 1000
        ok = result_dict.get("success", False)

        if ok:
            self.logger.info(
                f"[CognitiveCore] Task {request.task_id} completed in {processing_time:.2f}ms"
            )
        else:
            self.logger.warning(
                f"[CognitiveCore] Task {request.task_id} FAILED in {processing_time:.2f}ms: "
                f"{result_dict.get('error')}"
            )

        return CognitiveResponse(
            success=ok,
            result=result_dict.get("result", {}),
            error=result_dict.get("error"),
            metadata=result_dict.get("metadata", {}),
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
