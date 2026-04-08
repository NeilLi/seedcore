"""Cross-layer memory tool integration (ToolManager + query tools + semantic fake)."""

from __future__ import annotations

import pytest

import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from seedcore.memory.contracts import HolonRelation, MemoryHealth, MemorySubsystemStatus, SemanticMemoryStats
from seedcore.models.holon import Holon, HolonScope, HolonType
from seedcore.tools import query_tools
from seedcore.tools.manager import ToolManager


@pytest.fixture
def no_exec_token(monkeypatch):
    monkeypatch.setattr(ToolManager, "_requires_execution_token", lambda self, name: False)


class _FakeSemantic:
    holon_fabric = None

    def __init__(self) -> None:
        self._holons: dict[str, Holon] = {}
        self.upsert_calls: list[str] = []

    def seed(self, h: Holon) -> None:
        self._holons[str(h.id)] = h

    async def get_holon(self, hid: str):
        return self._holons.get(hid)

    async def search(self, q):
        return []

    async def upsert_holon(self, holon: Holon) -> None:
        self.upsert_calls.append(str(holon.id))
        self._holons[str(holon.id)] = holon

    async def list_relationships(self, holon_id: str, limit: int = 50):
        return [
            HolonRelation(
                holon_id=holon_id,
                neighbor_id="n1",
                rel_type="LINK",
                neighbor_summary="nb",
            )
        ]

    async def stats_snapshot(self) -> SemanticMemoryStats:
        return SemanticMemoryStats(health=MemoryHealth(status=MemorySubsystemStatus.ENABLED))


class _FakeMw:
    async def check_negative_cache(self, *a, **k):
        return False

    async def try_set_inflight(self, *a, **k):
        return True

    async def get_item_typed_async(self, *a, **k):
        return None

    async def del_global_key(self, *a, **k):
        pass

    def set_global_item_typed(self, *a, **k):
        pass

    def set_negative_cache(self, *a, **k):
        pass

    def set_item(self, *a, **k):
        pass


def _sample_holon(hid: str) -> Holon:
    return Holon(
        id=hid,
        type=HolonType.FACT,
        scope=HolonScope.GLOBAL,
        summary="integration",
        content={"v": 1},
        embedding=[0.0, 0.0, 0.0, 0.0],
    )


@pytest.mark.asyncio
async def test_tool_manager_memory_holon_query_uses_semantic(no_exec_token):
    sem = _FakeSemantic()
    sem.seed(_sample_holon("hid1"))
    tm = ToolManager(semantic_memory=sem)
    out = await tm.execute("memory.holon.query", {"holon_id": "hid1"}, "agent-1")
    assert out["id"] == "hid1"
    assert out["summary"] == "integration"


@pytest.mark.asyncio
async def test_tool_manager_memory_graph_relationships(no_exec_token):
    sem = _FakeSemantic()
    tm = ToolManager(semantic_memory=sem)
    out = await tm.execute("memory.graph.relationships", {"holon_id": "x"}, "agent-1")
    assert len(out) == 1
    assert out[0]["neighbor_id"] == "n1"


@pytest.mark.asyncio
async def test_register_query_tools_find_knowledge_escalates_to_semantic(no_exec_token):
    sem = _FakeSemantic()
    sem.seed(_sample_holon("fact-a"))
    tm = ToolManager(mw_manager=_FakeMw(), semantic_memory=sem)
    await query_tools.register_query_tools(
        tm,
        cognitive_client=None,
        agent_id="agent-x",
    )
    assert await tm.has("knowledge.find") is True
    res = await tm.execute("knowledge.find", {"fact_id": "fact-a"}, "agent-x")
    assert res["id"] == "fact-a"


@pytest.mark.asyncio
async def test_collaborative_task_promotes_via_semantic_upsert(no_exec_token):
    sem = _FakeSemantic()
    sem.seed(_sample_holon("needed-fact"))
    tm = ToolManager(mw_manager=_FakeMw(), semantic_memory=sem)
    await query_tools.register_query_tools(
        tm,
        cognitive_client=None,
        agent_id="agent-y",
        get_energy_slice=lambda: 1.0,
    )
    assert await tm.has("task.collaborative") is True
    payload = {
        "task_info": {
            "name": "demo",
            "task_id": "t1",
            "required_fact": "needed-fact",
        }
    }
    await tm.execute("task.collaborative", payload, "agent-y")
    assert len(sem.upsert_calls) == 1
