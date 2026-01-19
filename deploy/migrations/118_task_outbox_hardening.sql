-- Task Outbox hardening: availability scheduling, attempts tracking, and indexes
-- This migration is self-sufficient - it will create the table if it doesn't exist,
-- then apply hardening improvements (scheduling, retry tracking, constraints, indexes).

BEGIN;

-- Create task_outbox table if it doesn't exist
CREATE TABLE IF NOT EXISTS task_outbox (
  id           BIGSERIAL PRIMARY KEY,
  task_id      UUID NOT NULL,
  event_type   TEXT NOT NULL,
  payload      JSONB NOT NULL,
  dedupe_key   TEXT,                                -- for exactly-once semantics
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (dedupe_key)
);

-- Trigger to keep updated_at fresh
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := NOW();
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_task_outbox_updated_at ON task_outbox;
CREATE TRIGGER trg_task_outbox_updated_at
BEFORE UPDATE ON task_outbox
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- Hardening: Add scheduling column for backoff/delayed processing
ALTER TABLE task_outbox
  ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Hardening: Add retry counter for exponential backoff and dead-letter logic
ALTER TABLE task_outbox
  ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;

-- Hardening: Ensure attempts cannot be negative
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint c
    WHERE c.conname = 'task_outbox_attempts_nonneg'
      AND c.conrelid = 'task_outbox'::regclass
  ) THEN
    ALTER TABLE task_outbox
      ADD CONSTRAINT task_outbox_attempts_nonneg CHECK (attempts >= 0);
  END IF;
END$$;

-- Index for efficient picking of ready rows (FOR UPDATE SKIP LOCKED queries)
CREATE INDEX IF NOT EXISTS idx_task_outbox_available
  ON task_outbox(available_at);

-- Index for routing different outbox topics
CREATE INDEX IF NOT EXISTS idx_task_outbox_event_type
  ON task_outbox(event_type);

-- Index for task_id lookups
CREATE INDEX IF NOT EXISTS idx_task_outbox_task_id
  ON task_outbox(task_id);

-- Comments for documentation
COMMENT ON TABLE task_outbox IS 'Transactional outbox pattern for reliable event publishing';
COMMENT ON COLUMN task_outbox.available_at IS 'When the event becomes available for processing (enables backoff/scheduling)';
COMMENT ON COLUMN task_outbox.attempts IS 'Number of delivery attempts (for exponential backoff and dead-letter logic)';
COMMENT ON COLUMN task_outbox.dedupe_key IS 'Optional deduplication key for exactly-once semantics';
COMMENT ON COLUMN task_outbox.event_type IS 'Event type for routing (e.g., task.created, task.completed)';

COMMIT;


