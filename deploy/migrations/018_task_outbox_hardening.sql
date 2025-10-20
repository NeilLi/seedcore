-- Task Outbox hardening: availability scheduling, attempts tracking, and index

BEGIN;

ALTER TABLE IF EXISTS task_outbox
  ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE IF EXISTS task_outbox
  ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_task_outbox_available
    ON task_outbox(available_at);

COMMIT;


