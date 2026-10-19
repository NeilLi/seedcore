"""CW-ASM-02 local authoring validation; no hardware or admission surface."""
import json

import pytest
from fastapi.testclient import TestClient
from seedcore.robotics.assembly import compute_assembly_digest
from seedcore.robotics.component_registry import REGISTRY, parse_json, read_local, sha256
from seedcore.robotics.mini_studio_api import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def starter():
    return parse_json(read_local(REGISTRY, "assemblies/tabletop-starter.sc-assembly.json", 262144))


def test_starter_and_catalog_bytes_are_exact_and_scoped(client):
    response = client.get("/api/starter")
    assert response.content == read_local(REGISTRY, "assemblies/tabletop-starter.sc-assembly.json", 262144)
    result = client.post("/api/assembly/validate", json=starter())
    assert result.status_code == 200
    data = result.json()
    assert data["scope"] == "offline_proxy_authoring" and data["physical_acceptance"] is False
    assert data["assembly_digest"] == "2550d184c44a064c6ad6a2245a08f430f257c40ca8f3627e73eeb3fedd452acb"
    nodes = {node["part_id"]: node for node in starter()["nodes"]}
    for entry in data["part_documents"]:
        assert sha256(entry["raw_json"].encode()) == nodes[entry["part_id"]]["part_sha256"]
        visual = json.loads(entry["raw_json"])["mechanical"]["visual_mesh"]
        mesh = client.get("/" + visual["uri"])
        assert mesh.status_code == 200 and sha256(mesh.content) == visual["sha256"]
    assert set(data["transforms"]) == {node["node_id"] for node in starter()["nodes"]}
    assert "unsafe-eval" not in response.headers["Content-Security-Policy"]
    assert response.headers["Cross-Origin-Embedder-Policy"] == "require-corp"


@pytest.mark.parametrize("mutation", ["part_pin", "pose", "limit", "port", "v1", "token"])
def test_invalid_candidate_rejected_without_changing_starter(client, mutation):
    data = starter()
    if mutation == "part_pin": data["nodes"][0]["part_sha256"] = "0" * 64
    elif mutation == "pose": data["mechanical_tree"][0]["relative_transform"]["position_m"][0] = 1
    elif mutation == "limit":
        next(edge for edge in data["mechanical_tree"] if "joint" in edge)["joint"]["limits_rad"]["max_rad"] = 100
    elif mutation == "port": data["mechanical_tree"][0]["parent_port_id"] = "imaginary"
    elif mutation == "v1": data["schema_version"] = "seedcore.assembly.v1"
    else: data["execution_token"] = {"allow": True}
    result = client.post("/api/assembly/validate", json=data)
    assert result.status_code == 422
    assert compute_assembly_digest(client.get("/api/starter").json()) == compute_assembly_digest(starter())


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"x":{"a":1,"\\u0061":2}}', '1e999', '{bad'])
def test_raw_duplicate_and_malformed_json_rejected(client, raw):
    assert client.post("/api/assembly/validate", content=raw, headers={"Content-Type": "application/json"}).status_code == 422


def test_bounded_same_origin_only(client):
    assert client.post("/api/assembly/validate", content=b" " * 262145, headers={"Content-Type": "application/json"}).status_code == 413
    assert client.post("/api/assembly/validate", content="{}").status_code == 415
    assert client.post("/api/assembly/validate", json=starter(), headers={"Origin": "https://elsewhere.example"}).status_code == 403
    assert client.get("/api/starter", headers={"Host": "elsewhere.example"}).status_code == 403
    assert client.post("/api/assembly/validate", json=starter(), headers={"Origin": "http://testserver"}).status_code == 200


def test_no_deployment_or_arbitrary_asset_routes(client):
    for url in ["/api/admission", "/api/execute", "/api/flash", "/assets/missing.glb", "/catalog.json"]:
        assert client.get(url).status_code == 404


def test_placement_palette_keeps_exact_catalog_and_part_bytes(client):
    result = client.get("/api/placement-catalog")
    assert result.status_code == 200
    payload = result.json()
    assert payload["scope"] == "offline_proxy_authoring"
    assert payload["physical_acceptance"] is False
    assert payload["catalog_raw_json"].encode() == read_local(REGISTRY, "catalog.json")
    assert sha256(payload["catalog_raw_json"].encode()) == payload["catalog_sha256"]
    pins = {part["part_id"]: part for part in json.loads(payload["catalog_raw_json"])["parts"]}
    assert len(payload["part_documents"]) == len(pins) == 12
    for item in payload["part_documents"]:
        assert sha256(item["raw_json"].encode()) == pins[item["part_id"]]["sha256"]
        assert json.loads(item["raw_json"])["hal_and_safety"]["execution_authority"] == "none"
