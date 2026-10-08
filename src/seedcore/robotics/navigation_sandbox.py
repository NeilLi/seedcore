"""Offline planar navigation experiments. Outputs carry no execution authority.

Original implementation of dynamic-window sampling, informed by PythonRobotics;
see docs/development/robotics/pythonrobotics_assessment.md for pinned references.
The circular unicycle model is neither Microduck dynamics nor a safety verifier.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import math


def _finite_record(record: object) -> None:
    for field in fields(record):
        value = getattr(record, field.name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{field.name} must be a finite number")


@dataclass(frozen=True)
class PlanarState:
    """Metres, radians, m/s and rad/s in a fixed world frame."""

    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    speed: float = 0.0
    yaw_rate: float = 0.0

    def __post_init__(self) -> None:
        _finite_record(self)


@dataclass(frozen=True)
class PlanarCommand:
    speed: float
    yaw_rate: float

    def __post_init__(self) -> None:
        _finite_record(self)


@dataclass(frozen=True)
class CircleObstacle:
    x: float
    y: float
    radius: float = 0.0

    def __post_init__(self) -> None:
        _finite_record(self)
        if self.radius < 0:
            raise ValueError("obstacle radius must be nonnegative")


@dataclass(frozen=True)
class SandboxConfig:
    """Synthetic research limits; these are not an admitted hardware profile."""

    dt: float = 0.1
    horizon_steps: int = 20
    samples_per_axis: int = 7
    max_speed: float = 0.3
    max_yaw_rate: float = 1.0
    max_accel: float = 0.5
    max_yaw_accel: float = 2.0
    robot_radius: float = 0.1
    clearance_margin: float = 0.05

    def __post_init__(self) -> None:
        _finite_record(self)
        for name, low, high in (("horizon_steps", 1, 200), ("samples_per_axis", 2, 31)):
            value = getattr(self, name)
            if not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"{name} must be an integer in [{low}, {high}]")
        for name in ("dt", "max_speed", "max_yaw_rate", "max_accel", "max_yaw_accel", "robot_radius"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.clearance_margin < 0:
            raise ValueError("clearance_margin must be nonnegative")


@dataclass(frozen=True)
class NavigationAssessment:
    """An advisory result, never a token, controller stop or completion receipt."""

    status: str
    reason: str
    command: PlanarCommand | None = None
    trajectory: tuple[PlanarState, ...] = ()
    min_clearance_m: float | None = None
    candidate_count: int = 0
    mode: str = "OFFLINE_ADVISORY_NO_ACTUATION"
    model: str = "circular-unicycle-v1"


def _validate_scene(state: PlanarState, obstacles: tuple[CircleObstacle, ...], config: SandboxConfig) -> None:
    if not 0 <= state.speed <= config.max_speed or abs(state.yaw_rate) > config.max_yaw_rate:
        raise ValueError("initial velocity outside sandbox limits")
    if len(obstacles) > 256:
        raise ValueError("at most 256 obstacles supported")


def simulate_step(state: PlanarState, command: PlanarCommand, dt: float) -> PlanarState:
    """Exact constant-twist kinematics; no actuator or acceleration dynamics."""
    if isinstance(dt, bool) or not math.isfinite(dt) or dt <= 0:
        raise ValueError("dt must be positive and finite")
    turn = command.yaw_rate * dt
    if not math.isfinite(turn):
        raise ValueError("motion arithmetic overflow")
    half_turn = turn / 2
    # sinc form is stable near zero angular velocity.
    distance = command.speed * dt * (math.sin(half_turn) / half_turn if half_turn else 1.0)
    direction = state.yaw + half_turn
    return PlanarState(
        state.x + distance * math.cos(direction),
        state.y + distance * math.sin(direction),
        math.atan2(math.sin(state.yaw + turn), math.cos(state.yaw + turn)),
        command.speed, command.yaw_rate,
    )


def _segment_distance(a: PlanarState, b: PlanarState, obstacle: CircleObstacle) -> float:
    dx, dy = b.x - a.x, b.y - a.y
    length2 = dx * dx + dy * dy
    projection = (obstacle.x - a.x) * dx + (obstacle.y - a.y) * dy
    if not math.isfinite(length2) or not math.isfinite(projection):
        raise ValueError("scene arithmetic overflow")
    fraction = max(0.0, min(1.0, projection / length2)) if length2 else 0.0
    return math.hypot(obstacle.x - a.x - fraction * dx, obstacle.y - a.y - fraction * dy)


def assess_command(
    state: PlanarState, command: PlanarCommand,
    obstacles: tuple[CircleObstacle, ...], config: SandboxConfig = SandboxConfig(),
) -> NavigationAssessment:
    """Check a proposed constant twist against this model's finite horizon.

    Acceleration limits constrain the first command change, as in a dynamic
    window. They do not model the motor ramp or stopping distance. Clearance
    uses swept segments inflated by an arc interpolation error bound.
    """
    _validate_scene(state, obstacles, config)
    if not 0 <= command.speed <= config.max_speed or abs(command.yaw_rate) > config.max_yaw_rate:
        return NavigationAssessment("rejected", "velocity_limit")
    if (abs(command.speed - state.speed) > config.max_accel * config.dt + 1e-12
            or abs(command.yaw_rate - state.yaw_rate) > config.max_yaw_accel * config.dt + 1e-12):
        return NavigationAssessment("rejected", "acceleration_window")
    trajectory = [state]
    for _ in range(config.horizon_steps):
        trajectory.append(simulate_step(trajectory[-1], command, config.dt))
    # For a constant-twist arc, ||position''|| = |speed * yaw_rate|.
    # Its distance from the interpolating chord is <= ||position''|| * dt²/8.
    arc_margin = abs(command.speed * command.yaw_rate) * config.dt**2 / 8
    clearance = min((
        _segment_distance(a, b, obstacle) - obstacle.radius - config.robot_radius
        - config.clearance_margin - arc_margin
        for a, b in zip(trajectory, trajectory[1:]) for obstacle in obstacles
    ), default=None)
    if clearance is not None and not math.isfinite(clearance):
        raise ValueError("clearance arithmetic overflow")
    return NavigationAssessment(
        "rejected" if clearance is not None and clearance <= 0 else "model_clear",
        "predicted_collision" if clearance is not None and clearance <= 0 else "finite_horizon_only",
        command, tuple(trajectory), clearance,
    )


def _samples(low: float, high: float, count: int, current: float) -> tuple[float, ...]:
    values = {low + (high - low) * i / (count - 1) for i in range(count)}
    values.update((low, high, current))
    if low <= 0 <= high:
        values.add(0.0)
    return tuple(sorted(values))


def propose_dynamic_window(
    state: PlanarState, goal: tuple[float, float],
    obstacles: tuple[CircleObstacle, ...], config: SandboxConfig = SandboxConfig(),
) -> NavigationAssessment:
    """Return a reproducible candidate or explicitly no feasible candidate.

    Inputs are offline snapshots. This function performs no freshness checks,
    policy admission, dispatch, revocation or evidence closure.
    """
    _validate_scene(state, obstacles, config)
    if len(goal) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in goal):
        raise ValueError("goal must contain two finite coordinates")
    delta_v, delta_w = config.max_accel * config.dt, config.max_yaw_accel * config.dt
    speeds = _samples(max(0.0, state.speed - delta_v), min(config.max_speed, state.speed + delta_v), config.samples_per_axis, state.speed)
    rates = _samples(max(-config.max_yaw_rate, state.yaw_rate - delta_w), min(config.max_yaw_rate, state.yaw_rate + delta_w), config.samples_per_axis, state.yaw_rate)
    best = None
    best_score = math.inf
    for speed in speeds:
        for rate in rates:
            result = assess_command(state, PlanarCommand(speed, rate), obstacles, config)
            if result.status != "model_clear":
                continue
            last = result.trajectory[-1]
            goal_distance = math.hypot(goal[0] - last.x, goal[1] - last.y)
            clearance_cost = 0.0 if result.min_clearance_m is None else 0.01 / result.min_clearance_m
            score = goal_distance + clearance_cost + 0.01 * abs(rate)
            if not math.isfinite(score):
                raise ValueError("ranking arithmetic overflow")
            if score < best_score:
                best, best_score = result, score
    count = len(speeds) * len(rates)
    if best is None:
        return NavigationAssessment("no_feasible_candidate", "all_candidates_rejected", candidate_count=count)
    return NavigationAssessment("candidate", "finite_horizon_only", best.command, best.trajectory, best.min_clearance_m, count)
