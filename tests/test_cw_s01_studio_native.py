"""Validate actual Chrome downloads against source compilation and native 3.15.0."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from seedcore.robotics.assembly import canonical_assembly_bytes
from seedcore.robotics.mujoco_workbench.runtime import ENGINE_VERSION

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mode", ["position", "torque"])
def test_actual_browser_bundle_bytes_and_native_compile(mode):
    if os.environ.get("SEEDCORE_CW_S01_STUDIO_REQUIRED") != "1":
        pytest.skip("Run verify-authoring.cjs --browser for fresh downloaded artifacts")
    import mujoco as mj
    assert mj.__version__ == ENGINE_VERSION == "3.15.0"
    name = f"studio-reference-{mode}"
    directory = ROOT / "artifacts/robotics/cw-s01"
    raw = (directory / "studio" / f"{name}.cw-s01.model.json").read_bytes()
    assert raw == (directory / "models" / f"{name}.cw-s01.model.json").read_bytes()
    artifact = json.loads(raw)
    assert raw == canonical_assembly_bytes(artifact) + b"\n"
    payload = {k: v for k, v in artifact.items() if k != "modelDigest"}
    assert hashlib.sha256(canonical_assembly_bytes(payload)).hexdigest() == artifact["modelDigest"]
    assert artifact["physicalAcceptance"] is False and artifact["executionAuthority"] == "none"
    assert artifact["manifest"]["catalogProvenance"] == "synthetic_fixture"
    xml = (directory / "studio" / f"{name}.xml").read_bytes()
    assert xml == artifact["xml"].encode() == (directory / "models" / f"{name}.xml").read_bytes()
    model = mj.MjModel.from_xml_string(xml.decode())
    data = mj.MjData(model)
    mj.mj_forward(model, data)
    assert model.nq == model.nu == 2 and model.nbody == 5
    assert model.opt.timestep == 0.002
    for index, joint in enumerate(artifact["manifest"]["joints"]):
        assert model.qpos0[index] == joint["restAngleRad"]
        assert mj.mj_name2id(model, mj.mjtObj.mjOBJ_JOINT, joint["jointName"]) == index
