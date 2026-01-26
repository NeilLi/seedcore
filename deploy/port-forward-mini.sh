#!/usr/bin/env bash
# Script: port-forward-mini.sh
# Purpose: Forward PostgreSQL and Redis ports for local development

set -euo pipefail

NAMESPACE=${1:-seedcore-dev}

echo "🔗 Starting port-forwards for PostgreSQL and Redis in namespace: $NAMESPACE"

# Function to check if a port is already listening locally
is_port_forwarded() {
  lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

# Function to start a port-forward if not already active
start_forward() {
  local svc=$1
  local ports=$2

  for port_pair in $ports; do
    local local_port=${port_pair%%:*}
    if is_port_forwarded "$local_port"; then
      echo "⚙️  Port $local_port already forwarded, skipping $svc"
    else
      echo "🚀 Forwarding $svc ($port_pair)"
      kubectl -n "$NAMESPACE" port-forward "svc/$svc" $port_pair >/dev/null 2>&1 &
      sleep 1
    fi
  done
}

# Start port-forwards for PostgreSQL and Redis
start_forward "postgresql" "5432:5432"
start_forward "redis" "6379:6379"

# Wait for ports to be ready before returning
check_ports=(5432 6379)
echo "⏳ Waiting for services to become available..."
for port in "${check_ports[@]}"; do
  until nc -z localhost "$port" >/dev/null 2>&1; do
    sleep 0.5
  done
  echo "✅ Port $port is ready"
done

# Clean exit handler
trap "echo ''; echo '❌ Stopping all port-forwards...'; pkill -P $$ 2>/dev/null || true; exit 0" SIGINT SIGTERM

echo "🌐 All port-forwards established successfully."
echo "🛑 Press Ctrl+C to stop port-forwards."

# Keep script running to maintain background forwards
wait
