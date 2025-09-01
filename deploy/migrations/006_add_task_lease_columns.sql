-- Migration: Add task lease columns for stale task recovery
-- This migration adds columns needed for task leases and heartbeat tracking

-- Add lease-related columns if they don't exist
DO $$
BEGIN
    -- Add owner_id column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'owner_id') THEN
        ALTER TABLE tasks ADD COLUMN owner_id TEXT NULL;
        RAISE NOTICE 'Added owner_id column to tasks table';
    END IF;
    
    -- Add lease_expires_at column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'lease_expires_at') THEN
        ALTER TABLE tasks ADD COLUMN lease_expires_at TIMESTAMP WITH TIME ZONE NULL;
        RAISE NOTICE 'Added lease_expires_at column to tasks table';
    END IF;
    
    -- Add last_heartbeat column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'last_heartbeat') THEN
        ALTER TABLE tasks ADD COLUMN last_heartbeat TIMESTAMP WITH TIME ZONE NULL;
        RAISE NOTICE 'Added last_heartbeat column to tasks table';
    END IF;
END$$;

-- Create indexes for the new columns
CREATE INDEX IF NOT EXISTS idx_tasks_owner_id ON tasks(owner_id);
CREATE INDEX IF NOT EXISTS idx_tasks_lease_expires_at ON tasks(lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_tasks_last_heartbeat ON tasks(last_heartbeat);

-- Create composite index for stale task queries
CREATE INDEX IF NOT EXISTS idx_tasks_stale_running ON tasks(status, updated_at, last_heartbeat, lease_expires_at) 
WHERE status = 'running';

-- Create composite index for owner-based queries
CREATE INDEX IF NOT EXISTS idx_tasks_owner_status ON tasks(owner_id, status, last_heartbeat) 
WHERE owner_id IS NOT NULL;

-- Add comments for documentation
COMMENT ON COLUMN tasks.owner_id IS 'Identifier of the dispatcher/organism that claimed this task (for lease tracking)';
COMMENT ON COLUMN tasks.lease_expires_at IS 'Timestamp when the task lease expires (for automatic requeuing)';
COMMENT ON COLUMN tasks.last_heartbeat IS 'Timestamp of the last heartbeat from the task owner (for liveness detection)';

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

COMMENT ON FUNCTION cleanup_stale_running_tasks IS 'Emergency cleanup function to requeue stale RUNNING tasks';

-- Verify the schema is correct
DO $$
BEGIN
    RAISE NOTICE 'Task lease columns migration completed successfully';
    RAISE NOTICE 'New columns added: owner_id, lease_expires_at, last_heartbeat';
    RAISE NOTICE 'New indexes created for lease tracking and stale task detection';
END$$;
