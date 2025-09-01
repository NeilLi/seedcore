#!/usr/bin/env bash
# Quick fix script for current SeedCore database schema issues
# This script fixes the task execution hanging issue without full reinitialization

set -euo pipefail

NAMESPACE="${NAMESPACE:-seedcore-dev}"
DB_NAME="${DB_NAME:-seedcore}"
DB_USER="${DB_USER:-postgres}"
DB_PASS="${DB_PASS:-postgres}"

echo "🔧 Quick Database Schema Fix for SeedCore"
echo "🔧 Namespace: $NAMESPACE"
echo "🔧 Database:  $DB_NAME (user: $DB_USER)"
echo "🔧 Includes: Task lease columns for stale task recovery"

# Find PostgreSQL pod
find_pg_pod() {
  local sel pod
  for sel in \
    'app.kubernetes.io/name=postgresql,app.kubernetes.io/component=primary' \
    'app.kubernetes.io/name=postgresql' \
    'app=postgresql'
  do
    pod="$(kubectl -n "$NAMESPACE" get pods -l "$sel" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
    [[ -n "$pod" ]] && { echo "$pod"; return 0; }
  done
  pod="$(kubectl -n "$NAMESPACE" get pods --no-headers 2>/dev/null | awk '/^postgresql-|^postgres-/{print $1; exit}')"
  [[ -n "$pod" ]] && { echo "$pod"; return 0; }
  return 1
}

POSTGRES_POD="$(find_pg_pod || true)"
if [[ -z "${POSTGRES_POD:-}" ]]; then
  echo "❌ Could not locate a Postgres pod in namespace '$NAMESPACE'."
  exit 1
fi
echo "🧩 Using Postgres pod: $POSTGRES_POD"

echo "🔧 Applying critical database schema fixes..."

# Fix 1: Ensure taskstatus enum has 'retry' value
echo "⚙️  Fixing taskstatus enum..."
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "
DO \$\$
BEGIN
    -- Add retry status if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = (SELECT oid FROM pg_type WHERE typname = 'taskstatus') AND enumlabel = 'retry') THEN
        ALTER TYPE taskstatus ADD VALUE 'retry';
        RAISE NOTICE 'Added retry to taskstatus enum';
    ELSE
        RAISE NOTICE 'retry status already exists in taskstatus enum';
    END IF;
END\$\$;
"

# Fix 2: Add missing columns if they don't exist
echo "⚙️  Adding missing columns..."
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "
DO \$\$
BEGIN
    -- Add locked_by column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'locked_by') THEN
        ALTER TABLE tasks ADD COLUMN locked_by TEXT NULL;
        RAISE NOTICE 'Added locked_by column to tasks table';
    ELSE
        RAISE NOTICE 'locked_by column already exists';
    END IF;
    
    -- Add locked_at column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'locked_at') THEN
        ALTER TABLE tasks ADD COLUMN locked_at TIMESTAMP WITH TIME ZONE NULL;
        RAISE NOTICE 'Added locked_at column to tasks table';
    ELSE
        RAISE NOTICE 'locked_at column already exists';
    END IF;
    
    -- Add run_after column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'run_after') THEN
        ALTER TABLE tasks ADD COLUMN run_after TIMESTAMP WITH TIME ZONE NULL;
        RAISE NOTICE 'Added run_after column to tasks table';
    ELSE
        RAISE NOTICE 'run_after column already exists';
    END IF;
    
    -- Add attempts column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'attempts') THEN
        ALTER TABLE tasks ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
        RAISE NOTICE 'Added attempts column to tasks table';
    ELSE
        RAISE NOTICE 'attempts column already exists';
    END IF;
    
    -- Add drift_score column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'drift_score') THEN
        ALTER TABLE tasks ADD COLUMN drift_score DOUBLE PRECISION NOT NULL DEFAULT 0.0;
        RAISE NOTICE 'Added drift_score column to tasks table';
    ELSE
        RAISE NOTICE 'drift_score column already exists';
    END IF;
END\$\$;
"

# Fix 3: Fix any stuck tasks
echo "⚙️  Fixing stuck tasks..."
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "
-- Reset any tasks stuck in 'running' status for more than 5 minutes
UPDATE tasks 
SET status = 'retry', 
    locked_by = NULL, 
    locked_at = NULL, 
    run_after = NOW() + INTERVAL '10 seconds',
    attempts = attempts + 1
WHERE status = 'running' 
  AND locked_at < NOW() - INTERVAL '5 minutes';

-- Show how many tasks were fixed
SELECT 
    COUNT(*) as stuck_tasks_fixed,
    'Reset stuck tasks to retry status' as action
FROM tasks 
WHERE status = 'retry' 
  AND run_after > NOW() - INTERVAL '1 minute';
"

# Fix 4: Recreate indexes with proper retry status support
echo "⚙️  Recreating indexes..."
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "
-- Drop and recreate the claim query index to include retry status
DROP INDEX IF EXISTS idx_tasks_claim;
CREATE INDEX idx_tasks_claim ON tasks(status, run_after, created_at) 
WHERE status IN ('queued', 'failed', 'retry');

-- Ensure other indexes exist
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_run_after ON tasks(run_after);
CREATE INDEX IF NOT EXISTS idx_tasks_locked_at ON tasks(locked_at);
CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(type);
CREATE INDEX IF NOT EXISTS idx_tasks_domain ON tasks(domain);
"

# Fix 5: Add task lease columns for stale task recovery
echo "⚙️  Adding task lease columns..."
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "
DO \$\$
BEGIN
    -- Add owner_id column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'owner_id') THEN
        ALTER TABLE tasks ADD COLUMN owner_id TEXT NULL;
        RAISE NOTICE 'Added owner_id column to tasks table';
    ELSE
        RAISE NOTICE 'owner_id column already exists';
    END IF;
    
    -- Add lease_expires_at column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'lease_expires_at') THEN
        ALTER TABLE tasks ADD COLUMN lease_expires_at TIMESTAMP WITH TIME ZONE NULL;
        RAISE NOTICE 'Added lease_expires_at column to tasks table';
    ELSE
        RAISE NOTICE 'lease_expires_at column already exists';
    END IF;
    
    -- Add last_heartbeat column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'last_heartbeat') THEN
        ALTER TABLE tasks ADD COLUMN last_heartbeat TIMESTAMP WITH TIME ZONE NULL;
        RAISE NOTICE 'Added last_heartbeat column to tasks table';
    ELSE
        RAISE NOTICE 'last_heartbeat column already exists';
    END IF;
END\$\$;
"

# Create indexes for the new columns
echo "⚙️  Creating indexes for lease tracking..."
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "
CREATE INDEX IF NOT EXISTS idx_tasks_owner_id ON tasks(owner_id);
CREATE INDEX IF NOT EXISTS idx_tasks_lease_expires_at ON tasks(lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_tasks_last_heartbeat ON tasks(last_heartbeat);
CREATE INDEX IF NOT EXISTS idx_tasks_stale_running ON tasks(status, updated_at, last_heartbeat, lease_expires_at) 
WHERE status = 'running';
CREATE INDEX IF NOT EXISTS idx_tasks_owner_status ON tasks(owner_id, status, last_heartbeat) 
WHERE owner_id IS NOT NULL;
"

# Fix 6: Verify the schema is correct
echo "✅ Verifying fixed schema..."
echo "📊 Tasks table structure:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ tasks"

echo "📊 Taskstatus enum values:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT unnest(enum_range(NULL::taskstatus)) as enum_value;"

echo "📊 Current task statuses:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "
SELECT 
    status,
    COUNT(*) as count,
    CASE 
        WHEN status = 'running' THEN '🔄'
        WHEN status = 'queued' THEN '⏳'
        WHEN status = 'completed' THEN '✅'
        WHEN status = 'failed' THEN '❌'
        WHEN status = 'retry' THEN '🔄'
        WHEN status = 'created' THEN '📝'
        WHEN status = 'cancelled' THEN '❌'
        ELSE '❓'
    END as status_emoji
FROM tasks 
GROUP BY status 
ORDER BY count DESC;
"

echo "🎉 Database schema fixes completed!"
echo "✅ Added missing 'retry' status to taskstatus enum"
echo "✅ Ensured locked_by, locked_at, run_after, attempts columns exist"
echo "✅ Added task lease columns (owner_id, lease_expires_at, last_heartbeat) for stale task recovery"
echo "✅ Fixed claim query index to include retry status"
echo "✅ Reset any stuck tasks to retry status"
echo "✅ Recreated all necessary indexes"
echo ""
echo "🔧 Next steps:"
echo "   1. Restart the coordinator actor if tasks are still hanging"
echo "   2. Monitor task execution with: SELECT * FROM tasks ORDER BY updated_at DESC LIMIT 10;"
echo "   3. Check for any remaining stuck tasks"
