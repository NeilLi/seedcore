-- Combined HGNN Schema Migration
-- Purpose: Creates the complete two-layer HGNN schema, node mappers,
--          graph-aware task creators, and monitoring views.

BEGIN;

-- 0) Safety notes (idempotency)
--    All CREATEs use IF NOT EXISTS. No destructive changes.

-- 1) Monitoring View (from graph_tasks migration)
COMMENT ON COLUMN tasks.type IS 'Type/category of the task (e.g., graph_embed, graph_rag_query)';

-- Drop view first to allow column changes (CREATE OR REPLACE cannot drop columns)
DROP VIEW IF EXISTS graph_tasks;

CREATE VIEW graph_tasks AS
SELECT
    id,
    type,
    status,
    attempts,
    locked_by,
    locked_at,
    run_after,
    params,
    result,
    error,
    created_at,
    updated_at,
    drift_score,
    CASE
        WHEN status = 'completed' THEN '✅'
        WHEN status = 'running' THEN '🔄'
        WHEN status = 'queued' THEN '⏳'
        WHEN status = 'failed' THEN '❌'
        ELSE '❓'
    END as status_emoji
FROM tasks
WHERE type IN ('graph_embed', 'graph_rag_query')
ORDER BY updated_at DESC;

COMMENT ON VIEW graph_tasks IS 'View for monitoring graph-related tasks';
COMMENT ON COLUMN graph_tasks.status_emoji IS 'Visual status indicator';


-- 2) Canonical node-id mapping (for DGL)
CREATE TABLE IF NOT EXISTS graph_node_map (
    node_id      BIGSERIAL PRIMARY KEY,
    node_type    TEXT NOT NULL,                 -- e.g., 'task','agent','organ','artifact','capability','memory_cell'
    ext_table    TEXT NOT NULL,                 -- e.g., 'tasks','agent_registry','organ_registry', etc.
    ext_uuid     UUID NULL,
    ext_text_id  TEXT NULL,
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

-- Convenience upsert helpers
CREATE OR REPLACE FUNCTION ensure_task_node(p_task_id UUID)
RETURNS BIGINT AS $$
DECLARE
  nid BIGINT;
BEGIN
  INSERT INTO graph_node_map (node_type, ext_table, ext_uuid)
  VALUES ('task','tasks',p_task_id)
  ON CONFLICT (node_type, ext_table, ext_uuid)
  DO UPDATE SET updated_at = NOW()
  RETURNING node_id INTO nid;
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

-- 3) Minimal registries for Agents/Organs
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
  kind        TEXT NULL,
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

-- 4) HGNN: Task-layer resource tables
CREATE TABLE IF NOT EXISTS artifact (
  artifact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  uri         TEXT NOT NULL,
  kind        TEXT NULL,
  props       JSONB NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS capability (
  capability_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT UNIQUE NOT NULL,
  props         JSONB NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS memory_cell (
  memory_cell_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scope          TEXT NOT NULL,
  mkey           TEXT NOT NULL,
  version        INTEGER NOT NULL DEFAULT 1,
  props          JSONB NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(scope, mkey, version)
);

-- 5) HGNN: Task-layer edges
CREATE TABLE IF NOT EXISTS task_depends_on_task (
  id BIGSERIAL PRIMARY KEY,
  src_task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  dst_task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (src_task_id, dst_task_id)
);

CREATE TABLE IF NOT EXISTS task_produces_artifact (
  id BIGSERIAL PRIMARY KEY,
  task_id     UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  artifact_id UUID NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (task_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS task_uses_capability (
  id BIGSERIAL PRIMARY KEY,
  task_id       UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  capability_id UUID NOT NULL REFERENCES capability(capability_id) ON DELETE RESTRICT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (task_id, capability_id)
);

CREATE TABLE IF NOT EXISTS task_reads_memory (
  id BIGSERIAL PRIMARY KEY,
  task_id        UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  memory_cell_id UUID NOT NULL REFERENCES memory_cell(memory_cell_id) ON DELETE RESTRICT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (task_id, memory_cell_id)
);

CREATE TABLE IF NOT EXISTS task_writes_memory (
  id BIGSERIAL PRIMARY KEY,
  task_id        UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  memory_cell_id UUID NOT NULL REFERENCES memory_cell(memory_cell_id) ON DELETE RESTRICT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (task_id, memory_cell_id)
);

-- 6) Agent-layer capability binding
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

-- 7) Cross-layer edges
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

-- 8) Indexes
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

-- 9) Binding to separate graph_embeddings tables (128d and 1024d)
CREATE OR REPLACE VIEW task_embeddings_128 AS
SELECT
  t.id              AS task_id,
  m.node_id         AS node_id,
  e.emb             AS emb,
  e.label,
  e.props,
  e.model,
  e.content_sha256,
  e.created_at,
  e.updated_at
FROM tasks t
JOIN graph_node_map m
  ON m.node_type='task' AND m.ext_table='tasks' AND m.ext_uuid=t.id
LEFT JOIN graph_embeddings_128 e
  ON e.node_id = m.node_id;

CREATE OR REPLACE VIEW task_embeddings_1024 AS
SELECT
  t.id              AS task_id,
  m.node_id         AS node_id,
  e.emb             AS emb,
  e.label,
  e.props,
  e.model,
  e.content_sha256,
  e.created_at,
  e.updated_at
FROM tasks t
JOIN graph_node_map m
  ON m.node_type='task' AND m.ext_table='tasks' AND m.ext_uuid=t.id
LEFT JOIN graph_embeddings_1024 e
  ON e.node_id = m.node_id;

-- 10) Unified edge view for DGL ingest
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

-- 11) Backfill helpers (optional)
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

-- 12) Graph task creators (FINAL VERSION)
--     These now attach cross-layer edges for agent/organ
CREATE OR REPLACE FUNCTION create_graph_embed_task(
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
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION create_graph_rag_task(
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
END;
$$ LANGUAGE plpgsql;

-- 13) Comments
-- Specify full function signatures to disambiguate from migration 001 versions
COMMENT ON FUNCTION create_graph_embed_task(INTEGER[], INTEGER, TEXT, TEXT, TEXT) IS 'Helper function to create graph embedding tasks, optionally linking them to an agent/organ';
COMMENT ON FUNCTION create_graph_rag_task(INTEGER[], INTEGER, INTEGER, TEXT, TEXT, TEXT) IS 'Helper function to create graph RAG query tasks, optionally linking them to an agent/organ';
COMMENT ON VIEW hgnn_edges IS 'Flattened hetero-graph edges (numeric src/dst + type) for DGL export';
COMMENT ON VIEW task_embeddings_128 IS 'Convenience join: tasks ↔ graph_node_map ↔ graph_embeddings_128 (128d embeddings)';
COMMENT ON VIEW task_embeddings_1024 IS 'Convenience join: tasks ↔ graph_node_map ↔ graph_embeddings_1024 (1024d embeddings)';

-- 14) Example usage
/*
-- Example 1: Embed 2-hop neighborhood, owned by an agent
SELECT create_graph_embed_task(
    ARRAY[123],
    2,
    'Embed neighborhood around user node 123',
    'agent_xyz_123',  -- p_agent_id
    'organ_processing_A' -- p_organ_id
);

-- Example 2: RAG query, no owner
SELECT create_graph_rag_task(
    ARRAY[123, 456],
    2,
    15,
    'Find similar nodes to users 123 and 456 for RAG augmentation'
);
*/

-- 15) Final sanity notice
DO $$
BEGIN
  RAISE NOTICE '✅ Combined HGNN graph schema migration applied';
END$$;

COMMIT;