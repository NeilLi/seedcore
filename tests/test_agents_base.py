#!/usr/bin/env python3
import os
import sys
from typing import Any, Dict

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from seedcore.agents.base import BaseAgent
from seedcore.agents.roles import Specialization


@pytest.mark.asyncio
async def test_advertise_capabilities_reflects_role_profile():
    agent = BaseAgent(agent_id="agent-test", specialization=Specialization.GEA)

    advertisement = agent.advertise_capabilities()

    assert advertisement["agent_id"] == "agent-test"
    assert advertisement["specialization"] == Specialization.GEA.value
    assert set(advertisement["routing_tags"]) == {"guest_relations", "vip"}
    assert 0.0 <= advertisement["capability"] <= 1.0
    assert 0.0 <= advertisement["mem_util"] <= 1.0


@pytest.mark.asyncio
async def test_extract_salience_features_merges_system_and_error_context(monkeypatch: pytest.MonkeyPatch):
    agent = BaseAgent(agent_id="agent-salience")

    async def fake_heartbeat() -> Dict[str, Any]:
        return {"performance_metrics": {"capability_score_c": 0.7, "mem_util": 0.3}}

    monkeypatch.setattr(agent, "get_heartbeat", fake_heartbeat)
    monkeypatch.setattr(agent, "_get_system_load", lambda: 0.9)
    monkeypatch.setattr(agent, "_get_memory_usage", lambda: 0.4)
    monkeypatch.setattr(agent, "_get_cpu_usage", lambda: 0.45)
    monkeypatch.setattr(agent, "_get_response_time", lambda: 0.12)
    monkeypatch.setattr(agent, "_get_error_rate", lambda: 0.02)

    features = await agent._extract_salience_features(
        task_info={"risk": 0.8, "complexity": 0.6, "user_impact": 0.9},
        error_context={"reason": "Network timeout", "code": 503},
    )

    assert pytest.approx(features["agent_capability"]) == 0.7
    assert pytest.approx(features["agent_memory_util"]) == 0.3
    assert features["error_type"] == "timeout"
    assert pytest.approx(features["system_load"]) == 0.9
    assert pytest.approx(features["cpu_usage"]) == 0.45
    assert features["error_code"] == 503


@pytest.mark.asyncio
async def test_calculate_ml_salience_score_prefers_ml_response(monkeypatch: pytest.MonkeyPatch):
    agent = BaseAgent(agent_id="agent-ml")

    async def fake_extract(task_info: Dict[str, Any], error_context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "task_risk": 0.9,
            "failure_severity": 1.0,
            "user_impact": 0.8,
            "business_criticality": 0.7,
        }

    class FakeMlClient:
        async def compute_salience_score(self, *, text: str, context: Dict[str, Any]) -> Dict[str, Any]:
            assert "task_risk" in context
            return {"score": 0.85}

    async def fake_get_ml_client():
        return FakeMlClient()

    monkeypatch.setattr(agent, "_extract_salience_features", fake_extract)
    monkeypatch.setattr(agent, "_get_ml_client", fake_get_ml_client)

    salience = await agent._calculate_ml_salience_score(
        task_info={"task": "abc", "risk": 0.9},
        error_context={"reason": "planner timeout"},
    )

    assert pytest.approx(salience, rel=1e-5) == 0.85

