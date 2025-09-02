# Task Lease Fixes - Implementation Summary

This document summarizes all the changes made to implement the task lease and stale recovery fixes for the "lost worker / lost future" problem.

## Files Modified

### 1. Database Migration
- **`deploy/migrations/006_add_task_lease_columns.sql`** (NEW)
  - Added `owner_id`, `lease_expires_at`, `last_heartbeat` columns
  - Created indexes for lease tracking and stale task detection
  - Added emergency cleanup function

### 2. Database Initialization Scripts
- **`deploy/init_full_db.sh`**
  - Added migration 007 to run the new lease columns migration
  - Updated documentation and status messages

- **`deploy/fix_current_db.sh`**
  - Added task lease columns to the fix script
  - Added index creation for lease tracking

### 3. Core Dispatcher Code
- **`src/seedcore/agents/queue_dispatcher.py`**
  - Added task lease configuration constants
  - Enhanced Reaper with `reap_stale_tasks()` method
  - Updated claim SQL to set lease expiration and owner tracking
  - Added `_renew_task_lease()` method for periodic renewal
  - Added `_recover_mine()` method for startup recovery
  - Integrated lease renewal into task processing
  - Added startup recovery call

### 4. Bootstrap Script
- **`bootstraps/bootstrap_dispatchers.py`**
  - Added one-shot stale task sweep during bootstrap
  - Enhanced reaper initialization with cleanup

### 5. Emergency Tools
- **`scripts/cleanup_stale_tasks.py`** (NEW)
  - CLI tool for emergency cleanup of stale tasks
  - Dry-run mode for safe testing
  - Configurable stale thresholds and retry limits

### 6. Documentation
- **`docs/TASK_LEASE_FIXES.md`** (NEW)
  - Comprehensive documentation of the fixes
  - Usage instructions and monitoring queries
  - Migration path and configuration options

## Key Features Implemented

### 1. Task Leases
- **Lease Duration**: Configurable via `TASK_LEASE_S` (default 10 minutes)
- **Owner Tracking**: Each running task has an `owner_id` field
- **Lease Expiration**: Tasks automatically expire if not renewed
- **Periodic Renewal**: Leases are renewed every 30 seconds during execution

### 2. Stale Task Detection
- **Staleness Threshold**: Configurable via `TASK_STALE_S` (default 15 minutes)
- **Owner Liveness**: Checks if the owner actor is still alive via Ray ping
- **Fallback Detection**: Uses `updated_at` if lease columns don't exist
- **Batch Processing**: Processes up to 200 tasks per sweep (configurable)

### 3. Automatic Recovery
- **Startup Recovery**: Dispatchers recover their orphaned tasks on startup
- **Reaper Sweeps**: Periodic cleanup of stale tasks
- **Retry Budget**: Limits requeues to prevent infinite loops (default 3 attempts)
- **Graceful Degradation**: Works with or without new database columns

### 4. Emergency Tools
- **CLI Cleanup**: Command-line tool for manual cleanup
- **Dry Run Mode**: Safe testing without making changes
- **SQL Functions**: Database-level cleanup functions
- **Monitoring Queries**: SQL queries for status monitoring

## Configuration Options

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `TASK_STALE_S` | 900 (15m) | Seconds after which a RUNNING task is considered stale |
| `TASK_MAX_REQUEUE` | 3 | Maximum number of times a task can be requeued |
| `TASK_REAP_BATCH` | 200 | Number of tasks to process in each reaper batch |
| `TASK_LEASE_S` | 600 (10m) | Task lease duration in seconds |

## Migration Steps

### For New Installations
1. Run `./deploy/init_full_db.sh` to apply all migrations including the new lease columns

### For Existing Installations
1. Run `./deploy/fix_current_db.sh` to add the new columns to existing database
2. Deploy the updated code with lease functionality
3. Restart dispatchers to trigger startup recovery

### Emergency Cleanup
1. Run `python scripts/cleanup_stale_tasks.py --dry-run` to see what would be cleaned
2. Run `python scripts/cleanup_stale_tasks.py` to perform cleanup

## Benefits

1. **Prevents Stuck Tasks**: No more tasks stuck in RUNNING status forever
2. **Automatic Recovery**: Self-healing system that recovers from crashes
3. **Better Observability**: Clear ownership and lease tracking for debugging
4. **Configurable**: All timeouts and limits can be tuned via environment variables
5. **Backward Compatible**: Works with existing databases (graceful degradation)
6. **Safe Deployment**: Can be applied incrementally without downtime

## Testing

The implementation includes several safety features:
- **Dry Run Mode**: Test cleanup without making changes
- **Idempotent Operations**: Safe to run multiple times
- **Graceful Error Handling**: Continues operation even if individual operations fail
- **Fallback Mechanisms**: Works even if new columns don't exist

## Monitoring

Key metrics to monitor:
- Number of stale tasks detected and requeued
- Task status distribution
- Lease renewal success rate
- Startup recovery effectiveness

The system provides comprehensive logging and monitoring capabilities to track the effectiveness of the fixes.
