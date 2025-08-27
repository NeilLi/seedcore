-- Migration: Fix taskstatus enum to match code expectations
-- This migration ensures consistency with existing lowercase enum values
-- and adds missing status values if needed

-- First, check if we need to fix anything
DO $$
BEGIN
    -- If the enum doesn't exist, create it with correct lowercase values
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'taskstatus') THEN
        CREATE TYPE taskstatus AS ENUM (
            'created',
            'queued', 
            'running',
            'completed',
            'failed',
            'cancelled',
            'retry'
        );
        RAISE NOTICE 'Created taskstatus enum with correct lowercase values';
    ELSE
        -- Check if we need to add missing values
        IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = (SELECT oid FROM pg_type WHERE typname = 'taskstatus') AND enumlabel = 'retry') THEN
            ALTER TYPE taskstatus ADD VALUE 'retry';
            RAISE NOTICE 'Added retry to taskstatus enum';
        END IF;
        
        -- Ensure any existing uppercase values are converted to lowercase
        UPDATE tasks 
        SET status = CASE 
            WHEN status = 'CREATED' THEN 'created'
            WHEN status = 'QUEUED' THEN 'queued'
            WHEN status = 'RUNNING' THEN 'running'
            WHEN status = 'COMPLETED' THEN 'completed'
            WHEN status = 'FAILED' THEN 'failed'
            WHEN status = 'CANCELLED' THEN 'cancelled'
            WHEN status = 'RETRY' THEN 'retry'
            ELSE status  -- keep existing lowercase values
        END
        WHERE status IN ('CREATED', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', 'RETRY');
        
        RAISE NOTICE 'Updated existing task status values to lowercase';
    END IF;
END$$;

-- Now ensure the tasks table exists with the correct structure
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

-- Update the view to use the lowercase enum values
CREATE OR REPLACE VIEW graph_tasks AS
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

-- Update the helper functions to use the lowercase enum values
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
        params
    ) VALUES (
        'graph_embed',
        'queued',
        COALESCE(description, format('Embed %s-hop neighborhood around nodes %s', k_hops, array_to_string(start_node_ids, ', '))),
        jsonb_build_object(
            'start_ids', start_node_ids,
            'k', k_hops
        )
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
        params
    ) VALUES (
        'graph_rag_query',
        'queued',
        COALESCE(description, format('RAG query %s-hop neighborhood around nodes %s, top %s', k_hops, array_to_string(start_node_ids, ', '), top_k)),
        jsonb_build_object(
            'start_ids', start_node_ids,
            'k', k_hops,
            'topk', top_k
        )
    ) RETURNING id INTO task_id;
    
    RETURN task_id;
END;
$$ LANGUAGE plpgsql;

-- Add comments for the updated enum
COMMENT ON TYPE taskstatus IS 'Task status enum with lowercase values to match existing database schema';
COMMENT ON TABLE tasks IS 'Tasks table with consistent lowercase taskstatus enum';
