"""CW-MOM-01: independent Hermite target calculation and uninterrupted native parity.

No physical actuation, signer enrollment or policy execution is exercised here.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
NAMES = [f"serial-{n}-{orientation}" for n in (1, 2, 3) for orientation in ("aligned", "rotated")] + ["studio-reference"]


@pytest.fixture(scope="module")
def gesture_cases(tmp_path_factory):
    strict = os.environ.get("SEEDCORE_CW_S04_REQUIRE_NATIVE") == "1"
    try:
        mj = importlib.import_module("mujoco")
    except ImportError:
        if strict:
            pytest.fail("CW-S04 requires pinned native MuJoCo")
        pytest.skip("Optional native MuJoCo unavailable")
    assert mj.__version__ == "3.15.0"
    if directory := os.environ.get("SEEDCORE_CW_S04_CASES_DIR"):
        out = Path(directory)
    else:
        tsx = ROOT / "ts/node_modules/.bin/tsx"
        if not tsx.exists() or not (ROOT / "ts/packages/wasm-sim-bridge/dist/gesture.js").exists():
            if strict:
                pytest.fail("Build CW-S04 source workspaces first")
            pytest.skip("CW-S04 TypeScript workspace not built")
        out = tmp_path_factory.mktemp("cw-s04")
        subprocess.run([str(tsx), "tools/robotics/export-cw-s04.ts", str(out)], cwd=ROOT, check=True, capture_output=True, text=True)
    payload = json.loads((out / "cases.json").read_text())
    assert payload["scope"] == "offline_simulation_only"
    assert payload["physicalAcceptance"] is False
    assert payload["executionAuthority"] == "none"
    assert payload["starter"]["disposition"] == "blocked"
    assert payload["starter"]["readiness"]["ready"] is False
    assert {c["name"] for c in payload["cases"]} == set(NAMES)
    return mj, payload


@pytest.mark.parametrize("name", NAMES)
def test_cw_s04_hermite_commands_and_native_wasm_rollout(gesture_cases, name):
    mj, payload = gesture_cases
    case = next(c for c in payload["cases"] if c["name"] == name)
    replay = case["replay"]
    draft = replay["gesture"]["draft"]
    assert replay["scope"] == "offline_simulation_only"
    assert replay["physicalAcceptance"] is False and replay["executionAuthority"] == "none"
    assert draft["interpolation"] == "cubic_hermite" and draft["timeScale"] == 1 and draft["loops"] == 1
    model = mj.MjModel.from_xml_string(case["model"]["xml"])
    assert model.opt.timestep == 0.002
    assert case["model"]["manifest"]["options"]["positionGain"] == 1
    data = mj.MjData(model)
    assert len(replay["samples"]) == 120
    for index, sample in enumerate(replay["samples"]):
        tick = index + 1
        assert sample["tick"] == tick and sample["policyStep"] == index
        assert sample["stepExecuted"] is True and sample["vetoReason"] is None
        expected = []
        for track in draft["tracks"]:
            k0, k1 = next((a, b) for a, b in zip(track["knots"], track["knots"][1:]) if a["tick"] <= tick <= b["tick"])
            u = (tick - k0["tick"]) / (k1["tick"] - k0["tick"])
            seconds = (k1["tick"] - k0["tick"]) * 0.002
            # Independent Hermite basis, rather than the TS polynomial coefficients.
            expected.append((2*u**3 - 3*u**2 + 1)*k0["positionRad"] + (u**3 - 2*u**2 + u)*seconds*k0["velocityRadS"]
                            + (-2*u**3 + 3*u**2)*k1["positionRad"] + (u**3-u**2)*seconds*k1["velocityRadS"])
        np.testing.assert_allclose(sample["ctrl"], expected, atol=1e-15, rtol=0)
        data.ctrl[:] = sample["ctrl"]
        mj.mj_step(model, data)  # No reset/state injection between steps.
        assert sample["simTimeSeconds"] == pytest.approx(data.time, abs=1e-12)
        for key, actual in [("qpos", data.qpos), ("qvel", data.qvel), ("qfrcActuator", data.qfrc_actuator), ("xpos", data.xpos.reshape(-1))]:
            np.testing.assert_allclose(sample[key], actual, atol=1e-12, rtol=0)
    assert replay["summary"]["status"] == "completed"
    assert replay["summary"]["executedSubsteps"] == 120
    np.testing.assert_allclose(replay["summary"]["finalQpos"], data.qpos, atol=1e-12, rtol=0)
