-- Migration 129: phase-a receipt counter persistence for custody replay protection

BEGIN;

ALTER TABLE asset_custody_state
    ADD COLUMN IF NOT EXISTS last_receipt_counter INTEGER NULL;

ALTER TABLE custody_transition_event
    ADD COLUMN IF NOT EXISTS receipt_counter INTEGER NULL;

CREATE INDEX IF NOT EXISTS ix_custody_transition_event_asset_counter
    ON custody_transition_event(asset_id, receipt_counter);

COMMIT;
