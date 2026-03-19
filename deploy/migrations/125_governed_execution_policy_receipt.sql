-- Migration 125: Persist policy_receipt with governed execution audit records

BEGIN;

ALTER TABLE governed_execution_audit
    ADD COLUMN IF NOT EXISTS policy_receipt JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS ix_governed_execution_audit_policy_receipt_gin
    ON governed_execution_audit USING GIN(policy_receipt);

COMMIT;
