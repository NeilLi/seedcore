-- Migration 127: append-only normalized twin event journal

BEGIN;

CREATE TABLE IF NOT EXISTS digital_twin_event_journal (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_type VARCHAR(64) NOT NULL,
    twin_id VARCHAR(128) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    revision_stage VARCHAR(32) NOT NULL,
    lifecycle_state VARCHAR(64) NULL,
    task_id UUID NULL REFERENCES tasks(id) ON DELETE SET NULL,
    intent_id VARCHAR(128) NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_digital_twin_event_journal_twin_type_id
    ON digital_twin_event_journal(twin_type, twin_id);

CREATE INDEX IF NOT EXISTS ix_digital_twin_event_journal_event_type
    ON digital_twin_event_journal(event_type);

CREATE INDEX IF NOT EXISTS ix_digital_twin_event_journal_recorded_at
    ON digital_twin_event_journal(recorded_at);

COMMIT;
