-- Migration 123: Tracking Events for Source Registration
-- Purpose: Add append-only governed event ingress and projection traceability

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS tracking_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    registration_id UUID NOT NULL REFERENCES source_registrations(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    sha256 TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    producer_id TEXT NULL,
    device_id TEXT NULL,
    operator_id TEXT NULL,
    correlation_id TEXT NULL,
    snapshot_id INTEGER NULL,
    projected_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_tracking_events_event_type'
    ) THEN
        ALTER TABLE tracking_events
        ADD CONSTRAINT chk_tracking_events_event_type
        CHECK (
            event_type IN (
                'source_claim_declared',
                'provenance_scan_captured',
                'seal_check_captured',
                'environmental_reading_recorded',
                'bio_signature_recorded',
                'operator_request_received'
            )
        );
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_tracking_events_source_kind'
    ) THEN
        ALTER TABLE tracking_events
        ADD CONSTRAINT chk_tracking_events_source_kind
        CHECK (
            source_kind IN (
                'source_declaration',
                'provenance_scan',
                'telemetry',
                'operator_request',
                'system'
            )
        );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_tracking_events_registration_id
    ON tracking_events(registration_id);
CREATE INDEX IF NOT EXISTS ix_tracking_events_event_type
    ON tracking_events(event_type);
CREATE INDEX IF NOT EXISTS ix_tracking_events_captured_at
    ON tracking_events(captured_at);
CREATE INDEX IF NOT EXISTS ix_tracking_events_registration_captured_at
    ON tracking_events(registration_id, captured_at);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'source_registration_artifacts'
          AND column_name = 'source_event_id'
    ) THEN
        ALTER TABLE source_registration_artifacts
        ADD COLUMN source_event_id UUID NULL REFERENCES tracking_events(id) ON DELETE SET NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'source_registration_measurements'
          AND column_name = 'source_event_id'
    ) THEN
        ALTER TABLE source_registration_measurements
        ADD COLUMN source_event_id UUID NULL REFERENCES tracking_events(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_source_registration_artifacts_source_event_id
    ON source_registration_artifacts(source_event_id);
CREATE INDEX IF NOT EXISTS ix_source_registration_measurements_source_event_id
    ON source_registration_measurements(source_event_id);

COMMIT;
