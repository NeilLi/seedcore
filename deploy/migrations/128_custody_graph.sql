-- Migration 128: custody graph projection, lineage chain, and dispute workflow tables

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS custody_graph_node (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id VARCHAR(255) NOT NULL,
    node_kind VARCHAR(64) NOT NULL,
    subject_id VARCHAR(255) NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_custody_graph_node_node_id'
    ) THEN
        ALTER TABLE custody_graph_node
        ADD CONSTRAINT uq_custody_graph_node_node_id UNIQUE (node_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_custody_graph_node_kind
    ON custody_graph_node(node_kind);
CREATE INDEX IF NOT EXISTS ix_custody_graph_node_subject_id
    ON custody_graph_node(subject_id);

CREATE TABLE IF NOT EXISTS custody_graph_edge (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    edge_id VARCHAR(255) NOT NULL,
    edge_kind VARCHAR(64) NOT NULL,
    from_node_id VARCHAR(255) NOT NULL,
    to_node_id VARCHAR(255) NOT NULL,
    source_ref VARCHAR(255) NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_custody_graph_edge_edge_id'
    ) THEN
        ALTER TABLE custody_graph_edge
        ADD CONSTRAINT uq_custody_graph_edge_edge_id UNIQUE (edge_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_custody_graph_edge_kind
    ON custody_graph_edge(edge_kind);
CREATE INDEX IF NOT EXISTS ix_custody_graph_edge_from_node_id
    ON custody_graph_edge(from_node_id);
CREATE INDEX IF NOT EXISTS ix_custody_graph_edge_to_node_id
    ON custody_graph_edge(to_node_id);
CREATE INDEX IF NOT EXISTS ix_custody_graph_edge_recorded_at
    ON custody_graph_edge(recorded_at);

CREATE TABLE IF NOT EXISTS custody_transition_event (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transition_event_id VARCHAR(255) NOT NULL,
    asset_id VARCHAR(128) NOT NULL,
    intent_id VARCHAR(128) NULL,
    task_id UUID NULL REFERENCES tasks(id) ON DELETE SET NULL,
    token_id VARCHAR(128) NULL,
    authority_source VARCHAR(64) NOT NULL DEFAULT 'unknown',
    transition_seq INTEGER NOT NULL DEFAULT 0,
    from_zone VARCHAR(128) NULL,
    to_zone VARCHAR(128) NULL,
    actor_agent_id VARCHAR(128) NULL,
    actor_organ_id VARCHAR(128) NULL,
    endpoint_id VARCHAR(255) NULL,
    receipt_hash VARCHAR(128) NULL,
    receipt_nonce VARCHAR(128) NULL,
    previous_transition_event_id VARCHAR(255) NULL,
    previous_receipt_hash VARCHAR(128) NULL,
    evidence_bundle_id VARCHAR(255) NULL,
    policy_receipt_id VARCHAR(255) NULL,
    transition_receipt_id VARCHAR(255) NULL,
    lineage_status VARCHAR(64) NOT NULL DEFAULT 'authoritative',
    source_registration_id VARCHAR(128) NULL,
    audit_record_id VARCHAR(255) NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_custody_transition_event_transition_event_id'
    ) THEN
        ALTER TABLE custody_transition_event
        ADD CONSTRAINT uq_custody_transition_event_transition_event_id UNIQUE (transition_event_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_custody_transition_event_transition_seq_nonneg'
    ) THEN
        ALTER TABLE custody_transition_event
        ADD CONSTRAINT ck_custody_transition_event_transition_seq_nonneg
        CHECK (transition_seq >= 0);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_custody_transition_event_asset_id
    ON custody_transition_event(asset_id);
CREATE INDEX IF NOT EXISTS ix_custody_transition_event_intent_id
    ON custody_transition_event(intent_id);
CREATE INDEX IF NOT EXISTS ix_custody_transition_event_task_id
    ON custody_transition_event(task_id);
CREATE INDEX IF NOT EXISTS ix_custody_transition_event_token_id
    ON custody_transition_event(token_id);
CREATE INDEX IF NOT EXISTS ix_custody_transition_event_asset_seq
    ON custody_transition_event(asset_id, transition_seq);
CREATE INDEX IF NOT EXISTS ix_custody_transition_event_recorded_at
    ON custody_transition_event(recorded_at);

CREATE TABLE IF NOT EXISTS custody_dispute_case (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dispute_id VARCHAR(255) NOT NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'OPEN',
    asset_id VARCHAR(128) NULL,
    title VARCHAR(255) NOT NULL,
    summary TEXT NULL,
    opened_by VARCHAR(128) NULL,
    resolved_by VARCHAR(128) NULL,
    resolution TEXT NULL,
    reference_map JSONB NOT NULL DEFAULT '{}'::jsonb,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ NULL
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_custody_dispute_case_dispute_id'
    ) THEN
        ALTER TABLE custody_dispute_case
        ADD CONSTRAINT uq_custody_dispute_case_dispute_id UNIQUE (dispute_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_custody_dispute_case_status'
    ) THEN
        ALTER TABLE custody_dispute_case
        ADD CONSTRAINT ck_custody_dispute_case_status
        CHECK (status IN ('OPEN', 'UNDER_REVIEW', 'RESOLVED', 'REJECTED'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_custody_dispute_case_asset_id
    ON custody_dispute_case(asset_id);
CREATE INDEX IF NOT EXISTS ix_custody_dispute_case_status
    ON custody_dispute_case(status);
CREATE INDEX IF NOT EXISTS ix_custody_dispute_case_recorded_at
    ON custody_dispute_case(recorded_at);

CREATE TABLE IF NOT EXISTS custody_dispute_event (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dispute_case_id UUID NOT NULL REFERENCES custody_dispute_case(id) ON DELETE CASCADE,
    dispute_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    status VARCHAR(64) NULL,
    actor_id VARCHAR(128) NULL,
    note TEXT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_custody_dispute_event_status'
    ) THEN
        ALTER TABLE custody_dispute_event
        ADD CONSTRAINT ck_custody_dispute_event_status
        CHECK (status IS NULL OR status IN ('OPEN', 'UNDER_REVIEW', 'RESOLVED', 'REJECTED'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_custody_dispute_event_signature'
    ) THEN
        ALTER TABLE custody_dispute_event
        ADD CONSTRAINT uq_custody_dispute_event_signature
        UNIQUE (dispute_id, event_type, recorded_at);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_custody_dispute_event_dispute_id
    ON custody_dispute_event(dispute_id);
CREATE INDEX IF NOT EXISTS ix_custody_dispute_event_recorded_at
    ON custody_dispute_event(recorded_at);

COMMIT;
