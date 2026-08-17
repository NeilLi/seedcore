from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from seedcore.api.routers.discovery_router import (
    CITY_RUNTIME_PROFILE_ENV,
    haversine_distance,
    router,
)
from seedcore.models.city_foundation import CityFeatureV0
from seedcore.services.city_foundation_service import (
    REFERENCE_DISTRICT_FIXTURE_PATH,
    load_reference_district,
    public_discovery_features,
)


def _make_client(monkeypatch: pytest.MonkeyPatch, *, enabled: bool = True) -> TestClient:
    if enabled:
        monkeypatch.setenv(CITY_RUNTIME_PROFILE_ENV, "bootstrap_sim")
    else:
        monkeypatch.delenv(CITY_RUNTIME_PROFILE_ENV, raising=False)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_reference_fixture_freezes_53211_inventory() -> None:
    district = load_reference_district()

    assert district.district_ref == "fixture:district-01"
    assert district.runtime_profile == "bootstrap_sim"
    assert len(district.features.parcels) == 5
    assert len(district.features.buildings) == 3
    assert len(district.features.roads) == 2
    assert len(district.features.utilities) == 1
    assert len(district.features.workshops) == 1
    assert district.features.parcels[-1] == "parcel:05:private"
    assert district.features.utilities == ("water_segment:01:main_feed",)
    assert len(district.feature_records) == 12


def test_fixture_is_packaged_json_and_strictly_validated() -> None:
    payload = json.loads(Path(REFERENCE_DISTRICT_FIXTURE_PATH).read_text(encoding="utf-8"))
    assert payload["features"]["workshops"] == ["subject:artisan:som_wood"]

    invalid_feature = dict(payload["feature_records"][0])
    invalid_feature["feature_ref"] = "parcel:01:workshop"
    with pytest.raises(ValidationError):
        CityFeatureV0.model_validate(invalid_feature)


def test_public_discovery_redacts_private_and_infrastructure_features() -> None:
    public_refs = {feature.local_ref for feature in public_discovery_features()}

    assert "parcel:01:workshop" in public_refs
    assert "building:01:north_workshop" in public_refs
    assert "parcel:04:depot" not in public_refs
    assert "parcel:05:private" not in public_refs
    assert "building:03:storage_depot" not in public_refs
    assert "water_segment:01:main_feed" not in public_refs


def test_haversine_distance_uses_pure_python_great_circle_math() -> None:
    assert haversine_distance(0.0, 0.0, 0.0, 0.0) == pytest.approx(0.0)
    assert haversine_distance(0.0, 0.0, 0.0, 1.0) == pytest.approx(
        111_195.08,
        rel=1e-5,
    )


def test_discovery_query_filters_and_orders_by_distance(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(monkeypatch)

    response = client.post(
        "/api/v1/discovery/query",
        json={
            "feature_kinds": ["building"],
            "latitude": 0.0,
            "longitude": 0.0,
            "radius_meters": 20.0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["runtime_profile"] == "bootstrap_sim"
    assert body["source_posture"] == "FIXTURE"
    assert body["result_count"] == 1
    assert body["results"][0]["local_ref"] == "building:01:north_workshop"
    assert body["results"][0]["distance_meters"] == pytest.approx(11.12, rel=1e-3)
    assert body["results"][0]["profile_is_authority"] is False
    assert body["results"][0]["action_allowed"] is False
    assert "properties" not in body["results"][0]


def test_discovery_query_supports_text_without_exposing_protected_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)

    response = client.post(
        "/api/v1/discovery/query",
        json={"query": "workshop", "feature_kinds": ["parcel", "building"]},
    )

    assert response.status_code == 200
    refs = {item["local_ref"] for item in response.json()["results"]}
    assert refs == {
        "building:01:north_workshop",
        "parcel:01:workshop",
    }
    assert "water_segment:01:main_feed" not in refs


def test_projection_and_anchor_reads_share_the_same_public_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    projection_id = "projection:fixture:district-01:building:01:north_workshop"

    projection = client.get(f"/api/v1/discovery/projections/{projection_id}")
    anchor = client.get(
        "/api/v1/discovery/anchors/fixture:district-01:anchor:workshop"
    )

    assert projection.status_code == 200
    assert anchor.status_code == 200
    assert projection.json()["feature_ref"] == anchor.json()["feature_ref"]
    assert projection.json()["distance_meters"] is None


def test_discovery_fixture_fails_closed_outside_bootstrap_sim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch, enabled=False)

    response = client.post("/api/v1/discovery/query", json={})

    assert response.status_code == 404
    assert response.json()["detail"] == "Discovery fixture is not enabled"


def test_spatial_query_requires_complete_coordinate_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)

    response = client.post(
        "/api/v1/discovery/query",
        json={"latitude": 0.0, "radius_meters": 100.0},
    )

    assert response.status_code == 422
