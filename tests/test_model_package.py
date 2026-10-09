"""External-package integrity, native parity, and pinned Microduck checks."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from seedcore.robotics.model_package import (
    ModelPackage,
    ModelPackageError,
    load_model_package,
    verify_model_package,
)
from seedcore.robotics.model_package.loader import _prepare_xml
from seedcore.robotics.mujoco_workbench.runtime import (
    require_engine,
    inspect_model_package,
)

ROOT = Path(__file__).resolve().parents[1]
MICRODUCK = ROOT / "packages/models/microduck/0.1.0/manifest.json"
MICRODUCK_MANIFEST_SHA256 = (
    "31018dfaa996b9a4ae519f121134b40331be2ef9b92835bb9274c5f777444371"
)
XML = """<mujoco><compiler angle="radian"/><worldbody>
<body name="arm"><joint name="hinge" range="-1 1"/>
<inertial pos="0 0 0" mass="0.2" diaginertia="0.01 0.01 0.01"/>
</body></worldbody><actuator><motor name="motor" joint="hinge"
ctrllimited="true" ctrlrange="-2 2" forcelimited="true" forcerange="-3 3"/>
</actuator></mujoco>"""


@pytest.fixture
def engine():
    pytest.importorskip("mujoco", reason="install seedcore[robotics-sim]")
    return require_engine()


def write_package(tmp_path, xml=XML, extra=None, changes=None):
    files = {
        "robot.xml": (xml.encode(), "model"),
        "LICENSE": (b"Test fixture license", "license"),
    }
    files.update(extra or {})
    manifest = {
        "schema_version": "seedcore.model-package.v1",
        "package_id": "test-arm",
        "version": "0.1.0",
        "format": "mjcf",
        "engine": "mujoco",
        "engine_version": "3.15.0",
        "entrypoint": "robot.xml",
        "source": {
            "repository_url": "https://example.com/robot",
            "revision": "a" * 40,
            "source_path": "robot.xml",
            "license": "test-only",
        },
        "files": [],
        "parity": {
            "total_mass_kg": 0.2,
            "nq": 1,
            "nv": 1,
            "timestep_s": 0.002,
            "bodies": [{"name": "arm", "parent": "world"}],
            "joints": [
                {"name": "hinge", "body": "arm", "type": "hinge", "range": [-1.0, 1.0]}
            ],
            "actuators": [
                {
                    "name": "motor",
                    "joint": "hinge",
                    "gear": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    "control_range": [-2.0, 2.0],
                    "force_range": [-3.0, 3.0],
                }
            ],
        },
    }
    for name, (data, role) in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest["files"].append(
            {
                "path": name,
                "role": role,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    if changes:
        changes(manifest)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def test_schema_is_current_and_baseline_has_independent_pin():
    assert (
        json.loads((ROOT / "packages/models/model-package.schema.json").read_text())
        == ModelPackage.model_json_schema()
    )
    package = verify_model_package(
        MICRODUCK, expected_manifest_sha256=MICRODUCK_MANIFEST_SHA256
    )
    assert len(package.manifest.parity.actuators) == 14
    assert len(package.files) == 41
    assert all(
        hashlib.sha256(data).hexdigest() == file.sha256
        for file in package.manifest.files
        for data in [package.files[file.path]]
    )


def test_integrity_precedes_native_compile_and_snapshot_is_immutable(tmp_path):
    path = write_package(tmp_path)
    package = verify_model_package(path)
    with pytest.raises(TypeError):
        package.files["robot.xml"] = b"different"
    (tmp_path / "robot.xml").write_text(XML.replace("0.2", "0.3"))
    assert _prepare_xml(package)[0].find('mass="0.2"') >= 0
    with patch("seedcore.robotics.mujoco_workbench.runtime.require_engine") as native:
        with pytest.raises(ModelPackageError, match="SHA-256 mismatch"):
            load_model_package(path)
        native.assert_not_called()


@pytest.mark.parametrize(
    "path",
    [
        "../outside.xml",
        "/tmp/model.xml",
        "a/../b.xml",
        "a//b",
        "./a",
        "a\\b",
        "https://example.com/a",
        "package://robot/a",
    ],
)
def test_manifest_rejects_unsafe_paths(tmp_path, path):
    manifest = write_package(tmp_path, changes=lambda m: m.update(entrypoint=path))
    with pytest.raises(ModelPackageError, match="unsafe package path"):
        verify_model_package(manifest)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "v2"),
        ("engine_version", "3.10.0"),
        ("version", "latest"),
        ("unknown", True),
    ],
)
def test_manifest_rejects_versions_and_extra_fields(tmp_path, field, value):
    path = write_package(tmp_path, changes=lambda m: m.update({field: value}))
    with pytest.raises(ModelPackageError):
        verify_model_package(path)


def test_duplicate_keys_inventory_and_license_rejected(tmp_path):
    path = write_package(tmp_path)
    raw = path.read_text()
    path.write_text(
        raw.replace('"version": "0.1.0"', '"version": "0.1.0", "version": "0.2.0"')
    )
    with pytest.raises(ModelPackageError, match="duplicate JSON key"):
        verify_model_package(path)
    path = write_package(tmp_path, changes=lambda m: m["files"].append(m["files"][0]))
    with pytest.raises(ModelPackageError, match="duplicate paths"):
        verify_model_package(path)
    path = write_package(
        tmp_path, changes=lambda m: m["files"][1].update(role="provenance")
    )
    with pytest.raises(ModelPackageError, match="license file"):
        verify_model_package(path)


def test_missing_file_symlink_and_size_mismatch(tmp_path):
    path = write_package(tmp_path)
    robot = tmp_path / "robot.xml"
    robot.unlink()
    with pytest.raises(ModelPackageError, match="missing"):
        verify_model_package(path)
    outside = tmp_path / "outside.xml"
    outside.write_text(XML)
    robot.symlink_to(outside)
    with pytest.raises(ModelPackageError, match="symlink"):
        verify_model_package(path)
    robot.unlink()
    robot.write_bytes(b"x")
    with pytest.raises(ModelPackageError, match="mismatch"):
        verify_model_package(path)


def test_manifest_pin_and_content_identity(tmp_path):
    path = write_package(tmp_path)
    first = verify_model_package(path)
    manifest = json.loads(path.read_text())
    manifest["files"].reverse()
    path.write_text(json.dumps(manifest, indent=2))
    second = verify_model_package(path)
    assert first.package_sha256 == second.package_sha256
    assert first.manifest_sha256 != second.manifest_sha256
    with pytest.raises(ModelPackageError, match="caller pin"):
        verify_model_package(path, expected_manifest_sha256=first.manifest_sha256)


@pytest.mark.parametrize(
    "xml",
    [
        '<mujoco><include file="missing.xml"/></mujoco>',
        '<mujoco><include file="../robot.xml"/></mujoco>',
        '<mujoco><asset><mesh file="/tmp/outside.stl"/></asset></mujoco>',
        '<mujoco><compiler meshdir="/tmp"/></mujoco>',
        '<mujoco><extension><plugin plugin="anything"/></extension></mujoco>',
        '<mujoco><worldbody><replicate count="1000000"/></worldbody></mujoco>',
        '<!DOCTYPE mujoco [<!ENTITY x "test">]><mujoco/>',
        '<mujoco><asset><model name="attached" file="robot.xml"/></asset></mujoco>',
        '<robot name="wrong-format"/>',
    ],
)
def test_unsafe_or_unsupported_xml_rejected_before_native_call(tmp_path, xml):
    path = write_package(tmp_path, xml)
    with patch("seedcore.robotics.mujoco_workbench.runtime.require_engine") as native:
        with pytest.raises(ModelPackageError):
            load_model_package(path)
        native.assert_not_called()


def test_nested_includes_and_cycle_detection(tmp_path, engine):
    fragment = XML.replace("<mujoco>", "<fragment>").replace("</mujoco>", "</fragment>")
    extra = {
        "parts/first.xml": (
            b'<fragment><include file="parts/second.xml"/></fragment>',
            "model",
        ),
        "parts/second.xml": (fragment.encode(), "model"),
    }
    path = write_package(
        tmp_path, '<mujoco><include file="parts/first.xml"/></mujoco>', extra
    )
    assert load_model_package(path).model.nu == 1
    extra["parts/second.xml"] = (
        b'<fragment><include file="parts/first.xml"/></fragment>',
        "model",
    )
    path = write_package(
        tmp_path, '<mujoco><include file="parts/first.xml"/></mujoco>', extra
    )
    with pytest.raises(ModelPackageError, match="cyclic include"):
        load_model_package(path)


def test_colliding_mesh_basenames_have_distinct_verified_vfs_keys(tmp_path):
    xml = '<mujoco><asset><mesh name="first" file="one/shared.obj"/><mesh name="second" file="two/shared.obj"/></asset></mujoco>'
    path = write_package(
        tmp_path,
        xml,
        {"one/shared.obj": (b"first", "mesh"), "two/shared.obj": (b"second", "mesh")},
    )
    prepared, assets = _prepare_xml(verify_model_package(path))
    assert len(assets) == 2 and set(assets.values()) == {b"first", b"second"}
    assert "one/shared.obj" not in prepared


@pytest.mark.parametrize(
    "tag,role,suffix",
    [
        ("mesh", "mesh", "obj"),
        ("hfield", "heightfield", "bin"),
        ("skin", "skin", "skn"),
        ("texture", "texture", "png"),
    ],
)
def test_compiler_resource_directories_and_implicit_names(tmp_path, tag, role, suffix):
    xml = f'<mujoco><compiler assetdir="resources"/><asset><{tag} file="sample.{suffix}"/></asset></mujoco>'
    path = write_package(
        tmp_path, xml, {f"resources/sample.{suffix}": (b"resource", role)}
    )
    prepared, assets = _prepare_xml(verify_model_package(path))
    assert len(assets) == 1 and list(assets.values()) == [b"resource"]
    assert 'name="sample"' in prepared


def test_undeclared_mesh_and_incorrect_resource_role(tmp_path):
    xml = '<mujoco><asset><mesh file="sample.obj"/></asset></mujoco>'
    path = write_package(tmp_path, xml)
    with pytest.raises(ModelPackageError, match="undeclared XML dependency"):
        _prepare_xml(verify_model_package(path))
    path = write_package(tmp_path, xml, {"sample.obj": (b"resource", "provenance")})
    with pytest.raises(ModelPackageError, match="asset role mismatch"):
        _prepare_xml(verify_model_package(path))


@pytest.mark.parametrize(
    "field,value", [("total_mass_kg", 0.3), ("nq", 2), ("timestep_s", 0.003)]
)
def test_compiled_parity_failures(tmp_path, engine, field, value):
    path = write_package(tmp_path, changes=lambda m: m["parity"].update({field: value}))
    with pytest.raises(ModelPackageError, match="parity mismatch"):
        load_model_package(path)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("joints", "range", [-0.5, 0.5]),
        ("joints", "name", "renamed"),
        ("actuators", "control_range", [-1.0, 1.0]),
        ("actuators", "force_range", None),
        ("actuators", "gear", [2.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        ("bodies", "name", "renamed"),
    ],
)
def test_joint_actuator_and_tree_parity_fail_closed(
    tmp_path, engine, section, field, value
):
    def change(manifest):
        manifest["parity"][section][0][field] = value
        if section == "joints" and field == "name":
            manifest["parity"]["actuators"][0]["joint"] = value
        if section == "bodies" and field == "name":
            manifest["parity"]["joints"][0]["body"] = value

    path = write_package(tmp_path, changes=change)
    with pytest.raises(ModelPackageError, match="parity mismatch"):
        load_model_package(path)


def test_tree_and_nonfinite_contract_rejected(tmp_path):
    path = write_package(tmp_path)
    manifest = json.loads(path.read_text())
    manifest["parity"]["bodies"][0]["parent"] = "arm"
    with pytest.raises(ValidationError, match="parent-first tree"):
        ModelPackage.model_validate(manifest)
    manifest["parity"]["bodies"][0]["parent"] = "world"
    manifest["parity"]["total_mass_kg"] = float("nan")
    with pytest.raises(ValidationError):
        ModelPackage.model_validate(manifest)


def test_urdf_native_import_with_explicit_compiler_defaults(tmp_path, engine):
    urdf = """<robot name="test"><mujoco><compiler fusestatic="false" strippath="false"/></mujoco>
<link name="base"/><link name="arm"><inertial><mass value="0.2"/><origin xyz="0 0 0"/>
<inertia ixx="0.01" iyy="0.01" izz="0.01" ixy="0" ixz="0" iyz="0"/></inertial></link>
<joint name="hinge" type="revolute"><parent link="base"/><child link="arm"/>
<axis xyz="0 0 1"/><limit lower="-1" upper="1" effort="2" velocity="5"/></joint></robot>"""

    def change(manifest):
        manifest["format"] = "urdf"
        manifest["parity"]["actuators"] = []
        manifest["parity"]["bodies"] = [
            {"name": "base", "parent": "world"},
            {"name": "arm", "parent": "base"},
        ]

    path = write_package(tmp_path, urdf, changes=change)
    loaded = load_model_package(path)
    assert loaded.model.nu == 0
    assert loaded.report["checks"]["body_tree"]


def test_microduck_mass_ranges_pose_replay_and_short_dynamics(engine):
    import numpy as np

    loaded = load_model_package(
        MICRODUCK, expected_manifest_sha256=MICRODUCK_MANIFEST_SHA256
    )
    model, manifest = loaded.model, loaded.package.manifest
    assert loaded.report["total_mass_kg"] == pytest.approx(0.73724318, abs=1e-8)
    assert (model.nq, model.nv, model.nu) == (21, 20, 14)
    assert all(loaded.report["checks"].values())
    data = engine.MjData(model)
    rng = np.random.default_rng(42)
    for _ in range(32):
        for i, joint in enumerate(manifest.parity.joints):
            if joint.type == "hinge":
                data.qpos[model.jnt_qposadr[i]] = rng.uniform(*joint.range)
        engine.mj_forward(model, data)
        assert np.isfinite(data.xpos).all() and np.isfinite(data.xquat).all()
        positions = data.xpos.copy()
        replay = engine.MjData(model)
        replay.qpos[:] = data.qpos
        engine.mj_forward(model, replay)
        np.testing.assert_array_equal(positions, replay.xpos)
    engine.mj_resetData(model, data)
    for _ in range(25):
        engine.mj_step(model, data)
    assert np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all()
    assert not any(w.number for w in data.warning)
    assert (
        inspect_model_package(MICRODUCK)["package_sha256"]
        == loaded.report["package_sha256"]
    )
