from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from seedcore.hal.drivers.microduck import MicroduckReadOnlyDriver, DEFAULT_MANIFEST
from seedcore.robotics.microduck_contract import (
    HOME_RAD,
    POLICY_JOINTS,
    PinnedPolicy,
    build_observation,
    load_deployment_profile,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = json.loads((ROOT / "tests/fixtures/microduck/golden-v1.json").read_text())


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=lambda c: c["id"])
def test_observations_match_pinned_upstream_rust(case):
    actual = build_observation(**case["input"])
    np.testing.assert_allclose(actual, case["observation"], rtol=0, atol=1e-6)
    assert actual.shape == (61,)
    assert actual.dtype == np.float32


def test_manifest_keeps_unresolved_deployment_gates_explicit():
    profile = load_deployment_profile(DEFAULT_MANIFEST)
    assert profile.hardware is None
    assert profile.policy["training_checkpoint_parity"] == "not_available"
    assert profile.open_gates
    assert profile.policy_joints == POLICY_JOINTS
    bad = json.loads(DEFAULT_MANIFEST.read_text())
    bad["home_rad"][1] = -0.087  # rounded metadata must not replace source values
    with pytest.raises(ValueError, match="home/action"):
        type(profile).model_validate(bad)


@pytest.mark.parametrize(
    "field,size",
    [
        ("positions", 15),
        ("velocities", 15),
        ("gyro", 3),
        ("gravity", 3),
        ("previous_action", 14),
    ],
)
def test_bad_sensor_inputs_are_not_silently_padded_or_zeroed(field, size):
    raw = copy.deepcopy(GOLDEN["cases"][0]["input"])
    raw[field] = [0.0] * (size - 1)
    with pytest.raises(ValueError):
        build_observation(**raw)
    raw[field] = [float("nan")] * size
    with pytest.raises(ValueError):
        build_observation(**raw)


def test_mouth_does_not_leak_and_unbound_body_axes_are_rejected():
    raw = copy.deepcopy(GOLDEN["cases"][0]["input"])
    first = build_observation(**raw)
    raw["positions"][9] = 2.5
    raw["velocities"][9] = 100.0
    np.testing.assert_array_equal(first, build_observation(**raw))
    raw["body"][0] = 0.1
    with pytest.raises(ValueError, match="body x/y/yaw"):
        build_observation(**raw)


def test_native_readonly_startup_does_not_step_or_apply_policy(monkeypatch):
    mj = pytest.importorskip("mujoco")
    monkeypatch.setattr(mj, "mj_step", lambda *args: pytest.fail("M1 must never step"))
    driver = MicroduckReadOnlyDriver()
    assert driver.connect()
    qpos, ctrl = driver._data.qpos.copy(), driver._data.ctrl.copy()
    for _ in range(3):
        state = driver.get_state()
        observation = driver.get_observation()
        assert state["physical"] is False
        assert state["simulation_time_s"] == 0
        np.testing.assert_array_equal(observation[6:20], np.zeros(14))
        np.testing.assert_array_equal(observation[3:6], [0, 0, -1])
        np.testing.assert_array_equal(driver._data.qpos, qpos)
        np.testing.assert_array_equal(driver._data.ctrl, ctrl)
    assert driver.get_proprioception().joint_positions["mouth"] == 0
    for method in (
        driver.move_joints,
        driver.move_instant,
        driver.move_smooth,
        driver.move_to_pose,
    ):
        with pytest.raises(PermissionError, match="read-only"):
            method({})
    driver.disconnect()
    with pytest.raises(RuntimeError, match="disconnected"):
        driver.get_state()


def test_requested_hardware_never_falls_back_to_simulation():
    with pytest.raises(RuntimeError, match="no simulation fallback"):
        MicroduckReadOnlyDriver({"profile": "hardware"})
    with pytest.raises(ValueError):
        MicroduckReadOnlyDriver({"profile": "implicit"})
    with pytest.raises(ValueError, match="provider"):
        MicroduckReadOnlyDriver({"profile": "daemon_fake_io"})


def fake_snapshot():
    return {
        "profile": "daemon_fake_io",
        "sequence": 1,
        "captured_at": 1.0,
        "positions": list(HOME_RAD[:9]) + [0.0] + list(HOME_RAD[9:]),
        "velocities": [0.0] * 15,
        "gyro": [0.0] * 3,
        "gravity": [0.0, 0.0, -1.0],
    }


def test_fake_io_has_distinct_identity_and_rejects_replay_after_reconnect():
    snapshot = fake_snapshot()
    driver = MicroduckReadOnlyDriver(
        {"profile": "daemon_fake_io"},
        snapshot_provider=lambda: snapshot,
        clock=lambda: 1.01,
    )
    driver.connect()
    assert "daemon_fake_io" in driver.get_state()["endpoint_id"]
    driver.disconnect()
    driver.connect()
    with pytest.raises(ValueError, match="replayed"):
        driver.get_state()


@pytest.mark.parametrize(
    "update",
    [
        {"captured_at": 0.0},
        {"captured_at": 2.0},
        {"positions": [float("inf")] * 15},
        {"profile": "hardware"},
        {"sequence": True},
    ],
)
def test_fake_io_rejects_invalid_identity_freshness_and_values(update):
    snapshot = {**fake_snapshot(), **update}
    driver = MicroduckReadOnlyDriver(
        {"profile": "daemon_fake_io"},
        snapshot_provider=lambda: snapshot,
        clock=lambda: 1.01,
    )
    driver.connect()
    with pytest.raises(ValueError):
        driver.get_state()


def test_native_sensor_failure_is_explicit():
    pytest.importorskip("mujoco")
    driver = MicroduckReadOnlyDriver()
    driver.connect()
    driver._data.qvel[:] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        driver.get_state()


def test_downloaded_policy_matches_independent_onnx_reference():
    pytest.importorskip("onnxruntime")
    profile = load_deployment_profile(DEFAULT_MANIFEST)
    path = ROOT / profile.policy["local_cache"]
    if not path.exists():
        pytest.skip(
            "pinned public policy not downloaded; run documented hf download command"
        )
    policy = PinnedPolicy(path, expected_sha256=profile.policy["sha256"])
    for case in GOLDEN["cases"]:
        output = policy.infer(build_observation(**case["input"]))
        np.testing.assert_allclose(output, case["actions"], rtol=0, atol=1e-5)
    with pytest.raises(ValueError, match="SHA-256"):
        PinnedPolicy(path, expected_sha256="0" * 64)
    with pytest.raises(ValueError):
        policy.infer([float("nan")] * 61)
