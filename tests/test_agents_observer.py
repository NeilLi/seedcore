#!/usr/bin/env python3
import os
import sys
from typing import Any, Dict, List, Tuple

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from seedcore.agents.observer_agent import ObserverAgent
from seedcore.agents.roles import RoleProfile, RoleRegistry, Specialization


def make_observer_agent(agent_id: str = "observer-test") -> ObserverAgent:
    profile = RoleProfile(
        name=Specialization.OBS,
        default_skills={},
        allowed_tools={
            "mw.topn",
            "cache.get",
            "ltm.query_by_id",
            "cache.set",
        },
        visibility_scopes=set(),
        routing_tags={"observer"},
        safety_policies={},
    )
    registry = RoleRegistry([profile])
    return ObserverAgent(agent_id=agent_id, role_registry=registry, miss_threshold=2, apply_changes=True)


@pytest.mark.asyncio
async def test_proactive_pass_caches_hot_item(monkeypatch: pytest.MonkeyPatch):
    agent = make_observer_agent()

    read_sequence: List[Tuple[str, Dict[str, Any]]] = []
    write_sequence: List[Tuple[str, Dict[str, Any]]] = []

    async def fake_read(name: str, args: Dict[str, Any], timeout_s: float = 8.0):
        read_sequence.append((name, args))
        if name == "mw.topn":
            return [{"uuid": "item-42", "misses": 5}]
        if name == "cache.get":
            return {}
        if name == "ltm.query_by_id":
            return {"id": "item-42", "payload": {"foo": "bar"}}
        return None

    async def fake_write(name: str, args: Dict[str, Any], timeout_s: float = 8.0):
        write_sequence.append((name, args))
        return {"ok": True}

    monkeypatch.setattr(agent, "_safe_tool_read", fake_read)
    monkeypatch.setattr(agent, "_safe_tool_write", fake_write)

    await agent._proactive_pass()

    assert [name for name, _ in read_sequence] == ["mw.topn", "cache.get", "ltm.query_by_id"]
    assert write_sequence, "Expected cache.set to be invoked"
    cache_call = write_sequence[0]
    assert cache_call[0] == "cache.set"
    assert cache_call[1]["key"] == "global:item:item-42"
    assert cache_call[1]["value"]["id"] == "item-42"


@pytest.mark.asyncio
async def test_proactive_pass_skips_when_threshold_not_met(monkeypatch: pytest.MonkeyPatch):
    agent = make_observer_agent()

    async def fake_read(name: str, args: Dict[str, Any], timeout_s: float = 8.0):
        if name == "mw.topn":
            return [{"uuid": "item-1", "misses": 1}]
        pytest.fail(f"Unexpected read for {name}")

    async def fake_write(name: str, args: Dict[str, Any], timeout_s: float = 8.0):
        pytest.fail("No writes expected when miss threshold not met")

    monkeypatch.setattr(agent, "_safe_tool_read", fake_read)
    monkeypatch.setattr(agent, "_safe_tool_write", fake_write)

    await agent._proactive_pass()


@pytest.mark.asyncio
async def test_execute_task_handles_observer_commands(monkeypatch: pytest.MonkeyPatch):
    agent = make_observer_agent()

    async def fake_pass():
        return None

    monkeypatch.setattr(agent, "_proactive_pass", fake_pass)

    res = await agent.execute_task({"task_id": "t-obs", "type": "observer.proactive_cache"})
    assert res["success"] is True
    assert res["meta"]["exec"]["kind"] == "observer.proactive_cache"

    rejection = await agent.execute_task({"task_id": "t-bad", "type": "guest.task"})
    assert rejection["success"] is False
    assert rejection["meta"]["reject_reason"] == "agent_is_observer"

