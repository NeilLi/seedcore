-- Migration: Create tasks table for Coordinator + Dispatcher system
-- This table stores tasks that will be processed by the Dispatcher actors

-- Create the taskstatus enum type (idempotent)
DO $$
BEGIN
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
        RAISE NOTICE 'Created taskstatus enum type';
    ELSE
        RAISE NOTICE 'taskstatus enum type already exists, skipping creation';
    END IF;
END$$;

-- Create tasks table
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
    owner_id TEXT NULL,
    lease_expires_at TIMESTAMP WITH TIME ZONE NULL,
    last_heartbeat TIMESTAMP WITH TIME ZONE NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Add lease-related columns if they don't exist (for idempotency)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'tasks' AND column_name = 'owner_id') THEN
        ALTER TABLE tasks ADD COLUMN owner_id TEXT NULL;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'tasks' AND column_name = 'lease_expires_at') THEN
        ALTER TABLE tasks ADD COLUMN lease_expires_at TIMESTAMP WITH TIME ZONE NULL;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'tasks' AND column_name = 'last_heartbeat') THEN
        ALTER TABLE tasks ADD COLUMN last_heartbeat TIMESTAMP WITH TIME ZONE NULL;
    END IF;
END $$;

-- Create indexes for performance (matching model specification)
CREATE INDEX IF NOT EXISTS ix_tasks_status_runafter ON tasks (status, run_after);
CREATE INDEX IF NOT EXISTS ix_tasks_created_at_desc ON tasks (created_at);
CREATE INDEX IF NOT EXISTS ix_tasks_type ON tasks (type);
CREATE INDEX IF NOT EXISTS ix_tasks_domain ON tasks (domain);

-- Create GIN index for params JSONB column (enables filtering into params)
CREATE INDEX IF NOT EXISTS ix_tasks_params_gin ON tasks USING gin (params);

-- Create targeted JSONB path indexes to accelerate routing filters
-- Note: Use -> instead of ->> to keep JSONB type for GIN index
CREATE INDEX IF NOT EXISTS ix_tasks_params_routing_spec ON tasks
USING gin ((params -> 'routing' -> 'required_specialization'));

CREATE INDEX IF NOT EXISTS ix_tasks_params_routing_priority ON tasks
USING gin ((params #> '{routing,hints,priority}'));

CREATE INDEX IF NOT EXISTS ix_tasks_params_routing_deadline ON tasks
USING gin ((params #> '{routing,hints,deadline_at}'));

-- Create indexes for lease-related columns
CREATE INDEX IF NOT EXISTS idx_tasks_owner_id ON tasks(owner_id);
CREATE INDEX IF NOT EXISTS idx_tasks_lease_expires_at ON tasks(lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_tasks_last_heartbeat ON tasks(last_heartbeat);

-- Create composite index for stale task queries
CREATE INDEX IF NOT EXISTS idx_tasks_stale_running ON tasks(status, updated_at, last_heartbeat, lease_expires_at) 
WHERE status = 'running';

-- Create composite index for owner-based queries
CREATE INDEX IF NOT EXISTS idx_tasks_owner_status ON tasks(owner_id, status, last_heartbeat) 
WHERE owner_id IS NOT NULL;

-- Add check constraint for attempts >= 0 (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint 
                   WHERE conname = 'ck_tasks_attempts_nonneg') THEN
        ALTER TABLE tasks
        ADD CONSTRAINT ck_tasks_attempts_nonneg CHECK (attempts >= 0);
    END IF;
END $$;

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

-- Create view for graph tasks
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

-- Create helper functions for graph tasks
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

-- Create helper function for emergency cleanup of stale RUNNING tasks
CREATE OR REPLACE FUNCTION cleanup_stale_running_tasks(
    stale_minutes INTEGER DEFAULT 15,
    max_attempts INTEGER DEFAULT 3
) RETURNS INTEGER AS $$
DECLARE
    affected_rows INTEGER;
BEGIN
    -- Requeue RUNNING tasks older than stale_minutes (no owner/liveness check, just time-based)
    UPDATE tasks
    SET status = 'queued',
        attempts = attempts + 1,
        owner_id = NULL,
        lease_expires_at = NULL,
        updated_at = NOW(),
        error = COALESCE(error,'') || ' | requeued by admin: stale RUNNING'
    WHERE status = 'running'
      AND updated_at < NOW() - (stale_minutes || ' minutes')::interval
      AND (attempts IS NULL OR attempts < max_attempts);
    
    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    
    -- Mark as failed if max attempts exceeded
    UPDATE tasks
    SET status = 'failed',
        error = COALESCE(error,'') || ' | failed by admin: max requeues exceeded',
        updated_at = NOW()
    WHERE status = 'running'
      AND updated_at < NOW() - (stale_minutes || ' minutes')::interval
      AND attempts >= max_attempts;
    
    RETURN affected_rows;
END;
$$ LANGUAGE plpgsql;

-- Add comments for documentation
COMMENT ON TYPE taskstatus IS 'Task status enum with all required values for the Coordinator + Dispatcher system';
COMMENT ON TABLE tasks IS 'Tasks table with complete schema for Coordinator + Dispatcher system';
COMMENT ON COLUMN tasks.id IS 'Task UUID (v4)';
COMMENT ON COLUMN tasks.type IS 'Task type (short code, indexed)';
COMMENT ON COLUMN tasks.domain IS 'Logical domain/namespace for routing/policy';
COMMENT ON COLUMN tasks.description IS 'Optional human-readable description/input text';
COMMENT ON COLUMN tasks.params IS 'Input parameters including fast_eventizer outputs (JSONB)';
COMMENT ON COLUMN tasks.result IS 'Unified TaskResult schema (JSONB)';
COMMENT ON COLUMN tasks.error IS 'Error message/details on failure';
COMMENT ON COLUMN tasks.status IS 'Lifecycle status';
COMMENT ON COLUMN tasks.attempts IS 'Number of execution attempts (used for backoff logic)';
COMMENT ON COLUMN tasks.locked_by IS 'Identifier of the dispatcher that claimed this task';
COMMENT ON COLUMN tasks.locked_at IS 'Timestamp when the task was claimed by a dispatcher';
COMMENT ON COLUMN tasks.run_after IS 'Timestamp after which the task can be retried (for retry status)';
COMMENT ON COLUMN tasks.drift_score IS 'Drift score for OCPS valve decision making (0.0 = fast path, >=0.5 = escalation)';
COMMENT ON COLUMN tasks.owner_id IS 'Identifier of the dispatcher/organism that claimed this task (for lease tracking)';
COMMENT ON COLUMN tasks.lease_expires_at IS 'Timestamp when the task lease expires (for automatic requeuing)';
COMMENT ON COLUMN tasks.last_heartbeat IS 'Timestamp of the last heartbeat from the task owner (for liveness detection)';
COMMENT ON COLUMN tasks.created_at IS 'Creation time (UTC)';
COMMENT ON COLUMN tasks.updated_at IS 'Last update time (UTC)';
COMMENT ON FUNCTION cleanup_stale_running_tasks IS 'Emergency cleanup function to requeue stale RUNNING tasks';
