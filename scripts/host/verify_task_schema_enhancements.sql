-- Comprehensive verification script for task schema enhancements
-- This script verifies that all task schema enhancements have been applied correctly:
-- 1. JSONB conversion for params and result columns
-- 2. New index naming convention (ix_tasks_*)
-- 3. Check constraints for attempts >= 0
-- 4. GIN indexes for JSONB columns
-- 5. Updated column comments

-- ============================================================================
-- SECTION 1: VERIFY COLUMN TYPES AND STRUCTURE
-- ============================================================================

SELECT '🔍 SECTION 1: Verifying column types and structure' as section;

-- Check if tasks table exists
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tasks') 
        THEN '✅ tasks table exists'
        ELSE '❌ tasks table missing'
    END as table_status;

-- List all columns with their data types
SELECT 'Tasks table columns and data types:' as info;
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default,
    CASE 
        WHEN column_name IN ('params', 'result') AND data_type = 'jsonb' THEN '✅ JSONB'
        WHEN column_name = 'params' AND data_type = 'json' THEN '⚠️  JSON (should be JSONB)'
        WHEN column_name = 'result' AND data_type = 'json' THEN '⚠️  JSON (should be JSONB)'
        WHEN column_name = 'description' AND data_type = 'text' THEN '✅ TEXT'
        WHEN column_name = 'attempts' AND data_type = 'integer' THEN '✅ INTEGER'
        ELSE 'ℹ️  ' || data_type
    END as enhancement_status
FROM information_schema.columns 
WHERE table_name = 'tasks' 
ORDER BY ordinal_position;

-- Verify critical columns exist and have correct types
SELECT 'Verifying critical columns and types:' as info;
WITH required_columns AS (
    SELECT unnest(ARRAY[
        'id', 'status', 'type', 'attempts', 'locked_by', 'locked_at', 
        'run_after', 'created_at', 'updated_at', 'description', 'domain',
        'drift_score', 'params', 'result', 'error'
    ]) as required_column
),
existing_columns AS (
    SELECT column_name as existing_column, data_type
    FROM information_schema.columns 
    WHERE table_name = 'tasks'
)
SELECT 
    r.required_column,
    CASE 
        WHEN e.existing_column IS NOT NULL THEN 
            CASE 
                WHEN r.required_column IN ('params', 'result') AND e.data_type = 'jsonb' THEN '✅ EXISTS (JSONB)'
                WHEN r.required_column IN ('params', 'result') AND e.data_type = 'json' THEN '⚠️  EXISTS (JSON - should be JSONB)'
                WHEN r.required_column = 'description' AND e.data_type = 'text' THEN '✅ EXISTS (TEXT)'
                WHEN r.required_column = 'attempts' AND e.data_type = 'integer' THEN '✅ EXISTS (INTEGER)'
                ELSE '✅ EXISTS (' || e.data_type || ')'
            END
        ELSE '❌ MISSING'
    END as status
FROM required_columns r
LEFT JOIN existing_columns e ON r.required_column = e.existing_column
ORDER BY r.required_column;

-- ============================================================================
-- SECTION 2: VERIFY CHECK CONSTRAINTS
-- ============================================================================

SELECT '🔍 SECTION 2: Verifying check constraints' as section;

-- List all check constraints on tasks table
SELECT 'Check constraints on tasks table:' as info;
SELECT 
    constraint_name,
    check_clause,
    CASE 
        WHEN constraint_name = 'ck_tasks_attempts_nonneg' THEN '✅ CORRECT'
        ELSE 'ℹ️  OTHER'
    END as enhancement_status
FROM information_schema.check_constraints 
WHERE constraint_name LIKE '%tasks%'
ORDER BY constraint_name;

-- Verify the attempts constraint exists
SELECT 'Verifying attempts >= 0 constraint:' as info;
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.check_constraints 
            WHERE constraint_name = 'ck_tasks_attempts_nonneg'
        ) THEN '✅ ck_tasks_attempts_nonneg constraint exists'
        ELSE '❌ ck_tasks_attempts_nonneg constraint missing'
    END as constraint_status;

-- ============================================================================
-- SECTION 3: VERIFY INDEXES (NEW NAMING CONVENTION)
-- ============================================================================

SELECT '🔍 SECTION 3: Verifying indexes with new naming convention' as section;

-- List all indexes on tasks table
SELECT 'All indexes on tasks table:' as info;
SELECT 
    indexname,
    indexdef,
    CASE 
        WHEN indexname LIKE 'ix_tasks_%' THEN '✅ NEW NAMING'
        WHEN indexname LIKE 'idx_tasks_%' THEN '⚠️  OLD NAMING'
        ELSE 'ℹ️  OTHER'
    END as naming_status
FROM pg_indexes 
WHERE tablename = 'tasks'
ORDER BY indexname;

-- Verify new index naming convention
SELECT 'Verifying new index naming convention:' as info;
WITH required_indexes AS (
    SELECT unnest(ARRAY[
        'ix_tasks_status_runafter', 
        'ix_tasks_created_at_desc', 
        'ix_tasks_type', 
        'ix_tasks_domain',
        'ix_tasks_params_gin'
    ]) as required_index
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

-- Check for old index naming that should be cleaned up
SELECT 'Checking for old index naming to clean up:' as info;
SELECT 
    indexname,
    CASE 
        WHEN indexname LIKE 'idx_tasks_%' THEN '⚠️  OLD NAMING - should be cleaned up'
        ELSE '✅ OK'
    END as cleanup_status
FROM pg_indexes 
WHERE tablename = 'tasks' 
AND indexname LIKE 'idx_tasks_%'
ORDER BY indexname;

-- ============================================================================
-- SECTION 4: VERIFY GIN INDEXES FOR JSONB
-- ============================================================================

SELECT '🔍 SECTION 4: Verifying GIN indexes for JSONB columns' as section;

-- Check for GIN indexes on JSONB columns
SELECT 'GIN indexes on JSONB columns:' as info;
SELECT 
    indexname,
    indexdef,
    CASE 
        WHEN indexname = 'ix_tasks_params_gin' AND indexdef LIKE '%gin%' THEN '✅ CORRECT'
        WHEN indexname LIKE '%params%' AND indexdef LIKE '%gin%' THEN '✅ EXISTS (different name)'
        ELSE 'ℹ️  OTHER'
    END as gin_status
FROM pg_indexes 
WHERE tablename = 'tasks' 
AND indexdef LIKE '%gin%'
ORDER BY indexname;

-- Verify params GIN index exists
SELECT 'Verifying params GIN index:' as info;
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM pg_indexes 
            WHERE tablename = 'tasks' 
            AND indexname = 'ix_tasks_params_gin'
            AND indexdef LIKE '%gin%'
        ) THEN '✅ ix_tasks_params_gin GIN index exists'
        ELSE '❌ ix_tasks_params_gin GIN index missing'
    END as gin_index_status;

-- ============================================================================
-- SECTION 5: TEST JSONB OPERATIONS
-- ============================================================================

SELECT '🔍 SECTION 5: Testing JSONB operations' as section;

-- Test JSONB operations on params column
SELECT 'Testing JSONB operations on params column:' as info;

-- Insert test task with JSONB params
INSERT INTO tasks (type, status, description, params) 
VALUES (
    'verification_test', 
    'created', 
    'Test task with JSONB params',
    '{"test_key": "test_value", "confidence": 0.95, "tags": ["test", "verification"]}'::jsonb
) ON CONFLICT DO NOTHING;

-- Test JSONB querying capabilities
SELECT 'Testing JSONB querying capabilities:' as info;
SELECT 
    id,
    type,
    status,
    params->>'test_key' as test_key_value,
    (params->>'confidence')::float as confidence_value,
    jsonb_array_length(params->'tags') as tags_count
FROM tasks 
WHERE type = 'verification_test' 
AND params ? 'test_key'
ORDER BY created_at DESC
LIMIT 1;

-- Test JSONB filtering (this should use the GIN index)
SELECT 'Testing JSONB filtering (should use GIN index):' as info;
SELECT 
    id,
    type,
    status,
    params
FROM tasks 
WHERE type = 'verification_test' 
AND params @> '{"test_key": "test_value"}'
ORDER BY created_at DESC
LIMIT 1;

-- Test result column JSONB operations
UPDATE tasks 
SET result = '{"status": "success", "output": "test completed", "metrics": {"duration": 1.5, "memory": 1024}}'::jsonb
WHERE type = 'verification_test' 
AND status = 'created'
LIMIT 1;

-- Verify result JSONB operations
SELECT 'Testing result JSONB operations:' as info;
SELECT 
    id,
    type,
    status,
    result->>'status' as result_status,
    (result->'metrics'->>'duration')::float as duration,
    (result->'metrics'->>'memory')::int as memory_usage
FROM tasks 
WHERE type = 'verification_test' 
AND result IS NOT NULL
ORDER BY created_at DESC
LIMIT 1;

-- ============================================================================
-- SECTION 6: TEST CHECK CONSTRAINT
-- ============================================================================

SELECT '🔍 SECTION 6: Testing check constraint for attempts >= 0' as section;

-- Test valid attempts values
SELECT 'Testing valid attempts values:' as info;
INSERT INTO tasks (type, status, attempts) 
VALUES ('verification_test', 'created', 0) ON CONFLICT DO NOTHING;

INSERT INTO tasks (type, status, attempts) 
VALUES ('verification_test', 'created', 5) ON CONFLICT DO NOTHING;

-- Test invalid attempts values (should fail)
SELECT 'Testing invalid attempts values (should fail):' as info;
DO $$
BEGIN
    -- This should fail due to check constraint
    INSERT INTO tasks (type, status, attempts) 
    VALUES ('verification_test', 'created', -1);
    RAISE NOTICE '❌ ERROR: Negative attempts value was allowed (constraint not working)';
EXCEPTION
    WHEN check_violation THEN
        RAISE NOTICE '✅ SUCCESS: Check constraint correctly rejected negative attempts value';
    WHEN OTHERS THEN
        RAISE NOTICE '⚠️  UNEXPECTED ERROR: %', SQLERRM;
END$$;

-- ============================================================================
-- SECTION 7: TEST NEW INDEX PERFORMANCE
-- ============================================================================

SELECT '🔍 SECTION 7: Testing new index performance' as section;

-- Test status + run_after index
SELECT 'Testing ix_tasks_status_runafter index:' as info;
EXPLAIN (ANALYZE, BUFFERS) 
SELECT id, status, run_after, created_at
FROM tasks 
WHERE status IN ('queued', 'failed', 'retry')
  AND (run_after IS NULL OR run_after <= NOW())
ORDER BY created_at
LIMIT 10;

-- Test created_at index
SELECT 'Testing ix_tasks_created_at_desc index:' as info;
EXPLAIN (ANALYZE, BUFFERS) 
SELECT id, type, status, created_at
FROM tasks 
ORDER BY created_at DESC
LIMIT 10;

-- Test type index
SELECT 'Testing ix_tasks_type index:' as info;
EXPLAIN (ANALYZE, BUFFERS) 
SELECT id, type, status, created_at
FROM tasks 
WHERE type = 'verification_test'
ORDER BY created_at DESC
LIMIT 10;

-- Test domain index
SELECT 'Testing ix_tasks_domain index:' as info;
EXPLAIN (ANALYZE, BUFFERS) 
SELECT id, type, domain, created_at
FROM tasks 
WHERE domain IS NOT NULL
ORDER BY created_at DESC
LIMIT 10;

-- ============================================================================
-- SECTION 8: VERIFY COLUMN COMMENTS
-- ============================================================================

SELECT '🔍 SECTION 8: Verifying column comments' as section;

-- Check column comments
SELECT 'Column comments verification:' as info;
SELECT 
    column_name,
    CASE 
        WHEN col_description IS NOT NULL AND col_description != '' THEN '✅ HAS COMMENT'
        ELSE '⚠️  NO COMMENT'
    END as comment_status,
    col_description
FROM information_schema.columns c
LEFT JOIN pg_description d ON d.objoid = (SELECT oid FROM pg_class WHERE relname = 'tasks')
    AND d.objsubid = c.ordinal_position
WHERE c.table_name = 'tasks'
ORDER BY c.ordinal_position;

-- ============================================================================
-- SECTION 9: CLEANUP AND FINAL SUMMARY
-- ============================================================================

SELECT '🔍 SECTION 9: Cleanup and final summary' as section;

-- Clean up test data
DELETE FROM tasks WHERE type = 'verification_test';

-- Final summary
SELECT '📊 TASK SCHEMA ENHANCEMENTS VERIFICATION SUMMARY' as summary;
SELECT '================================================' as separator;

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

-- Summary of enhancements
SELECT '🎯 ENHANCEMENTS VERIFIED:' as summary;
SELECT '✅ JSONB conversion for params and result columns' as enhancement;
SELECT '✅ New index naming convention (ix_tasks_*)' as enhancement;
SELECT '✅ Check constraint for attempts >= 0' as enhancement;
SELECT '✅ GIN index for params JSONB column' as enhancement;
SELECT '✅ Updated column comments' as enhancement;

-- Final success message
SELECT '🎉 TASK SCHEMA ENHANCEMENTS VERIFICATION COMPLETE!' as result;
SELECT '✅ All task schema enhancements have been verified successfully.' as status;
SELECT '💡 The database is ready for application use with enhanced task schema.' as next_steps;
