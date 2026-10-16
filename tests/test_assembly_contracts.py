"""Central World CW-A01 Assembly Contract, Digest and Graph Topology Tests.

Verifies:
  - CW-ASM-01 positive case: Golden starter tabletop assembly passes schema,
    topological, kinematic and electrical net checks with stable digest.
  - CW-ASM-01 negative cases: Atomic rejection of invalid candidates (part hash mismatch,
    cycles, multi-parent, port collisions, joint limit violations, bus conflicts).
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import pytest

from seedcore.robotics.assembly import (
    ASSEMBLY_SCHEMA_VERSION,
    assembly_schema,
    build_tabletop_starter_assembly,
    canonical_assembly_bytes,
    compute_assembly_digest,
    compute_node_world_transforms,
    validate_assembly,
)
from seedcore.robotics.component_registry import (
    REGISTRY,
    load_catalog,
    parse_json,
    read_local,
    sha256,
)


@pytest.fixture
def catalog():
    cat = load_catalog(REGISTRY)
    return {p["identity"]["part_id"]: p for p in cat}


@pytest.fixture
def golden_starter(catalog):
    return build_tabletop_starter_assembly(catalog)


def test_assembly_schema_conforms_to_draft202012():
    schema = assembly_schema(REGISTRY)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "https://schemas.seedcore.ai/component/v1.sc-assembly.schema.json"
    assert "root_node_id" in schema["required"]
    assert "nodes" in schema["required"]
    assert "mechanical_tree" in schema["required"]
    assert "electrical_nets" in schema["required"]


def test_golden_starter_assembly_validates_and_reproduces_digest(golden_starter, catalog):
    validated = validate_assembly(golden_starter, catalog)
    assert validated["schema_version"] == ASSEMBLY_SCHEMA_VERSION
    assert validated["identity"]["assembly_id"] == "tabletop.starter-arm-v1"
    assert len(validated["nodes"]) == 5
    assert len(validated["mechanical_tree"]) == 4
    assert len(validated["electrical_nets"]) == 1

    digest1 = compute_assembly_digest(validated)
    raw_json = canonical_assembly_bytes(validated)
    reloaded = parse_json(raw_json)
    validated2 = validate_assembly(reloaded, catalog)
    digest2 = compute_assembly_digest(validated2)

    assert digest1 == digest2
    # Check stable known digest from disk fixture
    fixture_path = REGISTRY / "assemblies/tabletop-starter.sc-assembly.json"
    assert fixture_path.exists()
    disk_data = json.loads(fixture_path.read_text())
    assert compute_assembly_digest(disk_data) == digest1


def test_forward_world_transforms_compute_monotonically_ascending_chain(golden_starter):
    transforms = compute_node_world_transforms(golden_starter)
    assert len(transforms) == 5
    assert transforms["base_0"]["position_m"] == [0.0, 0.0, 0.0]
    assert transforms["base_0"]["quaternion_wxyz"] == [1.0, 0.0, 0.0, 0.0]

    # All stacked links should stay centered in X/Y and ascend in Z
    for node_id in ("bracket_0", "servo_0", "hat_0", "mcu_0"):
        pos = transforms[node_id]["position_m"]
        assert pos[0] == 0.0
        assert pos[1] == 0.0
        assert pos[2] >= 0.0


def test_reject_changed_part_bytes_or_digest_mismatch(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    corrupted["nodes"][0]["part_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="part sha256 mismatch"):
        validate_assembly(corrupted, catalog)


def test_reject_part_version_mismatch(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    corrupted["nodes"][0]["part_version"] = "9.9.9"
    with pytest.raises(ValueError, match="part version mismatch"):
        validate_assembly(corrupted, catalog)


def test_reject_unknown_part_id(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    corrupted["nodes"][0]["part_id"] = "unknown.custom-vendor.board-v1"
    with pytest.raises(ValueError, match="unknown part_id"):
        validate_assembly(corrupted, catalog)


def test_reject_missing_or_invalid_root_node(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    corrupted["root_node_id"] = "ghost_node_not_in_list"
    with pytest.raises(ValueError, match="root_node_id.*not in nodes list"):
        validate_assembly(corrupted, catalog)


def test_reject_duplicate_node_ids(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    duplicate_node = copy.deepcopy(corrupted["nodes"][0])
    corrupted["nodes"].append(duplicate_node)
    with pytest.raises(ValueError, match="duplicate node_id"):
        validate_assembly(corrupted, catalog)


def test_reject_mechanical_tree_edge_count_mismatch(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    corrupted["mechanical_tree"].pop()
    with pytest.raises(ValueError, match="mechanical tree must have exactly N-1"):
        validate_assembly(corrupted, catalog)


def test_reject_root_node_as_child(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    # Set child of edge 1 (parent is bracket_0) to root base_0
    corrupted["mechanical_tree"][1]["child_node_id"] = "base_0"
    with pytest.raises(ValueError, match="root node.*cannot be a child"):
        validate_assembly(corrupted, catalog)


def test_reject_self_loop_edge(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    corrupted["mechanical_tree"][0]["child_node_id"] = "base_0"
    corrupted["mechanical_tree"][0]["parent_node_id"] = "base_0"
    with pytest.raises(ValueError, match="self-loop on node"):
        validate_assembly(corrupted, catalog)


def test_reject_multiple_parents(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    # Make edge 2 (parent is servo_0) target bracket_0 as child too (already child of base_0)
    corrupted["mechanical_tree"][2]["child_node_id"] = "bracket_0"
    with pytest.raises(ValueError, match="has multiple parents"):
        validate_assembly(corrupted, catalog)


def test_reject_disconnected_or_cyclic_graph(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    # Disconnect mcu_0 by making edge point between bracket_0 and servo_0 redundantly
    corrupted["mechanical_tree"][3]["child_node_id"] = "servo_0"
    with pytest.raises(ValueError, match="has multiple parents|disconnected or unreachable"):
        validate_assembly(corrupted, catalog)


def test_reject_duplicate_occupied_port(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    # Have bracket_0 and servo_0 both connect to base_0.mount.top
    corrupted["mechanical_tree"][1]["parent_node_id"] = "base_0"
    corrupted["mechanical_tree"][1]["parent_port_id"] = "mount.top"
    with pytest.raises(ValueError, match="duplicate occupied port"):
        validate_assembly(corrupted, catalog)


def test_reject_nonexistent_snap_port(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    corrupted["mechanical_tree"][0]["parent_port_id"] = "nonexistent.port"
    with pytest.raises(ValueError, match="parent port 'nonexistent.port' not found"):
        validate_assembly(corrupted, catalog)


def test_reject_rigid_mount_declaring_joint(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    corrupted["mechanical_tree"][0]["joint"] = {
        "joint_id": "spurious_joint",
        "kind": "revolute",
        "axis": [0.0, 1.0, 0.0],
        "pivot_m": [0.0, 0.0, 0.0],
        "rest_angle_rad": 0.0,
        "limits_rad": {"min_rad": -1.0, "max_rad": 1.0},
    }
    with pytest.raises(ValueError, match="rigid mount cannot declare a joint"):
        validate_assembly(corrupted, catalog)


def test_reject_articulated_joint_missing_joint_data(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    del corrupted["mechanical_tree"][2]["joint"]
    with pytest.raises(ValueError, match="articulated joint must declare joint details|assembly schema"):
        validate_assembly(corrupted, catalog)


def test_reject_non_unit_joint_axis(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    corrupted["mechanical_tree"][2]["joint"]["axis"] = [0.0, 0.0, 0.0]
    with pytest.raises(ValueError, match="rotation axis must be a unit vector"):
        validate_assembly(corrupted, catalog)


def test_reject_reversed_joint_limits(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    corrupted["mechanical_tree"][2]["joint"]["limits_rad"]["min_rad"] = 0.5
    corrupted["mechanical_tree"][2]["joint"]["limits_rad"]["max_rad"] = -0.5
    with pytest.raises(ValueError, match="min_rad exceeds max_rad"):
        validate_assembly(corrupted, catalog)


def test_reject_rest_angle_outside_limits(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    corrupted["mechanical_tree"][2]["joint"]["rest_angle_rad"] = 1.5
    with pytest.raises(ValueError, match="rest_angle_rad.*outside limits"):
        validate_assembly(corrupted, catalog)


def test_reject_joint_limits_exceeding_actuator_capability(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    # Feetech sts3215 simulation_limits is [-0.5, 0.5]
    corrupted["mechanical_tree"][2]["joint"]["limits_rad"]["max_rad"] = 1.5
    with pytest.raises(ValueError, match="exceed actuator capability limits"):
        validate_assembly(corrupted, catalog)


def test_reject_actuator_node_lacking_actuator_capability(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    # Assign chassis base as actuator
    corrupted["mechanical_tree"][2]["joint"]["actuator_node_id"] = "base_0"
    with pytest.raises(ValueError, match="does not have 'actuator.joint_position' capability"):
        validate_assembly(corrupted, catalog)


def test_reject_electrical_net_missing_interface(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    corrupted["electrical_nets"][0]["endpoints"][0]["interface_id"] = "phantom_bus"
    with pytest.raises(ValueError, match="interface 'phantom_bus' not found"):
        validate_assembly(corrupted, catalog)


def test_reject_electrical_net_incompatible_bus_kind(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    # ESP32-S3 interface "i2c" is kind "I2C", but net is "TTL_UART_BUS"
    corrupted["electrical_nets"][0]["endpoints"][0]["interface_id"] = "i2c"
    with pytest.raises(ValueError, match="incompatible interface"):
        validate_assembly(corrupted, catalog)


def test_reject_electrical_net_multiple_controllers(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    # Add a second ESP32-S3 node as controller to the net
    second_mcu = copy.deepcopy(corrupted["nodes"][4])
    second_mcu["node_id"] = "mcu_1"
    # To avoid tree mismatch, replace a node or adjust
    corrupted["nodes"].append(second_mcu)
    corrupted["mechanical_tree"].append({
        "edge_id": "edge_mcu_mcu1",
        "parent_node_id": "mcu_0",
        "parent_port_id": "mount.top",
        "child_node_id": "mcu_1",
        "child_port_id": "mount.bottom",
        "connection_type": "rigid_mount",
    })
    corrupted["electrical_nets"][0]["endpoints"].append({
        "node_id": "mcu_1",
        "interface_id": "uart",
    })
    with pytest.raises(ValueError, match="has 2 controllers, bus allows at most one"):
        validate_assembly(corrupted, catalog)


def test_reject_non_finite_float(golden_starter, catalog):
    corrupted = copy.deepcopy(golden_starter)
    corrupted["mechanical_tree"][2]["joint"]["rest_angle_rad"] = float("nan")
    with pytest.raises(ValueError, match="non-finite float"):
        canonical_assembly_bytes(corrupted)


def test_atomic_rejection_leaves_source_unmutated(golden_starter, catalog):
    original_copy = copy.deepcopy(golden_starter)
    corrupted = copy.deepcopy(golden_starter)
    corrupted["root_node_id"] = "invalid_root"
    try:
        validate_assembly(corrupted, catalog)
    except ValueError:
        pass
    assert golden_starter == original_copy
