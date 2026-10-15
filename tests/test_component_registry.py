"""Component consistency, provenance and read-only catalog boundary checks."""

from __future__ import annotations

import copy
import json
import shutil
import struct

from fastapi.testclient import TestClient
import numpy as np
import pytest

from seedcore.robotics.component_catalog_api import create_app
from seedcore.robotics.component_registry import (
    REGISTRY,
    ROOT,
    load_catalog,
    parse_json,
    part_schema,
    read_local,
    sha256,
    validate_part,
)


@pytest.fixture
def registry(tmp_path):
    target = tmp_path / "registry"
    shutil.copytree(REGISTRY, target)
    return target


@pytest.fixture
def servo():
    return next(
        copy.deepcopy(p)
        for p in load_catalog()
        if p["identity"]["part_id"] == "feetech.sts3215-draft"
    )


def test_catalog_covers_twelve_drafts_without_claiming_hardware_authority():
    parts = load_catalog()
    assert len(parts) == 12
    assert {p["identity"]["category"] for p in parts} == {
        "mcu",
        "actuator",
        "sensor",
        "power",
        "chassis",
    }
    assert all(p["hal_and_safety"]["runtime_binding"] is None for p in parts)
    assert all(p["hal_and_safety"]["execution_authority"] == "none" for p in parts)
    assert all(p["identity"]["bom_cost_usd"] is None for p in parts)


def test_real_glb_vertices_match_part_frame_dimensions_and_mount_faces():
    for part in load_catalog():
        mechanical = part["mechanical"]
        raw = read_local(REGISTRY, mechanical["visual_mesh"]["uri"])
        magic, version, size = struct.unpack_from("<III", raw)
        assert magic == 0x46546C67 and version == 2 and size == len(raw)
        json_size, kind = struct.unpack_from("<II", raw, 12)
        assert kind == 0x4E4F534A
        metadata = json.loads(raw[20 : 20 + json_size])
        assert metadata["buffers"] == [{"byteLength": 168}]
        vertices = np.array(
            struct.unpack_from("<24f", raw, 20 + json_size + 8)
        ).reshape(8, 3)
        part_vertices = vertices[:, [0, 2, 1]] * [1, -1, 1]
        np.testing.assert_allclose(
            np.ptp(part_vertices, axis=0),
            mechanical["collision"]["size_m"],
            atol=1e-8,
            rtol=0,
        )
        for port in mechanical["snap_ports"]:
            assert (
                abs(port["position_m"][2]) == mechanical["collision"]["size_m"][2] / 2
            )
        # The inertia is about COM and uses the same authored geometry, not mesh units in mm.
        x, y, z = mechanical["collision"]["size_m"]
        mass = mechanical["mass_kg"]
        np.testing.assert_allclose(
            [mechanical["inertia_kg_m2"][k] for k in ["ixx", "iyy", "izz"]],
            [
                mass * (y * y + z * z) / 12,
                mass * (x * x + z * z) / 12,
                mass * (x * x + y * y) / 12,
            ],
            rtol=1e-12,
        )


@pytest.mark.parametrize(
    "fault",
    [
        "unknown_field",
        "bad_quaternion",
        "duplicate_port",
        "nonpositive_inertia",
        "triangle_inertia",
        "inertia_units",
        "nan",
        "fake_rating",
        "reversed_voltage",
        "bad_current",
        "fake_quote",
        "zero_range",
        "runtime_binding",
        "authority",
        "uri_escape",
        "remote_mesh",
    ],
)
def test_reject_invalid_component_semantics(servo, fault):
    m, e, h = servo["mechanical"], servo["electrical"], servo["hal_and_safety"]
    if fault == "unknown_field":
        m["unreviewed"] = True
    elif fault == "bad_quaternion":
        m["snap_ports"][0]["quaternion_wxyz"] = [0.0, 0.0, 0.0, 0.0]
    elif fault == "duplicate_port":
        m["snap_ports"][1]["port_id"] = m["snap_ports"][0]["port_id"]
    elif fault == "nonpositive_inertia":
        m["inertia_kg_m2"]["ixy"] = 1.0
    elif fault == "triangle_inertia":
        m["inertia_kg_m2"]["ixx"] = 1.0
    elif fault == "inertia_units":
        m["inertia_kg_m2"] = {
            key: value * 1e6 for key, value in m["inertia_kg_m2"].items()
        }
    elif fault == "nan":
        m["mass_kg"] = float("nan")
    elif fault == "fake_rating":
        e.update(min_v=5.0, max_v=6.0)
    elif fault == "reversed_voltage":
        e.update(
            rating_basis="documented",
            min_v=6.0,
            max_v=5.0,
            continuous_ma=1.0,
            peak_ma=2.0,
        )
    elif fault == "bad_current":
        e.update(
            rating_basis="documented",
            min_v=5.0,
            max_v=6.0,
            continuous_ma=3.0,
            peak_ma=2.0,
        )
    elif fault == "fake_quote":
        servo["identity"].update(cost_basis="supplier_quote", bom_cost_usd=12.0)
    elif fault == "zero_range":
        h["simulation_limits"].update(min_rad=0.0, max_rad=0.0)
    elif fault == "runtime_binding":
        h["runtime_binding"] = "seedcore.hal.physical"
    elif fault == "authority":
        h["execution_authority"] = "MOVE"
    elif fault == "uri_escape":
        m["visual_mesh"]["uri"] = "assets/../../secret.glb"
    else:
        m["visual_mesh"]["uri"] = "https://example.test/mesh.glb"
    with pytest.raises(ValueError):
        validate_part(servo)


@pytest.mark.parametrize("fault", ["part", "mesh", "schema", "reference", "symlink"])
def test_tampered_catalog_cannot_load(registry, fault):
    index = parse_json(read_local(registry, "catalog.json"))
    part = index["parts"][0]
    record = parse_json(read_local(registry, part["path"]))
    files = {
        "part": part["path"],
        "mesh": record["mechanical"]["visual_mesh"]["uri"],
        "schema": "schema/v1.sc-part.schema.json",
        "reference": index["references"][0]["path"],
    }
    if fault == "symlink":
        path = registry / record["mechanical"]["visual_mesh"]["uri"]
        target = path.with_suffix(".original")
        path.rename(target)
        path.symlink_to(target)
    else:
        with (registry / files[fault]).open("ab") as f:
            f.write(b" ")
    with pytest.raises(ValueError):
        load_catalog(registry)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"v":NaN}', b'{"v":1e999}'])
def test_reject_ambiguous_or_nonfinite_json(raw):
    with pytest.raises(ValueError):
        parse_json(raw)


def test_schema_never_fetches_remote_references(registry):
    path = registry / "schema/v1.sc-part.schema.json"
    schema = json.loads(path.read_bytes())
    schema["$defs"]["id"] = {"$ref": "https://example.test/remote-schema"}
    path.write_text(json.dumps(schema))
    with pytest.raises(ValueError, match="external references"):
        part_schema(registry)


def test_microduck_reference_preserves_existing_model_package():
    ref = parse_json(read_local(REGISTRY, "references/microduck-0.1.0.json"))
    assert ref["catalog_assembly"] is None
    assert ref["kind"] == "imported_native_model"
    assert (
        sha256(read_local(ROOT, ref["package_manifest"]))
        == ref["package_manifest_sha256"]
    )


def test_viewer_is_read_only_isolated_and_serves_only_pinned_assets():
    with TestClient(create_app()) as client:
        response = client.get("/api/catalog")
        assert response.status_code == 200
        data = response.json()
        assert data["scope"] == "authoring_only" and len(data["parts"]) == 12
        mesh = data["parts"][0]["mechanical"]["visual_mesh"]
        asset = client.get("/" + mesh["uri"])
        assert sha256(asset.content) == mesh["sha256"]
        assert (
            client.post("/api/catalog", json={"enable_motion": True}).status_code == 405
        )
        assert client.get("/api/flash").status_code == 404
        assert client.get("/assets/unknown.glb").status_code == 404
        assert client.get("/", headers={"Host": "external.test"}).status_code == 403
        page = client.get("/")
        assert page.status_code == 200
        assert page.headers["Cross-Origin-Opener-Policy"] == "same-origin"
        assert page.headers["Cross-Origin-Embedder-Policy"] == "require-corp"
        assert "script-src 'self'" in page.headers["Content-Security-Policy"]
        assert "No hardware connected" in page.text
