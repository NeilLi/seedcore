"""CW-SIM-02 / CW-SIM-03 / CW-SIM-04: native Python MuJoCo 3.15.0 vs Wasm parity.

Compares model topology, mass/subtree-mass/inertia, multi-state forward kinematics,
and 120-substep decimated control rollouts produced by @mujoco/mujoco@3.15.0 Wasm
against native Python mujoco==3.15.0 across all 14 synthetic CW-S01 models.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess

import numpy as np
import pytest

from seedcore.robotics.assembly import canonical_assembly_bytes
from seedcore.robotics.mujoco_workbench.runtime import ENGINE_VERSION

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    f"serial-{n}-{orientation}-{mode}"
    for n in (1, 2, 3)
    for orientation in ("aligned", "rotated")
    for mode in ("position", "torque")
]
CASES += [f"studio-reference-{mode}" for mode in ("position", "torque")]

EXPECTED_WASM_PROFILE = "seedcore.cw-s02.mujoco-wasm-st.v1"
EXPECTED_WASM_BYTES = 10370402
EXPECTED_WASM_SHA256 = "d59c489dd521c80af6965756c5b90daff549fa281566544e4540c170d937633d"


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    strict = os.environ.get("SEEDCORE_CW_S02_REQUIRE_NATIVE") == "1"
    try:
        mj = importlib.import_module("mujoco")
    except ImportError:
        if strict:
            pytest.fail("CW-S02 requires the pinned seedcore[robotics-sim] engine")
        pytest.skip("Optional seedcore[robotics-sim] engine unavailable")
    assert mj.__version__ == ENGINE_VERSION == "3.15.0", "No engine-version fallback"

    if directory := os.environ.get("SEEDCORE_CW_S02_CASES_DIR"):
        output = Path(directory)
    else:
        tsx = ROOT / "ts/node_modules/.bin/tsx"
        if not tsx.exists() or not (ROOT / "ts/packages/wasm-sim-bridge/dist/index.js").exists():
            if strict:
                pytest.fail("Run the CW-S02 source-build verifier first")
            pytest.skip("Build the locked TS workspaces first")
        output = tmp_path_factory.mktemp("cw-s02")
        subprocess.run(
            [str(tsx), "tools/robotics/export-cw-s02.ts", str(output)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    payload = json.loads((output / "cases.json").read_text())
    assert payload["scope"] == "offline_simulation_only"
    assert payload["physicalAcceptance"] is False
    assert payload["executionAuthority"] == "none"
    assert payload["profile"] == EXPECTED_WASM_PROFILE
    assert payload["engineVersion"] == ENGINE_VERSION
    assert payload["wasmBytes"] == EXPECTED_WASM_BYTES
    assert payload["wasmSha256"] == EXPECTED_WASM_SHA256
    assert payload["planarFallbackUsed"] is False
    assert len(payload["models"]) == len(CASES)
    return mj, payload


@pytest.mark.parametrize("name", CASES)
def test_wasm_and_native_mujoco_3_15_0_inspection_fk_and_rollout_parity(exported, name):
    mj, payload = exported
    case = next(c for c in payload["models"] if c["name"] == name)
    artifact = case["model"]
    inspection = case["inspection"]
    fk_states = case["fkStates"]
    fk_snapshots = case["fkSnapshots"]
    rollout = case["rollout"]

    assert inspection["profile"] == EXPECTED_WASM_PROFILE
    assert inspection["engineVersion"] == ENGINE_VERSION
    assert inspection["wasmBytes"] == EXPECTED_WASM_BYTES
    assert inspection["wasmSha256"] == EXPECTED_WASM_SHA256
    assert inspection["scope"] == "offline_simulation_only"
    assert inspection["physicalAcceptance"] is False
    assert inspection["executionAuthority"] == "none"
    assert inspection["planarFallbackUsed"] is False
    assert inspection["modelDigest"] == artifact["modelDigest"]

    model = mj.MjModel.from_xml_string(artifact["xml"])
    data = mj.MjData(model)

    assert inspection["nq"] == model.nq
    assert inspection["nv"] == model.nv
    assert inspection["nu"] == model.nu
    assert inspection["nbody"] == model.nbody
    assert inspection["njnt"] == model.njnt
    assert inspection["timestepSeconds"] == pytest.approx(model.opt.timestep, abs=1e-15)

    np.testing.assert_allclose(inspection["bodyMass"], model.body_mass, atol=1e-12, rtol=0)
    np.testing.assert_allclose(inspection["bodySubtreeMass"], model.body_subtreemass, atol=1e-12, rtol=0)
    np.testing.assert_allclose(inspection["bodyInertia"], model.body_inertia, atol=1e-12, rtol=0)
    np.testing.assert_allclose(inspection["qpos0"], model.qpos0, atol=1e-12, rtol=0)
    np.testing.assert_allclose(inspection["jointRanges"], model.jnt_range, atol=1e-12, rtol=0)
    np.testing.assert_allclose(inspection["actuatorCtrlRanges"], model.actuator_ctrlrange, atol=1e-12, rtol=0)
    np.testing.assert_allclose(inspection["actuatorForceRanges"], model.actuator_forcerange, atol=1e-12, rtol=0)
    np.testing.assert_allclose(inspection["jointActuatorForceRanges"], model.jnt_actfrcrange, atol=1e-12, rtol=0)
    np.testing.assert_allclose(inspection["actuatorGain0"], model.actuator_gainprm[:, 0], atol=1e-12, rtol=0)

    # Multi-state FK parity (5 states per model)
    assert len(fk_states) == len(fk_snapshots) == 5
    root_node_id = artifact["manifest"]["bodies"][0]["nodeId"]
    root_bid = inspection["bodyIds"][root_node_id]

    for state, snap in zip(fk_states, fk_snapshots):
        mj.mj_resetData(model, data)
        data.qpos[:] = state
        data.qvel[:] = 0
        data.act[:] = 0
        data.ctrl[:] = 0
        data.qfrc_applied[:] = 0
        data.xfrc_applied[:] = 0
        mj.mj_forward(model, data)

        np.testing.assert_allclose(snap["qpos"], data.qpos, atol=1e-12, rtol=0)
        np.testing.assert_allclose(snap["rootSubtreeCom"], data.subtree_com[root_bid], atol=1e-12, rtol=0)
        for body_snap in snap["bodies"]:
            bid = body_snap["bodyId"]
            np.testing.assert_allclose(body_snap["xpos"], data.xpos[bid], atol=1e-12, rtol=0)
            np.testing.assert_allclose(body_snap["xquat"], data.xquat[bid], atol=1e-12, rtol=0)
            np.testing.assert_allclose(body_snap["xmat"], data.xmat[bid], atol=1e-12, rtol=0)
            np.testing.assert_allclose(body_snap["xipos"], data.xipos[bid], atol=1e-12, rtol=0)
            np.testing.assert_allclose(body_snap["ximat"], data.ximat[bid], atol=1e-12, rtol=0)
            assert body_snap["bodyMass"] == pytest.approx(model.body_mass[bid], abs=1e-12)
            assert body_snap["bodySubtreeMass"] == pytest.approx(model.body_subtreemass[bid], abs=1e-12)
            np.testing.assert_allclose(body_snap["bodyInertia"], model.body_inertia[bid], atol=1e-12, rtol=0)

    # 120-substep decimated control rollout parity
    summary = rollout["summary"]
    samples = rollout["samples"]
    assert summary["status"] == "completed"
    assert summary["vetoReason"] is None
    assert summary["fenceCode"] is None
    assert summary["totalSubsteps"] == summary["executedSubsteps"] == summary["capturedSamples"] == len(samples) == 120
    assert summary["policyDecimation"] == 10
    assert summary["policyUpdates"] == 12
    assert summary["planarFallbackUsed"] is False
    trace = {"modelDigest": artifact["modelDigest"], "timestepSeconds": 0.002,
             "policyDecimation": 10, "samples": [{k: v for k, v in s.items() if k != "monotonicMs"} for s in samples]}
    assert hashlib.sha256(canonical_assembly_bytes(trace)).hexdigest() == summary["traceDigest"]

    # Uninterrupted native rollout: never reset/inject Wasm state between steps.
    assert model.opt.timestep == 0.002
    if artifact["manifest"]["options"]["actuatorMode"] == "position":
        assert artifact["manifest"]["options"]["positionGain"] == 1
    mj.mj_resetData(model, data)
    for index, sample in enumerate(samples):
        assert sample["tick"] == index + 1 and sample["policyStep"] == index // 10
        assert sample["stepExecuted"] is True and sample["vetoReason"] is None
        data.ctrl[:] = sample["ctrl"]
        mj.mj_step(model, data)
        assert sample["simTimeSeconds"] == pytest.approx(data.time, abs=1e-12)
        np.testing.assert_allclose(sample["qpos"], data.qpos, atol=1e-12, rtol=0)
        np.testing.assert_allclose(sample["qvel"], data.qvel, atol=1e-12, rtol=0)
        np.testing.assert_allclose(sample["qfrcActuator"], data.qfrc_actuator, atol=1e-12, rtol=0)
        np.testing.assert_allclose(sample["xpos"], data.xpos.reshape(-1), atol=1e-12, rtol=0)
    np.testing.assert_allclose(summary["finalQpos"], data.qpos, atol=1e-12, rtol=0)
    np.testing.assert_allclose(summary["finalQvel"], data.qvel, atol=1e-12, rtol=0)


def test_cw_s02_starter_remains_blocked_and_wasm_binary_matches_pin(exported):
    _, payload = exported
    starter = payload["starter"]
    assert starter["drc"]["disposition"] == "blocked"
    assert starter["drc"]["physicalAcceptance"] is False
    assert starter["readiness"]["ready"] is False
    assert len(starter["readiness"]["blockingFindings"]) == 9
    wasm_file = ROOT / "ts/node_modules/@mujoco/mujoco/mujoco.wasm"
    raw = wasm_file.read_bytes()
    assert len(raw) == EXPECTED_WASM_BYTES
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_WASM_SHA256
