CREATE TABLE IF NOT EXISTS transfer_approval_envelopes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_envelope_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    workflow_type TEXT NOT NULL,
    status TEXT NOT NULL,
    asset_ref TEXT NOT NULL,
    lot_id TEXT NULL,
    policy_snapshot_ref TEXT NULL,
    approval_binding_hash TEXT NULL,
    envelope_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NULL,
    superseded_by_version INTEGER NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_transfer_approval_envelopes_envelope_version
    ON transfer_approval_envelopes (approval_envelope_id, version);

CREATE UNIQUE INDEX IF NOT EXISTS ux_transfer_approval_envelopes_current
    ON transfer_approval_envelopes (approval_envelope_id)
    WHERE is_current = TRUE;

CREATE INDEX IF NOT EXISTS ix_transfer_approval_envelopes_envelope_id
    ON transfer_approval_envelopes (approval_envelope_id);

CREATE INDEX IF NOT EXISTS ix_transfer_approval_envelopes_asset_ref
    ON transfer_approval_envelopes (asset_ref);

CREATE INDEX IF NOT EXISTS ix_transfer_approval_envelopes_status
    ON transfer_approval_envelopes (status);


CREATE TABLE IF NOT EXISTS transfer_approval_transition_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_envelope_id TEXT NOT NULL,
    envelope_version INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    previous_event_hash TEXT NULL,
    previous_status TEXT NULL,
    next_status TEXT NULL,
    actor_ref TEXT NULL,
    transition_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    transition_event JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_transfer_approval_transition_events_event_id
    ON transfer_approval_transition_events (event_id);

CREATE INDEX IF NOT EXISTS ix_transfer_approval_transition_events_envelope_id
    ON transfer_approval_transition_events (approval_envelope_id);

CREATE INDEX IF NOT EXISTS ix_transfer_approval_transition_events_event_hash
    ON transfer_approval_transition_events (event_hash);
