-- 013_pkg_core.sql
-- Purpose: PKG core catalog (snapshots, rules, conditions, emissions) + artifacts

-- ===== Enums (idempotent) =====
DO $$ BEGIN
  CREATE TYPE pkg_env AS ENUM ('prod','staging','dev');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE pkg_engine AS ENUM ('wasm','native');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE pkg_condition_type AS ENUM ('TAG','SIGNAL','VALUE','FACT');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE pkg_operator AS ENUM ('=','!=','>=','<=','>','<','EXISTS','IN','MATCHES');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE pkg_relation AS ENUM ('EMITS','ORDERS','GATE');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE pkg_artifact_type AS ENUM ('rego_bundle','wasm_pack');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ===== Snapshots =====
CREATE TABLE IF NOT EXISTS pkg_snapshots (
  id              SERIAL PRIMARY KEY,
  version         TEXT NOT NULL UNIQUE,
  env             pkg_env NOT NULL DEFAULT 'prod',
  entrypoint      TEXT DEFAULT 'data.pkg',                -- OPA/Rego entrypoint
  schema_version  TEXT DEFAULT '1',
  checksum        TEXT NOT NULL CHECK (length(checksum)=64), -- hex sha256
  size_bytes      BIGINT,
  signature       TEXT,                                   -- optional Ed25519/PGP
  is_active       BOOLEAN NOT NULL DEFAULT FALSE,
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE pkg_snapshots IS 'Versioned policy snapshots (governance root)';

-- Only one active snapshot per env
CREATE UNIQUE INDEX IF NOT EXISTS ux_pkg_active_per_env
  ON pkg_snapshots (env) WHERE is_active = TRUE;

-- ===== Subtask types =====
CREATE TABLE IF NOT EXISTS pkg_subtask_types (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  snapshot_id    INT NOT NULL REFERENCES pkg_snapshots(id) ON DELETE CASCADE,
  name           TEXT NOT NULL,
  default_params JSONB,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pkg_subtask_name_snapshot
  ON pkg_subtask_types (snapshot_id, name);

-- ===== Rules =====
CREATE TABLE IF NOT EXISTS pkg_policy_rules (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  snapshot_id   INT NOT NULL REFERENCES pkg_snapshots(id) ON DELETE CASCADE,
  rule_name     TEXT NOT NULL,
  priority      INT NOT NULL DEFAULT 100,
  rule_source   TEXT NOT NULL,                -- YAML/Datalog/Rego
  compiled_rule TEXT,                         -- optional compiled form
  engine        pkg_engine NOT NULL DEFAULT 'wasm',
  rule_hash     TEXT,                         -- hash of rule_source (optional)
  metadata      JSONB,
  disabled      BOOLEAN NOT NULL DEFAULT FALSE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pkg_rules_snapshot ON pkg_policy_rules(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_pkg_rules_name     ON pkg_policy_rules(rule_name);

-- ===== Rule conditions =====
CREATE TABLE IF NOT EXISTS pkg_rule_conditions (
  rule_id        UUID NOT NULL REFERENCES pkg_policy_rules(id) ON DELETE CASCADE,
  condition_type pkg_condition_type NOT NULL,      -- TAG | SIGNAL | VALUE | FACT
  condition_key  TEXT NOT NULL,                    -- e.g., vip, x6, subject
  operator       pkg_operator NOT NULL DEFAULT 'EXISTS',
  value          TEXT,
  position       INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pkg_conditions_rule ON pkg_rule_conditions(rule_id);
CREATE INDEX IF NOT EXISTS idx_pkg_conditions_key  ON pkg_rule_conditions(condition_key, operator);

-- ===== Rule emissions =====
CREATE TABLE IF NOT EXISTS pkg_rule_emissions (
  rule_id           UUID NOT NULL REFERENCES pkg_policy_rules(id) ON DELETE CASCADE,
  subtask_type_id   UUID NOT NULL REFERENCES pkg_subtask_types(id) ON DELETE CASCADE,
  relationship_type pkg_relation NOT NULL DEFAULT 'EMITS',
  params            JSONB,
  position          INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pkg_emissions_rule    ON pkg_rule_emissions(rule_id);
CREATE INDEX IF NOT EXISTS idx_pkg_emissions_subtask ON pkg_rule_emissions(subtask_type_id);

-- ===== Artifacts (WASM/Rego) =====
CREATE TABLE IF NOT EXISTS pkg_snapshot_artifacts (
  snapshot_id    INT PRIMARY KEY REFERENCES pkg_snapshots(id) ON DELETE CASCADE,
  artifact_type  pkg_artifact_type NOT NULL,
  artifact_bytes BYTEA NOT NULL,
  size_bytes     BIGINT GENERATED ALWAYS AS (octet_length(artifact_bytes)) STORED,
  sha256         TEXT NOT NULL CHECK (length(sha256)=64),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by     TEXT NOT NULL DEFAULT 'system'
);
CREATE INDEX IF NOT EXISTS idx_pkg_artifacts_type ON pkg_snapshot_artifacts(artifact_type);
