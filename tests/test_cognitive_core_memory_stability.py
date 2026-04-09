from __future__ import annotations

import sys
import threading
import types

if "dspy" not in sys.modules:
    dspy_mod = types.ModuleType("dspy")

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

    dspy_mod.InputField = _Field
    dspy_mod.OutputField = _Field
    dspy_mod.Signature = _Signature
    dspy_mod.Module = _Module
    dspy_mod.Predict = _Noop
    dspy_mod.ChainOfThought = _Noop
    sys.modules["dspy"] = dspy_mod

from seedcore.cognitive.cognitive_core import CognitiveCore  # noqa: E402
from seedcore.models.cognitive import CognitiveContext, CognitiveType


def _make_core() -> CognitiveCore:
    core = CognitiveCore.__new__(CognitiveCore)
    core._state_lock = threading.RLock()
    core._mw_enabled = True
    core._mw_by_agent = {}
    core.memory_bridges = {}
    core.scope_resolvers = {}
    core.cognitive_retrievals = {}
    core.scope_resolver = None
    core.cognitive_retrieval = object()
    core.semantic_memory = None
    core.holon_fabric = None
    core.synopsis_embedder = None
    core._memory_bridge_degradation_counts = {}
    return core


def test_try_initialize_memory_bridge_cold_start_uses_lazy_mw_creation(monkeypatch):
    core = _make_core()
    captured = {"mw_called": 0}

    class _FakeLogger:
        def getChild(self, _name: str):
            return self

        def info(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

        def debug(self, *args, **kwargs):
            return None

        def exception(self, *args, **kwargs):
            return None

    monkeypatch.setattr("seedcore.cognitive.cognitive_core.logger", _FakeLogger())

    class _FakeBridge:
        def __init__(self, **kwargs):
            self.agent_id = kwargs["agent_id"]
            self.organ_id = kwargs.get("organ_id")

    monkeypatch.setattr(
        "seedcore.cognitive.cognitive_core.CognitiveMemoryBridge",
        _FakeBridge,
    )
    monkeypatch.setattr(
        "seedcore.cognitive.cognitive_core.MwManager",
        lambda organ_id: {"organ_id": organ_id},
    )

    def _fake_mw(agent_id: str):
        captured["mw_called"] += 1
        return {"agent_id": agent_id}

    monkeypatch.setattr(core, "_mw", _fake_mw)
    ok = core._try_initialize_memory_bridge(agent_id="agent-1", organ_id="organ-1")
    assert ok is True
    assert captured["mw_called"] == 1
    assert "agent-1" in core.memory_bridges


def test_build_fallback_knowledge_context_sets_degraded_flags():
    core = _make_core()
    ctx = CognitiveContext(
        agent_id="agent-2",
        cog_type=CognitiveType.CHAT,
        input_data={"task_id": "task-1", "params": {}},
    )
    out = core._build_fallback_knowledge_context(
        context=ctx,
        params={},
        chat_history=[],
        cog_flags={},
        reason="bridge unavailable",
        reason_code="bridge_unavailable",
    )
    assert out["memory_bridge_degraded"] is True
    assert out["memory_bridge_reason"] == "bridge_unavailable"


def test_construct_bridged_knowledge_context_does_not_set_degraded_flags():
    core = _make_core()
    ctx = CognitiveContext(
        agent_id="agent-3",
        cog_type=CognitiveType.PROBLEM_SOLVING,
        input_data={},
    )
    hydrated_task = {"params": {"context": {"holons": [], "chat_history": [], "token_budget": 3}}}
    out = core._construct_bridged_knowledge_context(
        context=ctx,
        hydrated_task=hydrated_task,
        initial_chat_history=[],
        cog_flags={},
    )
    assert "memory_bridge_degraded" not in out
    assert "memory_bridge_reason" not in out
