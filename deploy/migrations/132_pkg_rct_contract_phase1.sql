-- 132_pkg_rct_contract_phase1.sql
-- Purpose: Phase 1 additive RCT contract surfaces (manifest/taxonomy/artifacts/state binding)

-- ===== Extend artifact enum for snapshot-scoped contract artifacts =====
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_enum e ON e.enumtypid = t.oid
    WHERE t.typname = 'pkg_artifact_type'
      AND e.enumlabel = 'decision_graph_snapshot'
  ) THEN
    ALTER TYPE pkg_artifact_type ADD VALUE 'decision_graph_snapshot';
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_enum e ON e.enumtypid = t.oid
    WHERE t.typname = 'pkg_artifact_type'
      AND e.enumlabel = 'request_schema_bundle'
  ) THEN
    ALTER TYPE pkg_artifact_type ADD VALUE 'request_schema_bundle';
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_enum e ON e.enumtypid = t.oid
    WHERE t.typname = 'pkg_artifact_type'
      AND e.enumlabel = 'taxonomy_bundle'
  ) THEN
    ALTER TYPE pkg_artifact_type ADD VALUE 'taxonomy_bundle';
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_enum e ON e.enumtypid = t.oid
    WHERE t.typname = 'pkg_artifact_type'
      AND e.enumlabel = 'activation_manifest'
  ) THEN
    ALTER TYPE pkg_artifact_type ADD VALUE 'activation_manifest';
  END IF;
END $$;

-- ===== Allow multiple artifacts per snapshot =====
ALTER TABLE pkg_snapshot_artifacts
  DROP CONSTRAINT IF EXISTS pkg_snapshot_artifacts_pkey;

ALTER TABLE pkg_snapshot_artifacts
  ADD CONSTRAINT pkg_snapshot_artifacts_pkey PRIMARY KEY (snapshot_id, artifact_type);

-- ===== Snapshot manifest =====
CREATE TABLE IF NOT EXISTS pkg_snapshot_manifests (
  snapshot_id                         INT PRIMARY KEY REFERENCES pkg_snapshots(id) ON DELETE CASCADE,
  workflow_type                       TEXT NOT NULL DEFAULT 'restricted_custody_transfer',
  decision_contract_version           TEXT,
  request_schema_version              TEXT,
  evidence_contract_version           TEXT,
  reason_code_taxonomy_version        TEXT,
  trust_gap_taxonomy_version          TEXT,
  obligation_taxonomy_version         TEXT,
  consistency_contract_version        TEXT,
  safety_profile                      TEXT,
  requires_signed_bundle              BOOLEAN NOT NULL DEFAULT FALSE,
  requires_compiled_decision_graph    BOOLEAN NOT NULL DEFAULT FALSE,
  requires_authority_state_binding    BOOLEAN NOT NULL DEFAULT FALSE,
  activation_requirements             JSONB NOT NULL DEFAULT '{}'::jsonb,
  manifest_json                       JSONB NOT NULL DEFAULT '{}'::jsonb,
  manifest_hash                       TEXT,
  created_at                          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pkg_snapshot_manifests_workflow
  ON pkg_snapshot_manifests(workflow_type);

-- ===== Taxonomy catalogs =====
CREATE TABLE IF NOT EXISTS pkg_reason_codes (
  id                  BIGSERIAL PRIMARY KEY,
  snapshot_id         INT NOT NULL REFERENCES pkg_snapshots(id) ON DELETE CASCADE,
  taxonomy_version    TEXT NOT NULL DEFAULT 'v1',
  code                TEXT NOT NULL,
  disposition_family  TEXT NOT NULL DEFAULT 'general',
  severity            TEXT NOT NULL DEFAULT 'medium',
  operator_message    TEXT NOT NULL,
  machine_category    TEXT NOT NULL DEFAULT 'general',
  metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
  deprecated          BOOLEAN NOT NULL DEFAULT FALSE,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (snapshot_id, taxonomy_version, code)
);

CREATE INDEX IF NOT EXISTS idx_pkg_reason_codes_snapshot
  ON pkg_reason_codes(snapshot_id, taxonomy_version);

CREATE TABLE IF NOT EXISTS pkg_trust_gap_codes (
  id                  BIGSERIAL PRIMARY KEY,
  snapshot_id         INT NOT NULL REFERENCES pkg_snapshots(id) ON DELETE CASCADE,
  taxonomy_version    TEXT NOT NULL DEFAULT 'v1',
  code                TEXT NOT NULL,
  disposition_family  TEXT NOT NULL DEFAULT 'quarantine',
  severity            TEXT NOT NULL DEFAULT 'medium',
  operator_message    TEXT NOT NULL,
  machine_category    TEXT NOT NULL DEFAULT 'trust_gap',
  metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
  deprecated          BOOLEAN NOT NULL DEFAULT FALSE,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (snapshot_id, taxonomy_version, code)
);

CREATE INDEX IF NOT EXISTS idx_pkg_trust_gap_codes_snapshot
  ON pkg_trust_gap_codes(snapshot_id, taxonomy_version);

CREATE TABLE IF NOT EXISTS pkg_obligation_codes (
  id                  BIGSERIAL PRIMARY KEY,
  snapshot_id         INT NOT NULL REFERENCES pkg_snapshots(id) ON DELETE CASCADE,
  taxonomy_version    TEXT NOT NULL DEFAULT 'v1',
  code                TEXT NOT NULL,
  disposition_family  TEXT NOT NULL DEFAULT 'general',
  severity            TEXT NOT NULL DEFAULT 'medium',
  operator_message    TEXT NOT NULL,
  machine_category    TEXT NOT NULL DEFAULT 'obligation',
  metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
  deprecated          BOOLEAN NOT NULL DEFAULT FALSE,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (snapshot_id, taxonomy_version, code)
);

CREATE INDEX IF NOT EXISTS idx_pkg_obligation_codes_snapshot
  ON pkg_obligation_codes(snapshot_id, taxonomy_version);

-- ===== Keep active artifact helper stable for existing callers =====
CREATE OR REPLACE VIEW pkg_active_artifact AS
SELECT DISTINCT ON (s.env, s.id)
  s.env,
  s.id AS snapshot_id,
  s.version,
  a.artifact_type,
  a.size_bytes,
  a.sha256
FROM pkg_snapshots s
JOIN pkg_snapshot_artifacts a ON a.snapshot_id = s.id
WHERE s.is_active = TRUE
  AND a.artifact_type IN ('wasm_pack', 'rego_bundle')
ORDER BY
  s.env,
  s.id,
  CASE
    WHEN a.artifact_type = 'wasm_pack' THEN 0
    ELSE 1
  END,
  a.created_at DESC;
