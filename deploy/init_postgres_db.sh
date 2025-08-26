#!/usr/bin/env bash
# Setup script for SeedCore Postgres database with both tasks and holons tables

set -euo pipefail

NAMESPACE="${NAMESPACE:-seedcore-dev}"
DB_NAME="${DB_NAME:-seedcore}"
DB_USER="${DB_USER:-postgres}"
DB_PASS="${DB_PASS:-postgres}"

# Resolve migration file path relative to this script
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
MIGRATION_FILE="${SCRIPT_DIR}/migrations/001_create_tasks_table.sql"

if [[ ! -f "$MIGRATION_FILE" ]]; then
  echo "❌ Migration file not found at: $MIGRATION_FILE"
  exit 1
fi

echo "🔧 Namespace: $NAMESPACE"
echo "🔧 Database:  $DB_NAME (user: $DB_USER)"
echo "🔧 Migration: $MIGRATION_FILE"

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

# 3) Enable vector extension (required for holons table)
echo "🔌 Ensuring extension 'vector' is installed..."
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 4) Create holons table (required for telemetry system)
echo "🏗️  Creating holons table..."
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "
-- Create the holons table
CREATE TABLE IF NOT EXISTS holons (
    id           SERIAL PRIMARY KEY,
    uuid         UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    embedding    VECTOR(768),
    meta         JSONB,
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- Create HNSW index for vector similarity search
CREATE INDEX IF NOT EXISTS holons_embedding_idx ON holons USING hnsw (embedding vector_cosine_ops);

-- Create additional indexes for performance
CREATE INDEX IF NOT EXISTS holons_uuid_idx ON holons (uuid);
CREATE INDEX IF NOT EXISTS holons_created_at_idx ON holons (created_at);
CREATE INDEX IF NOT EXISTS holons_meta_idx ON holons USING GIN (meta);

-- Insert some sample data for testing (768-dimensional vectors)
INSERT INTO holons (uuid, embedding, meta) VALUES
    (gen_random_uuid(), array_fill(0.1, ARRAY[768])::vector, '{\"type\": \"sample\", \"description\": \"Test holon 1\"}'),
    (gen_random_uuid(), array_fill(0.2, ARRAY[768])::vector, '{\"type\": \"sample\", \"description\": \"Test holon 2\"}'),
    (gen_random_uuid(), array_fill(0.3, ARRAY[768])::vector, '{\"type\": \"sample\", \"description\": \"Test holon 3\"}')
ON CONFLICT (uuid) DO NOTHING;
"

# 5) Copy migration for tasks table
DEST="/tmp/001_create_tasks_table.sql"
echo "📂 Copying migration to pod: $DEST"
kubectl -n "$NAMESPACE" cp "$MIGRATION_FILE" "$POSTGRES_POD":"$DEST"

# 6) Run migration for tasks table
echo "⚙️  Running migration for tasks table..."
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -f "$DEST"

# 7) Verify schema
echo "✅ Verifying schema..."
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "\dt"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ tasks"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ holons"

echo "🎉 SeedCore database setup complete!"
echo "✅ Created tables: tasks, holons"
echo "✅ Enabled extensions: pgcrypto, vector"
echo "👉 Use DSN: postgresql://${DB_USER}:${DB_PASS}@postgresql:5432/${DB_NAME}"
