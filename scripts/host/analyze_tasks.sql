-- SeedCore local task analysis pack
-- Usage:
--   psql -h 127.0.0.1 -p 5432 -U "$USER" -d seedcore -f scripts/host/analyze_tasks.sql

\echo '== Task status summary =='
SELECT
  COUNT(*) AS total_tasks,
  COUNT(*) FILTER (WHERE status = 'created') AS created,
  COUNT(*) FILTER (WHERE status = 'queued') AS queued,
  COUNT(*) FILTER (WHERE status = 'running') AS running,
  COUNT(*) FILTER (WHERE status = 'retry') AS retry,
  COUNT(*) FILTER (WHERE status = 'completed') AS completed,
  COUNT(*) FILTER (WHERE status = 'failed') AS failed,
  COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled
FROM tasks;

\echo ''
\echo '== By type and status =='
SELECT type, status, COUNT(*) AS n
FROM tasks
GROUP BY type, status
ORDER BY type, status;

\echo ''
\echo '== By domain and status =='
SELECT domain, status, COUNT(*) AS n
FROM tasks
GROUP BY domain, status
ORDER BY domain, status;

\echo ''
\echo '== Retry/error hot spots =='
SELECT
  id,
  type,
  domain,
  status,
  attempts,
  owner_id,
  snapshot_id,
  run_after,
  left(coalesce(error, ''), 160) AS error_preview,
  created_at,
  updated_at
FROM tasks
WHERE status IN ('retry', 'failed')
ORDER BY updated_at DESC;

\echo ''
\echo '== Recent tasks =='
SELECT
  id,
  type,
  status,
  domain,
  attempts,
  owner_id,
  snapshot_id,
  created_at,
  updated_at,
  left(coalesce(description, ''), 120) AS description
FROM tasks
ORDER BY created_at DESC
LIMIT 25;
