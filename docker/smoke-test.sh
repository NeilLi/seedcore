#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# SeedCore • smoke‑test.sh
# -----------------------------------------------------------------------------
# Health check script that verifies critical SeedCore components are alive:
#   • Postgres / MySQL / Neo4j containers report **healthy**
#   • Ray Serve HTTP gateway answers on /health
#   • SeedCore API answers on /health **and** /ray/status (expects ray_available)
#   • Prometheus metrics endpoint responds (quick scrape check)
#
# The script assumes the cluster is already running and only performs health validations.
# -----------------------------------------------------------------------------
set -euo pipefail

TIMEOUT=${TIMEOUT:-120}                # max seconds to wait for any resource
SLEEP=3                                # polling interval

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
log() { printf "\n%s\n" "$1"; }

wait_for_health() {
  local container=$1 label=$2 start=$(date +%s)
  while true; do
    # if container has no healthcheck fall back to running state
    status=$(docker inspect -f '{{if .State.Health}}{{ .State.Health.Status }}{{ else }}{{ .State.Status }}{{ end }}' "$container" 2>/dev/null || echo "not-found")
    case "$status" in
      healthy|running)
        echo "✅ $label healthy ($status)"; return 0 ;;
      exited|dead)
        echo "❌ $label container stopped ($status)"; docker logs --tail=50 "$container" || true; return 1 ;;
    esac
    (( $(date +%s) - start > TIMEOUT )) && { echo "❌ $label not healthy after $TIMEOUT s"; return 1; }
    sleep $SLEEP
  done
}

wait_for_url() {
  local url=$1 label=$2 start=$(date +%s)
  while ! curl -sf "$url" >/dev/null 2>&1; do
    (( $(date +%s) - start > TIMEOUT )) && { echo "❌ $label not ready after $TIMEOUT s"; return 1; }
    sleep $SLEEP
  done
  echo "✅ $label ready"
}

# -----------------------------------------------------------------------------
# Health checks (assumes cluster is already running)
# -----------------------------------------------------------------------------

# Databases --------------------------------------------------------------------
log "⏳ Checking core databases …"
wait_for_health seedcore-postgres "Postgres"
wait_for_health seedcore-mysql    "MySQL"
wait_for_health seedcore-neo4j    "Neo4j"

# Ray Serve --------------------------------------------------------------------
log "⏳ Checking Ray Serve …"
wait_for_url http://localhost:8000/health "Ray Serve /health"

# API --------------------------------------------------------------------------
log "⏳ Checking SeedCore API …"
wait_for_url http://localhost/health "SeedCore API /health"

# Critical API checks ----------------------------------------------------------
log "🧪 Validating critical API endpoints …"
if curl -sf http://localhost/ray/status | grep -q '"ray_available":true'; then
  echo "✅ /ray/status reports ray_available=true"
else
  echo "❌ /ray/status check failed"; exit 1
fi

# Energy system health check ---------------------------------------------------
log "⚡ Checking energy system readiness …"
if curl -sf http://localhost/healthz/energy | grep -q '"status":"healthy"'; then
  echo "✅ Energy system operational"
else
  echo "❌ Energy system health check failed"; exit 1
fi

# Salience scoring service health check ----------------------------------------
log "🧠 Checking salience scoring service …"
if curl -sf http://localhost/salience/health | grep -q '"status":"healthy"'; then
  echo "✅ Salience scoring service healthy"
else
  echo "❌ Salience scoring service health check failed"; exit 1
fi

# System status check (organs and agents) -------------------------------------
log "🏥 Checking system status (organs and agents) …"
if curl -sf http://localhost/system/status | grep -q '"status":"operational"'; then
  echo "✅ System operational"
else
  echo "❌ System status check failed"; exit 1
fi

# Organism status check ------------------------------------------------------
log "🧬 Checking organism status (organs and agents) …"
if curl -sf http://localhost/organism/status | grep -q '"success":true'; then
  echo "✅ Organism operational"
else
  echo "❌ Organism status check failed"; exit 1
fi

# Lightweight Prometheus scrape (non‑blocking)
curl -sf http://localhost/metrics >/dev/null && echo "✅ /metrics scraped"

log "🎉 Health check successful!" 