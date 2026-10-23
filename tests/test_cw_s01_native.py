"""CW-SIM-01: independent assembly semantics and native MuJoCo parity.

Synthetic models cannot qualify hardware. No simulator stepping or motor IO.
The dedicated verifier requires native dependencies; general pytest may skip
when the optional native engine or locked TypeScript toolchain is unavailable.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from seedcore.robotics.assembly import (
    AssemblyCatalog, canonical_assembly_bytes, validate_assembly,
)
from seedcore.robotics.component_registry import REGISTRY
from seedcore.robotics.mujoco_workbench.runtime import ENGINE_VERSION

ROOT = Path(__file__).resolve().parents[1]
CASES = [f"serial-{n}-{orientation}-{mode}" for n in (1, 2, 3)
         for orientation in ("aligned", "rotated") for mode in ("position", "torque")]
CASES += [f"studio-reference-{mode}" for mode in ("position", "torque")]


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    strict = os.environ.get("SEEDCORE_CW_S01_REQUIRE_NATIVE") == "1"
    try:
        mj = importlib.import_module("mujoco")
    except ImportError:
        if strict:
            pytest.fail("CW-S01 requires the pinned seedcore[robotics-sim] engine")
        pytest.skip("Optional seedcore[robotics-sim] engine unavailable")
    assert mj.__version__ == ENGINE_VERSION, "No engine-version fallback"
    if directory := os.environ.get("SEEDCORE_CW_S01_CASES_DIR"):
        output = Path(directory)
    else:
        tsx = ROOT / "ts/node_modules/.bin/tsx"
        if not tsx.exists() or not (ROOT / "ts/packages/drc-solver/dist/index.js").exists():
            if strict:
                pytest.fail("Run the CW-S01 source-build verifier first")
            pytest.skip("Build the locked TS workspaces with verify-mjcf.cjs first")
        output = tmp_path_factory.mktemp("cw-s01")
        subprocess.run([str(tsx), "tools/robotics/export-cw-s01.ts", str(output)], cwd=ROOT, check=True, capture_output=True, text=True)
    payload = json.loads((output / "cases.json").read_text())
    assert payload["scope"] == "offline_simulation_only"
    assert payload["physicalAcceptance"] is False
    assert len(payload["models"]) == len(CASES)
    return mj, payload


def rotation(q):
    """Independent scalar-first quaternion reference, not compiler output."""
    w, x, y, z = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-w*z), 2*(x*z+w*y)],
                     [2*(x*y+w*z), 1-2*(x*x+z*z), 2*(y*z-w*x)],
                     [2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)]])


def about_axis(axis, angle):
    x, y, z = axis
    cross = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + math.sin(angle)*cross + (1-math.cos(angle))*(cross@cross)


def tensor(values):
    return np.array([[values["ixx"], values["ixy"], values["ixz"]],
                     [values["ixy"], values["iyy"], values["iyz"]],
                     [values["ixz"], values["iyz"], values["izz"]]])


def expected_frames(assembly, angles):
    poses = {assembly["root_node_id"]: (np.eye(3), np.zeros(3))}
    edges = {e["parent_node_id"]: e for e in assembly["mechanical_tree"]}
    parent = assembly["root_node_id"]
    while parent in edges:
        edge = edges[parent]
        rest = edge["relative_transform"]
        R, t = rotation(rest["quaternion_wxyz"]), np.array(rest["position_m"])
        if edge["connection_type"] == "articulated_joint":
            joint = edge["joint"]
            turn = about_axis(joint["axis"], angles[joint["joint_id"]]-joint["rest_angle_rad"])
            pivot = np.array(joint["pivot_m"])
            R, t = turn@R, pivot + turn@(t-pivot)
        Rp, tp = poses[parent]
        parent = edge["child_node_id"]
        poses[parent] = Rp@R, tp+Rp@t
    return poses


@pytest.mark.parametrize("name", CASES)
def test_native_compile_fk_mass_inertia_and_actuator_ranges(exported, name):
    mj, payload = exported
    case = next(c for c in payload["models"] if c["name"] == name)
    source, artifact = case["input"], case["model"]
    assembly = source["assembly"]
    raw_parts = source["catalog"]["partDocuments"]
    # Validate against the existing authoritative Python path and actual bytes.
    catalog = AssemblyCatalog(tuple(p["raw_json"].encode() for p in raw_parts), REGISTRY, "synthetic_fixture")
    assert validate_assembly(assembly, catalog) == assembly
    parts = {p["identity"]["part_id"]: p for p in map(lambda d: json.loads(d["raw_json"]), raw_parts)}
    node_parts = {n["node_id"]: parts[n["part_id"]] for n in assembly["nodes"]}
    metadata = {k: v for k, v in artifact.items() if k != "modelDigest"}
    assert hashlib.sha256(canonical_assembly_bytes(metadata)).hexdigest() == artifact["modelDigest"]
    assert artifact["physicalAcceptance"] is False
    assert artifact["executionAuthority"] == "none"
    assert artifact["manifest"]["catalogProvenance"] == "synthetic_fixture"
    assert source["drcReport"]["disposition"] == "blocked"
    assert {f["code"] for f in source["drcReport"]["findings"]} == {"MECHANICAL_PROXY_UNQUALIFIED"}
    xml = ET.fromstring(artifact["xml"])
    assert all(e.tag not in {"asset", "mesh", "include", "freejoint", "plugin"} and "file" not in e.attrib for e in xml.iter())
    model = mj.MjModel.from_xml_string(artifact["xml"])
    data = mj.MjData(model)
    body_map = {b["nodeId"]: mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, b["bodyName"]) for b in artifact["manifest"]["bodies"]}
    assert set(body_map) == set(node_parts)
    assert model.nbody == len(node_parts)+1
    joints = [e["joint"] for e in assembly["mechanical_tree"] if e["connection_type"] == "articulated_joint"]
    assert model.njnt == model.nu == model.nq == model.nv == len(joints)
    mode = source["options"]["actuatorMode"]
    for index, joint in enumerate(joints):
        limits = joint["limits_rad"]
        assert model.jnt_type[index] == mj.mjtJoint.mjJNT_HINGE
        np.testing.assert_allclose(model.jnt_range[index], [limits["min_rad"], limits["max_rad"]], atol=1e-12, rtol=0)
        assert model.qpos0[index] == pytest.approx(joint["rest_angle_rad"])
        assert model.actuator_trnid[index, 0] == index
        torque = limits["max_torque_nm"]
        control = [limits["min_rad"], limits["max_rad"]] if mode == "position" else [-torque, torque]
        np.testing.assert_allclose(model.actuator_ctrlrange[index], control, atol=1e-12, rtol=0)
        np.testing.assert_allclose(model.actuator_forcerange[index], [-torque, torque], atol=1e-12, rtol=0)
        np.testing.assert_allclose(model.jnt_actfrcrange[index], [-torque, torque], atol=1e-12, rtol=0)
        assert model.actuator_ctrllimited[index] and model.actuator_forcelimited[index]
        assert model.actuator_gainprm[index, 0] == pytest.approx(10 if mode == "position" else 1)
        entry = artifact["manifest"]["joints"][index]
        assert entry["jointId"] == joint["joint_id"]
        assert entry["maxVelocityRadS"] == limits["max_velocity_rad_s"]  # metadata only
    states = [[j["rest_angle_rad"] for j in joints], [0.0]*len(joints), [-0.5]*len(joints), [0.5]*len(joints), [0.15-i*0.1 for i in range(len(joints))]]
    order = [b["nodeId"] for b in artifact["manifest"]["bodies"]]
    for state_index, state in enumerate(states):
        data.qpos[:] = state
        mj.mj_forward(model, data)
        expected = expected_frames(assembly, dict(zip([j["joint_id"] for j in joints], state)))
        masses, coms, inertias = [], [], []
        for index, node in enumerate(order):
            bid = body_map[node]
            m = node_parts[node]["mechanical"]
            R, t = expected[node]
            np.testing.assert_allclose(data.xpos[bid], t, atol=1e-11, rtol=0)
            np.testing.assert_allclose(data.xmat[bid].reshape(3, 3), R, atol=1e-11, rtol=0)
            mass = m["mass_kg"]
            assert model.body_mass[bid] == pytest.approx(mass, abs=1e-12)
            assert model.body_subtreemass[bid] == pytest.approx(sum(node_parts[n]["mechanical"]["mass_kg"] for n in order[index:]), abs=1e-12)
            com = t+R@np.array(m["center_of_mass_m"])
            np.testing.assert_allclose(data.xipos[bid], com, atol=1e-11, rtol=0)
            actual_rotation = data.ximat[bid].reshape(3, 3)
            actual_inertia = actual_rotation@np.diag(model.body_inertia[bid])@actual_rotation.T
            world_inertia = R@tensor(m["inertia_kg_m2"])@R.T
            np.testing.assert_allclose(actual_inertia, world_inertia, atol=1e-12, rtol=1e-8)
            masses.append(mass); coms.append(com); inertias.append(world_inertia)
        total = sum(masses)
        center = np.average(coms, axis=0, weights=masses)
        np.testing.assert_allclose(data.subtree_com[body_map[assembly["root_node_id"]]], center, atol=1e-11, rtol=0)
        aggregate = sum(I + mass*(np.dot(d, d)*np.eye(3)-np.outer(d, d)) for I, mass, d in zip(inertias, masses, np.array(coms)-center))
        if state_index == 0:
            drc_mass = source["drcReport"]["massProperties"]
            assert total == pytest.approx(drc_mass["totalMassKg"], abs=1e-12)
            np.testing.assert_allclose(center, drc_mass["centerOfMassWorldM"], atol=1e-11, rtol=0)
            np.testing.assert_allclose(aggregate, tensor(drc_mass["inertiaWorldAtComKgM2"]), atol=1e-12, rtol=1e-8)


def test_original_starter_has_no_native_success_artifact(exported):
    _, payload = exported
    starter = payload["starter"]
    assert starter["drc"]["disposition"] == "blocked"
    assert starter["drc"]["physicalAcceptance"] is False
    assert starter["readiness"]["ready"] is False
    assert starter["readiness"]["blockingFindings"]
