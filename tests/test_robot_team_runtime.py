from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest
from pydantic import ValidationError

from seedcore.robotics.agent import prepare_robot_task, validate_robot_assignment
from seedcore.robotics.cognitive import RobotCognitivePlanner
from seedcore.robotics.contracts import (
    ActionClosure, RobotBinding, RobotProposal, TeamMission, TeamObservation,
)
from seedcore.robotics.coordinator import RobotTeamCoordinator
from seedcore.robotics.roster import RobotTeamRoster


def mission(**changes):
    data = dict(
        mission_id="football-1", organ_id="robotics",
        objective="Blue attacks +x; orange attacks -x", mode="competitive",
        roles={"blue": "attack +x", "orange": "attack -x"},
        bindings=tuple(RobotBinding(
            robot_id=f"duck-{name}", agent_id=name, organ_id="robotics",
            endpoint_id=f"hal://{name}", tool_name="robot.bounded_skill",
            profile="simulation", skills={"walk", "hold"},
        ) for name in ("blue", "orange")),
    )
    data.update(changes)
    return TeamMission(**data)


def observation(sequence=1, **changes):
    data = dict(mission_id="football-1", sequence=sequence, observed_at=100,
                robots={"duck-blue": {"x": -1}, "duck-orange": {"x": 1}}, world={"ball": [0, 0]})
    data.update(changes)
    return TeamObservation(**data)


async def propose(context):
    return dict(observation_sequence=context["observation"]["sequence"], skill="walk",
                arguments={"vx": .1}, duration_ms=100)


def task():
    team = mission()
    return prepare_robot_task(agent_id="blue", binding=team.bindings[0], mission=team,
                              observation=observation(), proposal=RobotProposal(
                                  observation_sequence=1, skill="walk", duration_ms=100), round_id="round-1")


def fake_closure(task):
    """TEST ONLY: production closure MUST come from an authenticated verifier."""
    command = task.params["robot_command"]
    return ActionClosure(
        task_id=task.task_id,
        **{key: command[key] for key in ("mission_id", "round_id", "robot_id", "agent_id",
                                         "endpoint_id", "observation_sequence")},
        command_hash=task.params["payload_hash"], execution_token_id="test-token",
        verifier_record_id="test-verifier-record", evidence_refs=("test://evidence",), verified=True,
    )


class Harness:
    def __init__(self, team=None, **ports):
        self.dispatched, self.halts = [], []
        self.time = 100.1
        defaults = dict(dispatch=self.dispatch, verify=self.verify, halt=self.halt,
                        clock=lambda: self.time)
        defaults.update(ports)
        self.runtime = RobotTeamCoordinator(team or mission(),
            defaults.pop("planners", {name: RobotCognitivePlanner(propose) for name in ("blue", "orange")}),
            **defaults)

    async def dispatch(self, task):
        self.dispatched.append(task)
        return {"success": True}

    async def verify(self, task, result):
        return fake_closure(task)

    async def halt(self, mission, reason):
        self.halts.append((mission.mission_id, reason))


@pytest.mark.parametrize("key", ["robot_id", "agent_id", "endpoint_id"])
def test_roster_rejects_duplicate_identities(key):
    data = mission().model_dump(mode="json")
    data["bindings"][1][key] = data["bindings"][0][key]
    with pytest.raises(ValidationError, match="duplicate"):
        TeamMission.model_validate(data)


def test_organ_roster_reserves_and_retains_ownership():
    roster = RobotTeamRoster("robotics")
    with pytest.raises(ValueError, match="unregistered"):
        roster.reserve(mission(), {"blue"})
    roster.reserve(mission(), {"blue", "orange"})
    with pytest.raises(ValueError, match="already reserved"):
        roster.reserve(mission(mission_id="work-2"), {"blue", "orange"})
    with pytest.raises(ValueError, match="reconcile"):
        roster.assert_agent_removable("blue")
    roster.get("football-1").roles["blue"] = "changed copy"
    assert roster.get("football-1").roles["blue"] == "attack +x"
    roster.release_after_reconciliation("football-1")
    roster.assert_agent_removable("blue")


@pytest.mark.asyncio
async def test_two_agents_plan_and_dispatch_concurrently_then_verify():
    started = set()
    barrier = asyncio.Event()

    async def simultaneous_dispatch(task):
        started.add(task.params["robot_command"]["agent_id"])
        if len(started) == 2:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), 1)
        return {"success": True}

    h = Harness(dispatch=simultaneous_dispatch)
    result = await h.runtime.run_round(observation())
    assert result.status == "verified"
    assert set(result.closures) == {"blue", "orange"}
    assert not h.halts
    assert result.closures["blue"].task_id != result.closures["orange"].task_id


@pytest.mark.asyncio
async def test_planning_barrier_and_snapshot_isolation():
    started = set()
    barrier = asyncio.Event()
    h = Harness()

    async def isolated(context):
        started.add(context["robot_id"])
        assert context["observation"]["world"]["ball"] == [0, 0]
        context["observation"]["world"]["ball"][0] = 99
        if len(started) == 2:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), 1)
        assert not h.dispatched
        return await propose(context)

    h.runtime._planners = {n: RobotCognitivePlanner(isolated) for n in ("blue", "orange")}
    obs = observation()
    assert (await h.runtime.run_round(obs)).status == "verified"
    assert obs.world["ball"] == [0, 0]


@pytest.mark.parametrize("extra", [{"endpoint_id": "evil"}, {"execution_token": "fake"}, {"agent_id": "other"}])
@pytest.mark.asyncio
async def test_model_cannot_add_routing_or_authority(extra):
    async def bad(context):
        return {**await propose(context), **extra}

    h = Harness(planners={"blue": RobotCognitivePlanner(bad), "orange": RobotCognitivePlanner(propose)})
    result = await h.runtime.run_round(observation())
    assert result.status == "halted"
    assert not h.dispatched
    assert h.halts


@pytest.mark.parametrize("changes", [dict(observed_at=90), dict(observed_at=101),
                                    dict(mission_id="other"), dict(robots={})])
@pytest.mark.asyncio
async def test_invalid_snapshot_halts_before_dispatch(changes):
    h = Harness()
    assert (await h.runtime.run_round(observation(**changes))).status == "halted"
    assert not h.dispatched


@pytest.mark.asyncio
async def test_snapshot_expiring_during_planning_is_rejected():
    h = Harness()

    async def delayed(context):
        h.time = 103
        return await propose(context)

    h.runtime._planners["blue"] = RobotCognitivePlanner(delayed)
    assert (await h.runtime.run_round(observation())).status == "halted"
    assert not h.dispatched


@pytest.mark.parametrize("change", [dict(skill="fly"), dict(duration_ms=2000), dict(observation_sequence=0)])
@pytest.mark.asyncio
async def test_invalid_proposal_aborts_whole_round(change):
    async def bad(context):
        return {**await propose(context), **change}

    h = Harness(planners={"blue": RobotCognitivePlanner(bad), "orange": RobotCognitivePlanner(propose)})
    assert (await h.runtime.run_round(observation())).status == "halted"
    assert not h.dispatched


@pytest.mark.asyncio
async def test_operator_resource_claims_cannot_be_omitted_by_planner():
    data = mission().model_dump(mode="json")
    for binding in data["bindings"]:
        binding["exclusive_resources"] = ["workcell-1"]
    h = Harness(TeamMission.model_validate(data))
    assert (await h.runtime.run_round(observation())).status == "halted"
    assert not h.dispatched


@pytest.mark.asyncio
async def test_work_rounds_require_verified_barrier_and_reject_replay():
    h = Harness(mission(mode="cooperative", objective="Inspect then hand off the part"))
    assert (await h.runtime.run_round(observation(1))).status == "verified"
    assert (await h.runtime.run_round(observation(2))).status == "verified"
    assert (await h.runtime.run_round(observation(2))).status == "halted"
    assert len(h.dispatched) == 4
    with pytest.raises(RuntimeError, match="halted"):
        await h.runtime.run_round(observation(3))


@pytest.mark.parametrize("field,value", [("verified", False), ("robot_id", "wrong"),
    ("command_hash", "wrong"), ("task_id", "wrong"), ("observation_sequence", 2),
    ("agent_id", "wrong"), ("endpoint_id", "wrong"), ("round_id", "wrong")])
@pytest.mark.asyncio
async def test_bad_closure_halts_without_retry(field, value):
    async def verify(task, result):
        return fake_closure(task).model_copy(update={field: value})

    h = Harness(verify=verify)
    result = await h.runtime.run_round(observation())
    assert result.status == "halted"
    # Immediate failure may fence a peer before its submission. Neither action
    # may be replayed, regardless of the scheduling order.
    assert 1 <= len(h.dispatched) <= 2
    assert len({t.task_id for t in h.dispatched}) == len(h.dispatched)
    assert not result.closures


@pytest.mark.asyncio
async def test_partial_execution_preserves_verified_evidence_and_halts():
    async def dispatch(task):
        return {"success": task.params["robot_command"]["agent_id"] == "blue"}

    h = Harness(dispatch=dispatch)
    result = await h.runtime.run_round(observation())
    assert result.status == "halted"
    assert set(result.closures) == {"blue"}
    assert set(result.failures) == {"orange"}
    assert result.halt_acknowledged


@pytest.mark.asyncio
async def test_acknowledgement_is_not_verification():
    async def not_a_verifier(task, result):
        return {"actuator_ack": True}

    h = Harness(verify=not_a_verifier)
    assert (await h.runtime.run_round(observation())).status == "halted"


@pytest.mark.asyncio
async def test_planning_timeout_dispatches_nothing():
    async def stuck(context):
        await asyncio.Event().wait()

    h = Harness(mission(planning_timeout_s=.01), planners={
        "blue": RobotCognitivePlanner(stuck), "orange": RobotCognitivePlanner(propose)})
    assert (await h.runtime.run_round(observation())).status == "halted"
    assert not h.dispatched


@pytest.mark.asyncio
async def test_execution_timeout_and_failed_halt_do_not_claim_stopped():
    async def stuck(task):
        await asyncio.Event().wait()

    async def failed_halt(team, reason):
        raise OSError("offline")

    h = Harness(mission(execution_timeout_s=.01), dispatch=stuck, halt=failed_halt)
    result = await h.runtime.run_round(observation())
    assert result.status == "halted" and not result.halt_acknowledged
    assert h.runtime.halted


@pytest.mark.asyncio
async def test_cancellation_requests_halt_and_prevents_overlapping_rounds():
    entered = asyncio.Event()

    async def stuck(task):
        entered.set()
        await asyncio.Event().wait()

    h = Harness(dispatch=stuck)
    running = asyncio.create_task(h.runtime.run_round(observation()))
    await asyncio.wait_for(entered.wait(), 1)
    with pytest.raises(RuntimeError, match="already running"):
        await h.runtime.run_round(observation(2))
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert h.halts and h.runtime.halted
    assert h.runtime.last_result.status == "halted"
    assert set(h.runtime.last_result.failures) == {"blue", "orange"}


def admitted_task():
    data = task().model_dump(mode="json")
    params = data["params"]
    # TEST ONLY: shape checks do not replace PDP/HAL cryptographic checks.
    params["governance"].update(
        action_intent={"principal": {"agent_id": "blue"}, "resource": {"asset_id": "duck-blue"},
                       "action": {"parameters": deepcopy(params)}},
        execution_token={"token_id": "test-only"}, policy_decision={"allowed": True},
    )
    return data


def test_agent_guard_pins_identity_command_and_deadline():
    data = admitted_task()
    validate_robot_assignment(data, "blue", now=100.1)
    with pytest.raises(ValueError):
        validate_robot_assignment(data, "orange", now=100.1)
    with pytest.raises(ValueError):
        validate_robot_assignment(data, "blue", now=103)
    data["params"]["robot_command"]["arguments"]["vx"] = 99
    with pytest.raises(ValueError):
        validate_robot_assignment(data, "blue", now=100.1)


def test_agent_guard_rejects_ungoverned_and_changed_tool():
    with pytest.raises(KeyError):
        validate_robot_assignment(task().model_dump(mode="json"), "blue", now=100.1)
    data = admitted_task()
    data["params"]["tool_calls"][0]["name"] = "other.tool"
    with pytest.raises(ValueError):
        validate_robot_assignment(data, "blue", now=100.1)


def test_task_is_governed_and_intent_binds_endpoint_and_command():
    from seedcore.coordinator.core.governance import build_action_intent, requires_action_intent

    proposed_task = task()
    assert requires_action_intent(proposed_task)
    intent = build_action_intent(proposed_task)
    assert intent.principal.agent_id == "blue"
    assert intent.resource.asset_id == "duck-blue"
    assert intent.action.type == "ROBOT_SKILL"
    assert intent.action.parameters["endpoint_id"] == "hal://blue"
    assert intent.action.parameters["payload_hash"] == proposed_task.params["payload_hash"]
    assert "execution_token" not in proposed_task.params["governance"]


def test_task_identity_and_tool_survive_db_and_coordinator_normalization():
    from seedcore.coordinator.utils import coerce_task_payload

    proposed_task = task()
    for incoming in (proposed_task, proposed_task.model_dump(mode="json"), proposed_task.to_db_row()):
        hydrated, packed = coerce_task_payload(incoming)
        assert packed["params"]["interaction"]["assigned_agent_id"] == "blue"
        assert packed["params"]["tool_calls"] == proposed_task.params["tool_calls"]
        assert hydrated.deadline_at == proposed_task.deadline_at


def test_base_agent_packages_only_its_assigned_robot():
    from seedcore.agents.base import BaseAgent

    agent = BaseAgent.__new__(BaseAgent)
    agent.agent_id, agent.organ_id = "blue", "robotics"
    kwargs = dict(mission=mission().model_dump(mode="json"), observation=observation().model_dump(mode="json"),
                  proposal=dict(observation_sequence=1, skill="hold", duration_ms=100), round_id="round-local")
    result = agent.prepare_robot_action(**kwargs)
    assert result["params"]["robot_command"]["robot_id"] == "duck-blue"
    agent.agent_id = "outsider"
    with pytest.raises(ValueError, match="not assigned"):
        agent.prepare_robot_action(**kwargs)


@pytest.mark.asyncio
async def test_base_agent_rejects_ungoverned_robot_task_before_tools():
    from unittest.mock import AsyncMock
    from seedcore.agents.base import BaseAgent

    agent = BaseAgent(agent_id="blue", organ_id="robotics")
    agent._behaviors_initialized = True
    agent._behaviors = []
    agent.use_tool = AsyncMock()
    result = await agent.execute_task(task().model_dump(mode="json"))
    assert result["success"] is False
    agent.use_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_organ_methods_keep_reserved_agents_until_reconciliation():
    from seedcore.organs.organ import Organ

    organ = Organ(organ_id="robotics")
    organ.agents = {"blue": object(), "orange": object()}
    reserved = await organ.reserve_robot_team(mission().model_dump(mode="json"))
    assert reserved["mission_id"] == "football-1"
    with pytest.raises(ValueError, match="reconcile"):
        await organ.remove_agent("blue")
    assert "blue" in organ.agents
    await organ.release_robot_team_after_reconciliation("football-1")


@pytest.mark.asyncio
async def test_cognitive_builder_uses_proposal_contract():
    from seedcore.cognitive.advisory import CognitiveAdvisoryContractBuilder

    planner = CognitiveAdvisoryContractBuilder.robot_team_planner(propose)
    proposal = await planner.propose(mission(), mission().bindings[0], observation())
    assert proposal.skill == "walk"


@pytest.mark.asyncio
async def test_coordinator_factory_uses_existing_governed_entrypoint():
    from seedcore.services.coordinator_service import Coordinator
    from seedcore.models.task_payload import TaskPayload

    coordinator = Coordinator.__new__(Coordinator)
    h = Harness()
    entries = []

    async def governed_entry(payload):
        entries.append(payload)
        assert payload["type"] == "action"
        assert payload["params"]["governance"]["require_action_intent"]
        return await h.dispatch(TaskPayload.model_validate(payload))

    coordinator.route_and_execute = governed_entry
    planners = {name: RobotCognitivePlanner(propose) for name in ("blue", "orange")}
    runtime = coordinator.create_robot_team_runtime(mission(), planners, verify=h.verify, halt=h.halt)
    runtime._clock = lambda: 100.1
    assert (await runtime.run_round(observation())).status == "verified"
    assert len(entries) == 2
    with pytest.raises(ValueError, match="already exists"):
        coordinator.create_robot_team_runtime(mission(), planners, verify=h.verify, halt=h.halt)
    with pytest.raises(ValueError, match="already owned"):
        coordinator.create_robot_team_runtime(mission(mission_id="overlap"), planners,
                                              verify=h.verify, halt=h.halt)
    with pytest.raises(ValueError, match="halt and reconcile"):
        coordinator.release_robot_team_runtime_after_reconciliation("football-1")
    assert await runtime.halt_mission()
    coordinator.release_robot_team_runtime_after_reconciliation("football-1")
    with pytest.raises(RuntimeError, match="halted"):
        await runtime.run_round(observation(2))


@pytest.mark.asyncio
async def test_failure_requests_halt_before_stuck_peer_finishes():
    halt_seen = asyncio.Event()

    async def dispatch(task):
        if task.params["robot_command"]["agent_id"] == "blue":
            return {"success": False}
        await asyncio.wait_for(halt_seen.wait(), .5)
        return {"success": False}

    async def halt(team, reason):
        halt_seen.set()

    h = Harness(dispatch=dispatch, halt=halt)
    assert (await h.runtime.run_round(observation())).status == "halted"
    assert halt_seen.is_set()


def test_mixed_profiles_and_missing_safety_ports_rejected():
    data = mission().model_dump(mode="json")
    data["bindings"][0]["profile"] = "hardware"
    with pytest.raises(ValidationError, match="cannot share"):
        TeamMission.model_validate(data)
    with pytest.raises(ValueError, match="adapters are required"):
        Harness(verify=None)


@pytest.mark.asyncio
async def test_cancellation_retains_already_verified_peer():
    verified = asyncio.Event()

    async def dispatch(task):
        if task.params["robot_command"]["agent_id"] == "orange":
            await asyncio.Event().wait()
        return {"success": True}

    async def verify(task, result):
        verified.set()
        return fake_closure(task)

    h = Harness(dispatch=dispatch, verify=verify)
    running = asyncio.create_task(h.runtime.run_round(observation()))
    await asyncio.wait_for(verified.wait(), 1)
    await asyncio.sleep(0)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert set(h.runtime.last_result.closures) == {"blue"}
    assert set(h.runtime.last_result.failures) == {"orange"}


@pytest.mark.asyncio
async def test_nonfinite_command_arguments_fail_before_dispatch():
    async def invalid(context):
        return {**await propose(context), "arguments": {"vx": float("nan")}}

    h = Harness(planners={name: RobotCognitivePlanner(invalid) for name in ("blue", "orange")})
    assert (await h.runtime.run_round(observation())).status == "halted"
    assert not h.dispatched
