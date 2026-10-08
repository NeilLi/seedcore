"""Numerical and failure-mode checks for advisory navigation experiments."""

import json
import math
from dataclasses import asdict, replace

import pytest

from seedcore.robotics.navigation_sandbox import (
    CircleObstacle, PlanarCommand, PlanarState, SandboxConfig,
    assess_command, propose_dynamic_window, simulate_step,
)


def test_constant_twist_matches_analytic_quarter_circle():
    end = simulate_step(PlanarState(), PlanarCommand(1, 1), math.pi / 2)
    assert (end.x, end.y, end.yaw) == pytest.approx((1, 1, math.pi / 2))
    straight = simulate_step(PlanarState(yaw=math.pi / 2), PlanarCommand(2, 0), 0.5)
    assert (straight.x, straight.y) == pytest.approx((0, 1))


def test_collision_between_endpoints_is_rejected():
    config = SandboxConfig(dt=1, horizon_steps=1, max_speed=2, max_accel=2,
                           robot_radius=0.01, clearance_margin=0)
    result = assess_command(PlanarState(), PlanarCommand(1, 0),
                            (CircleObstacle(0.5, 0, 0.01),), config)
    # Neither endpoint overlaps, but the swept robot passes through the obstacle.
    assert result.status == "rejected"
    assert result.reason == "predicted_collision"
    assert result.min_clearance_m == pytest.approx(-0.02)


def test_curved_motion_clearance_includes_arc_not_just_chord():
    config = SandboxConfig(dt=math.pi / 2, horizon_steps=1, max_speed=1,
                           max_yaw_rate=1, robot_radius=0.01, clearance_margin=0)
    result = assess_command(PlanarState(speed=1, yaw_rate=1), PlanarCommand(1, 1),
                            (CircleObstacle(math.sqrt(0.5), 1 - math.sqrt(0.5)),), config)
    assert result.reason == "predicted_collision"


def test_empty_obstacles_and_exact_horizon_are_json_serializable():
    config = SandboxConfig(horizon_steps=7)
    result = assess_command(PlanarState(), PlanarCommand(0.05, 0), (), config)
    assert result.status == "model_clear"
    assert len(result.trajectory) == 8
    assert result.trajectory[-1].x == pytest.approx(0.035)
    assert result.min_clearance_m is None
    json.dumps(asdict(result), allow_nan=False)


@pytest.mark.parametrize("command,reason", [
    (PlanarCommand(-0.1, 0), "velocity_limit"),
    (PlanarCommand(0.31, 0), "velocity_limit"),
    (PlanarCommand(0, 1.1), "velocity_limit"),
    (PlanarCommand(0.1, 0), "acceleration_window"),
    (PlanarCommand(0, 0.3), "acceleration_window"),
])
def test_out_of_bounds_proposals_are_rejected(command, reason):
    result = assess_command(PlanarState(), command, ())
    assert result.status == "rejected"
    assert result.reason == reason
    assert result.command is None


def test_fully_blocked_scene_returns_no_command_or_fake_stop():
    result = propose_dynamic_window(PlanarState(speed=0.2), (1, 0), (CircleObstacle(0, 0),))
    assert result.status == "no_feasible_candidate"
    assert result.command is None
    assert result.trajectory == ()
    assert result.candidate_count > 0


def test_obstacle_changes_selection_and_output_stays_advisory():
    state = PlanarState(speed=0.2)
    clear = propose_dynamic_window(state, (1, 0), ())
    obstacle = (CircleObstacle(0.55, 0, 0.05),)
    straight = assess_command(state, PlanarCommand(0.2, 0), obstacle)
    result = propose_dynamic_window(state, (1, 0), obstacle)
    assert straight.reason == "predicted_collision"
    assert result.status == "candidate"
    assert result.command != clear.command
    assert result.min_clearance_m > 0
    assert result.mode == "OFFLINE_ADVISORY_NO_ACTUATION"
    assert result == propose_dynamic_window(state, (1, 0), obstacle)
    assert state == PlanarState(speed=0.2)
    reassessed = assess_command(state, result.command, obstacle)
    assert reassessed.trajectory == result.trajectory


def test_narrow_window_keeps_current_and_zero_samples():
    config = SandboxConfig(max_speed=0.001, max_yaw_rate=0.001)
    result = propose_dynamic_window(PlanarState(), (1, 0), (), config)
    assert result.status == "candidate"
    assert result.command.speed == pytest.approx(0.001)
    assert result.command.yaw_rate == 0


@pytest.mark.parametrize("factory", [
    lambda: PlanarState(x=math.nan), lambda: PlanarCommand(0, math.inf),
    lambda: CircleObstacle(0, 0, -1), lambda: CircleObstacle(True, 0),
    lambda: SandboxConfig(dt=0), lambda: SandboxConfig(max_accel=-1),
    lambda: SandboxConfig(horizon_steps=201), lambda: SandboxConfig(horizon_steps=1.5),
    lambda: SandboxConfig(samples_per_axis=1), lambda: SandboxConfig(clearance_margin=-1),
])
def test_invalid_numeric_inputs_are_rejected(factory):
    with pytest.raises(ValueError):
        factory()


def test_invalid_scene_and_goal_are_rejected():
    with pytest.raises(ValueError, match="initial velocity"):
        propose_dynamic_window(PlanarState(speed=1), (1, 0), ())
    with pytest.raises(ValueError, match="goal"):
        propose_dynamic_window(PlanarState(), (math.nan, 0), ())
    with pytest.raises(ValueError, match="256"):
        propose_dynamic_window(PlanarState(), (1, 0), (CircleObstacle(1, 1),) * 257)


def test_no_clearance_claim_beyond_the_horizon():
    state, command = PlanarState(speed=0.2), PlanarCommand(0.2, 0)
    obstacle = (CircleObstacle(0.6, 0),)
    config = SandboxConfig(horizon_steps=10)
    assert assess_command(state, command, obstacle, config).status == "model_clear"
    assert assess_command(state, command, obstacle, replace(config, horizon_steps=40)).status == "rejected"


def test_finite_inputs_that_overflow_do_not_produce_a_clearance_claim():
    with pytest.raises(ValueError, match="arithmetic overflow"):
        assess_command(PlanarState(x=1e308), PlanarCommand(0, 0),
                       (CircleObstacle(-1e308, 0),))
    with pytest.raises(ValueError, match="ranking arithmetic overflow"):
        propose_dynamic_window(PlanarState(x=-1e308), (1e308, 0), ())
