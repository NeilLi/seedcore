#!/usr/bin/env bash
# Live drill: briefly remove Redis from the deployment topology and verify that
# the runtime stays healthy while PKG hot-swap degrades and recovers cleanly.
set -euo pipefail

RUNTIME_API_BASE="${SEEDCORE_RUNTIME_API_BASE:-http://127.0.0.1:8002/api/v1}"
RUNTIME_HEALTH_URL="${SEEDCORE_RUNTIME_HEALTH_URL:-http://127.0.0.1:8002/health}"
RUNTIME_READYZ_URL="${SEEDCORE_RUNTIME_READYZ_URL:-http://127.0.0.1:8002/readyz}"
REDIS_CONTAINER="${SEEDCORE_REDIS_CONTAINER:-seedcore-redis}"
REDIS_DRILL_MODE="${SEEDCORE_REDIS_DRILL_MODE:-auto}"
REDIS_KUBE_NAMESPACE="${SEEDCORE_REDIS_KUBE_NAMESPACE:-seedcore-dev}"
REDIS_KUBE_DEPLOYMENT="${SEEDCORE_REDIS_KUBE_DEPLOYMENT:-redis}"
API_LOG_PATH="${SEEDCORE_API_LOG_PATH:-}"
REDIS_OUTAGE_WAIT_SECONDS="${SEEDCORE_REDIS_OUTAGE_WAIT_SECONDS:-3}"
REDIS_RECOVERY_WAIT_SECONDS="${SEEDCORE_REDIS_RECOVERY_WAIT_SECONDS:-5}"

ACTIVE_REDIS_MODE=""
redis_was_running="false"
redis_kube_original_replicas=""

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[FAIL] missing required binary: $1" >&2
    exit 1
  fi
}

require_bin curl
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

resolve_redis_mode() {
  local requested="$1"
  case "${requested}" in
    docker|kube)
      ACTIVE_REDIS_MODE="${requested}"
      return 0
      ;;
    auto)
      if command -v kubectl >/dev/null 2>&1; then
        if kubectl -n "${REDIS_KUBE_NAMESPACE}" get deployment "${REDIS_KUBE_DEPLOYMENT}" >/dev/null 2>&1; then
          ACTIVE_REDIS_MODE="kube"
          return 0
        fi
      fi
      if command -v docker >/dev/null 2>&1; then
        if docker inspect "${REDIS_CONTAINER}" >/dev/null 2>&1; then
          ACTIVE_REDIS_MODE="docker"
          return 0
        fi
      fi
      echo "[FAIL] could not resolve Redis drill mode in auto mode" >&2
      echo "       checked deployment ${REDIS_KUBE_NAMESPACE}/${REDIS_KUBE_DEPLOYMENT} and container ${REDIS_CONTAINER}" >&2
      exit 1
      ;;
    *)
      echo "[FAIL] unsupported SEEDCORE_REDIS_DRILL_MODE=${requested}" >&2
      exit 1
      ;;
  esac
}

prepare_redis_target() {
  if [[ "${ACTIVE_REDIS_MODE}" == "docker" ]]; then
    require_bin docker
    redis_was_running="$(docker inspect -f '{{.State.Running}}' "${REDIS_CONTAINER}")"
    if [[ "${redis_was_running}" != "true" ]]; then
      echo "[FAIL] Redis container ${REDIS_CONTAINER} is not running before drill" >&2
      exit 1
    fi
    return 0
  fi

  require_bin kubectl
  redis_kube_original_replicas="$(
    kubectl -n "${REDIS_KUBE_NAMESPACE}" get deployment "${REDIS_KUBE_DEPLOYMENT}" -o jsonpath='{.spec.replicas}'
  )"
  if [[ -z "${redis_kube_original_replicas}" ]]; then
    echo "[FAIL] could not resolve current replicas for ${REDIS_KUBE_NAMESPACE}/${REDIS_KUBE_DEPLOYMENT}" >&2
    exit 1
  fi
  if [[ "${redis_kube_original_replicas}" == "0" ]]; then
    echo "[FAIL] Redis deployment ${REDIS_KUBE_NAMESPACE}/${REDIS_KUBE_DEPLOYMENT} is already scaled to 0 before drill" >&2
    exit 1
  fi
}

redis_outage_start() {
  if [[ "${ACTIVE_REDIS_MODE}" == "docker" ]]; then
    echo "Stopping ${REDIS_CONTAINER} for ${REDIS_OUTAGE_WAIT_SECONDS}s..."
    docker stop "${REDIS_CONTAINER}" >/dev/null
    sleep "${REDIS_OUTAGE_WAIT_SECONDS}"
    return 0
  fi

  echo "Scaling ${REDIS_KUBE_NAMESPACE}/${REDIS_KUBE_DEPLOYMENT} to 0 for ${REDIS_OUTAGE_WAIT_SECONDS}s..."
  kubectl -n "${REDIS_KUBE_NAMESPACE}" scale deployment "${REDIS_KUBE_DEPLOYMENT}" --replicas=0 >/dev/null
  kubectl -n "${REDIS_KUBE_NAMESPACE}" rollout status deployment "${REDIS_KUBE_DEPLOYMENT}" --timeout=90s >/dev/null || true
  sleep "${REDIS_OUTAGE_WAIT_SECONDS}"
}

redis_outage_stop() {
  if [[ "${ACTIVE_REDIS_MODE}" == "docker" ]]; then
    echo "Restarting ${REDIS_CONTAINER} and waiting ${REDIS_RECOVERY_WAIT_SECONDS}s..."
    docker start "${REDIS_CONTAINER}" >/dev/null
    sleep "${REDIS_RECOVERY_WAIT_SECONDS}"
    return 0
  fi

  echo "Restoring ${REDIS_KUBE_NAMESPACE}/${REDIS_KUBE_DEPLOYMENT} replicas=${redis_kube_original_replicas} and waiting ${REDIS_RECOVERY_WAIT_SECONDS}s..."
  kubectl -n "${REDIS_KUBE_NAMESPACE}" scale deployment "${REDIS_KUBE_DEPLOYMENT}" --replicas="${redis_kube_original_replicas}" >/dev/null
  kubectl -n "${REDIS_KUBE_NAMESPACE}" rollout status deployment "${REDIS_KUBE_DEPLOYMENT}" --timeout=180s >/dev/null
  sleep "${REDIS_RECOVERY_WAIT_SECONDS}"
}

cleanup() {
  if [[ "${ACTIVE_REDIS_MODE}" == "docker" && "${redis_was_running}" == "true" ]]; then
    docker start "${REDIS_CONTAINER}" >/dev/null 2>&1 || true
  fi
  if [[ "${ACTIVE_REDIS_MODE}" == "kube" && -n "${redis_kube_original_replicas}" ]]; then
    kubectl -n "${REDIS_KUBE_NAMESPACE}" scale deployment "${REDIS_KUBE_DEPLOYMENT}" --replicas="${redis_kube_original_replicas}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

resolve_redis_mode "${REDIS_DRILL_MODE}"
prepare_redis_target

echo "== Redis resilience drill =="
echo "Runtime API: ${RUNTIME_API_BASE}"
if [[ "${ACTIVE_REDIS_MODE}" == "docker" ]]; then
  echo "Redis target mode: docker (${REDIS_CONTAINER})"
else
  echo "Redis target mode: kube (${REDIS_KUBE_NAMESPACE}/${REDIS_KUBE_DEPLOYMENT})"
fi

expect_runtime_operational "baseline"
redis_outage_start

expect_runtime_operational "during_redis_outage"

if [[ -n "${API_LOG_PATH}" && -f "${API_LOG_PATH}" ]]; then
  if grep -Eq "Redis listener connection error|Redis connection failed|Redis timeout error" "${API_LOG_PATH}"; then
    echo "[PASS] outage emitted Redis reconnect log lines"
  else
    echo "[WARN] no Redis reconnect log lines detected in ${API_LOG_PATH}"
  fi
fi

redis_outage_stop

expect_runtime_operational "after_redis_recovery"
trap - EXIT

echo "Redis resilience drill passed."
