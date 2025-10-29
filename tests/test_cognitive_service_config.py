import logging

import pytest

from src.seedcore.services.cognitive_service import (
    CognitiveService,
    LLMProfile,
    _default_provider_deep,
)


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Ensure provider-related env vars are cleared between tests."""
    for var in ("LLM_PROVIDER_DEEP", "LLM_PROVIDER", "LLM_PROVIDER_FAST", "LLM_PROVIDERS"):
        monkeypatch.delenv(var, raising=False)
    yield


def test_default_provider_deep_respects_explicit(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_DEEP", "Anthropic")

    assert _default_provider_deep() == "anthropic"


def test_default_provider_deep_ignores_global(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    assert _default_provider_deep() == "openai"


def test_cognitive_service_enforces_openai_deep(monkeypatch, caplog):
    monkeypatch.setenv("LLM_PROVIDER_DEEP", "anthropic")
    monkeypatch.setattr(CognitiveService, "_initialize_cores", lambda self: None)

    with caplog.at_level(logging.WARNING):
        service = CognitiveService()

    deep_profile = service.profiles[LLMProfile.DEEP]
    assert deep_profile["provider"] == "openai"
    assert any("forcing 'openai'" in record.getMessage().lower() for record in caplog.records)
