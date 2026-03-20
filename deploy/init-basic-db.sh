#!/usr/bin/env bash
# SeedCore Auxiliary Database Initialization (Kubernetes)
# Portable: can be run from any directory.
# Postgres schema is owned by init-full-db.sh; this script only preflights
# Postgres readiness and bootstraps auxiliary stores.

set -Eeuo pipefail

############################
# Config & CLI
############################
NAMESPACE="${1:-${NAMESPACE:-seedcore-dev}}"

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

log "🔧 Initializing SeedCore auxiliary databases in Kubernetes..."
log "📋 Namespace: $NAMESPACE"
log "📦 Bootstrap mode: preflight Postgres + inline MySQL/Neo4j bootstrap"

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

init_mysql() {
  log "🐬 Initializing MySQL..."
  wait_for_pods_ready "$MYSQL_SELECTOR"
  local pod; pod="$(first_pod_name "$MYSQL_SELECTOR")"
  [[ -n "$pod" ]] || die "MySQL pod not found."

  log "🚀 Running inline MySQL bootstrap..."
  kubectl exec -i -n "$NAMESPACE" "$pod" -- sh -c \
    "mysql -u '$MYSQL_ROOT_USER' -p'$MYSQL_ROOT_PASSWORD'" <<'SQL'
CREATE DATABASE IF NOT EXISTS seedcore CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE seedcore;

CREATE TABLE IF NOT EXISTS flashbulb_incidents (
    incident_id CHAR(36) PRIMARY KEY,
    salience_score FLOAT NOT NULL,
    event_data JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

SET @idx_exists := (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'flashbulb_incidents'
      AND index_name = 'idx_flashbulb_created_at'
);
SET @idx_sql := IF(
    @idx_exists = 0,
    'CREATE INDEX idx_flashbulb_created_at ON flashbulb_incidents(created_at)',
    'SELECT ''idx_flashbulb_created_at already exists'''
);
PREPARE stmt FROM @idx_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
SQL

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

  log "🚀 Running inline Neo4j bootstrap..."
  kubectl exec -i -n "$NAMESPACE" -c "$NEO4J_CONTAINER" "$pod" -- \
    "$NEO4J_CYPHER_SHELL" -a bolt://localhost:7687 -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" -d "$NEO4J_DB" --non-interactive <<'CYPHER'
CREATE CONSTRAINT holon_uuid IF NOT EXISTS
FOR (h:Holon) REQUIRE h.uuid IS UNIQUE;

CREATE INDEX holon_created_at IF NOT EXISTS FOR (h:Holon) ON (h.created_at);
CREATE INDEX holon_type IF NOT EXISTS FOR (h:Holon) ON (h.type);

MERGE (h1:Holon {description: 'Bootstrap holon 1'})
  ON CREATE SET
    h1.uuid = randomUUID(),
    h1.type = 'sample',
    h1.created_at = datetime(),
    h1.meta_source = 'bootstrap';

MERGE (h2:Holon {description: 'Bootstrap holon 2'})
  ON CREATE SET
    h2.uuid = randomUUID(),
    h2.type = 'sample',
    h2.created_at = datetime(),
    h2.meta_source = 'bootstrap';

MERGE (h1)-[:RELATED_TO]->(h2);
CYPHER

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
    if kubectl exec -n "$NAMESPACE" "$pg_pod" -- psql -U "$POSTGRES_USER" -d postgres -c "SELECT 1;" >/dev/null 2>&1; then
      log "✅ PostgreSQL: ready for full migration step"
    else
      log "❌ PostgreSQL: readiness query failed"
      kubectl exec -n "$NAMESPACE" "$pg_pod" -- psql -U "$POSTGRES_USER" -l 2>&1 || true
    fi
  fi

  # MySQL
  log "🐬 Checking MySQL..."
  local my_pod; my_pod="$(first_pod_name "$MYSQL_SELECTOR")"
  if [[ -n "$my_pod" ]]; then
    if kubectl exec -n "$NAMESPACE" "$my_pod" -- sh -c "mysql -u '$MYSQL_ROOT_USER' -p'$MYSQL_ROOT_PASSWORD' seedcore -e \"SHOW TABLES LIKE 'flashbulb_incidents';\"" | grep -q flashbulb_incidents; then
      log "✅ MySQL: flashbulb_incidents table exists"
    else
      log "❌ MySQL: flashbulb_incidents table missing or query failed"
    fi
  fi

  # Neo4j
  log "🟢 Checking Neo4j..."
  local neo_pod; neo_pod="$(first_pod_name "$NEO4J_SELECTOR")"
  if [ -n "$neo_pod" ]; then 
    COUNT="$(kubectl exec -n "$NAMESPACE" "$neo_pod" -- bash -lc 'echo "MATCH (h:Holon) RETURN COUNT(h) AS count;" | /var/lib/neo4j/bin/cypher-shell -u neo4j -p password -d neo4j --format plain | tail -n 1' 2>/dev/null || echo 0)"
    if [[ "$COUNT" =~ ^[0-9]+$ ]] && [ "$COUNT" -gt 0 ]; then
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
  log "🚀 Starting SeedCore auxiliary database initialization..."
  ensure_postgresql_ready
  init_mysql
  init_neo4j
  verify_databases
  log "🎉 Auxiliary database initialization completed!"
  printf "\nNext steps:\n"
    printf "1) Run init-full-db.sh (or deploy/init-databases.sh) to apply the PostgreSQL schema\n"
  printf "2) Check logs for database errors\n"
  printf "3) Verify the application end-to-end\n"
}

main
