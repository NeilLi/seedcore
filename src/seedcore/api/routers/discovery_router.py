"""Read-only discovery over the deterministic SeedCore reference district.

This router intentionally uses no database, GIS extension, model inference, or
authority-bearing action. It is available only in the ``bootstrap_sim`` city
runtime profile.
"""

from __future__ import annotations

import math
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from seedcore.models.city_foundation import (
    CityFeatureKind,
    CityFeatureV0,
    CitySourcePosture,
    REFERENCE_DISTRICT_RUNTIME_PROFILE,
)
from seedcore.services.city_foundation_service import (
    feature_by_projection_id,
    feature_by_public_anchor,
    load_reference_district,
    public_discovery_features,
)


CITY_RUNTIME_PROFILE_ENV = "SEEDCORE_CITY_RUNTIME_PROFILE"
EARTH_RADIUS_METERS = 6_371_008.8


def _require_bootstrap_sim() -> None:
    if os.getenv(CITY_RUNTIME_PROFILE_ENV) != REFERENCE_DISTRICT_RUNTIME_PROFILE:
        raise HTTPException(status_code=404, detail="Discovery fixture is not enabled")


router = APIRouter(prefix="/discovery", dependencies=[Depends(_require_bootstrap_sim)])


def haversine_distance(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return great-circle distance in meters for two WGS84 coordinates."""

    lat_a = math.radians(latitude_a)
    lat_b = math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    haversine = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2.0) ** 2
    )
    angular_distance = 2.0 * math.atan2(math.sqrt(haversine), math.sqrt(1.0 - haversine))
    return EARTH_RADIUS_METERS * angular_distance


class DiscoveryQueryV0(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(default=None, max_length=160)
    feature_kinds: list[CityFeatureKind] = Field(default_factory=list, max_length=8)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    radius_meters: float | None = Field(default=None, gt=0.0, le=100_000.0)
    limit: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def validate_spatial_query(self) -> "DiscoveryQueryV0":
        has_latitude = self.latitude is not None
        has_longitude = self.longitude is not None
        if has_latitude != has_longitude:
            raise ValueError("latitude and longitude must be supplied together")
        if self.radius_meters is not None and not has_latitude:
            raise ValueError("radius_meters requires latitude and longitude")
        if self.query is not None:
            normalized_query = self.query.strip()
            self.query = normalized_query or None
        return self


class DiscoveryLocationV0(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    latitude: float
    longitude: float
    precision_class: str


class DiscoveryProjectionV0(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: str = "seedcore.discovery_projection.v0"
    projection_id: str
    district_ref: str
    as_of: str
    feature_ref: str
    local_ref: str
    feature_kind: CityFeatureKind
    name: str
    lifecycle_state: str
    administrative_state: str
    physical_state: str
    operational_state: str
    trust_state: str
    source_posture: CitySourcePosture
    public_anchor_ref: str | None = None
    location: DiscoveryLocationV0
    distance_meters: float | None = None
    profile_is_authority: bool = False
    action_allowed: bool = False


class DiscoveryQueryResponseV0(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: str = "seedcore.discovery_query_response.v0"
    district_ref: str
    as_of: str
    source_posture: CitySourcePosture
    runtime_profile: str
    result_count: int
    results: tuple[DiscoveryProjectionV0, ...]


def _projection_from_feature(
    feature: CityFeatureV0,
    *,
    district_ref: str,
    as_of: str,
    distance_meters: float | None = None,
) -> DiscoveryProjectionV0:
    return DiscoveryProjectionV0(
        projection_id=f"projection:{feature.feature_ref}",
        district_ref=district_ref,
        as_of=as_of,
        feature_ref=feature.feature_ref,
        local_ref=feature.local_ref,
        feature_kind=feature.feature_kind,
        name=feature.name,
        lifecycle_state=feature.lifecycle_state.value,
        administrative_state=feature.administrative_state.value,
        physical_state=feature.physical_state.value,
        operational_state=feature.operational_state.value,
        trust_state=feature.trust_state.value,
        source_posture=feature.source_posture,
        public_anchor_ref=feature.public_anchor_ref,
        location=DiscoveryLocationV0(
            latitude=feature.geometry.latitude,
            longitude=feature.geometry.longitude,
            precision_class=feature.geometry.precision_class,
        ),
        distance_meters=None if distance_meters is None else round(distance_meters, 3),
    )


@router.post("/query", response_model=DiscoveryQueryResponseV0)
def query_discovery(request: DiscoveryQueryV0) -> DiscoveryQueryResponseV0:
    district = load_reference_district()
    normalized_query = request.query.casefold() if request.query else None
    allowed_kinds = set(request.feature_kinds)
    candidates: list[tuple[CityFeatureV0, float | None]] = []

    for feature in public_discovery_features(district):
        if allowed_kinds and feature.feature_kind not in allowed_kinds:
            continue
        if normalized_query is not None:
            searchable = " ".join(
                (feature.name, feature.local_ref, feature.feature_kind.value)
            ).casefold()
            if normalized_query not in searchable:
                continue

        distance: float | None = None
        if request.latitude is not None and request.longitude is not None:
            distance = haversine_distance(
                request.latitude,
                request.longitude,
                feature.geometry.latitude,
                feature.geometry.longitude,
            )
            if request.radius_meters is not None and distance > request.radius_meters:
                continue
        candidates.append((feature, distance))

    candidates.sort(
        key=lambda item: (
            item[1] is None,
            item[1] if item[1] is not None else 0.0,
            item[0].feature_ref,
        )
    )
    results = tuple(
        _projection_from_feature(
            feature,
            district_ref=district.district_ref,
            as_of=district.as_of,
            distance_meters=distance,
        )
        for feature, distance in candidates[: request.limit]
    )
    return DiscoveryQueryResponseV0(
        district_ref=district.district_ref,
        as_of=district.as_of,
        source_posture=district.source_posture,
        runtime_profile=district.runtime_profile,
        result_count=len(results),
        results=results,
    )


@router.get("/projections/{projection_id:path}", response_model=DiscoveryProjectionV0)
def get_discovery_projection(projection_id: str) -> DiscoveryProjectionV0:
    district = load_reference_district()
    feature = feature_by_projection_id(projection_id, district=district)
    if feature is None:
        raise HTTPException(status_code=404, detail="Discovery projection not found")
    return _projection_from_feature(
        feature,
        district_ref=district.district_ref,
        as_of=district.as_of,
    )


@router.get("/anchors/{public_anchor_ref:path}", response_model=DiscoveryProjectionV0)
def get_discovery_anchor(public_anchor_ref: str) -> DiscoveryProjectionV0:
    district = load_reference_district()
    feature = feature_by_public_anchor(public_anchor_ref, district=district)
    if feature is None:
        raise HTTPException(status_code=404, detail="Public anchor not found")
    return _projection_from_feature(
        feature,
        district_ref=district.district_ref,
        as_of=district.as_of,
    )


__all__ = [
    "CITY_RUNTIME_PROFILE_ENV",
    "DiscoveryProjectionV0",
    "DiscoveryQueryResponseV0",
    "DiscoveryQueryV0",
    "get_discovery_anchor",
    "get_discovery_projection",
    "haversine_distance",
    "query_discovery",
    "router",
]
