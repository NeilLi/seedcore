-- Migration 137: bounded sovereign-city foundation persistence (C1b)
-- Scope: bootstrap_sim reference features, current geometry, and relationships.

BEGIN;

CREATE SCHEMA IF NOT EXISTS seedcore_city_foundation;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'seedcore_city_foundation_read') THEN
        CREATE ROLE seedcore_city_foundation_read NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'seedcore_city_foundation_write') THEN
        CREATE ROLE seedcore_city_foundation_write NOLOGIN;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS seedcore_city_foundation.city_features (
    feature_ref TEXT PRIMARY KEY,
    contract_version TEXT NOT NULL,
    district_ref TEXT NOT NULL,
    runtime_profile TEXT NOT NULL,
    district_as_of TIMESTAMPTZ NOT NULL,
    local_ref TEXT NOT NULL,
    feature_kind TEXT NOT NULL,
    name TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL,
    administrative_state TEXT NOT NULL,
    physical_state TEXT NOT NULL,
    operational_state TEXT NOT NULL,
    trust_state TEXT NOT NULL,
    source_posture TEXT NOT NULL,
    visibility TEXT NOT NULL,
    public_anchor_ref TEXT NULL,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_city_features_contract
        CHECK (contract_version = 'seedcore.city_feature.v0'),
    CONSTRAINT chk_city_features_runtime
        CHECK (runtime_profile = 'bootstrap_sim'),
    CONSTRAINT chk_city_features_fixture_namespace
        CHECK (
            district_ref = 'fixture:district-01'
            AND feature_ref LIKE 'fixture:district-01:%'
            AND local_ref NOT LIKE 'fixture:%'
            AND local_ref NOT LIKE 'sim:%'
            AND (
                public_anchor_ref IS NULL
                OR public_anchor_ref LIKE 'fixture:district-01:anchor:%'
            )
        ),
    CONSTRAINT chk_city_features_kind
        CHECK (feature_kind IN ('parcel', 'building', 'road', 'water_segment', 'workshop')),
    CONSTRAINT chk_city_features_lifecycle
        CHECK (lifecycle_state IN ('PLANNED', 'OPERATIONAL', 'UNDER_MAINTENANCE', 'RETIRED')),
    CONSTRAINT chk_city_features_visibility
        CHECK (visibility IN ('PUBLIC', 'PUBLIC_COARSE', 'OPERATOR', 'PROTECTED_INFRASTRUCTURE')),
    CONSTRAINT ux_city_features_district_local UNIQUE (district_ref, local_ref)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_city_features_public_anchor
    ON seedcore_city_foundation.city_features(district_ref, public_anchor_ref)
    WHERE public_anchor_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_city_features_discovery
    ON seedcore_city_foundation.city_features(district_ref, feature_kind, visibility);

CREATE TABLE IF NOT EXISTS seedcore_city_foundation.city_feature_geometries (
    geometry_ref TEXT PRIMARY KEY,
    feature_ref TEXT NOT NULL
        REFERENCES seedcore_city_foundation.city_features(feature_ref) ON DELETE CASCADE,
    district_ref TEXT NOT NULL,
    geometry_version INTEGER NOT NULL,
    geometry JSONB NOT NULL,
    crs TEXT NOT NULL,
    precision_class TEXT NOT NULL,
    source_posture TEXT NOT NULL,
    visibility TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_city_geometries_version CHECK (geometry_version > 0),
    CONSTRAINT chk_city_geometries_fixture_namespace
        CHECK (
            district_ref = 'fixture:district-01'
            AND geometry_ref LIKE 'fixture:district-01:%:geometry:v0'
        ),
    CONSTRAINT chk_city_geometries_crs CHECK (crs = 'EPSG:4326'),
    CONSTRAINT chk_city_geometries_point
        CHECK (
            jsonb_typeof(geometry) = 'object'
            AND geometry ? 'geometry_type'
            AND geometry ? 'coordinates'
            AND geometry ->> 'geometry_type' = 'Point'
            AND jsonb_typeof(geometry -> 'coordinates') = 'array'
            AND jsonb_array_length(geometry -> 'coordinates') = 2
        ),
    CONSTRAINT chk_city_geometries_visibility
        CHECK (visibility IN ('PUBLIC', 'PUBLIC_COARSE', 'OPERATOR', 'PROTECTED_INFRASTRUCTURE')),
    CONSTRAINT ux_city_geometries_feature_version UNIQUE (feature_ref, geometry_version)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_city_geometries_current
    ON seedcore_city_foundation.city_feature_geometries(feature_ref)
    WHERE is_current = TRUE;
CREATE INDEX IF NOT EXISTS ix_city_geometries_district
    ON seedcore_city_foundation.city_feature_geometries(district_ref);

CREATE TABLE IF NOT EXISTS seedcore_city_foundation.city_feature_relationships (
    relationship_ref TEXT PRIMARY KEY,
    contract_version TEXT NOT NULL,
    district_ref TEXT NOT NULL,
    relationship_kind TEXT NOT NULL,
    from_feature_ref TEXT NOT NULL
        REFERENCES seedcore_city_foundation.city_features(feature_ref) ON DELETE CASCADE,
    to_feature_ref TEXT NOT NULL
        REFERENCES seedcore_city_foundation.city_features(feature_ref) ON DELETE CASCADE,
    source_posture TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_city_relationships_contract
        CHECK (contract_version = 'seedcore.city_relationship.v0'),
    CONSTRAINT chk_city_relationships_fixture_namespace
        CHECK (
            district_ref = 'fixture:district-01'
            AND relationship_ref LIKE 'fixture:district-01:relationship:%'
        ),
    CONSTRAINT chk_city_relationships_kind
        CHECK (relationship_kind IN ('LOCATED_IN', 'CONNECTS', 'SERVES', 'HOSTS', 'ACCESS_VIA')),
    CONSTRAINT chk_city_relationships_distinct_endpoints
        CHECK (from_feature_ref <> to_feature_ref),
    CONSTRAINT chk_city_relationships_time
        CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE INDEX IF NOT EXISTS ix_city_relationships_from
    ON seedcore_city_foundation.city_feature_relationships(district_ref, from_feature_ref);
CREATE INDEX IF NOT EXISTS ix_city_relationships_to
    ON seedcore_city_foundation.city_feature_relationships(district_ref, to_feature_ref);

GRANT USAGE ON SCHEMA seedcore_city_foundation
    TO seedcore_city_foundation_read, seedcore_city_foundation_write;
GRANT SELECT ON ALL TABLES IN SCHEMA seedcore_city_foundation
    TO seedcore_city_foundation_read;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA seedcore_city_foundation
    TO seedcore_city_foundation_write;
ALTER DEFAULT PRIVILEGES IN SCHEMA seedcore_city_foundation
    GRANT SELECT ON TABLES TO seedcore_city_foundation_read;
ALTER DEFAULT PRIVILEGES IN SCHEMA seedcore_city_foundation
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO seedcore_city_foundation_write;

COMMIT;
