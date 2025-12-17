# seedcore/dispatcher/persistence/task_sql.py

# Task lease and stale recovery configuration
# 1. Define SQL with proper parameter placeholders (No f-strings)
# We use 'interval' logic directly in SQL with a parameter
CLAIM_BATCH_SQL = """
WITH c AS (
  SELECT id
  FROM tasks
  WHERE status IN ('queued','retry')
    AND (run_after IS NULL OR run_after <= NOW())
    AND NOT (type = ANY($3::text[]))
  ORDER BY created_at
  FOR UPDATE SKIP LOCKED
  LIMIT $1
)
UPDATE tasks t
SET status='running',
    locked_by=$2,
    locked_at=NOW(),
    owner_id=$2,
    -- Safely add seconds to current time
    lease_expires_at = NOW() + ($4 || ' seconds')::interval, 
    last_heartbeat = NOW(),
    attempts = t.attempts + 1
FROM c
WHERE t.id = c.id
RETURNING t.id, t.type, t.description, t.params, t.domain, t.drift_score, t.attempts;
"""

COMPLETE_TASK_SQL = """
UPDATE tasks
SET status = 'completed',
    locked_by = NULL,
    lease_expires_at = NULL,
    updated_at = NOW(),
    result = $3::jsonb   -- Optional: Save output if you have it
WHERE id = $1 
  AND locked_by = $2;     -- CRITICAL: Only complete if I still own it
"""

RETRY_TASK_SQL = """
UPDATE tasks
SET status = 'retry',       -- Distinct status helps monitoring vs 'queued'
    error = $1,
    run_after = NOW() + ($2 || ' seconds')::INTERVAL,
    locked_by = NULL,       -- Release the lock
    lease_expires_at = NULL,
    updated_at = NOW()
WHERE id = $3 
  AND locked_by = $4;       -- CRITICAL: Only retry if I still own it
"""

RELEASE_TASK_SQL = """
UPDATE tasks
SET status = 'retry', -- or 'queued'
    locked_by = NULL,
    lease_expires_at = NULL,
    updated_at = NOW(),
    error = $3
WHERE id = $1 
  AND locked_by = $2;
"""

RENEW_LEASE_SQL = """
UPDATE tasks
SET lease_expires_at = NOW() + ($3 || ' seconds')::interval,
    last_heartbeat = NOW()
WHERE id = $1 
  AND locked_by = $2 -- CRITICAL: Only renew if I still own it
RETURNING id;
"""

RECOVER_STALE_SQL = """
UPDATE tasks
SET status = 'retry',
    locked_by = NULL,
    lease_expires_at = NULL,
    updated_at = NOW(),
    error = 'dispatcher: lease expired (worker crash detected)',
    attempts = attempts + 1
WHERE status = 'running'
  AND lease_expires_at < NOW()
RETURNING id;
"""

# ---------------------------------------------------------------------
# SQL DEFINITIONS
# ---------------------------------------------------------------------

# 1. Recover Stuck Tasks (Attempts remaining)
#    - Resets to 'retry'
#    - Adds 15s delay to prevent immediate thrashing
REAP_STUCK_SQL = """
UPDATE tasks
SET status='retry',
    run_after = NOW() + INTERVAL '15 seconds',
    owner_id = NULL,
    lease_expires_at = NULL,
    locked_by = NULL,
    locked_at = NULL,
    updated_at = NOW(),
    error = COALESCE(error,'') || ' | reaper: lease expired'
WHERE status='running'
  AND attempts < $2
  AND (
        (lease_expires_at IS NOT NULL AND lease_expires_at < NOW())
        OR
        (last_heartbeat IS NOT NULL AND last_heartbeat < NOW() - ($1 || ' seconds')::interval)
      )
RETURNING id, locked_by;
"""

# 2. Fail Exhausted Tasks (Max attempts reached)
#    - Sets to 'failed'
#    - No further retries
REAP_FAILED_SQL = """
UPDATE tasks
SET status='failed',
    error = COALESCE(error,'') || ' | reaper: max attempts exceeded',
    owner_id = NULL,
    lease_expires_at = NULL,
    locked_by = NULL,
    locked_at = NULL,
    updated_at = NOW()
WHERE status='running'
  AND attempts >= $2
  AND (
        (lease_expires_at IS NOT NULL AND lease_expires_at < NOW())
        OR
        (last_heartbeat IS NOT NULL AND last_heartbeat < NOW() - ($1 || ' seconds')::interval)
      )
RETURNING id, locked_by;
"""

# 3. Duplicate Check (Utility)
CHECK_DUPLICATE_SQL = """
SELECT id
FROM tasks
WHERE status IN ('queued', 'running', 'retry')
  AND type = $1
  AND description = $2
  AND params = $3
  AND domain = $4
  AND created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC
LIMIT 1;
"""