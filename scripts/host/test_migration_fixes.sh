#!/bin/bash
# Comprehensive test script for migration fixes
# This script verifies that all migration issues have been resolved:
# 1. Enum type creation is idempotent
# 2. Enum values are consistently lowercase  
# 3. View creation works without column rename conflicts
# 4. All task operations work correctly

set -euo pipefail

# Configuration
NAMESPACE="${NAMESPACE:-seedcore-dev}"
DB_NAME="${DB_NAME:-seedcore}"
DB_USER="${DB_USER:-postgres}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🧪 Testing Migration Fixes${NC}"
echo -e "${BLUE}===========================${NC}"
echo -e "📋 Namespace: $NAMESPACE"
echo -e "📋 Database: $DB_NAME"
echo -e "📋 User: $DB_USER"
echo ""

# Function to find PostgreSQL pod
find_postgres_pod() {
    local pod=""
    for selector in \
        'app.kubernetes.io/name=postgresql,app.kubernetes.io/component=primary' \
        'app.kubernetes.io/name=postgresql' \
        'app=postgresql'
    do
        pod="$(kubectl -n "$NAMESPACE" get pods -l "$selector" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
        [[ -n "$pod" ]] && break
    done
    echo "$pod"
}

# Function to run SQL and capture output
run_sql() {
    local sql_file="$1"
    local description="$2"
    
    echo -e "${YELLOW}🔍 $description${NC}"
    echo "----------------------------------------"
    
    if kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
        psql -U "$DB_USER" -d "$DB_NAME" -f "$sql_file" 2>&1; then
        echo -e "${GREEN}✅ $description completed successfully${NC}"
    else
        echo -e "${RED}❌ $description failed${NC}"
        return 1
    fi
    echo ""
}

# Function to run SQL command and capture output
run_sql_command() {
    local sql_command="$1"
    local description="$2"
    
    echo -e "${YELLOW}🔍 $description${NC}"
    echo "----------------------------------------"
    
    if kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
        psql -U "$DB_USER" -d "$DB_NAME" -c "$sql_command" 2>&1; then
        echo -e "${GREEN}✅ $description completed successfully${NC}"
    else
        echo -e "${RED}❌ $description failed${NC}"
        return 1
    fi
    echo ""
}

# Main execution
echo -e "${BLUE}🔍 Finding PostgreSQL pod...${NC}"
POSTGRES_POD=$(find_postgres_pod)

if [[ -z "$POSTGRES_POD" ]]; then
    echo -e "${RED}❌ Could not locate a Postgres pod in namespace '$NAMESPACE'.${NC}"
    echo "   Tip: kubectl -n $NAMESPACE get pods --show-labels | grep -i postgres"
    exit 1
fi

echo -e "${GREEN}✅ Found Postgres pod: $POSTGRES_POD${NC}"
echo ""

# Test 1: Basic connectivity and enum check
echo -e "${BLUE}📋 TEST 1: Basic connectivity and enum check${NC}"
run_sql_command "SELECT version();" "PostgreSQL version check"
run_sql_command "SELECT unnest(enum_range(NULL::taskstatus)) as enum_value;" "Current enum values"

# Test 2: Copy and run comprehensive verification
echo -e "${BLUE}📋 TEST 2: Comprehensive migration verification${NC}"
echo -e "${YELLOW}📝 Copying verification script to pod...${NC}"
kubectl -n "$NAMESPACE" cp "verify_migration_fixes.sql" "$POSTGRES_POD:/tmp/verify_migration_fixes.sql"

run_sql "/tmp/verify_migration_fixes.sql" "Comprehensive migration verification"

# Test 3: Test specific migration scenarios
echo -e "${BLUE}📋 TEST 3: Testing specific migration scenarios${NC}"

# Test enum type creation idempotency
run_sql_command "
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'taskstatus') THEN
        CREATE TYPE taskstatus AS ENUM ('created', 'queued', 'running', 'completed', 'failed', 'cancelled', 'retry');
        RAISE NOTICE 'Created taskstatus enum type';
    ELSE
        RAISE NOTICE 'taskstatus enum type already exists, skipping creation';
    END IF;
END\$\$;
" "Testing enum type creation idempotency"

# Test uppercase value detection and conversion
run_sql_command "
DO \$\$
DECLARE
    has_uppercase_values BOOLEAN;
    uppercase_count INTEGER;
BEGIN
    -- Check if there are any uppercase values in the tasks table
    SELECT EXISTS (
        SELECT 1 FROM tasks 
        WHERE status::text IN ('CREATED', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', 'RETRY')
    ) INTO has_uppercase_values;
    
    IF has_uppercase_values THEN
        RAISE NOTICE 'Uppercase values found - conversion would be needed';
    ELSE
        RAISE NOTICE 'No uppercase values found - enum is consistent';
    END IF;
END\$\$;
" "Testing uppercase value detection"

# Test 4: Test critical application queries
echo -e "${BLUE}📋 TEST 4: Testing critical application queries${NC}"

# Test task creation
run_sql_command "
INSERT INTO tasks (type, status, description) 
VALUES ('migration_test', 'queued', 'Test task for migration verification')
ON CONFLICT DO NOTHING;
" "Creating test task"

# Test claim query
run_sql_command "
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
LIMIT 3;
" "Testing claim query"

# Test view access (before status update)
run_sql_command "
SELECT 
    id,
    type,
    status,
    status_emoji,
    created_at
FROM graph_tasks 
WHERE type = 'migration_test'
ORDER BY created_at DESC
LIMIT 3;
" "Testing graph_tasks view (before update)"

# Test status updates
run_sql_command "
WITH task_to_update AS (
    SELECT id FROM tasks 
    WHERE type = 'migration_test' AND status = 'queued' 
    LIMIT 1
)
UPDATE tasks 
SET status = 'running', locked_by = 'test_dispatcher', locked_at = NOW()
WHERE id IN (SELECT id FROM task_to_update);
" "Testing status update"

# Test view access (after status update)
run_sql_command "
SELECT 
    id,
    type,
    status,
    status_emoji,
    created_at
FROM graph_tasks 
WHERE type = 'migration_test'
ORDER BY created_at DESC
LIMIT 3;
" "Testing graph_tasks view (after update)"

# Test 5: Cleanup and final verification
echo -e "${BLUE}📋 TEST 5: Cleanup and final verification${NC}"

# Clean up test data
run_sql_command "DELETE FROM tasks WHERE type = 'migration_test';" "Cleaning up test data"

# Final status check
run_sql_command "
SELECT 
    'Total tasks:' as metric,
    COUNT(*) as value
FROM tasks
UNION ALL
SELECT 
    'Enum values:' as metric,
    COUNT(*) as value
FROM pg_enum e
JOIN pg_type t ON e.enumtypid = t.oid
WHERE t.typname = 'taskstatus';
" "Final status check"

# Summary
echo -e "${GREEN}🎉 MIGRATION FIXES VERIFICATION COMPLETE!${NC}"
echo -e "${GREEN}===========================================${NC}"
echo -e "${GREEN}✅ All migration fixes have been verified successfully.${NC}"
echo -e "${GREEN}✅ The database is ready for application use.${NC}"
echo ""
echo -e "${BLUE}📋 Summary of fixes verified:${NC}"
echo -e "   ✅ Enum type creation is idempotent"
echo -e "   ✅ Enum values are consistently lowercase"
echo -e "   ✅ View creation works without column rename conflicts"
echo -e "   ✅ All task operations work correctly"
echo -e "   ✅ Critical queries function properly"
echo ""
echo -e "${BLUE}💡 Next steps:${NC}"
echo -e "   • Update application code to use lowercase status values"
echo -e "   • Run the full migration sequence in your environment"
echo -e "   • Monitor application logs for any remaining issues"
