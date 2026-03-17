-- Migration 124: Expand tracking events for app-scoped policy/runtime telemetry
-- Purpose: Allow external apps such as pkg-simulator to persist monitoring events
-- without requiring a source_registration row.

BEGIN;

ALTER TABLE tracking_events
    ALTER COLUMN registration_id DROP NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'tracking_events'
          AND column_name = 'subject_type'
    ) THEN
        ALTER TABLE tracking_events
        ADD COLUMN subject_type TEXT NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'tracking_events'
          AND column_name = 'subject_id'
    ) THEN
        ALTER TABLE tracking_events
        ADD COLUMN subject_id TEXT NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_tracking_events_event_type'
    ) THEN
        ALTER TABLE tracking_events DROP CONSTRAINT chk_tracking_events_event_type;
    END IF;
END $$;

ALTER TABLE tracking_events
ADD CONSTRAINT chk_tracking_events_event_type
CHECK (
    event_type IN (
        'source_claim_declared',
        'provenance_scan_captured',
        'seal_check_captured',
        'environmental_reading_recorded',
        'bio_signature_recorded',
        'operator_request_received',
        'runtime_incident_detected',
        'policy_implementation_reported',
        'policy_decision_recorded'
    )
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_tracking_events_source_kind'
    ) THEN
        ALTER TABLE tracking_events DROP CONSTRAINT chk_tracking_events_source_kind;
    END IF;
END $$;

ALTER TABLE tracking_events
ADD CONSTRAINT chk_tracking_events_source_kind
CHECK (
    source_kind IN (
        'source_declaration',
        'provenance_scan',
        'telemetry',
        'operator_request',
        'system',
        'application_log',
        'policy_monitor'
    )
);

CREATE INDEX IF NOT EXISTS ix_tracking_events_subject
    ON tracking_events(subject_type, subject_id);

COMMIT;
