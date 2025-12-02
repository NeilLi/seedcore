-- 008_hgnn_agent_layer.sql
BEGIN;

-- === Dimension tables (TEXT natural keys) ===
CREATE TABLE IF NOT EXISTS model (
  model_name   TEXT PRIMARY KEY,
  meta         JSONB DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ DEFAULT now(),
  updated_at   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS policy (
  policy_name  TEXT PRIMARY KEY,
  meta         JSONB DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ DEFAULT now(),
  updated_at   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS service (
  service_name TEXT PRIMARY KEY,
  meta         JSONB DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ DEFAULT now(),
  updated_at   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS skill (
  skill_name   TEXT PRIMARY KEY,
  meta         JSONB DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ DEFAULT now(),
  updated_at   TIMESTAMPTZ DEFAULT now()
);

-- Reuse the update_timestamps() from 007 for updated_at maintenance
DROP TRIGGER IF EXISTS trg_model_updated_at   ON model;
DROP TRIGGER IF EXISTS trg_policy_updated_at  ON policy;
DROP TRIGGER IF EXISTS trg_service_updated_at ON service;
DROP TRIGGER IF EXISTS trg_skill_updated_at   ON skill;

CREATE TRIGGER trg_model_updated_at
BEFORE UPDATE ON model FOR EACH ROW EXECUTE FUNCTION update_timestamps();

CREATE TRIGGER trg_policy_updated_at
BEFORE UPDATE ON policy FOR EACH ROW EXECUTE FUNCTION update_timestamps();

CREATE TRIGGER trg_service_updated_at
BEFORE UPDATE ON service FOR EACH ROW EXECUTE FUNCTION update_timestamps();

CREATE TRIGGER trg_skill_updated_at
BEFORE UPDATE ON skill FOR EACH ROW EXECUTE FUNCTION update_timestamps();

-- === Agent/Organ relations (edge tables) ===
CREATE TABLE IF NOT EXISTS agent_member_of_organ (
  agent_id   TEXT NOT NULL REFERENCES agent_registry(agent_id) ON DELETE CASCADE,
  organ_id   TEXT NOT NULL REFERENCES organ_registry(organ_id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (agent_id, organ_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_member_of_organ_agent ON agent_member_of_organ(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_member_of_organ_organ ON agent_member_of_organ(organ_id);

CREATE TABLE IF NOT EXISTS agent_collab_agent (
  src_agent  TEXT NOT NULL REFERENCES agent_registry(agent_id) ON DELETE CASCADE,
  dst_agent  TEXT NOT NULL REFERENCES agent_registry(agent_id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (src_agent, dst_agent)
);

-- Extend agent_collab_agent to be a proper virtual network overlay
ALTER TABLE agent_collab_agent
  ADD COLUMN IF NOT EXISTS weight      REAL   NOT NULL DEFAULT 0.5,
  ADD COLUMN IF NOT EXISTS bond_kind   TEXT   NOT NULL DEFAULT 'functional',  -- e.g., 'strong_pair', 'cross_organ', 'learned'
  ADD COLUMN IF NOT EXISTS meta        JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Optional: if you want overlay per epoch/version
-- ALTER TABLE agent_collab_agent
--   ADD COLUMN IF NOT EXISTS overlay_epoch UUID;

CREATE INDEX IF NOT EXISTS idx_agent_collab_src ON agent_collab_agent(src_agent);
CREATE INDEX IF NOT EXISTS idx_agent_collab_dst ON agent_collab_agent(dst_agent);

CREATE TABLE IF NOT EXISTS organ_provides_skill (
  organ_id    TEXT NOT NULL REFERENCES organ_registry(organ_id) ON DELETE CASCADE,
  skill_name  TEXT NOT NULL REFERENCES skill(skill_name)        ON DELETE CASCADE,
  created_at  TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (organ_id, skill_name)
);

CREATE INDEX IF NOT EXISTS idx_organ_provides_skill_organ ON organ_provides_skill(organ_id);
CREATE INDEX IF NOT EXISTS idx_organ_provides_skill_skill ON organ_provides_skill(skill_name);

CREATE TABLE IF NOT EXISTS organ_uses_service (
  organ_id     TEXT NOT NULL REFERENCES organ_registry(organ_id) ON DELETE CASCADE,
  service_name TEXT NOT NULL REFERENCES service(service_name)     ON DELETE CASCADE,
  created_at   TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (organ_id, service_name)
);

CREATE INDEX IF NOT EXISTS idx_organ_uses_service_organ ON organ_uses_service(organ_id);
CREATE INDEX IF NOT EXISTS idx_organ_uses_service_serv  ON organ_uses_service(service_name);

CREATE TABLE IF NOT EXISTS organ_governed_by_policy (
  organ_id    TEXT NOT NULL REFERENCES organ_registry(organ_id) ON DELETE CASCADE,
  policy_name TEXT NOT NULL REFERENCES policy(policy_name)       ON DELETE CASCADE,
  created_at  TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (organ_id, policy_name)
);

CREATE INDEX IF NOT EXISTS idx_organ_governed_by_policy_organ  ON organ_governed_by_policy(organ_id);
CREATE INDEX IF NOT EXISTS idx_organ_governed_by_policy_policy ON organ_governed_by_policy(policy_name);

CREATE TABLE IF NOT EXISTS agent_uses_model (
  agent_id   TEXT NOT NULL REFERENCES agent_registry(agent_id) ON DELETE CASCADE,
  model_name TEXT NOT NULL REFERENCES model(model_name)        ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (agent_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_agent_uses_model_agent ON agent_uses_model(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_uses_model_model ON agent_uses_model(model_name);

-- === ensure_* helpers: TEXT keys must use ext_text_id in graph_node_map ===
CREATE OR REPLACE FUNCTION ensure_model_node(p_name TEXT)
RETURNS BIGINT AS $$
DECLARE nid BIGINT;
BEGIN
  INSERT INTO model(model_name) VALUES (p_name) ON CONFLICT DO NOTHING;
  SELECT node_id INTO nid
    FROM graph_node_map
   WHERE node_type='model' AND ext_table='model' AND ext_text_id=p_name;
  IF nid IS NULL THEN
    INSERT INTO graph_node_map(node_type, ext_table, ext_text_id)
    VALUES ('model','model',p_name)
    RETURNING node_id INTO nid;
  END IF;
  RETURN nid;
END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION ensure_policy_node(p_name TEXT)
RETURNS BIGINT AS $$
DECLARE nid BIGINT;
BEGIN
  INSERT INTO policy(policy_name) VALUES (p_name) ON CONFLICT DO NOTHING;
  SELECT node_id INTO nid
    FROM graph_node_map
   WHERE node_type='policy' AND ext_table='policy' AND ext_text_id=p_name;
  IF nid IS NULL THEN
    INSERT INTO graph_node_map(node_type, ext_table, ext_text_id)
    VALUES ('policy','policy',p_name)
    RETURNING node_id INTO nid;
  END IF;
  RETURN nid;
END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION ensure_service_node(p_name TEXT)
RETURNS BIGINT AS $$
DECLARE nid BIGINT;
BEGIN
  INSERT INTO service(service_name) VALUES (p_name) ON CONFLICT DO NOTHING;
  SELECT node_id INTO nid
    FROM graph_node_map
   WHERE node_type='service' AND ext_table='service' AND ext_text_id=p_name;
  IF nid IS NULL THEN
    INSERT INTO graph_node_map(node_type, ext_table, ext_text_id)
    VALUES ('service','service',p_name)
    RETURNING node_id INTO nid;
  END IF;
  RETURN nid;
END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION ensure_skill_node(p_name TEXT)
RETURNS BIGINT AS $$
DECLARE nid BIGINT;
BEGIN
  INSERT INTO skill(skill_name) VALUES (p_name) ON CONFLICT DO NOTHING;
  SELECT node_id INTO nid
    FROM graph_node_map
   WHERE node_type='skill' AND ext_table='skill' AND ext_text_id=p_name;
  IF nid IS NULL THEN
    INSERT INTO graph_node_map(node_type, ext_table, ext_text_id)
    VALUES ('skill','skill',p_name)
    RETURNING node_id INTO nid;
  END IF;
  RETURN nid;
END; $$ LANGUAGE plpgsql;

-- === Extend the unified HGNN edge view ===
-- NOTE: We re-specify the full view: keep all 007 unions, then append new ones.
CREATE OR REPLACE VIEW hgnn_edges AS
  -- task -> task (depends_on)
  SELECT ensure_task_node(d.src_task_id) AS src_node_id,
         ensure_task_node(d.dst_task_id) AS dst_node_id,
         'task__depends_on__task'::TEXT AS edge_type
    FROM task_depends_on_task d
  UNION ALL
  -- task -> artifact
  SELECT ensure_task_node(p.task_id),
         m.node_id,
         'task__produces__artifact'
    FROM task_produces_artifact p
    JOIN graph_node_map m
      ON m.node_type='artifact' AND m.ext_table='artifact' AND m.ext_uuid = p.artifact_id
  UNION ALL
  -- task -> capability (uses)
  SELECT ensure_task_node(u.task_id),
         m.node_id,
         'task__uses__capability'
    FROM task_uses_capability u
    JOIN graph_node_map m
      ON m.node_type='capability' AND m.ext_table='capability' AND m.ext_uuid = u.capability_id
  UNION ALL
  -- task -> memory_cell (reads)
  SELECT ensure_task_node(r.task_id),
         m.node_id,
         'task__reads__memory_cell'
    FROM task_reads_memory r
    JOIN graph_node_map m
      ON m.node_type='memory_cell' AND m.ext_table='memory_cell' AND m.ext_uuid = r.memory_cell_id
  UNION ALL
  -- task -> memory_cell (writes)
  SELECT ensure_task_node(w.task_id),
         m.node_id,
         'task__writes__memory_cell'
    FROM task_writes_memory w
    JOIN graph_node_map m
      ON m.node_type='memory_cell' AND m.ext_table='memory_cell' AND m.ext_uuid = w.memory_cell_id
  UNION ALL
  -- task -> organ (executed_by)
  SELECT ensure_task_node(e.task_id),
         ensure_organ_node(e.organ_id),
         'task__executed_by__organ'
    FROM task_executed_by_organ e
  UNION ALL
  -- task -> agent (owned_by)
  SELECT ensure_task_node(o.task_id),
         ensure_agent_node(o.agent_id),
         'task__owned_by__agent'
    FROM task_owned_by_agent o
  UNION ALL
  -- NEW agent/organ unions
  SELECT ensure_agent_node(a.agent_id),
         ensure_organ_node(a.organ_id),
         'agent__member_of__organ'
    FROM agent_member_of_organ a
  UNION ALL
  SELECT ensure_agent_node(c.src_agent),
         ensure_agent_node(c.dst_agent),
         'agent__collab__agent'
    FROM agent_collab_agent c
  UNION ALL
  SELECT ensure_organ_node(ps.organ_id),
         ensure_skill_node(ps.skill_name),
         'organ__provides__skill'
    FROM organ_provides_skill ps
  UNION ALL
  SELECT ensure_organ_node(us.organ_id),
         ensure_service_node(us.service_name),
         'organ__uses__service'
    FROM organ_uses_service us
  UNION ALL
  SELECT ensure_agent_node(am.agent_id),
         ensure_model_node(am.model_name),
         'agent__uses__model'
    FROM agent_uses_model am
  UNION ALL
  SELECT ensure_organ_node(gb.organ_id),
         ensure_policy_node(gb.policy_name),
         'organ__governed_by__policy'
    FROM organ_governed_by_policy gb
;

COMMENT ON VIEW hgnn_edges IS 'Flattened hetero-graph edges (numeric src/dst + type) for DGL export';

COMMIT;
