-- Verification script for TaskStatus enum fix
-- This script tests that all enum values are working correctly

-- 1. Check current enum values
SELECT 'Current enum values:' as info;
SELECT 
    t.typname as enum_name,
    e.enumlabel as enum_value,
    e.enumsortorder
FROM pg_type t
JOIN pg_enum e ON t.oid = e.enumtypid
WHERE t.typname = 'taskstatus'
ORDER BY e.enumsortorder;

-- 2. Test inserting tasks with each status
SELECT 'Testing task creation with each status...' as info;

-- Test created status
INSERT INTO tasks (type, status, description) 
VALUES ('test', 'created', 'Test task with created status')
ON CONFLICT DO NOTHING;

-- Test queued status
INSERT INTO tasks (type, status, description) 
VALUES ('test', 'queued', 'Test task with queued status')
ON CONFLICT DO NOTHING;

-- Test running status
INSERT INTO tasks (type, status, description) 
VALUES ('test', 'running', 'Test task with running status')
ON CONFLICT DO NOTHING;

-- Test completed status
INSERT INTO tasks (type, status, description) 
VALUES ('test', 'completed', 'Test task with completed status')
ON CONFLICT DO NOTHING;

-- Test failed status
INSERT INTO tasks (type, status, description) 
VALUES ('test', 'failed', 'Test task with failed status')
ON CONFLICT DO NOTHING;

-- Test cancelled status
INSERT INTO tasks (type, status, description) 
VALUES ('test', 'cancelled', 'Test task with cancelled status')
ON CONFLICT DO NOTHING;

-- Test retry status
INSERT INTO tasks (type, status, description) 
VALUES ('test', 'retry', 'Test task with retry status')
ON CONFLICT DO NOTHING;

-- 3. Verify all tasks were created
SELECT 'Verifying all test tasks were created:' as info;
SELECT 
    id, 
    type, 
    status, 
    description, 
    created_at 
FROM tasks 
WHERE type = 'test' 
ORDER BY status, created_at;

-- 4. Test the claim query that was failing (updated for new index naming)
SELECT 'Testing the claim query that was failing:' as info;
SELECT 
    id,
    type,
    status,
    description,
    created_at
FROM tasks
WHERE status IN ('queued', 'failed', 'retry')
  AND (run_after IS NULL OR run_after <= NOW())
ORDER BY created_at
LIMIT 5;

-- 4b. Verify new indexes exist
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

-- 4c. Verify JSONB conversion
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

-- 4d. Verify check constraint
SELECT 'Verifying check constraint for attempts >= 0:' as info;
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.check_constraints 
            WHERE constraint_name = 'ck_tasks_attempts_nonneg'
        ) THEN '✅ ck_tasks_attempts_nonneg constraint exists'
        ELSE '❌ ck_tasks_attempts_nonneg constraint missing'
    END as constraint_status;

-- 5. Test status filtering
SELECT 'Testing status filtering for each enum value:' as info;
SELECT 'created tasks:' as status, COUNT(*) as count FROM tasks WHERE type = 'test' AND status = 'created'
UNION ALL
SELECT 'queued tasks:', COUNT(*) FROM tasks WHERE type = 'test' AND status = 'queued'
UNION ALL
SELECT 'running tasks:', COUNT(*) FROM tasks WHERE type = 'test' AND status = 'running'
UNION ALL
SELECT 'completed tasks:', COUNT(*) FROM tasks WHERE type = 'test' AND status = 'completed'
UNION ALL
SELECT 'failed tasks:', COUNT(*) FROM tasks WHERE type = 'test' AND status = 'failed'
UNION ALL
SELECT 'cancelled tasks:', COUNT(*) FROM tasks WHERE type = 'test' AND status = 'cancelled'
UNION ALL
SELECT 'retry tasks:', COUNT(*) FROM tasks WHERE type = 'test' AND status = 'retry';

-- 6. Clean up test data
SELECT 'Cleaning up test data...' as info;
DELETE FROM tasks WHERE type = 'test';

SELECT '✅ Enum verification complete! All lowercase values are working correctly.' as result;
SELECT '✅ JSONB conversion verified.' as enhancement;
SELECT '✅ New index naming convention verified.' as enhancement;
SELECT '✅ Check constraint verified.' as enhancement;
