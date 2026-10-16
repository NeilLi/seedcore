"""CW-ASM-01 conformance, exact provenance, mating and atomic import regressions."""

from __future__ import annotations

import copy
import json
import math
import shutil
from pathlib import Path

from jsonschema import Draft202012Validator
import numpy as np
import pytest

from seedcore.robotics.assembly import (
    ASSEMBLY_SCHEMA_VERSION,
    AssemblyCatalog,
    assembly_schema,
    build_tabletop_starter_assembly,
    canonical_assembly_bytes,
    compute_assembly_digest,
    compute_node_world_transforms,
    load_assembly_catalog,
    mate_transform,
    validate_assembly,
    validate_assembly_structure,
)
from seedcore.robotics.component_registry import (
    REGISTRY,
    parse_json,
    read_local,
    sha256,
)

FIXTURES = Path(__file__).parent / "fixtures/assembly-v2"
CASES = json.loads((FIXTURES / "conformance.json").read_text())["cases"]
VECTORS = json.loads((FIXTURES / "canonical.json").read_text())["vectors"]
GOLDEN = REGISTRY / "assemblies/tabletop-starter.sc-assembly.json"


def patched(source, operations):
    result = copy.deepcopy(source)
    for operation in operations:
        target = result
        for key in operation["path"][:-1]:
            target = target[key]
        key = operation["path"][-1]
        if operation["op"] == "remove":
            if isinstance(target, list):
                target.pop(key)
            else:
                del target[key]
        elif isinstance(target, list) and key == len(target):
            target.append(copy.deepcopy(operation["value"]))
        else:
            target[key] = copy.deepcopy(operation["value"])
    return result


@pytest.fixture(scope="module")
def catalog():
    return load_assembly_catalog()


@pytest.fixture
def starter():
    return parse_json(GOLDEN.read_bytes())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_shared_structural_and_semantic_conformance(starter, catalog, case):
    candidate = patched(starter, case["patch"])
    before = copy.deepcopy(candidate)
    retained_revision = copy.deepcopy(starter)
    if "schema_valid" in case:
        assert (
            Draft202012Validator(assembly_schema()).is_valid(candidate)
            is case["schema_valid"]
        )
    if case["structural_valid"]:
        assert validate_assembly_structure(candidate) == candidate
    else:
        with pytest.raises(ValueError):
            validate_assembly_structure(candidate)
    if case["semantic_valid"]:
        assert validate_assembly(candidate, catalog) == candidate
    else:
        with pytest.raises(ValueError):
            validate_assembly(candidate, catalog)
    assert candidate == before
    assert starter == retained_revision


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v["name"])
def test_independent_canonical_vectors(vector):
    if vector.get("reject"):
        with pytest.raises(ValueError):
            canonical_assembly_bytes(vector["input"])
    else:
        assert canonical_assembly_bytes(vector["input"]) == vector["expected"].encode()


@pytest.mark.parametrize(
    "value",
    [math.nan, math.inf, -math.inf, 10**400, {"x": object()}, {1: "not a string"}],
)
def test_reject_non_json_numbers_and_types(value):
    with pytest.raises(ValueError):
        canonical_assembly_bytes(value)


def test_reject_nesting_and_size_bounds():
    value = []
    for _ in range(34):
        value = [value]
    for bad in [value, "x" * 262145, [0] * 50001]:
        with pytest.raises(ValueError):
            canonical_assembly_bytes(bad)


def test_golden_round_trip_byte_pins_and_new_digest(starter, catalog):
    assert ASSEMBLY_SCHEMA_VERSION == "seedcore.assembly.v2"
    assert build_tabletop_starter_assembly(catalog) == starter
    assert (
        validate_assembly(parse_json(canonical_assembly_bytes(starter)), catalog)
        == starter
    )
    index = parse_json(read_local(REGISTRY, "catalog.json"))
    pins = {p["part_id"]: p["sha256"] for p in index["parts"]}
    assert all(
        node["part_sha256"] == pins[node["part_id"]] for node in starter["nodes"]
    )
    assert (
        compute_assembly_digest(starter)
        == "2550d184c44a064c6ad6a2245a08f430f257c40ca8f3627e73eeb3fedd452acb"
    )


def test_validation_returns_detached_candidate(starter, catalog):
    accepted = validate_assembly(starter, catalog)
    accepted["nodes"][0]["display_name"] = "changed copy"
    assert starter["nodes"][0]["display_name"] == "Tabletop Base"


def test_catalog_requires_actual_artifact_bytes(starter, catalog):
    parsed = [parse_json(raw) for raw in catalog.artifacts]
    with pytest.raises(ValueError, match="exact byte artifacts"):
        validate_assembly(starter, parsed)
    with pytest.raises(ValueError, match="verified catalog entry"):
        validate_assembly(
            starter,
            AssemblyCatalog(
                tuple(raw + b" " for raw in catalog.artifacts),
                REGISTRY,
                "verified_local_catalog",
            ),
        )


def test_whitespace_edit_breaks_existing_artifact_pin(tmp_path, starter):
    registry = tmp_path / "registry"
    shutil.copytree(REGISTRY, registry)
    index = parse_json(read_local(registry, "catalog.json"))
    entry = next(p for p in index["parts"] if p["part_id"] == "seedcore.tabletop-base")
    part_path = registry / entry["path"]
    part_path.write_bytes(part_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="part digest mismatch"):
        load_assembly_catalog(registry)
    # Even a newly pinned catalog cannot retroactively change the old assembly pin.
    entry["sha256"] = sha256(part_path.read_bytes())
    (registry / "catalog.json").write_text(json.dumps(index))
    with pytest.raises(ValueError, match="part sha256 mismatch"):
        validate_assembly(starter, load_assembly_catalog(registry))


def test_corrected_numeric_rest_geometry(starter):
    poses = compute_node_world_transforms(starter)
    expected = {
        "base_0": 0,
        "bracket_0": 0.011,
        "servo_0": 0.036,
        "hat_0": 0.060,
        "mcu_0": 0.068,
    }
    for node, z in expected.items():
        np.testing.assert_allclose(
            poses[node]["position_m"], [0, 0, z], atol=1e-12, rtol=0
        )
        np.testing.assert_allclose(
            poses[node]["quaternion_wxyz"], [1, 0, 0, 0], atol=1e-12, rtol=0
        )
    assert poses["bracket_0"]["position_m"][2] - 0.005 == pytest.approx(0.006)


def test_rotated_port_mating_and_nonorigin_parent_pose(starter):
    parent = {
        "position_m": [1, 2, 3],
        "quaternion_wxyz": [math.sqrt(0.5), 0, 0, math.sqrt(0.5)],
    }
    child = {"position_m": [0.2, 0, 0], "quaternion_wxyz": [0, 1, 0, 0]}
    relative = mate_transform(parent, child)
    np.testing.assert_allclose(relative["position_m"], [1, 1.8, 3], atol=1e-12)
    np.testing.assert_allclose(
        relative["quaternion_wxyz"], parent["quaternion_wxyz"], atol=1e-12
    )
    # World composition is tested independently from the port-mate helper.
    first = starter["mechanical_tree"][0]["relative_transform"]
    first["position_m"] = [1, 2, 3]
    first["quaternion_wxyz"] = [math.sqrt(0.5), 0, 0, math.sqrt(0.5)]
    second = starter["mechanical_tree"][1]["relative_transform"]
    second["position_m"] = [0.1, 0, 0]
    world = compute_node_world_transforms(starter)["servo_0"]
    np.testing.assert_allclose(world["position_m"], [1, 2.1, 3], atol=1e-12)


def test_geometry_helper_rejects_disconnected_cycle(starter):
    cycle = next(c for c in CASES if c["name"] == "disconnected cycle")
    with pytest.raises(ValueError, match="disconnected"):
        compute_node_world_transforms(patched(starter, cycle["patch"]))


def test_channel_cannot_drive_two_joints(starter):
    edge = starter["mechanical_tree"][3]
    edge.update(
        parent_node_id="servo_0",
        parent_port_id="another.output",
        connection_type="articulated_joint",
    )
    edge["joint"] = copy.deepcopy(starter["mechanical_tree"][2]["joint"])
    edge["joint"]["joint_id"] = "second_joint"
    with pytest.raises(ValueError, match="assigned to multiple joints"):
        validate_assembly_structure(starter)


def synthetic(catalog, change):
    parts = [parse_json(raw) for raw in catalog.artifacts]
    for part in parts:
        change(part)
    return AssemblyCatalog(
        tuple(json.dumps(p).encode() for p in parts), REGISTRY, "synthetic_fixture"
    )


def with_pins(starter, catalog):
    pins = {
        parse_json(raw)["identity"]["part_id"]: sha256(raw) for raw in catalog.artifacts
    }
    for node in starter["nodes"]:
        node["part_sha256"] = pins[node["part_id"]]
    return starter


def test_synthetic_catalog_is_explicit_and_unknown_actuator_bounds_reject(
    starter, catalog
):
    def change(part):
        if part["identity"]["part_id"] == "feetech.sts3215-draft":
            part["hal_and_safety"]["simulation_limits"]["max_torque_nm"] = None

    changed = synthetic(catalog, change)
    with pytest.raises(ValueError, match="simulation joint limits must be complete"):
        validate_assembly(with_pins(starter, changed), changed)


def test_multi_controller_bus_rejects(starter, catalog):
    def change(part):
        if part["identity"]["part_id"] == "feetech.sts3215-draft":
            part["electrical"]["bus_interfaces"][0]["role"] = "controller"

    changed = synthetic(catalog, change)
    with pytest.raises(ValueError, match="at most one controller"):
        validate_assembly(with_pins(starter, changed), changed)


def test_power_ground_net_pin_roles_and_separation(starter, catalog):
    def change(part):
        interfaces = part["electrical"]["bus_interfaces"]
        if part["identity"]["part_id"] in {
            "feetech.sts3215-draft",
            "espressif.esp32-s3-draft",
        }:
            interfaces.append(
                {
                    "interface_id": "power-rail",
                    "kind": "POWER_RAIL",
                    "role": "source"
                    if part["identity"]["category"] == "mcu"
                    else "sink",
                    "protocol": None,
                    "logic_min_v": None,
                    "logic_max_v": None,
                    "i2c_address": None,
                    "pins": ["VCC", "GND"],
                }
            )

    changed = synthetic(catalog, change)
    with_pins(starter, changed)
    starter["electrical_nets"] = [
        {
            "net_id": kind + "_rail",
            "kind": kind,
            "endpoints": [
                {"node_id": node, "interface_id": "power-rail", "pins": [pin]}
                for node in ["mcu_0", "servo_0"]
            ],
        }
        for kind, pin in [("power", "VCC"), ("ground", "GND")]
    ]
    assert validate_assembly(starter, changed)
    for net in starter["electrical_nets"]:
        for ep in net["endpoints"]:
            ep["pins"] = ["VCC"]
    with pytest.raises(ValueError, match="reused across nets"):
        validate_assembly(starter, changed)


@pytest.mark.parametrize(
    "fault", ["mount_standard", "neutral_socket", "plug_plug", "plug_socket"]
)
def test_explicit_mount_mating_compatibility(starter, catalog, fault):
    def change(part):
        if part["identity"]["part_id"] == "seedcore.tabletop-base" and fault in {
            "plug_plug",
            "plug_socket",
        }:
            part["mechanical"]["snap_ports"][1]["gender"] = "plug"
        if part["identity"]["part_id"] == "seedcore.link-bracket":
            port = part["mechanical"]["snap_ports"][0]
            if fault == "mount_standard":
                port["mount_standard"] = "unsupported.mount"
            elif fault == "plug_plug":
                port["gender"] = "plug"
            else:
                port["gender"] = "socket"

    changed = synthetic(catalog, change)
    with_pins(starter, changed)
    if fault == "plug_socket":
        assert validate_assembly(starter, changed)
    else:
        with pytest.raises(
            ValueError, match="incompatible mount standards|incompatible port genders"
        ):
            validate_assembly(starter, changed)
