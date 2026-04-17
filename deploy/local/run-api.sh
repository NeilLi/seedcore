#!/usr/bin/env bash
# Run SeedCore API directly on macOS against the lean local Postgres/Redis stack.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

cd "${PROJECT_ROOT}"

source .venv/bin/activate

export PATH="/opt/homebrew/opt/postgresql@17/bin:${PATH}"
export PYTHONPATH="${PROJECT_ROOT}/src"
if [[ -z "${SEEDCORE_VERIFY_BIN:-}" ]]; then
  if [[ -x "${PROJECT_ROOT}/rust/target/release/seedcore-verify" ]]; then
    export SEEDCORE_VERIFY_BIN="${PROJECT_ROOT}/rust/target/release/seedcore-verify"
  elif [[ -x "${PROJECT_ROOT}/rust/target/debug/seedcore-verify" ]]; then
    export SEEDCORE_VERIFY_BIN="${PROJECT_ROOT}/rust/target/debug/seedcore-verify"
  fi
fi

export PG_DSN="${PG_DSN:-postgresql://ningli@127.0.0.1:5432/seedcore}"
export PG_DSN_ASYNC="${PG_DSN_ASYNC:-postgresql+asyncpg://ningli@127.0.0.1:5432/seedcore}"
export REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
export REDIS_PORT="${REDIS_PORT:-6379}"
export NEO4J_HOST="${NEO4J_HOST:-127.0.0.1}"
export NEO4J_BOLT_PORT="${NEO4J_BOLT_PORT:-7687}"
export NEO4J_HTTP_PORT="${NEO4J_HTTP_PORT:-7474}"
export NEO4J_USER="${NEO4J_USER:-neo4j}"
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-password}"
export NEO4J_BOLT_URL="${NEO4J_BOLT_URL:-bolt://${NEO4J_HOST}:${NEO4J_BOLT_PORT}}"
export NEO4J_HTTP_URL="${NEO4J_HTTP_URL:-http://${NEO4J_HOST}:${NEO4J_HTTP_PORT}}"
export NEO4J_URI="${NEO4J_URI:-${NEO4J_BOLT_URL}}"
export POSTGRES_POOL_SIZE="${POSTGRES_POOL_SIZE:-5}"
export POSTGRES_MAX_OVERFLOW="${POSTGRES_MAX_OVERFLOW:-5}"
export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-8002}"
# Align hot-path status/metrics labels with k8s (`kubernetes`) and Ray (`ray`) deploys.
export SEEDCORE_HOT_PATH_DEPLOYMENT_ROLE="${SEEDCORE_HOT_PATH_DEPLOYMENT_ROLE:-host}"
export SEEDCORE_EXECUTION_TOKEN_TTL_SECONDS="${SEEDCORE_EXECUTION_TOKEN_TTL_SECONDS:-900}"

exec uvicorn seedcore.main:app --host "${HOST}" --port "${PORT}"
