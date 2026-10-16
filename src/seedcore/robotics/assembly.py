"""Central World Robot Assembly contract and semantic validation.

Defines the versioned assembly schema (seedcore.assembly.v1), canonical digest rules,
and validation logic enforcing tree topology, unique port occupancy,
articulation vs. rigid mount separation, and electrical net consistency.
No HAL execution authority is granted by this authoring contract.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
import numpy as np

from seedcore.robotics.component_registry import (
    MAX_JSON_BYTES,
    REGISTRY,
    ROOT,
    load_catalog,
    parse_json,
    read_local,
    sha256,
)

ASSEMBLY_SCHEMA_VERSION = "seedcore.assembly.v1"
SCHEMA_REL_PATH = "schema/v1.sc-assembly.schema.json"


def assembly_schema(root: Path = REGISTRY) -> dict[str, Any]:
    """Load and validate the Central World assembly schema."""
    schema = parse_json(read_local(root, SCHEMA_REL_PATH))

    def local_refs(value: Any, *, root_node: bool = False) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "$id" and not root_node:
                    raise ValueError(
                        "nested schema IDs cannot redirect local references"
                    )
                if key == "$dynamicRef" or (
                    key == "$ref"
                    and (not isinstance(child, str) or not child.startswith("#/$defs/"))
                ):
                    raise ValueError(
                        "assembly schema cannot resolve external references"
                    )
                local_refs(child)
        elif isinstance(value, list):
            for child in value:
                local_refs(child)

    local_refs(schema, root_node=True)
    Draft202012Validator.check_schema(schema)
    return schema


def canonical_assembly_bytes(data: dict[str, Any]) -> bytes:
    """Return deterministic canonical JSON bytes (RFC 8785 style) for an assembly."""
    def _normalize(val: Any) -> Any:
        if isinstance(val, float):
            if not math.isfinite(val):
                raise ValueError(f"non-finite float in assembly: {val}")
            if val.is_integer():
                return int(val)
            return val
        elif isinstance(val, dict):
            return {k: _normalize(v) for k, v in val.items()}
        elif isinstance(val, list):
            return [_normalize(item) for item in val]
        return val

    normalized = _normalize(data)
    encoded = json.dumps(normalized, separators=(",", ":"), sort_keys=True, allow_nan=False)
    return encoded.encode("utf-8")


def compute_assembly_digest(data: dict[str, Any]) -> str:
    """Compute the SHA-256 digest of canonical assembly bytes."""
    return sha256(canonical_assembly_bytes(data))


def _quat_norm(q: list[float]) -> float:
    return math.sqrt(sum(v * v for v in q))


def _quat_mult(q1: list[float], q2: list[float]) -> list[float]:
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    return [
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    ]


def _quat_conjugate(q: list[float]) -> list[float]:
    return [q[0], -q[1], -q[2], -q[3]]


def _quat_rot_vec(q: list[float], v: list[float]) -> list[float]:
    qv = [0.0, v[0], v[1], v[2]]
    res = _quat_mult(_quat_mult(q, qv), _quat_conjugate(q))
    return [res[1], res[2], res[3]]


def mate_transform(parent_port: dict[str, Any], child_port: dict[str, Any]) -> dict[str, Any]:
    """Compute relative transform (child origin in parent frame) to mate two snap ports.

    Assumes port quaternions define local-to-part rotations.
    """
    p_p = parent_port["position_m"]
    q_p = parent_port["quaternion_wxyz"]
    p_c = child_port["position_m"]
    q_c = child_port["quaternion_wxyz"]

    q_c_inv = _quat_conjugate(q_c)
    # Relative rotation of child frame in parent frame
    q_rel = _quat_mult(q_p, q_c_inv)
    # Normalise
    norm = _quat_norm(q_rel)
    if norm > 0:
        q_rel = [v / norm for v in q_rel]

    # Child origin in parent frame: p_rel = p_p - rotate(q_rel, p_c)
    p_c_rot = _quat_rot_vec(q_rel, p_c)
    p_rel = [p_p[i] - p_c_rot[i] for i in range(3)]

    return {
        "position_m": [round(v, 8) for v in p_rel],
        "quaternion_wxyz": [round(v, 8) for v in q_rel],
    }


def validate_assembly(
    data: dict[str, Any],
    catalog: list[dict[str, Any]] | dict[str, dict[str, Any]] | Path | None = None,
    *,
    schema: dict[str, Any] | None = None,
    root: Path = REGISTRY,
) -> dict[str, Any]:
    """Validate structure, tree topology, ports, kinematics, and electrical nets.

    Rejects invalid candidates atomically via ValueError without mutating data.
    """
    raw_bytes = canonical_assembly_bytes(data)
    if len(raw_bytes) > MAX_JSON_BYTES * 2:
        raise ValueError("assembly JSON exceeds its size bound")

    compiled_schema = schema if schema is not None else assembly_schema(root)
    validator = Draft202012Validator(compiled_schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: str(list(e.path)))
    if errors:
        raise ValueError("assembly schema: " + errors[0].message)

    if data.get("schema_version") != ASSEMBLY_SCHEMA_VERSION:
        raise ValueError(f"unsupported schema version: {data.get('schema_version')}")

    # Build catalog map: part_id -> part_dict
    catalog_map: dict[str, dict[str, Any]] = {}
    if catalog is None or isinstance(catalog, Path):
        cat_list = load_catalog(catalog or root)
        catalog_map = {p["identity"]["part_id"]: p for p in cat_list}
    elif isinstance(catalog, list):
        catalog_map = {p["identity"]["part_id"]: p for p in catalog}
    elif isinstance(catalog, dict):
        catalog_map = catalog
    else:
        raise ValueError("invalid catalog specification")

    nodes = data["nodes"]
    nodes_map: dict[str, dict[str, Any]] = {}
    seen_nodes: set[str] = set()

    for node in nodes:
        node_id = node["node_id"]
        if node_id in seen_nodes:
            raise ValueError(f"duplicate node_id: '{node_id}'")
        seen_nodes.add(node_id)
        nodes_map[node_id] = node

        part_id = node["part_id"]
        if part_id not in catalog_map:
            raise ValueError(f"unknown part_id: '{part_id}' in node '{node_id}'")

        part = catalog_map[part_id]
        if node["part_version"] != part["identity"]["version"]:
            raise ValueError(
                f"part version mismatch for node '{node_id}': "
                f"expected '{part['identity']['version']}', got '{node['part_version']}'"
            )

        # Check part digest matches canonical part JSON
        expected_part_sha = sha256(canonical_assembly_bytes(part))
        if node["part_sha256"] != expected_part_sha:
            raise ValueError(
                f"part sha256 mismatch for node '{node_id}': "
                f"expected '{expected_part_sha}', got '{node['part_sha256']}'"
            )

    root_id = data["root_node_id"]
    if root_id not in nodes_map:
        raise ValueError(f"root_node_id '{root_id}' is not in nodes list")

    mech_tree = data["mechanical_tree"]
    num_nodes = len(nodes)
    if num_nodes > 1 and len(mech_tree) != num_nodes - 1:
        raise ValueError(
            f"mechanical tree must have exactly N-1 ({num_nodes - 1}) edges for {num_nodes} nodes, "
            f"got {len(mech_tree)}"
        )
    if num_nodes == 1 and len(mech_tree) != 0:
        raise ValueError(f"single-node assembly must have 0 mechanical edges, got {len(mech_tree)}")

    # Graph connectivity and tree topology
    parent_of: dict[str, str] = {}
    children_of: dict[str, list[str]] = {n: [] for n in nodes_map}
    occupied_ports: set[tuple[str, str]] = set()
    joint_ids: set[str] = set()

    for edge in mech_tree:
        edge_id = edge["edge_id"]
        p_node = edge["parent_node_id"]
        c_node = edge["child_node_id"]
        p_port = edge["parent_port_id"]
        c_port = edge["child_port_id"]
        conn_type = edge["connection_type"]

        if p_node not in nodes_map:
            raise ValueError(f"edge '{edge_id}': parent node '{p_node}' not in nodes")
        if c_node not in nodes_map:
            raise ValueError(f"edge '{edge_id}': child node '{c_node}' not in nodes")
        if p_node == c_node:
            raise ValueError(f"edge '{edge_id}': self-loop on node '{p_node}'")
        if c_node == root_id:
            raise ValueError(f"edge '{edge_id}': root node '{root_id}' cannot be a child")
        if c_node in parent_of:
            raise ValueError(
                f"edge '{edge_id}': node '{c_node}' has multiple parents: "
                f"'{parent_of[c_node]}' and '{p_node}'"
            )

        parent_of[c_node] = p_node
        children_of[p_node].append(c_node)

        # Port validation on parent and child parts
        parent_part = catalog_map[nodes_map[p_node]["part_id"]]
        child_part = catalog_map[nodes_map[c_node]["part_id"]]

        parent_ports = {p["port_id"]: p for p in parent_part["mechanical"]["snap_ports"]}
        child_ports = {p["port_id"]: p for p in child_part["mechanical"]["snap_ports"]}

        if p_port not in parent_ports:
            raise ValueError(
                f"edge '{edge_id}': parent port '{p_port}' not found on part '{parent_part['identity']['part_id']}'"
            )
        if c_port not in child_ports:
            raise ValueError(
                f"edge '{edge_id}': child port '{c_port}' not found on part '{child_part['identity']['part_id']}'"
            )

        # Port occupancy check: no port used more than once
        p_key = (p_node, p_port)
        c_key = (c_node, c_port)
        if p_key in occupied_ports:
            raise ValueError(f"duplicate occupied port: node '{p_node}' port '{p_port}'")
        if c_key in occupied_ports:
            raise ValueError(f"duplicate occupied port: node '{c_node}' port '{c_port}'")
        occupied_ports.add(p_key)
        occupied_ports.add(c_key)

        # Mount standard & gender compatibility
        p_spec = parent_ports[p_port]
        c_spec = child_ports[c_port]
        if p_spec["mount_standard"] != c_spec["mount_standard"]:
            raise ValueError(
                f"edge '{edge_id}': incompatible mount standards: "
                f"'{p_spec['mount_standard']}' vs '{c_spec['mount_standard']}'"
            )

        pg, cg = p_spec["gender"], c_spec["gender"]
        if (pg == "neutral" and cg != "neutral") or (cg == "neutral" and pg != "neutral"):
            raise ValueError(f"edge '{edge_id}': neutral port cannot mate with '{cg or pg}'")
        if pg == cg and pg in {"plug", "socket"}:
            raise ValueError(f"edge '{edge_id}': cannot mate two {pg} ports")

        # Transform check
        if "relative_transform" in edge and edge["relative_transform"] is not None:
            q = edge["relative_transform"]["quaternion_wxyz"]
            if not math.isclose(_quat_norm(q), 1.0, abs_tol=1e-5):
                raise ValueError(f"edge '{edge_id}': relative transform quaternion must be unit length")

        # Connection type vs joint model
        joint = edge.get("joint")
        if conn_type == "rigid_mount":
            if joint is not None:
                raise ValueError(f"edge '{edge_id}': rigid mount cannot declare a joint")
        elif conn_type == "articulated_joint":
            if joint is None:
                raise ValueError(f"edge '{edge_id}': articulated joint must declare joint details")
            j_id = joint["joint_id"]
            if j_id in joint_ids:
                raise ValueError(f"duplicate joint_id: '{j_id}'")
            joint_ids.add(j_id)

            axis = joint["axis"]
            axis_len = math.sqrt(sum(a * a for a in axis))
            if not math.isclose(axis_len, 1.0, abs_tol=1e-4):
                raise ValueError(f"joint '{j_id}': rotation axis must be a unit vector, got {axis}")

            limits = joint["limits_rad"]
            if limits["min_rad"] > limits["max_rad"]:
                raise ValueError(f"joint '{j_id}': min_rad exceeds max_rad")
            if joint["kind"] == "revolute" and limits["min_rad"] == limits["max_rad"]:
                raise ValueError(f"joint '{j_id}': revolute joint range must have positive width")

            rest_angle = joint["rest_angle_rad"]
            if not (limits["min_rad"] <= rest_angle <= limits["max_rad"]):
                raise ValueError(
                    f"joint '{j_id}': rest_angle_rad ({rest_angle}) outside limits "
                    f"[{limits['min_rad']}, {limits['max_rad']}]"
                )

            actuator_node_id = joint.get("actuator_node_id")
            if actuator_node_id is not None:
                if actuator_node_id not in nodes_map:
                    raise ValueError(
                        f"joint '{j_id}': actuator node '{actuator_node_id}' not found in nodes"
                    )
                actuator_part = catalog_map[nodes_map[actuator_node_id]["part_id"]]
                capabilities = actuator_part["hal_and_safety"]["capabilities"]
                if "actuator.joint_position" not in capabilities:
                    raise ValueError(
                        f"joint '{j_id}': actuator node '{actuator_node_id}' does not have "
                        f"'actuator.joint_position' capability"
                    )
                # Check limits do not exceed actuator's declared limits
                act_limits = (
                    actuator_part["hal_and_safety"].get("simulation_limits")
                    or actuator_part["hal_and_safety"].get("hard_limits")
                )
                if act_limits and act_limits.get("min_rad") is not None:
                    if limits["min_rad"] < act_limits["min_rad"] - 1e-6 or limits["max_rad"] > act_limits["max_rad"] + 1e-6:
                        raise ValueError(
                            f"joint '{j_id}' limits [{limits['min_rad']}, {limits['max_rad']}] exceed "
                            f"actuator capability limits [{act_limits['min_rad']}, {act_limits['max_rad']}]"
                        )

    # Reachability from root (no cycles, no disconnected nodes)
    visited = set()
    queue = [root_id]
    while queue:
        curr = queue.pop(0)
        visited.add(curr)
        for child in children_of[curr]:
            if child not in visited:
                queue.append(child)

    if len(visited) != num_nodes:
        unreachable = set(nodes_map.keys()) - visited
        raise ValueError(
            f"mechanical tree has disconnected or unreachable nodes: {sorted(unreachable)}"
        )

    # Electrical Net validation
    electrical_nets = data["electrical_nets"]
    seen_nets = set()

    for net in electrical_nets:
        net_id = net["net_id"]
        if net_id in seen_nets:
            raise ValueError(f"duplicate net_id: '{net_id}'")
        seen_nets.add(net_id)

        net_kind = net["kind"]
        controllers = 0

        for ep in net["endpoints"]:
            ep_node = ep["node_id"]
            ep_iface = ep["interface_id"]

            if ep_node not in nodes_map:
                raise ValueError(f"net '{net_id}': endpoint node '{ep_node}' not in nodes")

            ep_part = catalog_map[nodes_map[ep_node]["part_id"]]
            buses = {b["interface_id"]: b for b in ep_part["electrical"]["bus_interfaces"]}

            if ep_iface not in buses:
                raise ValueError(
                    f"net '{net_id}': interface '{ep_iface}' not found on node '{ep_node}' "
                    f"(part '{ep_part['identity']['part_id']}')"
                )

            bus_spec = buses[ep_iface]
            # Bus kind compatibility
            if net_kind in {"TTL_UART_BUS", "I2C", "PWM", "GPIO"}:
                if bus_spec["kind"] != net_kind:
                    raise ValueError(
                        f"net '{net_id}' of kind '{net_kind}' connected to incompatible "
                        f"interface '{ep_iface}' of kind '{bus_spec['kind']}'"
                    )

            if bus_spec.get("role") == "controller":
                controllers += 1

        if net_kind in {"TTL_UART_BUS", "I2C"} and controllers > 1:
            raise ValueError(
                f"net '{net_id}' has {controllers} controllers, bus allows at most one"
            )

    return data


def build_tabletop_starter_assembly(
    catalog: list[dict[str, Any]] | dict[str, dict[str, Any]] | None = None,
    root: Path = REGISTRY,
) -> dict[str, Any]:
    """Build the canonical golden starter tabletop robot assembly.

    Structure:
      base_0 (tabletop-base, root)
        -> bracket_0 (link-bracket, rigid_mount)
          -> servo_0 (sts3215-draft, rigid_mount)
            -> hat_0 (sensor-hat, articulated_joint: pitch)
              -> mcu_0 (esp32-s3-draft, rigid_mount)
      Electrical:
        TTL UART bus connecting mcu_0 (uart controller) to servo_0 (servo-bus peripheral).
    """
    if catalog is None or isinstance(catalog, (Path, str)):
        cat_list = load_catalog(root)
        cat_map = {p["identity"]["part_id"]: p for p in cat_list}
    elif isinstance(catalog, list):
        cat_map = {p["identity"]["part_id"]: p for p in catalog}
    else:
        cat_map = catalog

    def _part_sha(part_id: str) -> str:
        return sha256(canonical_assembly_bytes(cat_map[part_id]))

    base_part = cat_map["seedcore.tabletop-base"]
    bracket_part = cat_map["seedcore.link-bracket"]
    servo_part = cat_map["feetech.sts3215-draft"]
    hat_part = cat_map["seedcore.sensor-hat"]
    mcu_part = cat_map["espressif.esp32-s3-draft"]

    # Calculate port-mating transforms
    t_base_bracket = mate_transform(
        base_part["mechanical"]["snap_ports"][1],  # mount.top
        bracket_part["mechanical"]["snap_ports"][0],  # mount.bottom
    )
    t_bracket_servo = mate_transform(
        bracket_part["mechanical"]["snap_ports"][1],  # mount.top
        servo_part["mechanical"]["snap_ports"][0],  # mount.bottom
    )
    t_servo_hat = mate_transform(
        servo_part["mechanical"]["snap_ports"][1],  # mount.top
        hat_part["mechanical"]["snap_ports"][0],  # mount.bottom
    )
    t_hat_mcu = mate_transform(
        hat_part["mechanical"]["snap_ports"][1],  # mount.top
        mcu_part["mechanical"]["snap_ports"][0],  # mount.bottom
    )

    assembly = {
        "schema_version": ASSEMBLY_SCHEMA_VERSION,
        "identity": {
            "assembly_id": "tabletop.starter-arm-v1",
            "version": "0.1.0",
            "name": "SeedCore Tabletop Starter Arm - Golden Assembly",
            "status": "draft",
            "created_at": "2026-10-16T00:00:00Z",
            "notes": "Golden reference tabletop assembly for CW-A01 qualification and testing.",
        },
        "root_node_id": "base_0",
        "nodes": [
            {
                "node_id": "base_0",
                "part_id": "seedcore.tabletop-base",
                "part_version": "0.1.0",
                "part_sha256": _part_sha("seedcore.tabletop-base"),
                "role": "chassis",
                "display_name": "Tabletop Base",
            },
            {
                "node_id": "bracket_0",
                "part_id": "seedcore.link-bracket",
                "part_version": "0.1.0",
                "part_sha256": _part_sha("seedcore.link-bracket"),
                "role": "bracket",
                "display_name": "Link Bracket",
            },
            {
                "node_id": "servo_0",
                "part_id": "feetech.sts3215-draft",
                "part_version": "0.1.0",
                "part_sha256": _part_sha("feetech.sts3215-draft"),
                "role": "actuator",
                "display_name": "Shoulder Pitch Servo",
            },
            {
                "node_id": "hat_0",
                "part_id": "seedcore.sensor-hat",
                "part_version": "0.1.0",
                "part_sha256": _part_sha("seedcore.sensor-hat"),
                "role": "payload",
                "display_name": "Sensor Hat Link",
            },
            {
                "node_id": "mcu_0",
                "part_id": "espressif.esp32-s3-draft",
                "part_version": "0.1.0",
                "part_sha256": _part_sha("espressif.esp32-s3-draft"),
                "role": "mcu",
                "display_name": "ESP32-S3 Controller",
            },
        ],
        "mechanical_tree": [
            {
                "edge_id": "edge_base_bracket",
                "parent_node_id": "base_0",
                "parent_port_id": "mount.top",
                "child_node_id": "bracket_0",
                "child_port_id": "mount.bottom",
                "connection_type": "rigid_mount",
                "relative_transform": t_base_bracket,
            },
            {
                "edge_id": "edge_bracket_servo",
                "parent_node_id": "bracket_0",
                "parent_port_id": "mount.top",
                "child_node_id": "servo_0",
                "child_port_id": "mount.bottom",
                "connection_type": "rigid_mount",
                "relative_transform": t_bracket_servo,
            },
            {
                "edge_id": "edge_servo_hat",
                "parent_node_id": "servo_0",
                "parent_port_id": "mount.top",
                "child_node_id": "hat_0",
                "child_port_id": "mount.bottom",
                "connection_type": "articulated_joint",
                "relative_transform": t_servo_hat,
                "joint": {
                    "joint_id": "joint_shoulder_pitch",
                    "kind": "revolute",
                    "axis": [0.0, 1.0, 0.0],
                    "pivot_m": [0.0, 0.0, 0.0],
                    "actuator_node_id": "servo_0",
                    "actuator_channel": 1,
                    "rest_angle_rad": 0.0,
                    "limits_rad": {
                        "min_rad": -0.5,
                        "max_rad": 0.5,
                        "max_velocity_rad_s": 1.0,
                        "max_torque_nm": 0.2,
                    },
                },
            },
            {
                "edge_id": "edge_hat_mcu",
                "parent_node_id": "hat_0",
                "parent_port_id": "mount.top",
                "child_node_id": "mcu_0",
                "child_port_id": "mount.bottom",
                "connection_type": "rigid_mount",
                "relative_transform": t_hat_mcu,
            },
        ],
        "electrical_nets": [
            {
                "net_id": "net_servo_ttl",
                "kind": "TTL_UART_BUS",
                "nominal_voltage_v": 7.4,
                "endpoints": [
                    {
                        "node_id": "mcu_0",
                        "interface_id": "uart",
                    },
                    {
                        "node_id": "servo_0",
                        "interface_id": "servo-bus",
                    },
                ],
            }
        ],
        "metadata": {
            "notes": "Tabletop starter reference assembly satisfying CW-A01 contracts.",
            "generator": "SeedCore CW-A01 reference generator",
        },
    }

    return validate_assembly(assembly, cat_map, root=root)


def compute_node_world_transforms(
    assembly: dict[str, Any],
) -> dict[str, dict[str, list[float]]]:
    """Compute global world transform for each node assuming root node at origin."""
    root_id = assembly["root_node_id"]
    transforms: dict[str, dict[str, list[float]]] = {
        root_id: {
            "position_m": [0.0, 0.0, 0.0],
            "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
        }
    }

    edges_by_parent: dict[str, list[dict[str, Any]]] = {}
    for edge in assembly["mechanical_tree"]:
        edges_by_parent.setdefault(edge["parent_node_id"], []).append(edge)

    queue = [root_id]
    while queue:
        p_id = queue.pop(0)
        p_trans = transforms[p_id]
        p_pos = p_trans["position_m"]
        p_quat = p_trans["quaternion_wxyz"]

        for edge in edges_by_parent.get(p_id, []):
            c_id = edge["child_node_id"]
            rel = edge.get("relative_transform") or {
                "position_m": [0.0, 0.0, 0.0],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            }
            rel_pos = rel["position_m"]
            rel_quat = rel["quaternion_wxyz"]

            # c_quat = p_quat * rel_quat
            c_quat = _quat_mult(p_quat, rel_quat)
            # c_pos = p_pos + rotate(p_quat, rel_pos)
            rel_pos_rot = _quat_rot_vec(p_quat, rel_pos)
            c_pos = [p_pos[i] + rel_pos_rot[i] for i in range(3)]

            transforms[c_id] = {
                "position_m": [round(v, 8) for v in c_pos],
                "quaternion_wxyz": [round(v, 8) for v in c_quat],
            }
            queue.append(c_id)

    return transforms
