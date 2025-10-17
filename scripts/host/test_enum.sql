-- Test script to verify taskstatus enum values
-- Run this to check if the enum is working correctly

-- Check if the enum exists and what values it has
SELECT 
    t.typname as enum_name,
    e.enumlabel as enum_value
FROM pg_type t
JOIN pg_enum e ON t.oid = e.enumtypid
WHERE t.typname = 'taskstatus'
ORDER BY e.enumsortorder;

-- Test inserting a task with queued status
INSERT INTO tasks (type, status, description) 
VALUES ('test', 'queued', 'Test task with queued status')
ON CONFLICT DO NOTHING;

-- Verify the task was created
SELECT id, type, status, description, created_at 
FROM tasks 
WHERE type = 'test' 
ORDER BY created_at DESC 
LIMIT 1;

-- Test the claim query that was failing
SELECT id
FROM tasks
WHERE status IN ('queued','retry')
  AND (run_after IS NULL OR run_after <= NOW())
ORDER BY created_at
LIMIT 5;

-- Verify new indexes exist
SELECT 'Verifying new indexes exist:' as info;
SELECT 
    indexname,
    CASE 
        WHEN indexname LIKE 'ix_tasks_%' THEN '✅ NEW NAMING'
        WHEN indexname LIKE 'idx_tasks_%' THEN '⚠️  OLD NAMING'
        ELSE 'ℹ️  OTHER'
    END as naming_status
FROM pg_indexes 
WHERE tablename = 'tasks'
ORDER BY indexname;

-- Verify JSONB conversion
SELECT 'Verifying JSONB conversion:' as info;
SELECT 
    column_name,
    data_type,
    CASE 
        WHEN column_name IN ('params', 'result') AND data_type = 'jsonb' THEN '✅ JSONB'
        WHEN column_name IN ('params', 'result') AND data_type = 'json' THEN '⚠️  JSON (should be JSONB)'
        ELSE 'ℹ️  ' || data_type
    END as jsonb_status
FROM information_schema.columns 
WHERE table_name = 'tasks' 
AND column_name IN ('params', 'result')
ORDER BY column_name;

-- Clean up test data
DELETE FROM tasks WHERE type = 'test';
