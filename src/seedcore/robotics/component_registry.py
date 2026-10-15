"""Read-only component authoring validation. No I/O beyond contained local assets.

A valid catalog part is never a HAL driver, qualified device or execution grant.
All v1 components deliberately have no runtime binding or execution authority.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import struct

from jsonschema import Draft202012Validator
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "packages/component-registry"
MAX_JSON_BYTES = 128 * 1024
MAX_MESH_BYTES = 1024 * 1024


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_local(root: Path, relative: str, limit: int = MAX_JSON_BYTES) -> bytes:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative:
        raise ValueError("asset path must be local and contained")
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("symlinked catalog root is unsupported")
    root = root.resolve(strict=True)
    candidate = root / path
    if any(p.is_symlink() for p in (candidate, *candidate.parents)):
        raise ValueError("symlinked catalog assets are unsupported")
    if not candidate.resolve(strict=True).is_relative_to(root):
        raise ValueError("catalog asset escaped its root")
    if not candidate.is_file() or not 0 < candidate.stat().st_size <= limit:
        raise ValueError("catalog asset missing/empty/oversized")
    data = candidate.read_bytes()
    if len(data) > limit:
        raise ValueError("catalog asset exceeded its bound")
    return data


def parse_json(data: bytes):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"non-finite JSON number: {value}")

    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            invalid(value)
        return parsed

    return json.loads(
        data, object_pairs_hook=pairs, parse_constant=invalid, parse_float=number
    )


def part_schema(root: Path = REGISTRY):
    schema = parse_json(read_local(root, "schema/v1.sc-part.schema.json"))

    def local_refs(value, *, root_node=False):
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
                        "component schema cannot resolve external references"
                    )
                local_refs(child)
        elif isinstance(value, list):
            for child in value:
                local_refs(child)

    local_refs(schema, root_node=True)
    Draft202012Validator.check_schema(schema)
    return schema


def proxy_glb(size_m: list[float]) -> bytes:
    """Original, deterministic glTF 2.0 box mesh; part Z-up -> glTF Y-up."""
    x, y, z = (v / 2 for v in size_m)
    part_vertices = [
        (a * x, b * y, c * z) for c in (-1, 1) for b in (-1, 1) for a in (-1, 1)
    ]
    vertices = [(a, c, -b) for a, b, c in part_vertices]
    indices = [
        0,
        2,
        3,
        0,
        3,
        1,
        4,
        5,
        7,
        4,
        7,
        6,
        0,
        1,
        5,
        0,
        5,
        4,
        2,
        6,
        7,
        2,
        7,
        3,
        0,
        4,
        6,
        0,
        6,
        2,
        1,
        3,
        7,
        1,
        7,
        5,
    ]
    binary = struct.pack(
        "<24f", *(v for point in vertices for v in point)
    ) + struct.pack("<36H", *indices)
    model = {
        "asset": {
            "version": "2.0",
            "generator": "SeedCore original illustrative box proxy",
        },
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 96, "target": 34962},
            {"buffer": 0, "byteOffset": 96, "byteLength": 72, "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 8,
                "type": "VEC3",
                "min": [-x, -z, -y],
                "max": [x, z, y],
            },
            {"bufferView": 1, "componentType": 5123, "count": 36, "type": "SCALAR"},
        ],
    }
    encoded = json.dumps(model, separators=(",", ":"), sort_keys=True).encode("ascii")
    encoded += b" " * (-len(encoded) % 4)
    total = 12 + 8 + len(encoded) + 8 + len(binary)
    return (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(encoded), 0x4E4F534A)
        + encoded
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


def _pair(minimum, maximum, label):
    if (minimum is None) != (maximum is None):
        raise ValueError(f"{label}: both bounds or neither are required")
    if minimum is not None and minimum > maximum:
        raise ValueError(f"{label}: reversed bounds")


def validate_part(data: dict, root: Path = REGISTRY, *, schema=None):
    """Validate structure, physical consistency and an immutable local visual asset."""
    encoded = json.dumps(data, allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("part JSON exceeds its size bound")
    validator = Draft202012Validator(
        schema if schema is not None else part_schema(root)
    )
    errors = sorted(validator.iter_errors(data), key=lambda e: str(list(e.path)))
    if errors:
        raise ValueError("part schema: " + errors[0].message)
    identity, mechanical, electrical, safety = (
        data[k] for k in ("identity", "mechanical", "electrical", "hal_and_safety")
    )
    if (identity["cost_basis"] == "unknown") != (identity["bom_cost_usd"] is None):
        raise ValueError("cost basis/value mismatch")
    if identity["cost_basis"] == "supplier_quote" and not any(
        s["quoted_on"] for s in identity["supplier_skus"]
    ):
        raise ValueError("a supplier quote requires dated SKU provenance")
    ports = mechanical["snap_ports"]
    if len({p["port_id"] for p in ports}) != len(ports):
        raise ValueError("duplicate snap port")
    for port in ports:
        if not math.isclose(
            sum(v * v for v in port["quaternion_wxyz"]), 1.0, abs_tol=1e-6
        ):
            raise ValueError("snap quaternion must be normalized wxyz")
        if (
            mechanical["basis"] == "simulation_proxy"
            and port["qualification"] != "illustrative"
        ):
            raise ValueError("proxy mount cannot claim drawing qualification")
    inertia = mechanical["inertia_kg_m2"]
    tensor = [
        [inertia["ixx"], inertia["ixy"], inertia["ixz"]],
        [inertia["ixy"], inertia["iyy"], inertia["iyz"]],
        [inertia["ixz"], inertia["iyz"], inertia["izz"]],
    ]
    moments = np.linalg.eigvalsh(tensor)
    if moments[0] <= 0 or moments[2] > moments[0] + moments[1] + max(
        1e-15, moments[2] * 1e-8
    ):
        raise ValueError(
            "inertia must be positive definite with principal-moment triangle inequalities"
        )
    _pair(electrical["min_v"], electrical["max_v"], "operating voltage")
    _pair(electrical["continuous_ma"], electrical["peak_ma"], "current")
    ratings = [
        electrical[k]
        for k in ("min_v", "max_v", "continuous_ma", "peak_ma", "output_capacity_ma")
    ]
    if electrical["rating_basis"] in {"unknown", "not_applicable"} and any(
        v is not None for v in ratings
    ):
        raise ValueError("unknown/not-applicable electrical ratings must remain null")
    if electrical["rating_basis"] == "documented" and any(
        v is None for v in ratings[:4]
    ):
        raise ValueError("documented electrical ratings are incomplete")
    buses = electrical["bus_interfaces"]
    if electrical["rating_basis"] == "not_applicable" and buses:
        raise ValueError("passive part cannot expose electrical interfaces")
    if len({b["interface_id"] for b in buses}) != len(buses):
        raise ValueError("duplicate electrical interface")
    for bus in buses:
        _pair(bus["logic_min_v"], bus["logic_max_v"], "logic voltage")
        if bus["kind"] != "I2C" and bus["i2c_address"] is not None:
            raise ValueError("I2C address on a different bus")
    joint = "actuator.joint_position" in safety["capabilities"]
    for key in ("hard_limits", "simulation_limits"):
        limits = safety[key]
        if limits is None:
            if key == "simulation_limits" and joint:
                raise ValueError("joint preview requires explicit simulation limits")
            continue
        _pair(limits["min_rad"], limits["max_rad"], key)
        if limits["min_rad"] is not None and limits["min_rad"] == limits["max_rad"]:
            raise ValueError("joint range must have positive width")
        if not joint and any(v is not None for v in limits.values()):
            raise ValueError("non-joint part cannot declare joint limits")
        if key == "simulation_limits" and any(v is None for v in limits.values()):
            raise ValueError("simulation joint limits must be complete")
    visual = mechanical["visual_mesh"]
    mesh = read_local(root, visual["uri"], MAX_MESH_BYTES)
    if sha256(mesh) != visual["sha256"]:
        raise ValueError("visual mesh digest mismatch")
    if visual["origin"] == "seedcore_box_proxy":
        if mechanical["basis"] != "simulation_proxy" or mesh != proxy_glb(
            mechanical["collision"]["size_m"]
        ):
            raise ValueError(
                "proxy mesh/frame/dimensions differ from collision geometry"
            )
        x, y, z = mechanical["collision"]["size_m"]
        mass = mechanical["mass_kg"]
        expected_tensor = np.diag(
            [
                mass * (y * y + z * z) / 12,
                mass * (x * x + z * z) / 12,
                mass * (x * x + y * y) / 12,
            ]
        )
        if mechanical["center_of_mass_m"] != [0, 0, 0] or not np.allclose(
            tensor, expected_tensor, rtol=1e-10, atol=0
        ):
            raise ValueError(
                "box proxy mass/COM/inertia must describe the same authored geometry"
            )
    return data


def load_catalog(root: Path = REGISTRY):
    """Load the frozen draft catalog. Does not follow remote refs or load code."""
    index = parse_json(read_local(root, "catalog.json"))
    if (
        set(index)
        != {"schema_version", "status", "schema_sha256", "parts", "references"}
        or index["schema_version"] != "seedcore.component-catalog.v1"
        or index["status"] != "draft_only"
    ):
        raise ValueError("invalid catalog index")
    schema_bytes = read_local(root, "schema/v1.sc-part.schema.json")
    if index["schema_sha256"] != sha256(schema_bytes):
        raise ValueError("schema pin mismatch")
    schema = part_schema(root)
    if not isinstance(index["parts"], list) or not 1 <= len(index["parts"]) <= 256:
        raise ValueError("catalog part count outside bound")
    result, seen = [], set()
    for entry in index["parts"]:
        if set(entry) != {"part_id", "version", "path", "sha256"}:
            raise ValueError("invalid catalog entry")
        raw = read_local(root, entry["path"])
        if sha256(raw) != entry["sha256"]:
            raise ValueError("part digest mismatch")
        data = validate_part(parse_json(raw), root, schema=schema)
        if (data["identity"]["part_id"], data["identity"]["version"]) != (
            entry["part_id"],
            entry["version"],
        ):
            raise ValueError("catalog identity/version mismatch")
        if entry["part_id"] in seen:
            raise ValueError("duplicate catalog identity")
        seen.add(entry["part_id"])
        result.append(data)
    if not isinstance(index["references"], list) or len(index["references"]) > 32:
        raise ValueError("reference count outside bound")
    for entry in index["references"]:
        if (
            set(entry) != {"path", "sha256"}
            or sha256(read_local(root, entry["path"])) != entry["sha256"]
        ):
            raise ValueError("reference digest/shape mismatch")
    return result
