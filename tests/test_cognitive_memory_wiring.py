"""Shared semantic-memory wiring for cognitive core/orchestrator."""

from __future__ import annotations

import sys
import types
import importlib

import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

if "dspy" not in sys.modules:
    mod = types.ModuleType("dspy")

    class _Field:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _Signature:
        pass

    class _Module:
        pass

    class _Noop:
        def __init__(self, *args, **kwargs):
            pass

    mod.InputField = _Field
    mod.OutputField = _Field
    mod.Signature = _Signature
    mod.Module = _Module
    mod.Predict = _Noop
    mod.ChainOfThought = _Noop
    sys.modules["dspy"] = mod

if "openai" not in sys.modules:
    openai_mod = types.ModuleType("openai")

    class _OpenAI:
        def __init__(self, *args, **kwargs):
            pass

    openai_mod.OpenAI = _OpenAI
    sys.modules["openai"] = openai_mod

def _import_cognitive_modules():
    saved: dict[str, types.ModuleType] = {}
    for key in list(sys.modules):
        if key == "seedcore.cognitive" or key.startswith("seedcore.cognitive."):
            saved[key] = sys.modules.pop(key)
    try:
        core_mod = importlib.import_module("seedcore.cognitive.cognitive_core")
        cs_mod = importlib.import_module("seedcore.services.cognitive_service")
        return core_mod, cs_mod
    finally:
        sys.modules.update(saved)


class _FakeSemantic:
    def __init__(self, fabric: object) -> None:
        self.holon_fabric = fabric


def test_cognitive_core_attach_shared_semantic_memory_sets_fields():
    core_mod, _ = _import_cognitive_modules()
    core_cls = core_mod.CognitiveCore
    core = core_cls.__new__(core_cls)
    fabric = object()
    semantic = _FakeSemantic(fabric)
    core.attach_shared_semantic_memory(semantic)  # type: ignore[arg-type]
    assert core.semantic_memory is semantic
    assert core.holon_fabric is fabric


def test_orchestrator_passes_shared_semantic_memory_to_cores(monkeypatch):
    _, cs = _import_cognitive_modules()
    calls: list[dict] = []

    class _FakeCore:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(cs, "CognitiveCore", _FakeCore)

    semantic = _FakeSemantic(object())
    cs.CognitiveOrchestrator(
        fast_pool_size=1,
        deep_pool_size=1,
        semantic_memory=semantic,  # type: ignore[arg-type]
    )

    assert len(calls) == 2
    assert all(call.get("semantic_memory") is semantic for call in calls)


def test_initialize_cognitive_service_passes_semantic_memory(monkeypatch):
    _, cs = _import_cognitive_modules()
    cs.COGNITIVE_SERVICE_INSTANCE = None

    captured: dict[str, object] = {}

    class _FakeOrchestrator:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(cs, "CognitiveOrchestrator", _FakeOrchestrator)

    semantic = _FakeSemantic(object())
    service = cs.initialize_cognitive_service(semantic_memory=semantic)  # type: ignore[arg-type]
    assert service is not None
    assert captured.get("semantic_memory") is semantic


def test_initialize_cognitive_service_without_semantic_memory_is_backward_compatible(monkeypatch):
    _, cs = _import_cognitive_modules()
    cs.COGNITIVE_SERVICE_INSTANCE = None

    captured: dict[str, object] = {}

    class _FakeOrchestrator:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(cs, "CognitiveOrchestrator", _FakeOrchestrator)
    service = cs.initialize_cognitive_service()
    assert service is not None
    assert "semantic_memory" in captured
    assert captured["semantic_memory"] is None


def test_initialize_cognitive_service_late_binds_semantic_memory_on_existing_singleton(monkeypatch):
    _, cs = _import_cognitive_modules()

    class _FakeInstance:
        def __init__(self) -> None:
            self.calls = []

        def attach_shared_semantic_memory(self, semantic_memory):
            self.calls.append(semantic_memory)

    instance = _FakeInstance()
    cs.COGNITIVE_SERVICE_INSTANCE = instance

    semantic = _FakeSemantic(object())
    service = cs.initialize_cognitive_service(semantic_memory=semantic)  # type: ignore[arg-type]
    assert service is instance
    assert instance.calls == [semantic]


def test_orchestrator_health_check_aggregates_memory_bridge_degradation_counts(monkeypatch):
    _, cs = _import_cognitive_modules()

    class _FakeCore:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.pending_requests = 0

        def get_memory_bridge_degradation_counts(self):
            return {"bridge_unavailable": 2, "post_exec_failed": 1}

    monkeypatch.setattr(cs, "CognitiveCore", _FakeCore)
    orchestrator = cs.CognitiveOrchestrator(fast_pool_size=1, deep_pool_size=1)
    health = orchestrator.health_check()
    assert health["memory_bridge_degradation_counts"]["bridge_unavailable"] == 4
    assert health["memory_bridge_degradation_counts"]["post_exec_failed"] == 2
