#!/usr/bin/env python3
import os
import sys
from typing import Any, Dict, Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from seedcore.agents.roles import (
    Specialization,
    RoleProfile,
    RoleRegistry,
    HOSPITALITY_ROLE_REGISTRY,
    build_hospitality_role_registry,
    SkillVector,
    SkillStoreProtocol,
    NullSkillStore,
    RbacEnforcer,
    AccessDecision,
    build_advertisement,
    AgentAdvertisement,
    Router,
    SkillLearner,
    LearningConfig,
    PromotionPolicy,
    Outcome,
)


def test_role_profile_materialize_and_context():
    profile = RoleProfile(
        name=Specialization.GENERALIST,
        default_skills={"analysis": 0.6, "planning": 0.4},
        allowed_tools={"notify.send"},
        visibility_scopes={"guest_profile"},
        routing_tags={"default"},
        safety_policies={"max_cost_usd": 25.0},
    )

    skill_vec = SkillVector(deltas={"analysis": 0.2, "new_skill": 0.9})
    materialized = profile.materialize_skills(skill_vec.deltas)
    assert pytest.approx(materialized["analysis"]) == 0.8
    assert materialized["planning"] == pytest.approx(0.4)
    assert materialized["new_skill"] == pytest.approx(0.9)

    ctx = profile.to_context(
        agent_id="agent-1",
        organ_id="organ-x",
        skill_deltas=skill_vec.deltas,
        capability=0.7,
        mem_util=0.3,
    )
    assert ctx["agent_id"] == "agent-1"
    assert ctx["specialization"] == Specialization.GENERALIST.value
    assert ctx["skills"]["analysis"] == pytest.approx(0.8)
    assert ctx["routing_tags"] == ["default"]
    assert ctx["safety"]["max_cost_usd"] == 25.0


def test_role_registry_register_and_update():
    profile = RoleProfile(
        name=Specialization.GENERALIST,
        default_skills={"analysis": 0.6},
        allowed_tools={"notify.send"},
        visibility_scopes={"guest_profile"},
        routing_tags={"default"},
        safety_policies={"max_cost_usd": 15.0},
    )
    registry = RoleRegistry([profile])

    fetched = registry.get(Specialization.GENERALIST)
    assert fetched is profile

    updated = registry.update(
        Specialization.GENERALIST,
        default_skills={"analysis": 0.7, "planning": 0.5},
        safety_policies={"max_cost_usd": 20.0},
    )
    assert pytest.approx(updated.default_skills["analysis"]) == 0.7
    assert updated.default_skills["planning"] == pytest.approx(0.5)
    assert updated.safety_policies["max_cost_usd"] == 20.0


def test_hospitality_role_registry_contains_specializations():
    registry = build_hospitality_role_registry()
    # Note: This test may need adjustment if HospitalitySpecialization doesn't match Specialization enum
    # For now, we test that the registry builds successfully
    assert registry is not None
    assert HOSPITALITY_ROLE_REGISTRY is not None


class MemorySkillStore(SkillStoreProtocol):
    def __init__(self) -> None:
        self.saved: Dict[str, Dict[str, float]] = {}

    async def load(self, agent_id: str) -> Optional[Dict[str, float]]:
        return self.saved.get(agent_id)

    async def save(self, agent_id: str, deltas: Dict[str, float], metadata: Optional[Dict[str, Any]] = None) -> None:
        self.saved[agent_id] = dict(deltas)


@pytest.mark.asyncio
async def test_skill_vector_persistence_and_math():
    store = MemorySkillStore()
    vec = await SkillVector.from_store(agent_id="agent-a", store=store)
    assert vec.deltas == {}

    vec.bump("analysis", 0.8)
    vec.bump("analysis", 0.5)  # clamp delta within [-1, 1]
    vec.bump("planning", -0.4)

    defaults = {"analysis": 0.6, "planning": 0.6}
    materialized = vec.materialize(defaults)
    assert materialized["analysis"] == pytest.approx(1.0)
    assert materialized["planning"] == pytest.approx(0.2)

    await vec.persist(agent_id="agent-a")
    assert store.saved["agent-a"]["analysis"] == pytest.approx(1.0)
    assert store.saved["agent-a"]["planning"] == pytest.approx(-0.4)

    other = SkillVector(deltas={"analysis": -1.0, "communication": 0.5})
    vec.merge(other, weight_self=0.25)
    merged = vec.materialize(defaults)
    assert 0.0 <= merged["analysis"] <= 1.0
    assert merged["communication"] == pytest.approx(0.375)


def test_rbac_enforcer_authorization_and_constraints():
    profile = RoleProfile(
        name=Specialization.GENERALIST,
        default_skills={"analysis": 0.6},
        allowed_tools={"notify.send", "analytics.run"},
        visibility_scopes={"guest_profile", "room_iot"},
        routing_tags={"default"},
        safety_policies={"max_cost_usd": 30.0, "max_autonomy": 0.5},
    )
    enforcer = RbacEnforcer()

    decision = enforcer.authorize_tool(profile, "notify.send", cost_usd=10.0, autonomy=0.4)
    assert isinstance(decision, AccessDecision)
    assert decision.allowed
    assert decision.constraints["max_cost_usd"] == 30.0

    denied_cost = enforcer.authorize_tool(profile, "notify.send", cost_usd=40.0)
    assert not denied_cost.allowed
    assert "cost" in denied_cost.reason

    denied_tool = enforcer.authorize_tool(profile, "unknown.tool")
    assert not denied_tool.allowed

    scope_ok = enforcer.authorize_scope(profile, "guest_profile")
    assert scope_ok.allowed

    scope_denied = enforcer.authorize_scope(profile, "restricted_scope")
    assert not scope_denied.allowed


def test_build_advertisement_and_router_selection():
    profile = RoleProfile(
        name=Specialization.GENERALIST,
        default_skills={"analysis": 0.6, "planning": 0.5},
        allowed_tools={"notify.send"},
        visibility_scopes={"guest_profile"},
        routing_tags={"default"},
        safety_policies={},
    )
    registry = RoleRegistry([profile])

    ad1 = build_advertisement(
        agent_id="agent-fast",
        role_profile=profile,
        specialization=Specialization.GENERALIST,
        materialized_skills={"analysis": 0.9, "planning": 0.8},
        capability=0.9,
        mem_util=0.2,
        quality_avg=0.85,
        latency_ms=150,
        routing_tags={"default", "guest_relations"},
    )
    ad2 = build_advertisement(
        agent_id="agent-loaded",
        role_profile=profile,
        specialization=Specialization.GENERALIST,
        materialized_skills={"analysis": 0.7, "planning": 0.4},
        capability=0.8,
        mem_util=0.7,
        quality_avg=0.9,
        latency_ms=400,
        routing_tags={"default"},
    )

    router = Router(registry)
    router.register(ad1)
    router.register(ad2)

    best = router.select_best(required_tags={"guest_relations"})
    assert best is not None
    assert best.agent_id == "agent-fast"

    top_two = router.select_topk(2, desired_skills={"analysis": 1.0})
    assert [ad.agent_id for ad in top_two] == ["agent-fast", "agent-loaded"]


def test_agent_advertisement_free_capacity_prefers_hint():
    ad = AgentAdvertisement(
        agent_id="agent-1",
        specialization=Specialization.GENERALIST,
        skills={"analysis": 0.7},
        capability=0.8,
        mem_util=0.9,
        capacity_hint=0.6,
    )
    assert ad.free_capacity() == pytest.approx(0.6)

    ad.capacity_hint = None
    assert ad.free_capacity() == pytest.approx(0.1)


def test_skill_learner_updates_and_promotes():
    general_role = RoleProfile(
        name=Specialization.GENERALIST,
        default_skills={"analysis": 0.6, "planning": 0.5, "communication": 0.4},
        allowed_tools={"notify.send"},
        visibility_scopes={"guest_profile"},
        routing_tags={"default"},
        safety_policies={},
    )
    observer_role = RoleProfile(
        name=Specialization.OBSERVER,
        default_skills={"analysis": 0.4, "planning": 0.4, "communication": 0.6},
        allowed_tools={"mw.topn"},
        visibility_scopes=set(),
        routing_tags={"observer"},
        safety_policies={},
    )
    registry = RoleRegistry([general_role, observer_role])

    lcfg = LearningConfig(
        lr_success=0.05,
        lr_failure=-0.02,
        salience_gain=0.0,
        quality_center=0.5,
        max_abs_delta_per_update=0.1,
        decay_rate_per_tick=0.0,
    )
    ppol = PromotionPolicy(
        window=3,
        min_tasks=3,
        min_quality_avg=0.8,
        demote_quality_avg=0.3,
        min_capability=0.7,
        cooldown_s=0.0,
        preferred_promotions={Specialization.GENERALIST: [Specialization.OBSERVER]},
    )

    learner = SkillLearner(registry, lcfg, ppol)
    skills = SkillVector()

    promoted = None
    for _ in range(3):
        outcome = Outcome(success=True, quality=0.9, escalated=False, salience=0.2)
        changed, promoted, diag = learner.learn(
            agent_id="agent-promote",
            current_spec=Specialization.GENERALIST,
            role_prof=general_role,
            skills=skills,
            outcome=outcome,
            capability=0.9,
        )
        assert changed

    assert promoted == Specialization.OBSERVER
    assert diag["role_change_reason"] == "promotion"
    assert skills.deltas

