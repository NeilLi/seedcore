#!/usr/bin/env bash
# SeedCore Database Initialization (Kubernetes)
# Portable: can be run from ANY directory

set -Eeuo pipefail

############################
# Config & CLI
############################
NAMESPACE="${1:-seedcore-dev}"

# Allow overriding credentials via environment variables
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-seedcore}"

MYSQL_ROOT_USER="${MYSQL_ROOT_USER:-root}"
MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-password}"

NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-password}"
NEO4J_DB="${NEO4J_DB:-neo4j}"

# Label selectors (tweak if your charts use different labels)
PG_SELECTOR="${PG_SELECTOR:-app.kubernetes.io/name=postgresql}"
MYSQL_SELECTOR="${MYSQL_SELECTOR:-app.kubernetes.io/name=mysql}"
NEO4J_SELECTOR="${NEO4J_SELECTOR:-app=neo4j}"

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
  MYSQL_ROOT_USER, MYSQL_ROOT_PASSWORD
  NEO4J_USER, NEO4J_PASSWORD, NEO4J_DB
  PG_SELECTOR, MYSQL_SELECTOR, NEO4J_SELECTOR
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
    if [ -e "$try/docker/setup/init_pgvector.sql" ] && \
       [ -e "$try/docker/setup/init_mysql.sql" ] && \
       [ -e "$try/docker/setup/init_neo4j.cypher" ]; then
      REPO_ROOT="$try"; break
    fi
    try="$(dirname "$try")"
  done
fi
[ -z "$REPO_ROOT" ] && { echo "❌ Could not locate repo root containing docker/setup"; exit 1; }

PG_SQL="$REPO_ROOT/docker/setup/init_pgvector.sql"
MYSQL_SQL="$REPO_ROOT/docker/setup/init_mysql.sql"
NEO4J_CQL="$REPO_ROOT/docker/setup/init_neo4j.cypher"
echo "📂 Repo root: $REPO_ROOT"
echo "📁 Setup dir: $REPO_ROOT/docker/setup"

[[ -r "$PG_SQL"    ]] || die "Missing: $PG_SQL"
[[ -r "$MYSQL_SQL" ]] || die "Missing: $MYSQL_SQL"
[[ -r "$NEO4J_CQL" ]] || die "Missing: $NEO4J_CQL"

log "🔧 Initializing SeedCore databases in Kubernetes..."
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

init_mysql() {
  log "🐬 Initializing MySQL..."
  wait_for_pods_ready "$MYSQL_SELECTOR"
  local pod; pod="$(first_pod_name "$MYSQL_SELECTOR")"
  [[ -n "$pod" ]] || die "MySQL pod not found."

  log "📝 Copying SQL to pod: $pod"
  kubectl cp "$MYSQL_SQL" "$NAMESPACE/$pod:/tmp/init_mysql.sql"

  log "🚀 Running SQL (drop & recreate for idempotency)..."
  kubectl exec -n "$NAMESPACE" "$pod" -- sh -c \
    "mysql -u '$MYSQL_ROOT_USER' -p'$MYSQL_ROOT_PASSWORD' -e \"DROP DATABASE IF EXISTS seedcore; CREATE DATABASE seedcore;\""
  kubectl exec -n "$NAMESPACE" "$pod" -- sh -c \
    "mysql -u '$MYSQL_ROOT_USER' -p'$MYSQL_ROOT_PASSWORD' seedcore < /tmp/init_mysql.sql"

  log "✅ MySQL initialized successfully."
}

# internal: figure out the right container and cypher-shell path
neo4j_detect() {
  local pod="$1"

  # pick container (prefer a container literally named 'neo4j' if present)
  local containers; containers="$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.spec.containers[*].name}')"
  NEO4J_CONTAINER=""
  for c in $containers; do
    if [[ "$c" == "neo4j" ]]; then NEO4J_CONTAINER="$c"; break; fi
  done
  [[ -z "$NEO4J_CONTAINER" ]] && NEO4J_CONTAINER="$(echo "$containers" | awk '{print $1}')"  # fallback to first

  # Use standard Neo4j 5 path for cypher-shell
  NEO4J_CYPHER_SHELL="/var/lib/neo4j/bin/cypher-shell"
}

init_neo4j() {
  log "🟢 Initializing Neo4j..."
  wait_for_pods_ready "$NEO4J_SELECTOR"
  local pod; pod="$(first_pod_name "$NEO4J_SELECTOR")"
  [[ -n "$pod" ]] || die "Neo4j pod not found."

  # detect container + cypher-shell path
  neo4j_detect "$pod"
  log "📦 Using container: $NEO4J_CONTAINER"
  log "🛠  Using cypher-shell: $NEO4J_CYPHER_SHELL"

  log "📝 Copying CQL to pod: $pod"
  kubectl cp "$NEO4J_CQL" "$NAMESPACE/$pod:/tmp/init_neo4j.cypher" -c "$NEO4J_CONTAINER"

  log "🚀 Running CQL..."
  # Explicitly target bolt on localhost and run non-interactively
  kubectl exec -n "$NAMESPACE" -c "$NEO4J_CONTAINER" "$pod" -- \
    "$NEO4J_CYPHER_SHELL" -a bolt://localhost:7687 -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" -d "$NEO4J_DB" -f /tmp/init_neo4j.cypher --non-interactive

  log "✅ Neo4j initialized successfully."
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

  # MySQL
  log "🐬 Checking MySQL..."
  local my_pod; my_pod="$(first_pod_name "$MYSQL_SELECTOR")"
  if [[ -n "$my_pod" ]]; then
    if kubectl exec -n "$NAMESPACE" "$my_pod" -- sh -c "mysql -u '$MYSQL_ROOT_USER' -p'$MYSQL_ROOT_PASSWORD' seedcore -e \"SHOW TABLES;\"" >/dev/null 2>&1; then
      log "✅ MySQL: tables exist"
    else
      log "❌ MySQL: tables missing or query failed"
    fi
  fi

  # Neo4j
  log "🟢 Checking Neo4j..."
  local neo_pod; neo_pod="$(first_pod_name "$NEO4J_SELECTOR")"
  if [ -n "$neo_pod" ]; then 
    # This is the new, correct command
    COUNT=$(kubectl exec -n $NAMESPACE $neo_pod -- bash -c 'echo "MATCH (h:Holon) RETURN COUNT(h) AS count;" | /var/lib/neo4j/bin/cypher-shell -u neo4j -p password -d neo4j --format plain | tail -n 1')
    if [ "$COUNT" -gt 0 ]; then
      log "✅ Neo4j: Holon nodes exist (Count: $COUNT)"
    else
      log "❌ Neo4j: Holon nodes missing"
    fi
  fi
}

############################
# Main
############################
main() {
  log "🚀 Starting SeedCore database initialization..."
  init_postgresql
  init_mysql
  init_neo4j
  verify_databases
  log "🎉 Database initialization completed!"
  printf "\nNext steps:\n"
  printf "1) Restart your seedcore-api pod to pick up the new schema\n"
  printf "2) Check logs for database errors\n"
  printf "3) Verify the application end-to-end\n"
}

main
