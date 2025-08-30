# Dispatcher Database Troubleshooting Guide

## Overview

This guide helps diagnose and resolve issues where tasks get stuck in the `QUEUED` status, indicating that dispatcher actors are unable to claim tasks from the database.

## Problem Symptoms

- Tasks remain in `QUEUED` status indefinitely
- Dispatcher actors appear alive but don't process tasks
- No error messages in application logs
- Database shows queued tasks but no status changes

## Root Cause Analysis

The issue typically occurs in the dispatcher's main loop when:

1. **Database Connection Problems**: Connection pool issues, authentication failures, or network connectivity problems
2. **SQL Query Failures**: The `CLAIM_BATCH_SQL` query fails due to syntax errors, missing tables, or permission issues
3. **Transaction Locking**: Database locks prevent the `FOR UPDATE SKIP LOCKED` query from executing
4. **Dispatcher Actor Issues**: Ray actor health problems or resource constraints

## Quick Diagnostic Commands

### 1. Check Dispatcher Actor Status

```bash
# Get a shell in the Ray head node
kubectl exec -it <ray-head-pod> -- bash

# Check dispatcher actors
python -c "
import ray
ray.init()
actors = [ray.get_actor(f'seedcore_dispatcher_{i}', namespace='seedcore-dev') for i in range(2)]
for i, actor in enumerate(actors):
    print(f'Dispatcher {i}:', ray.get(actor.get_status.remote()))
"
```

### 2. Check Dispatcher Logs

```bash
# Get a shell in a Ray worker pod
kubectl exec -it <ray-worker-pod> -- bash

# Find dispatcher PIDs
ray list actors | grep Dispatcher

# Tail dispatcher logs (replace <PID> with actual PID)
tail -f /tmp/ray/session_latest/logs/*<PID>*.log
```

### 3. Test Database Connectivity

```bash
# Test from Ray worker pod
kubectl exec -it <ray-worker-pod> -- psql -h postgresql -U postgres -d seedcore -c 'SELECT 1'

# Test from database pod
kubectl exec -it <postgres-pod> -- psql -U postgres -d seedcore -c 'SELECT 1'
```

### 4. Verify Tasks Table

```bash
# Check table structure
kubectl exec -it <postgres-pod> -- psql -U postgres -d seedcore -c '\d+ tasks'

# Check for queued tasks
kubectl exec -it <postgres-pod> -- psql -U postgres -d seedcore -c "
SELECT id, status, created_at, updated_at, locked_by, locked_at
FROM tasks 
WHERE status = 'queued' 
ORDER BY created_at DESC 
LIMIT 5;
"
```

## Comprehensive Diagnostic Script

Use the automated diagnostic script to get a complete system health check:

```bash
# Run from Ray head node
kubectl exec -it <ray-head-pod> -- python /app/scripts/diagnose_dispatcher_db.py
```

This script will:
- Check Ray cluster status
- Verify dispatcher actor health
- Test database connectivity
- Validate the CLAIM_BATCH_SQL query
- Provide specific recommendations

## Common Issues and Solutions

### Issue 1: Database Connection Pool Errors

**Symptoms**: `last_pool_error` in dispatcher status, connection timeouts

**Solutions**:
```bash
# Restart dispatchers
kubectl exec -it <ray-head-pod> -- python /app/scripts/bootstrap_dispatchers.py

# Check database pod health
kubectl get pods -l app=postgres
kubectl logs <postgres-pod>
```

### Issue 2: Missing or Corrupted Tasks Table

**Symptoms**: "relation 'tasks' does not exist" errors

**Solutions**:
```bash
# Check if table exists
kubectl exec -it <postgres-pod> -- psql -U postgres -d seedcore -c '\dt'

# Recreate table if missing (check migrations/001_create_tasks_table.sql)
kubectl exec -it <postgres-pod> -- psql -U postgres -d seedcore -f /path/to/migration.sql
```

### Issue 3: Database Permission Issues

**Symptoms**: "permission denied" errors

**Solutions**:
```bash
# Check user permissions
kubectl exec -it <postgres-pod> -- psql -U postgres -d seedcore -c '\du'

# Grant necessary permissions
kubectl exec -it <postgres-pod> -- psql -U postgres -d seedcore -c "
GRANT ALL PRIVILEGES ON TABLE tasks TO postgres;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO postgres;
"
```

### Issue 4: Ray Actor Health Problems

**Symptoms**: Dispatcher actors unresponsive or restarting

**Solutions**:
```bash
# Check Ray cluster status
kubectl exec -it <ray-head-pod> -- python -c "
import ray
ray.init()
print('Ray status:', ray.is_initialized())
print('Cluster resources:', ray.cluster_resources())
"

# Restart dispatchers
kubectl exec -it <ray-head-pod> -- python /app/scripts/bootstrap_dispatchers.py
```

## Manual CLAIM_BATCH_SQL Testing

Test the dispatcher's claim query manually to isolate database issues:

```sql
-- Connect to database and test the claim query
BEGIN;

-- Check current queued tasks
SELECT id, type, description, created_at
FROM tasks
WHERE status = 'queued'
ORDER BY created_at
LIMIT 3;

-- Test the claim query (this will lock a task)
WITH c AS (
  SELECT id
  FROM tasks
  WHERE status IN ('queued','retry')
    AND (run_after IS NULL OR run_after <= NOW())
  ORDER BY created_at
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
UPDATE tasks t
SET status='running',
    locked_by='manual_test',
    locked_at=NOW(),
    attempts = t.attempts + 1
FROM c
WHERE t.id = c.id
RETURNING t.id, t.type, t.description;

-- Rollback to restore task state
ROLLBACK;
```

## Monitoring and Prevention

### 1. Set Up Health Checks

```bash
# Monitor dispatcher health every minute
while true; do
  kubectl exec -it <ray-head-pod> -- python -c "
import ray
ray.init()
try:
    actor = ray.get_actor('seedcore_dispatcher_0', namespace='seedcore-dev')
    status = ray.get(actor.get_status.remote())
    print(f'Health: {status.get(\"status\")}, Pool: {status.get(\"pool_initialized\")}')
except Exception as e:
    print(f'Error: {e}')
"
  sleep 60
done
```

### 2. Database Monitoring

```bash
# Monitor database connections
kubectl exec -it <postgres-pod> -- psql -U postgres -d seedcore -c "
SELECT 
    state,
    count(*) as connections,
    max(backend_start) as oldest_connection
FROM pg_stat_activity 
WHERE datname = 'seedcore'
GROUP BY state;
"
```

### 3. Task Queue Monitoring

```bash
# Monitor task status distribution
kubectl exec -it <postgres-pod> -- psql -U postgres -d seedcore -c "
SELECT 
    status,
    count(*) as count,
    max(created_at) as latest_task
FROM tasks 
GROUP BY status 
ORDER BY count DESC;
"
```

## Emergency Recovery

If all else fails, perform a complete restart:

```bash
# 1. Stop all dispatchers
kubectl exec -it <ray-head-pod> -- python -c "
import ray
ray.init()
for i in range(10):
    try:
        actor = ray.get_actor(f'seedcore_dispatcher_{i}', namespace='seedcore-dev')
        ray.kill(actor, no_restart=True)
        print(f'Killed dispatcher {i}')
    except:
        break
"

# 2. Restart Ray cluster (if necessary)
kubectl delete pod <ray-head-pod>
kubectl delete pod <ray-worker-pod>

# 3. Recreate dispatchers
kubectl exec -it <ray-head-pod> -- python /app/scripts/bootstrap_dispatchers.py
```

## Getting Help

If you're still experiencing issues:

1. **Collect Logs**: Gather dispatcher logs, database logs, and Ray cluster logs
2. **Run Diagnostics**: Execute the diagnostic script and share the output
3. **Check Recent Changes**: Review any recent deployments or configuration changes
4. **Verify Environment**: Ensure all environment variables and dependencies are correct

## Prevention Best Practices

1. **Regular Health Checks**: Monitor dispatcher health and database connectivity
2. **Connection Pool Tuning**: Adjust pool sizes based on workload and resources
3. **Database Maintenance**: Regular database maintenance and index optimization
4. **Resource Monitoring**: Monitor CPU, memory, and network resources
5. **Backup and Recovery**: Regular backups and tested recovery procedures
