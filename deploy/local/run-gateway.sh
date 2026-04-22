#!/usr/bin/env bash
# Run the dedicated SeedCore Agent Action Gateway service on macOS against the
# lean local Postgres/Redis stack.  Mirrors deploy/local/run-api.sh but only
# mounts the gateway surface (`/api/v1/agent-actions/*`).

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

cd "${PROJECT_ROOT}"

source .venv/bin/activate
source "${SCRIPT_DIR}/host-env.sh"

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
export POSTGRES_POOL_SIZE="${POSTGRES_POOL_SIZE:-5}"
export POSTGRES_MAX_OVERFLOW="${POSTGRES_MAX_OVERFLOW:-5}"

# Gateway-specific defaults
export GATEWAY_HOST="${GATEWAY_HOST:-${HOST:-127.0.0.1}}"
export GATEWAY_PORT="${GATEWAY_PORT:-8022}"
# The dedicated process is the single source of truth for the gateway surface
# once it is running.  Keep this off when you also run the monolith locally to
# avoid double-registering `/api/v1/agent-actions/*`.
export SEEDCORE_MAIN_API_MOUNT_AGENT_ACTION_GATEWAY="${SEEDCORE_MAIN_API_MOUNT_AGENT_ACTION_GATEWAY:-false}"
# Align hot-path status/metrics labels with k8s (`kubernetes`) and Ray (`ray`) deploys.
export SEEDCORE_HOT_PATH_DEPLOYMENT_ROLE="${SEEDCORE_HOT_PATH_DEPLOYMENT_ROLE:-host}"
export SEEDCORE_EXECUTION_TOKEN_TTL_SECONDS="${SEEDCORE_EXECUTION_TOKEN_TTL_SECONDS:-900}"

exec uvicorn seedcore.gateway_service.main:app --host "${GATEWAY_HOST}" --port "${GATEWAY_PORT}"
