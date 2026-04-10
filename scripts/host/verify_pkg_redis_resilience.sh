#!/usr/bin/env bash
# Live drill: briefly remove Redis from the deployment topology and verify that
# the runtime stays healthy while PKG hot-swap degrades and recovers cleanly.
set -euo pipefail

RUNTIME_API_BASE="${SEEDCORE_RUNTIME_API_BASE:-http://127.0.0.1:8002/api/v1}"
RUNTIME_HEALTH_URL="${SEEDCORE_RUNTIME_HEALTH_URL:-http://127.0.0.1:8002/health}"
RUNTIME_READYZ_URL="${SEEDCORE_RUNTIME_READYZ_URL:-http://127.0.0.1:8002/readyz}"
REDIS_CONTAINER="${SEEDCORE_REDIS_CONTAINER:-seedcore-redis}"
API_LOG_PATH="${SEEDCORE_API_LOG_PATH:-}"
REDIS_OUTAGE_WAIT_SECONDS="${SEEDCORE_REDIS_OUTAGE_WAIT_SECONDS:-3}"
REDIS_RECOVERY_WAIT_SECONDS="${SEEDCORE_REDIS_RECOVERY_WAIT_SECONDS:-5}"

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[FAIL] missing required binary: $1" >&2
    exit 1
  fi
}

require_bin curl
require_bin docker
require_bin jq

status_code() {
  local url="$1"
  curl -sS -o /dev/null -w "%{http_code}" "$url"
}

json_get() {
  local url="$1"
  curl -fsS "$url"
}

expect_runtime_operational() {
  local phase="$1"
  local health_code ready_code status_json
  health_code="$(status_code "${RUNTIME_HEALTH_URL}")"
  ready_code="$(status_code "${RUNTIME_READYZ_URL}")"
  status_json="$(json_get "${RUNTIME_API_BASE}/pdp/hot-path/status")"

  [[ "${health_code}" == "200" ]] || {
    echo "[FAIL] ${phase}: /health returned ${health_code}" >&2
    exit 1
  }
  [[ "${ready_code}" == "200" ]] || {
    echo "[FAIL] ${phase}: /readyz returned ${ready_code}" >&2
    exit 1
  }
  jq -e '
    .runtime_ready == true and
    .authz_graph_ready == true and
    .graph_freshness_ok == true
  ' >/dev/null <<<"${status_json}" || {
    echo "[FAIL] ${phase}: hot-path status degraded unexpectedly" >&2
    echo "${status_json}" | jq .
    exit 1
  }

  echo "[PASS] ${phase}: runtime remained operational"
  echo "${status_json}" | jq '{mode, total, parity_ok, mismatched, graph_age_seconds, runtime_ready, authz_graph_ready, graph_freshness_ok, observability}'
}

redis_was_running="$(docker inspect -f '{{.State.Running}}' "${REDIS_CONTAINER}")"

cleanup() {
  if [[ "${redis_was_running}" == "true" ]]; then
    docker start "${REDIS_CONTAINER}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "== Redis resilience drill =="
echo "Runtime API: ${RUNTIME_API_BASE}"
echo "Redis container: ${REDIS_CONTAINER}"

expect_runtime_operational "baseline"

if [[ "${redis_was_running}" != "true" ]]; then
  echo "[FAIL] Redis container ${REDIS_CONTAINER} is not running before drill" >&2
  exit 1
fi

echo "Stopping ${REDIS_CONTAINER} for ${REDIS_OUTAGE_WAIT_SECONDS}s..."
docker stop "${REDIS_CONTAINER}" >/dev/null
sleep "${REDIS_OUTAGE_WAIT_SECONDS}"

expect_runtime_operational "during_redis_outage"

if [[ -n "${API_LOG_PATH}" && -f "${API_LOG_PATH}" ]]; then
  if grep -Eq "Redis listener connection error|Redis connection failed|Redis timeout error" "${API_LOG_PATH}"; then
    echo "[PASS] outage emitted Redis reconnect log lines"
  else
    echo "[WARN] no Redis reconnect log lines detected in ${API_LOG_PATH}"
  fi
fi

echo "Restarting ${REDIS_CONTAINER} and waiting ${REDIS_RECOVERY_WAIT_SECONDS}s..."
docker start "${REDIS_CONTAINER}" >/dev/null
sleep "${REDIS_RECOVERY_WAIT_SECONDS}"

expect_runtime_operational "after_redis_recovery"
trap - EXIT

echo "Redis resilience drill passed."
