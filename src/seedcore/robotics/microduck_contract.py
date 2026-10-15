"""Pinned, offline Microduck observation and policy boundary. No motor access."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

POLICY_JOINTS = (
    "left_hip_yaw",
    "left_hip_roll",
    "left_hip_pitch",
    "left_knee",
    "left_ankle",
    "neck_pitch",
    "head_pitch",
    "head_yaw",
    "head_roll",
    "right_hip_yaw",
    "right_hip_roll",
    "right_hip_pitch",
    "right_knee",
    "right_ankle",
)
PHYSICAL_JOINTS = POLICY_JOINTS[:9] + ("mouth",) + POLICY_JOINTS[9:]
HOME_RAD = (
    0.0,
    -0.0873,
    -0.4579,
    -0.0049,
    0.4530,
    0.3491,
    0.3491,
    0.0,
    0.0,
    0.0,
    0.0873,
    0.4579,
    0.0049,
    -0.4530,
)
OBSERVATION_NAMES = (
    "base_ang_vel",
    "projected_gravity",
    "joint_pos",
    "joint_vel",
    "actions",
    "command",
    "head_command",
    "body_command",
)


def finite_vector(values, size: int, name: str) -> np.ndarray:
    raw = np.asarray(values)
    if raw.shape != (size,) or raw.dtype.kind not in "fiu":
        raise ValueError(f"{name}: expected {size} numeric values")
    with np.errstate(over="ignore", invalid="ignore"):
        vector = raw.astype(np.float32)
    if not np.isfinite(vector).all():
        raise ValueError(f"{name}: non-finite or float32-overflow value")
    return vector


def build_observation(
    *,
    gyro,
    gravity,
    positions,
    velocities,
    previous_action,
    twist=(0.0, 0.0, 0.0),
    head=(0.0,) * 4,
    body=(0.0,) * 6,
):
    """61 raw floats; normalization belongs to the pinned exported ONNX graph.

    Positions/velocities are in 15-channel runtime order. The mouth is omitted.
    Body x/y/yaw are deliberately uncommandable in this version of the contract.
    """
    q = np.delete(finite_vector(positions, 15, "positions"), 9)
    v = np.delete(finite_vector(velocities, 15, "velocities"), 9)
    body = finite_vector(body, 6, "body")
    if np.any(body[[0, 1, 5]] != 0):
        raise ValueError("body x/y/yaw are not admitted command axes")
    return np.concatenate(
        (
            finite_vector(gyro, 3, "gyro"),
            finite_vector(gravity, 3, "gravity"),
            q - np.asarray(HOME_RAD, dtype=np.float32),
            v,
            finite_vector(previous_action, 14, "previous_action"),
            finite_vector(twist, 3, "twist"),
            finite_vector(head, 4, "head"),
            body,
        )
    ).astype(np.float32)


class DeploymentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["seedcore.microduck.deployment.v1"]
    profile: Literal["offline_mujoco"]
    status: Literal["offline_candidate"]
    runtime: dict
    rl: dict
    body_manifest: str
    body_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy: dict
    observation_layout: tuple[dict, ...]
    policy_joints: tuple[str, ...]
    physical_joints: tuple[str, ...]
    home_rad: tuple[float, ...]
    action_scale: float = Field(gt=0, allow_inf_nan=False)
    policy_period_s: float = Field(gt=0, allow_inf_nan=False)
    tolerances: dict
    hardware: None
    open_gates: tuple[str, ...]

    @model_validator(mode="after")
    def pinned_contract(self):
        if (
            self.policy_joints != POLICY_JOINTS
            or self.physical_joints != PHYSICAL_JOINTS
        ):
            raise ValueError("unsupported joint ordering")
        if self.home_rad != HOME_RAD or self.action_scale != 1.0:
            raise ValueError("unsupported home/action scale")
        for source in (self.runtime, self.rl):
            revision = source.get("revision", "")
            if len(revision) != 40 or any(
                c not in "0123456789abcdef" for c in revision
            ):
                raise ValueError("source revision must be a full Git object ID")
        return self


def load_deployment_profile(path: str | Path) -> DeploymentProfile:
    return DeploymentProfile.model_validate_json(Path(path).read_bytes())


class PinnedPolicy:
    """CPU-only inference from verified bytes; no download, training or actuation."""

    def __init__(self, path: str | Path, *, expected_sha256: str):
        import onnxruntime as ort

        p = Path(path)
        if p.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("policy exceeds 8 MiB limit")
        data = p.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise ValueError("policy SHA-256 mismatch")
        # Bytes rather than a path prevent implicit external-weight file resolution.
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            data, sess_options=options, providers=["CPUExecutionProvider"]
        )
        inputs, outputs = self._session.get_inputs(), self._session.get_outputs()
        if (len(inputs), len(outputs)) != (1, 1):
            raise ValueError(
                "only the pinned feed-forward policy interface is supported"
            )
        for port, name, shape in (
            (inputs[0], "obs", [1, 61]),
            (outputs[0], "actions", [1, 14]),
        ):
            if (port.name, port.shape, port.type) != (name, shape, "tensor(float)"):
                raise ValueError("policy interface mismatch")
        metadata = self._session.get_modelmeta().custom_metadata_map
        if metadata.get("joint_names", "").split(",") != list(POLICY_JOINTS):
            raise ValueError("policy joint metadata mismatch")
        if metadata.get("observation_names", "").split(",") != list(OBSERVATION_NAMES):
            raise ValueError("policy observation metadata mismatch")
        if metadata.get("action_scale") != "1.0":
            raise ValueError("policy action scale mismatch")
        # Published metadata is rounded to three decimals: never use it as HOME.
        rounded_home = np.asarray(
            [float(x) for x in metadata.get("default_joint_pos", "").split(",")]
        )
        if rounded_home.shape != (14,) or not np.allclose(
            rounded_home, HOME_RAD, rtol=0, atol=0.000501
        ):
            raise ValueError("policy home metadata mismatch")
        self.sha256 = expected_sha256
        self.metadata = dict(metadata)

    def infer(self, observation) -> np.ndarray:
        obs = finite_vector(observation, 61, "observation")
        output = self._session.run(["actions"], {"obs": obs.reshape(1, 61)})[0]
        if output.shape != (1, 14):
            raise ValueError("policy returned an invalid action shape")
        return finite_vector(output[0], 14, "actions").copy()
