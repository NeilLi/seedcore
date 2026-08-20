"""Explicit PostgreSQL boundary for the bootstrap city foundation.

This repository persists and reconstructs the strict ``ReferenceDistrictV0``
envelope. It is not queried by PDP or PKG hot paths and never falls back to a
fixture after PostgreSQL has been explicitly selected.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Protocol, cast

from sqlalchemy import text
from sqlalchemy.engine import Engine

from seedcore.models.city_foundation import (
    CityFeatureKind,
    CityFeatureRelationshipV0,
    CityFeatureV0,
    ReferenceDistrictV0,
    ReferenceFeatureInventoryV0,
)

CITY_FOUNDATION_SCHEMA = "seedcore_city_foundation"


class CityFoundationStorageError(RuntimeError):
    """Fail-closed persistence or hydration error."""


class CityFoundationRepository(Protocol):
    def load_reference_district(self, district_ref: str) -> ReferenceDistrictV0: ...

    def replace_reference_district(self, district: ReferenceDistrictV0) -> None: ...


_DELETE_RELATIONSHIPS_SQL = text("""
    DELETE FROM seedcore_city_foundation.city_feature_relationships
    WHERE district_ref = :district_ref
    """)
_DELETE_GEOMETRIES_SQL = text("""
    DELETE FROM seedcore_city_foundation.city_feature_geometries
    WHERE district_ref = :district_ref
    """)
_DELETE_FEATURES_SQL = text("""
    DELETE FROM seedcore_city_foundation.city_features
    WHERE district_ref = :district_ref
    """)
_INSERT_FEATURE_SQL = text("""
    INSERT INTO seedcore_city_foundation.city_features (
        feature_ref, contract_version, district_ref, runtime_profile,
        district_as_of, local_ref, feature_kind, name, lifecycle_state,
        administrative_state, physical_state, operational_state, trust_state,
        source_posture, visibility, public_anchor_ref, properties
    ) VALUES (
        :feature_ref, :contract_version, :district_ref, :runtime_profile,
        :district_as_of, :local_ref, :feature_kind, :name, :lifecycle_state,
        :administrative_state, :physical_state, :operational_state, :trust_state,
        :source_posture, :visibility, :public_anchor_ref, CAST(:properties AS JSONB)
    )
    """)
_INSERT_GEOMETRY_SQL = text("""
    INSERT INTO seedcore_city_foundation.city_feature_geometries (
        geometry_ref, feature_ref, district_ref, geometry_version, geometry,
        crs, precision_class, source_posture, visibility, observed_at, is_current
    ) VALUES (
        :geometry_ref, :feature_ref, :district_ref, :geometry_version,
        CAST(:geometry AS JSONB), :crs, :precision_class, :source_posture,
        :visibility, :observed_at, TRUE
    )
    """)
_INSERT_RELATIONSHIP_SQL = text("""
    INSERT INTO seedcore_city_foundation.city_feature_relationships (
        relationship_ref, contract_version, district_ref, relationship_kind,
        from_feature_ref, to_feature_ref, source_posture, valid_from
    ) VALUES (
        :relationship_ref, :contract_version, :district_ref, :relationship_kind,
        :from_feature_ref, :to_feature_ref, :source_posture, :valid_from
    )
    """)
_SELECT_FEATURES_SQL = text("""
    SELECT
        f.feature_ref, f.contract_version, f.district_ref, f.runtime_profile,
        f.district_as_of, f.local_ref, f.feature_kind, f.name,
        f.lifecycle_state, f.administrative_state, f.physical_state,
        f.operational_state, f.trust_state, f.source_posture, f.visibility,
        f.public_anchor_ref, f.properties, g.geometry
    FROM seedcore_city_foundation.city_features AS f
    JOIN seedcore_city_foundation.city_feature_geometries AS g
      ON g.feature_ref = f.feature_ref AND g.is_current = TRUE
    WHERE f.district_ref = :district_ref
    ORDER BY f.feature_ref
    """)
_SELECT_RELATIONSHIPS_SQL = text("""
    SELECT
        relationship_ref, contract_version, district_ref, relationship_kind,
        from_feature_ref, to_feature_ref, source_posture
    FROM seedcore_city_foundation.city_feature_relationships
    WHERE district_ref = :district_ref AND valid_to IS NULL
    ORDER BY relationship_ref
    """)


def _json_payload(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _canonical_as_of(value: Any) -> str:
    if isinstance(value, datetime):
        return (
            value.astimezone(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    return str(value)


def feature_storage_row(
    district: ReferenceDistrictV0,
    feature: CityFeatureV0,
) -> dict[str, Any]:
    return {
        "feature_ref": feature.feature_ref,
        "contract_version": feature.contract_version,
        "district_ref": district.district_ref,
        "runtime_profile": district.runtime_profile,
        "district_as_of": district.as_of,
        "local_ref": feature.local_ref,
        "feature_kind": feature.feature_kind.value,
        "name": feature.name,
        "lifecycle_state": feature.lifecycle_state.value,
        "administrative_state": feature.administrative_state.value,
        "physical_state": feature.physical_state.value,
        "operational_state": feature.operational_state.value,
        "trust_state": feature.trust_state.value,
        "source_posture": feature.source_posture.value,
        "visibility": feature.visibility.value,
        "public_anchor_ref": feature.public_anchor_ref,
        "properties": json.dumps(
            feature.properties, sort_keys=True, separators=(",", ":")
        ),
    }


def geometry_storage_row(
    district: ReferenceDistrictV0,
    feature: CityFeatureV0,
) -> dict[str, Any]:
    return {
        "geometry_ref": f"{feature.feature_ref}:geometry:v0",
        "feature_ref": feature.feature_ref,
        "district_ref": district.district_ref,
        "geometry_version": 1,
        "geometry": json.dumps(
            feature.geometry.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ),
        "crs": feature.geometry.crs,
        "precision_class": feature.geometry.precision_class,
        "source_posture": feature.geometry.source_posture.value,
        "visibility": feature.geometry.visibility.value,
        "observed_at": district.as_of,
    }


def relationship_storage_row(
    district: ReferenceDistrictV0,
    relationship: CityFeatureRelationshipV0,
) -> dict[str, Any]:
    return {
        "relationship_ref": relationship.relationship_ref,
        "contract_version": relationship.contract_version,
        "district_ref": district.district_ref,
        "relationship_kind": relationship.relationship_kind,
        "from_feature_ref": relationship.from_feature_ref,
        "to_feature_ref": relationship.to_feature_ref,
        "source_posture": relationship.source_posture.value,
        "valid_from": district.as_of,
    }


def hydrate_reference_district(
    feature_rows: Sequence[Mapping[str, Any]],
    relationship_rows: Sequence[Mapping[str, Any]],
) -> ReferenceDistrictV0:
    if not feature_rows:
        raise CityFoundationStorageError("reference district is absent from PostgreSQL")

    first = feature_rows[0]
    identity = {
        (
            row["district_ref"],
            row["runtime_profile"],
            _canonical_as_of(row["district_as_of"]),
        )
        for row in feature_rows
    }
    if len(identity) != 1:
        raise CityFoundationStorageError(
            "persisted feature rows disagree on district identity"
        )

    feature_payloads: list[dict[str, Any]] = []
    inventory: dict[CityFeatureKind, list[str]] = {kind: [] for kind in CityFeatureKind}
    for row in feature_rows:
        kind = CityFeatureKind(row["feature_kind"])
        inventory[kind].append(row["local_ref"])
        feature_payloads.append(
            {
                "contract_version": row["contract_version"],
                "feature_ref": row["feature_ref"],
                "local_ref": row["local_ref"],
                "feature_kind": kind.value,
                "name": row["name"],
                "lifecycle_state": row["lifecycle_state"],
                "administrative_state": row["administrative_state"],
                "physical_state": row["physical_state"],
                "operational_state": row["operational_state"],
                "trust_state": row["trust_state"],
                "source_posture": row["source_posture"],
                "visibility": row["visibility"],
                "geometry": _json_payload(row["geometry"]),
                "public_anchor_ref": row["public_anchor_ref"],
                "properties": _json_payload(row["properties"]),
            }
        )

    relationship_payloads = [
        {
            "contract_version": row["contract_version"],
            "relationship_ref": row["relationship_ref"],
            "relationship_kind": row["relationship_kind"],
            "from_feature_ref": row["from_feature_ref"],
            "to_feature_ref": row["to_feature_ref"],
            "source_posture": row["source_posture"],
        }
        for row in relationship_rows
    ]

    feature_inventory = ReferenceFeatureInventoryV0(
        parcels=tuple(sorted(inventory[CityFeatureKind.PARCEL])),
        buildings=tuple(sorted(inventory[CityFeatureKind.BUILDING])),
        roads=tuple(sorted(inventory[CityFeatureKind.ROAD])),
        utilities=tuple(sorted(inventory[CityFeatureKind.WATER_SEGMENT])),
        workshops=tuple(sorted(inventory[CityFeatureKind.WORKSHOP])),
    )
    return ReferenceDistrictV0.model_validate(
        {
            "district_ref": first["district_ref"],
            "runtime_profile": first["runtime_profile"],
            "source_posture": "FIXTURE",
            "as_of": _canonical_as_of(first["district_as_of"]),
            "features": feature_inventory.model_dump(mode="json"),
            "feature_records": feature_payloads,
            "relationships": relationship_payloads,
        }
    )


def canonical_reference_district_payload(
    district: ReferenceDistrictV0,
) -> dict[str, Any]:
    """Normalize set-like collections for storage parity comparisons."""

    payload = district.model_dump(mode="json")
    for inventory_key in ("parcels", "buildings", "roads", "utilities", "workshops"):
        payload["features"][inventory_key] = sorted(payload["features"][inventory_key])
    payload["feature_records"] = sorted(
        payload["feature_records"], key=lambda item: item["feature_ref"]
    )
    payload["relationships"] = sorted(
        payload["relationships"], key=lambda item: item["relationship_ref"]
    )
    return payload


class PostgresCityFoundationRepository:
    def __init__(self, engine: Engine):
        self._engine = engine

    def replace_reference_district(self, district: ReferenceDistrictV0) -> None:
        feature_rows = [
            feature_storage_row(district, feature)
            for feature in district.feature_records
        ]
        geometry_rows = [
            geometry_storage_row(district, feature)
            for feature in district.feature_records
        ]
        relationship_rows = [
            relationship_storage_row(district, relationship)
            for relationship in district.relationships
        ]
        try:
            with self._engine.begin() as connection:
                params = {"district_ref": district.district_ref}
                connection.execute(_DELETE_RELATIONSHIPS_SQL, params)
                connection.execute(_DELETE_GEOMETRIES_SQL, params)
                connection.execute(_DELETE_FEATURES_SQL, params)
                connection.execute(_INSERT_FEATURE_SQL, feature_rows)
                connection.execute(_INSERT_GEOMETRY_SQL, geometry_rows)
                connection.execute(_INSERT_RELATIONSHIP_SQL, relationship_rows)
                persisted_feature_rows = cast(
                    list[Mapping[str, Any]],
                    list(connection.execute(_SELECT_FEATURES_SQL, params).mappings()),
                )
                persisted_relationship_rows = cast(
                    list[Mapping[str, Any]],
                    list(
                        connection.execute(_SELECT_RELATIONSHIPS_SQL, params).mappings()
                    ),
                )
                persisted = hydrate_reference_district(
                    persisted_feature_rows,
                    persisted_relationship_rows,
                )
                if canonical_reference_district_payload(
                    persisted
                ) != canonical_reference_district_payload(district):
                    raise CityFoundationStorageError(
                        "transactional reference district parity check failed"
                    )
        except Exception as exc:  # pragma: no cover - exact driver errors vary
            raise CityFoundationStorageError(
                "failed to persist reference district"
            ) from exc

    def load_reference_district(self, district_ref: str) -> ReferenceDistrictV0:
        try:
            with self._engine.connect() as connection:
                feature_rows = cast(
                    list[Mapping[str, Any]],
                    list(
                        connection.execute(
                            _SELECT_FEATURES_SQL, {"district_ref": district_ref}
                        ).mappings()
                    ),
                )
                relationship_rows = cast(
                    list[Mapping[str, Any]],
                    list(
                        connection.execute(
                            _SELECT_RELATIONSHIPS_SQL,
                            {"district_ref": district_ref},
                        ).mappings()
                    ),
                )
        except Exception as exc:  # pragma: no cover - exact driver errors vary
            raise CityFoundationStorageError(
                "failed to load reference district"
            ) from exc
        return hydrate_reference_district(feature_rows, relationship_rows)


__all__ = [
    "CITY_FOUNDATION_SCHEMA",
    "CityFoundationRepository",
    "CityFoundationStorageError",
    "PostgresCityFoundationRepository",
    "canonical_reference_district_payload",
    "feature_storage_row",
    "geometry_storage_row",
    "hydrate_reference_district",
    "relationship_storage_row",
]
