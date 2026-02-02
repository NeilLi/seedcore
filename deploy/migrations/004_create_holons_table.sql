-- Migration 004: Create Holons Table
-- Purpose: Cognitive memory objects with 1024-dimensional embeddings
-- This is separate from graph embeddings (migration 002) which use 128d and 1024d.
-- Holons are cognitive memory objects, not graph nodes.
--
-- Dependencies: None (standalone table)
-- Architecture:
-- - 1024-d embeddings: Cognitive memory objects (e.g., large semantic / multimodal models)
--   This is INTENTIONAL and separate from graph embeddings:
--   - graph_embeddings_128: 128-d for fast HGNN routing
--   - graph_embeddings_1024: 1024-d for deep graph semantics
--   - holons.embedding: 1024-d for cognitive memory objects (not graph nodes)
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
    embedding    VECTOR(1024) NOT NULL,  -- 1024-d for cognitive memory (separate from graph embeddings)
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

    -- Make embedding NOT NULL if it's currently nullable
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'holons'
          AND column_name = 'embedding'
          AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE holons ALTER COLUMN embedding SET NOT NULL;
        RAISE NOTICE '✅ Made embedding column NOT NULL';
    END IF;

    -- Make created_at NOT NULL if it's currently nullable
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'holons'
          AND column_name = 'created_at'
          AND is_nullable = 'YES'
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
CREATE INDEX IF NOT EXISTS holons_embedding_idx 
    ON holons USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Index on UUID for fast lookups
CREATE INDEX IF NOT EXISTS holons_uuid_idx 
    ON holons (uuid);

-- Index on created_at for time-based queries
CREATE INDEX IF NOT EXISTS holons_created_at_idx 
    ON holons (created_at);

-- GIN index on JSONB meta field
CREATE INDEX IF NOT EXISTS holons_meta_idx 
    ON holons USING GIN (meta);

-- Supporting indexes
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
    (gen_random_uuid(), array_fill(0.1, ARRAY[1024])::vector, 'text-embedding-3-large', '{"type": "sample", "description": "Test holon 1"}'),
    (gen_random_uuid(), array_fill(0.2, ARRAY[1024])::vector, 'text-embedding-3-large', '{"type": "sample", "description": "Test holon 2"}'),
    (gen_random_uuid(), array_fill(0.3, ARRAY[1024])::vector, 'CLIP-ViT-L-14', '{"type": "sample", "description": "Test holon 3"}')
ON CONFLICT (uuid) DO NOTHING;

-- ============================================================================
-- Comments for documentation
-- ============================================================================

COMMENT ON TABLE holons IS 
    'Cognitive memory objects with 1024-dimensional embeddings. Separate from graph embeddings (128d/1024d) used for HGNN routing and knowledge graph semantics. Holons represent cognitive memory objects, not graph nodes.';

COMMENT ON COLUMN holons.embedding IS 
    '1024-dimensional vector embedding for cognitive memory objects. Separate from graph embeddings which use 128d (HGNN routing) and 1024d (deep graph semantics).';

COMMENT ON INDEX holons_embedding_idx IS 
    'HNSW index for fast cosine similarity search on 1024-d embeddings. Parameters: m=16, ef_construction=64.';

-- ============================================================================
-- Verification
-- ============================================================================

DO $$
DECLARE
    emb_dim INT;
    emb_type TEXT;
BEGIN
    BEGIN
        SELECT vector_dims(embedding) INTO emb_dim FROM holons LIMIT 1;
        SELECT format_type(a.atttypid, a.atttypmod)
          INTO emb_type
          FROM pg_attribute a
         WHERE a.attrelid = 'holons'::regclass
           AND a.attname = 'embedding';

        IF emb_dim != 1024 THEN
            RAISE WARNING 'Vector dimension is % (expected 1024).', emb_dim;
        ELSE
            RAISE NOTICE '✅ Vector dimension verification: % (correct)', emb_dim;
            RAISE NOTICE '   • Vector type: %', emb_type;
        END IF;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RAISE NOTICE 'ℹ️  Table empty — schema check only (VECTOR(1024))';
    END;
END;
$$;

COMMIT;
