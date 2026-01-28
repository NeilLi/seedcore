-- 014_pkg_ops.sql
-- Purpose: canary deployments, validation/promotion audit, device coverage

-- ===== Targeted deployments (router/edge classes) =====
CREATE TABLE IF NOT EXISTS pkg_deployments (
  id           BIGSERIAL PRIMARY KEY,
  snapshot_id  INT NOT NULL REFERENCES pkg_snapshots(id) ON DELETE CASCADE,
  target       TEXT NOT NULL,                 -- e.g., 'router','edge:door','edge:robot'
  region       TEXT NOT NULL DEFAULT 'global',
  percent      INT  NOT NULL DEFAULT 100 CHECK (percent BETWEEN 0 AND 100),
  is_active    BOOLEAN NOT NULL DEFAULT TRUE,
  activated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  activated_by TEXT NOT NULL DEFAULT 'system'
);
CREATE INDEX IF NOT EXISTS idx_pkg_deploy_snapshot ON pkg_deployments(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_pkg_deploy_target   ON pkg_deployments(target, region);
-- Unique constraint prevents duplicate deployments for same target/region lane
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conname = 'uq_pkg_deploy_lane'
          AND c.conrelid = 'pkg_deployments'::regclass
    ) THEN
        ALTER TABLE pkg_deployments
        ADD CONSTRAINT uq_pkg_deploy_lane UNIQUE (target, region);
        RAISE NOTICE '✅ Added unique constraint uq_pkg_deploy_lane';
    ELSE
        RAISE NOTICE 'ℹ️  Unique constraint uq_pkg_deploy_lane already exists';
    END IF;
END $$;

-- ===== Validation fixtures & runs =====
CREATE TABLE IF NOT EXISTS pkg_validation_fixtures (
  id          BIGSERIAL PRIMARY KEY,
  snapshot_id INT NOT NULL REFERENCES pkg_snapshots(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  input       JSONB NOT NULL,     -- evaluator input
  expect      JSONB NOT NULL,     -- expected outputs/properties
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (snapshot_id, name)
);

CREATE TABLE IF NOT EXISTS pkg_validation_runs (
  id          BIGSERIAL PRIMARY KEY,
  snapshot_id INT NOT NULL REFERENCES pkg_snapshots(id) ON DELETE CASCADE,
  started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  success     BOOLEAN,
  report      JSONB
);
CREATE INDEX IF NOT EXISTS idx_pkg_valruns_snapshot ON pkg_validation_runs(snapshot_id);

-- ===== Promotion/rollback audit =====
CREATE TABLE IF NOT EXISTS pkg_promotions (
  id          BIGSERIAL PRIMARY KEY,
  snapshot_id INT NOT NULL REFERENCES pkg_snapshots(id) ON DELETE CASCADE,
  from_version TEXT,
  to_version   TEXT,
  actor        TEXT NOT NULL,
  action       TEXT NOT NULL, -- 'promote' | 'rollback'
  reason       TEXT,
  metrics      JSONB,         -- eval p95, validation summary
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  success      BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_pkg_promotions_snapshot ON pkg_promotions(snapshot_id);

-- ===== Device version heartbeat (edge telemetry) =====
CREATE TABLE IF NOT EXISTS pkg_device_versions (
  device_id   TEXT PRIMARY KEY,                 -- e.g., 'door:D-1510'
  device_type TEXT NOT NULL,                    -- 'door'|'robot'|'shuttle'|...
  region      TEXT NOT NULL DEFAULT 'global',
  snapshot_id INT REFERENCES pkg_snapshots(id) ON DELETE SET NULL,
  version     TEXT,
  last_seen   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pkg_device_type_region ON pkg_device_versions(device_type, region);

-- ===== Rollout events audit (canary control history) =====
CREATE TABLE IF NOT EXISTS pkg_rollout_events (
  id            BIGSERIAL PRIMARY KEY,
  target        TEXT NOT NULL,
  region        TEXT NOT NULL DEFAULT 'global',
  snapshot_id   INT NOT NULL REFERENCES pkg_snapshots(id) ON DELETE CASCADE,
  from_percent  INT,
  to_percent    INT NOT NULL,
  is_rollback   BOOLEAN NOT NULL DEFAULT FALSE,
  actor         TEXT NOT NULL DEFAULT 'system',
  validation_run_id BIGINT REFERENCES pkg_validation_runs(id) ON DELETE SET NULL,
  reason        TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rollout_events_lane ON pkg_rollout_events(target, region, created_at DESC);

-- ===== Guest Capabilities (Temporal Overlay Layer) =====
-- This table provides guest-specific persona overlays on top of system-level pkg_subtask_types.
-- Acts as a Dynamic Overlay: when Router looks for a specialization, it checks guest_capabilities
-- first (if guest_id is present) before falling back to system-level pkg_subtask_types.
--
-- Architecture Benefits:
-- 1. Prevents configuration drift in system tables (pkg_subtask_types remains immutable)
-- 2. Enables automatic cleanup via temporal bounds (valid_from/valid_to)
-- 3. Respects SeedCore v2.5 Isolation Rule: upstream components don't modify system core
-- 4. Supports multi-tenant/hospitality robotics scenarios
CREATE TABLE IF NOT EXISTS guest_capabilities (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    guest_id            UUID NOT NULL,                     -- Guest UUID identifier
    base_subtask_type_id UUID REFERENCES pkg_subtask_types(id) ON DELETE CASCADE,
    persona_name        TEXT NOT NULL,                    -- e.g., "Mimi", "Reachy Companion"
    custom_params       JSONB NOT NULL DEFAULT '{}'::JSONB, -- Personality/Behavior overrides
    valid_from          TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to            TIMESTAMPTZ NOT NULL,            -- Set to guest checkout time
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    -- Ensure valid_from <= valid_to
    CONSTRAINT chk_guest_cap_validity CHECK (valid_from <= valid_to)
);

CREATE INDEX IF NOT EXISTS idx_guest_capabilities_guest ON guest_capabilities(guest_id);
CREATE INDEX IF NOT EXISTS idx_guest_capabilities_validity ON guest_capabilities(valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_guest_capabilities_base_type ON guest_capabilities(base_subtask_type_id);
CREATE INDEX IF NOT EXISTS idx_guest_capabilities_persona ON guest_capabilities(persona_name);

-- Unique constraint for upsert behavior: one capability per (guest_id, persona_name, valid_from)
-- This is required for the ON CONFLICT clause in upsert_guest_capability()
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes 
        WHERE tablename = 'guest_capabilities' 
          AND indexname = 'ux_guest_capabilities_guest_persona_time'
    ) THEN
        CREATE UNIQUE INDEX ux_guest_capabilities_guest_persona_time
            ON guest_capabilities(guest_id, persona_name, valid_from);
        RAISE NOTICE '✅ Created unique index ux_guest_capabilities_guest_persona_time';
    ELSE
        RAISE NOTICE 'ℹ️  Unique index ux_guest_capabilities_guest_persona_time already exists';
    END IF;
END $$;

-- Composite index for guest capability lookups (most common query pattern)
-- Note: Temporal validity checks (valid_from <= now() AND valid_to > now()) 
-- are performed in query WHERE clauses, not in index predicates, since now() 
-- is not IMMUTABLE and cannot be used in index predicates.
CREATE INDEX IF NOT EXISTS idx_guest_capabilities_active 
    ON guest_capabilities(guest_id, valid_from, valid_to);

COMMENT ON TABLE guest_capabilities IS 
    'Guest-level temporal capability overlays. System checks this layer first before falling back to pkg_subtask_types.';
COMMENT ON COLUMN guest_capabilities.base_subtask_type_id IS 
    'Reference to system-level capability (hardware limits, base behaviors)';
COMMENT ON COLUMN guest_capabilities.custom_params IS 
    'Personality/behavior overrides (Energy, Humor, Warmth sliders) merged with base params';
COMMENT ON COLUMN guest_capabilities.valid_from IS 
    'When this guest capability becomes active (default: now)';
COMMENT ON COLUMN guest_capabilities.valid_to IS 
    'When this guest capability expires (typically guest checkout time). Janitor Agent can clean up expired entries.';
