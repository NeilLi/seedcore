-- 012_task_fact_integration.sql
-- Purpose: Integrate the 'facts' table into the HGNN, completing the memory-action loop.

BEGIN;

-- 1) Helper: ensure a numeric node_id exists for a fact (UUID-keyed)
-- Note: snapshot_id will be set by the application layer or migration 017 backfill
CREATE OR REPLACE FUNCTION ensure_fact_node(p_fact_id UUID)
RETURNS BIGINT AS $$
DECLARE
  nid BIGINT;
BEGIN
  SELECT node_id INTO nid
  FROM graph_node_map
  WHERE node_type='fact' AND ext_table='facts' AND ext_uuid=p_fact_id;

  IF nid IS NULL THEN
    INSERT INTO graph_node_map (node_type, ext_table, ext_uuid)
    VALUES ('fact','facts',p_fact_id)
    RETURNING node_id INTO nid;
  END IF;
  RETURN nid;
END; $$ LANGUAGE plpgsql;

-- 2) Edge tables: task ↔ fact relations
CREATE TABLE IF NOT EXISTS task_reads_fact (
  id BIGSERIAL PRIMARY KEY,
  task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  fact_id UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (task_id, fact_id)
);

CREATE INDEX IF NOT EXISTS idx_task_reads_fact_task ON task_reads_fact(task_id);
CREATE INDEX IF NOT EXISTS idx_task_reads_fact_fact ON task_reads_fact(fact_id);

CREATE TABLE IF NOT EXISTS task_produces_fact (
  id BIGSERIAL PRIMARY KEY,
  task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  fact_id UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (task_id, fact_id)
);

CREATE INDEX IF NOT EXISTS idx_task_produces_fact_task ON task_produces_fact(task_id);
CREATE INDEX IF NOT EXISTS idx_task_produces_fact_fact ON task_produces_fact(fact_id);

-- 3) Extend unified HGNN edge view with fact relations
--     We preserve all unions from 008_hgnn_agent_layer.sql and append new ones.
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
  -- agent/organ unions
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
  UNION ALL
  -- NEW: task -> fact (reads)
  SELECT ensure_task_node(trf.task_id) AS src_node_id,
         ensure_fact_node(trf.fact_id) AS dst_node_id,
         'task__reads__fact'::TEXT
    FROM task_reads_fact trf
  UNION ALL
  -- NEW: task -> fact (produces)
  SELECT ensure_task_node(tpf.task_id) AS src_node_id,
         ensure_fact_node(tpf.fact_id) AS dst_node_id,
         'task__produces__fact'::TEXT
    FROM task_produces_fact tpf;

COMMENT ON VIEW hgnn_edges IS 'Flattened hetero-graph edges (numeric src/dst + type) for DGL export';

COMMIT;


