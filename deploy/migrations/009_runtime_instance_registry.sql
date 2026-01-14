-- migrations/009_runtime_instance_registry.sql
BEGIN;

-- Single-row cluster metadata with updated_at
CREATE TABLE IF NOT EXISTS cluster_metadata (
  id            INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  current_epoch UUID NOT NULL,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Instance status as enum for safety
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'instancestatus') THEN
    CREATE TYPE InstanceStatus AS ENUM ('starting', 'alive', 'draining', 'dead');
  END IF;
END$$;

CREATE TABLE IF NOT EXISTS registry_instance (
  instance_id    UUID PRIMARY KEY,
  logical_id     TEXT NOT NULL,     -- e.g. 'cognitive_organ_1'
  cluster_epoch  UUID NOT NULL,
  status         InstanceStatus NOT NULL DEFAULT 'starting',
  actor_name     TEXT,              -- for named actors
  serve_route    TEXT,              -- for Serve/http (deployment name or base route)
  node_id        TEXT,
  ip_address     INET,
  pid            INT,
  started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  stopped_at     TIMESTAMPTZ,
  last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_instance_logical_id         ON registry_instance(logical_id);
CREATE INDEX IF NOT EXISTS idx_instance_epoch_status       ON registry_instance(cluster_epoch, status);
CREATE INDEX IF NOT EXISTS idx_instance_status_heartbeat   ON registry_instance(status, last_heartbeat DESC);
CREATE INDEX IF NOT EXISTS idx_instance_logical_status     ON registry_instance(logical_id, status, cluster_epoch);

-- All alive replicas for monitoring
CREATE OR REPLACE VIEW active_instances AS
SELECT ri.*
FROM registry_instance ri
JOIN cluster_metadata cm ON ri.cluster_epoch = cm.current_epoch
WHERE ri.status = 'alive'
  AND ri.last_heartbeat > (now() - INTERVAL '15 seconds');

-- One best instance per logical_id (useful for named actors)
CREATE OR REPLACE VIEW active_instance AS
SELECT DISTINCT ON (ri.logical_id)
  ri.*
FROM registry_instance ri
JOIN cluster_metadata cm ON ri.cluster_epoch = cm.current_epoch
WHERE ri.status = 'alive'
  AND ri.last_heartbeat > (now() - INTERVAL '15 seconds')
ORDER BY ri.logical_id, ri.last_heartbeat DESC, ri.started_at ASC, ri.instance_id ASC;

COMMIT;

