-- 016_fact_pkg_integration.sql
-- Purpose: PKG integration enhancements for facts table
--          Note: Migration 011 already creates the facts table with all PKG columns.
--          This migration adds foreign key constraints, helper functions, and data conversions.
--
-- Dependencies: 011 (facts table), 013 (pkg_snapshots)

BEGIN;

-- ============================================================================
-- Foreign Key Constraint to PKG Snapshots
-- ============================================================================
-- Add foreign key constraint to PKG snapshots (if pkg_snapshots table exists)

DO $$
BEGIN
    -- Check if pkg_snapshots table exists (migration 013)
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'pkg_snapshots'
    ) THEN
        -- Add foreign key constraint
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint c
            WHERE c.conname = 'fk_facts_snapshot_id'
              AND c.conrelid = 'public.facts'::regclass
        ) THEN
            ALTER TABLE public.facts ADD CONSTRAINT fk_facts_snapshot_id
                FOREIGN KEY (snapshot_id) REFERENCES pkg_snapshots(id) ON DELETE SET NULL;
            RAISE NOTICE '✅ Added foreign key constraint fk_facts_snapshot_id';
        ELSE
            RAISE NOTICE 'ℹ️  Foreign key constraint fk_facts_snapshot_id already exists';
        END IF;
    ELSE
        RAISE NOTICE 'ℹ️  pkg_snapshots table not found - skipping foreign key constraint (will be added after migration 013)';
    END IF;
END
$$;

-- ============================================================================
-- Issue C: Temporal Modeling - Set Default valid_from
-- ============================================================================
-- Set valid_from = created_at for facts without temporal information
-- This enables "what was true yesterday?" queries

DO $$
DECLARE
    updated_count INTEGER;
BEGIN
    UPDATE public.facts
    SET valid_from = created_at
    WHERE valid_from IS NULL
      AND (subject IS NOT NULL OR pkg_rule_id IS NOT NULL);  -- Only for structured/PKG facts
    
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RAISE NOTICE '✅ Set valid_from for % facts (enables temporal queries)', updated_count;
END
$$;

-- ============================================================================
-- Issue D: Convert Text-Only Facts to Structured Triples
-- ============================================================================
-- Convert text-only facts in default namespace to structured triples

DO $$
DECLARE
    fact_record RECORD;
    new_subject TEXT;
    new_predicate TEXT;
    new_object_data JSONB;
    converted_count INTEGER := 0;
BEGIN
    FOR fact_record IN 
        SELECT id, text, tags, meta_data, created_at
        FROM public.facts
        WHERE namespace = 'default'
          AND subject IS NULL
          AND predicate IS NULL
          AND text IS NOT NULL
    LOOP
        -- Heuristic conversion based on text patterns
        IF fact_record.text ~* '^([A-Za-z0-9_]+) is a (.+)$' THEN
            -- Pattern: "X is a Y" -> subject=X, predicate=hasType, object={type: Y}
            new_subject := (regexp_match(fact_record.text, '^([A-Za-z0-9_]+) is a (.+)$'))[1];
            new_predicate := 'hasType';
            new_object_data := jsonb_build_object(
                'type', (regexp_match(fact_record.text, '^([A-Za-z0-9_]+) is a (.+)$'))[2],
                'description', fact_record.text,
                'original_tags', fact_record.tags,
                'converted_from_text', true
            );
        ELSIF fact_record.text ~* '^([A-Za-z0-9_]+) provides (.+)$' THEN
            -- Pattern: "X provides Y" -> subject=X, predicate=provides, object={description: Y}
            new_subject := (regexp_match(fact_record.text, '^([A-Za-z0-9_]+) provides (.+)$'))[1];
            new_predicate := 'provides';
            new_object_data := jsonb_build_object(
                'description', (regexp_match(fact_record.text, '^([A-Za-z0-9_]+) provides (.+)$'))[2],
                'full_text', fact_record.text,
                'original_tags', fact_record.tags,
                'converted_from_text', true
            );
        ELSIF fact_record.text ~* '^([A-Za-z0-9_]+) offers (.+)$' THEN
            -- Pattern: "X offers Y" -> subject=X, predicate=offers, object={description: Y}
            new_subject := (regexp_match(fact_record.text, '^([A-Za-z0-9_]+) offers (.+)$'))[1];
            new_predicate := 'offers';
            new_object_data := jsonb_build_object(
                'description', (regexp_match(fact_record.text, '^([A-Za-z0-9_]+) offers (.+)$'))[2],
                'full_text', fact_record.text,
                'original_tags', fact_record.tags,
                'converted_from_text', true
            );
        ELSE
            -- Fallback: use first word as subject, "hasDescription" as predicate
            new_subject := split_part(fact_record.text, ' ', 1);
            new_predicate := 'hasDescription';
            new_object_data := jsonb_build_object(
                'description', fact_record.text,
                'original_tags', fact_record.tags,
                'converted_from_text', true
            );
        END IF;
        
        -- Update the fact with structured triple
        UPDATE public.facts
        SET 
            subject = new_subject,
            predicate = new_predicate,
            object_data = new_object_data,
            valid_from = fact_record.created_at  -- Set temporal info
        WHERE id = fact_record.id;
        
        converted_count := converted_count + 1;
    END LOOP;
    
    RAISE NOTICE '✅ Converted % text-only facts to structured triples', converted_count;
END
$$;

-- ============================================================================
-- Helper Functions for Fact Management
-- ============================================================================
-- Note: Views (facts_structured, facts_text_only, facts_with_capabilities, 
--       active_temporal_facts, facts_current_truth) are already created in migration 011

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
    FROM public.facts f
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
    FROM public.facts
    WHERE 
        valid_to IS NOT NULL 
        AND valid_to <= now()
        AND (p_namespace IS NULL OR namespace = p_namespace);
    
    IF p_dry_run THEN
        -- Just return count without deleting
        RETURN expired_count;
    ELSE
        -- Delete expired facts
        DELETE FROM public.facts
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
        SELECT * FROM public.facts 
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

-- ============================================================================
-- Note: Views are already created in migration 011:
--   - facts_structured
--   - facts_text_only  
--   - facts_with_capabilities
--   - active_temporal_facts
--   - facts_current_truth
-- ============================================================================

-- Function: Get facts at a specific point in time (temporal queries)
CREATE OR REPLACE FUNCTION get_facts_at_time(
    p_namespace TEXT DEFAULT NULL,
    p_point_in_time TIMESTAMPTZ DEFAULT NOW()
) RETURNS TABLE (
    id UUID,
    namespace TEXT,
    subject TEXT,
    predicate TEXT,
    object_data JSONB,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ
) LANGUAGE SQL STABLE AS $$
    SELECT 
        f.id,
        f.namespace,
        f.subject,
        f.predicate,
        f.object_data,
        f.valid_from,
        f.valid_to,
        f.created_at
    FROM public.facts f
    WHERE 
        (p_namespace IS NULL OR f.namespace = p_namespace)
        AND f.subject IS NOT NULL
        AND f.predicate IS NOT NULL
        AND (
            (f.valid_from IS NULL OR f.valid_from <= p_point_in_time)
            AND (f.valid_to IS NULL OR f.valid_to > p_point_in_time)
        )
    ORDER BY f.created_at DESC;
$$;

COMMENT ON FUNCTION get_facts_at_time IS 
    'Get facts that were valid at a specific point in time. Enables "what was true yesterday?" queries.';

-- ============================================================================
-- Note: Enhanced indexes are already created in migration 011:
--   - idx_facts_spo_namespace
--   - idx_facts_object_capabilities
--   - idx_facts_object_type
-- ============================================================================

COMMIT;
