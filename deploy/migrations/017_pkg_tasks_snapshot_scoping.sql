-- Migration 017: PKG Tasks Snapshot Scoping
-- Purpose: Add snapshot_id to core operational tables (tasks, graph_embeddings_1024, graph_node_map)
--          to enable reproducible runs, multi-world isolation, time travel debugging, and safe retrieval.
--          This migration implements the P0 critical refactor identified in snapshot_id_analysis.md.
--
-- Dependencies: 001 (tasks), 002 (graph_embeddings_1024), 007 (graph_node_map), 013 (pkg_snapshots), 016 (facts)
--
-- Architecture:
-- - Phase 1: Add nullable snapshot_id columns (non-breaking)
-- - Phase 2: Backfill existing rows with current active snapshot
-- - Phase 3: Enforce NOT NULL constraints and foreign keys
-- - Phase 4: Add indexes for performance
-- - Phase 5: Add constraint to facts table for PKG-governed facts
--
-- This migration is idempotent and safe to run multiple times.

BEGIN;

-- ============================================================================
-- PHASE 1: Add nullable snapshot_id columns (Non-Breaking)
-- ============================================================================

-- Add snapshot_id to tasks table
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'tasks' AND column_name = 'snapshot_id'
    ) THEN
        ALTER TABLE tasks ADD COLUMN snapshot_id INTEGER;
        RAISE NOTICE '✅ Added snapshot_id column to tasks table';
    ELSE
        RAISE NOTICE 'ℹ️  snapshot_id column already exists in tasks table';
    END IF;
END $$;

-- Add snapshot_id to graph_embeddings_1024 table
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'graph_embeddings_1024' AND column_name = 'snapshot_id'
    ) THEN
        ALTER TABLE graph_embeddings_1024 ADD COLUMN snapshot_id INTEGER;
        RAISE NOTICE '✅ Added snapshot_id column to graph_embeddings_1024 table';
    ELSE
        RAISE NOTICE 'ℹ️  snapshot_id column already exists in graph_embeddings_1024 table';
    END IF;
END $$;

-- Add snapshot_id to graph_node_map table
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'graph_node_map' AND column_name = 'snapshot_id'
    ) THEN
        ALTER TABLE graph_node_map ADD COLUMN snapshot_id INTEGER;
        RAISE NOTICE '✅ Added snapshot_id column to graph_node_map table';
    ELSE
        RAISE NOTICE 'ℹ️  snapshot_id column already exists in graph_node_map table';
    END IF;
END $$;

-- ============================================================================
-- PHASE 2: Backfill existing rows with current active snapshot
-- ============================================================================

-- Backfill tasks table
DO $$
DECLARE
    active_snapshot_id INTEGER;
    updated_count INTEGER;
BEGIN
    -- Get the current active snapshot ID
    SELECT id INTO active_snapshot_id
    FROM pkg_snapshots
    WHERE is_active = TRUE
    ORDER BY created_at DESC
    LIMIT 1;

    IF active_snapshot_id IS NOT NULL THEN
        -- Backfill tasks
        UPDATE tasks
        SET snapshot_id = active_snapshot_id
        WHERE snapshot_id IS NULL;
        
        GET DIAGNOSTICS updated_count = ROW_COUNT;
        RAISE NOTICE '✅ Backfilled % tasks with snapshot_id = %', updated_count, active_snapshot_id;

        -- Backfill graph_embeddings_1024
        UPDATE graph_embeddings_1024
        SET snapshot_id = active_snapshot_id
        WHERE snapshot_id IS NULL;
        
        GET DIAGNOSTICS updated_count = ROW_COUNT;
        RAISE NOTICE '✅ Backfilled % graph_embeddings_1024 rows with snapshot_id = %', updated_count, active_snapshot_id;

        -- Backfill graph_node_map
        UPDATE graph_node_map
        SET snapshot_id = active_snapshot_id
        WHERE snapshot_id IS NULL;
        
        GET DIAGNOSTICS updated_count = ROW_COUNT;
        RAISE NOTICE '✅ Backfilled % graph_node_map rows with snapshot_id = %', updated_count, active_snapshot_id;
    ELSE
        RAISE WARNING '⚠️  No active snapshot found - skipping backfill. Please create an active snapshot first.';
    END IF;
END $$;

-- ============================================================================
-- PHASE 3: Add foreign key constraints
-- ============================================================================

-- Add foreign key constraint to tasks.snapshot_id
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conname = 'fk_tasks_snapshot_id'
          AND c.conrelid = 'tasks'::regclass
    ) THEN
        ALTER TABLE tasks ADD CONSTRAINT fk_tasks_snapshot_id
            FOREIGN KEY (snapshot_id) REFERENCES pkg_snapshots(id) ON DELETE SET NULL;
        RAISE NOTICE '✅ Added foreign key constraint fk_tasks_snapshot_id';
    ELSE
        RAISE NOTICE 'ℹ️  Foreign key constraint fk_tasks_snapshot_id already exists';
    END IF;
END $$;

-- Add foreign key constraint to graph_embeddings_1024.snapshot_id
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conname = 'fk_graph_embeddings_1024_snapshot_id'
          AND c.conrelid = 'graph_embeddings_1024'::regclass
    ) THEN
        ALTER TABLE graph_embeddings_1024 ADD CONSTRAINT fk_graph_embeddings_1024_snapshot_id
            FOREIGN KEY (snapshot_id) REFERENCES pkg_snapshots(id) ON DELETE SET NULL;
        RAISE NOTICE '✅ Added foreign key constraint fk_graph_embeddings_1024_snapshot_id';
    ELSE
        RAISE NOTICE 'ℹ️  Foreign key constraint fk_graph_embeddings_1024_snapshot_id already exists';
    END IF;
END $$;

-- Add foreign key constraint to graph_node_map.snapshot_id
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conname = 'fk_graph_node_map_snapshot_id'
          AND c.conrelid = 'graph_node_map'::regclass
    ) THEN
        ALTER TABLE graph_node_map ADD CONSTRAINT fk_graph_node_map_snapshot_id
            FOREIGN KEY (snapshot_id) REFERENCES pkg_snapshots(id) ON DELETE SET NULL;
        RAISE NOTICE '✅ Added foreign key constraint fk_graph_node_map_snapshot_id';
    ELSE
        RAISE NOTICE 'ℹ️  Foreign key constraint fk_graph_node_map_snapshot_id already exists';
    END IF;
END $$;

-- ============================================================================
-- PHASE 4: Add indexes for performance
-- ============================================================================

-- Index on tasks.snapshot_id
CREATE INDEX IF NOT EXISTS idx_tasks_snapshot_id ON tasks(snapshot_id);
COMMENT ON INDEX idx_tasks_snapshot_id IS 'Index for filtering tasks by snapshot_id (enables reproducible runs and time travel)';

-- Composite index for snapshot-aware task queries
CREATE INDEX IF NOT EXISTS idx_tasks_snapshot_status ON tasks(snapshot_id, status);
COMMENT ON INDEX idx_tasks_snapshot_status IS 'Composite index for snapshot-scoped task status queries';

-- Index on graph_embeddings_1024.snapshot_id
CREATE INDEX IF NOT EXISTS idx_graph_embeddings_1024_snapshot_id ON graph_embeddings_1024(snapshot_id);
COMMENT ON INDEX idx_graph_embeddings_1024_snapshot_id IS 'Index for filtering graph embeddings by snapshot_id (prevents historical bleed)';

-- Composite index for snapshot-aware embedding queries
CREATE INDEX IF NOT EXISTS idx_graph_embeddings_1024_snapshot_label ON graph_embeddings_1024(snapshot_id, label);
COMMENT ON INDEX idx_graph_embeddings_1024_snapshot_label IS 'Composite index for snapshot-scoped embedding label queries';

-- Index on graph_node_map.snapshot_id
CREATE INDEX IF NOT EXISTS idx_graph_node_map_snapshot_id ON graph_node_map(snapshot_id);
COMMENT ON INDEX idx_graph_node_map_snapshot_id IS 'Index for filtering graph nodes by snapshot_id (enables graph isolation)';

-- Composite index for snapshot-aware node queries
CREATE INDEX IF NOT EXISTS idx_graph_node_map_snapshot_type ON graph_node_map(snapshot_id, node_type);
COMMENT ON INDEX idx_graph_node_map_snapshot_type IS 'Composite index for snapshot-scoped node type queries';

-- ============================================================================
-- PHASE 5: Enforce NOT NULL constraints (after backfill)
-- ============================================================================
-- NOTE: These constraints are enforced only if all rows have been backfilled.
-- If backfill failed (no active snapshot), these will be skipped.

DO $$
DECLARE
    tasks_null_count INTEGER;
    embeddings_null_count INTEGER;
    nodes_null_count INTEGER;
BEGIN
    -- Check if there are any NULL snapshot_id values
    SELECT COUNT(*) INTO tasks_null_count FROM tasks WHERE snapshot_id IS NULL;
    SELECT COUNT(*) INTO embeddings_null_count FROM graph_embeddings_1024 WHERE snapshot_id IS NULL;
    SELECT COUNT(*) INTO nodes_null_count FROM graph_node_map WHERE snapshot_id IS NULL;

    -- Only enforce NOT NULL if all rows have been backfilled
    IF tasks_null_count = 0 THEN
        -- Check if constraint already exists
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint c
            WHERE c.conname = 'chk_tasks_snapshot_id_not_null'
              AND c.conrelid = 'tasks'::regclass
        ) THEN
            ALTER TABLE tasks ALTER COLUMN snapshot_id SET NOT NULL;
            RAISE NOTICE '✅ Enforced NOT NULL constraint on tasks.snapshot_id';
        ELSE
            RAISE NOTICE 'ℹ️  NOT NULL constraint on tasks.snapshot_id already exists';
        END IF;
    ELSE
        RAISE WARNING '⚠️  Cannot enforce NOT NULL on tasks.snapshot_id: % rows still have NULL values', tasks_null_count;
    END IF;

    -- Note: graph_embeddings_1024 and graph_node_map snapshot_id remain nullable
    -- because they may be created before a snapshot exists (e.g., during system bootstrap)
    -- The application layer should ensure snapshot_id is set, but we allow NULL for flexibility.
    
    IF embeddings_null_count > 0 THEN
        RAISE NOTICE 'ℹ️  graph_embeddings_1024.snapshot_id remains nullable (% NULL rows)', embeddings_null_count;
    END IF;
    
    IF nodes_null_count > 0 THEN
        RAISE NOTICE 'ℹ️  graph_node_map.snapshot_id remains nullable (% NULL rows)', nodes_null_count;
    END IF;
END $$;

-- ============================================================================
-- PHASE 6: Add constraint to facts table for PKG-governed facts (P1 Enhancement)
-- ============================================================================
-- This ensures that any fact created by a PKG rule must have a non-null snapshot_id
-- Note: Migration 011 already creates the facts table with snapshot_id column and
--       chk_facts_pkg_requires_triple constraint. This adds an additional constraint
--       requiring snapshot_id when pkg_rule_id is set.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conname = 'chk_facts_pkg_rule_requires_snapshot'
          AND c.conrelid = 'public.facts'::regclass
    ) THEN
        ALTER TABLE public.facts ADD CONSTRAINT chk_facts_pkg_rule_requires_snapshot
            CHECK (pkg_rule_id IS NULL OR snapshot_id IS NOT NULL);
        RAISE NOTICE '✅ Added constraint: PKG-governed facts must have snapshot_id';
    ELSE
        RAISE NOTICE 'ℹ️  Constraint chk_facts_pkg_rule_requires_snapshot already exists';
    END IF;
END $$;

-- ============================================================================
-- PHASE 7: Add comments for documentation
-- ============================================================================

COMMENT ON COLUMN tasks.snapshot_id IS 
    'Reference to PKG snapshot that evaluated/created this task. NOT NULL after backfill. Critical for reproducible runs, multi-world isolation, and time travel debugging.';

COMMENT ON COLUMN graph_embeddings_1024.snapshot_id IS 
    'Reference to PKG snapshot that created this embedding. Nullable to allow bootstrap flexibility. Critical for preventing historical bleed in semantic search.';

COMMENT ON COLUMN graph_node_map.snapshot_id IS 
    'Reference to PKG snapshot that created this graph node. Nullable to allow bootstrap flexibility. Critical for graph isolation and complete rollback.';

-- ============================================================================
-- Verification
-- ============================================================================

DO $$
DECLARE
    tasks_with_snapshot INTEGER;
    embeddings_with_snapshot INTEGER;
    nodes_with_snapshot INTEGER;
    total_tasks INTEGER;
    total_embeddings INTEGER;
    total_nodes INTEGER;
BEGIN
    -- Count rows with snapshot_id
    SELECT COUNT(*) INTO total_tasks FROM tasks;
    SELECT COUNT(*) INTO tasks_with_snapshot FROM tasks WHERE snapshot_id IS NOT NULL;
    
    SELECT COUNT(*) INTO total_embeddings FROM graph_embeddings_1024;
    SELECT COUNT(*) INTO embeddings_with_snapshot FROM graph_embeddings_1024 WHERE snapshot_id IS NOT NULL;
    
    SELECT COUNT(*) INTO total_nodes FROM graph_node_map;
    SELECT COUNT(*) INTO nodes_with_snapshot FROM graph_node_map WHERE snapshot_id IS NOT NULL;

    RAISE NOTICE '';
    RAISE NOTICE '📋 PKG Tasks Snapshot Scoping Migration Summary:';
    RAISE NOTICE '   • tasks: %/% rows have snapshot_id (%.1f%%)', 
        tasks_with_snapshot, total_tasks, 
        CASE WHEN total_tasks > 0 THEN (tasks_with_snapshot::FLOAT / total_tasks * 100) ELSE 0 END;
    RAISE NOTICE '   • graph_embeddings_1024: %/% rows have snapshot_id (%.1f%%)', 
        embeddings_with_snapshot, total_embeddings,
        CASE WHEN total_embeddings > 0 THEN (embeddings_with_snapshot::FLOAT / total_embeddings * 100) ELSE 0 END;
    RAISE NOTICE '   • graph_node_map: %/% rows have snapshot_id (%.1f%%)', 
        nodes_with_snapshot, total_nodes,
        CASE WHEN total_nodes > 0 THEN (nodes_with_snapshot::FLOAT / total_nodes * 100) ELSE 0 END;
    RAISE NOTICE '   • Purpose: Enable reproducible runs, multi-world isolation, time travel debugging, safe retrieval';
    RAISE NOTICE '';
END $$;

COMMIT;
