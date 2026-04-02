#!/usr/bin/env bash
# Shared localhost-friendly environment for experimental SeedCore host mode.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
DEFAULT_ENV_FILE="${PROJECT_ROOT}/docker/.env"
if [[ -n "${ENV_FILE:-}" && -f "${ENV_FILE}" ]]; then
  ENV_FILE="${ENV_FILE}"
else
  ENV_FILE="${DEFAULT_ENV_FILE}"
fi

# Import only model/provider credentials from docker/.env.
# Full docker/.env loading is unsafe for host mode because it contains
# container-oriented hosts/namespaces like `postgresql`, `redis`, and
# cluster-specific Ray settings.
if [[ -f "${ENV_FILE}" ]]; then
  import_env_key() {
    local env_key="$1"
    local env_value=""
    [[ -z "${!env_key:-}" ]] || return 0
    env_value="$(grep -E "^${env_key}=" "${ENV_FILE}" | tail -n1 | cut -d= -f2- || true)"
    [[ -n "${env_value}" ]] || return 0
    if [[ "${env_value}" == \"*\" && "${env_value}" == *\" ]]; then
      env_value="${env_value:1:${#env_value}-2}"
    elif [[ "${env_value}" == \'*\' && "${env_value}" == *\' ]]; then
      env_value="${env_value:1:${#env_value}-2}"
    fi
    export "${env_key}=${env_value}"
  }

  for env_key in \
    OPENAI_API_KEY \
    ANTHROPIC_API_KEY \
    GOOGLE_API_KEY \
    GOOGLE_VERTEX_MODEL \
    GOOGLE_API_TIMEOUT_S \
    GOOGLE_PLANNER_TEMPERATURE; do
    import_env_key "${env_key}"
  done

  while IFS='=' read -r env_key _; do
    [[ "${env_key}" == GOOGLE_LLM_* ]] || continue
    import_env_key "${env_key}"
  done < <(grep -E '^GOOGLE_LLM_[A-Z0-9_]*=' "${ENV_FILE}" || true)
fi

looks_like_placeholder_openai_key() {
  local key="${1:-}"
  [[ -z "${key}" ]] && return 0
  [[ "${key}" == *"REPLACE_ME"* ]] && return 0
  [[ "${key}" == *"YOUR_"* ]] && return 0
  [[ "${key}" == *"HERE"* ]] && return 0
  [[ "${key}" == *"example"* ]] && return 0
  return 1
}

export PROJECT_ROOT
export PYTHONPATH="${PROJECT_ROOT}/src"
export PATH="${PROJECT_ROOT}/.venv/bin:/opt/homebrew/opt/postgresql@17/bin:${PATH}"
export SEEDCORE_APP_ROOT="${SEEDCORE_APP_ROOT:-${PROJECT_ROOT}}"
export SEEDCORE_CONFIG_DIR="${SEEDCORE_CONFIG_DIR:-${PROJECT_ROOT}/config}"
export SEEDCORE_DATA_DIR="${SEEDCORE_DATA_DIR:-${PROJECT_ROOT}/data}"
export SEEDCORE_OPT_DIR="${SEEDCORE_OPT_DIR:-${PROJECT_ROOT}/opt}"

export POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export POSTGRES_DB="${POSTGRES_DB:-seedcore}"
export POSTGRES_USER="${POSTGRES_USER:-ningli}"
export PG_DSN="${PG_DSN:-postgresql://${POSTGRES_USER}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}}"
export PG_DSN_ASYNC="${PG_DSN_ASYNC:-postgresql+asyncpg://${POSTGRES_USER}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}}"
export SEEDCORE_PG_DSN="${SEEDCORE_PG_DSN:-${PG_DSN}}"

export REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
export REDIS_PORT="${REDIS_PORT:-6379}"
export REDIS_DB="${REDIS_DB:-0}"
export REDIS_URL="${REDIS_URL:-redis://${REDIS_HOST}:${REDIS_PORT}/${REDIS_DB}}"

export RAY_HOST="${RAY_HOST:-127.0.0.1}"
export RAY_GCS_PORT="${RAY_GCS_PORT:-26079}"
export RAY_CLIENT_PORT="${RAY_CLIENT_PORT:-23001}"
export RAY_DASHBOARD_PORT="${RAY_DASHBOARD_PORT:-8265}"
export RAY_ADDRESS="${RAY_ADDRESS:-${RAY_HOST}:${RAY_GCS_PORT}}"
export RAY_CLIENT_ADDRESS="${RAY_CLIENT_ADDRESS:-ray://${RAY_HOST}:${RAY_CLIENT_PORT}}"
export RAY_STATUS_ADDRESS="${RAY_STATUS_ADDRESS:-${RAY_HOST}:${RAY_GCS_PORT}}"
export RAY_NAMESPACE="${RAY_NAMESPACE:-seedcore-local}"
export SEEDCORE_NS="${SEEDCORE_NS:-${RAY_NAMESPACE}}"
export SERVE_GATEWAY="${SERVE_GATEWAY:-http://${RAY_HOST}:8000}"

export SEEDCORE_API_URL="${SEEDCORE_API_URL:-http://127.0.0.1:8002}"
export SEEDCORE_HOT_PATH_DEPLOYMENT_ROLE="${SEEDCORE_HOT_PATH_DEPLOYMENT_ROLE:-host}"
export HAL_BASE_URL="${HAL_BASE_URL:-http://127.0.0.1:8003}"
export COG_BASE_URL="${COG_BASE_URL:-${SERVE_GATEWAY}/cognitive}"
export ORG_BASE_PATH="${ORG_BASE_PATH:-/organism}"
export COG_BASE_PATH="${COG_BASE_PATH:-/cognitive}"
export SERVE_BASE_PATH="${SERVE_BASE_PATH:-/ml}"

export POSTGRES_POOL_SIZE="${POSTGRES_POOL_SIZE:-5}"
export POSTGRES_MAX_OVERFLOW="${POSTGRES_MAX_OVERFLOW:-5}"

export ENABLE_ML_SERVICE="${ENABLE_ML_SERVICE:-false}"
export DGL_GRAPHBOLT_SKIP="${DGL_GRAPHBOLT_SKIP:-1}"
export RAY_USAGE_STATS_ENABLED="${RAY_USAGE_STATS_ENABLED:-0}"
export SEEDCORE_SKIP_EAGER_RAY="${SEEDCORE_SKIP_EAGER_RAY:-1}"
export SEEDCORE_DISPATCHER_MAIN_INTERVAL_S="${SEEDCORE_DISPATCHER_MAIN_INTERVAL_S:-0.05}"

# External API mock controls (safe local defaults).
# Set to 1/true/yes/on to use deterministic non-network mock behavior.
export SEEDCORE_MOCK_EXTERNAL_APIS="${SEEDCORE_MOCK_EXTERNAL_APIS:-0}"
export SEEDCORE_MOCK_GEMINI_API="${SEEDCORE_MOCK_GEMINI_API:-0}"
export GOOGLE_API_MOCK="${GOOGLE_API_MOCK:-0}"
export GEMINI_API_MOCK="${GEMINI_API_MOCK:-0}"
export SYNOPSIS_EMBEDDING_MOCK="${SYNOPSIS_EMBEDDING_MOCK:-0}"
export NIM_RETRIEVAL_MOCK="${NIM_RETRIEVAL_MOCK:-0}"

# Local host-mode should prefer a working provider over container defaults.
# If Gemini credentials are present but OpenAI is unset or clearly placeholder-only,
# switch local cognitive defaults to Google so both DSPy and direct fast-query paths
# use the same functioning provider.
if [[ -n "${GOOGLE_API_KEY:-}" ]] && looks_like_placeholder_openai_key "${OPENAI_API_KEY:-}"; then
  export LLM_PROVIDER_FAST="${LLM_PROVIDER_FAST:-google}"
  export LLM_PROVIDER_DEEP="${LLM_PROVIDER_DEEP:-google}"
  export LLM_PROVIDER="${LLM_PROVIDER:-google}"
  export LLM_PROVIDERS="${LLM_PROVIDERS:-google,anthropic,nim}"
  export GOOGLE_LLM_FAST="${GOOGLE_LLM_FAST:-gemini-flash-latest}"
  export GOOGLE_LLM_DEEP="${GOOGLE_LLM_DEEP:-gemini-pro-latest}"
fi
