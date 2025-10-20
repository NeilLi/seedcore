--
-- NOTE: this migration is intentionally idempotent and stages the changes in
--       the same order you would use for a low-downtime rollout:
--         1. Ensure metadata columns + indexes exist.
--         2. Backfill/lock label semantics.
--         3. Switch uniqueness enforcement to (node_id, label).
--         4. Publish helper views for observability.
--
-- Safe to run multiple times.

-- Ensure the table exists before altering.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'graph_embeddings'
    ) THEN
        RAISE NOTICE 'graph_embeddings table does not exist – skipping upgrade.';
        RETURN;
    END IF;
END;
$$;

-- We rely on digest() to compute SHA256 hashes in helper views.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Drop legacy primary key on node_id only.
ALTER TABLE graph_embeddings
    DROP CONSTRAINT IF EXISTS graph_embeddings_pkey;

-- Backfill NULL/blank labels before making the column NOT NULL.
UPDATE graph_embeddings
   SET label = 'default'
 WHERE label IS NULL OR btrim(label) = '';

-- Ensure a deterministic default label and prevent NULLs going forward.
ALTER TABLE graph_embeddings
    ALTER COLUMN label SET DEFAULT 'default';
ALTER TABLE graph_embeddings
    ALTER COLUMN label SET NOT NULL;

-- Add metadata columns for embedding provenance / freshness.
ALTER TABLE graph_embeddings
    ADD COLUMN IF NOT EXISTS model TEXT,
    ADD COLUMN IF NOT EXISTS content_sha256 TEXT;

-- Enforce uniqueness on (node_id, label) and keep it even after promoting to
-- the primary key for clarity and query planning hints.
CREATE UNIQUE INDEX IF NOT EXISTS uq_graph_embeddings_node_label
    ON graph_embeddings (node_id, label);

-- Promote (node_id, label) to the new primary key (after the unique index is
-- in place so ON CONFLICT targets work during the transition).
ALTER TABLE graph_embeddings
    ADD CONSTRAINT graph_embeddings_pkey PRIMARY KEY (node_id, label);

-- Add supporting indexes for common query paths.
CREATE INDEX IF NOT EXISTS idx_graph_embeddings_node
    ON graph_embeddings (node_id);

CREATE INDEX IF NOT EXISTS idx_graph_embeddings_label
    ON graph_embeddings (label);

-- Helper view: tasks missing primary task embeddings.
CREATE OR REPLACE VIEW tasks_missing_embeddings AS
SELECT t.id AS task_id,
       m.node_id
  FROM tasks t
  JOIN graph_node_map m
    ON m.node_type = 'task'
   AND m.ext_table = 'tasks'
   AND m.ext_uuid = t.id
  LEFT JOIN graph_embeddings e
    ON e.node_id = m.node_id
   AND e.label = 'task.primary'
 WHERE e.node_id IS NULL;

-- Optional narrower convenience view for the primary task embedding label.
CREATE OR REPLACE VIEW task_embeddings_primary AS
SELECT t.id         AS task_id,
       m.node_id    AS node_id,
       e.emb        AS emb,
       e.model      AS model,
       e.props      AS props,
       e.content_sha256,
       e.created_at,
       e.updated_at
  FROM tasks t
  JOIN graph_node_map m
    ON m.node_type = 'task'
   AND m.ext_table = 'tasks'
   AND m.ext_uuid = t.id
  JOIN graph_embeddings e
    ON e.node_id = m.node_id
   AND e.label = 'task.primary';

-- Helper view: detect embeddings whose stored hash no longer matches the
-- current task content (allows targeted refreshes). The 16000 character limit
-- mirrors TASK_EMBED_TEXT_MAX_CHARS in the application worker.
CREATE OR REPLACE VIEW task_embeddings_stale AS
SELECT t.id AS task_id,
       m.node_id AS node_id,
       e.label,
       e.content_sha256 AS stored_sha256,
       encode(
           digest(
               convert_to(
                   left(
                       concat_ws(
                           '\n',
                           NULLIF(btrim(t.description), ''),
                           NULLIF(btrim(t.type), ''),
                           NULLIF(btrim(jsonb_pretty(t.params)), '')
                       ),
                       16000
                   ),
                   'UTF8'
               ),
               'sha256'
           ),
           'hex'
       ) AS current_sha256
  FROM tasks t
  JOIN graph_node_map m
    ON m.node_type = 'task'
   AND m.ext_table = 'tasks'
   AND m.ext_uuid = t.id
  JOIN graph_embeddings e
    ON e.node_id = m.node_id
WHERE e.label = 'task.primary'
   AND e.content_sha256 IS DISTINCT FROM encode(
           digest(
               convert_to(
                   left(
                       concat_ws(
                           '\n',
                           NULLIF(btrim(t.description), ''),
                           NULLIF(btrim(t.type), ''),
                           NULLIF(btrim(jsonb_pretty(t.params)), '')
                       ),
                       16000
                   ),
                   'UTF8'
               ),
               'sha256'
           ),
           'hex'
       );
