"""
Provider registry for multi-provider LLM orchestration.

- Supports: openai, anthropic, google, azure, local, nim
- Reads providers from env var `LLM_PROVIDERS` (comma-separated),
  falls back to legacy `LLM_PROVIDER` when unset.
"""

from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional


class LLMRegistry:
    _providers: Dict[str, Callable[[], object]] = {}

    @classmethod
    def register(cls, name: str, factory: Callable[[], object]) -> None:
        if not name:
            raise ValueError("Provider name must be non-empty")
        cls._providers[name.lower()] = factory

    @classmethod
    def get(cls, name: str) -> object:
        key = (name or "").lower()
        if key not in cls._providers:
            supported = ", ".join(sorted(cls._providers))
            raise ValueError(f"Unsupported provider: {name}. Supported: {supported}")
        return cls._providers[key]()


def _normalize_list(value: Optional[str]) -> List[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# ------- Provider factories -------
def _openai_client_factory() -> object:
    try:
        import openai  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("openai package is required for provider 'openai'") from exc

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    # Modern client
    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=api_key)
        api_base = os.getenv("LLM_API_BASE")
        if api_base:
            client = OpenAI(api_key=api_key, base_url=api_base)
        return client
    except Exception:
        # Fallback to legacy global config
        openai.api_key = api_key
        if os.getenv("LLM_API_BASE"):
            openai.api_base = os.getenv("LLM_API_BASE")
        return openai


def _anthropic_client_factory() -> object:
    try:
        import anthropic  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("anthropic package is required for provider 'anthropic'") from exc

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key)


def _nim_client_factory() -> object:
    # NIM uses OpenAI-compatible API schema
    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("openai package is required for provider 'nim'") from exc

    endpoint = (
        os.getenv("NIM_ENDPOINT")
        or os.getenv("NIM_LLM_BASE_URL")
        or "http://seedcore-nim-svc:8080/v1"
    )
    api_key = (
        os.getenv("NIM_LLM_API_KE")
        or os.getenv("NIM_API_KEY")
        or os.getenv("LLM_API_KEY")
        or ""
    )
    # Some NIM deployments accept empty/placeholder API keys
    client = OpenAI(base_url=endpoint, api_key=api_key or "none")
    return client


# Register built-in providers
LLMRegistry.register("openai", _openai_client_factory)
LLMRegistry.register("anthropic", _anthropic_client_factory)
LLMRegistry.register("nim", _nim_client_factory)


# ------- Active providers -------
def get_active_providers() -> List[str]:
    providers = _normalize_list(os.getenv("LLM_PROVIDERS"))
    if providers:
        return [p.lower() for p in providers]
    # Back-compat with legacy single-provider
    legacy = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    return [legacy]


# ------- Agent mapping -------
_DEFAULT_AGENT_CONFIG: Dict[str, str] = {
    "reasoning": "openai",
    "planning": "anthropic",
    "embedding": "nim",
    "reflection": "openai",
}


def get_llm_for(agent_role: str, agent_config: Optional[Dict[str, str]] = None) -> object:
    config = agent_config or _DEFAULT_AGENT_CONFIG
    active = get_active_providers()
    provider_name = config.get(agent_role) or (active[0] if active else "openai")
    return LLMRegistry.get(provider_name)


__all__ = [
    "LLMRegistry",
    "get_active_providers",
    "get_llm_for",
]


