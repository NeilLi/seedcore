-- 136_nfc_monotonic_counters.sql
-- Persistent ledger for dynamic NFC monotonic counters.

BEGIN;

CREATE TABLE IF NOT EXISTS nfc_monotonic_counters (
    nfc_uid_hash VARCHAR(128) NOT NULL,
    anchor_profile_ref VARCHAR(255) NOT NULL,
    highest_scan_counter INT NOT NULL DEFAULT -1,
    last_observed_at TIMESTAMPTZ NOT NULL,
    last_workflow_join_key VARCHAR(255) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (nfc_uid_hash, anchor_profile_ref),
    CHECK (highest_scan_counter >= -1)
);

COMMIT;
