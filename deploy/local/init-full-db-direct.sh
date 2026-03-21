#!/usr/bin/env bash
# Initialize the full SeedCore Postgres schema against a directly reachable
# local/host Postgres instance without going through Kubernetes.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
MIGRATIONS_DIR="${DEPLOY_DIR}/migrations"

DB_HOST="${DB_HOST:-${PGHOST:-127.0.0.1}}"
DB_PORT="${DB_PORT:-${PGPORT:-5432}}"
DB_USER="${DB_USER:-${PGUSER:-postgres}}"
DB_PASS="${DB_PASS:-${PGPASSWORD:-password}}"
DB_NAME="${DB_NAME:-seedcore}"
BOOTSTRAP_DB="${BOOTSTRAP_DB:-postgres}"

MIGRATIONS=(
  001_create_tasks_table.sql
  002_dual_dimension_embeddings.sql
  003_task_multimodal_embeddings.sql
  004_create_holons_table.sql
  007_hgnn_core_topology.sql
  008_hgnn_agent_layer.sql
  009_runtime_instance_registry.sql
  010_runtime_control_logic.sql
  011_create_facts_table.sql
  012_task_fact_integration.sql
  013_pkg_core.sql
  014_pkg_ops.sql
  015_pkg_views_functions.sql
  016_fact_pkg_integration.sql
  017_pkg_tasks_snapshot_scoping.sql
  117_unified_cortex.sql
  118_task_outbox_hardening.sql
  119_task_router_telemetry.sql
  120_organ_specialization_indexing.sql
  121_task_proto_plan.sql
  122_source_registration.sql
  123_tracking_events.sql
  124_tracking_events_app_scope.sql
  124_governed_execution_audit.sql
  125_governed_execution_policy_receipt.sql
  126_digital_twin_persistence.sql
  127_digital_twin_event_journal.sql
  128_custody_graph.sql
)

for migration in "${MIGRATIONS[@]}"; do
  if [[ ! -f "${MIGRATIONS_DIR}/${migration}" ]]; then
    echo "❌ Missing migration: ${MIGRATIONS_DIR}/${migration}" >&2
    exit 1
  fi
done

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "❌ Required command not found: $1" >&2
    exit 1
  }
}

psql_base() {
  PGPASSWORD="${DB_PASS}" psql \
    -h "${DB_HOST}" \
    -p "${DB_PORT}" \
    -U "${DB_USER}" \
    "$@"
}

echo "🔧 SeedCore direct DB init"
echo "   host: ${DB_HOST}"
echo "   port: ${DB_PORT}"
echo "   user: ${DB_USER}"
echo "   db:   ${DB_NAME}"

require_cmd psql

echo "🔍 Checking bootstrap connectivity..."
psql_base -d "${BOOTSTRAP_DB}" -c "SELECT 1;" >/dev/null

echo "🗄️  Creating database '${DB_NAME}' if needed..."
if ! psql_base -d "${BOOTSTRAP_DB}" -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
  psql_base -d "${BOOTSTRAP_DB}" -c "CREATE DATABASE ${DB_NAME};"
fi

echo "🔌 Ensuring required extensions..."
psql_base -d "${DB_NAME}" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
psql_base -d "${DB_NAME}" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector;"

for migration in "${MIGRATIONS[@]}"; do
  echo "⚙️  Running ${migration}..."
  psql_base -d "${DB_NAME}" -v ON_ERROR_STOP=1 -f "${MIGRATIONS_DIR}/${migration}"
done

echo "✅ Verifying required functions..."
psql_base -d "${DB_NAME}" -v ON_ERROR_STOP=1 -c \
  "SELECT to_regprocedure('ensure_task_node(uuid)') AS ensure_task_node;"
psql_base -d "${DB_NAME}" -v ON_ERROR_STOP=1 -c \
  "SELECT to_regprocedure('pkg_active_snapshot_id(pkg_env)') AS pkg_active_snapshot_id;"

echo "🎉 SeedCore schema is ready on ${DB_NAME}"
