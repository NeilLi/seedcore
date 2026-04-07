-- 133_result_verifier.sql
-- Durable RESULT_VERIFIER job queue and immutable outcome audit rows (Coordinator-embedded runtime).

BEGIN;

CREATE TABLE IF NOT EXISTS result_verifier_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_journal_id UUID NOT NULL REFERENCES digital_twin_event_journal(id) ON DELETE CASCADE,
    task_id UUID NULL REFERENCES tasks(id) ON DELETE SET NULL,
    intent_id VARCHAR(128) NULL,
    asset_id VARCHAR(256) NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    attempt_count INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error_code VARCHAR(128) NULL,
    last_error_detail TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_result_verifier_jobs_event_journal UNIQUE (event_journal_id)
);

CREATE INDEX IF NOT EXISTS ix_result_verifier_jobs_status_next_attempt
    ON result_verifier_jobs(status, next_attempt_at);

CREATE INDEX IF NOT EXISTS ix_result_verifier_jobs_task_id
    ON result_verifier_jobs(task_id);

CREATE TABLE IF NOT EXISTS result_verifier_outcomes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES result_verifier_jobs(id) ON DELETE CASCADE,
    event_journal_id UUID NOT NULL,
    verified BOOLEAN NOT NULL,
    failure_code VARCHAR(256) NULL,
    failure_class VARCHAR(32) NULL,
    twin_event_type VARCHAR(64) NULL,
    asset_id VARCHAR(256) NULL,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    artifact_results JSONB NOT NULL DEFAULT '{}'::jsonb,
    issues JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_result_verifier_outcomes_job_id
    ON result_verifier_outcomes(job_id);

CREATE INDEX IF NOT EXISTS ix_result_verifier_outcomes_event_journal_id
    ON result_verifier_outcomes(event_journal_id);

COMMIT;
