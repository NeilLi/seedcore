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
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create indexes for performance (matching model specification)
CREATE INDEX IF NOT EXISTS ix_tasks_status_runafter ON tasks (status, run_after);
CREATE INDEX IF NOT EXISTS ix_tasks_created_at_desc ON tasks (created_at);
CREATE INDEX IF NOT EXISTS ix_tasks_type ON tasks (type);
CREATE INDEX IF NOT EXISTS ix_tasks_domain ON tasks (domain);

-- Create GIN index for params JSONB column (enables filtering into params)
CREATE INDEX IF NOT EXISTS ix_tasks_params_gin ON tasks USING gin (params);

-- Add check constraint for attempts >= 0
ALTER TABLE tasks
ADD CONSTRAINT ck_tasks_attempts_nonneg CHECK (attempts >= 0);

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

-- Add comments for documentation
COMMENT ON TABLE tasks IS 'Tasks table for Coordinator + Dispatcher system';
COMMENT ON COLUMN tasks.id IS 'Unique task identifier';
COMMENT ON COLUMN tasks.status IS 'Current status of the task';
COMMENT ON COLUMN tasks.attempts IS 'Number of execution attempts';
COMMENT ON COLUMN tasks.locked_by IS 'Identifier of the dispatcher that claimed this task';
COMMENT ON COLUMN tasks.locked_at IS 'Timestamp when the task was claimed';
COMMENT ON COLUMN tasks.run_after IS 'Timestamp after which the task can be retried';
COMMENT ON COLUMN tasks.type IS 'Type/category of the task';
COMMENT ON COLUMN tasks.description IS 'Human-readable description of the task';
COMMENT ON COLUMN tasks.domain IS 'Domain context for the task';
COMMENT ON COLUMN tasks.drift_score IS 'Drift score for OCPS valve decision making';
COMMENT ON COLUMN tasks.params IS 'Task parameters as JSON';
COMMENT ON COLUMN tasks.result IS 'Task execution result as JSON';
COMMENT ON COLUMN tasks.error IS 'Error message if task failed';
COMMENT ON COLUMN tasks.created_at IS 'Timestamp when task was created';
COMMENT ON COLUMN tasks.updated_at IS 'Timestamp when task was last updated';
