"""Bounded, stateless MuJoCo experiments with explicit provenance and diagnostics."""

from __future__ import annotations

import hashlib
import importlib
import json
import platform
from uuid import uuid4

from .contracts import ComparisonSpec, ExperimentSpec, RobotSpec
from .models import build_mjcf

ENGINE_VERSION = "3.15.0"
ADAPTER_VERSION = "seedcore-mujoco-workbench-v1"
PROFILE = "OFFLINE_MUJOCO_NO_ACTUATION"


def require_engine():
    try:
        mj = importlib.import_module("mujoco")
    except ImportError as exc:
        raise RuntimeError(
            f"MuJoCo unavailable; install seedcore[robotics-sim] or mujoco=={ENGINE_VERSION}"
        ) from exc
    if mj.__version__ != ENGINE_VERSION:
        raise RuntimeError(
            f"MuJoCo version mismatch: expected {ENGINE_VERSION}, found {mj.__version__}"
        )
    return mj


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _compile(robot: RobotSpec):
    robot = RobotSpec.model_validate(robot.model_dump(mode="json"))
    mj = require_engine()
    xml = build_mjcf(robot)
    return mj, mj.MjModel.from_xml_string(xml), xml


def inspect_robot(robot: RobotSpec) -> dict:
    mj, model, xml = _compile(robot)
    return {
        "profile": PROFILE,
        "engine": "mujoco",
        "engine_version": mj.__version__,
        "adapter_version": ADAPTER_VERSION,
        "model_sha256": _digest(xml),
        "robot": robot.model_dump(mode="json"),
        "mjcf": xml,
        "dimensions": {
            "nq": model.nq,
            "nv": model.nv,
            "nu": model.nu,
            "nbody": model.nbody,
            "nsensor": model.nsensor,
        },
        "joint_names": [f"joint_{i}" for i in range(len(robot.links))],
        "sensor_names": [
            mj.mj_id2name(model, mj.mjtObj.mjOBJ_SENSOR, i)
            for i in range(model.nsensor)
        ],
        "timestep_s": float(model.opt.timestep),
        "limitations": [
            "primitive_serial_models_only",
            "synthetic_sensor_data",
            "no_hardware_adapter",
            "no_execution_authority",
        ],
    }


def run_experiment(spec: ExperimentSpec) -> dict:
    """Each attempt compiles its own model and owns fresh mjData; no shared state."""
    import numpy as np

    # Revalidate even programmatic model_copy/update inputs before native calls.
    spec = ExperimentSpec.model_validate(spec.model_dump(mode="json"))
    mj, model, xml = _compile(spec.robot)
    model.opt.enableflags |= int(mj.mjtEnableBit.mjENBL_ENERGY)
    data = mj.MjData(model)
    n = len(spec.robot.links)
    q_indices = [int(model.joint(f"joint_{i}").qposadr[0]) for i in range(n)]
    v_indices = [int(model.joint(f"joint_{i}").dofadr[0]) for i in range(n)]
    data.qpos[q_indices] = spec.initial_joint_angles_rad or (0.0,) * n
    data.qvel[v_indices] = spec.initial_joint_velocities_rad_s or (0.0,) * n
    limits = np.asarray([link.torque_limit_nm for link in spec.robot.links])
    target = np.asarray(spec.controller.values)
    lower = np.asarray([link.lower_rad for link in spec.robot.links])
    upper = np.asarray([link.upper_rad for link in spec.robot.links])
    mj.mj_forward(model, data)
    trace = []
    max_speed = 0.0
    max_contacts = 0
    max_joint_limit_excess = 0.0
    contact_pairs = set()
    saturated_ticks = 0
    failure = None
    completed_steps = 0

    def diagnostics():
        if not all(
            np.isfinite(array).all()
            for array in (
                data.qpos,
                data.qvel,
                data.qacc,
                data.sensordata,
                data.ctrl,
                data.energy,
            )
        ):
            return "non_finite_state"
        warnings = [
            mj.mjtWarning(i).name
            for i, warning in enumerate(data.warning)
            if warning.number
        ]
        return ",".join(warnings) if warnings else None

    def observe():
        nonlocal max_speed, max_contacts, max_joint_limit_excess
        if n:
            max_speed = max(max_speed, float(np.max(np.abs(data.qvel[v_indices]))))
            joint_angles = data.qpos[q_indices]
            excess = np.maximum(
                np.maximum(lower - joint_angles, joint_angles - upper), 0.0
            )
            max_joint_limit_excess = max(max_joint_limit_excess, float(np.max(excess)))
        max_contacts = max(max_contacts, data.ncon)
        for contact in data.contact:
            pair = sorted(
                (
                    mj.mj_id2name(model, mj.mjtObj.mjOBJ_GEOM, int(contact.geom1)),
                    mj.mj_id2name(model, mj.mjtObj.mjOBJ_GEOM, int(contact.geom2)),
                )
            )
            contact_pairs.add(tuple(pair))

    def snapshot(tick: int):
        sensors = {}
        for i in range(model.nsensor):
            start, dimension = int(model.sensor_adr[i]), int(model.sensor_dim[i])
            name = mj.mj_id2name(model, mj.mjtObj.mjOBJ_SENSOR, i)
            sensors[name] = data.sensordata[start : start + dimension].tolist()
        return {
            "tick": tick,
            "time_s": float(data.time),
            "qpos": data.qpos.tolist(),
            "qvel": data.qvel.tolist(),
            "control": data.ctrl.tolist(),
            "actuator_force": data.actuator_force.tolist(),
            "sensors": sensors,
            "contact_points": data.ncon,
            "energy_j": data.energy.tolist(),
        }

    failure = diagnostics()
    if failure is None:
        observe()
        trace.append(snapshot(0))
    for tick in range(1, spec.steps + 1):
        if failure is not None:
            break
        if spec.controller.mode == "position":
            torque = (
                spec.controller.kp * (target - data.qpos[q_indices])
                - spec.controller.kd * data.qvel[v_indices]
            )
            saturated_ticks += int(bool(np.any(np.abs(torque) > limits)))
            data.ctrl[:] = np.clip(torque, -limits, limits)
        elif spec.controller.mode == "torque":
            data.ctrl[:] = target
        else:
            data.ctrl[:] = 0
        mj.mj_step(model, data)
        # Recompute derived observations at the returned qpos/qvel, not the
        # preceding integration state. Also makes warning/sensor checks explicit.
        mj.mj_forward(model, data)
        completed_steps = tick
        failure = diagnostics()
        if failure is not None:
            break
        observe()
        if tick % spec.sample_every == 0 or tick == spec.steps:
            trace.append(snapshot(tick))

    error = (
        float(np.max(np.abs(target - data.qpos[q_indices])))
        if failure is None and spec.controller.mode == "position"
        else None
    )
    checks = {}
    if failure is None:
        criteria = spec.criteria
        if criteria.final_joint_error_rad is not None:
            checks["final_joint_error"] = error <= criteria.final_joint_error_rad
        if criteria.max_joint_speed_rad_s is not None:
            checks["max_joint_speed"] = max_speed <= criteria.max_joint_speed_rad_s
        if criteria.max_contact_points is not None:
            checks["max_contact_points"] = max_contacts <= criteria.max_contact_points
    status = (
        "numerical_failure"
        if failure
        else (
            "criteria_not_met"
            if checks and not all(checks.values())
            else "criteria_met" if checks else "completed_unassessed"
        )
    )
    result = {
        "run_id": str(uuid4()),
        "profile": PROFILE,
        "engine": "mujoco",
        "engine_version": mj.__version__,
        "adapter_version": ADAPTER_VERSION,
        "model_sha256": _digest(xml),
        "recipe_sha256": _digest(
            json.dumps(spec.model_dump(mode="json"), sort_keys=True, allow_nan=False)
        ),
        "environment": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "numpy": np.__version__,
        },
        "request": spec.model_dump(mode="json"),
        "status": status,
        "failure_reason": failure,
        "completed_steps": completed_steps,
        "checks": checks,
        "metrics": {
            "final_joint_error_rad": error,
            "max_joint_speed_rad_s": max_speed,
            "max_contact_points": max_contacts,
            "observed_contact_pairs": [list(pair) for pair in sorted(contact_pairs)],
            "max_joint_limit_excess_rad": max_joint_limit_excess,
            "saturated_control_fraction": saturated_ticks / max(1, completed_steps),
        },
        "trace": trace,
        "claim": "Simulation observations only; no physical acceptance or verifier closure.",
    }
    json.dumps(result, allow_nan=False)
    return result


def compare_experiments(spec: ComparisonSpec) -> dict:
    spec = ComparisonSpec.model_validate(spec.model_dump(mode="json"))
    baseline, candidate = run_experiment(spec.baseline), run_experiment(spec.candidate)
    before = baseline["metrics"]["final_joint_error_rad"]
    after = candidate["metrics"]["final_joint_error_rad"]
    return {
        "profile": PROFILE,
        "baseline": baseline,
        "candidate": candidate,
        "final_joint_error_change_rad": (
            None if before is None or after is None else after - before
        ),
        "claim": "Comparison under the preserved joint task; no automatic promotion or authority.",
    }
