-- Migration 126: Persistent digital twin state + append-only twin history

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS digital_twin_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_type VARCHAR(64) NOT NULL,
    twin_id VARCHAR(128) NOT NULL,
    state_version INTEGER NOT NULL DEFAULT 1,
    authority_source VARCHAR(64) NOT NULL DEFAULT 'unknown',
    snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_task_id UUID NULL REFERENCES tasks(id) ON DELETE SET NULL,
    last_intent_id VARCHAR(128) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_digital_twin_state_type_id UNIQUE (twin_type, twin_id),
    CONSTRAINT ck_digital_twin_state_version_positive CHECK (state_version >= 1)
);

CREATE INDEX IF NOT EXISTS ix_digital_twin_state_twin_type
    ON digital_twin_state(twin_type);
CREATE INDEX IF NOT EXISTS ix_digital_twin_state_twin_id
    ON digital_twin_state(twin_id);
CREATE INDEX IF NOT EXISTS ix_digital_twin_state_updated_at
    ON digital_twin_state(updated_at);

CREATE TABLE IF NOT EXISTS digital_twin_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_state_id UUID NOT NULL REFERENCES digital_twin_state(id) ON DELETE CASCADE,
    twin_type VARCHAR(64) NOT NULL,
    twin_id VARCHAR(128) NOT NULL,
    state_version INTEGER NOT NULL,
    authority_source VARCHAR(64) NOT NULL,
    snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    change_reason VARCHAR(128) NULL,
    source_task_id UUID NULL REFERENCES tasks(id) ON DELETE SET NULL,
    source_intent_id VARCHAR(128) NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_digital_twin_history_state_version UNIQUE (twin_state_id, state_version),
    CONSTRAINT ck_digital_twin_history_version_positive CHECK (state_version >= 1)
);

CREATE INDEX IF NOT EXISTS ix_digital_twin_history_twin_type_id
    ON digital_twin_history(twin_type, twin_id);
CREATE INDEX IF NOT EXISTS ix_digital_twin_history_recorded_at
    ON digital_twin_history(recorded_at);

COMMIT;
