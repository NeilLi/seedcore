-- Repair transfer approval runtime tables created before migration 130 was
-- included in the direct host bootstrap path. Re-running 130 is not enough on
-- already-existing tables because CREATE TABLE IF NOT EXISTS does not backfill
-- column defaults.

ALTER TABLE IF EXISTS transfer_approval_envelopes
  ALTER COLUMN id SET DEFAULT gen_random_uuid();

ALTER TABLE IF EXISTS transfer_approval_transition_events
  ALTER COLUMN id SET DEFAULT gen_random_uuid();
