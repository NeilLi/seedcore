"""Strict contracts for the deterministic SeedCore reference district.

These models describe fixture and public-read state only. They do not grant
execution authority, establish legal or physical truth, or replace the
existing governed action, audit, replay, and verifier contracts.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CITY_FEATURE_CONTRACT_VERSION: Literal["seedcore.city_feature.v0"] = (
    "seedcore.city_feature.v0"
)
CITY_RELATIONSHIP_CONTRACT_VERSION: Literal["seedcore.city_relationship.v0"] = (
    "seedcore.city_relationship.v0"
)
REFERENCE_DISTRICT_CONTRACT_VERSION: Literal["seedcore.reference_district.v0"] = (
    "seedcore.reference_district.v0"
)
REFERENCE_DISTRICT_REF: Literal["fixture:district-01"] = "fixture:district-01"
REFERENCE_DISTRICT_RUNTIME_PROFILE: Literal["bootstrap_sim"] = "bootstrap_sim"


class CityFeatureKind(str, Enum):
    PARCEL = "parcel"
    BUILDING = "building"
    ROAD = "road"
    WATER_SEGMENT = "water_segment"
    WORKSHOP = "workshop"


class CityLifecycleState(str, Enum):
    PLANNED = "PLANNED"
    OPERATIONAL = "OPERATIONAL"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
    RETIRED = "RETIRED"


class CityAdministrativeState(str, Enum):
    FIXTURE_ONLY = "FIXTURE_ONLY"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    EXTERNAL_REFERENCE = "EXTERNAL_REFERENCE"


class CityPhysicalState(str, Enum):
    DECLARED = "DECLARED"
    OBSERVED_PRESENT = "OBSERVED_PRESENT"
    NOT_OBSERVED = "NOT_OBSERVED"


class CityOperationalState(str, Enum):
    AVAILABLE = "AVAILABLE"
    OPERATIONAL = "OPERATIONAL"
    CLOSED = "CLOSED"
    OUTAGE = "OUTAGE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CityTrustState(str, Enum):
    FIXTURE = "FIXTURE"
    DECLARED = "DECLARED"
    VERIFIED_FOR_CURRENT_PROFILE = "VERIFIED_FOR_CURRENT_PROFILE"
    QUARANTINED = "QUARANTINED"


class CitySourcePosture(str, Enum):
    FIXTURE = "FIXTURE"
    SIMULATED_PROVIDER = "SIMULATED_PROVIDER"
    OWNER_DECLARED = "OWNER_DECLARED"
    DEVICE_OBSERVED = "DEVICE_OBSERVED"
    SEEDCORE_DERIVED = "SEEDCORE_DERIVED"


class CityVisibility(str, Enum):
    PUBLIC = "PUBLIC"
    PUBLIC_COARSE = "PUBLIC_COARSE"
    OPERATOR = "OPERATOR"
    PROTECTED_INFRASTRUCTURE = "PROTECTED_INFRASTRUCTURE"


class GeometryEnvelopeV0(BaseModel):
    """Small WGS84 point envelope used by the Phase 1 fixture."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    geometry_type: Literal["Point"] = "Point"
    coordinates: tuple[float, float] = Field(
        description="GeoJSON coordinate order: longitude, latitude."
    )
    crs: Literal["EPSG:4326"] = "EPSG:4326"
    precision_class: Literal["fixture_exact", "public_coarse"] = "fixture_exact"
    source_posture: CitySourcePosture = CitySourcePosture.FIXTURE
    visibility: CityVisibility = CityVisibility.PUBLIC_COARSE

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(cls, value: tuple[float, float]) -> tuple[float, float]:
        longitude, latitude = value
        if not -180.0 <= longitude <= 180.0:
            raise ValueError("longitude must be between -180 and 180")
        if not -90.0 <= latitude <= 90.0:
            raise ValueError("latitude must be between -90 and 90")
        return value

    @property
    def longitude(self) -> float:
        return self.coordinates[0]

    @property
    def latitude(self) -> float:
        return self.coordinates[1]


class CityFeatureV0(BaseModel):
    """Authority-neutral feature envelope for deterministic discovery."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["seedcore.city_feature.v0"] = (
        CITY_FEATURE_CONTRACT_VERSION
    )
    feature_ref: str
    local_ref: str
    feature_kind: CityFeatureKind
    name: str = Field(min_length=1, max_length=160)
    lifecycle_state: CityLifecycleState
    administrative_state: CityAdministrativeState
    physical_state: CityPhysicalState
    operational_state: CityOperationalState
    trust_state: CityTrustState
    source_posture: CitySourcePosture = CitySourcePosture.FIXTURE
    visibility: CityVisibility = CityVisibility.PUBLIC_COARSE
    geometry: GeometryEnvelopeV0
    public_anchor_ref: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)

    @field_validator("feature_ref")
    @classmethod
    def require_fixture_namespace(cls, value: str) -> str:
        prefix = f"{REFERENCE_DISTRICT_REF}:"
        if not value.startswith(prefix):
            raise ValueError(f"feature_ref must start with {prefix!r}")
        return value

    @field_validator("local_ref")
    @classmethod
    def require_local_ref(cls, value: str) -> str:
        if value.startswith("fixture:") or value.startswith("sim:") or ":" not in value:
            raise ValueError("local_ref must be an unqualified typed reference")
        return value

    @field_validator("public_anchor_ref")
    @classmethod
    def validate_public_anchor_ref(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(
            f"{REFERENCE_DISTRICT_REF}:anchor:"
        ):
            raise ValueError(
                "public_anchor_ref must use the district fixture namespace"
            )
        return value


class CityFeatureRelationshipV0(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["seedcore.city_relationship.v0"] = (
        CITY_RELATIONSHIP_CONTRACT_VERSION
    )
    relationship_ref: str
    relationship_kind: Literal[
        "LOCATED_IN", "CONNECTS", "SERVES", "HOSTS", "ACCESS_VIA"
    ]
    from_feature_ref: str
    to_feature_ref: str
    source_posture: CitySourcePosture = CitySourcePosture.FIXTURE

    @field_validator("relationship_ref", "from_feature_ref", "to_feature_ref")
    @classmethod
    def require_fixture_ref(cls, value: str) -> str:
        if not value.startswith(f"{REFERENCE_DISTRICT_REF}:"):
            raise ValueError(
                "relationship refs and endpoints must use the district namespace"
            )
        return value


class ReferenceFeatureInventoryV0(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parcels: tuple[str, ...]
    buildings: tuple[str, ...]
    roads: tuple[str, ...]
    utilities: tuple[str, ...]
    workshops: tuple[str, ...]

    @model_validator(mode="after")
    def validate_53211_profile(self) -> "ReferenceFeatureInventoryV0":
        counts = (
            len(self.parcels),
            len(self.buildings),
            len(self.roads),
            len(self.utilities),
            len(self.workshops),
        )
        if counts != (5, 3, 2, 1, 1):
            raise ValueError(
                f"reference district must use the 5-3-2-1-1 profile, got {counts}"
            )
        refs = (
            self.parcels + self.buildings + self.roads + self.utilities + self.workshops
        )
        if len(set(refs)) != len(refs):
            raise ValueError("reference district local refs must be unique")
        return self


class ReferenceDistrictV0(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["seedcore.reference_district.v0"] = (
        REFERENCE_DISTRICT_CONTRACT_VERSION
    )
    district_ref: Literal["fixture:district-01"] = REFERENCE_DISTRICT_REF
    runtime_profile: Literal["bootstrap_sim"] = REFERENCE_DISTRICT_RUNTIME_PROFILE
    source_posture: Literal[CitySourcePosture.FIXTURE] = CitySourcePosture.FIXTURE
    as_of: str
    features: ReferenceFeatureInventoryV0
    feature_records: tuple[CityFeatureV0, ...]
    relationships: tuple[CityFeatureRelationshipV0, ...]

    @model_validator(mode="after")
    def validate_inventory_bindings(self) -> "ReferenceDistrictV0":
        inventory_refs = set(
            self.features.parcels
            + self.features.buildings
            + self.features.roads
            + self.features.utilities
            + self.features.workshops
        )
        record_local_refs = [record.local_ref for record in self.feature_records]
        if set(record_local_refs) != inventory_refs:
            missing = sorted(inventory_refs - set(record_local_refs))
            extra = sorted(set(record_local_refs) - inventory_refs)
            raise ValueError(
                f"fixture inventory mismatch: missing={missing}, extra={extra}"
            )
        if len(record_local_refs) != len(set(record_local_refs)):
            raise ValueError("feature record local refs must be unique")

        feature_refs = {record.feature_ref for record in self.feature_records}
        for relationship in self.relationships:
            if relationship.from_feature_ref not in feature_refs:
                raise ValueError(
                    f"unknown relationship source {relationship.from_feature_ref}"
                )
            if relationship.to_feature_ref not in feature_refs:
                raise ValueError(
                    f"unknown relationship target {relationship.to_feature_ref}"
                )
        return self


__all__ = [
    "CITY_FEATURE_CONTRACT_VERSION",
    "CITY_RELATIONSHIP_CONTRACT_VERSION",
    "REFERENCE_DISTRICT_CONTRACT_VERSION",
    "REFERENCE_DISTRICT_REF",
    "REFERENCE_DISTRICT_RUNTIME_PROFILE",
    "CityAdministrativeState",
    "CityFeatureKind",
    "CityFeatureRelationshipV0",
    "CityFeatureV0",
    "CityLifecycleState",
    "CityOperationalState",
    "CityPhysicalState",
    "CitySourcePosture",
    "CityTrustState",
    "CityVisibility",
    "GeometryEnvelopeV0",
    "ReferenceDistrictV0",
    "ReferenceFeatureInventoryV0",
]
