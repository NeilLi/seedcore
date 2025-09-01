# Task Lease and Stale Recovery Fixes

This document describes the fixes implemented to solve the "lost worker / lost future" problem where tasks remain in `RUNNING` status forever after crashes or restarts.

## Problem Description

The original system had a classic "lost worker / lost future" problem:

1. Dispatcher picks a task → writes `status='running'`
2. Execution happens in Ray (organ → tier0 agent)
3. If the process (serve replica / organism / ray cluster) dies, the DB row isn't reverted
4. On restart, there's nothing that detects "this RUNNING row is orphaned" or re-queues it

## Solution Overview

The fix implements a three-layer approach:

### Layer 1: Immediate Safety Net - Reaper Re-queues Stale RUNNING Tasks

**Goal:** If a task has been `RUNNING` too long *and* the owner can't prove liveness, flip it back to `QUEUED` (or mark `FAILED` with retry budget logic).

**Implementation:**
- Enhanced `Reaper` class with `reap_stale_tasks()` method
- Configurable staleness threshold (`TASK_STALE_S`, default 15 minutes)
- Owner liveness detection via Ray actor ping
- Retry budget enforcement (`MAX_REQUEUE`, default 3 attempts)

### Layer 2: Task Leases - Make RUNNING Rows Recoverable

**Goal:** Convert "RUNNING" into a **time-boxed lease** that must be renewed. If the process dies, the lease expires naturally and the Reaper picks it up.

**Implementation:**
- New database columns: `owner_id`, `lease_expires_at`, `last_heartbeat`
- Updated claim SQL to set lease expiration (default 10 minutes)
- Periodic lease renewal during task execution (every 30 seconds)
- Automatic lease expiration detection

### Layer 3: Startup Recovery - Belt-and-Suspenders

**Goal:** When any dispatcher starts, recover any `RUNNING` rows owned by this process.

**Implementation:**
- `_recover_mine()` method in Dispatcher
- Called during startup to requeue orphaned tasks
- Owner-based recovery with heartbeat validation

## Database Schema Changes

### New Migration: `006_add_task_lease_columns.sql`

Added the following columns to the `tasks` table:

```sql
-- Add lease-related columns
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS owner_id TEXT NULL;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMP WITH TIME ZONE NULL;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS last_heartbeat TIMESTAMP WITH TIME ZONE NULL;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_tasks_owner_id ON tasks(owner_id);
CREATE INDEX IF NOT EXISTS idx_tasks_lease_expires_at ON tasks(lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_tasks_last_heartbeat ON tasks(last_heartbeat);
CREATE INDEX IF NOT EXISTS idx_tasks_stale_running ON tasks(status, updated_at, last_heartbeat, lease_expires_at) 
WHERE status = 'running';
CREATE INDEX IF NOT EXISTS idx_tasks_owner_status ON tasks(owner_id, status, last_heartbeat) 
WHERE owner_id IS NOT NULL;
```

### Emergency Cleanup Function

Added a PostgreSQL function for emergency cleanup:

```sql
CREATE OR REPLACE FUNCTION cleanup_stale_running_tasks(
    stale_minutes INTEGER DEFAULT 15,
    max_attempts INTEGER DEFAULT 3
) RETURNS INTEGER;
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TASK_STALE_S` | 900 (15m) | Seconds after which a RUNNING task is considered stale |
| `TASK_MAX_REQUEUE` | 3 | Maximum number of times a task can be requeued |
| `TASK_REAP_BATCH` | 200 | Number of tasks to process in each reaper batch |
| `TASK_LEASE_S` | 600 (10m) | Task lease duration in seconds |

## Code Changes

### Enhanced Reaper (`src/seedcore/agents/queue_dispatcher.py`)

- Added `reap_stale_tasks()` method for comprehensive stale task detection
- Owner liveness checking via Ray actor ping
- Retry budget enforcement
- Safe fallback to `updated_at` if lease columns don't exist

### Enhanced Dispatcher (`src/seedcore/agents/queue_dispatcher.py`)

- Updated claim SQL to set lease expiration and owner tracking
- Added `_renew_task_lease()` method for periodic lease renewal
- Added `_recover_mine()` method for startup recovery
- Integrated lease renewal into task processing loop

### Bootstrap Integration (`bootstraps/bootstrap_dispatchers.py`)

- Added one-shot stale task sweep during bootstrap
- Automatic cleanup of orphaned tasks on startup

## Usage

### Emergency Cleanup

For immediate cleanup of stuck tasks:

```bash
# Show what would be cleaned up (dry run)
python scripts/cleanup_stale_tasks.py --dry-run

# Clean up tasks older than 15 minutes
python scripts/cleanup_stale_tasks.py

# Custom stale threshold
python scripts/cleanup_stale_tasks.py --stale-minutes 30 --max-attempts 5
```

### Database Migration

Apply the new migration:

```bash
# For new installations
./deploy/init_full_db.sh

# For existing installations
./deploy/fix_current_db.sh
```

### Manual SQL Cleanup

For emergency situations, you can run this SQL directly:

```sql
-- Requeue RUNNING older than 15m (no owner/liveness check, just time-based)
UPDATE tasks
   SET status='queued',
       attempts = attempts + 1,
       owner_id = NULL,
       lease_expires_at = NULL,
       updated_at = NOW(),
       error = COALESCE(error,'') || ' | requeued by admin: stale RUNNING'
 WHERE status='running'
   AND updated_at < NOW() - INTERVAL '15 minutes';
```

## Monitoring

### Task Status Monitoring

Monitor task status distribution:

```sql
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
```

### Stale Task Detection

Find stale RUNNING tasks:

```sql
SELECT 
    id, 
    type, 
    description, 
    attempts, 
    owner_id, 
    updated_at,
    EXTRACT(EPOCH FROM (NOW() - updated_at))/60 as age_minutes
FROM tasks 
WHERE status = 'running' 
  AND updated_at < NOW() - INTERVAL '15 minutes'
ORDER BY updated_at ASC;
```

## Benefits

1. **Automatic Recovery**: Stale tasks are automatically detected and requeued
2. **Owner Tracking**: Clear ownership of running tasks for better debugging
3. **Lease-based Execution**: Tasks have time-bounded leases that expire naturally
4. **Startup Safety**: Automatic recovery of orphaned tasks on restart
5. **Configurable**: All timeouts and limits are configurable via environment variables
6. **Backward Compatible**: Works even without the new database columns (falls back to `updated_at`)

## Migration Path

1. **Immediate**: Run emergency cleanup to unstick current tasks
2. **Database**: Apply migration to add lease columns
3. **Deploy**: Deploy updated code with lease functionality
4. **Monitor**: Watch for any remaining issues

The system is designed to be safe and idempotent - you can apply these fixes incrementally without downtime.
