#!/usr/bin/env bash
# Live drill: verify that Kafka-gated readiness fails closed on broker loss while
# the API health endpoint stays up, then recovers once the broker returns.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

PORT="${PORT:-8012}"
HOST="${HOST:-127.0.0.1}"
HEALTH_URL="http://${HOST}:${PORT}/health"
READYZ_URL="http://${HOST}:${PORT}/readyz"
KAFKA_CONTAINER="${SEEDCORE_KAFKA_CONTAINER:-seedcore-kafka}"
COMPOSE_FILE="${SEEDCORE_KAFKA_COMPOSE_FILE:-${ROOT}/deploy/local/docker-compose.kafka.yml}"
API_LOG_PATH="${SEEDCORE_KAFKA_GATE_API_LOG:-${ROOT}/.local-runtime/api-kafka-readyz-drill.log}"
API_PID_PATH="${SEEDCORE_KAFKA_GATE_API_PID:-${ROOT}/.local-runtime/api-kafka-readyz-drill.pid}"
KAFKA_BOOTSTRAP_SERVERS="${KAFKA_BOOTSTRAP_SERVERS:-127.0.0.1:9092}"
OUTAGE_WAIT_SECONDS="${SEEDCORE_KAFKA_OUTAGE_WAIT_SECONDS:-4}"
RECOVERY_WAIT_SECONDS="${SEEDCORE_KAFKA_RECOVERY_WAIT_SECONDS:-6}"
EXISTING_API_PORT="${SEEDCORE_EXISTING_API_PORT:-8002}"

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[FAIL] missing required binary: $1" >&2
    exit 1
  fi
}

require_bin curl
require_bin docker
require_bin jq

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "[FAIL] missing docker compose support (need 'docker compose' or 'docker-compose')" >&2
  exit 1
fi

mkdir -p "$(dirname "${API_LOG_PATH}")"

status_code() {
  local url="$1"
  curl -sS -o /dev/null -w "%{http_code}" "$url"
}

wait_for_status() {
  local url="$1"
  local expected="$2"
  local label="$3"
  local attempts="${4:-40}"
  local sleep_seconds="${5:-0.5}"
  local code=""

  for ((i=1; i<=attempts; i++)); do
    if [[ -f "${API_PID_PATH}" ]]; then
      local pid
      pid="$(cat "${API_PID_PATH}" 2>/dev/null || true)"
      if [[ -n "${pid}" ]] && ! kill -0 "${pid}" >/dev/null 2>&1; then
        echo "[FAIL] ${label}: drill API exited before reaching HTTP ${expected}" >&2
        tail -n 80 "${API_LOG_PATH}" >&2 || true
        return 1
      fi
    fi
    code="$(status_code "${url}" || true)"
    if [[ "${code}" == "${expected}" ]]; then
      return 0
    fi
    sleep "${sleep_seconds}"
  done

  echo "[FAIL] ${label}: expected HTTP ${expected}, got ${code:-none}" >&2
  tail -n 80 "${API_LOG_PATH}" >&2 || true
  return 1
}

read_env_value_from_pid() {
  local pid="$1"
  local key="$2"
  tr '\0' '\n' <"/proc/${pid}/environ" 2>/dev/null | awk -F= -v target="${key}" '$1 == target { sub($1 "=", ""); print; exit }'
}

inherit_existing_api_env() {
  local pid="$1"
  local keys=(
    PG_DSN
    PG_DSN_ASYNC
    SEEDCORE_PG_DSN
    POSTGRES_HOST
    POSTGRES_PORT
    POSTGRES_DB
    POSTGRES_USER
    POSTGRES_PASSWORD
    POSTGRES_POOL_SIZE
    POSTGRES_MAX_OVERFLOW
    REDIS_HOST
    REDIS_PORT
    REDIS_DB
    REDIS_URL
    NEO4J_HOST
    NEO4J_BOLT_PORT
    NEO4J_HTTP_PORT
    NEO4J_USER
    NEO4J_PASSWORD
    NEO4J_URI
    NEO4J_BOLT_URL
    NEO4J_HTTP_URL
    SEEDCORE_VERIFY_BIN
    SEEDCORE_MOCK_EXTERNAL_APIS
    SEEDCORE_MOCK_GEMINI_API
    GOOGLE_API_MOCK
    GEMINI_API_MOCK
    SYNOPSIS_EMBEDDING_MOCK
    NIM_RETRIEVAL_MOCK
  )

  for key in "${keys[@]}"; do
    local value
    value="$(read_env_value_from_pid "${pid}" "${key}")"
    if [[ -n "${value}" ]]; then
      export "${key}=${value}"
    fi
  done
}

resolve_existing_api_pid() {
  local port="$1"
  local pid
  while read -r pid; do
    [[ -n "${pid}" ]] || continue
    if [[ -n "$(read_env_value_from_pid "${pid}" "PG_DSN")" || -n "$(read_env_value_from_pid "${pid}" "PG_DSN_ASYNC")" ]]; then
      echo "${pid}"
      return 0
    fi
  done < <(ps -eo pid=,args= | awk -v port="${port}" '
    $0 ~ /seedcore.main:app/ && $0 ~ ("--port " port) { print $1 }
  ')
  return 1
}

cleanup() {
  if [[ -f "${API_PID_PATH}" ]]; then
    local pid
    pid="$(cat "${API_PID_PATH}" 2>/dev/null || true)"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1; then
      kill "${pid}" >/dev/null 2>&1 || true
      wait "${pid}" 2>/dev/null || true
    fi
    rm -f "${API_PID_PATH}"
  fi

  if [[ "${kafka_started_by_script:-0}" == "1" ]]; then
    "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" down >/dev/null 2>&1 || true
  elif [[ "${kafka_was_running:-false}" != "true" ]]; then
    docker stop "${KAFKA_CONTAINER}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "== Kafka readyz gate drill =="
echo "Compose file: ${COMPOSE_FILE}"
echo "Kafka bootstrap: ${KAFKA_BOOTSTRAP_SERVERS}"
echo "Drill API: http://${HOST}:${PORT}"

source "${ROOT}/deploy/local/host-env.sh"

existing_api_pid="$(resolve_existing_api_pid "${EXISTING_API_PORT}" || true)"
if [[ -n "${existing_api_pid}" ]]; then
  inherit_existing_api_env "${existing_api_pid}"
fi

kafka_was_running="false"
if docker inspect "${KAFKA_CONTAINER}" >/dev/null 2>&1; then
  kafka_was_running="$(docker inspect -f '{{.State.Running}}' "${KAFKA_CONTAINER}")"
fi

kafka_started_by_script=0
if [[ "${kafka_was_running}" != "true" ]]; then
  "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" up -d >/dev/null
  kafka_started_by_script=1
fi

SEEDCORE_KAFKA_READYZ_CHECK=1 \
KAFKA_BOOTSTRAP_SERVERS="${KAFKA_BOOTSTRAP_SERVERS}" \
HOST="${HOST}" \
PORT="${PORT}" \
"${ROOT}/.venv/bin/uvicorn" seedcore.main:app --host "${HOST}" --port "${PORT}" \
  >"${API_LOG_PATH}" 2>&1 &
echo $! > "${API_PID_PATH}"

wait_for_status "${HEALTH_URL}" "200" "api startup health"
wait_for_status "${READYZ_URL}" "200" "baseline readyz"
echo "[PASS] baseline: /health=200 and /readyz=200 with Kafka reachable"

docker stop "${KAFKA_CONTAINER}" >/dev/null
sleep "${OUTAGE_WAIT_SECONDS}"

wait_for_status "${HEALTH_URL}" "200" "outage health"
wait_for_status "${READYZ_URL}" "503" "outage readyz"
echo "[PASS] outage: /health stayed 200 while /readyz failed closed on Kafka"

docker start "${KAFKA_CONTAINER}" >/dev/null
sleep "${RECOVERY_WAIT_SECONDS}"

wait_for_status "${HEALTH_URL}" "200" "recovery health"
wait_for_status "${READYZ_URL}" "200" "recovery readyz"
echo "[PASS] recovery: /readyz returned to 200 after Kafka recovered"

echo "Kafka readyz gate drill passed."
