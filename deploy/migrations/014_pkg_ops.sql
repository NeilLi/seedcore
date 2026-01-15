-- 014_pkg_ops.sql
-- Purpose: canary deployments, temporal facts, validation/promotion audit, device coverage

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
ALTER TABLE pkg_deployments
ADD CONSTRAINT uq_pkg_deploy_lane UNIQUE (target, region);

-- ===== Temporal policy facts (e.g., temporary access) =====
CREATE TABLE IF NOT EXISTS pkg_facts (
  id          BIGSERIAL PRIMARY KEY,
  snapshot_id INT REFERENCES pkg_snapshots(id) ON DELETE CASCADE,
  namespace   TEXT NOT NULL DEFAULT 'default',
  subject     TEXT NOT NULL,                   -- e.g., 'guest:Ben'
  predicate   TEXT NOT NULL,                   -- e.g., 'hasTemporaryAccess'
  object      JSONB NOT NULL,                  -- e.g., {"service":"lounge"}
  valid_from  TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_to    TIMESTAMPTZ,                     -- NULL = indefinite
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by  TEXT NOT NULL DEFAULT 'system'
);
CREATE INDEX IF NOT EXISTS idx_pkg_facts_subject   ON pkg_facts(subject);
CREATE INDEX IF NOT EXISTS idx_pkg_facts_predicate ON pkg_facts(predicate);
CREATE INDEX IF NOT EXISTS idx_pkg_facts_window    ON pkg_facts(valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_pkg_facts_snapshot  ON pkg_facts(snapshot_id);

-- (Optional) Partition hint:
-- -- ALTER TABLE pkg_facts PARTITION BY RANGE (valid_from);

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
