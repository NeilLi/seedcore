"""Read-only service for the deterministic 5-3-2-1-1 reference district."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from seedcore.models.city_foundation import (
    CityFeatureV0,
    CityVisibility,
    REFERENCE_DISTRICT_REF,
    REFERENCE_DISTRICT_RUNTIME_PROFILE,
    ReferenceDistrictV0,
)
from seedcore.services.city_foundation_repository import (
    CityFoundationRepository,
    CityFoundationStorageError,
    PostgresCityFoundationRepository,
    canonical_reference_district_payload,
)

REFERENCE_DISTRICT_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "city_reference_district_v0.json"
)
PUBLIC_DISCOVERY_VISIBILITIES = frozenset(
    {CityVisibility.PUBLIC, CityVisibility.PUBLIC_COARSE}
)
CITY_FOUNDATION_STORAGE_ENV = "SEEDCORE_CITY_FOUNDATION_STORAGE"
CITY_RUNTIME_PROFILE_ENV = "SEEDCORE_CITY_RUNTIME_PROFILE"
CITY_FOUNDATION_STORAGE_FIXTURE = "fixture"
CITY_FOUNDATION_STORAGE_POSTGRES = "postgres"


@lru_cache(maxsize=1)
def _load_reference_district_cached() -> ReferenceDistrictV0:
    payload = json.loads(REFERENCE_DISTRICT_FIXTURE_PATH.read_text(encoding="utf-8"))
    return ReferenceDistrictV0.model_validate(payload)


def load_packaged_reference_district() -> ReferenceDistrictV0:
    """Return an isolated copy of the reviewed, non-live fixture artifact."""

    return _load_reference_district_cached().model_copy(deep=True)


def _selected_storage() -> Literal["fixture", "postgres"]:
    storage = (
        os.getenv(
            CITY_FOUNDATION_STORAGE_ENV,
            CITY_FOUNDATION_STORAGE_FIXTURE,
        )
        .strip()
        .lower()
    )
    if storage not in {
        CITY_FOUNDATION_STORAGE_FIXTURE,
        CITY_FOUNDATION_STORAGE_POSTGRES,
    }:
        raise CityFoundationStorageError(
            f"unsupported city foundation storage {storage!r}"
        )
    return storage  # type: ignore[return-value]


def _postgres_repository() -> PostgresCityFoundationRepository:
    if os.getenv(CITY_RUNTIME_PROFILE_ENV) != REFERENCE_DISTRICT_RUNTIME_PROFILE:
        raise CityFoundationStorageError(
            "PostgreSQL city foundation requires bootstrap_sim runtime profile"
        )
    from seedcore.database import get_sync_pg_engine

    return PostgresCityFoundationRepository(get_sync_pg_engine())


def load_reference_district(
    *,
    repository: CityFoundationRepository | None = None,
) -> ReferenceDistrictV0:
    """Load an isolated district from the explicitly selected storage boundary."""

    if repository is not None:
        return repository.load_reference_district(REFERENCE_DISTRICT_REF).model_copy(
            deep=True
        )
    if _selected_storage() == CITY_FOUNDATION_STORAGE_POSTGRES:
        return (
            _postgres_repository()
            .load_reference_district(REFERENCE_DISTRICT_REF)
            .model_copy(deep=True)
        )
    return load_packaged_reference_district()


def persist_reference_district(
    *,
    repository: CityFoundationRepository | None = None,
) -> ReferenceDistrictV0:
    """Explicitly seed the reviewed fixture; never called as a read fallback."""

    resolved_repository = repository or _postgres_repository()
    district = load_packaged_reference_district()
    resolved_repository.replace_reference_district(district)
    persisted = resolved_repository.load_reference_district(district.district_ref)
    if canonical_reference_district_payload(
        persisted
    ) != canonical_reference_district_payload(district):
        raise CityFoundationStorageError(
            "persisted reference district failed parity check"
        )
    return persisted


def public_discovery_features(
    district: ReferenceDistrictV0 | None = None,
) -> tuple[CityFeatureV0, ...]:
    resolved = district or load_reference_district()
    return tuple(
        feature
        for feature in resolved.feature_records
        if feature.visibility in PUBLIC_DISCOVERY_VISIBILITIES
        and feature.geometry.visibility in PUBLIC_DISCOVERY_VISIBILITIES
    )


def feature_by_ref(
    feature_ref: str,
    *,
    district: ReferenceDistrictV0 | None = None,
    public_only: bool = True,
) -> CityFeatureV0 | None:
    features = (
        public_discovery_features(district)
        if public_only
        else (district or load_reference_district()).feature_records
    )
    return next(
        (
            feature
            for feature in features
            if feature.feature_ref == feature_ref or feature.local_ref == feature_ref
        ),
        None,
    )


def feature_by_projection_id(
    projection_id: str,
    *,
    district: ReferenceDistrictV0 | None = None,
) -> CityFeatureV0 | None:
    prefix = "projection:"
    if not projection_id.startswith(prefix):
        return None
    return feature_by_ref(
        projection_id[len(prefix) :], district=district, public_only=True
    )


def feature_by_public_anchor(
    public_anchor_ref: str,
    *,
    district: ReferenceDistrictV0 | None = None,
) -> CityFeatureV0 | None:
    return next(
        (
            feature
            for feature in public_discovery_features(district)
            if feature.public_anchor_ref == public_anchor_ref
        ),
        None,
    )


__all__ = [
    "PUBLIC_DISCOVERY_VISIBILITIES",
    "REFERENCE_DISTRICT_FIXTURE_PATH",
    "CITY_FOUNDATION_STORAGE_ENV",
    "CITY_FOUNDATION_STORAGE_FIXTURE",
    "CITY_FOUNDATION_STORAGE_POSTGRES",
    "feature_by_projection_id",
    "feature_by_public_anchor",
    "feature_by_ref",
    "load_reference_district",
    "load_packaged_reference_district",
    "persist_reference_district",
    "public_discovery_features",
]
