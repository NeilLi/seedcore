-- Migration 019: Task Router Telemetry
-- Purpose: Store router telemetry snapshots for coordinator routing decisions
-- This table captures OCPS (Online Change Point Detection) signals, surprise scores,
-- and routing decisions for observability and debugging.
--
-- Dependencies: 001 (tasks table)
-- Architecture:
-- - Foreign key to tasks(id) for task association
-- - JSONB columns for flexible vector and metadata storage
-- - Indexes for efficient querying by task_id and chosen_route

BEGIN;

-- Ensure required extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- Create task_router_telemetry table
-- ============================================================================

CREATE TABLE IF NOT EXISTS task_router_telemetry (
    id BIGSERIAL PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    surprise_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    x_vector JSONB NOT NULL DEFAULT '[]'::jsonb,  -- Surprise vector (x1..x6)
    weights JSONB NOT NULL DEFAULT '[]'::jsonb,   -- Feature weights
    ocps_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,  -- OCPS state (S_t, h_threshold, etc.)
    chosen_route TEXT NOT NULL DEFAULT 'unknown',  -- Route decision (fast, planner, hgnn)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_task_router_telemetry_task_id 
    ON task_router_telemetry (task_id);

CREATE INDEX IF NOT EXISTS idx_task_router_telemetry_chosen_route 
    ON task_router_telemetry (chosen_route);

CREATE INDEX IF NOT EXISTS idx_task_router_telemetry_created_at 
    ON task_router_telemetry (created_at DESC);

-- Composite index for route analysis queries
CREATE INDEX IF NOT EXISTS idx_task_router_telemetry_route_created 
    ON task_router_telemetry (chosen_route, created_at DESC);

-- GIN index for JSONB queries on ocps_metadata
CREATE INDEX IF NOT EXISTS idx_task_router_telemetry_ocps_metadata 
    ON task_router_telemetry USING GIN (ocps_metadata);

-- ============================================================================
-- Comments for documentation
-- ============================================================================

COMMENT ON TABLE task_router_telemetry IS 
    'Router telemetry snapshots for coordinator routing decisions. Stores OCPS signals, surprise scores, and routing outcomes for observability.';

COMMENT ON COLUMN task_router_telemetry.task_id IS 
    'Foreign key to tasks table. One telemetry record per routing decision.';

COMMENT ON COLUMN task_router_telemetry.surprise_score IS 
    'Cumulative surprise score (S_t) from OCPS. Higher values indicate more novel/unexpected events.';

COMMENT ON COLUMN task_router_telemetry.x_vector IS 
    'Surprise vector components (x1..x6): cache_novelty, semantic_drift, multimodal_anomaly, graph_context_drift, logic_uncertainty, cost_risk.';

COMMENT ON COLUMN task_router_telemetry.weights IS 
    'Feature weights used in routing decision. Array of floats corresponding to x_vector components.';

COMMENT ON COLUMN task_router_telemetry.ocps_metadata IS 
    'OCPS state metadata: S_t (cumulative sum), h_threshold (valve threshold), drift_flag, etc.';

COMMENT ON COLUMN task_router_telemetry.chosen_route IS 
    'Route decision: fast (deterministic), planner (deep analysis), hgnn (graph-based routing).';

COMMENT ON INDEX idx_task_router_telemetry_task_id IS 
    'Index for fast lookups of telemetry by task_id.';

COMMENT ON INDEX idx_task_router_telemetry_chosen_route IS 
    'Index for analyzing routing decisions by route type.';

COMMENT ON INDEX idx_task_router_telemetry_ocps_metadata IS 
    'GIN index for efficient JSONB queries on OCPS metadata fields.';

-- ============================================================================
-- Verification
-- ============================================================================

DO $$
DECLARE
    table_exists BOOLEAN;
    index_count INT;
BEGIN
    -- Check if table exists
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' 
        AND table_name = 'task_router_telemetry'
    ) INTO table_exists;

    -- Count indexes
    SELECT COUNT(*) INTO index_count
    FROM pg_indexes
    WHERE schemaname = 'public'
    AND tablename = 'task_router_telemetry';

    RAISE NOTICE '';
    RAISE NOTICE '📋 Task Router Telemetry Migration Summary:';
    RAISE NOTICE '   • Table created: %', CASE WHEN table_exists THEN '✅' ELSE '❌' END;
    RAISE NOTICE '   • Indexes created: %', index_count;
    RAISE NOTICE '   • Purpose: Router telemetry snapshots for OCPS signals and routing decisions';
    RAISE NOTICE '';
END;
$$;

COMMIT;


