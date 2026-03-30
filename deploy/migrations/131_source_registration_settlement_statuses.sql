-- Migration 131: Source Registration Settlement Statuses
-- Purpose: Allow post-approval settlement states for governed custody handoffs.

BEGIN;

ALTER TABLE source_registrations
    DROP CONSTRAINT IF EXISTS chk_source_registrations_status;

ALTER TABLE source_registrations
    ADD CONSTRAINT chk_source_registrations_status
    CHECK (
        status IN (
            'draft',
            'ingesting',
            'verifying',
            'approved',
            'pending_settlement',
            'settled',
            'quarantined',
            'rejected'
        )
    );

COMMIT;
