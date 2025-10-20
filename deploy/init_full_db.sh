#!/usr/bin/env bash
# Setup script for SeedCore Postgres database with tasks, holons, graphs (HGNN), and facts

set -euo pipefail

NAMESPACE="${NAMESPACE:-seedcore-dev}"
DB_NAME="${DB_NAME:-seedcore}"
DB_USER="${DB_USER:-postgres}"
DB_PASS="${DB_PASS:-postgres}"

# Resolve migration file paths relative to this script
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
MIGRATION_001="${SCRIPT_DIR}/migrations/001_create_tasks_table.sql"
MIGRATION_002="${SCRIPT_DIR}/migrations/002_graph_embeddings.sql"
MIGRATION_003="${SCRIPT_DIR}/migrations/003_graph_task_types.sql"
MIGRATION_004="${SCRIPT_DIR}/migrations/004_fix_taskstatus_enum.sql"
MIGRATION_005="${SCRIPT_DIR}/migrations/005_consolidate_task_schema.sql"
MIGRATION_006="${SCRIPT_DIR}/migrations/006_add_task_lease_columns.sql"
MIGRATION_007="${SCRIPT_DIR}/migrations/007_hgnn_graph_schema.sql"
# HGNN base graph schema (task layer)
MIGRATION_008="${SCRIPT_DIR}/migrations/008_hgnn_agent_layer.sql"
# NEW: HGNN agent/organ layer extensions
MIGRATION_009="${SCRIPT_DIR}/migrations/009_create_facts_table.sql"
MIGRATION_010="${SCRIPT_DIR}/migrations/010_task_fact_integration.sql"
MIGRATION_011="${SCRIPT_DIR}/migrations/011_add_runtime_registry.sql"
MIGRATION_012="${SCRIPT_DIR}/migrations/012_runtime_registry_functions.sql"
MIGRATION_013="${SCRIPT_DIR}/migrations/013_pkg_core.sql"
MIGRATION_014="${SCRIPT_DIR}/migrations/014_pkg_ops.sql"
MIGRATION_015="${SCRIPT_DIR}/migrations/015_pkg_views_functions.sql"
MIGRATION_016="${SCRIPT_DIR}/migrations/016_fact_pkg_integration.sql"
MIGRATION_017="${SCRIPT_DIR}/migrations/017_task_embedding_support.sql"
MIGRATION_018="${SCRIPT_DIR}/migrations/018_task_outbox_hardening.sql"

# Check if all migration files exist
for migration in \
  "$MIGRATION_001" "$MIGRATION_002" "$MIGRATION_003" "$MIGRATION_004" \
  "$MIGRATION_005" "$MIGRATION_006" "$MIGRATION_007" "$MIGRATION_008" \
  "$MIGRATION_009" "$MIGRATION_010" "$MIGRATION_011" "$MIGRATION_012" \
  "$MIGRATION_013" "$MIGRATION_014" "$MIGRATION_015" "$MIGRATION_016" \
  "$MIGRATION_017" "$MIGRATION_018"
do
  if [[ ! -f "$migration" ]]; then
    echo "❌ Migration file not found at: $migration"
    exit 1
  fi
done

echo "🔧 Namespace: $NAMESPACE"
echo "🔧 Database:  $DB_NAME (user: $DB_USER)"
echo "🔧 Migrations:"
echo "   - 001: $MIGRATION_001"
echo "   - 002: $MIGRATION_002"
echo "   - 003: $MIGRATION_003"
echo "   - 004: $MIGRATION_004"
echo "   - 005: $MIGRATION_005 (NEW: Consolidated task schema)"
echo "   - 006: $MIGRATION_006"
echo "   - 007: $MIGRATION_007 (HGNN base graph schema)"
echo "   - 008: $MIGRATION_008 (NEW: HGNN agent/organ layer + relations)"
echo "   - 009: $MIGRATION_009 (Create facts table)"
echo "   - 010: $MIGRATION_010 (NEW: Task-Fact integration + view update)"
echo "   - 011: $MIGRATION_011 (NEW: Runtime registry tables & views)"
echo "   - 012: $MIGRATION_012 (NEW: Runtime registry functions)"
echo "   - 013: $MIGRATION_013 (NEW: PKG core catalog - snapshots, rules, conditions, emissions, artifacts)"
echo "   - 014: $MIGRATION_014 (NEW: PKG operations - deployments, temporal facts, validation, promotions, device coverage)"
echo "   - 015: $MIGRATION_015 (NEW: PKG views and helper functions)"
echo "   - 016: $MIGRATION_016 (NEW: Fact model PKG integration - temporal facts, policy governance, eventizer support)"
echo "   - 017: $MIGRATION_017 (NEW: Task embedding support: views/functions/backfill)"
echo "   - 018: $MIGRATION_018 (NEW: Task outbox hardening: available_at, attempts, index)"

find_pg_pod() {
  local sel pod
  # Try common selectors (Bitnami, etc.), then fallback to name prefix
  for sel in \
    'app.kubernetes.io/name=postgresql,app.kubernetes.io/component=primary' \
    'app.kubernetes.io/name=postgresql' \
    'app=postgresql'
  do
    pod="$(kubectl -n "$NAMESPACE" get pods -l "$sel" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
    [[ -n "$pod" ]] && { echo "$pod"; return 0; }
  done
  pod="$(kubectl -n "$NAMESPACE" get pods --no-headers 2>/dev/null | awk '/^postgresql-|^postgres-/{print $1; exit}')"
  [[ -n "$pod" ]] && { echo "$pod"; return 0; }
  return 1
}

POSTGRES_POD="$(find_pg_pod || true)"
if [[ -z "${POSTGRES_POD:-}" ]]; then
  echo "❌ Could not locate a Postgres pod in namespace '$NAMESPACE'."
  echo "   Tip: kubectl -n $NAMESPACE get pods --show-labels | grep -i postgres"
  exit 1
fi
echo "🧩 Using Postgres pod: $POSTGRES_POD"

# 1) Create database (idempotent)
echo "🚀 Creating database '$DB_NAME' (if not exists)..."
if ! kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}';" | grep -q 1; then
  kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -c "CREATE DATABASE ${DB_NAME};"
fi

# 2) Ensure pgcrypto exists (needed for gen_random_uuid)
echo "🔌 Ensuring extension 'pgcrypto' is installed..."
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"

# 3) Ensure vector extension
echo "🔌 Ensuring extension 'vector' is installed..."
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 4) Holons table (kept from your baseline)
echo "🏗️  Creating holons table..."
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "
CREATE TABLE IF NOT EXISTS holons (
    id           SERIAL PRIMARY KEY,
    uuid         UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    embedding    VECTOR(768),
    meta         JSONB,
    created_at   TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS holons_embedding_idx ON holons USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS holons_uuid_idx ON holons (uuid);
CREATE INDEX IF NOT EXISTS holons_created_at_idx ON holons (created_at);
CREATE INDEX IF NOT EXISTS holons_meta_idx ON holons USING GIN (meta);
INSERT INTO holons (uuid, embedding, meta) VALUES
  (gen_random_uuid(), array_fill(0.1, ARRAY[768])::vector, '{\"type\": \"sample\", \"description\": \"Test holon 1\"}'),
  (gen_random_uuid(), array_fill(0.2, ARRAY[768])::vector, '{\"type\": \"sample\", \"description\": \"Test holon 2\"}'),
  (gen_random_uuid(), array_fill(0.3, ARRAY[768])::vector, '{\"type\": \"sample\", \"description\": \"Test holon 3\"}')
ON CONFLICT (uuid) DO NOTHING;
"

# 5) Copy and run migrations in sequence
echo "📂 Copying and running migrations..."

# Migration 001
echo "⚙️  Running migration 001: Create tasks table..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_001" "$POSTGRES_POD:/tmp/001_create_tasks_table.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/001_create_tasks_table.sql"

# Migration 002
echo "⚙️  Running migration 002: Create graph embeddings table..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_002" "$POSTGRES_POD:/tmp/002_graph_embeddings.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/002_graph_embeddings.sql"

# Migration 003
echo "⚙️  Running migration 003: Add graph task types and helper functions..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_003" "$POSTGRES_POD:/tmp/003_graph_task_types.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/003_graph_task_types.sql"

# Migration 004
echo "⚙️  Running migration 004: Fix taskstatus enum to match code expectations..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_004" "$POSTGRES_POD:/tmp/004_fix_taskstatus_enum.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/004_fix_taskstatus_enum.sql"

# Migration 005
echo "⚙️  Running migration 005: Consolidate and fix task schema (CRITICAL FIX)..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_005" "$POSTGRES_POD:/tmp/005_consolidate_task_schema.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/005_consolidate_task_schema.sql"

# Migration 006
echo "⚙️  Running migration 006: Add task lease columns for stale task recovery..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_006" "$POSTGRES_POD:/tmp/006_add_task_lease_columns.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/006_add_task_lease_columns.sql"

# Migration 007
echo "⚙️  Running migration 007: HGNN base graph schema..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_007" "$POSTGRES_POD:/tmp/007_hgnn_graph_schema.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/007_hgnn_graph_schema.sql"

# Migration 008
echo "⚙️  Running migration 008: HGNN agent/organ layer + relations..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_008" "$POSTGRES_POD:/tmp/008_hgnn_agent_layer.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/008_hgnn_agent_layer.sql"

# Migration 009 (NEW)
echo "⚙️  Running migration 009: Create facts table..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_009" "$POSTGRES_POD:/tmp/009_create_facts_table.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/009_create_facts_table.sql"

# Migration 010 (NEW)
echo "⚙️  Running migration 010: Task-Fact integration + view update..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_010" "$POSTGRES_POD:/tmp/010_task_fact_integration.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/010_task_fact_integration.sql"

# Migration 011 (NEW)
echo "⚙️  Running migration 011: Runtime registry tables & views..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_011" "$POSTGRES_POD:/tmp/011_add_runtime_registry.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/011_add_runtime_registry.sql"

# Migration 012 (NEW)
echo "⚙️  Running migration 012: Runtime registry functions..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_012" "$POSTGRES_POD:/tmp/012_runtime_registry_functions.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/012_runtime_registry_functions.sql"

# Migration 013 (NEW - PKG Core)
echo "⚙️  Running migration 013: PKG core catalog (snapshots, rules, conditions, emissions, artifacts)..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_013" "$POSTGRES_POD:/tmp/013_pkg_core.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/013_pkg_core.sql"

# Migration 014 (NEW - PKG Operations)
echo "⚙️  Running migration 014: PKG operations (deployments, temporal facts, validation, promotions, device coverage)..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_014" "$POSTGRES_POD:/tmp/014_pkg_ops.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/014_pkg_ops.sql"

# Migration 015 (NEW - PKG Views and Functions)
echo "⚙️  Running migration 015: PKG views and helper functions..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_015" "$POSTGRES_POD:/tmp/015_pkg_views_functions.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/015_pkg_views_functions.sql"

# Migration 016 (NEW - Fact PKG Integration)
echo "⚙️  Running migration 016: Fact model PKG integration (temporal facts, policy governance, eventizer support)..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_016" "$POSTGRES_POD:/tmp/016_fact_pkg_integration.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/016_fact_pkg_integration.sql"

# Migration 017 (NEW - Task Embedding Support)
echo "⚙️  Running migration 017: Task embedding support (views/functions/backfill)..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_017" "$POSTGRES_POD:/tmp/017_task_embedding_support.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/017_task_embedding_support.sql"

# Migration 018 (NEW - Task Outbox Hardening)
echo "⚙️  Running migration 018: Task outbox hardening (available_at, attempts, index)..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_018" "$POSTGRES_POD:/tmp/018_task_outbox_hardening.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/018_task_outbox_hardening.sql"

# 6) Verify schema
echo "✅ Verifying schema..."

echo "📊 Tables:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\dt"

echo "📊 Views:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\dv"

echo "📊 Tasks table structure:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ tasks"

echo "📊 Graph embeddings table structure:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ graph_embeddings"

echo "📊 Holons table structure:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ holons"

echo "📊 Graph tasks view:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ graph_tasks"

echo "📊 Facts table structure (enhanced with PKG integration):"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ facts"

# NEW: HGNN verification (key tables + views + helper functions)
echo "📊 HGNN core mapping + registries:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ graph_node_map"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ agent_registry"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ organ_registry"

echo "📊 HGNN task-layer resource tables:"
for tbl in artifact capability memory_cell \
           task_depends_on_task task_produces_artifact task_uses_capability \
           task_reads_memory task_writes_memory task_executed_by_organ task_owned_by_agent \
           organ_provides_capability agent_owns_memory_cell task_reads_fact task_produces_fact
do
  kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ $tbl" || true
done

echo "📊 HGNN views:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ hgnn_edges"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ task_embeddings"

echo "📊 Key HGNN functions:"
for fn in ensure_task_node ensure_agent_node ensure_organ_node ensure_fact_node backfill_task_nodes \
          create_graph_embed_task_v2 create_graph_rag_task_v2
do
  kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\df+ $fn" || true
done

echo "📊 Runtime registry tables:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ cluster_metadata"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ registry_instance"

echo "📊 Runtime registry views:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ active_instances"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ active_instance"

echo "📊 Runtime registry functions:"
for fn in set_current_epoch register_instance set_instance_status beat expire_stale_instances expire_old_epoch_instances
do
  kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\df+ $fn" || true
done

echo "📊 PKG core tables:"
for tbl in pkg_snapshots pkg_subtask_types pkg_policy_rules pkg_rule_conditions pkg_rule_emissions pkg_snapshot_artifacts
do
  kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ $tbl" || true
done

echo "📊 PKG operations tables:"
for tbl in pkg_deployments pkg_facts pkg_validation_fixtures pkg_validation_runs pkg_promotions pkg_device_versions
do
  kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ $tbl" || true
done

echo "📊 PKG views:"
for view in pkg_active_artifact pkg_rules_expanded pkg_deployment_coverage
do
  kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ $view" || true
done

echo "📊 PKG functions:"
for fn in pkg_check_integrity pkg_active_snapshot_id pkg_promote_snapshot
do
  kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\df+ $fn" || true
done

echo "📊 PKG enum types:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT typname FROM pg_type WHERE typname LIKE 'pkg_%' ORDER BY typname;"

echo "📊 Enhanced facts table views and functions:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ active_temporal_facts"

echo "📊 Facts helper functions:"
for fn in get_facts_by_subject cleanup_expired_facts get_fact_statistics
do
  kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\df+ $fn" || true
done

echo "📊 PKG sanity checks:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "
    -- 1) Exactly one active snapshot per env
    SELECT 'Active snapshots per env:' as check_name, env, COUNT(*) as count 
    FROM pkg_snapshots WHERE is_active = TRUE GROUP BY env;
    
    -- 2) PKG integrity check
    SELECT 'PKG integrity:' as check_name, * FROM pkg_check_integrity();
    
    -- 3) Check all PKG enum types were created
    SELECT 'PKG enum types:' as check_name, COUNT(*) as count 
    FROM pg_type WHERE typname LIKE 'pkg_%';
    
    -- 4) Check all PKG tables were created
    SELECT 'PKG tables:' as check_name, COUNT(*) as count 
    FROM information_schema.tables WHERE table_name LIKE 'pkg_%';
    
    -- 5) Check all PKG views were created
    SELECT 'PKG views:' as check_name, COUNT(*) as count 
    FROM information_schema.views WHERE table_name LIKE 'pkg_%';
    
    -- 6) Check all PKG functions were created
    SELECT 'PKG functions:' as check_name, COUNT(*) as count 
    FROM information_schema.routines WHERE routine_name LIKE 'pkg_%';
"

echo "📊 Taskstatus enum values:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT unnest(enum_range(NULL::taskstatus)) as enum_value;"

echo "🎉 SeedCore database setup complete!"
echo "✅ Created tables: tasks, holons, graph_embeddings, facts"
echo "✅ Created graph schema (HGNN): graph_node_map, agent_registry, organ_registry,"
echo "   artifact, capability, memory_cell, edge tables (task_*), organ_provides_capability, agent_owns_memory_cell"
echo "✅ Created views: graph_tasks, task_embeddings, hgnn_edges"
echo "✅ Helper functions: create_graph_embed_task, create_graph_rag_task, *_v2 variants with agent/organ,"
echo "   ensure_*_node, backfill_task_nodes"
echo "✅ Fixed taskstatus enum to use consistent lowercase values"
echo "✅ Consolidated task schema + added task lease columns"
echo "✅ Created PKG schema: pkg_snapshots, pkg_policy_rules, pkg_rule_conditions, pkg_rule_emissions,"
echo "   pkg_snapshot_artifacts, pkg_deployments, pkg_facts, pkg_validation_*, pkg_promotions, pkg_device_versions"
echo "✅ Created PKG views: pkg_active_artifact, pkg_rules_expanded, pkg_deployment_coverage"
echo "✅ Created PKG functions: pkg_check_integrity, pkg_active_snapshot_id, pkg_promote_snapshot"
echo "✅ Created PKG enums: pkg_env, pkg_engine, pkg_condition_type, pkg_operator, pkg_relation, pkg_artifact_type"
echo "✅ Enhanced facts table with PKG integration: temporal facts, policy governance, eventizer support"
echo "✅ Created fact helper functions: get_facts_by_subject, cleanup_expired_facts, get_fact_statistics"
echo "✅ Created active_temporal_facts view for efficient temporal fact queries"
echo "✅ Enabled extensions: pgcrypto, vector"
echo "👉 DSN: postgresql://${DB_USER}:${DB_PASS}@postgresql:5432/${DB_NAME}"
echo ""
echo "📋 Quick start examples:"
echo "   -- Create a graph embedding task (legacy):"
echo "   SELECT create_graph_embed_task(ARRAY[123], 2, 'Embed neighborhood around node 123');"
echo ""
echo "   -- Create a graph embedding task and wire ownership/executor (HGNN v2):"
echo "   SELECT create_graph_embed_task_v2(ARRAY[123], 2, 'Embed with ownership', 'agent_main', 'utility_organ_1');"
echo ""
echo "   -- Ensure tasks are mapped to numeric node ids:"
echo "   SELECT backfill_task_nodes();"
echo ""
echo "   -- Explore edges for DGL ingest:"
echo "   SELECT * FROM hgnn_edges LIMIT 20;"
echo ""
echo '   -- Pull task embeddings joined to numeric node ids:'
echo "   SELECT task_id, node_id, emb[1:8] AS emb_head FROM task_embeddings LIMIT 5;"
echo ""
echo "   -- Monitor graph tasks:"
echo "   SELECT * FROM graph_tasks ORDER BY updated_at DESC LIMIT 10;"
echo ""
echo "   -- Test facts table:"
echo "   SELECT * FROM facts LIMIT 5;"
echo ""
echo "📋 PKG Quick start examples:"
echo "   -- Check PKG integrity:"
echo "   SELECT * FROM pkg_check_integrity();"
echo ""
echo "   -- View active PKG snapshot:"
echo "   SELECT * FROM pkg_active_artifact;"
echo ""
echo "   -- View PKG rules with emissions:"
echo "   SELECT * FROM pkg_rules_expanded LIMIT 10;"
echo ""
echo "   -- Check deployment coverage:"
echo "   SELECT * FROM pkg_deployment_coverage;"
echo ""
echo "   -- View PKG enum types:"
echo "   SELECT typname FROM pg_type WHERE typname LIKE 'pkg_%' ORDER BY typname;"
echo ""
echo "📋 Enhanced Facts Quick start examples:"
echo "   -- Get facts by subject:"
echo "   SELECT * FROM get_facts_by_subject('guest:john_doe', 'hotel_ops');"
echo ""
echo "   -- View active temporal facts:"
echo "   SELECT * FROM active_temporal_facts LIMIT 10;"
echo ""
echo "   -- Get fact statistics:"
echo "   SELECT * FROM get_fact_statistics('hotel_ops');"
echo ""
echo "   -- Cleanup expired facts (dry run):"
echo "   SELECT cleanup_expired_facts('hotel_ops', true);"
