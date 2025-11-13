# seedcore/dispatcher/persistence/task_sql.py

CLAIM_BATCH_SQL = """
UPDATE tasks
SET lease_owner = $2,
    lease_expiry = NOW() + INTERVAL '30 seconds'
WHERE id IN (
    SELECT id FROM tasks
    WHERE state = 'queued'
      AND type <> ALL($3)
    ORDER BY priority DESC, created_at ASC
    LIMIT $1
    FOR UPDATE SKIP LOCKED
)
RETURNING id, type, params, description, domain, priority, drift_score,
          required_specialization, lease_expiry;
"""

COMPLETE_SQL = """
UPDATE tasks
SET state='completed',
    result=$1,
    completed_at=NOW(),
    lease_owner=NULL,
    lease_expiry=NULL
WHERE id=$2;
"""

RETRY_SQL = """
UPDATE tasks
SET state='queued',
    error=$1,
    next_attempt_at=NOW() + ($2 || ' seconds')::INTERVAL,
    attempts = attempts + 1,
    lease_owner=NULL,
    lease_expiry=NULL
WHERE id=$3;
"""

FAIL_SQL = """
UPDATE tasks
SET state='failed',
    error=$1,
    lease_owner=NULL,
    lease_expiry=NULL
WHERE id=$2;
"""

RENEW_LEASE_SQL = """
UPDATE tasks
SET lease_expiry = NOW() + INTERVAL '30 seconds',
    lease_owner = $2
WHERE id=$1;
"""

CLEAR_LEASE_SQL = """
UPDATE tasks
SET lease_owner=NULL,
    lease_expiry=NULL
WHERE id=$1;
"""

REQUEUE_STUCK_SQL = """
UPDATE tasks
SET state='queued',
    lease_owner=NULL,
    lease_expiry=NULL,
    error='dispatcher: requeued stale task',
    next_attempt_at=NOW()
WHERE state='processing'
  AND lease_expiry < NOW()
RETURNING id;
"""
