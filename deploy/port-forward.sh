#!/usr/bin/env bash
# Script: port-forward.sh
# Purpose: Safely forward all key SeedCore services for local development & debugging

set -euo pipefail

NAMESPACE=${1:-seedcore-dev}

echo "🔗 Checking existing port-forwards in namespace: $NAMESPACE"

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

# Define all port-forwards
start_forward "seedcore-api" "8002:8002"
start_forward "seedcore-svc-head-svc" "8265:8265 10001:10001"
start_forward "seedcore-svc-serve-svc" "8000:8000"
start_forward "postgresql" "5432:5432"
start_forward "mysql" "3306:3306"
start_forward "neo4j" "7474:7474 7687:7687"
start_forward "redis" "6379:6379"

# Wait for core ports to be ready before returning
check_ports=(8000 8002 5432 6379)
echo "⏳ Waiting for core services to become available..."
for port in "${check_ports[@]}"; do
  until nc -z localhost "$port" >/dev/null 2>&1; do
    sleep 0.5
  done
  echo "✅ Port $port is ready"
done

# Clean exit handler
trap "echo '❌ Killing all port-forwards...'; pkill -P $$; exit 0" SIGINT SIGTERM

echo "🌐 All port-forwards established successfully."

echo "🛑 Press Ctrl+C to stop port-forwards manually."

# Keep script running to maintain background forwards
wait
