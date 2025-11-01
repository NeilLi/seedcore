-- fix_1024_vector.sql
-- Hard reset graph_embeddings.emb to vector(1024)
-- Recreate dependent views.

-- 1. Safety: ensure table exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema='public' AND table_name='graph_embeddings'
    ) THEN
        RAISE EXCEPTION 'graph_embeddings does not exist in this DB. Are you on the right Postgres?';
    END IF;
END;
$$;

-- 2. Drop dependent views that reference graph_embeddings.emb
DROP VIEW IF EXISTS task_embeddings_stale;
DROP VIEW IF EXISTS task_embeddings_primary;
DROP VIEW IF EXISTS tasks_missing_embeddings;
DROP VIEW IF EXISTS task_embeddings;  -- if you have this legacy view

-- 3. Drop ANN index on emb (if it exists)
DROP INDEX IF EXISTS idx_graph_embeddings_emb;

-- 4. Drop and recreate the emb column with 1024 dims
ALTER TABLE graph_embeddings
    DROP COLUMN IF EXISTS emb;

ALTER TABLE graph_embeddings
    ADD COLUMN emb vector(1024);

-- 5. Recreate ANN index for pgvector on the new emb column
-- tune lists=100 as before (can adjust later based on table size)
CREATE INDEX idx_graph_embeddings_emb
    ON graph_embeddings
    USING ivfflat (emb vector_l2_ops)
    WITH (lists = 100);

-- 6. Recreate helper / convenience views using the new schema

-- Note: mirrors your previous definitions

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

-- (Recreate any other views you had that depended on graph_embeddings.emb here)

-- 7. Final sanity notice
DO $$
DECLARE
    dim_ok TEXT;
BEGIN
    SELECT format_type(a.atttypid, a.atttypmod)
      INTO dim_ok
      FROM pg_attribute a
     WHERE a.attrelid = 'graph_embeddings'::regclass
       AND a.attname = 'emb';

    RAISE NOTICE '✅ graph_embeddings.emb type is now: %', dim_ok;
    RAISE NOTICE '   All old embeddings are gone. You must re-embed.';
END;
$$;
