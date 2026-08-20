from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from seedcore.models.city_foundation import ReferenceDistrictV0
from seedcore.services.city_foundation_repository import (
    CityFoundationStorageError,
    PostgresCityFoundationRepository,
    canonical_reference_district_payload,
    feature_storage_row,
    geometry_storage_row,
    hydrate_reference_district,
    relationship_storage_row,
)
from seedcore.services.city_foundation_service import (
    CITY_FOUNDATION_STORAGE_ENV,
    CITY_FOUNDATION_STORAGE_POSTGRES,
    CITY_RUNTIME_PROFILE_ENV,
    load_reference_district,
    persist_reference_district,
)

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "migrations"
    / "137_city_foundation.sql"
)


class InMemoryCityFoundationRepository:
    def __init__(self) -> None:
        self.district: ReferenceDistrictV0 | None = None

    def replace_reference_district(self, district: ReferenceDistrictV0) -> None:
        self.district = district.model_copy(deep=True)

    def load_reference_district(self, district_ref: str) -> ReferenceDistrictV0:
        if self.district is None or self.district.district_ref != district_ref:
            raise CityFoundationStorageError("district missing")
        return self.district.model_copy(deep=True)


class EmptyResult:
    def mappings(self) -> "EmptyResult":
        return self

    def __iter__(self):
        return iter(())


class TrackingConnection:
    def __init__(self) -> None:
        self.execute_count = 0

    def execute(self, *_args, **_kwargs) -> EmptyResult:
        self.execute_count += 1
        return EmptyResult()


class TrackingTransaction:
    def __init__(self, engine: "TrackingEngine") -> None:
        self.engine = engine

    def __enter__(self) -> TrackingConnection:
        return self.engine.connection

    def __exit__(self, exc_type, _exc, _traceback) -> bool:
        self.engine.rolled_back = exc_type is not None
        return False


class TrackingEngine:
    def __init__(self) -> None:
        self.connection = TrackingConnection()
        self.rolled_back = False

    def begin(self) -> TrackingTransaction:
        return TrackingTransaction(self)


def test_three_table_migration_freezes_schema_and_roles() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    assert sql.count("CREATE TABLE IF NOT EXISTS seedcore_city_foundation.") == 3
    assert "seedcore_city_foundation.city_features" in sql
    assert "seedcore_city_foundation.city_feature_geometries" in sql
    assert "seedcore_city_foundation.city_feature_relationships" in sql
    assert "seedcore_city_foundation_read" in sql
    assert "seedcore_city_foundation_write" in sql
    assert "runtime_profile = 'bootstrap_sim'" in sql
    assert "PostGIS" not in sql


def test_storage_rows_round_trip_to_strict_reference_district() -> None:
    district = load_reference_district()
    feature_rows = []
    for feature in district.feature_records:
        feature_row = feature_storage_row(district, feature)
        feature_row["geometry"] = geometry_storage_row(district, feature)["geometry"]
        feature_rows.append(feature_row)
    relationship_rows = [
        relationship_storage_row(district, relationship)
        for relationship in district.relationships
    ]

    hydrated = hydrate_reference_district(feature_rows, relationship_rows)

    assert hydrated.model_dump(mode="json") == district.model_dump(mode="json")


def test_storage_parity_treats_feature_and_relationship_order_as_set_like() -> None:
    district = load_reference_district()
    reordered = district.model_copy(
        update={
            "feature_records": tuple(reversed(district.feature_records)),
            "relationships": tuple(reversed(district.relationships)),
        }
    )

    assert canonical_reference_district_payload(reordered) == (
        canonical_reference_district_payload(district)
    )


def test_hydration_normalizes_database_session_timezone_to_utc() -> None:
    district = load_reference_district()
    feature_rows = []
    for feature in district.feature_records:
        feature_row = feature_storage_row(district, feature)
        feature_row["geometry"] = geometry_storage_row(district, feature)["geometry"]
        feature_row["district_as_of"] = datetime.fromisoformat(
            "2026-08-17T07:00:00+07:00"
        )
        feature_rows.append(feature_row)
    relationship_rows = [
        relationship_storage_row(district, relationship)
        for relationship in district.relationships
    ]

    hydrated = hydrate_reference_district(feature_rows, relationship_rows)

    assert hydrated.as_of == "2026-08-17T00:00:00Z"


def test_explicit_seed_requires_round_trip_parity() -> None:
    repository = InMemoryCityFoundationRepository()

    persisted = persist_reference_district(repository=repository)

    assert persisted.district_ref == "fixture:district-01"
    assert len(persisted.feature_records) == 12
    assert len(persisted.relationships) == 12


def test_transactional_parity_failure_rolls_back_before_commit() -> None:
    engine = TrackingEngine()
    repository = PostgresCityFoundationRepository(engine)  # type: ignore[arg-type]

    with pytest.raises(CityFoundationStorageError, match="failed to persist"):
        repository.replace_reference_district(load_reference_district())

    assert engine.connection.execute_count == 8
    assert engine.rolled_back is True


def test_repository_injection_never_uses_ambient_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCityFoundationRepository()
    fixture = load_reference_district()
    repository.replace_reference_district(fixture)
    monkeypatch.setenv(CITY_FOUNDATION_STORAGE_ENV, "unsupported")

    loaded = load_reference_district(repository=repository)

    assert loaded.model_dump(mode="json") == fixture.model_dump(mode="json")


def test_unknown_storage_profile_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CITY_FOUNDATION_STORAGE_ENV, "automatic-fallback")

    with pytest.raises(CityFoundationStorageError, match="unsupported"):
        load_reference_district()


def test_postgres_selection_requires_bootstrap_sim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CITY_FOUNDATION_STORAGE_ENV, CITY_FOUNDATION_STORAGE_POSTGRES)
    monkeypatch.delenv(CITY_RUNTIME_PROFILE_ENV, raising=False)

    with pytest.raises(CityFoundationStorageError, match="bootstrap_sim"):
        load_reference_district()
