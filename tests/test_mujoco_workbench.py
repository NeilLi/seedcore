"""Real MuJoCo acceptance checks plus draft and internal-agent tool boundaries."""

import asyncio
import importlib
import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from seedcore.robotics.mujoco_workbench.contracts import (
    ComparisonSpec,
    ControllerSpec,
    ExperimentCriteria,
    ExperimentSpec,
    LinkSpec,
    RobotSpec,
)
from seedcore.robotics.mujoco_workbench.models import build_mjcf
from seedcore.robotics.mujoco_workbench import runtime


@pytest.fixture
def engine():
    pytest.importorskip(
        "mujoco", reason="install seedcore[robotics-sim] for native physics tests"
    )
    return runtime.require_engine()


def position_recipe(**kwargs):
    return ExperimentSpec(
        controller=ControllerSpec(mode="position", values=(0.5, -0.5)),
        steps=1500,
        sample_every=15,
        **kwargs,
    )


def test_mjcf_is_asset_free_and_varies_with_robot_design():
    robot = RobotSpec()
    xml = build_mjcf(robot)
    assert "<include" not in xml and "<plugin" not in xml and "file=" not in xml
    changed = robot.model_dump(mode="json")
    changed["links"][0]["mass_kg"] = 0.3
    assert xml != build_mjcf(RobotSpec.model_validate(changed))


@pytest.mark.parametrize(
    "changes",
    [
        {"steps": 0},
        {"steps": True},
        {"steps": 10001},
        {"sample_every": 0},
        {"steps": 1001, "sample_every": 1},
        {"steps": 10000, "robot": {"timestep_s": 0.005}},
        {"robot": {"timestep_s": float("nan")}},
        {"robot": {"gravity_m_s2": True}},
        {"robot": {"floating_base": "true"}},
        {"initial_joint_angles_rad": [0.5]},
        {"initial_joint_velocities_rad_s": [float("inf"), 0]},
        {"initial_joint_angles_rad": [True, 0]},
        {"initial_joint_angles_rad": [3, 0]},
        {"controller": {"mode": "torque", "values": [100, 0]}},
        {"controller": {"mode": "position", "values": [3, 0]}},
        {"controller": {"mode": "passive", "values": [1, 1]}},
        {"criteria": {"final_joint_error_rad": 0.1}},
        {"execution_token": "invented"},
        {"endpoint_id": "hal://robot"},
        {"mjcf": "<mujoco/>"},
        {"python": "arbitrary code"},
    ],
)
def test_invalid_or_authority_bearing_drafts_are_rejected(changes):
    with pytest.raises(ValidationError):
        ExperimentSpec.model_validate(changes)


def test_impossible_primitive_geometry_is_rejected():
    with pytest.raises(ValidationError):
        LinkSpec(lower_rad=1, upper_rad=0)
    with pytest.raises(ValidationError):
        LinkSpec(length_m=0.02, radius_m=0.03)
    with pytest.raises(ValidationError):
        RobotSpec(links=())
    with pytest.raises(ValidationError):
        RobotSpec(links=(LinkSpec(),) * 7)


def test_engine_unavailable_or_mismatched_never_falls_back(monkeypatch):
    real_import = importlib.import_module

    def missing(name):
        if name == "mujoco":
            raise ImportError("missing")
        return real_import(name)

    monkeypatch.setattr(runtime.importlib, "import_module", missing)
    with pytest.raises(RuntimeError, match="MuJoCo unavailable"):
        runtime.require_engine()
    monkeypatch.setattr(
        runtime.importlib,
        "import_module",
        lambda _: type("Engine", (), {"__version__": "0.0"})(),
    )
    with pytest.raises(RuntimeError, match="version mismatch"):
        runtime.require_engine()


def test_native_model_compiles_hinge_actuator_and_sensor_contracts(engine):
    description = runtime.inspect_robot(RobotSpec())
    assert description["dimensions"] == {
        "nq": 2,
        "nv": 2,
        "nu": 2,
        "nbody": 4,
        "nsensor": 7,
    }
    assert description["engine_version"] == runtime.ENGINE_VERSION
    assert "base_accelerometer" in description["sensor_names"]
    assert len(description["model_sha256"]) == 64
    spatial = RobotSpec(
        links=(LinkSpec(axis="z"), LinkSpec(axis="y"), LinkSpec(axis="x"))
    )
    assert runtime.inspect_robot(spatial)["dimensions"]["nv"] == 3


def test_programmatic_model_copy_cannot_bypass_native_work_bounds(engine):
    invalid = RobotSpec().model_copy(update={"links": (LinkSpec(),) * 7})
    with pytest.raises(ValidationError):
        runtime.inspect_robot(invalid)


def test_native_free_fall_matches_ballistic_height_before_contact(engine):
    spec = ExperimentSpec(
        robot=RobotSpec(links=(), floating_base=True), steps=50, sample_every=50
    )
    result = runtime.run_experiment(spec)
    dt = spec.robot.timestep_s
    # MuJoCo's semi-implicit free fall advances position with the new velocity.
    expected = spec.robot.base_height_m - spec.robot.gravity_m_s2 * dt**2 * 50 * 51 / 2
    assert result["trace"][-1]["qpos"][2] == pytest.approx(expected, abs=1e-9)
    assert result["metrics"]["max_contact_points"] == 0


def test_native_floor_contacts_are_measured_and_evaluated(engine):
    result = runtime.run_experiment(
        ExperimentSpec(
            robot=RobotSpec(links=(), floating_base=True),
            criteria=ExperimentCriteria(max_contact_points=0),
        )
    )
    assert result["status"] == "criteria_not_met"
    assert result["checks"]["max_contact_points"] is False
    assert ["base_geom", "floor"] in result["metrics"]["observed_contact_pairs"]
    assert result["trace"][-1]["qpos"][2] == pytest.approx(0.04, abs=0.001)


def test_native_sensors_controls_and_final_tick_are_coherent(engine):
    spec = position_recipe().model_dump(mode="json")
    spec.update(steps=37, sample_every=10)
    result = runtime.run_experiment(ExperimentSpec.model_validate(spec))
    assert [sample["tick"] for sample in result["trace"]] == [0, 10, 20, 30, 37]
    assert result["trace"][-1]["time_s"] == pytest.approx(37 * 0.002)
    for sample in result["trace"]:
        for i in range(2):
            assert sample["sensors"][f"encoder_{i}"][0] == pytest.approx(
                sample["qpos"][i]
            )
            assert sample["sensors"][f"velocity_{i}"][0] == pytest.approx(
                sample["qvel"][i]
            )
            assert abs(sample["control"][i]) <= 2
            assert abs(sample["actuator_force"][i]) <= 2
    json.dumps(result, allow_nan=False)


def test_native_repetition_uses_fresh_state_and_preserves_recipe_identity(engine):
    spec = position_recipe()
    first = runtime.run_experiment(spec)
    runtime.run_experiment(
        ExperimentSpec(robot=RobotSpec(links=(), floating_base=True))
    )
    second = runtime.run_experiment(spec)
    assert first["run_id"] != second["run_id"]
    assert first["recipe_sha256"] == second["recipe_sha256"]
    assert first["model_sha256"] == second["model_sha256"]
    assert first["trace"] == second["trace"]
    assert first["metrics"] == second["metrics"]


def test_native_warning_prevents_false_completion(engine, monkeypatch):
    real_step = engine.mj_step

    def warn(model, data):
        real_step(model, data)
        data.warning[int(engine.mjtWarning.mjWARN_BADQPOS)].number = 1

    monkeypatch.setattr(engine, "mj_step", warn)
    result = runtime.run_experiment(position_recipe())
    assert result["status"] == "numerical_failure"
    assert result["failure_reason"] == "mjWARN_BADQPOS"
    assert result["completed_steps"] == 1
    assert result["checks"] == {}
    assert result["metrics"]["final_joint_error_rad"] is None
    assert len(result["trace"]) == 1


def test_native_comparison_preserves_criteria_and_reports_measured_delta(engine):
    baseline = position_recipe(
        criteria=ExperimentCriteria(
            final_joint_error_rad=0.05, max_joint_speed_rad_s=10
        )
    )
    candidate = baseline.model_dump(mode="json")
    candidate["controller"]["kp"] = 48
    result = runtime.compare_experiments(
        ComparisonSpec(
            baseline=baseline,
            candidate=ExperimentSpec.model_validate(candidate),
        )
    )
    assert (
        result["baseline"]["request"]["criteria"]
        == result["candidate"]["request"]["criteria"]
    )
    before = result["baseline"]["metrics"]["final_joint_error_rad"]
    after = result["candidate"]["metrics"]["final_joint_error_rad"]
    assert result["final_joint_error_change_rad"] == pytest.approx(after - before)
    assert result["baseline"]["recipe_sha256"] != result["candidate"]["recipe_sha256"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("steps", 2000),
        ("initial_joint_angles_rad", [0.1, 0.1]),
        ("criteria", {"final_joint_error_rad": 1}),
    ],
)
def test_comparison_cannot_change_task_or_relax_acceptance(field, value):
    baseline = position_recipe()
    candidate = baseline.model_dump(mode="json")
    candidate[field] = value
    with pytest.raises(ValidationError, match="comparison must preserve"):
        ComparisonSpec(
            baseline=baseline, candidate=ExperimentSpec.model_validate(candidate)
        )


@pytest.mark.asyncio
async def test_internal_agent_tools_build_and_run_through_real_manager(engine):
    from jsonschema import Draft202012Validator
    from seedcore.tools.manager import ToolError, ToolManager
    from seedcore.tools.mujoco_tools import register_mujoco_tools

    manager = ToolManager()
    registered = await register_mujoco_tools(manager)
    assert len(registered["tools"]) == 3
    assert await manager.has_capability("simulation.mujoco.development")
    for name in registered["tools"]:
        schema = await manager.get_tool_schema(name)
        Draft202012Validator.check_schema(schema["parameters"])
    spec = ExperimentSpec(steps=20).model_dump(mode="json")
    schema = await manager.get_tool_schema("simulation.mujoco.run")
    Draft202012Validator(schema["parameters"]).validate({"spec": spec})
    built = await manager.execute(
        "simulation.mujoco.build", {"spec": spec["robot"]}, agent_id="robot-dev-1"
    )
    result = await manager.execute(
        "simulation.mujoco.run", {"spec": spec}, agent_id="robot-dev-1"
    )
    assert built["model_sha256"] == result["model_sha256"]
    assert result["completed_steps"] == 20
    assert result["profile"] == "OFFLINE_MUJOCO_NO_ACTUATION"
    manager.rbac_provider = type(
        "RBAC", (), {"allowed": AsyncMock(return_value=False)}
    )()
    with pytest.raises(ToolError, match="rbac_denied"):
        await manager.execute(
            "simulation.mujoco.run", {"spec": spec}, agent_id="unassigned"
        )


@pytest.mark.asyncio
async def test_opt_in_registration_handles_local_and_sharded_agents(
    engine, monkeypatch
):
    from seedcore.tools.manager import ToolManager
    from seedcore.tools.mujoco_tools import register_mujoco_tools_if_enabled

    manager = ToolManager()
    monkeypatch.delenv("SEEDCORE_ENABLE_MUJOCO_TOOLS", raising=False)
    assert await register_mujoco_tools_if_enabled(manager) is False
    assert not await manager.has("simulation.mujoco.run")
    monkeypatch.setenv("SEEDCORE_ENABLE_MUJOCO_TOOLS", "1")
    assert await register_mujoco_tools_if_enabled(manager) is True
    remote = AsyncMock()
    shard = type(
        "Shard", (), {"register_mujoco_tools": type("Call", (), {"remote": remote})()}
    )()
    assert await register_mujoco_tools_if_enabled(shard) is True
    remote.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_native_work_retains_its_concurrency_slot(engine, monkeypatch):
    import threading
    from seedcore.tools.mujoco_tools import MuJoCoDevelopmentTool

    started, finish = threading.Event(), threading.Event()
    budget = asyncio.Semaphore(1)
    tool = MuJoCoDevelopmentTool("run", budget)

    def compute(_):
        started.set()
        assert finish.wait(timeout=5)
        return {}

    monkeypatch.setattr(tool, "_compute", compute)
    task = asyncio.create_task(
        tool.execute(ExperimentSpec(steps=1).model_dump(mode="json"))
    )
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert budget.locked()
    task.cancel()
    await asyncio.sleep(0)
    assert budget.locked()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not budget.locked()


@pytest.mark.asyncio
async def test_internal_development_assistant_preserves_operator_recipe(engine):
    from seedcore.robotics.mujoco_workbench.assistant import RobotDevelopmentAssistant
    from seedcore.tools.manager import ToolManager
    from seedcore.tools.mujoco_tools import register_mujoco_tools

    template = position_recipe(criteria=ExperimentCriteria(final_joint_error_rad=0.05))
    proposer = AsyncMock(
        return_value={
            "robot": template.robot.model_dump(mode="json"),
            "controller": template.controller.model_dump(mode="json"),
            "rationale": "Test the requested joint posture using a fixed-base two-link draft.",
        }
    )
    manager = ToolManager()
    await register_mujoco_tools(manager)
    assistant = RobotDevelopmentAssistant(
        agent_id="internal-robotics-agent",
        tool_manager=manager,
        propose=proposer,
        template=template,
    )
    result = await assistant.develop("Help me test this small robot arm")
    assert result["agent_id"] == "internal-robotics-agent"
    assert result["experiment"]["request"]["criteria"] == template.criteria.model_dump(
        mode="json"
    )
    assert result["experiment"]["request"]["steps"] == template.steps
    assert result["findings"][0]["source"] == "experiment.checks.final_joint_error"
    assert result["next_step"] == "review_failed_checks_or_numerical_diagnostics"
    # Failed physics acceptance causes a review, never another automatic proposal.
    proposer.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra",
    [
        {"criteria": {}},
        {"agent_id": "other"},
        {"endpoint_id": "hal://real-robot"},
        {"steps": 10000},
    ],
)
async def test_assistant_rejects_cognitive_scope_widening_before_tools(extra):
    from seedcore.robotics.mujoco_workbench.assistant import RobotDevelopmentAssistant

    template = position_recipe()
    manager = type("Manager", (), {"execute": AsyncMock()})()
    proposer = AsyncMock(
        return_value={
            "robot": template.robot.model_dump(mode="json"),
            "controller": template.controller.model_dump(mode="json"),
            "rationale": "Draft",
            **extra,
        }
    )
    assistant = RobotDevelopmentAssistant(
        agent_id="internal-robotics-agent",
        tool_manager=manager,
        propose=proposer,
        template=template,
    )
    with pytest.raises(ValidationError):
        await assistant.develop("Develop a robot")
    manager.execute.assert_not_awaited()
