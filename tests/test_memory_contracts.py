import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from src.seedcore.memory.mw_manager import MwManager
from src.seedcore.tools.manager import ToolManager


def test_mw_manager_recent_episode_round_trip(monkeypatch):
    mgr = MwManager("organ-alpha")
    shared: dict[tuple[str, str, str], list[dict]] = {}
    local: dict[str, object] = {}

    def fake_set_global_item_typed(kind, scope, item_id, value, ttl_s=None):
        shared[(kind, scope, item_id)] = value

    def fake_set_item(item_id, value, ttl_s=None):
        local[item_id] = value

    async def fake_get_item_async(item_id, is_global=False):
        if item_id == mgr._build_global_key("episode", "agent", "agent-7"):
            return shared.get(("episode", "agent", "agent-7"))
        if item_id == "chat_history:agent-7":
            return None
        return None

    monkeypatch.setattr(mgr, "set_global_item_typed", fake_set_global_item_typed)
    monkeypatch.setattr(mgr, "set_item", fake_set_item)
    monkeypatch.setattr(mgr, "get_item_async", fake_get_item_async)
    monkeypatch.setattr(mgr, "get_item", lambda item_id: local.get(item_id))

    asyncio.run(
        mgr.append_episode_async(
            agent_id="agent-7",
            episode={
                "task_description": "Investigate router latency",
                "success": True,
                "result": {"summary": "Pinned slow shard"},
            },
        )
    )

    recent = asyncio.run(
        mgr.get_recent_episode(
            organ_id="organ-alpha",
            agent_id="agent-7",
            k=5,
        )
    )

    assert len(recent) == 1
    assert recent[0]["role"] == "system"
    assert "Investigate router latency" in recent[0]["content"]
    assert "Pinned slow shard" in recent[0]["content"]


def test_mw_manager_recent_episode_falls_back_to_chat_history(monkeypatch):
    mgr = MwManager("organ-beta")
    chat_history = [
        {"role": "user", "content": "What changed in memory?"},
        {"role": "assistant", "content": "The cache contract was unified."},
    ]

    async def fake_get_item_async(item_id, is_global=False):
        if item_id == mgr._build_global_key("episode", "agent", "agent-9"):
            return None
        if item_id == "chat_history:agent-9":
            return chat_history
        return None

    monkeypatch.setattr(mgr, "get_item_async", fake_get_item_async)
    monkeypatch.setattr(mgr, "get_item", lambda item_id: None)

    recent = asyncio.run(
        mgr.get_recent_episode(
            organ_id="organ-beta",
            agent_id="agent-9",
            k=10,
        )
    )

    assert recent == chat_history


def test_mw_manager_set_item_with_ttl_writes_through(monkeypatch):
    mgr = MwManager("organ-gamma")
    seen = {}

    def fake_set_global_item(item_id, value, ttl_s=None):
        seen["call"] = (item_id, value, ttl_s)

    monkeypatch.setattr(mgr, "set_global_item", fake_set_global_item)

    mgr.set_item("chat_history:agent-1", [{"role": "user", "content": "hi"}], ttl_s=300)

    assert seen["call"] == (
        "chat_history:agent-1",
        [{"role": "user", "content": "hi"}],
        300,
    )


class _FakeMwManager:
    def __init__(self):
        self.local_writes = []
        self.global_writes = []

    async def get_item_async(self, item_id, is_global=False):
        return {"item_id": item_id, "is_global": is_global}

    def set_item(self, item_id, value, ttl_s=None):
        self.local_writes.append((item_id, value, ttl_s))

    def set_global_item(self, item_id, value, ttl_s=None):
        self.global_writes.append((item_id, value, ttl_s))

    async def get_hot_items_async(self, top_n=5):
        return [("task:123", 4)]


class _FakeGraph:
    async def get_neighbors(self, holon_id, limit=None):
        return [{"summary": "router knowledge", "props": {"type": "fact", "scope": "global"}}]


class _FakeHolonFabric:
    def __init__(self):
        self.graph = _FakeGraph()

    async def query_context(self, query_vec, scopes, limit):
        return []

    async def insert_holon(self, holon):
        return None


def test_tool_manager_memory_routes_use_runtime_contracts(monkeypatch):
    monkeypatch.setattr(
        ToolManager,
        "_requires_execution_token",
        lambda self, name: False,
    )
    mw_manager = _FakeMwManager()
    holon_fabric = _FakeHolonFabric()
    manager = ToolManager(mw_manager=mw_manager, holon_fabric=holon_fabric)

    write_result = asyncio.run(
        manager.execute(
            "memory.mw.write",
            {"item_id": "chat_history:agent-2", "value": {"ok": True}, "ttl_s": 60},
            agent_id="agent-2",
        )
    )
    read_result = asyncio.run(
        manager.execute(
            "memory.mw.read",
            {"item_id": "chat_history:agent-2", "is_global": False},
            agent_id="agent-2",
        )
    )
    hot_result = asyncio.run(
        manager.execute(
            "memory.mw.hot_items",
            {"top_n": 1},
            agent_id="agent-2",
        )
    )
    rel_result = asyncio.run(
        manager.execute(
            "memory.graph.relationships",
            {"holon_id": "holon-1"},
            agent_id="agent-2",
        )
    )

    assert write_result == {"status": "success", "item_id": "chat_history:agent-2"}
    assert mw_manager.local_writes == [("chat_history:agent-2", {"ok": True}, 60)]
    assert read_result == {"item_id": "chat_history:agent-2", "is_global": False}
    assert hot_result == [{"item_id": "task:123", "count": 4}]
    assert rel_result[0]["summary"] == "router knowledge"
    assert asyncio.run(manager.has("memory.graph.relationships")) is True

    schemas = asyncio.run(manager.list_tools())
    assert "memory.mw.read" in schemas
    assert "memory.holon.relationships" in schemas
