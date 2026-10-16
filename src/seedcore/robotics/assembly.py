"""Assembly v2: bounded offline authoring with exact artifact provenance.

The v1 draft is historical. No schema, catalog, output declaration or digest
in this module grants HAL execution authority.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
import rfc8785

from seedcore.robotics.component_registry import (
    MAX_JSON_BYTES,
    REGISTRY,
    load_catalog,
    parse_json,
    read_local,
    sha256,
    part_schema,
    validate_part,
)

ASSEMBLY_SCHEMA_VERSION = "seedcore.assembly.v2"
CANONICAL_PROFILE = "seedcore.jcs-safe-integers.v1"
SCHEMA_REL_PATH = "schema/v2.sc-assembly.schema.json"
MAX_ASSEMBLY_BYTES = MAX_JSON_BYTES * 2
SAFE_INTEGER = 2**53 - 1


@dataclass(frozen=True)
class AssemblyCatalog:
    """Exact immutable component bytes; synthetic fixtures are explicitly labeled."""

    artifacts: tuple[bytes, ...]
    root: Path
    provenance: str


def load_assembly_catalog(root: Path = REGISTRY) -> AssemblyCatalog:
    load_catalog(root)  # Verify frozen index, parts, meshes and references.
    index = parse_json(read_local(root, "catalog.json"))
    artifacts = []
    for entry in index["parts"]:
        raw = read_local(root, entry["path"])
        if sha256(raw) != entry["sha256"]:
            raise ValueError("part digest changed while loading assembly catalog")
        part = parse_json(raw)
        if (part["identity"]["part_id"], part["identity"]["version"]) != (
            entry["part_id"],
            entry["version"],
        ):
            raise ValueError("catalog identity/version mismatch")
        artifacts.append(raw)
    return AssemblyCatalog(tuple(artifacts), root, "verified_local_catalog")


def _catalog_parts(catalog: AssemblyCatalog | Path | None, root: Path):
    if catalog is None or isinstance(catalog, Path):
        catalog = load_assembly_catalog(catalog or root)
    if not isinstance(catalog, AssemblyCatalog):
        raise ValueError(
            "catalog requires exact byte artifacts; use load_assembly_catalog"
        )
    if catalog.provenance not in {"verified_local_catalog", "synthetic_fixture"}:
        raise ValueError("unknown catalog provenance")
    if (
        not isinstance(catalog.artifacts, tuple)
        or not 1 <= len(catalog.artifacts) <= 256
    ):
        raise ValueError("invalid catalog artifact count")
    schema = part_schema(catalog.root)
    parts, pins = {}, {}
    index = None
    if catalog.provenance == "verified_local_catalog":
        load_catalog(catalog.root)
        index = {
            entry["part_id"]: entry
            for entry in parse_json(read_local(catalog.root, "catalog.json"))["parts"]
        }
    for raw in catalog.artifacts:
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_JSON_BYTES:
            raise ValueError("invalid component byte artifact")
        part = validate_part(parse_json(raw), catalog.root, schema=schema)
        key = part["identity"]["part_id"]
        if index is not None and (
            key not in index
            or index[key]["sha256"] != sha256(raw)
            or index[key]["version"] != part["identity"]["version"]
        ):
            raise ValueError("artifact differs from verified catalog entry")
        if key in parts:
            raise ValueError("duplicate catalog identity")
        parts[key], pins[key] = part, sha256(raw)
    return parts, pins


def assembly_schema(root: Path = REGISTRY) -> dict[str, Any]:
    schema = parse_json(read_local(root, SCHEMA_REL_PATH))

    def local_refs(value, *, top=False):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "$id" and not top:
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

    local_refs(schema, top=True)
    Draft202012Validator.check_schema(schema)
    return schema


def canonical_assembly_bytes(data: Any) -> bytes:
    """RFC 8785 plus bounded JSON and safe integral-number domain in both languages."""
    budget = [0]

    def check(value, depth=0):
        budget[0] += 1
        if depth > 32 or budget[0] > 50000:
            raise ValueError("assembly JSON nesting/node bound exceeded")
        if value is None or isinstance(value, bool):
            return
        if isinstance(value, str):
            try:
                encoded = value.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError("invalid Unicode in assembly") from exc
            if len(encoded) > MAX_ASSEMBLY_BYTES:
                raise ValueError("assembly string exceeds size bound")
        elif type(value) in (int, float):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("non-finite float in assembly")
            if (isinstance(value, int) or value.is_integer()) and abs(
                value
            ) > SAFE_INTEGER:
                raise ValueError("unsafe integer in assembly")
        elif type(value) is list:
            for item in value:
                check(item, depth + 1)
        elif type(value) is dict:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError("assembly JSON keys must be strings")
                check(key, depth + 1)
                check(item, depth + 1)
        else:
            raise ValueError("assembly contains a non-JSON value")

    check(data)
    result = rfc8785.dumps(data)
    if len(result) > MAX_ASSEMBLY_BYTES:
        raise ValueError("assembly JSON exceeds its size bound")
    return result


def compute_assembly_digest(data: dict[str, Any]) -> str:
    return sha256(canonical_assembly_bytes(data))


def _quat_mult(a, b):
    w, x, y, z = a
    v, i, j, k = b
    return [
        w * v - x * i - y * j - z * k,
        w * i + x * v + y * k - z * j,
        w * j - x * k + y * v + z * i,
        w * k + x * j - y * i + z * v,
    ]


def _quat_conjugate(q):
    return [q[0], -q[1], -q[2], -q[3]]


def _quat_rot_vec(q, v):
    return _quat_mult(_quat_mult(q, [0, *v]), _quat_conjugate(q))[1:]


def _unit(values, label):
    if not math.isclose(sum(v * v for v in values), 1.0, rel_tol=0, abs_tol=1e-8):
        raise ValueError(f"{label} must be a unit vector/quaternion")


def _near(a, b, *, quaternion=False):
    distance = max(abs(x - y) for x, y in zip(a, b))
    if quaternion:
        distance = min(distance, max(abs(x + y) for x, y in zip(a, b)))
    return distance <= 1e-8


def mate_transform(parent_port, child_port):
    """T_parent_port * Rx(pi) * inverse(T_child_port); port +Z normals oppose."""
    qp, qc = parent_port["quaternion_wxyz"], child_port["quaternion_wxyz"]
    _unit(qp, "parent port quaternion")
    _unit(qc, "child port quaternion")
    q = _quat_mult(_quat_mult(qp, [0, 1, 0, 0]), _quat_conjugate(qc))
    offset = _quat_rot_vec(q, child_port["position_m"])
    return {
        "position_m": [v - offset[i] for i, v in enumerate(parent_port["position_m"])],
        "quaternion_wxyz": q,
    }


def validate_assembly_structure(data, *, root=REGISTRY):
    canonical_assembly_bytes(data)
    errors = list(Draft202012Validator(assembly_schema(root)).iter_errors(data))
    if errors:
        raise ValueError("assembly schema: " + errors[0].message)
    nodes = {n["node_id"] for n in data["nodes"]}
    if len(nodes) != len(data["nodes"]):
        raise ValueError("duplicate node_id")
    root_id = data["root_node_id"]
    if root_id not in nodes:
        raise ValueError("root_node_id not in nodes list")
    if len(data["mechanical_tree"]) != len(nodes) - 1:
        raise ValueError("mechanical tree must have exactly N-1 edges")
    children = {n: [] for n in nodes}
    parents, edges, joints, ports, channels = set(), set(), set(), set(), set()
    for edge in data["mechanical_tree"]:
        p, c = edge["parent_node_id"], edge["child_node_id"]
        if edge["edge_id"] in edges:
            raise ValueError("duplicate edge_id")
        edges.add(edge["edge_id"])
        if p not in nodes or c not in nodes:
            raise ValueError("mechanical endpoint not in nodes")
        if p == c:
            raise ValueError("self-loop on node")
        if c == root_id:
            raise ValueError("root node cannot be a child")
        if c in parents:
            raise ValueError("node has multiple parents")
        parents.add(c)
        children[p].append(c)
        for key in [(p, edge["parent_port_id"]), (c, edge["child_port_id"])]:
            if key in ports:
                raise ValueError("duplicate occupied port")
            ports.add(key)
        _unit(
            edge["relative_transform"]["quaternion_wxyz"],
            "relative transform quaternion",
        )
        if edge["connection_type"] == "articulated_joint":
            joint = edge["joint"]
            if joint["joint_id"] in joints:
                raise ValueError("duplicate joint_id")
            joints.add(joint["joint_id"])
            _unit(joint["axis"], "rotation axis")
            limits = joint["limits_rad"]
            if limits["min_rad"] >= limits["max_rad"]:
                raise ValueError(
                    "joint range must have positive width; min_rad exceeds max_rad"
                )
            if not limits["min_rad"] <= joint["rest_angle_rad"] <= limits["max_rad"]:
                raise ValueError("rest_angle_rad outside limits")
            key = (joint["actuator_node_id"], joint["actuator_channel"])
            if key in channels:
                raise ValueError("actuator channel assigned to multiple joints")
            channels.add(key)
            if joint["actuator_node_id"] != p:
                raise ValueError("actuator output must belong to parent node")
    visited, queue = set(), [root_id]
    while queue:
        node = queue.pop()
        if node in visited:
            raise ValueError("mechanical cycle")
        visited.add(node)
        queue.extend(children[node])
    if visited != nodes:
        raise ValueError("mechanical tree has disconnected or unreachable nodes")
    outputs, output_ports = {}, set()
    for output in data["actuator_outputs"]:
        key = (output["node_id"], output["channel"])
        port = (output["node_id"], output["port_id"])
        if output["node_id"] not in nodes or key in outputs or port in output_ports:
            raise ValueError("invalid or duplicate actuator output")
        _unit(output["axis"], "output axis")
        outputs[key] = output
        output_ports.add(port)
    for edge in data["mechanical_tree"]:
        if edge["connection_type"] == "articulated_joint":
            joint = edge["joint"]
            output = outputs.get((joint["actuator_node_id"], joint["actuator_channel"]))
            if output is None or output["port_id"] != edge["parent_port_id"]:
                raise ValueError("unknown actuator output/channel for joint port")
            if not _near(output["axis"], joint["axis"]) or not _near(
                output["pivot_m"], joint["pivot_m"]
            ):
                raise ValueError("joint frame differs from declared actuator output")
        elif (edge["parent_node_id"], edge["parent_port_id"]) in output_ports:
            raise ValueError("rotating output requires articulated_joint")
        if (edge["child_node_id"], edge["child_port_id"]) in output_ports:
            raise ValueError("rotating output cannot be used as housing attachment")
    seen_nets = set()
    for net in data["electrical_nets"]:
        if net["net_id"] in seen_nets:
            raise ValueError("duplicate net_id")
        seen_nets.add(net["net_id"])
        for ep in net["endpoints"]:
            if ep["node_id"] not in nodes:
                raise ValueError("electrical endpoint not in nodes")
    return copy.deepcopy(data)


def validate_assembly(
    data, catalog: AssemblyCatalog | Path | None = None, *, root=REGISTRY
):
    data = validate_assembly_structure(data, root=root)
    parts, pins = _catalog_parts(catalog, root)
    nodes = {n["node_id"]: n for n in data["nodes"]}
    for node in data["nodes"]:
        part_id = node["part_id"]
        if part_id not in parts:
            raise ValueError("unknown part_id")
        part = parts[part_id]
        if node["part_version"] != part["identity"]["version"]:
            raise ValueError("part version mismatch")
        if node["part_sha256"] != pins[part_id]:
            raise ValueError("part sha256 mismatch (exact catalog bytes required)")

    def part_for(node_id):
        return parts[nodes[node_id]["part_id"]]

    def port_for(node_id, port_id):
        ports = {p["port_id"]: p for p in part_for(node_id)["mechanical"]["snap_ports"]}
        if port_id not in ports:
            raise ValueError(f"port '{port_id}' not found")
        return ports[port_id]

    for output in data["actuator_outputs"]:
        part = part_for(output["node_id"])
        if "actuator.joint_position" not in part["hal_and_safety"]["capabilities"]:
            raise ValueError("output node lacks actuator.joint_position capability")
        if part["mechanical"]["basis"] != "simulation_proxy":
            raise ValueError("v2 supports declared proxy outputs only")
        port = port_for(output["node_id"], output["port_id"])
        if not _near(output["pivot_m"], port["position_m"]):
            raise ValueError("output pivot must match declared proxy port")

    for edge in data["mechanical_tree"]:
        pp = port_for(edge["parent_node_id"], edge["parent_port_id"])
        cp = port_for(edge["child_node_id"], edge["child_port_id"])
        if pp["mount_standard"] != cp["mount_standard"]:
            raise ValueError("incompatible mount standards")
        if pp["mount_standard"] != "seedcore.proxy_mount_v1":
            raise ValueError("unsupported mating standard")
        pg, cg = pp["gender"], cp["gender"]
        if not ((pg == cg == "neutral") or {pg, cg} == {"plug", "socket"}):
            raise ValueError("incompatible port genders")
        expected, actual = mate_transform(pp, cp), edge["relative_transform"]
        if not _near(expected["position_m"], actual["position_m"]) or not _near(
            expected["quaternion_wxyz"], actual["quaternion_wxyz"], quaternion=True
        ):
            raise ValueError("relative transform does not mate declared ports")
        if edge["connection_type"] == "articulated_joint":
            joint = edge["joint"]
            bounds = part_for(joint["actuator_node_id"])["hal_and_safety"][
                "simulation_limits"
            ]
            requested = joint["limits_rad"]
            if bounds is None or any(v is None for v in bounds.values()):
                raise ValueError("unknown simulation actuator limits")
            if (
                requested["min_rad"] < bounds["min_rad"]
                or requested["max_rad"] > bounds["max_rad"]
            ):
                raise ValueError("joint limits exceed actuator capability limits")
            if (
                requested["max_velocity_rad_s"] > bounds["max_rad_s"]
                or requested["max_torque_nm"] > bounds["max_torque_nm"]
            ):
                raise ValueError(
                    "joint velocity/torque exceed actuator capability limits"
                )

    net_kinds = {
        "TTL_UART_BUS": "TTL_UART_BUS",
        "I2C": "I2C",
        "PWM": "PWM",
        "power": "POWER_RAIL",
        "ground": "POWER_RAIL",
    }
    used = {}
    for net in data["electrical_nets"]:
        controllers, endpoints = 0, set()
        for ep in net["endpoints"]:
            key = (ep["node_id"], ep["interface_id"])
            if key in endpoints:
                raise ValueError("duplicate electrical endpoint")
            endpoints.add(key)
            buses = {
                b["interface_id"]: b
                for b in part_for(ep["node_id"])["electrical"]["bus_interfaces"]
            }
            if ep["interface_id"] not in buses:
                raise ValueError(f"interface '{ep['interface_id']}' not found")
            bus = buses[ep["interface_id"]]
            if bus["kind"] != net_kinds[net["kind"]]:
                raise ValueError("incompatible interface for electrical net kind")
            roles = (
                {"source", "sink"}
                if net["kind"] in {"power", "ground"}
                else {"controller", "peripheral"}
            )
            if bus["role"] not in roles:
                raise ValueError("incompatible electrical role")
            controllers += bus["role"] == "controller"
            selected = set(ep.get("pins", []))
            if not selected.issubset(bus["pins"]):
                raise ValueError("undeclared electrical pin")
            if net["kind"] in {"power", "ground"} and not selected:
                raise ValueError("power/ground endpoint requires declared pins")
            previous = used.setdefault(key, set())
            resources = selected or {"*"}
            if previous and (
                "*" in previous
                or "*" in resources
                or previous & resources
                or net["kind"] not in {"power", "ground"}
            ):
                raise ValueError("electrical interface/pin reused across nets")
            previous.update(resources)
        if net["kind"] in {"TTL_UART_BUS", "I2C", "PWM"} and controllers > 1:
            raise ValueError("bus allows at most one controller")
    return data


def build_tabletop_starter_assembly(
    catalog: AssemblyCatalog | Path | None = None,
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
    cat_map, part_pins = _catalog_parts(catalog, root)

    def _part_sha(part_id: str) -> str:
        return part_pins[part_id]

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
        "canonicalization": CANONICAL_PROFILE,
        "runtime_profile": "offline_proxy_no_actuation",
        "mating_convention": "opposed_z_rx_pi",
        "actuator_outputs": [
            {
                "node_id": "servo_0",
                "port_id": "mount.top",
                "channel": 1,
                "basis": "simulation_proxy",
                "axis": [0.0, 1.0, 0.0],
                "pivot_m": [0.0, 0.0, 0.02],
            }
        ],
        "identity": {
            "assembly_id": "tabletop.starter-arm-v1",
            "version": "0.2.0",
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
                    "frame": "parent_part",
                    "axis": [0.0, 1.0, 0.0],
                    "pivot_m": [0.0, 0.0, 0.02],
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
                "nominal_voltage_v": None,
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

    return validate_assembly(assembly, catalog, root=root)


def compute_node_world_transforms(assembly):
    """Return validated structural rest poses, root at identity; no dynamic stepping."""
    assembly = validate_assembly_structure(assembly)
    root = assembly["root_node_id"]
    transforms = {
        root: {"position_m": [0.0, 0.0, 0.0], "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0]}
    }
    children = {}
    for edge in assembly["mechanical_tree"]:
        children.setdefault(edge["parent_node_id"], []).append(edge)
    queue = [root]
    while queue:
        parent = queue.pop()
        current = transforms[parent]
        for edge in children.get(parent, []):
            relative = edge["relative_transform"]
            rotated = _quat_rot_vec(current["quaternion_wxyz"], relative["position_m"])
            transforms[edge["child_node_id"]] = {
                "position_m": [current["position_m"][i] + rotated[i] for i in range(3)],
                "quaternion_wxyz": _quat_mult(
                    current["quaternion_wxyz"], relative["quaternion_wxyz"]
                ),
            }
            queue.append(edge["child_node_id"])
    return transforms
