"""Read-only service for the deterministic 5-3-2-1-1 reference district."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from seedcore.models.city_foundation import (
    CityFeatureV0,
    CityVisibility,
    ReferenceDistrictV0,
)


REFERENCE_DISTRICT_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "city_reference_district_v0.json"
)
PUBLIC_DISCOVERY_VISIBILITIES = frozenset(
    {CityVisibility.PUBLIC, CityVisibility.PUBLIC_COARSE}
)


@lru_cache(maxsize=1)
def _load_reference_district_cached() -> ReferenceDistrictV0:
    payload = json.loads(REFERENCE_DISTRICT_FIXTURE_PATH.read_text(encoding="utf-8"))
    return ReferenceDistrictV0.model_validate(payload)


def load_reference_district() -> ReferenceDistrictV0:
    """Return an isolated copy so callers cannot mutate the cached fixture."""

    return _load_reference_district_cached().model_copy(deep=True)


def public_discovery_features(district: ReferenceDistrictV0 | None = None) -> tuple[CityFeatureV0, ...]:
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
    return feature_by_ref(projection_id[len(prefix) :], district=district, public_only=True)


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
    "feature_by_projection_id",
    "feature_by_public_anchor",
    "feature_by_ref",
    "load_reference_district",
    "public_discovery_features",
]
