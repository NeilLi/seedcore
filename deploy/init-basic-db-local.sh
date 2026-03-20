#!/usr/bin/env bash
# SeedCore PostgreSQL Preflight (Kubernetes) - Local / low-memory variant
# Portable: can be run from any directory.
# Full Postgres schema is owned by init-full-db.sh.

set -Eeuo pipefail

############################
# Config & CLI
############################
NAMESPACE="${1:-${NAMESPACE:-seedcore-dev}}"

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

log "🔧 Preflighting SeedCore PostgreSQL in Kubernetes..."
log "📋 Namespace: $NAMESPACE"
log "📦 Bootstrap mode: readiness check only; full schema lives in init-full-db.sh"

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
ensure_postgresql_ready() {
  log "🐘 Checking PostgreSQL readiness..."
  wait_for_pods_ready "$PG_SELECTOR"
  local pod; pod="$(first_pod_name "$PG_SELECTOR")"
  [[ -n "$pod" ]] || die "PostgreSQL pod not found."

  if ! kubectl exec -n "$NAMESPACE" "$pod" -- psql -U "$POSTGRES_USER" -d postgres -c "SELECT 1;" >/dev/null; then
    log "❌ PostgreSQL readiness check failed. Checking database connection..."
    kubectl exec -n "$NAMESPACE" "$pod" -- psql -U "$POSTGRES_USER" -l 2>&1 || true
    die "PostgreSQL is reachable but not ready for migrations"
  fi

  log "✅ PostgreSQL is ready. Full schema will be applied by init-full-db.sh."
}

############################
# Verification
############################
verify_databases() {
  log "🔍 Verifying PostgreSQL readiness..."

  log "🐘 Checking PostgreSQL..."
  local pg_pod; pg_pod="$(first_pod_name "$PG_SELECTOR")"
  if [[ -n "$pg_pod" ]]; then
    if kubectl exec -n "$NAMESPACE" "$pg_pod" -- psql -U "$POSTGRES_USER" -d postgres -c "SELECT 1;" >/dev/null 2>&1; then
      log "✅ PostgreSQL: ready for full migration step"
    else
      log "❌ PostgreSQL: readiness query failed"
      kubectl exec -n "$NAMESPACE" "$pg_pod" -- psql -U "$POSTGRES_USER" -l 2>&1 || true
    fi
  fi
}

############################
# Main
############################
main() {
  log "🚀 Starting SeedCore PostgreSQL preflight..."
  ensure_postgresql_ready
  verify_databases
  log "🎉 PostgreSQL preflight completed!"
}

main
