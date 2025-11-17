--
-- NOTE: This migration creates views for the separate embedding tables (128d and 1024d).
-- If an old graph_embeddings table exists, it will be migrated to graph_embeddings_128.
-- Safe to run multiple times.
--

-- We rely on digest() to compute SHA256 hashes in helper views.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- Migrate from old graph_embeddings table if it exists
-- ============================================================================

DO $$
BEGIN
    -- Check if old graph_embeddings table exists
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'graph_embeddings'
    ) THEN
        -- Ensure graph_embeddings_128 table exists (should exist from migration 002)
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'graph_embeddings_128'
        ) THEN
            -- Migrate data from old table to graph_embeddings_128
            INSERT INTO graph_embeddings_128 (node_id, label, props, emb, model, content_sha256, created_at, updated_at)
            SELECT 
                node_id,
                COALESCE(NULLIF(btrim(label), ''), 'default') AS label,
                props,
                emb,
                model,
                content_sha256,
                created_at,
                updated_at
            FROM graph_embeddings
            WHERE NOT EXISTS (
                SELECT 1 FROM graph_embeddings_128 ge128
                WHERE ge128.node_id = graph_embeddings.node_id
                AND ge128.label = COALESCE(NULLIF(btrim(graph_embeddings.label), ''), 'default')
            )
            ON CONFLICT DO NOTHING;

            RAISE NOTICE '✅ Migrated data from graph_embeddings to graph_embeddings_128';
        END IF;

        -- Drop old table and its dependencies
        DROP INDEX IF EXISTS idx_graph_embeddings_emb;
        DROP INDEX IF EXISTS idx_graph_embeddings_node;
        DROP INDEX IF EXISTS idx_graph_embeddings_label;
        DROP INDEX IF EXISTS uq_graph_embeddings_node_label;
        DROP TRIGGER IF EXISTS trg_graph_embeddings_updated_at ON graph_embeddings;
        DROP FUNCTION IF EXISTS update_graph_embeddings_updated_at();
        DROP TABLE IF EXISTS graph_embeddings;
        
        RAISE NOTICE '✅ Dropped old graph_embeddings table';
    ELSE
        RAISE NOTICE 'ℹ️  No old graph_embeddings table found - using new separate tables';
    END IF;
END;
$$;

-- ============================================================================
-- Create views for 128d embeddings
-- ============================================================================

-- Helper view: tasks missing primary task embeddings (128d)
CREATE OR REPLACE VIEW tasks_missing_embeddings_128 AS
SELECT t.id AS task_id,
       m.node_id
  FROM tasks t
  JOIN graph_node_map m
    ON m.node_type = 'task'
   AND m.ext_table = 'tasks'
   AND m.ext_uuid = t.id
  LEFT JOIN graph_embeddings_128 e
    ON e.node_id = m.node_id
   AND e.label = 'task.primary'
 WHERE e.node_id IS NULL;

-- Convenience view for the primary task embedding label (128d)
CREATE OR REPLACE VIEW task_embeddings_primary_128 AS
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
  JOIN graph_embeddings_128 e
    ON e.node_id = m.node_id
   AND e.label = 'task.primary';

-- Helper view: detect stale embeddings (128d)
CREATE OR REPLACE VIEW task_embeddings_stale_128 AS
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
  JOIN graph_embeddings_128 e
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

-- ============================================================================
-- Create views for 1024d embeddings
-- ============================================================================

-- Helper view: tasks missing primary task embeddings (1024d)
CREATE OR REPLACE VIEW tasks_missing_embeddings_1024 AS
SELECT t.id AS task_id,
       m.node_id
  FROM tasks t
  JOIN graph_node_map m
    ON m.node_type = 'task'
   AND m.ext_table = 'tasks'
   AND m.ext_uuid = t.id
  LEFT JOIN graph_embeddings_1024 e
    ON e.node_id = m.node_id
   AND e.label = 'task.primary'
 WHERE e.node_id IS NULL;

-- Convenience view for the primary task embedding label (1024d)
CREATE OR REPLACE VIEW task_embeddings_primary_1024 AS
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
  JOIN graph_embeddings_1024 e
    ON e.node_id = m.node_id
   AND e.label = 'task.primary';

-- Helper view: detect stale embeddings (1024d)
CREATE OR REPLACE VIEW task_embeddings_stale_1024 AS
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
  JOIN graph_embeddings_1024 e
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
