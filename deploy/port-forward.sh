#!/bin/bash
# Script: port-forward.sh
# Purpose: Forward all key SeedCore services for local development & debugging

set -euo pipefail

NAMESPACE=${1:-seedcore-dev}

echo "🔗 Starting port-forwards into namespace: $NAMESPACE"

# 🌐 API Service
# http://localhost:8002 → SeedCore API
kubectl -n "$NAMESPACE" port-forward svc/seedcore-api 8002:8002 &

# 📊 Ray Dashboard / Management
# http://localhost:8265 → Ray Dashboard UI
# localhost:10001 → Ray gRPC (for Ray client connections)
kubectl -n "$NAMESPACE" port-forward svc/seedcore-svc-head-svc 8265:8265 10001:10001 &

# 🧠 Ray Serve
# http://localhost:8000 → Ray Serve HTTP endpoint
kubectl -n "$NAMESPACE" port-forward svc/seedcore-svc-serve-svc 8000:8000 &

# 🗄️ Databases
# localhost:5432 → PostgreSQL
kubectl -n "$NAMESPACE" port-forward svc/postgresql 5432:5432 &
# localhost:3306 → MySQL
kubectl -n "$NAMESPACE" port-forward svc/mysql 3306:3306 &
# http://localhost:7474 → Neo4j Browser (UI)
# localhost:7687 → Neo4j Bolt (driver protocol)
kubectl -n "$NAMESPACE" port-forward svc/neo4j 7474:7474 7687:7687 &

# ⚡ Redis
# localhost:6379 → Redis (master)
kubectl -n "$NAMESPACE" port-forward svc/redis-master 6379:6379 &

# Clean exit: kill all port-forwards on Ctrl+C
trap "echo '❌ Killing port-forwards...'; kill 0" SIGINT SIGTERM EXIT

wait
