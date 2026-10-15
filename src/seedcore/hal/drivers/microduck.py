"""M1 read-only Microduck profiles. There is intentionally no actuation path."""

from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np

from seedcore.hal.interfaces import (
    BaseRobotDriver,
    RobotCapabilities,
    RobotState,
    ProprioceptionState,
)
from seedcore.robotics.microduck_contract import (
    HOME_RAD,
    POLICY_JOINTS,
    PHYSICAL_JOINTS,
    build_observation,
    finite_vector,
    load_deployment_profile,
)
from seedcore.robotics.model_package import load_model_package

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_MANIFEST = ROOT / "packages/robotics-profiles/microduck-sim-v1.json"


class MicroduckReadOnlyDriver(BaseRobotDriver):
    def __init__(self, config=None, *, snapshot_provider=None, clock=time.monotonic):
        super().__init__(config)
        self.profile = self.config.get("profile", "offline_mujoco")
        if self.profile not in {"offline_mujoco", "daemon_fake_io", "hardware"}:
            raise ValueError("an explicit supported Microduck profile is required")
        if self.profile == "hardware":
            raise RuntimeError("hardware profile unavailable; no simulation fallback")
        if self.profile == "daemon_fake_io" and not callable(snapshot_provider):
            raise ValueError(
                "daemon_fake_io requires an explicit read-only snapshot provider"
            )
        self.endpoint_id = f"microduck_sim://{self.profile}/reference-v1"
        self._endpoint_id = self.endpoint_id
        self._clock, self._provider = clock, snapshot_provider
        self._model = self._data = self._mj = None
        self._last_sequence = -1
        self._last_captured_at = -math.inf

    def _initialize_capabilities(self):
        return RobotCapabilities(supported_pose_types=[])

    def connect(self):
        if self.state != RobotState.DISCONNECTED:
            raise RuntimeError("already connected")
        if self.profile == "offline_mujoco":
            from seedcore.robotics.mujoco_workbench.runtime import require_engine

            deployment = load_deployment_profile(
                self.config.get("deployment_manifest", DEFAULT_MANIFEST)
            )
            body = (ROOT / deployment.body_manifest).resolve()
            if not body.is_relative_to(ROOT):
                raise ValueError("body manifest must be repository-local")
            loaded = load_model_package(
                body, expected_manifest_sha256=deployment.body_manifest_sha256
            )
            mj = require_engine()
            model, data = loaded.model, mj.MjData(loaded.model)
            q = [int(model.joint(name).qposadr[0]) for name in POLICY_JOINTS]
            # Initialize offline state only: no step(), socket, policy or motor enable.
            data.qpos[q] = HOME_RAD
            data.ctrl[:] = HOME_RAD
            mj.mj_forward(model, data)
            self._mj, self._model, self._data = mj, model, data
        self._state = RobotState.CONNECTED
        return True

    def disconnect(self):
        self._model = self._data = self._mj = None
        self._state = RobotState.DISCONNECTED
        # Sequence watermarks deliberately survive reconnect on this instance.

    def get_state(self):
        if self.state != RobotState.CONNECTED:
            raise RuntimeError("Microduck read-only adapter is disconnected")
        now = self._clock()
        if type(now) not in (int, float) or not math.isfinite(now):
            raise ValueError("invalid observation clock")
        if self.profile == "daemon_fake_io":
            raw = dict(self._provider())
            expected = {
                "profile",
                "sequence",
                "captured_at",
                "positions",
                "velocities",
                "gyro",
                "gravity",
            }
            if set(raw) != expected or raw["profile"] != "daemon_fake_io":
                raise ValueError("wrong fake-I/O snapshot identity/schema")
            seq, captured = raw["sequence"], raw["captured_at"]
            if type(seq) is not int or seq <= self._last_sequence:
                raise ValueError("replayed/out-of-order fake-I/O snapshot")
            if type(captured) not in (int, float) or not math.isfinite(captured):
                raise ValueError("invalid snapshot capture time")
            if captured < self._last_captured_at or not 0 <= now - captured <= 0.1:
                raise ValueError("stale/future fake-I/O snapshot")
            snapshot = {
                name: finite_vector(raw[name], size, name).tolist()
                for name, size in (
                    ("positions", 15),
                    ("velocities", 15),
                    ("gyro", 3),
                    ("gravity", 3),
                )
            }
            self._last_sequence, self._last_captured_at = seq, captured
            simulation_time = None
        else:
            mj, model, data = self._mj, self._model, self._data
            positions, velocities = np.zeros(15), np.zeros(15)
            for name in POLICY_JOINTS:
                i = PHYSICAL_JOINTS.index(name)
                joint = model.joint(name)
                positions[i] = data.qpos[int(joint.qposadr[0])]
                velocities[i] = data.qvel[int(joint.dofadr[0])]
            # MuJoCo gyro sensors and projected gravity are both in trunk coordinates.
            gyro_sensor = model.sensor("imu_ang_vel").id
            if model.sensor_type[gyro_sensor] != mj.mjtSensor.mjSENS_GYRO:
                raise ValueError("pinned imu_ang_vel sensor is not a gyro")
            gyro = data.sensordata[int(model.sensor_adr[gyro_sensor]) :][:3]
            trunk = model.body("trunk_base").id
            gravity = data.xmat[trunk].reshape(3, 3).T @ np.array([0.0, 0.0, -1.0])
            snapshot = {
                "positions": positions.tolist(),
                "velocities": velocities.tolist(),
                "gyro": gyro.tolist(),
                "gravity": gravity.tolist(),
            }
            simulation_time = float(data.time)
        snapshot = {
            name: finite_vector(snapshot[name], size, name).tolist()
            for name, size in (
                ("positions", 15),
                ("velocities", 15),
                ("gyro", 3),
                ("gravity", 3),
            )
        }
        return {
            "profile": self.profile,
            "endpoint_id": self.endpoint_id,
            "captured_at": now,
            "simulation_time_s": simulation_time,
            "physical": False,
            **snapshot,
        }

    def get_observation(self, *, previous_action=(0.0,) * 14, **commands):
        state = self.get_state()
        return build_observation(
            **{k: state[k] for k in ("gyro", "gravity", "positions", "velocities")},
            previous_action=previous_action,
            **commands,
        )

    def get_current_pose(self, pose_type="joints"):
        return dict(zip(PHYSICAL_JOINTS, self.get_state()["positions"], strict=True))

    def get_proprioception(self):
        s = self.get_state()
        return ProprioceptionState(
            joint_positions=dict(zip(PHYSICAL_JOINTS, s["positions"], strict=True)),
            imu_data={"gyro": s["gyro"], "gravity": s["gravity"]},
            timestamp=time.time(),
        )

    def _reject_motion(self, *args, **kwargs):
        raise PermissionError(
            "M1 read-only profile has no actuation authority or motion interface"
        )

    move_instant = move_smooth = move_to_pose = move_joints = play_audio = (
        _reject_motion
    )

    def emergency_stop(self):
        self.disconnect()

    def is_moving(self):
        return False

    def wait_for_motion_complete(self, timeout=None):
        return self.state == RobotState.CONNECTED

    def get_latest_frame(self):
        return None
