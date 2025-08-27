-- Initialize PGVector schema for Holon Fabric
-- Run this inside psql: psql -h localhost -U postgres -d postgres -f init_pgvector.sql

-- Enable the pgcrypto extension (needed for gen_random_uuid)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

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

-- Create the taskstatus enum with lowercase values to match existing database schema
CREATE TYPE IF NOT EXISTS taskstatus AS ENUM (
    'created',
    'queued', 
    'running',
    'completed',
    'failed',
    'cancelled',
    'retry'
);

-- Create tasks table for the Coordinator + Dispatcher system
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status taskstatus NOT NULL DEFAULT 'created',
    attempts INTEGER NOT NULL DEFAULT 0,
    locked_by TEXT NULL,
    locked_at TIMESTAMP WITH TIME ZONE NULL,
    run_after TIMESTAMP WITH TIME ZONE NULL,
    type TEXT NOT NULL,
    description TEXT NULL,
    domain TEXT NULL,
    drift_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB NULL,
    error TEXT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_run_after ON tasks(run_after);
CREATE INDEX IF NOT EXISTS idx_tasks_locked_at ON tasks(locked_at);
CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(type);
CREATE INDEX IF NOT EXISTS idx_tasks_domain ON tasks(domain);

-- Create composite index for the claim query
CREATE INDEX IF NOT EXISTS idx_tasks_claim ON tasks(status, run_after, created_at) 
WHERE status IN ('queued', 'failed', 'retry');

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_tasks_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger to automatically update updated_at
DROP TRIGGER IF EXISTS trigger_tasks_updated_at ON tasks;
CREATE TRIGGER trigger_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_tasks_updated_at(); 