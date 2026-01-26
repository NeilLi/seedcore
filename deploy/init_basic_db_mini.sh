#!/usr/bin/env bash
# SeedCore Database Initialization (Kubernetes) - Mini Version
# Portable: can be run from ANY directory
# Only initializes PostgreSQL (no MySQL or Neo4j)

set -Eeuo pipefail

############################
# Config & CLI
############################
NAMESPACE="${1:-seedcore-dev}"

# Allow overriding credentials via environment variables
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-seedcore}"

# Label selectors (tweak if your charts use different labels)
PG_SELECTOR="${PG_SELECTOR:-app.kubernetes.io/name=postgresql}"

TIMEOUT="${TIMEOUT:-180s}"

############################
# Helpers
############################
log()   { printf "%s\n" "[$(date +'%H:%M:%S')] $*"; }
die()   { printf "❌ %s\n" "$*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: $(basename "$0") [NAMESPACE]

Environment overrides:
  POSTGRES_USER, POSTGRES_DB
  PG_SELECTOR
  TIMEOUT (kubectl wait timeout, e.g. 180s)

Examples:
  $(basename "$0")                    # uses namespace 'seedcore-dev'
  $(basename "$0") seedcore-staging   # different namespace
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage; exit 0
fi

command -v kubectl >/dev/null 2>&1 || die "kubectl is not installed or not in PATH."
kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 || die "Namespace '$NAMESPACE' does not exist."

############################
# Locate repo root so paths work from anywhere
############################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO_ROOT" ] || [ ! -d "$REPO_ROOT/docker/setup" ]; then
  # Walk upward until we find docker/setup with our init files
  try="$SCRIPT_DIR"
  while [ "$try" != "/" ]; do
    if [ -e "$try/docker/setup/init_pgvector.sql" ]; then
      REPO_ROOT="$try"; break
    fi
    try="$(dirname "$try")"
  done
fi
[ -z "$REPO_ROOT" ] && { echo "❌ Could not locate repo root containing docker/setup"; exit 1; }

PG_SQL="$REPO_ROOT/docker/setup/init_pgvector.sql"
echo "📂 Repo root: $REPO_ROOT"
echo "📁 Setup dir: $REPO_ROOT/docker/setup"

[[ -r "$PG_SQL" ]] || die "Missing: $PG_SQL"

log "🔧 Initializing SeedCore PostgreSQL database in Kubernetes..."
log "📋 Namespace: $NAMESPACE"
log "📂 Repo root: $REPO_ROOT"
log "📁 Setup dir: $REPO_ROOT/docker/setup"

############################
# K8s helpers
############################
wait_for_pods_ready() {
  local selector="$1"
  log "⏳ Waiting for pods with selector '$selector' to be Ready (timeout $TIMEOUT)..."
  kubectl wait --for=condition=ready pod -l "$selector" -n "$NAMESPACE" --timeout="$TIMEOUT" \
    || die "Timeout waiting for selector '$selector'."
}

first_pod_name() {
  local selector="$1"
  kubectl get pods -n "$NAMESPACE" -l "$selector" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true
}

############################
# Initializers
############################
init_postgresql() {
  log "🐘 Initializing PostgreSQL..."
  wait_for_pods_ready "$PG_SELECTOR"
  local pod; pod="$(first_pod_name "$PG_SELECTOR")"
  [[ -n "$pod" ]] || die "PostgreSQL pod not found."

  # Create the database if it doesn't exist
  log "🔧 Creating database: $POSTGRES_DB"
  kubectl exec -n "$NAMESPACE" "$pod" -- psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $POSTGRES_DB;" 2>/dev/null || log "Database $POSTGRES_DB may already exist"

  log "📝 Copying SQL to pod: $pod"
  kubectl cp "$PG_SQL" "$NAMESPACE/$pod:/tmp/init_pgvector.sql" || die "Failed to copy SQL file"

  log "🚀 Running SQL in database: $POSTGRES_DB"
  if ! kubectl exec -n "$NAMESPACE" "$pod" -- psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /tmp/init_pgvector.sql; then
    log "❌ PostgreSQL initialization failed. Checking database connection..."
    kubectl exec -n "$NAMESPACE" "$pod" -- psql -U "$POSTGRES_USER" -l || true
    die "PostgreSQL initialization failed"
  fi

  log "✅ PostgreSQL initialized successfully."
}

############################
# Verification
############################
verify_databases() {
  log "🔍 Verifying database initialization..."

  # PostgreSQL
  log "🐘 Checking PostgreSQL..."
  local pg_pod; pg_pod="$(first_pod_name "$PG_SELECTOR")"
  if [[ -n "$pg_pod" ]]; then
    local result
    result=$(kubectl exec -n "$NAMESPACE" "$pg_pod" -- psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM holons;" 2>&1)
    if [[ $? -eq 0 ]] && [[ -n "$result" ]]; then
      local count=$(echo "$result" | tr -d ' ')
      log "✅ PostgreSQL: holons table exists (count: $count)"
    else
      log "❌ PostgreSQL: holons table missing or query failed"
      log "Debug: Checking if database exists..."
      kubectl exec -n "$NAMESPACE" "$pg_pod" -- psql -U "$POSTGRES_USER" -l 2>&1 || true
      log "Debug: Checking if holons table exists..."
      kubectl exec -n "$NAMESPACE" "$pg_pod" -- psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt" 2>&1 || true
    fi
  fi
}

############################
# Main
############################
main() {
  log "🚀 Starting SeedCore PostgreSQL database initialization..."
  init_postgresql
  verify_databases
  log "🎉 PostgreSQL database initialization completed!"
}

main
