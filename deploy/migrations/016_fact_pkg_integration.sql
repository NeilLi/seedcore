-- 016_fact_pkg_integration.sql
-- Purpose: Add PKG integration fields to facts table for policy-driven fact management

BEGIN;

-- Add PKG integration columns to facts table
ALTER TABLE facts ADD COLUMN IF NOT EXISTS snapshot_id INTEGER;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS namespace TEXT NOT NULL DEFAULT 'default';
ALTER TABLE facts ADD COLUMN IF NOT EXISTS subject TEXT;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS predicate TEXT;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS object_data JSONB;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS created_by TEXT NOT NULL DEFAULT 'system';
ALTER TABLE facts ADD COLUMN IF NOT EXISTS pkg_rule_id TEXT;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS pkg_provenance JSONB;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS validation_status TEXT;

-- Add foreign key constraint to PKG snapshots
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conname = 'fk_facts_snapshot_id'
          AND c.conrelid = 'facts'::regclass
    ) THEN
        ALTER TABLE facts ADD CONSTRAINT fk_facts_snapshot_id
            FOREIGN KEY (snapshot_id) REFERENCES pkg_snapshots(id) ON DELETE SET NULL;
    END IF;
END
$$;

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject);
CREATE INDEX IF NOT EXISTS idx_facts_predicate ON facts(predicate);
CREATE INDEX IF NOT EXISTS idx_facts_namespace ON facts(namespace);
CREATE INDEX IF NOT EXISTS idx_facts_temporal ON facts(valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_facts_snapshot ON facts(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_facts_created_by ON facts(created_by);
CREATE INDEX IF NOT EXISTS idx_facts_pkg_rule ON facts(pkg_rule_id);
CREATE INDEX IF NOT EXISTS idx_facts_validation_status ON facts(validation_status);

-- Add composite indexes for common queries
CREATE INDEX IF NOT EXISTS idx_facts_subject_namespace ON facts(subject, namespace);
CREATE INDEX IF NOT EXISTS idx_facts_temporal_namespace ON facts(valid_from, valid_to, namespace);
CREATE INDEX IF NOT EXISTS idx_facts_created_at_namespace ON facts(created_at, namespace);

-- Add constraints
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conname = 'chk_facts_temporal'
          AND c.conrelid = 'facts'::regclass
    ) THEN
        ALTER TABLE facts ADD CONSTRAINT chk_facts_temporal
            CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conname = 'chk_facts_namespace_not_empty'
          AND c.conrelid = 'facts'::regclass
    ) THEN
        ALTER TABLE facts ADD CONSTRAINT chk_facts_namespace_not_empty
            CHECK (namespace IS NOT NULL AND length(trim(namespace)) > 0);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conname = 'chk_facts_created_by_not_empty'
          AND c.conrelid = 'facts'::regclass
    ) THEN
        ALTER TABLE facts ADD CONSTRAINT chk_facts_created_by_not_empty
            CHECK (created_by IS NOT NULL AND length(trim(created_by)) > 0);
    END IF;
END
$$;

-- Update existing facts to have default namespace
UPDATE facts SET namespace = 'default' WHERE namespace IS NULL;

-- Add comments for documentation
COMMENT ON COLUMN facts.snapshot_id IS 'Reference to PKG snapshot for policy governance';
COMMENT ON COLUMN facts.namespace IS 'Fact namespace for organization and access control';
COMMENT ON COLUMN facts.subject IS 'Fact subject (e.g., guest:john_doe)';
COMMENT ON COLUMN facts.predicate IS 'Fact predicate (e.g., hasTemporaryAccess)';
COMMENT ON COLUMN facts.object_data IS 'Fact object data as JSON';
COMMENT ON COLUMN facts.valid_from IS 'Fact validity start time (NULL = immediate)';
COMMENT ON COLUMN facts.valid_to IS 'Fact validity end time (NULL = indefinite)';
COMMENT ON COLUMN facts.created_by IS 'Creator identifier for audit trail';
COMMENT ON COLUMN facts.pkg_rule_id IS 'PKG rule that created this fact';
COMMENT ON COLUMN facts.pkg_provenance IS 'PKG rule provenance data for governance';
COMMENT ON COLUMN facts.validation_status IS 'PKG validation status (pkg_validated, pkg_validation_failed, etc.)';

-- Create a view for active temporal facts
CREATE OR REPLACE VIEW active_temporal_facts AS
SELECT 
    id,
    text,
    tags,
    meta_data,
    namespace,
    subject,
    predicate,
    object_data,
    valid_from,
    valid_to,
    created_by,
    snapshot_id,
    pkg_rule_id,
    validation_status,
    created_at,
    updated_at,
    CASE 
        WHEN valid_to IS NULL THEN 'indefinite'
        WHEN valid_to > now() THEN 'active'
        ELSE 'expired'
    END AS status
FROM facts
WHERE 
    (valid_from IS NOT NULL OR valid_to IS NOT NULL)
    AND (valid_to IS NULL OR valid_to > now());

COMMENT ON VIEW active_temporal_facts IS 'View of non-expired temporal facts with status indicator';

-- Create a function to get facts by subject with temporal filtering
CREATE OR REPLACE FUNCTION get_facts_by_subject(
    p_subject TEXT,
    p_namespace TEXT DEFAULT 'default',
    p_include_expired BOOLEAN DEFAULT FALSE
) RETURNS TABLE (
    id UUID,
    text TEXT,
    tags TEXT[],
    meta_data JSONB,
    namespace TEXT,
    subject TEXT,
    predicate TEXT,
    object_data JSONB,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    created_by TEXT,
    snapshot_id INTEGER,
    pkg_rule_id TEXT,
    validation_status TEXT,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    is_temporal BOOLEAN,
    is_expired BOOLEAN
) LANGUAGE SQL STABLE AS $$
    SELECT 
        f.id,
        f.text,
        f.tags,
        f.meta_data,
        f.namespace,
        f.subject,
        f.predicate,
        f.object_data,
        f.valid_from,
        f.valid_to,
        f.created_by,
        f.snapshot_id,
        f.pkg_rule_id,
        f.validation_status,
        f.created_at,
        f.updated_at,
        (f.valid_from IS NOT NULL OR f.valid_to IS NOT NULL) AS is_temporal,
        (f.valid_to IS NOT NULL AND f.valid_to <= now()) AS is_expired
    FROM facts f
    WHERE 
        f.subject = p_subject 
        AND f.namespace = p_namespace
        AND (p_include_expired OR f.valid_to IS NULL OR f.valid_to > now())
    ORDER BY f.created_at DESC;
$$;

COMMENT ON FUNCTION get_facts_by_subject IS 'Get facts for a subject with optional temporal filtering';

-- Create a function to cleanup expired facts
CREATE OR REPLACE FUNCTION cleanup_expired_facts(
    p_namespace TEXT DEFAULT NULL,
    p_dry_run BOOLEAN DEFAULT FALSE
) RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE
    expired_count INTEGER;
BEGIN
    -- Count expired facts
    SELECT COUNT(*) INTO expired_count
    FROM facts
    WHERE 
        valid_to IS NOT NULL 
        AND valid_to <= now()
        AND (p_namespace IS NULL OR namespace = p_namespace);
    
    IF p_dry_run THEN
        -- Just return count without deleting
        RETURN expired_count;
    ELSE
        -- Delete expired facts
        DELETE FROM facts
        WHERE 
            valid_to IS NOT NULL 
            AND valid_to <= now()
            AND (p_namespace IS NULL OR namespace = p_namespace);
        
        RETURN expired_count;
    END IF;
END;
$$;

COMMENT ON FUNCTION cleanup_expired_facts IS 'Cleanup expired temporal facts with optional dry run mode';

-- Create a function to get fact statistics
CREATE OR REPLACE FUNCTION get_fact_statistics(
    p_namespace TEXT DEFAULT NULL
) RETURNS TABLE (
    total_facts BIGINT,
    temporal_facts BIGINT,
    pkg_governed_facts BIGINT,
    expired_facts BIGINT,
    active_temporal_facts BIGINT,
    namespaces TEXT[]
) LANGUAGE SQL STABLE AS $$
    WITH namespace_filter AS (
        SELECT * FROM facts 
        WHERE p_namespace IS NULL OR namespace = p_namespace
    ),
    stats AS (
        SELECT 
            COUNT(*) AS total_facts,
            COUNT(*) FILTER (WHERE valid_from IS NOT NULL OR valid_to IS NOT NULL) AS temporal_facts,
            COUNT(*) FILTER (WHERE validation_status IS NOT NULL) AS pkg_governed_facts,
            COUNT(*) FILTER (WHERE valid_to IS NOT NULL AND valid_to <= now()) AS expired_facts,
            COUNT(*) FILTER (WHERE (valid_from IS NOT NULL OR valid_to IS NOT NULL) AND (valid_to IS NULL OR valid_to > now())) AS active_temporal_facts
        FROM namespace_filter
    ),
    namespace_list AS (
        SELECT array_agg(DISTINCT namespace ORDER BY namespace) AS namespaces
        FROM namespace_filter
    )
    SELECT 
        s.total_facts,
        s.temporal_facts,
        s.pkg_governed_facts,
        s.expired_facts,
        s.active_temporal_facts,
        COALESCE(nl.namespaces, ARRAY[]::TEXT[]) AS namespaces
    FROM stats s
    CROSS JOIN namespace_list nl;
$$;

COMMENT ON FUNCTION get_fact_statistics IS 'Get comprehensive statistics about facts';

COMMIT;
