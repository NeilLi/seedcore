-- Migration: Consolidate and fix task schema for Coordinator + Dispatcher system
-- This migration ensures consistency and fixes any schema mismatches

-- Step 1: Ensure taskstatus enum has all required values
DO $$
DECLARE
    enum_exists BOOLEAN;
    has_uppercase_values BOOLEAN;
    uppercase_count INTEGER;
BEGIN
    -- Check if the enum exists
    SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'taskstatus') INTO enum_exists;
    
    IF NOT enum_exists THEN
        -- Create the enum with all required values
        CREATE TYPE taskstatus AS ENUM (
            'created',
            'queued', 
            'running',
            'completed',
            'failed',
            'cancelled',
            'retry'
        );
        RAISE NOTICE 'Created taskstatus enum with all required values';
    ELSE
        -- Check if we need to add missing values
        IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = (SELECT oid FROM pg_type WHERE typname = 'taskstatus') AND enumlabel = 'retry') THEN
            ALTER TYPE taskstatus ADD VALUE 'retry';
            RAISE NOTICE 'Added retry to taskstatus enum';
        END IF;
        
        -- Check if there are any uppercase values in the tasks table (cast to text for comparison)
        SELECT EXISTS (
            SELECT 1 FROM tasks 
            WHERE status::text IN ('CREATED', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', 'RETRY')
        ) INTO has_uppercase_values;
        
        IF has_uppercase_values THEN
            -- Convert any existing uppercase values to lowercase (cast to text for comparison)
            UPDATE tasks 
            SET status = CASE 
                WHEN status::text = 'CREATED' THEN 'created'::taskstatus
                WHEN status::text = 'QUEUED' THEN 'queued'::taskstatus
                WHEN status::text = 'RUNNING' THEN 'running'::taskstatus
                WHEN status::text = 'COMPLETED' THEN 'completed'::taskstatus
                WHEN status::text = 'FAILED' THEN 'failed'::taskstatus
                WHEN status::text = 'CANCELLED' THEN 'cancelled'::taskstatus
                WHEN status::text = 'RETRY' THEN 'retry'::taskstatus
                ELSE status  -- keep existing lowercase values
            END
            WHERE status::text IN ('CREATED', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', 'RETRY');
            
            GET DIAGNOSTICS uppercase_count = ROW_COUNT;
            RAISE NOTICE 'Updated % task status values from uppercase to lowercase', uppercase_count;
        ELSE
            RAISE NOTICE 'No uppercase task status values found - enum is already consistent';
        END IF;
    END IF;
END$$;

-- Step 2: Ensure tasks table exists with correct structure
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

-- Step 3: Add any missing columns if they don't exist
DO $$
BEGIN
    -- Add locked_by column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'locked_by') THEN
        ALTER TABLE tasks ADD COLUMN locked_by TEXT NULL;
        RAISE NOTICE 'Added locked_by column to tasks table';
    END IF;
    
    -- Add locked_at column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'locked_at') THEN
        ALTER TABLE tasks ADD COLUMN locked_at TIMESTAMP WITH TIME ZONE NULL;
        RAISE NOTICE 'Added locked_at column to tasks table';
    END IF;
    
    -- Add run_after column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'run_after') THEN
        ALTER TABLE tasks ADD COLUMN run_after TIMESTAMP WITH TIME ZONE NULL;
        RAISE NOTICE 'Added run_after column to tasks table';
    END IF;
    
    -- Add attempts column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'attempts') THEN
        ALTER TABLE tasks ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
        RAISE NOTICE 'Added attempts column to tasks table';
    END IF;
    
    -- Add drift_score column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'drift_score') THEN
        ALTER TABLE tasks ADD COLUMN drift_score DOUBLE PRECISION NOT NULL DEFAULT 0.0;
        RAISE NOTICE 'Added drift_score column to tasks table';
    END IF;
END$$;

-- Step 4: Create or recreate all necessary indexes
DROP INDEX IF EXISTS idx_tasks_status;
CREATE INDEX idx_tasks_status ON tasks(status);

DROP INDEX IF EXISTS idx_tasks_created_at;
CREATE INDEX idx_tasks_created_at ON tasks(created_at);

DROP INDEX IF EXISTS idx_tasks_run_after;
CREATE INDEX idx_tasks_run_after ON tasks(run_after);

DROP INDEX IF EXISTS idx_tasks_locked_at;
CREATE INDEX idx_tasks_locked_at ON tasks(locked_at);

DROP INDEX IF EXISTS idx_tasks_type;
CREATE INDEX idx_tasks_type ON tasks(type);

DROP INDEX IF EXISTS idx_tasks_domain;
CREATE INDEX idx_tasks_domain ON tasks(domain);

-- Create composite index for the claim query (include retry status)
DROP INDEX IF EXISTS idx_tasks_claim;
CREATE INDEX idx_tasks_claim ON tasks(status, run_after, created_at) 
WHERE status IN ('queued', 'failed', 'retry');

-- Step 5: Ensure the updated_at trigger function exists
CREATE OR REPLACE FUNCTION update_tasks_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Step 6: Create or recreate the updated_at trigger
DROP TRIGGER IF EXISTS trigger_tasks_updated_at ON tasks;
CREATE TRIGGER trigger_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_tasks_updated_at();

-- Step 7: Create helper functions for task management
CREATE OR REPLACE FUNCTION create_graph_embed_task(
    start_node_ids INTEGER[],
    k_hops INTEGER DEFAULT 2,
    description TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    task_id UUID;
BEGIN
    INSERT INTO tasks (
        type, 
        status, 
        description,
        params,
        drift_score
    ) VALUES (
        'graph_embed',
        'queued',
        COALESCE(description, format('Embed %s-hop neighborhood around nodes %s', k_hops, array_to_string(start_node_ids, ', '))),
        jsonb_build_object(
            'start_ids', start_node_ids,
            'k', k_hops
        ),
        0.0
    ) RETURNING id INTO task_id;
    
    RETURN task_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION create_graph_rag_task(
    start_node_ids INTEGER[],
    k_hops INTEGER DEFAULT 2,
    top_k INTEGER DEFAULT 10,
    description TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    task_id UUID;
BEGIN
    INSERT INTO tasks (
        type, 
        status, 
        description,
        params,
        drift_score
    ) VALUES (
        'graph_rag_query',
        'queued',
        COALESCE(description, format('RAG query %s-hop neighborhood around nodes %s, top %s', k_hops, array_to_string(start_node_ids, ', '), top_k)),
        jsonb_build_object(
            'start_ids', start_node_ids,
            'k', k_hops,
            'topk', top_k
        ),
        0.0
    ) RETURNING id INTO task_id;
    
    RETURN task_id;
END;
$$ LANGUAGE plpgsql;

-- Step 8: Create a view for monitoring tasks
-- Drop the existing view first to avoid column rename conflicts
DROP VIEW IF EXISTS graph_tasks;
CREATE VIEW graph_tasks AS
SELECT 
    id,
    type,
    status,
    attempts,
    locked_by,
    locked_at,
    run_after,
    params,
    result,
    error,
    created_at,
    updated_at,
    drift_score,
    CASE 
        WHEN status = 'completed' THEN '✅'
        WHEN status = 'running' THEN '🔄'
        WHEN status = 'queued' THEN '⏳'
        WHEN status = 'failed' THEN '❌'
        WHEN status = 'retry' THEN '🔄'
        WHEN status = 'created' THEN '📝'
        WHEN status = 'cancelled' THEN '❌'
        ELSE '❓'
    END as status_emoji
FROM tasks 
WHERE type IN ('graph_embed', 'graph_rag_query')
ORDER BY updated_at DESC;

-- Step 9: Add comprehensive comments
COMMENT ON TYPE taskstatus IS 'Task status enum with all required values for the Coordinator + Dispatcher system';
COMMENT ON TABLE tasks IS 'Tasks table with complete schema for Coordinator + Dispatcher system';
COMMENT ON COLUMN tasks.locked_by IS 'Identifier of the dispatcher that claimed this task';
COMMENT ON COLUMN tasks.locked_at IS 'Timestamp when the task was claimed by a dispatcher';
COMMENT ON COLUMN tasks.run_after IS 'Timestamp after which the task can be retried (for retry status)';
COMMENT ON COLUMN tasks.attempts IS 'Number of execution attempts (used for backoff logic)';
COMMENT ON COLUMN tasks.drift_score IS 'Drift score for OCPS valve decision making (0.0 = fast path, >=0.5 = escalation)';

-- Step 10: Verify the schema is correct
DO $$
BEGIN
    RAISE NOTICE 'Task schema consolidation completed successfully';
    RAISE NOTICE 'Tasks table columns: %', (
        SELECT string_agg(column_name, ', ' ORDER BY ordinal_position)
        FROM information_schema.columns 
        WHERE table_name = 'tasks'
    );
    RAISE NOTICE 'Taskstatus enum values: %', (
        SELECT string_agg(enumlabel, ', ' ORDER BY enumsortorder)
        FROM pg_enum 
        WHERE enumtypid = (SELECT oid FROM pg_type WHERE typname = 'taskstatus')
    );
END$$;
