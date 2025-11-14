#!/usr/bin/env python3
import os
import sys
from typing import Any, Dict, List, Tuple

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from seedcore.agents.ula_agent import UtilityLearningAgent


@pytest.mark.asyncio
async def test_observe_and_tune_system_applies_suggestions(monkeypatch: pytest.MonkeyPatch):
    agent = UtilityLearningAgent(
        agent_id="ula-test",
        apply_changes=True,
        min_samples_for_action=1,
    )

    metrics = {
        "queue_depth_fast": 150,
        "queue_depth_cog": 60,
        "latency_p95": 2.2,
        "drift_score_p90": 0.3,
        "drift_score_mean": 0.25,
        "errors_5m": 5,
        "throughput_1m": 20,
    }
    router_stats = {"sample_count": 12}
    agents = {
        "agents": [
            {"specialization": "generalist", "load": 0.05},
            {"specialization": "guest_empathy_agent", "load": 0.02},
            {"specialization": "utility_learning_agent", "load": 0.8},
        ]
    }
    energy = {"power_avg_w": 750.0, "delta_j": 120.0}

    read_calls: List[Tuple[str, Dict[str, Any]]] = []
    write_calls: List[Tuple[str, Dict[str, Any]]] = []

    async def fake_read(name: str, args: Dict[str, Any], timeout_s: float = 8.0):
        read_calls.append((name, args))
        mapping = {
            "metrics.read": metrics,
            "router.stats": router_stats,
            "agents.list": agents,
            "energy.summary": energy,
        }
        return mapping.get(name)

    async def fake_write(name: str, args: Dict[str, Any], timeout_s: float = 8.0):
        write_calls.append((name, args))
        return {"ok": True}

    monkeypatch.setattr(agent, "_safe_tool_read", fake_read)
    monkeypatch.setattr(agent, "_safe_tool_write", fake_write)

    result = await agent.observe_and_tune_system()

    assert {name for name, _ in read_calls} == {
        "metrics.read",
        "router.stats",
        "agents.list",
        "energy.summary",
    }
    policy_updates = [payload for name, payload in write_calls if name == "policy.update"]
    assert policy_updates, "Expected policy.update tool write to be invoked"

    suggestion_kinds = {s["kind"] for s in result["suggestions"]}
    assert {"router_tuning", "planner_tuning", "router_bias"} <= suggestion_kinds
    assert all(s["status"] == "applied" for s in result["suggestions"])


@pytest.mark.asyncio
async def test_observe_and_tune_system_defers_when_samples_insufficient(monkeypatch: pytest.MonkeyPatch):
    agent = UtilityLearningAgent(
        agent_id="ula-dry",
        apply_changes=True,
        min_samples_for_action=50,
    )

    metrics = {
        "queue_depth_fast": 200,
        "queue_depth_cog": 70,
        "latency_p95": 3.0,
        "drift_score_p90": 0.2,
        "throughput_1m": 10,
    }
    router_stats = {"sample_count": 10}
    agents = {"agents": []}
    energy = {}

    async def fake_read(name: str, args: Dict[str, Any], timeout_s: float = 8.0):
        return {
            "metrics.read": metrics,
            "router.stats": router_stats,
            "agents.list": agents,
            "energy.summary": energy,
        }.get(name)

    async def fake_write(name: str, args: Dict[str, Any], timeout_s: float = 8.0):
        pytest.fail("No writes should be attempted when samples are insufficient")

    monkeypatch.setattr(agent, "_safe_tool_read", fake_read)
    monkeypatch.setattr(agent, "_safe_tool_write", fake_write)

    result = await agent.observe_and_tune_system()

    assert all(s["status"] == "skipped_insufficient_samples" for s in result["suggestions"])


@pytest.mark.asyncio
async def test_execute_task_handles_ula_specific_commands(monkeypatch: pytest.MonkeyPatch):
    agent = UtilityLearningAgent(agent_id="ula-exec", apply_changes=False)

    async def fake_observe():
        return {"metrics": {}, "router_stats": {}, "agents": 0, "energy": {}, "suggestions": []}

    monkeypatch.setattr(agent, "observe_and_tune_system", fake_observe)

    observe_res = await agent.execute_task({"task_id": "t1", "type": "ula.observe"})
    assert observe_res["success"] is True
    assert observe_res["meta"]["exec"]["kind"] == "ula.observe"

    tune_res = await agent.execute_task({"task_id": "t2", "type": "ula.tune"})
    assert tune_res["success"] is True
    assert tune_res["meta"]["exec"]["kind"] == "ula.tune_forced"

    reject_res = await agent.execute_task({"task_id": "t3", "type": "guest.task"})
    assert reject_res["success"] is False
    assert reject_res["meta"]["reject_reason"] == "agent_is_observer"

