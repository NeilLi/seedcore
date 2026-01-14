-- migrations/010_runtime_control_logic.sql
BEGIN;

-- Get/Rotate epoch under advisory lock (prevents split brain on bootstrap)
CREATE OR REPLACE FUNCTION set_current_epoch(new_epoch UUID)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE locked BOOLEAN;
BEGIN
  -- lock key: choose a stable app-wide key (e.g., 42)
  locked := pg_try_advisory_lock(42);
  IF NOT locked THEN
    RAISE EXCEPTION 'set_current_epoch: could not acquire advisory lock';
  END IF;

  UPDATE cluster_metadata SET current_epoch = new_epoch, updated_at = now() WHERE id = 1;
  IF NOT FOUND THEN
    INSERT INTO cluster_metadata (id, current_epoch) VALUES (1, new_epoch);
  END IF;

  PERFORM pg_advisory_unlock(42);
END$$;

-- Register/Upsert instance
CREATE OR REPLACE FUNCTION register_instance(
  p_instance_id UUID,
  p_logical_id TEXT,
  p_cluster_epoch UUID,
  p_actor_name TEXT,
  p_serve_route TEXT,
  p_node_id TEXT,
  p_ip INET,
  p_pid INT
) RETURNS VOID LANGUAGE sql AS $$
INSERT INTO registry_instance(instance_id, logical_id, cluster_epoch, status, actor_name, serve_route, node_id, ip_address, pid)
VALUES (p_instance_id, p_logical_id, p_cluster_epoch, 'starting', p_actor_name, p_serve_route, p_node_id, p_ip, p_pid)
ON CONFLICT (instance_id) DO UPDATE
SET last_heartbeat = now();
$$;

-- Set status
CREATE OR REPLACE FUNCTION set_instance_status(p_instance_id UUID, p_status InstanceStatus)
RETURNS VOID LANGUAGE sql AS $$
UPDATE registry_instance SET status = p_status,
                             stopped_at = CASE WHEN p_status IN ('dead','draining') THEN now() ELSE stopped_at END
WHERE instance_id = p_instance_id;
$$;

-- Heartbeat (cheap write)
CREATE OR REPLACE FUNCTION beat(p_instance_id UUID)
RETURNS VOID LANGUAGE sql AS $$
UPDATE registry_instance SET last_heartbeat = now() WHERE instance_id = p_instance_id;
$$;

-- Expire stale
CREATE OR REPLACE FUNCTION expire_stale_instances(p_timeout_seconds INT DEFAULT 15)
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE cnt INT;
BEGIN
  UPDATE registry_instance
  SET status = 'dead', stopped_at = COALESCE(stopped_at, now())
  WHERE status IN ('starting','alive','draining')
    AND last_heartbeat < (now() - make_interval(secs => p_timeout_seconds));
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RETURN cnt;
END$$;

-- Expire old epochs
CREATE OR REPLACE FUNCTION expire_old_epoch_instances()
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE cnt INT;
BEGIN
  UPDATE registry_instance ri
  SET status = 'dead', stopped_at = COALESCE(stopped_at, now())
  FROM cluster_metadata cm
  WHERE ri.cluster_epoch <> cm.current_epoch
    AND ri.status IN ('starting','alive','draining');
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RETURN cnt;
END$$;

COMMIT;

