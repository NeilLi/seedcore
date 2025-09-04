#!/usr/bin/env bash
# SeedCore development environment variables
# Usage: source ./env.host.sh

### Ray cluster connection
export RAY_ADDRESS="ray://127.0.0.1:10001"
export RAY_NAMESPACE="seedcore-dev"

### Postgres connection
export SEEDCORE_PG_DSN="postgresql://postgres:postgres@localhost:5432/seedcore"

### Orchestrator (Serve app, internal)
export ORCH_URL="http://127.0.0.1:8000/orchestrator"
export ORCH_PATHS="/tasks"

# Adjust if your gateway differs
# export ORCH_URL="http://127.0.0.1:8000/orchestrator"

# Orchestrator → per-request budget for cognitive calls
export COGNITIVE_TIMEOUT_S=12
# Orchestrator client default; keep small but > COGNITIVE_TIMEOUT_S
export ORCH_HTTP_TIMEOUT=15
# Make memory synthesis optional (or off)
export SEEDCORE_FACTS_ENABLED=false
export ENABLE_MEMORY_SYNTHESIS=false   # if you added this flag


### SeedCore API (FastAPI front door)
export SEEDCORE_API_URL="http://127.0.0.1:8002"
export SEEDCORE_API_TIMEOUT=5.0

### Dispatcher expectations
export EXPECT_DISPATCHERS=2
export EXPECT_GRAPH_DISPATCHERS=1
export STRICT_GRAPH_DISPATCHERS=false  # allow fewer than expected
export VERIFY_GRAPH_TASK=true

### OCPS & Cognitive escalation
export OCPS_DRIFT_THRESHOLD=0.5
export COGNITIVE_TIMEOUT_S=8.0
export COGNITIVE_MAX_INFLIGHT=64
export MAX_PLAN_STEPS=16

### Performance & SLOs
export FAST_PATH_LATENCY_SLO_MS=1000
export RAY_SERVE_MAX_QUEUE_LENGTH=2000
export RAY_SERVE_QUEUE_LENGTH_RESPONSE_DEADLINE_S=2.0

echo "[seedcore-dev] Environment variables set."

