-- verify_hgnn_graph_schema.sql
-- Purpose: Verify presence and basic integrity of objects introduced by 007_hgnn_graph_schema.sql
-- Safe to run multiple times. Read-only except metadata queries.

-- Show server and current database/user
SELECT version() AS postgres_version;
SELECT current_database() AS db, current_user AS usr;

-- Section 1: Tables
SELECT 'graph_node_map'                    AS object, CASE WHEN to_regclass('public.graph_node_map') IS NOT NULL THEN 'OK' ELSE 'MISSING' END AS status
UNION ALL SELECT 'agent_registry',               CASE WHEN to_regclass('public.agent_registry') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'organ_registry',               CASE WHEN to_regclass('public.organ_registry') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'artifact',                     CASE WHEN to_regclass('public.artifact') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'capability',                   CASE WHEN to_regclass('public.capability') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'memory_cell',                  CASE WHEN to_regclass('public.memory_cell') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'task_depends_on_task',         CASE WHEN to_regclass('public.task_depends_on_task') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'task_produces_artifact',       CASE WHEN to_regclass('public.task_produces_artifact') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'task_uses_capability',         CASE WHEN to_regclass('public.task_uses_capability') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'task_reads_memory',            CASE WHEN to_regclass('public.task_reads_memory') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'task_writes_memory',           CASE WHEN to_regclass('public.task_writes_memory') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'organ_provides_capability',    CASE WHEN to_regclass('public.organ_provides_capability') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'agent_owns_memory_cell',       CASE WHEN to_regclass('public.agent_owns_memory_cell') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'task_executed_by_organ',       CASE WHEN to_regclass('public.task_executed_by_organ') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'task_owned_by_agent',          CASE WHEN to_regclass('public.task_owned_by_agent') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
ORDER BY object;

-- Section 2: Views
SELECT 'graph_tasks' AS view, CASE WHEN to_regclass('public.graph_tasks') IS NOT NULL THEN 'OK' ELSE 'MISSING' END AS status
UNION ALL SELECT 'hgnn_edges', CASE WHEN to_regclass('public.hgnn_edges') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'task_embeddings_128', CASE WHEN to_regclass('public.task_embeddings_128') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'task_embeddings_1024', CASE WHEN to_regclass('public.task_embeddings_1024') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
ORDER BY view;

-- Section 3: Functions (presence via to_regprocedure)
SELECT 'ensure_task_node(uuid)'                                   AS function, CASE WHEN to_regprocedure('ensure_task_node(uuid)') IS NOT NULL THEN 'OK' ELSE 'MISSING' END AS status
UNION ALL SELECT 'ensure_agent_node(text)',                        CASE WHEN to_regprocedure('ensure_agent_node(text)') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'ensure_organ_node(text)',                        CASE WHEN to_regprocedure('ensure_organ_node(text)') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'update_graph_node_map_updated_at()',             CASE WHEN to_regprocedure('update_graph_node_map_updated_at()') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'update_timestamps()',                            CASE WHEN to_regprocedure('update_timestamps()') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'backfill_task_nodes()',                          CASE WHEN to_regprocedure('backfill_task_nodes()') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'create_graph_embed_task(integer[],integer,text,text,text)', CASE WHEN to_regprocedure('create_graph_embed_task(integer[],integer,text,text,text)') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'create_graph_rag_task(integer[],integer,integer,text,text,text)', CASE WHEN to_regprocedure('create_graph_rag_task(integer[],integer,integer,text,text,text)') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
ORDER BY function;

-- Section 4: Triggers
SELECT 'trg_graph_node_map_updated_at on graph_node_map' AS trigger, CASE WHEN EXISTS (
  SELECT 1 FROM pg_trigger t WHERE t.tgname = 'trg_graph_node_map_updated_at' AND t.tgrelid = 'public.graph_node_map'::regclass
) THEN 'OK' ELSE 'MISSING' END AS status
UNION ALL SELECT 'trg_agent_registry_updated_at on agent_registry', CASE WHEN EXISTS (
  SELECT 1 FROM pg_trigger t WHERE t.tgname = 'trg_agent_registry_updated_at' AND t.tgrelid = 'public.agent_registry'::regclass
) THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'trg_organ_registry_updated_at on organ_registry', CASE WHEN EXISTS (
  SELECT 1 FROM pg_trigger t WHERE t.tgname = 'trg_organ_registry_updated_at' AND t.tgrelid = 'public.organ_registry'::regclass
) THEN 'OK' ELSE 'MISSING' END
ORDER BY trigger;

-- Section 5: Index presence (spot-check)
SELECT 'idx_task_dep_src' AS index, CASE WHEN to_regclass('public.idx_task_dep_src') IS NOT NULL THEN 'OK' ELSE 'MISSING' END AS status
UNION ALL SELECT 'idx_task_dep_dst', CASE WHEN to_regclass('public.idx_task_dep_dst') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'idx_task_prod_task', CASE WHEN to_regclass('public.idx_task_prod_task') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'idx_task_uses_task', CASE WHEN to_regclass('public.idx_task_uses_task') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'idx_task_reads_task', CASE WHEN to_regclass('public.idx_task_reads_task') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'idx_task_writes_task', CASE WHEN to_regclass('public.idx_task_writes_task') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'idx_task_exec_task', CASE WHEN to_regclass('public.idx_task_exec_task') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'idx_task_owned_task', CASE WHEN to_regclass('public.idx_task_owned_task') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'idx_organ_cap_organ', CASE WHEN to_regclass('public.idx_organ_cap_organ') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'idx_agent_mem_agent', CASE WHEN to_regclass('public.idx_agent_mem_agent') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
ORDER BY index;

-- Section 6: View shape smoke tests (no rows required)
SELECT * FROM graph_tasks LIMIT 0;
SELECT * FROM hgnn_edges LIMIT 0;
SELECT * FROM task_embeddings_128 LIMIT 0;
SELECT * FROM task_embeddings_1024 LIMIT 0;
