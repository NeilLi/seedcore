-- Migration 004: Create Holons Table
-- Purpose: Cognitive memory objects with 768-dimensional embeddings
-- This is separate from graph embeddings (migration 002) which use 128d and 1024d.
-- Holons are cognitive memory objects, not graph nodes.
--
-- Dependencies: None (standalone table)
-- Architecture:
-- - 768-d embeddings: Cognitive memory objects (e.g., OpenAI text-embedding-3-large, CLIP-style)
--   This is INTENTIONAL and separate from graph embeddings:
--   - graph_embeddings_128: 128-d for fast HGNN routing
--   - graph_embeddings_1024: 1024-d for deep graph semantics
--   - holons.embedding: 768-d for cognitive memory objects (not graph nodes)
-- - HNSW index for fast similarity search
-- - GIN index on JSONB meta field for flexible querying

BEGIN;

-- Ensure required extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- Create holons table
-- ============================================================================

CREATE TABLE IF NOT EXISTS holons (
    id           SERIAL PRIMARY KEY,
    uuid         UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    embedding    VECTOR(768) NOT NULL,  -- 768-d for cognitive memory (separate from graph embeddings)
    meta         JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- Add new columns if they don't exist (for idempotent migration)
-- ============================================================================

DO $$
BEGIN
    -- Add model column if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'holons' AND column_name = 'model'
    ) THEN
        ALTER TABLE holons ADD COLUMN model TEXT NULL;
        RAISE NOTICE '✅ Added model column to holons table';
    ELSE
        RAISE NOTICE 'ℹ️  model column already exists in holons table';
    END IF;

    -- Add content_sha256 column if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'holons' AND column_name = 'content_sha256'
    ) THEN
        ALTER TABLE holons ADD COLUMN content_sha256 TEXT NULL;
        RAISE NOTICE '✅ Added content_sha256 column to holons table';
    ELSE
        RAISE NOTICE 'ℹ️  content_sha256 column already exists in holons table';
    END IF;

    -- Add updated_at column if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'holons' AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE holons ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        RAISE NOTICE '✅ Added updated_at column to holons table';
    ELSE
        RAISE NOTICE 'ℹ️  updated_at column already exists in holons table';
    END IF;

    -- Make embedding NOT NULL if it's currently nullable (for existing tables)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'holons' 
        AND column_name = 'embedding' AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE holons ALTER COLUMN embedding SET NOT NULL;
        RAISE NOTICE '✅ Made embedding column NOT NULL';
    END IF;

    -- Make created_at NOT NULL if it's currently nullable (for existing tables)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'holons' 
        AND column_name = 'created_at' AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE holons ALTER COLUMN created_at SET NOT NULL;
        RAISE NOTICE '✅ Made created_at column NOT NULL';
    END IF;
END;
$$;

-- ============================================================================
-- Indexes
-- ============================================================================

-- HNSW index for fast cosine similarity search on embeddings
-- HNSW parameters:
--   m=16: number of connections per layer (balance between quality and speed)
--   ef_construction=64: size of dynamic candidate list during construction
CREATE INDEX IF NOT EXISTS holons_embedding_idx 
    ON holons USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Index on UUID for fast lookups
CREATE INDEX IF NOT EXISTS holons_uuid_idx 
    ON holons (uuid);

-- Index on created_at for time-based queries
CREATE INDEX IF NOT EXISTS holons_created_at_idx 
    ON holons (created_at);

-- GIN index on JSONB meta field for flexible querying
CREATE INDEX IF NOT EXISTS holons_meta_idx 
    ON holons USING GIN (meta);

-- Supporting indexes for common query paths
CREATE INDEX IF NOT EXISTS holons_model_idx 
    ON holons (model);

CREATE INDEX IF NOT EXISTS holons_content_sha256_idx 
    ON holons (content_sha256);

-- ============================================================================
-- Trigger for auto-updating updated_at timestamp
-- ============================================================================

CREATE OR REPLACE FUNCTION update_holons_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_holons_updated_at ON holons;
CREATE TRIGGER trg_holons_updated_at
    BEFORE UPDATE ON holons
    FOR EACH ROW EXECUTE FUNCTION update_holons_updated_at();

-- ============================================================================
-- Sample data (for testing/development)
-- ============================================================================

INSERT INTO holons (uuid, embedding, model, meta) VALUES
    (gen_random_uuid(), array_fill(0.1, ARRAY[768])::vector, 'text-embedding-3-large', '{"type": "sample", "description": "Test holon 1"}'),
    (gen_random_uuid(), array_fill(0.2, ARRAY[768])::vector, 'text-embedding-3-large', '{"type": "sample", "description": "Test holon 2"}'),
    (gen_random_uuid(), array_fill(0.3, ARRAY[768])::vector, 'CLIP-ViT-L-14', '{"type": "sample", "description": "Test holon 3"}')
ON CONFLICT (uuid) DO NOTHING;

-- ============================================================================
-- Comments for documentation
-- ============================================================================

COMMENT ON TABLE holons IS 
    'Cognitive memory objects with 768-dimensional embeddings. Separate from graph embeddings (128d/1024d) used for HGNN routing and knowledge graph semantics. Holons represent cognitive memory objects, not graph nodes.';

COMMENT ON COLUMN holons.id IS 
    'Primary key (SERIAL)';

COMMENT ON COLUMN holons.uuid IS 
    'Unique identifier (UUID) for external references';

COMMENT ON COLUMN holons.embedding IS 
    '768-dimensional vector embedding for cognitive memory (e.g., OpenAI text-embedding-3-large, CLIP-style). Separate from graph embeddings which use 128d (HGNN routing) and 1024d (deep semantics).';

COMMENT ON COLUMN holons.model IS 
    'Model identifier for embedding provenance (e.g., text-embedding-3-large, CLIP-ViT-L-14)';

COMMENT ON COLUMN holons.content_sha256 IS 
    'SHA256 hash of content for change detection and stale embedding identification';

COMMENT ON COLUMN holons.meta IS 
    'JSONB metadata field for flexible storage of holon properties';

COMMENT ON COLUMN holons.created_at IS 
    'Timestamp when the holon was created';

COMMENT ON COLUMN holons.updated_at IS 
    'Timestamp when the holon was last updated (automatically maintained by trigger)';

COMMENT ON INDEX holons_embedding_idx IS 
    'HNSW index for fast cosine similarity search on 768-d embeddings. Superior to IVFFlat for high-dimensional vectors. Parameters: m=16 (connections per layer), ef_construction=64 (candidate list size).';

COMMENT ON INDEX holons_meta_idx IS 
    'GIN index on JSONB meta field for flexible querying of holon properties';

-- ============================================================================
-- Verification
-- ============================================================================

DO $$
DECLARE
    table_exists BOOLEAN;
    embedding_index_exists BOOLEAN;
    uuid_index_exists BOOLEAN;
    meta_index_exists BOOLEAN;
    model_index_exists BOOLEAN;
    trigger_exists BOOLEAN;
    emb_dim INT;
    emb_type TEXT;
BEGIN
    -- Check if table exists
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' 
        AND table_name = 'holons'
    ) INTO table_exists;

    -- Check if indexes exist
    SELECT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'public'
        AND indexname = 'holons_embedding_idx'
    ) INTO embedding_index_exists;

    SELECT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'public'
        AND indexname = 'holons_uuid_idx'
    ) INTO uuid_index_exists;

    SELECT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'public'
        AND indexname = 'holons_meta_idx'
    ) INTO meta_index_exists;

    SELECT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'public'
        AND indexname = 'holons_model_idx'
    ) INTO model_index_exists;

    -- Check if trigger exists
    SELECT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_holons_updated_at'
    ) INTO trigger_exists;

    -- Verify vector dimension and type if table has data
    BEGIN
        -- Get vector dimension
        SELECT vector_dims(embedding) INTO emb_dim 
        FROM holons 
        LIMIT 1;
        
        -- Get vector type
        SELECT format_type(a.atttypid, a.atttypmod)
          INTO emb_type
          FROM pg_attribute a
         WHERE a.attrelid = 'holons'::regclass
           AND a.attname = 'embedding';
        
        IF emb_dim != 768 THEN
            RAISE WARNING 'Vector dimension is % (expected 768). Adjust VECTOR(768) if using different model.', emb_dim;
        ELSE
            RAISE NOTICE '✅ Vector dimension verification: %d (correct)', emb_dim;
            RAISE NOTICE '   • Vector type: %', emb_type;
        END IF;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            -- Table is empty, verify schema instead
            BEGIN
                SELECT format_type(a.atttypid, a.atttypmod)
                  INTO emb_type
                  FROM pg_attribute a
                 WHERE a.attrelid = 'holons'::regclass
                   AND a.attname = 'embedding';
                RAISE NOTICE 'ℹ️  Table is empty - dimension check skipped (expected on fresh install)';
                RAISE NOTICE '   • Vector type: %', emb_type;
            EXCEPTION
                WHEN OTHERS THEN
                    RAISE NOTICE 'ℹ️  Table is empty - schema check skipped (expected on fresh install)';
            END;
    END;

    RAISE NOTICE '';
    RAISE NOTICE '📋 Holons Table Migration Summary:';
    RAISE NOTICE '   • Table created: %', CASE WHEN table_exists THEN '✅' ELSE '❌' END;
    RAISE NOTICE '   • Embedding index created: %', CASE WHEN embedding_index_exists THEN '✅' ELSE '❌' END;
    RAISE NOTICE '   • UUID index created: %', CASE WHEN uuid_index_exists THEN '✅' ELSE '❌' END;
    RAISE NOTICE '   • Meta index created: %', CASE WHEN meta_index_exists THEN '✅' ELSE '❌' END;
    RAISE NOTICE '   • Model index created: %', CASE WHEN model_index_exists THEN '✅' ELSE '❌' END;
    RAISE NOTICE '   • Updated_at trigger created: %', CASE WHEN trigger_exists THEN '✅' ELSE '❌' END;
    RAISE NOTICE '   • Architecture: 768-d cognitive memory (separate from graph embeddings)';
    RAISE NOTICE '   • Index type: HNSW (superior to IVFFlat for high-dimensional vectors)';
    RAISE NOTICE '';
END;
$$;

COMMIT;
