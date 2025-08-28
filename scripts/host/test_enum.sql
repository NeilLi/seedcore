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

-- Clean up test data
DELETE FROM tasks WHERE type = 'test';
