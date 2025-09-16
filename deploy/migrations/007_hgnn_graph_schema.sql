-- 007_hgnn_graph_schema.sql
-- Purpose: Add a comprehensive two-layer HGNN schema (Task layer + Agent/Organ layer),
--          cross-layer edges, numeric node-id mapping for DGL, and integration with
--          existing task + embedding infrastructure.

BEGIN;

-- 0) Safety notes (idempotency)
--    All CREATEs use IF NOT EXISTS. No destructive changes.

-- 1) Canonical node-id mapping (lets DGL use BIGINT while business tables keep UUID/TEXT)
CREATE TABLE IF NOT EXISTS graph_node_map (
    node_id      BIGSERIAL PRIMARY KEY,
    node_type    TEXT NOT NULL,                 -- e.g., 'task','agent','organ','artifact','capability','memory_cell'
    ext_table    TEXT NOT NULL,                 -- e.g., 'tasks','agent_registry','organ_registry', etc.
    ext_uuid     UUID NULL,                     -- for UUID-based rows (e.g., tasks)
    ext_text_id  TEXT NULL,                     -- for TEXT-based ids (e.g., organ_id/agent_id)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (node_type, ext_table, ext_uuid),
    UNIQUE (node_type, ext_table, ext_text_id)
);

CREATE OR REPLACE FUNCTION update_graph_node_map_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_graph_node_map_updated_at ON graph_node_map;
CREATE TRIGGER trg_graph_node_map_updated_at
BEFORE UPDATE ON graph_node_map
FOR EACH ROW EXECUTE FUNCTION update_graph_node_map_updated_at();

-- Convenience upsert helpers to ensure node-ids exist
CREATE OR REPLACE FUNCTION ensure_task_node(p_task_id UUID)
RETURNS BIGINT AS $$
DECLARE
  nid BIGINT;
BEGIN
  SELECT node_id INTO nid
  FROM graph_node_map
  WHERE node_type='task' AND ext_table='tasks' AND ext_uuid=p_task_id;

  IF nid IS NULL THEN
    INSERT INTO graph_node_map (node_type, ext_table, ext_uuid)
    VALUES ('task','tasks',p_task_id)
    RETURNING node_id INTO nid;
  END IF;
  RETURN nid;
END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION ensure_agent_node(p_agent_id TEXT)
RETURNS BIGINT AS $$
DECLARE
  nid BIGINT;
BEGIN
  SELECT node_id INTO nid
  FROM graph_node_map
  WHERE node_type='agent' AND ext_table='agent_registry' AND ext_text_id=p_agent_id;

  IF nid IS NULL THEN
    INSERT INTO graph_node_map (node_type, ext_table, ext_text_id)
    VALUES ('agent','agent_registry',p_agent_id)
    RETURNING node_id INTO nid;
  END IF;
  RETURN nid;
END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION ensure_organ_node(p_organ_id TEXT)
RETURNS BIGINT AS $$
DECLARE
  nid BIGINT;
BEGIN
  SELECT node_id INTO nid
  FROM graph_node_map
  WHERE node_type='organ' AND ext_table='organ_registry' AND ext_text_id=p_organ_id;

  IF nid IS NULL THEN
    INSERT INTO graph_node_map (node_type, ext_table, ext_text_id)
    VALUES ('organ','organ_registry',p_organ_id)
    RETURNING node_id INTO nid;
  END IF;
  RETURN nid;
END; $$ LANGUAGE plpgsql;

-- 2) Minimal registries for Agents/Organs (keys are TEXT in runtime; keep TEXT in DB too)
CREATE TABLE IF NOT EXISTS agent_registry (
  agent_id    TEXT PRIMARY KEY,
  display_name TEXT NULL,
  props       JSONB NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS organ_registry (
  organ_id    TEXT PRIMARY KEY,
  agent_id    TEXT NULL REFERENCES agent_registry(agent_id) ON UPDATE CASCADE ON DELETE SET NULL,
  kind        TEXT NULL,    -- e.g., 'utility','actuator','retriever', etc.
  props       JSONB NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION update_timestamps()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_agent_registry_updated_at ON agent_registry;
CREATE TRIGGER trg_agent_registry_updated_at
BEFORE UPDATE ON agent_registry
FOR EACH ROW EXECUTE FUNCTION update_timestamps();

DROP TRIGGER IF EXISTS trg_organ_registry_updated_at ON organ_registry;
CREATE TRIGGER trg_organ_registry_updated_at
BEFORE UPDATE ON organ_registry
FOR EACH ROW EXECUTE FUNCTION update_timestamps();

-- 3) HGNN: Task-layer resource tables (artifact, capability, memory_cell)
CREATE TABLE IF NOT EXISTS artifact (
  artifact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  uri         TEXT NOT NULL,
  kind        TEXT NULL,         -- e.g., 'file','s3','vector','blob'
  props       JSONB NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS capability (
  capability_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT UNIQUE NOT NULL,  -- e.g., 'summarize','embed','plan-route'
  props         JSONB NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS memory_cell (
  memory_cell_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scope          TEXT NOT NULL,       -- e.g., 'agent','organ','global'
  mkey           TEXT NOT NULL,
  version        INTEGER NOT NULL DEFAULT 1,
  props          JSONB NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(scope, mkey, version)
);

-- 4) HGNN: Task-layer edges (as discussed in your paper)
-- ("task","depends_on","task")
CREATE TABLE IF NOT EXISTS task_depends_on_task (
  id BIGSERIAL PRIMARY KEY,
  src_task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  dst_task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (src_task_id, dst_task_id)
);

-- ("task","produces","artifact")
CREATE TABLE IF NOT EXISTS task_produces_artifact (
  id BIGSERIAL PRIMARY KEY,
  task_id     UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  artifact_id UUID NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (task_id, artifact_id)
);

-- ("task","uses","capability")
CREATE TABLE IF NOT EXISTS task_uses_capability (
  id BIGSERIAL PRIMARY KEY,
  task_id       UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  capability_id UUID NOT NULL REFERENCES capability(capability_id) ON DELETE RESTRICT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (task_id, capability_id)
);

-- ("task","reads","memory_cell")
CREATE TABLE IF NOT EXISTS task_reads_memory (
  id BIGSERIAL PRIMARY KEY,
  task_id        UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  memory_cell_id UUID NOT NULL REFERENCES memory_cell(memory_cell_id) ON DELETE RESTRICT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (task_id, memory_cell_id)
);

-- ("task","writes","memory_cell")
CREATE TABLE IF NOT EXISTS task_writes_memory (
  id BIGSERIAL PRIMARY KEY,
  task_id        UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  memory_cell_id UUID NOT NULL REFERENCES memory_cell(memory_cell_id) ON DELETE RESTRICT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (task_id, memory_cell_id)
);

-- 5) Agent-layer capability binding (optional but useful)
-- ("organ","provides","capability"); ("agent","owns","memory_cell")
CREATE TABLE IF NOT EXISTS organ_provides_capability (
  id BIGSERIAL PRIMARY KEY,
  organ_id      TEXT NOT NULL REFERENCES organ_registry(organ_id) ON DELETE CASCADE,
  capability_id UUID NOT NULL REFERENCES capability(capability_id) ON DELETE CASCADE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (organ_id, capability_id)
);

CREATE TABLE IF NOT EXISTS agent_owns_memory_cell (
  id BIGSERIAL PRIMARY KEY,
  agent_id       TEXT NOT NULL REFERENCES agent_registry(agent_id) ON DELETE CASCADE,
  memory_cell_id UUID NOT NULL REFERENCES memory_cell(memory_cell_id) ON DELETE CASCADE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (agent_id, memory_cell_id)
);

-- 6) Cross-layer edges (the ones you asked to double-confirm)
-- ("task","executed_by","organ"), ("task","owned_by","agent")
CREATE TABLE IF NOT EXISTS task_executed_by_organ (
  id BIGSERIAL PRIMARY KEY,
  task_id  UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  organ_id TEXT NOT NULL REFERENCES organ_registry(organ_id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (task_id, organ_id)
);

CREATE TABLE IF NOT EXISTS task_owned_by_agent (
  id BIGSERIAL PRIMARY KEY,
  task_id  UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  agent_id TEXT NOT NULL REFERENCES agent_registry(agent_id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (task_id, agent_id)
);

-- 7) Indexes tuned for common traversals
CREATE INDEX IF NOT EXISTS idx_task_dep_src ON task_depends_on_task(src_task_id);
CREATE INDEX IF NOT EXISTS idx_task_dep_dst ON task_depends_on_task(dst_task_id);
CREATE INDEX IF NOT EXISTS idx_task_prod_task ON task_produces_artifact(task_id);
CREATE INDEX IF NOT EXISTS idx_task_uses_task ON task_uses_capability(task_id);
CREATE INDEX IF NOT EXISTS idx_task_reads_task ON task_reads_memory(task_id);
CREATE INDEX IF NOT EXISTS idx_task_writes_task ON task_writes_memory(task_id);
CREATE INDEX IF NOT EXISTS idx_task_exec_task ON task_executed_by_organ(task_id);
CREATE INDEX IF NOT EXISTS idx_task_owned_task ON task_owned_by_agent(task_id);
CREATE INDEX IF NOT EXISTS idx_organ_cap_organ ON organ_provides_capability(organ_id);
CREATE INDEX IF NOT EXISTS idx_agent_mem_agent ON agent_owns_memory_cell(agent_id);

-- 8) Binding to existing graph_embeddings table (kept as-is)
-- We expose a view that ties 'task' nodes to the BIGINT node_id used by graph_embeddings.
-- (Your graph_embeddings table already exists with node_id BIGINT + vector index.)
-- NOTE: populate graph_node_map for tasks to use this view.
CREATE OR REPLACE VIEW task_embeddings AS
SELECT
  t.id              AS task_id,
  m.node_id         AS node_id,
  e.emb             AS emb,
  e.label,
  e.props,
  e.created_at,
  e.updated_at
FROM tasks t
JOIN graph_node_map m
  ON m.node_type='task' AND m.ext_table='tasks' AND m.ext_uuid=t.id
JOIN graph_embeddings e
  ON e.node_id = m.node_id;

-- 9) Unified edge view for DGL ingest (numeric node ids + typed edge label)
--    This “flattens” heterogenous edges into (src_nid, dst_nid, edge_type).
CREATE OR REPLACE VIEW hgnn_edges AS
    -- task -> task (depends_on)
    SELECT
      ensure_task_node(d.src_task_id) AS src_node_id,
      ensure_task_node(d.dst_task_id) AS dst_node_id,
      'task__depends_on__task'::TEXT  AS edge_type
    FROM task_depends_on_task d
UNION ALL
    -- task -> artifact
    SELECT
      ensure_task_node(p.task_id)     AS src_node_id,
      m.node_id                       AS dst_node_id,
      'task__produces__artifact'::TEXT
    FROM task_produces_artifact p
    JOIN graph_node_map m ON m.node_type='artifact' AND m.ext_table='artifact' AND m.ext_uuid = p.artifact_id
UNION ALL
    -- task -> capability (uses)
    SELECT
      ensure_task_node(u.task_id)     AS src_node_id,
      m.node_id                       AS dst_node_id,
      'task__uses__capability'::TEXT
    FROM task_uses_capability u
    JOIN graph_node_map m ON m.node_type='capability' AND m.ext_table='capability' AND m.ext_uuid = u.capability_id
UNION ALL
    -- task -> memory_cell (reads)
    SELECT
      ensure_task_node(r.task_id)     AS src_node_id,
      m.node_id                       AS dst_node_id,
      'task__reads__memory_cell'::TEXT
    FROM task_reads_memory r
    JOIN graph_node_map m ON m.node_type='memory_cell' AND m.ext_table='memory_cell' AND m.ext_uuid = r.memory_cell_id
UNION ALL
    -- task -> memory_cell (writes)
    SELECT
      ensure_task_node(w.task_id)     AS src_node_id,
      m.node_id                       AS dst_node_id,
      'task__writes__memory_cell'::TEXT
    FROM task_writes_memory w
    JOIN graph_node_map m ON m.node_type='memory_cell' AND m.ext_table='memory_cell' AND m.ext_uuid = w.memory_cell_id
UNION ALL
    -- task -> organ (executed_by)
    SELECT
      ensure_task_node(x.task_id)     AS src_node_id,
      ensure_organ_node(x.organ_id)   AS dst_node_id,
      'task__executed_by__organ'::TEXT
    FROM task_executed_by_organ x
UNION ALL
    -- task -> agent (owned_by)
    SELECT
      ensure_task_node(o.task_id)     AS src_node_id,
      ensure_agent_node(o.agent_id)   AS dst_node_id,
      'task__owned_by__agent'::TEXT
    FROM task_owned_by_agent o
;

-- 10) Backfill helpers (optional)
-- Map existing tasks to node ids (run once if you want immediate availability in views)
CREATE OR REPLACE FUNCTION backfill_task_nodes()
RETURNS INTEGER AS $$
DECLARE
  c INTEGER := 0;
BEGIN
  INSERT INTO graph_node_map(node_type, ext_table, ext_uuid)
  SELECT 'task','tasks',t.id
  FROM tasks t
  LEFT JOIN graph_node_map m
    ON m.node_type='task' AND m.ext_table='tasks' AND m.ext_uuid=t.id
  WHERE m.node_id IS NULL;
  GET DIAGNOSTICS c = ROW_COUNT;
  RETURN c;
END; $$ LANGUAGE plpgsql;

-- 11) Overloaded graph task creators (v2) that can attach cross-layer edges
--     (keeps your old functions intact; these add optional agent/organ wiring)
CREATE OR REPLACE FUNCTION create_graph_embed_task_v2(
    start_node_ids INTEGER[],
    k_hops INTEGER DEFAULT 2,
    description TEXT DEFAULT NULL,
    p_agent_id TEXT DEFAULT NULL,
    p_organ_id TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    task_id UUID;
BEGIN
    INSERT INTO tasks(type, status, description, params, drift_score)
    VALUES (
        'graph_embed',
        'queued',
        COALESCE(description, format('Embed %s-hop neighborhood around nodes %s',
                 k_hops, array_to_string(start_node_ids, ', '))),
        jsonb_build_object('start_ids', start_node_ids, 'k', k_hops),
        0.0
    ) RETURNING id INTO task_id;

    -- attach cross-layer edges if provided
    IF p_agent_id IS NOT NULL THEN
        INSERT INTO agent_registry(agent_id) VALUES (p_agent_id)
        ON CONFLICT (agent_id) DO NOTHING;
        INSERT INTO task_owned_by_agent(task_id, agent_id)
        VALUES (task_id, p_agent_id)
        ON CONFLICT DO NOTHING;
    END IF;

    IF p_organ_id IS NOT NULL THEN
        INSERT INTO organ_registry(organ_id, agent_id)
        VALUES (p_organ_id, p_agent_id)  -- p_agent_id may be NULL
        ON CONFLICT (organ_id) DO NOTHING;
        INSERT INTO task_executed_by_organ(task_id, organ_id)
        VALUES (task_id, p_organ_id)
        ON CONFLICT DO NOTHING;
    END IF;

    PERFORM ensure_task_node(task_id);
    RETURN task_id;
END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION create_graph_rag_task_v2(
    start_node_ids INTEGER[],
    k_hops INTEGER DEFAULT 2,
    top_k INTEGER DEFAULT 10,
    description TEXT DEFAULT NULL,
    p_agent_id TEXT DEFAULT NULL,
    p_organ_id TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    task_id UUID;
BEGIN
    INSERT INTO tasks(type, status, description, params, drift_score)
    VALUES (
        'graph_rag_query',
        'queued',
        COALESCE(description, format('RAG query %s-hop neighborhood around nodes %s, top %s',
                 k_hops, array_to_string(start_node_ids, ', '), top_k)),
        jsonb_build_object('start_ids', start_node_ids, 'k', k_hops, 'topk', top_k),
        0.0
    ) RETURNING id INTO task_id;

    IF p_agent_id IS NOT NULL THEN
        INSERT INTO agent_registry(agent_id) VALUES (p_agent_id)
        ON CONFLICT (agent_id) DO NOTHING;
        INSERT INTO task_owned_by_agent(task_id, agent_id)
        VALUES (task_id, p_agent_id)
        ON CONFLICT DO NOTHING;
    END IF;

    IF p_organ_id IS NOT NULL THEN
        INSERT INTO organ_registry(organ_id, agent_id)
        VALUES (p_organ_id, p_agent_id)
        ON CONFLICT (organ_id) DO NOTHING;
        INSERT INTO task_executed_by_organ(task_id, organ_id)
        VALUES (task_id, p_organ_id)
        ON CONFLICT DO NOTHING;
    END IF;

    PERFORM ensure_task_node(task_id);
    RETURN task_id;
END; $$ LANGUAGE plpgsql;

-- 12) Comments to tie back to your execution/runtime
COMMENT ON VIEW hgnn_edges IS 'Flattened hetero-graph edges (numeric src/dst + type) for DGL export';
COMMENT ON VIEW task_embeddings IS 'Convenience join: tasks ↔ graph_node_map ↔ graph_embeddings';

-- Optional: tiny check
DO $$
BEGIN
  RAISE NOTICE 'HGNN graph schema migration applied';
END$$;

COMMIT;

