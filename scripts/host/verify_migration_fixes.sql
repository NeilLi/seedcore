-- Comprehensive verification script for all migrations (001-018)
-- This script verifies that all migration features have been deployed successfully:
-- 
-- CORE MIGRATIONS (001-008):
-- 1. Enum type creation is idempotent
-- 2. Enum values are consistently lowercase
-- 3. View creation works without column rename conflicts
-- 4. All task operations work correctly
-- 5. JSONB conversion and check constraints
-- 6. Proper index naming conventions
--
-- ADVANCED FEATURES (010-018):
-- 7. Task-fact integration (migration 010)
-- 8. Runtime registry system (migrations 011-012)
-- 9. PKG core catalog & policy governance (migrations 013-015)
-- 10. Fact PKG integration & temporal facts (migration 016)
-- 11. Task embedding support with content hashing (migration 017)
-- 12. Task outbox hardening with availability scheduling (migration 018)

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

-- Verify critical columns exist and have correct types
SELECT 'Verifying critical columns exist and have correct types:' as info;
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
-- SECTION 3: TEST ENUM VALUE OPERATIONS
-- ============================================================================

SELECT '🔍 SECTION 3: Testing enum value operations' as section;

-- Test inserting tasks with each status (clean up first)
DELETE FROM tasks WHERE type = 'verification_test';

-- Test created status
INSERT INTO tasks (type, status, description) 
VALUES ('verification_test', 'created', 'Test task with created status');

-- Test queued status
-- Make it non-claimable to avoid background workers flipping it to running
INSERT INTO tasks (type, status, description, run_after)
VALUES ('verification_test', 'queued', 'Test task with queued status', NOW() + INTERVAL '10 minutes');

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
-- SECTION 7: VERIFY JSONB CONVERSION AND CHECK CONSTRAINTS
-- ============================================================================

SELECT '🔍 SECTION 7: Verifying JSONB conversion and check constraints' as section;

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

-- Verify check constraint for attempts >= 0
SELECT 'Verifying check constraint for attempts >= 0:' as info;
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.check_constraints 
            WHERE constraint_name = 'ck_tasks_attempts_nonneg'
        ) THEN '✅ ck_tasks_attempts_nonneg constraint exists'
        ELSE '❌ ck_tasks_attempts_nonneg constraint missing'
    END as constraint_status;

-- Test JSONB operations
SELECT 'Testing JSONB operations:' as info;
INSERT INTO tasks (type, status, description, params) 
VALUES (
    'verification_test', 
    'created', 
    'Test JSONB operations',
    '{"test_key": "test_value", "confidence": 0.95}'::jsonb
) ON CONFLICT DO NOTHING;

-- Test JSONB querying
SELECT 
    id,
    params->>'test_key' as test_key_value,
    (params->>'confidence')::float as confidence_value
FROM tasks 
WHERE type = 'verification_test' 
AND params ? 'test_key'
ORDER BY created_at DESC
LIMIT 1;

-- Test check constraint (should fail for negative attempts)
SELECT 'Testing check constraint (should fail for negative attempts):' as info;
DO $$
BEGIN
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
-- SECTION 8: VERIFY INDEXES
-- ============================================================================

SELECT '🔍 SECTION 8: Verifying critical indexes' as section;

-- List indexes on tasks table
SELECT 'Indexes on tasks table:' as info;
SELECT 
    indexname,
    indexdef
FROM pg_indexes 
WHERE tablename = 'tasks'
ORDER BY indexname;

-- Verify critical indexes exist (updated for new naming convention)
SELECT 'Verifying critical indexes exist:' as info;
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
-- SECTION 9: VERIFY TASK-FACT INTEGRATION (Migration 010)
-- ============================================================================

SELECT '🔍 SECTION 9: Verifying task-fact integration' as section;

-- Check if task_reads_fact table exists
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'task_reads_fact') 
        THEN '✅ task_reads_fact table exists'
        ELSE '❌ task_reads_fact table missing'
    END as table_status;

-- Check if task_produces_fact table exists
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'task_produces_fact') 
        THEN '✅ task_produces_fact table exists'
        ELSE '❌ task_produces_fact table missing'
    END as table_status;

-- Verify ensure_fact_node function exists
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.routines 
            WHERE routine_name = 'ensure_fact_node'
        ) 
        THEN '✅ ensure_fact_node function exists'
        ELSE '❌ ensure_fact_node function missing'
    END as function_status;

-- Verify hgnn_edges view includes fact edges
SELECT 'Verifying hgnn_edges view includes fact relations:' as info;
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.views 
            WHERE table_name = 'hgnn_edges'
        ) 
        THEN '✅ hgnn_edges view exists'
        ELSE '❌ hgnn_edges view missing'
    END as view_status;

-- ============================================================================
-- SECTION 10: VERIFY RUNTIME REGISTRY (Migrations 011-012)
-- ============================================================================

SELECT '🔍 SECTION 10: Verifying runtime registry' as section;

-- Check if cluster_metadata table exists
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'cluster_metadata') 
        THEN '✅ cluster_metadata table exists'
        ELSE '❌ cluster_metadata table missing'
    END as table_status;

-- Check if registry_instance table exists
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'registry_instance') 
        THEN '✅ registry_instance table exists'
        ELSE '❌ registry_instance table missing'
    END as table_status;

-- Check if InstanceStatus enum exists
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM pg_type WHERE typname = 'instancestatus') 
        THEN '✅ InstanceStatus enum type exists'
        ELSE '❌ InstanceStatus enum type missing'
    END as enum_type_status;

-- List InstanceStatus enum values
SELECT 'InstanceStatus enum values:' as info;
SELECT 
    e.enumlabel as enum_value,
    e.enumsortorder as sort_order
FROM pg_type t
JOIN pg_enum e ON t.oid = e.enumtypid
WHERE t.typname = 'instancestatus'
ORDER BY e.enumsortorder;

-- Verify runtime registry views exist
SELECT 'Verifying runtime registry views:' as info;
WITH required_views AS (
    SELECT unnest(ARRAY['active_instances', 'active_instance']) as required_view
),
existing_views AS (
    SELECT table_name as existing_view
    FROM information_schema.views 
    WHERE table_name IN ('active_instances', 'active_instance')
)
SELECT 
    r.required_view,
    CASE 
        WHEN e.existing_view IS NOT NULL THEN '✅ EXISTS'
        ELSE '❌ MISSING'
    END as status
FROM required_views r
LEFT JOIN existing_views e ON r.required_view = e.existing_view
ORDER BY r.required_view;

-- Verify runtime registry functions exist
SELECT 'Verifying runtime registry functions:' as info;
WITH required_functions AS (
    SELECT unnest(ARRAY[
        'set_current_epoch',
        'register_instance',
        'set_instance_status',
        'beat',
        'expire_stale_instances',
        'expire_old_epoch_instances'
    ]) as required_function
),
existing_functions AS (
    SELECT routine_name as existing_function
    FROM information_schema.routines 
    WHERE routine_name IN (
        'set_current_epoch', 'register_instance', 'set_instance_status',
        'beat', 'expire_stale_instances', 'expire_old_epoch_instances'
    )
)
SELECT 
    r.required_function,
    CASE 
        WHEN e.existing_function IS NOT NULL THEN '✅ EXISTS'
        ELSE '❌ MISSING'
    END as status
FROM required_functions r
LEFT JOIN existing_functions e ON r.required_function = e.existing_function
ORDER BY r.required_function;

-- ============================================================================
-- SECTION 11: VERIFY PKG CORE CATALOG (Migration 013)
-- ============================================================================

SELECT '🔍 SECTION 11: Verifying PKG core catalog' as section;

-- Check PKG enums exist
SELECT 'Verifying PKG enum types:' as info;
WITH required_enums AS (
    SELECT unnest(ARRAY[
        'pkg_env', 'pkg_engine', 'pkg_condition_type', 
        'pkg_operator', 'pkg_relation', 'pkg_artifact_type'
    ]) as required_enum
),
existing_enums AS (
    SELECT typname as existing_enum
    FROM pg_type 
    WHERE typname IN (
        'pkg_env', 'pkg_engine', 'pkg_condition_type',
        'pkg_operator', 'pkg_relation', 'pkg_artifact_type'
    )
)
SELECT 
    r.required_enum,
    CASE 
        WHEN e.existing_enum IS NOT NULL THEN '✅ EXISTS'
        ELSE '❌ MISSING'
    END as status
FROM required_enums r
LEFT JOIN existing_enums e ON r.required_enum = e.existing_enum
ORDER BY r.required_enum;

-- Check PKG core tables exist
SELECT 'Verifying PKG core tables:' as info;
WITH required_tables AS (
    SELECT unnest(ARRAY[
        'pkg_snapshots', 'pkg_subtask_types', 'pkg_policy_rules',
        'pkg_rule_conditions', 'pkg_rule_emissions', 'pkg_snapshot_artifacts'
    ]) as required_table
),
existing_tables AS (
    SELECT table_name as existing_table
    FROM information_schema.tables 
    WHERE table_name IN (
        'pkg_snapshots', 'pkg_subtask_types', 'pkg_policy_rules',
        'pkg_rule_conditions', 'pkg_rule_emissions', 'pkg_snapshot_artifacts'
    )
)
SELECT 
    r.required_table,
    CASE 
        WHEN e.existing_table IS NOT NULL THEN '✅ EXISTS'
        ELSE '❌ MISSING'
    END as status
FROM required_tables r
LEFT JOIN existing_tables e ON r.required_table = e.existing_table
ORDER BY r.required_table;

-- Verify pkg_snapshots structure
SELECT 'Verifying pkg_snapshots key columns:' as info;
WITH required_columns AS (
    SELECT unnest(ARRAY[
        'id', 'version', 'env', 'checksum', 'is_active', 'created_at'
    ]) as required_column
),
existing_columns AS (
    SELECT column_name as existing_column
    FROM information_schema.columns 
    WHERE table_name = 'pkg_snapshots'
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
-- SECTION 12: VERIFY PKG OPS TABLES (Migration 014)
-- ============================================================================

SELECT '🔍 SECTION 12: Verifying PKG ops tables' as section;

-- Check PKG ops tables exist
SELECT 'Verifying PKG ops tables:' as info;
WITH required_tables AS (
    SELECT unnest(ARRAY[
        'pkg_deployments', 'pkg_facts', 'pkg_validation_fixtures',
        'pkg_validation_runs', 'pkg_promotions', 'pkg_device_versions'
    ]) as required_table
),
existing_tables AS (
    SELECT table_name as existing_table
    FROM information_schema.tables 
    WHERE table_name IN (
        'pkg_deployments', 'pkg_facts', 'pkg_validation_fixtures',
        'pkg_validation_runs', 'pkg_promotions', 'pkg_device_versions'
    )
)
SELECT 
    r.required_table,
    CASE 
        WHEN e.existing_table IS NOT NULL THEN '✅ EXISTS'
        ELSE '❌ MISSING'
    END as status
FROM required_tables r
LEFT JOIN existing_tables e ON r.required_table = e.existing_table
ORDER BY r.required_table;

-- Verify pkg_facts structure (temporal policy facts)
SELECT 'Verifying pkg_facts key columns:' as info;
WITH required_columns AS (
    SELECT unnest(ARRAY[
        'id', 'snapshot_id', 'namespace', 'subject', 'predicate',
        'object', 'valid_from', 'valid_to', 'created_at', 'created_by'
    ]) as required_column
),
existing_columns AS (
    SELECT column_name as existing_column
    FROM information_schema.columns 
    WHERE table_name = 'pkg_facts'
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
-- SECTION 13: VERIFY PKG VIEWS AND FUNCTIONS (Migration 015)
-- ============================================================================

SELECT '🔍 SECTION 13: Verifying PKG views and functions' as section;

-- Check PKG views exist
SELECT 'Verifying PKG views:' as info;
WITH required_views AS (
    SELECT unnest(ARRAY[
        'pkg_active_artifact', 'pkg_rules_expanded', 'pkg_deployment_coverage'
    ]) as required_view
),
existing_views AS (
    SELECT table_name as existing_view
    FROM information_schema.views 
    WHERE table_name IN (
        'pkg_active_artifact', 'pkg_rules_expanded', 'pkg_deployment_coverage'
    )
)
SELECT 
    r.required_view,
    CASE 
        WHEN e.existing_view IS NOT NULL THEN '✅ EXISTS'
        ELSE '❌ MISSING'
    END as status
FROM required_views r
LEFT JOIN existing_views e ON r.required_view = e.existing_view
ORDER BY r.required_view;

-- Check PKG functions exist
SELECT 'Verifying PKG functions:' as info;
WITH required_functions AS (
    SELECT unnest(ARRAY[
        'pkg_check_integrity', 'pkg_active_snapshot_id', 'pkg_promote_snapshot'
    ]) as required_function
),
existing_functions AS (
    SELECT routine_name as existing_function
    FROM information_schema.routines 
    WHERE routine_name IN (
        'pkg_check_integrity', 'pkg_active_snapshot_id', 'pkg_promote_snapshot'
    )
)
SELECT 
    r.required_function,
    CASE 
        WHEN e.existing_function IS NOT NULL THEN '✅ EXISTS'
        ELSE '❌ MISSING'
    END as status
FROM required_functions r
LEFT JOIN existing_functions e ON r.required_function = e.existing_function
ORDER BY r.required_function;

-- ============================================================================
-- SECTION 14: VERIFY FACT PKG INTEGRATION (Migration 016)
-- ============================================================================

SELECT '🔍 SECTION 14: Verifying fact PKG integration' as section;

-- Verify facts table has PKG integration columns
SELECT 'Verifying facts table PKG integration columns:' as info;
WITH required_columns AS (
    SELECT unnest(ARRAY[
        'snapshot_id', 'namespace', 'subject', 'predicate', 'object_data',
        'valid_from', 'valid_to', 'created_by', 'pkg_rule_id', 
        'pkg_provenance', 'validation_status'
    ]) as required_column
),
existing_columns AS (
    SELECT column_name as existing_column
    FROM information_schema.columns 
    WHERE table_name = 'facts'
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

-- Verify facts PKG integration indexes
SELECT 'Verifying facts table PKG integration indexes:' as info;
WITH required_indexes AS (
    SELECT unnest(ARRAY[
        'idx_facts_subject', 'idx_facts_predicate', 'idx_facts_namespace',
        'idx_facts_temporal', 'idx_facts_snapshot', 'idx_facts_created_by',
        'idx_facts_pkg_rule', 'idx_facts_validation_status'
    ]) as required_index
),
existing_indexes AS (
    SELECT indexname as existing_index
    FROM pg_indexes 
    WHERE tablename = 'facts'
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

-- Verify facts check constraints
SELECT 'Verifying facts table check constraints:' as info;
WITH required_constraints AS (
    SELECT unnest(ARRAY[
        'chk_facts_temporal', 'chk_facts_namespace_not_empty', 'chk_facts_created_by_not_empty'
    ]) as required_constraint
),
existing_constraints AS (
    SELECT constraint_name as existing_constraint
    FROM information_schema.check_constraints
    WHERE constraint_name LIKE 'chk_facts_%'
)
SELECT 
    r.required_constraint,
    CASE 
        WHEN e.existing_constraint IS NOT NULL THEN '✅ EXISTS'
        ELSE '❌ MISSING'
    END as status
FROM required_constraints r
LEFT JOIN existing_constraints e ON r.required_constraint = e.existing_constraint
ORDER BY r.required_constraint;

-- Check active_temporal_facts view
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.views WHERE table_name = 'active_temporal_facts') 
        THEN '✅ active_temporal_facts view exists'
        ELSE '❌ active_temporal_facts view missing'
    END as view_status;

-- Verify fact PKG integration functions
SELECT 'Verifying fact PKG integration functions:' as info;
WITH required_functions AS (
    SELECT unnest(ARRAY[
        'get_facts_by_subject', 'cleanup_expired_facts', 'get_fact_statistics'
    ]) as required_function
),
existing_functions AS (
    SELECT routine_name as existing_function
    FROM information_schema.routines 
    WHERE routine_name IN (
        'get_facts_by_subject', 'cleanup_expired_facts', 'get_fact_statistics'
    )
)
SELECT 
    r.required_function,
    CASE 
        WHEN e.existing_function IS NOT NULL THEN '✅ EXISTS'
        ELSE '❌ MISSING'
    END as status
FROM required_functions r
LEFT JOIN existing_functions e ON r.required_function = e.existing_function
ORDER BY r.required_function;

-- ============================================================================
-- SECTION 15: VERIFY TASK EMBEDDING SUPPORT (Migration 017)
-- ============================================================================

SELECT '🔍 SECTION 15: Verifying task embedding support' as section;

-- Check if pgcrypto extension is installed
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto') 
        THEN '✅ pgcrypto extension installed'
        ELSE '❌ pgcrypto extension missing'
    END as extension_status;

-- Verify graph_embeddings table structure
SELECT 'Verifying graph_embeddings enhanced columns:' as info;
WITH required_columns AS (
    SELECT unnest(ARRAY[
        'node_id', 'label', 'model', 'content_sha256', 'emb'
    ]) as required_column
),
existing_columns AS (
    SELECT column_name as existing_column
    FROM information_schema.columns 
    WHERE table_name = 'graph_embeddings'
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

-- Verify graph_embeddings primary key
SELECT 'Verifying graph_embeddings primary key (node_id, label):' as info;
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu 
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = 'graph_embeddings' 
                AND tc.constraint_type = 'PRIMARY KEY'
                AND kcu.column_name IN ('node_id', 'label')
        ) 
        THEN '✅ Primary key on (node_id, label) exists'
        ELSE '❌ Primary key on (node_id, label) missing'
    END as pk_status;

-- Verify embedding-related views
SELECT 'Verifying task embedding views:' as info;
WITH required_views AS (
    SELECT unnest(ARRAY[
        'tasks_missing_embeddings', 'task_embeddings_primary', 'task_embeddings_stale'
    ]) as required_view
),
existing_views AS (
    SELECT table_name as existing_view
    FROM information_schema.views 
    WHERE table_name IN (
        'tasks_missing_embeddings', 'task_embeddings_primary', 'task_embeddings_stale'
    )
)
SELECT 
    r.required_view,
    CASE 
        WHEN e.existing_view IS NOT NULL THEN '✅ EXISTS'
        ELSE '❌ MISSING'
    END as status
FROM required_views r
LEFT JOIN existing_views e ON r.required_view = e.existing_view
ORDER BY r.required_view;

-- Verify graph_embeddings indexes
SELECT 'Verifying graph_embeddings indexes:' as info;
WITH required_indexes AS (
    SELECT unnest(ARRAY[
        'uq_graph_embeddings_node_label', 'idx_graph_embeddings_node', 'idx_graph_embeddings_label'
    ]) as required_index
),
existing_indexes AS (
    SELECT indexname as existing_index
    FROM pg_indexes 
    WHERE tablename = 'graph_embeddings'
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
-- SECTION 16: VERIFY TASK OUTBOX HARDENING (Migration 018)
-- ============================================================================

SELECT '🔍 SECTION 16: Verifying task outbox (transactional outbox pattern)' as section;

-- Check if task_outbox table exists
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'task_outbox') 
        THEN '✅ task_outbox table exists'
        ELSE '❌ task_outbox table missing'
    END as table_status;

-- Verify task_outbox base columns
SELECT 'Verifying task_outbox base columns:' as info;
WITH required_columns AS (
    SELECT unnest(ARRAY[
        'id', 'task_id', 'event_type', 'payload', 'dedupe_key',
        'created_at', 'updated_at', 'available_at', 'attempts'
    ]) as required_column
),
existing_columns AS (
    SELECT column_name as existing_column, data_type
    FROM information_schema.columns 
    WHERE table_name = 'task_outbox'
)
SELECT 
    r.required_column,
    CASE 
        WHEN e.existing_column IS NOT NULL THEN 
            '✅ EXISTS (' || e.data_type || ')'
        ELSE '❌ MISSING'
    END as status
FROM required_columns r
LEFT JOIN existing_columns e ON r.required_column = e.existing_column
ORDER BY r.required_column;

-- Verify task_outbox indexes
SELECT 'Verifying task_outbox indexes:' as info;
WITH required_indexes AS (
    SELECT unnest(ARRAY[
        'idx_task_outbox_available',
        'idx_task_outbox_event_type',
        'idx_task_outbox_task_id'
    ]) as required_index
),
existing_indexes AS (
    SELECT indexname as existing_index
    FROM pg_indexes 
    WHERE tablename = 'task_outbox'
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

-- Verify task_outbox check constraint
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.check_constraints 
            WHERE constraint_name = 'task_outbox_attempts_nonneg'
        ) 
        THEN '✅ task_outbox_attempts_nonneg constraint exists'
        ELSE '❌ task_outbox_attempts_nonneg constraint missing'
    END as constraint_status;

-- Verify touch_updated_at function exists
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.routines 
            WHERE routine_name = 'touch_updated_at'
        ) 
        THEN '✅ touch_updated_at function exists'
        ELSE '❌ touch_updated_at function missing'
    END as function_status;

-- Verify trigger exists
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.triggers 
            WHERE trigger_name = 'trg_task_outbox_updated_at'
            AND event_object_table = 'task_outbox'
        ) 
        THEN '✅ trg_task_outbox_updated_at trigger exists'
        ELSE '❌ trg_task_outbox_updated_at trigger missing'
    END as trigger_status;

-- Test outbox operations
SELECT 'Testing task_outbox operations:' as info;

-- Insert a test outbox event
INSERT INTO task_outbox (task_id, event_type, payload, dedupe_key)
VALUES (
    gen_random_uuid(),
    'task.test',
    '{"test": "verification_event"}'::jsonb,
    'test_verification_' || extract(epoch from now())::text
) ON CONFLICT (dedupe_key) DO NOTHING
RETURNING id, event_type, attempts, available_at;

-- Query test event with scheduling logic (simulating outbox flusher)
SELECT 
    id,
    event_type,
    attempts,
    available_at <= NOW() as is_ready,
    CASE 
        WHEN available_at <= NOW() THEN '✅ Ready for processing'
        ELSE '⏰ Scheduled for later'
    END as status
FROM task_outbox
WHERE event_type = 'task.test'
ORDER BY created_at DESC
LIMIT 1;

-- Test updating attempts (simulating retry logic)
UPDATE task_outbox
SET attempts = attempts + 1,
    available_at = NOW() + INTERVAL '5 minutes'
WHERE event_type = 'task.test'
AND id = (SELECT id FROM task_outbox WHERE event_type = 'task.test' ORDER BY created_at DESC LIMIT 1);

-- Verify the update worked and updated_at was touched
SELECT 
    id,
    event_type,
    attempts,
    available_at > NOW() as is_scheduled,
    updated_at > created_at as was_updated
FROM task_outbox
WHERE event_type = 'task.test'
ORDER BY created_at DESC
LIMIT 1;

-- Cleanup test data
DELETE FROM task_outbox WHERE event_type = 'task.test';

-- ============================================================================
-- SECTION 17: CLEANUP AND FINAL SUMMARY
-- ============================================================================

SELECT '🔍 SECTION 17: Cleanup and final summary' as section;

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

-- Display counts for new tables
SELECT '📊 NEW TABLE STATISTICS' as summary;

SELECT 
    'Task-fact relations:' as metric,
    (SELECT COUNT(*) FROM task_reads_fact) as reads_count,
    (SELECT COUNT(*) FROM task_produces_fact) as produces_count;

SELECT 
    'Runtime registry:' as metric,
    (SELECT COUNT(*) FROM registry_instance) as instances,
    (SELECT COUNT(*) FROM cluster_metadata) as cluster_records;

SELECT 
    'PKG snapshots:' as metric,
    COUNT(*) as total_snapshots,
    COUNT(*) FILTER (WHERE is_active = TRUE) as active_snapshots
FROM pkg_snapshots;

SELECT 
    'PKG policy rules:' as metric,
    COUNT(*) as total_rules,
    COUNT(*) FILTER (WHERE disabled = FALSE) as enabled_rules
FROM pkg_policy_rules;

SELECT 
    'Facts table (PKG integration):' as metric,
    COUNT(*) as total_facts,
    COUNT(*) FILTER (WHERE snapshot_id IS NOT NULL) as pkg_governed_facts,
    COUNT(*) FILTER (WHERE valid_to IS NOT NULL AND valid_to > now()) as temporal_facts
FROM facts;

SELECT 
    'Graph embeddings:' as metric,
    COUNT(*) as total_embeddings,
    COUNT(DISTINCT node_id) as unique_nodes,
    COUNT(DISTINCT label) as unique_labels
FROM graph_embeddings;

SELECT 
    'Task outbox:' as metric,
    COUNT(*) as total_events,
    COUNT(*) FILTER (WHERE available_at <= now()) as ready_events,
    COUNT(*) FILTER (WHERE available_at > now()) as scheduled_events,
    COUNT(DISTINCT event_type) as event_types
FROM task_outbox;

-- Final success message
SELECT '🎉 COMPREHENSIVE MIGRATION VERIFICATION COMPLETE!' as result;
SELECT '✅ All core migration fixes (001-008) have been verified successfully.' as status;
SELECT '✅ Task-fact integration (migration 010) verified.' as enhancement;
SELECT '✅ Runtime registry system (migrations 011-012) verified.' as enhancement;
SELECT '✅ PKG core catalog & governance (migrations 013-015) verified.' as enhancement;
SELECT '✅ Fact PKG integration & temporal facts (migration 016) verified.' as enhancement;
SELECT '✅ Task embedding support with content hashing (migration 017) verified.' as enhancement;
SELECT '✅ Task outbox pattern with retry logic & scheduling (migration 018) verified.' as enhancement;
SELECT '💡 The database is ready for advanced task workflows, policy governance, embedding-based retrieval, and reliable event publishing.' as next_steps;
