-- 015_pkg_views_functions.sql
-- Purpose: helper views for loaders/CI and integrity checks

-- Active artifact per env
CREATE OR REPLACE VIEW pkg_active_artifact AS
SELECT s.env, s.id AS snapshot_id, s.version, a.artifact_type, a.size_bytes, a.sha256
FROM pkg_snapshots s
JOIN pkg_snapshot_artifacts a ON a.snapshot_id = s.id
WHERE s.is_active = TRUE;

-- Rules + emissions flattened (audit-friendly)
CREATE OR REPLACE VIEW pkg_rules_expanded AS
SELECT
  r.id AS rule_id, r.rule_name, r.priority, r.engine, r.disabled,
  r.snapshot_id, s.version AS snapshot_version, s.env,
  e.relationship_type, st.name AS subtask_name, e.params,
  r.metadata
FROM pkg_policy_rules r
LEFT JOIN pkg_rule_emissions e ON e.rule_id = r.id
LEFT JOIN pkg_subtask_types st ON st.id = e.subtask_type_id
JOIN pkg_snapshots s ON s.id = r.snapshot_id;

-- Deployment coverage: how many devices are running the snapshot we intended
-- Handles router, edge:robot, edge:door targets correctly
CREATE OR REPLACE VIEW pkg_deployment_coverage AS
SELECT
  d.target, d.region, d.snapshot_id, s.version,
  count(*) FILTER (WHERE dv.snapshot_id = d.snapshot_id) AS devices_on_snapshot,
  count(*) AS devices_total
FROM pkg_deployments d
LEFT JOIN pkg_device_versions dv
  ON ( (d.region = dv.region OR d.region = 'global')
       AND (
         dv.device_type = d.target
         OR dv.device_type = split_part(d.target, ':', 2)     -- edge:robot -> robot
         OR d.target = 'router'                               -- routers aren't devices
       )
     )
JOIN pkg_snapshots s ON s.id = d.snapshot_id
GROUP BY d.target, d.region, d.snapshot_id, s.version;

-- Integrity check: emissions use subtasks in same snapshot
CREATE OR REPLACE FUNCTION pkg_check_integrity()
RETURNS TABLE(ok BOOLEAN, msg TEXT) LANGUAGE plpgsql STABLE AS $$
BEGIN
  RETURN QUERY
  SELECT
    (COUNT(*) = 0) AS ok,
    CASE WHEN COUNT(*) = 0 THEN 'OK'
         ELSE 'Cross-snapshot emission mismatch found' END
  FROM (
    SELECT 1
    FROM pkg_rule_emissions e
    JOIN pkg_policy_rules r ON r.id = e.rule_id
    JOIN pkg_subtask_types st ON st.id = e.subtask_type_id
    WHERE r.snapshot_id <> st.snapshot_id
  ) x;
END; $$;

-- Quick helpers
CREATE OR REPLACE FUNCTION pkg_active_snapshot_id(p_env pkg_env DEFAULT 'prod')
RETURNS INT LANGUAGE SQL STABLE AS $$
  SELECT id FROM pkg_snapshots WHERE env = p_env AND is_active = TRUE LIMIT 1
$$;

CREATE OR REPLACE FUNCTION pkg_promote_snapshot(p_snapshot_id INT, p_env pkg_env, p_actor TEXT, p_reason TEXT DEFAULT NULL)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
  prev_version TEXT;
  new_version  TEXT;
BEGIN
  SELECT version INTO new_version FROM pkg_snapshots WHERE id = p_snapshot_id;
  IF new_version IS NULL THEN
    RAISE EXCEPTION 'snapshot % not found', p_snapshot_id;
  END IF;

  SELECT version INTO prev_version FROM pkg_snapshots WHERE env = p_env AND is_active = TRUE LIMIT 1;

  UPDATE pkg_snapshots SET is_active = FALSE WHERE env = p_env AND is_active = TRUE;
  UPDATE pkg_snapshots SET is_active = TRUE  WHERE id = p_snapshot_id;

  INSERT INTO pkg_promotions(snapshot_id, from_version, to_version, actor, action, reason, success)
  VALUES (p_snapshot_id, prev_version, new_version, p_actor, 'promote', p_reason, TRUE);
END;
$$;
