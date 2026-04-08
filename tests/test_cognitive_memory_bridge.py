"""CognitiveMemoryBridge uses WorkingMemory + SemanticMemory contracts."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_MB_PATH = _ROOT / "src" / "seedcore" / "cognitive" / "memory_bridge.py"
_mod_name = "seedcore.cognitive.memory_bridge"
for _pkg in ("seedcore", "seedcore.cognitive"):
    if _pkg not in sys.modules:
        _m = types.ModuleType(_pkg)
        _m.__path__ = []
        sys.modules[_pkg] = _m
_spec = importlib.util.spec_from_file_location(_mod_name, _MB_PATH)
assert _spec and _spec.loader
_mb_mod = importlib.util.module_from_spec(_spec)
_mb_mod.__package__ = "seedcore.cognitive"
sys.modules[_mod_name] = _mb_mod
_spec.loader.exec_module(_mb_mod)
CognitiveMemoryBridge = _mb_mod.CognitiveMemoryBridge


class _ScopeResolver:
    def resolve(
        self, *, agent_id: str, organ_id: Optional[str], task_params: Dict[str, Any]
    ):
        return (["GLOBAL"], [])


class _FakeWorking:
    def __init__(self) -> None:
        self.puts: List[tuple] = []
        self.global_puts: List[tuple] = []
        self.episodes: List[Any] = []

    def put(self, key: str, value: Any, ttl_s: Optional[int] = None) -> None:
        self.puts.append((key, value, ttl_s))

    def put_global_typed(
        self,
        kind: str,
        scope: str,
        item_id: str,
        value: Any,
        ttl_s: Optional[int] = None,
    ) -> None:
        self.global_puts.append((kind, scope, item_id, value, ttl_s))

    async def append_episode(
        self,
        *,
        agent_id: str,
        episode: Any,
        ttl_s: Optional[int] = None,
        max_items: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        self.episodes.append(episode)
        return []

    async def get_recent_episode(
        self, *, organ_id: Optional[str], agent_id: str, k: int = 10
    ) -> List[Dict[str, Any]]:
        return []


class _FakeEmbedder:
    def embed(self, text: str) -> List[float]:
        return [0.0] * 1024


@pytest.mark.asyncio
async def test_process_post_execution_promotes_via_semantic_memory():
    working = _FakeWorking()
    upserts: List[Any] = []

    class _Sem:
        async def upsert_holon(self, holon: Any) -> None:
            upserts.append(holon)

    retrieval = AsyncMock()
    retrieval.query_context = AsyncMock(return_value=[])

    bridge = CognitiveMemoryBridge(
        agent_id="agent-1",
        organ_id="organ-1",
        working=working,
        semantic=_Sem(),
        embedder=_FakeEmbedder(),
        scope_resolver=_ScopeResolver(),
        retrieval=retrieval,
    )

    await bridge.process_post_execution(
        task={"type": "test", "description": "Do the thing"},
        result={
            "task_id": "tid-42",
            "success": True,
            "results": {"ok": True},
            "quality": 0.95,
        },
    )

    assert len(working.puts) >= 1
    assert len(working.global_puts) >= 1
    assert len(working.episodes) >= 1
    assert len(upserts) == 1
    assert upserts[0].id == "task:tid-42"
    assert upserts[0].type.value == "episode"


@pytest.mark.asyncio
async def test_promotion_skipped_without_semantic():
    working = _FakeWorking()
    retrieval = AsyncMock()
    retrieval.query_context = AsyncMock(return_value=[])

    bridge = CognitiveMemoryBridge(
        agent_id="agent-2",
        organ_id=None,
        working=working,
        semantic=None,
        embedder=_FakeEmbedder(),
        scope_resolver=_ScopeResolver(),
        retrieval=retrieval,
    )

    await bridge.process_post_execution(
        task={"description": "x"},
        result={"task_id": "t2", "success": True, "quality": 0.95},
    )
    assert len(working.episodes) == 1
