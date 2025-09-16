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

# Check if all migration files exist
for migration in \
  "$MIGRATION_001" "$MIGRATION_002" "$MIGRATION_003" "$MIGRATION_004" \
  "$MIGRATION_005" "$MIGRATION_006" "$MIGRATION_007" "$MIGRATION_008" \
  "$MIGRATION_009" "$MIGRATION_010"
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

echo "📊 Facts table structure:"
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
