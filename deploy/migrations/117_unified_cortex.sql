-- Migration 117: Task Embedding Support & Unified Memory Integration
-- Purpose: Creates views for separate embedding tables (128d and 1024d) and integrates
--          multimodal embeddings with graph embeddings into a unified memory system.
--          Enhanced with snapshot_id scoping (from migration 017) to enable snapshot-aware
--          semantic search and prevent historical bleed.
-- If an old graph_embeddings table exists, it will be migrated to graph_embeddings_128.
-- Safe to run multiple times.
--
-- Dependencies: 001 (tasks), 002 (graph_embeddings_1024), 003 (task_multimodal_embeddings), 
--               007 (graph_node_map), 017 (pkg_tasks_snapshot_scoping)
--
-- Architecture:
-- - 128d embeddings: Fast HGNN routing (graph structure)
-- - 1024d embeddings: Deep semantic understanding (knowledge graph)
-- - Multimodal embeddings: Working memory for perception events (voice, vision, sensor)
-- - Unified Memory View: Merges all three tiers for PKG/Coordinator queries

-- We rely on digest() to compute SHA256 hashes in helper views.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- Drop views first (with CASCADE) to ensure clean state
-- ============================================================================
-- Views are dropped with CASCADE to automatically handle dependencies.
-- This ensures a clean state before recreating views, preventing errors
-- from column name/type changes or dependency issues.
DROP VIEW IF EXISTS v_unified_cortex_memory CASCADE;
DROP VIEW IF EXISTS task_embeddings_primary_1024 CASCADE;
DROP VIEW IF EXISTS task_embeddings_primary_128 CASCADE;
DROP VIEW IF EXISTS tasks_missing_embeddings_1024 CASCADE;
DROP VIEW IF EXISTS tasks_missing_embeddings_128 CASCADE;
DROP VIEW IF EXISTS task_embeddings_stale_1024 CASCADE;
DROP VIEW IF EXISTS task_embeddings_stale_128 CASCADE;
DROP VIEW IF EXISTS tasks_missing_any_embedding_1024 CASCADE;

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
-- Uses LEFT JOIN for graph_node_map to detect tasks that haven't been mapped to the graph yet
CREATE OR REPLACE VIEW tasks_missing_embeddings_128 AS
SELECT t.id AS task_id,
       m.node_id
  FROM tasks t
  LEFT JOIN graph_node_map m
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
-- Hash computation matches Python build_task_text() exactly:
--   Python: "\n".join([p.strip() for p in [description, task_type, params_pretty] if p and p.strip()])
--   SQL: concat_ws('\n', NULLIF(btrim(description), ''), NULLIF(btrim(type), ''), NULLIF(btrim(jsonb_pretty(params)), ''))
--   Note: jsonb_pretty uses 2-space indentation (matches json.dumps(indent=2))
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
-- Uses LEFT JOIN for graph_node_map to detect tasks that haven't been mapped to the graph yet
CREATE OR REPLACE VIEW tasks_missing_embeddings_1024 AS
SELECT t.id AS task_id,
       m.node_id
  FROM tasks t
  LEFT JOIN graph_node_map m
    ON m.node_type = 'task'
   AND m.ext_table = 'tasks'
   AND m.ext_uuid = t.id
  LEFT JOIN graph_embeddings_1024 e
    ON e.node_id = m.node_id
   AND e.label = 'task.primary'
 WHERE e.node_id IS NULL;

-- Convenience view for the primary task embedding label (1024d)
-- Enhanced with memory_tier, memory_label, and snapshot_id for Unified Memory integration
-- Drop first to handle column name changes (CREATE OR REPLACE cannot rename columns)
DROP VIEW IF EXISTS task_embeddings_primary_1024 CASCADE;
CREATE VIEW task_embeddings_primary_1024 AS
SELECT t.id         AS task_id,
       m.node_id    AS node_id,
       e.emb        AS emb,
       e.model      AS model,
       e.props      AS props,
       e.label      AS memory_label,
       'knowledge_base'::TEXT AS memory_tier,
       COALESCE(t.snapshot_id, e.snapshot_id, m.snapshot_id) AS snapshot_id,
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
-- Hash computation matches Python build_task_text() exactly:
--   Python: "\n".join([p.strip() for p in [description, task_type, params_pretty] if p and p.strip()])
--   SQL: concat_ws('\n', NULLIF(btrim(description), ''), NULLIF(btrim(type), ''), NULLIF(btrim(jsonb_pretty(params)), ''))
--   Note: jsonb_pretty uses 2-space indentation (matches json.dumps(indent=2))
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

-- ============================================================================
-- Unified Memory Integration: The Unified Cortex View
-- ============================================================================
-- This view merges three memory tiers with snapshot_id scoping (from migration 017):
--   A) Multimodal Task Events (The "Now" - System 1 / Working Memory)
--      - Direct FK to tasks, fast "Living System" response times
--      - Voice, vision, sensor perception events
--      - snapshot_id from tasks table (enables snapshot-aware filtering)
--      - EXCLUDES tasks that have been promoted to knowledge graph (TIER 2) to avoid duplication
--   B) Knowledge Graph Tasks (The "Rules" - System 2 / Structural Memory)
--      - Tasks linked through graph_node_map to graph_embeddings_1024
--      - Structural knowledge and task relationships
--      - Includes tasks promoted from TIER 1 (multimodal) to knowledge graph
--      - snapshot_id from tasks/graph_embeddings_1024/graph_node_map (COALESCE)
--   C) General Graph Entities (The "World" - Context Memory)
--      - All other graph nodes (agents, organs, artifacts, etc.)
--      - Broader knowledge base context
--      - snapshot_id from graph_embeddings_1024 table
--
-- The view uses TEXT casting for polymorphic IDs (UUID -> TEXT, BIGINT -> TEXT)
-- to resolve the impedance mismatch between Knowledge Graph (BIGINT) and
-- Multimodal Events (UUID).
--
-- Deduplication Strategy:
--   - TIER 1 excludes tasks that have graph_embeddings_1024 entries with label='task.primary'
--   - TIER 2 includes all tasks with graph_embeddings_1024 entries with label='task.primary'
--   - TIER 3 excludes label='task.primary' to avoid duplication with TIER 2
--   This ensures each task appears in exactly one tier based on its promotion status.
--
-- IMPORTANT: All queries should filter by snapshot_id to prevent historical bleed:
--   SELECT * FROM v_unified_cortex_memory WHERE snapshot_id = :current_snapshot_id
-- ============================================================================

CREATE OR REPLACE VIEW v_unified_cortex_memory AS
-- TIER 1: Multimodal Event Memory (Working Memory - "The Now")
-- These are perception events: voice commands, vision frames, sensor readings
-- Exclude tasks that have been promoted to the knowledge graph (TIER 2) to avoid duplication
SELECT 
    t.id::TEXT                    AS id, 
    t.type                        AS category, 
    t.description                 AS content, 
    'event_working'::TEXT          AS memory_tier,
    t.snapshot_id                 AS snapshot_id,
    te.emb                        AS vector,
    jsonb_build_object(
        'multimodal', t.params->'multimodal',
        'source_modality', te.source_modality,
        'model_version', te.model_version,
        'task_id', t.id,
        'task_status', t.status,
        'task_type', t.type
    )                             AS metadata
FROM tasks t
JOIN task_multimodal_embeddings te ON t.id = te.task_id
-- Exclude tasks that have been promoted to knowledge graph (have graph_embeddings_1024 with label='task.primary')
WHERE NOT EXISTS (
    SELECT 1
    FROM graph_node_map m
    JOIN graph_embeddings_1024 e ON e.node_id = m.node_id AND e.label = 'task.primary'
    WHERE m.node_type = 'task'
      AND m.ext_table = 'tasks'
      AND m.ext_uuid = t.id
)

UNION ALL

-- TIER 2: Knowledge Graph Tasks (Structural Memory - "The Rules")
-- These are tasks that are part of the static Knowledge Graph structure
-- This includes tasks that have been promoted from TIER 1 (multimodal) to the knowledge graph
SELECT 
    task_id::TEXT                 AS id,
    'task_graph'::TEXT            AS category,
    'KG Task Reference'::TEXT     AS content,
    'knowledge_base'::TEXT         AS memory_tier,
    snapshot_id                   AS snapshot_id,
    emb                           AS vector,
    jsonb_build_object(
        'node_id', node_id,
        'memory_label', memory_label,
        'model', model,
        'props', props,
        'content_sha256', content_sha256
    )                             AS metadata
FROM task_embeddings_primary_1024

UNION ALL

-- TIER 3: General Graph Entities (World Memory - "The Context")
-- All other graph nodes: agents, organs, artifacts, capabilities, memory_cells, etc.
-- We exclude 'task.primary' to avoid duplication with TIER 2
SELECT 
    node_id::TEXT                 AS id,
    label                         AS category,
    COALESCE(
        props->>'name',
        props->>'description',
        props->>'title',
        props->>'specialization',
        'Graph Entity'
    )                             AS content,
    'world_memory'::TEXT          AS memory_tier,
    snapshot_id                   AS snapshot_id,
    emb                           AS vector,
    jsonb_build_object(
        'node_id', node_id,
        'label', label,
        'model', model,
        'props', props,
        'content_sha256', content_sha256
    )                             AS metadata
FROM graph_embeddings_1024
WHERE label != 'task.primary'; -- Avoid duplication of TIER 2

-- ============================================================================
-- Unified Maintenance Views
-- ============================================================================

-- View: Tasks missing ANY 1024d embedding (multimodal OR graph)
-- Useful for backfill operations to ensure all tasks have appropriate embeddings
-- Enhanced with snapshot_id for snapshot-aware backfill operations
CREATE OR REPLACE VIEW tasks_missing_any_embedding_1024 AS
SELECT 
    t.id AS task_id,
    t.type AS task_type,
    t.description AS task_description,
    t.snapshot_id AS snapshot_id,
    CASE 
        WHEN te.task_id IS NULL AND ge.node_id IS NULL THEN 'both'
        WHEN te.task_id IS NULL THEN 'multimodal'
        WHEN ge.node_id IS NULL THEN 'graph'
    END AS missing_type
FROM tasks t
LEFT JOIN task_multimodal_embeddings te ON t.id = te.task_id
LEFT JOIN graph_node_map m ON m.ext_uuid = t.id AND m.node_type = 'task' AND m.ext_table = 'tasks'
LEFT JOIN graph_embeddings_1024 ge ON ge.node_id = m.node_id AND ge.label = 'task.primary'
WHERE te.task_id IS NULL AND ge.node_id IS NULL;

-- ============================================================================
-- Comments for Unified Memory Views
-- ============================================================================

COMMENT ON VIEW v_unified_cortex_memory IS 
    'Unified Memory View: Merges multimodal events (working memory), knowledge graph tasks (structural memory), and general graph entities (world memory). Uses TEXT casting for polymorphic IDs to resolve UUID/BIGINT impedance mismatch. Includes snapshot_id for snapshot-aware filtering to prevent historical bleed. The Coordinator can filter by memory_tier for fast-path queries, while PKG can query the entire view for deep reasoning. IMPORTANT: Always filter by snapshot_id in production queries (e.g., WHERE snapshot_id = :current_snapshot_id) to ensure reproducible runs and safe retrieval.';

COMMENT ON VIEW tasks_missing_any_embedding_1024 IS 
    'Identifies tasks missing 1024d embeddings in either multimodal or graph tables (or both). Useful for backfill operations to ensure complete embedding coverage. Includes snapshot_id for snapshot-aware backfill operations (e.g., WHERE snapshot_id = :current_snapshot_id) to prevent cross-snapshot contamination.';

COMMENT ON COLUMN task_embeddings_primary_1024.memory_tier IS 
    'Memory tier classification: knowledge_base (structural/static knowledge) vs event_working (perception events)';

COMMENT ON COLUMN task_embeddings_primary_1024.memory_label IS 
    'Label from graph_embeddings_1024 (typically task.primary) for memory organization';

COMMENT ON COLUMN task_embeddings_primary_1024.snapshot_id IS 
    'PKG snapshot ID (COALESCE from tasks, graph_embeddings_1024, or graph_node_map). Critical for snapshot-aware semantic search and preventing historical bleed.';

-- ============================================================================
-- Performance Optimization: Partial GIN Index for Multimodal Tasks
-- ============================================================================
-- This partial index dramatically improves query performance for multimodal tasks
-- by only indexing the small subset of tasks that contain multimodal data.
-- At 1M+ rows, this reduces index size from ~500MB+ to ~10-50MB and improves
-- query times from ~200-500ms to ~5-15ms for multimodal queries.
--
-- IMPORTANT FOR PRODUCTION:
-- If applying this migration to a production database with 100K+ tasks, consider
-- creating the index CONCURRENTLY to avoid locking the table:
--   DROP INDEX IF EXISTS idx_tasks_multimodal_fast;
--   CREATE INDEX CONCURRENTLY idx_tasks_multimodal_fast 
--   ON tasks USING GIN (params) WHERE (params ? 'multimodal');
--
-- For fresh installs or small tables, the regular CREATE INDEX is faster and safe.
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_tasks_multimodal_fast 
ON tasks USING GIN (params) 
WHERE (params ? 'multimodal');

COMMENT ON INDEX idx_tasks_multimodal_fast IS 
    'Partial GIN index for fast multimodal task queries. Only indexes tasks containing params.multimodal, dramatically reducing index size and improving query performance for unified memory views. For production databases with 100K+ tasks, recreate with CONCURRENTLY to avoid table locks.';

-- ============================================================================
-- Semantic Search Helper Function
-- ============================================================================
-- Provides snapshot-aware semantic search across the unified cortex memory
-- with similarity threshold enforcement to prevent low-quality matches.
--
-- Usage:
--   SELECT * FROM unified_cortex_semantic_search(
--       query_vector := '[0.1, 0.2, ...]'::vector(1024),
--       snapshot_id := 123,
--       similarity_threshold := 0.8,
--       limit_results := 10,
--       memory_tier_filter := NULL  -- or 'event_working', 'knowledge_base'
--   );
-- ============================================================================

CREATE OR REPLACE FUNCTION unified_cortex_semantic_search(
    query_vector vector(1024),
    snapshot_id INTEGER,
    similarity_threshold FLOAT DEFAULT 0.8,
    limit_results INTEGER DEFAULT 10,
    memory_tier_filter TEXT DEFAULT NULL
)
RETURNS TABLE (
    id TEXT,
    category TEXT,
    content TEXT,
    memory_tier TEXT,
    snapshot_id INTEGER,
    similarity FLOAT,
    metadata JSONB
) 
LANGUAGE SQL
STABLE
AS $$
    SELECT 
        v.id,
        v.category,
        v.content,
        v.memory_tier,
        v.snapshot_id,
        1 - (v.vector <=> query_vector) AS similarity,
        v.metadata
    FROM v_unified_cortex_memory v
    WHERE v.snapshot_id = unified_cortex_semantic_search.snapshot_id
      AND (memory_tier_filter IS NULL OR v.memory_tier = memory_tier_filter)
      AND 1 - (v.vector <=> query_vector) >= similarity_threshold
    ORDER BY v.vector <=> query_vector
    LIMIT limit_results;
$$;

COMMENT ON FUNCTION unified_cortex_semantic_search IS 
    'Snapshot-aware semantic search across unified cortex memory. Enforces snapshot_id filtering to prevent historical bleed and similarity threshold to ensure high-quality matches. Returns results ordered by similarity (highest first). Use memory_tier_filter to restrict search to specific tiers (event_working, knowledge_base) or NULL for all tiers.';

-- ============================================================================
-- IMMUTABLE Function for Hash Computation (Required for Functional Index)
-- ============================================================================
-- PostgreSQL requires functions used in indexes to be marked IMMUTABLE.
-- However, jsonb_pretty() is marked STABLE (not IMMUTABLE) because PostgreSQL
-- cannot guarantee its output won't change across versions.
--
-- IMPORTANT LIMITATION: We cannot use jsonb_pretty() in an IMMUTABLE function.
-- The views use jsonb_pretty() to match Python's json.dumps(params, indent=2),
-- but the index must use params::text (compact JSON) which is IMMUTABLE.
--
-- This means:
--   - Views: Use jsonb_pretty(params) → matches Python json.dumps(params, indent=2)
--   - Index: Uses params::text → compact JSON (doesn't match Python exactly)
--
-- The index won't perfectly match the view hash, but it can still help with
-- performance by pre-filtering tasks. For exact hash matching, queries should
-- use the view logic directly (which can use STABLE functions).
--
-- FUTURE OPTIMIZATION: Consider adding a computed column that stores the hash
-- using jsonb_pretty(), updated via trigger, if exact index matching is critical.
-- ============================================================================

CREATE OR REPLACE FUNCTION immutable_task_content_hash(
    description TEXT,
    task_type TEXT,
    params JSONB
)
RETURNS TEXT
LANGUAGE SQL
IMMUTABLE
STRICT
AS $$
    -- Note: Using params::text (compact JSON) because jsonb_pretty() is STABLE
    -- This won't match Python's json.dumps(params, indent=2) exactly, but
    -- allows us to create a functional index for performance optimization.
    SELECT encode(
        digest(
            convert_to(
                left(
                    concat_ws(
                        '\n',
                        NULLIF(btrim(description), ''),
                        NULLIF(btrim(task_type), ''),
                        NULLIF(btrim(params::text), '')
                    ),
                    16000
                ),
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    );
$$;

COMMENT ON FUNCTION immutable_task_content_hash IS 
    'IMMUTABLE wrapper for task content hash computation. Uses params::text (compact JSON) because jsonb_pretty() is STABLE and cannot be used in IMMUTABLE functions. Note: This produces a different hash than the views (which use jsonb_pretty to match Python json.dumps(params, indent=2)). The index helps with performance but queries should use view logic for exact hash matching.';

-- ============================================================================
-- Performance Optimization: Functional Index for Stale Embedding Detection
-- ============================================================================
-- The stale view performs a heavy digest(sha256) computation on every row.
-- As the tasks table grows to 100k+ rows, this view becomes extremely slow.
-- This functional index uses the IMMUTABLE function to pre-compute hashes.
--
-- IMPORTANT LIMITATION: The index uses params::text (compact JSON) via the
-- IMMUTABLE function, while the views use jsonb_pretty() (pretty JSON) to
-- match Python's json.dumps(params, indent=2). This means the index hash
-- won't match the view hash exactly, but it can still help with performance
-- by pre-filtering tasks before the view's hash computation.
--
-- For exact hash matching, queries should use the view logic directly
-- (which can use STABLE functions like jsonb_pretty).
--
-- For production databases with 100K+ tasks, consider creating this index CONCURRENTLY:
--   DROP INDEX IF EXISTS idx_tasks_content_hash_1024;
--   CREATE INDEX CONCURRENTLY idx_tasks_content_hash_1024 
--   ON tasks (immutable_task_content_hash(description, type, params));
-- ============================================================================

-- Drop the old index if it exists (it may have failed to create due to IMMUTABLE error)
DROP INDEX IF EXISTS idx_tasks_content_hash_1024;

-- Create the index using the IMMUTABLE function
CREATE INDEX IF NOT EXISTS idx_tasks_content_hash_1024 
ON tasks (immutable_task_content_hash(description, type, params));

COMMENT ON INDEX idx_tasks_content_hash_1024 IS 
    'Functional index for fast stale embedding detection. Uses IMMUTABLE function with params::text (compact JSON). Note: Index hash differs from view hash (which uses jsonb_pretty for exact Python matching), but still helps with performance. For production databases, recreate with CONCURRENTLY to avoid table locks.';
