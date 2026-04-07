-- 134_result_verifier_runtime_state.sql
-- Durable RESULT_VERIFIER intake watermark state.

BEGIN;

CREATE TABLE IF NOT EXISTS result_verifier_runtime_state (
    stream_key VARCHAR(64) PRIMARY KEY,
    watermark_recorded_at TIMESTAMPTZ NOT NULL,
    watermark_event_id UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
