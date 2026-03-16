-- Migration 124: Durable append-only governed execution audit trail

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS governed_execution_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    record_type TEXT NOT NULL,
    intent_id TEXT NOT NULL,
    token_id TEXT NULL,
    policy_snapshot TEXT NULL,
    policy_decision JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_intent JSONB NOT NULL DEFAULT '{}'::jsonb,
    policy_case JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_bundle JSONB NULL,
    actor_agent_id TEXT NULL,
    actor_organ_id TEXT NULL,
    input_hash TEXT NULL,
    evidence_hash TEXT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_governed_execution_audit_record_type'
    ) THEN
        ALTER TABLE governed_execution_audit
        ADD CONSTRAINT chk_governed_execution_audit_record_type
        CHECK (record_type IN ('policy_decision', 'execution_receipt'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_governed_execution_audit_task_id
    ON governed_execution_audit(task_id);
CREATE INDEX IF NOT EXISTS ix_governed_execution_audit_intent_id
    ON governed_execution_audit(intent_id);
CREATE INDEX IF NOT EXISTS ix_governed_execution_audit_token_id
    ON governed_execution_audit(token_id);
CREATE INDEX IF NOT EXISTS ix_governed_execution_audit_record_type
    ON governed_execution_audit(record_type);
CREATE INDEX IF NOT EXISTS ix_governed_execution_audit_recorded_at_desc
    ON governed_execution_audit(recorded_at DESC);
CREATE INDEX IF NOT EXISTS ix_governed_execution_audit_policy_decision_gin
    ON governed_execution_audit USING GIN(policy_decision);
CREATE INDEX IF NOT EXISTS ix_governed_execution_audit_action_intent_gin
    ON governed_execution_audit USING GIN(action_intent);
CREATE INDEX IF NOT EXISTS ix_governed_execution_audit_policy_case_gin
    ON governed_execution_audit USING GIN(policy_case);

COMMIT;
