-- Migration: Task schema enhancements to match latest model
-- This migration implements JSONB conversion, new indexes, and constraints
-- as specified in the task model enhancements

-- Step 1: Convert JSON to JSONB if needed (safe in PG 9.4+)
DO $$
BEGIN
    -- Check if params column is JSON and convert to JSONB
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'tasks' 
        AND column_name = 'params' 
        AND data_type = 'json'
    ) THEN
        ALTER TABLE tasks
        ALTER COLUMN params TYPE JSONB USING params::jsonb;
        RAISE NOTICE 'Converted params column from JSON to JSONB';
    ELSE
        RAISE NOTICE 'params column is already JSONB or does not exist';
    END IF;
    
    -- Check if result column is JSON and convert to JSONB
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'tasks' 
        AND column_name = 'result' 
        AND data_type = 'json'
    ) THEN
        ALTER TABLE tasks
        ALTER COLUMN result TYPE JSONB USING result::jsonb;
        RAISE NOTICE 'Converted result column from JSON to JSONB';
    ELSE
        RAISE NOTICE 'result column is already JSONB or does not exist';
    END IF;
END$$;

-- Step 2: Add description column if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'tasks' 
        AND column_name = 'description'
    ) THEN
        ALTER TABLE tasks
        ADD COLUMN description TEXT;
        RAISE NOTICE 'Added description column to tasks table';
    ELSE
        RAISE NOTICE 'description column already exists';
    END IF;
END$$;

-- Step 3: Add check constraint for attempts >= 0
DO $$
BEGIN
    -- Drop existing constraint if it exists with different name
    IF EXISTS (
        SELECT 1 FROM information_schema.check_constraints 
        WHERE constraint_name = 'ck_tasks_attempts_nonneg'
    ) THEN
        ALTER TABLE tasks DROP CONSTRAINT ck_tasks_attempts_nonneg;
        RAISE NOTICE 'Dropped existing ck_tasks_attempts_nonneg constraint';
    END IF;
    
    -- Add the constraint
    ALTER TABLE tasks
    ADD CONSTRAINT ck_tasks_attempts_nonneg CHECK (attempts >= 0);
    RAISE NOTICE 'Added ck_tasks_attempts_nonneg constraint';
EXCEPTION
    WHEN duplicate_object THEN
        RAISE NOTICE 'Constraint ck_tasks_attempts_nonneg already exists';
END$$;

-- Step 4: Drop old indexes and create new ones to match model specification
-- Drop old indexes that don't match the new naming convention
DROP INDEX IF EXISTS idx_tasks_status;
DROP INDEX IF EXISTS idx_tasks_created_at;
DROP INDEX IF EXISTS idx_tasks_run_after;
DROP INDEX IF EXISTS idx_tasks_locked_at;
DROP INDEX IF EXISTS idx_tasks_type;
DROP INDEX IF EXISTS idx_tasks_domain;
DROP INDEX IF EXISTS idx_tasks_claim;

-- Create new indexes to match the model specification
CREATE INDEX IF NOT EXISTS ix_tasks_status_runafter ON tasks (status, run_after);
CREATE INDEX IF NOT EXISTS ix_tasks_created_at_desc ON tasks (created_at);
CREATE INDEX IF NOT EXISTS ix_tasks_type ON tasks (type);
CREATE INDEX IF NOT EXISTS ix_tasks_domain ON tasks (domain);

-- Create GIN index for params JSONB column (enables filtering into params)
CREATE INDEX IF NOT EXISTS ix_tasks_params_gin ON tasks USING gin (params);

-- Optional: Create GIN index for result JSONB column (commented out as per model)
-- CREATE INDEX IF NOT EXISTS ix_tasks_result_gin ON tasks USING gin (result);

-- Step 5: Update column comments to match the model
COMMENT ON COLUMN tasks.id IS 'Task UUID (v4)';
COMMENT ON COLUMN tasks.type IS 'Task type (short code, indexed)';
COMMENT ON COLUMN tasks.domain IS 'Logical domain/namespace for routing/policy';
COMMENT ON COLUMN tasks.description IS 'Optional human-readable description/input text';
COMMENT ON COLUMN tasks.params IS 'Input parameters including fast_eventizer outputs (JSONB)';
COMMENT ON COLUMN tasks.result IS 'Unified TaskResult schema (JSONB)';
COMMENT ON COLUMN tasks.error IS 'Error message/details on failure';
COMMENT ON COLUMN tasks.status IS 'Lifecycle status';
COMMENT ON COLUMN tasks.attempts IS 'Number of execution attempts';
COMMENT ON COLUMN tasks.locked_by IS 'Lock owner (worker id) if any';
COMMENT ON COLUMN tasks.locked_at IS 'When the lock was taken';
COMMENT ON COLUMN tasks.run_after IS 'Earliest time this task may be scheduled';
COMMENT ON COLUMN tasks.drift_score IS 'Model/policy drift indicator (0..1)';
COMMENT ON COLUMN tasks.created_at IS 'Creation time (UTC)';
COMMENT ON COLUMN tasks.updated_at IS 'Last update time (UTC)';

-- Step 6: Verify the schema matches the model
DO $$
DECLARE
    column_count INTEGER;
    index_count INTEGER;
    constraint_count INTEGER;
BEGIN
    -- Count columns
    SELECT COUNT(*) INTO column_count
    FROM information_schema.columns 
    WHERE table_name = 'tasks';
    
    -- Count indexes
    SELECT COUNT(*) INTO index_count
    FROM pg_indexes 
    WHERE tablename = 'tasks' 
    AND indexname LIKE 'ix_tasks_%';
    
    -- Count check constraints
    SELECT COUNT(*) INTO constraint_count
    FROM information_schema.check_constraints 
    WHERE constraint_name = 'ck_tasks_attempts_nonneg';
    
    RAISE NOTICE 'Task schema enhancements completed successfully';
    RAISE NOTICE 'Columns: %, Indexes: %, Check constraints: %', column_count, index_count, constraint_count;
    
    -- List all indexes
    RAISE NOTICE 'Indexes created:';
    FOR rec IN 
        SELECT indexname 
        FROM pg_indexes 
        WHERE tablename = 'tasks' 
        AND indexname LIKE 'ix_tasks_%'
        ORDER BY indexname
    LOOP
        RAISE NOTICE '  - %', rec.indexname;
    END LOOP;
END$$;
