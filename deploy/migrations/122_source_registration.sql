-- Migration 122: Source Registration
-- Purpose: Add provenance-first source registration persistence for governed intake

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS source_registrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_claim_id TEXT NULL,
    lot_id TEXT NOT NULL,
    producer_id TEXT NOT NULL,
    rare_grade_profile_id TEXT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    claimed_origin JSONB NOT NULL DEFAULT '{}'::jsonb,
    collection_site JSONB NOT NULL DEFAULT '{}'::jsonb,
    collected_at TIMESTAMPTZ NULL,
    snapshot_id INTEGER NULL,
    submitted_task_id UUID NULL REFERENCES tasks(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_source_registrations_status'
    ) THEN
        ALTER TABLE source_registrations
        ADD CONSTRAINT chk_source_registrations_status
        CHECK (status IN ('draft', 'ingesting', 'verifying', 'approved', 'quarantined', 'rejected'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_source_registrations_status ON source_registrations(status);
CREATE INDEX IF NOT EXISTS ix_source_registrations_lot_id ON source_registrations(lot_id);
CREATE INDEX IF NOT EXISTS ix_source_registrations_snapshot_id ON source_registrations(snapshot_id);

CREATE TABLE IF NOT EXISTS source_registration_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    registration_id UUID NOT NULL REFERENCES source_registrations(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    uri TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    captured_at TIMESTAMPTZ NULL,
    captured_by TEXT NULL,
    device_id TEXT NULL,
    content_type TEXT NULL,
    meta_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_source_registration_artifacts_registration_id
    ON source_registration_artifacts(registration_id);
CREATE INDEX IF NOT EXISTS ix_source_registration_artifacts_sha256
    ON source_registration_artifacts(sha256);
CREATE UNIQUE INDEX IF NOT EXISTS ux_source_registration_artifacts_registration_sha256
    ON source_registration_artifacts(registration_id, sha256);

CREATE TABLE IF NOT EXISTS source_registration_measurements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    registration_id UUID NOT NULL REFERENCES source_registrations(id) ON DELETE CASCADE,
    measurement_type TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    unit TEXT NOT NULL,
    measured_at TIMESTAMPTZ NULL,
    sensor_id TEXT NULL,
    quality_score DOUBLE PRECISION NULL,
    raw_artifact_id UUID NULL REFERENCES source_registration_artifacts(id) ON DELETE SET NULL,
    meta_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_source_registration_measurements_registration_id
    ON source_registration_measurements(registration_id);
CREATE INDEX IF NOT EXISTS ix_source_registration_measurements_type
    ON source_registration_measurements(measurement_type);

CREATE TABLE IF NOT EXISTS registration_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    registration_id UUID NOT NULL REFERENCES source_registrations(id) ON DELETE CASCADE,
    decision TEXT NOT NULL,
    grade_result TEXT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    policy_snapshot_id INTEGER NULL,
    rule_trace JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason_codes JSONB NOT NULL DEFAULT '{}'::jsonb,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL DEFAULT 'coordinator'
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_registration_decisions_decision'
    ) THEN
        ALTER TABLE registration_decisions
        ADD CONSTRAINT chk_registration_decisions_decision
        CHECK (decision IN ('approved', 'quarantined', 'rejected'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_registration_decisions_registration_id
    ON registration_decisions(registration_id);
CREATE INDEX IF NOT EXISTS ix_registration_decisions_decision
    ON registration_decisions(decision);
CREATE INDEX IF NOT EXISTS ix_registration_decisions_policy_snapshot_id
    ON registration_decisions(policy_snapshot_id);

CREATE OR REPLACE FUNCTION update_source_registrations_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_source_registrations_updated_at ON source_registrations;
CREATE TRIGGER trigger_source_registrations_updated_at
    BEFORE UPDATE ON source_registrations
    FOR EACH ROW
    EXECUTE FUNCTION update_source_registrations_updated_at();

COMMIT;
