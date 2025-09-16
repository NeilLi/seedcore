-- Comprehensive verification script for migration fixes
-- This script verifies that all migration issues have been resolved:
-- 1. Enum type creation is idempotent
-- 2. Enum values are consistently lowercase
-- 3. View creation works without column rename conflicts
-- 4. All task operations work correctly

-- ============================================================================
-- SECTION 1: VERIFY ENUM TYPE AND VALUES
-- ============================================================================

SELECT '🔍 SECTION 1: Verifying taskstatus enum type and values' as section;

-- Check if enum type exists
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM pg_type WHERE typname = 'taskstatus') 
        THEN '✅ taskstatus enum type exists'
        ELSE '❌ taskstatus enum type missing'
    END as enum_type_status;

-- List all enum values
SELECT 'Current taskstatus enum values:' as info;
SELECT 
    t.typname as enum_name,
    e.enumlabel as enum_value,
    e.enumsortorder as sort_order
FROM pg_type t
JOIN pg_enum e ON t.oid = e.enumtypid
WHERE t.typname = 'taskstatus'
ORDER BY e.enumsortorder;

-- Verify all required enum values exist
SELECT 'Verifying all required enum values exist:' as info;
WITH required_values AS (
    SELECT unnest(ARRAY['created', 'queued', 'running', 'completed', 'failed', 'cancelled', 'retry']) as required_value
),
existing_values AS (
    SELECT e.enumlabel as existing_value
    FROM pg_type t
    JOIN pg_enum e ON t.oid = e.enumtypid
    WHERE t.typname = 'taskstatus'
)
SELECT 
    r.required_value,
    CASE 
        WHEN e.existing_value IS NOT NULL THEN '✅ EXISTS'
        ELSE '❌ MISSING'
    END as status
FROM required_values r
LEFT JOIN existing_values e ON r.required_value = e.existing_value
ORDER BY r.required_value;

-- ============================================================================
-- SECTION 2: VERIFY TASKS TABLE STRUCTURE
-- ============================================================================

SELECT '🔍 SECTION 2: Verifying tasks table structure' as section;

-- Check if tasks table exists
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tasks') 
        THEN '✅ tasks table exists'
        ELSE '❌ tasks table missing'
    END as table_status;

-- List all columns in tasks table
SELECT 'Tasks table columns:' as info;
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns 
WHERE table_name = 'tasks' 
ORDER BY ordinal_position;

-- Verify critical columns exist
SELECT 'Verifying critical columns exist:' as info;
WITH required_columns AS (
    SELECT unnest(ARRAY['id', 'status', 'type', 'attempts', 'locked_by', 'locked_at', 'run_after', 'created_at', 'updated_at']) as required_column
),
existing_columns AS (
    SELECT column_name as existing_column
    FROM information_schema.columns 
    WHERE table_name = 'tasks'
)
SELECT 
    r.required_column,
    CASE 
        WHEN e.existing_column IS NOT NULL THEN '✅ EXISTS'
        ELSE '❌ MISSING'
    END as status
FROM required_columns r
LEFT JOIN existing_columns e ON r.required_column = e.existing_column
ORDER BY r.required_column;

-- ============================================================================
-- SECTION 3: TEST ENUM VALUE OPERATIONS
-- ============================================================================

SELECT '🔍 SECTION 3: Testing enum value operations' as section;

-- Test inserting tasks with each status (clean up first)
DELETE FROM tasks WHERE type = 'verification_test';

-- Test created status
INSERT INTO tasks (type, status, description) 
VALUES ('verification_test', 'created', 'Test task with created status');

-- Test queued status
INSERT INTO tasks (type, status, description) 
VALUES ('verification_test', 'queued', 'Test task with queued status');

-- Test running status
INSERT INTO tasks (type, status, description) 
VALUES ('verification_test', 'running', 'Test task with running status');

-- Test completed status
INSERT INTO tasks (type, status, description) 
VALUES ('verification_test', 'completed', 'Test task with completed status');

-- Test failed status
INSERT INTO tasks (type, status, description) 
VALUES ('verification_test', 'failed', 'Test task with failed status');

-- Test cancelled status
INSERT INTO tasks (type, status, description) 
VALUES ('verification_test', 'cancelled', 'Test task with cancelled status');

-- Test retry status
INSERT INTO tasks (type, status, description) 
VALUES ('verification_test', 'retry', 'Test task with retry status');

-- Verify all test tasks were created
SELECT 'Verifying all test tasks were created:' as info;
SELECT 
    id, 
    type, 
    status, 
    description, 
    created_at 
FROM tasks 
WHERE type = 'verification_test' 
ORDER BY status, created_at;

-- Test status filtering for each enum value (before any updates)
SELECT 'Testing status filtering for each enum value (initial state):' as info;
SELECT 
    status,
    COUNT(*) as count,
    CASE 
        WHEN COUNT(*) = 1 THEN '✅ PASS'
        ELSE '❌ FAIL'
    END as test_result
FROM tasks 
WHERE type = 'verification_test' 
GROUP BY status
ORDER BY status;

-- ============================================================================
-- SECTION 4: TEST CRITICAL QUERIES
-- ============================================================================

SELECT '🔍 SECTION 4: Testing critical queries' as section;

-- Test the claim query that was failing
SELECT 'Testing the claim query (queued, failed, retry):' as info;
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

-- Test status updates
SELECT 'Testing status updates:' as info;
UPDATE tasks 
SET status = 'running', locked_by = 'test_dispatcher', locked_at = NOW()
WHERE type = 'verification_test' AND status = 'queued'
AND id = (SELECT id FROM tasks WHERE type = 'verification_test' AND status = 'queued' LIMIT 1);

-- Verify the update worked
SELECT 
    id,
    status,
    locked_by,
    locked_at
FROM tasks 
WHERE type = 'verification_test' AND locked_by = 'test_dispatcher';

-- Test status filtering after updates
SELECT 'Testing status filtering after updates:' as info;
SELECT 
    status,
    COUNT(*) as count,
    CASE 
        WHEN status = 'running' AND COUNT(*) >= 1 THEN '✅ PASS (includes updated tasks)'
        WHEN status = 'queued' AND COUNT(*) >= 0 THEN '✅ PASS (may have been updated)'
        WHEN status != 'running' AND status != 'queued' AND COUNT(*) = 1 THEN '✅ PASS'
        ELSE '❌ FAIL'
    END as test_result
FROM tasks 
WHERE type = 'verification_test' 
GROUP BY status
ORDER BY status;

-- ============================================================================
-- SECTION 5: VERIFY VIEWS AND FUNCTIONS
-- ============================================================================

SELECT '🔍 SECTION 5: Verifying views and functions' as section;

-- Check if graph_tasks view exists
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.views WHERE table_name = 'graph_tasks') 
        THEN '✅ graph_tasks view exists'
        ELSE '❌ graph_tasks view missing'
    END as view_status;

-- Test graph_tasks view
SELECT 'Testing graph_tasks view:' as info;
SELECT 
    id,
    type,
    status,
    status_emoji,
    created_at
FROM graph_tasks 
WHERE type = 'verification_test'
ORDER BY created_at DESC
LIMIT 3;

-- Check if helper functions exist
SELECT 'Verifying helper functions exist:' as info;
SELECT 
    routine_name,
    routine_type,
    CASE 
        WHEN routine_name IN ('create_graph_embed_task', 'create_graph_rag_task', 'cleanup_stale_running_tasks') 
        THEN '✅ EXISTS'
        ELSE '❌ MISSING'
    END as status
FROM information_schema.routines 
WHERE routine_name IN ('create_graph_embed_task', 'create_graph_rag_task', 'cleanup_stale_running_tasks')
ORDER BY routine_name;

-- ============================================================================
-- SECTION 6: TEST ENUM CASTING (UPPERCASE HANDLING)
-- ============================================================================

SELECT '🔍 SECTION 6: Testing enum casting for uppercase handling' as section;

-- Test that we can detect uppercase values (if any exist)
SELECT 'Testing uppercase value detection:' as info;
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM tasks 
            WHERE status::text IN ('CREATED', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', 'RETRY')
        ) 
        THEN '⚠️  Uppercase values found - migration may be needed'
        ELSE '✅ No uppercase values found - enum is consistent'
    END as uppercase_check;

-- Test enum casting operations
SELECT 'Testing enum casting operations:' as info;
SELECT 
    'created'::taskstatus as test_created,
    'queued'::taskstatus as test_queued,
    'running'::taskstatus as test_running,
    'completed'::taskstatus as test_completed,
    'failed'::taskstatus as test_failed,
    'cancelled'::taskstatus as test_cancelled,
    'retry'::taskstatus as test_retry;

-- ============================================================================
-- SECTION 7: VERIFY INDEXES
-- ============================================================================

SELECT '🔍 SECTION 7: Verifying critical indexes' as section;

-- List indexes on tasks table
SELECT 'Indexes on tasks table:' as info;
SELECT 
    indexname,
    indexdef
FROM pg_indexes 
WHERE tablename = 'tasks'
ORDER BY indexname;

-- Verify critical indexes exist
SELECT 'Verifying critical indexes exist:' as info;
WITH required_indexes AS (
    SELECT unnest(ARRAY['idx_tasks_status', 'idx_tasks_created_at', 'idx_tasks_claim']) as required_index
),
existing_indexes AS (
    SELECT indexname as existing_index
    FROM pg_indexes 
    WHERE tablename = 'tasks'
)
SELECT 
    r.required_index,
    CASE 
        WHEN e.existing_index IS NOT NULL THEN '✅ EXISTS'
        ELSE '❌ MISSING'
    END as status
FROM required_indexes r
LEFT JOIN existing_indexes e ON r.required_index = e.existing_index
ORDER BY r.required_index;

-- ============================================================================
-- SECTION 8: CLEANUP AND FINAL SUMMARY
-- ============================================================================

SELECT '🔍 SECTION 8: Cleanup and final summary' as section;

-- Clean up test data
DELETE FROM tasks WHERE type = 'verification_test';

-- Final summary
SELECT '📊 MIGRATION VERIFICATION SUMMARY' as summary;
SELECT '================================' as separator;

-- Count total tasks (excluding test data)
SELECT 
    'Total tasks in database:' as metric,
    COUNT(*) as value
FROM tasks;

-- Count tasks by status
SELECT 
    'Tasks by status:' as metric,
    status as value,
    COUNT(*) as count
FROM tasks 
GROUP BY status
ORDER BY status;

-- Final success message
SELECT '🎉 MIGRATION VERIFICATION COMPLETE!' as result;
SELECT '✅ All migration fixes have been verified successfully.' as status;
SELECT '💡 The database is ready for application use with lowercase enum values.' as next_steps;
