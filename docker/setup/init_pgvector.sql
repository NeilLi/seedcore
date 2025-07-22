-- Initialize PGVector schema for Holon Fabric
-- Run this inside psql: psql -h localhost -U postgres -d postgres -f init_pgvector.sql

-- Enable the vector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create the holons table
CREATE TABLE IF NOT EXISTS holons (
    id           SERIAL PRIMARY KEY,
    uuid         UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    embedding    VECTOR(768),
    meta         JSONB,
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- Create HNSW index for vector similarity search
-- HNSW is simpler to tune than IVFFlat
CREATE INDEX IF NOT EXISTS holons_embedding_idx ON holons USING hnsw (embedding vector_cosine_ops);

-- Create additional indexes for performance
CREATE INDEX IF NOT EXISTS holons_uuid_idx ON holons (uuid);
CREATE INDEX IF NOT EXISTS holons_created_at_idx ON holons (created_at);
CREATE INDEX IF NOT EXISTS holons_meta_idx ON holons USING GIN (meta);

-- Insert some sample data for testing (768-dimensional vectors)
INSERT INTO holons (uuid, embedding, meta) VALUES
    (gen_random_uuid(), array_fill(0.1, ARRAY[768])::vector, '{"type": "sample", "description": "Test holon 1"}'),
    (gen_random_uuid(), array_fill(0.2, ARRAY[768])::vector, '{"type": "sample", "description": "Test holon 2"}'),
    (gen_random_uuid(), array_fill(0.3, ARRAY[768])::vector, '{"type": "sample", "description": "Test holon 3"}')
ON CONFLICT (uuid) DO NOTHING; 