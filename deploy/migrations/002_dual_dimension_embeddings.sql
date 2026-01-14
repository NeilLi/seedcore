-- Option 2: Separate Tables (Cleanest Approach)
-- Creates separate tables for 128d and 1024d embeddings from the start.
-- This approach makes application code simpler - no if/else logic needed.
-- Your 128d AI engine reads/writes from graph_embeddings_128.
-- Your 1024d AI engine reads/writes from graph_embeddings_1024.

-- Requires: CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- Create graph_embeddings_128 table (128-dimensional embeddings)
-- ============================================================================

CREATE TABLE IF NOT EXISTS graph_embeddings_128 (
    node_id BIGINT NOT NULL,
    label TEXT NOT NULL DEFAULT 'default',
    props JSONB NULL,
    emb VECTOR(128) NOT NULL,
    model TEXT NULL,
    content_sha256 TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (node_id, label)
);

-- ANN index (adjust lists per data size)
CREATE INDEX IF NOT EXISTS idx_graph_embeddings_128_emb
    ON graph_embeddings_128
    USING ivfflat (emb vector_l2_ops)
    WITH (lists = 100);

-- Supporting indexes for common query paths
CREATE INDEX IF NOT EXISTS idx_graph_embeddings_128_node
    ON graph_embeddings_128 (node_id);

CREATE INDEX IF NOT EXISTS idx_graph_embeddings_128_label
    ON graph_embeddings_128 (label);

CREATE OR REPLACE FUNCTION update_graph_embeddings_128_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_graph_embeddings_128_updated_at ON graph_embeddings_128;
CREATE TRIGGER trg_graph_embeddings_128_updated_at
    BEFORE UPDATE ON graph_embeddings_128
    FOR EACH ROW EXECUTE FUNCTION update_graph_embeddings_128_updated_at();

-- ============================================================================
-- Create graph_embeddings_1024 table (1024-dimensional embeddings)
-- ============================================================================

CREATE TABLE IF NOT EXISTS graph_embeddings_1024 (
    node_id BIGINT NOT NULL,
    label TEXT NOT NULL DEFAULT 'default',
    props JSONB NULL,
    emb VECTOR(1024) NOT NULL,
    model TEXT NULL,
    content_sha256 TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (node_id, label)
);

-- ANN index (adjust lists per data size)
CREATE INDEX IF NOT EXISTS idx_graph_embeddings_1024_emb
    ON graph_embeddings_1024
    USING ivfflat (emb vector_l2_ops)
    WITH (lists = 100);

-- Supporting indexes for common query paths
CREATE INDEX IF NOT EXISTS idx_graph_embeddings_1024_node
    ON graph_embeddings_1024 (node_id);

CREATE INDEX IF NOT EXISTS idx_graph_embeddings_1024_label
    ON graph_embeddings_1024 (label);

CREATE OR REPLACE FUNCTION update_graph_embeddings_1024_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_graph_embeddings_1024_updated_at ON graph_embeddings_1024;
CREATE TRIGGER trg_graph_embeddings_1024_updated_at
    BEFORE UPDATE ON graph_embeddings_1024
    FOR EACH ROW EXECUTE FUNCTION update_graph_embeddings_1024_updated_at();

-- ============================================================================
-- Migrate data from old graph_embeddings table if it exists
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'graph_embeddings'
    ) THEN
        -- Migrate to graph_embeddings_128 (assuming existing data is 128d)
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

        -- Drop old table dependencies
        DROP INDEX IF EXISTS idx_graph_embeddings_emb;
        DROP INDEX IF EXISTS idx_graph_embeddings_node;
        DROP INDEX IF EXISTS idx_graph_embeddings_label;
        DROP INDEX IF EXISTS uq_graph_embeddings_node_label;
        DROP TRIGGER IF EXISTS trg_graph_embeddings_updated_at ON graph_embeddings;
        DROP FUNCTION IF EXISTS update_graph_embeddings_updated_at();
        
        -- Drop old views that reference graph_embeddings
        DROP VIEW IF EXISTS task_embeddings;  -- Created by migration 007 (old version)
        DROP VIEW IF EXISTS task_embeddings_stale;
        DROP VIEW IF EXISTS task_embeddings_primary;
        DROP VIEW IF EXISTS tasks_missing_embeddings;
        
        -- Drop old table
        DROP TABLE graph_embeddings;
        
        RAISE NOTICE '✅ Dropped old graph_embeddings table and dependencies';
    ELSE
        RAISE NOTICE 'ℹ️  No old graph_embeddings table found - migration not needed';
    END IF;
END;
$$;

-- ============================================================================
-- Final verification
-- ============================================================================

DO $$
DECLARE
    dim_128 TEXT;
    dim_1024 TEXT;
    old_table_exists BOOLEAN;
    dim_128_check INT;
    dim_1024_check INT;
BEGIN
    -- Check if old table still exists (shouldn't)
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'graph_embeddings'
    ) INTO old_table_exists;

    -- Verify 128d table structure
    SELECT format_type(a.atttypid, a.atttypmod)
      INTO dim_128
      FROM pg_attribute a
     WHERE a.attrelid = 'graph_embeddings_128'::regclass
       AND a.attname = 'emb';

    -- Verify 1024d table structure
    SELECT format_type(a.atttypid, a.atttypmod)
      INTO dim_1024
      FROM pg_attribute a
     WHERE a.attrelid = 'graph_embeddings_1024'::regclass
       AND a.attname = 'emb';

    RAISE NOTICE '';
    RAISE NOTICE '📋 Graph Embeddings Migration Summary:';
    RAISE NOTICE '   • graph_embeddings_128.emb type: %', dim_128;
    RAISE NOTICE '   • graph_embeddings_1024.emb type: %', dim_1024;
    
    IF old_table_exists THEN
        RAISE WARNING '⚠️  Old graph_embeddings table still exists - migration may have failed';
    ELSE
        RAISE NOTICE '   • Old graph_embeddings table: ✅ Removed';
    END IF;
    
    RAISE NOTICE '';
    RAISE NOTICE '💡 Note: Views are created in migration 017';
    
    -- CI-grade safety: Assert correct dimensions (fail fast if schema drift)
    -- Only check if tables have data (skip on fresh install)
    BEGIN
        SELECT vector_dims(emb) INTO dim_128_check FROM graph_embeddings_128 LIMIT 1;
        IF dim_128_check != 128 THEN
            RAISE EXCEPTION 'graph_embeddings_128 dimension mismatch: expected 128, got %', dim_128_check;
        END IF;
        
        SELECT vector_dims(emb) INTO dim_1024_check FROM graph_embeddings_1024 LIMIT 1;
        IF dim_1024_check != 1024 THEN
            RAISE EXCEPTION 'graph_embeddings_1024 dimension mismatch: expected 1024, got %', dim_1024_check;
        END IF;
        
        RAISE NOTICE '   • Vector dimension verification: ✅ Passed (128-d and 1024-d)';
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            -- Tables are empty, skip dimension check (expected on fresh install)
            RAISE NOTICE '   • Vector dimension verification: ⏭️  Skipped (tables empty)';
    END;
END;
$$;
