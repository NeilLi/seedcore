-- Migration: Create facts table for SeedCore fact management system
-- This table stores facts with text, tags, and metadata for efficient searching and retrieval

-- Create facts table
CREATE TABLE IF NOT EXISTS facts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    text TEXT NOT NULL,
    tags TEXT[] DEFAULT '{}',
    meta_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_facts_text ON facts USING gin(to_tsvector('english', text));
CREATE INDEX IF NOT EXISTS idx_facts_created_at ON facts(created_at);
CREATE INDEX IF NOT EXISTS idx_facts_updated_at ON facts(updated_at);
CREATE INDEX IF NOT EXISTS idx_facts_tags ON facts USING gin(tags);
CREATE INDEX IF NOT EXISTS idx_facts_meta_data ON facts USING gin(meta_data);

-- Create full-text search index for text field
CREATE INDEX IF NOT EXISTS idx_facts_text_search ON facts USING gin(to_tsvector('english', text));

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_facts_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger to automatically update updated_at
DROP TRIGGER IF EXISTS trigger_facts_updated_at ON facts;
CREATE TRIGGER trigger_facts_updated_at
    BEFORE UPDATE ON facts
    FOR EACH ROW
    EXECUTE FUNCTION update_facts_updated_at();

-- Add comments for documentation
COMMENT ON TABLE facts IS 'Facts table for SeedCore fact management system';
COMMENT ON COLUMN facts.id IS 'Unique fact identifier';
COMMENT ON COLUMN facts.text IS 'The fact text content';
COMMENT ON COLUMN facts.tags IS 'Array of tags for categorizing the fact';
COMMENT ON COLUMN facts.meta_data IS 'Additional metadata as JSON';
COMMENT ON COLUMN facts.created_at IS 'Timestamp when fact was created';
COMMENT ON COLUMN facts.updated_at IS 'Timestamp when fact was last updated';

-- Insert some sample facts for testing (optional)
INSERT INTO facts (text, tags, meta_data) VALUES
    ('SeedCore is a scalable task management system', ARRAY['system', 'description'], '{"source": "documentation", "priority": "high"}'),
    ('PostgreSQL provides excellent JSON support', ARRAY['database', 'json'], '{"source": "technical", "verified": true}'),
    ('FastAPI offers modern Python web development', ARRAY['framework', 'python'], '{"source": "development", "rating": 5}')
ON CONFLICT (id) DO NOTHING;


